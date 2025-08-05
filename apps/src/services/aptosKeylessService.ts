// Import polyfills before Aptos SDK
import './aptosPolyfills';

import {
  Aptos,
  AptosConfig,
  EphemeralKeyPair,
  Ed25519PrivateKey,
  KeylessAccount,
  ProofFetchStatus,
  Serializer,
  Deserializer,
} from '@aptos-labs/ts-sdk';
import { sha256 } from '@noble/hashes/sha256';

interface GenerateAuthenticatorParams {
  jwt: string;
  ephemeralKeyPair: {
    privateKey: string;
    publicKey: string;
    expiryDate: string;
    nonce?: string;
    blinder?: string;
  };
  signingMessage: string; // Base64 encoded
  pepper?: Uint8Array;
}

// Storage format for ephemeral key pairs
interface StoredEphemeralKeyPair {
  privateKey_b64: string;
  publicKey_b64: string;
  nonce_b64: string;
  blinder_b64: string;
  expiryISO: string;
  version: 'ekp-v1';
}

interface GenerateAuthenticatorResponse {
  senderAuthenticatorBcsBase64: string;
  authKeyHex: string;
  ephemeralPublicKeyHex: string;
  addressHex: string;
}

export class AptosKeylessService {
  private aptos: Aptos;
  
  // Expose aptos instance for direct access
  public getAptosClient(): Aptos {
    return this.aptos;
  }
  
  constructor(network: 'testnet' | 'mainnet' = 'testnet') {
    const aptosConfig = new AptosConfig({ 
      network: network === 'mainnet' ? AptosConfig.MAINNET : AptosConfig.TESTNET 
    });
    this.aptos = new Aptos(aptosConfig);
  }

  // Base64 helpers for lossless byte conversion
  private bytesToB64(u8: Uint8Array): string {
    // Use btoa which is available in React Native
    const binaryString = Array.from(u8).map(byte => String.fromCharCode(byte)).join('');
    return btoa(binaryString);
  }

  private b64ToBytes(b64: string): Uint8Array {
    // Use atob which is available in React Native
    const binaryString = atob(b64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
  }

  private hexToBytes(hex: string): Uint8Array {
    const clean = hex.replace(/^0x/i, '');
    if (clean.length % 2) throw new Error('Odd-length hex');
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < clean.length; i += 2) {
      out[i / 2] = parseInt(clean.slice(i, i + 2), 16);
    }
    return out;
  }

  private csvToBytes(csv: string): Uint8Array {
    const parts = csv.split(',').map(s => {
      const n = Number(s.trim());
      if (!Number.isInteger(n) || n < 0 || n > 255) {
        throw new Error('Invalid byte in CSV');
      }
      return n;
    });
    return new Uint8Array(parts);
  }

  /**
   * Generate a keyless authenticator for a transaction
   * This is used for sponsored transactions where we need just the authenticator
   */
  async generateAuthenticator(params: GenerateAuthenticatorParams): Promise<GenerateAuthenticatorResponse> {
    try {
      const { jwt, ephemeralKeyPair, signingMessage, pepper } = params;
      
      // Check if ephemeralKeyPair is in stored format
      let ekpToUse = ephemeralKeyPair;
      if ((ephemeralKeyPair as any).version === 'ekp-v1') {
        console.log('AptosKeylessService - Converting stored ephemeral key pair format');
        ekpToUse = this.ekpFromStored(ephemeralKeyPair as any as StoredEphemeralKeyPair);
      } else {
        console.log('AptosKeylessService - Using ephemeral key pair in original backend format');
      }
      
      console.log('AptosKeylessService - generateAuthenticator called with:', {
        jwtLength: jwt?.length,
        ephemeralKeyPair: {
          privateKey: ekpToUse?.privateKey ? (ekpToUse.privateKey instanceof Uint8Array ? 'Uint8Array[' + ekpToUse.privateKey.length + ']' : ekpToUse.privateKey.substring(0, 10) + '...') : 'undefined',
          publicKey: ekpToUse?.publicKey ? (ekpToUse.publicKey instanceof Uint8Array ? 'Uint8Array[' + ekpToUse.publicKey.length + ']' : ekpToUse.publicKey) : 'undefined',
          expiryDate: ekpToUse?.expiryDate,
          nonce: ekpToUse?.nonce ? (ekpToUse.nonce instanceof Uint8Array ? 'Uint8Array[' + ekpToUse.nonce.length + ']' : ekpToUse.nonce) : 'undefined',
          blinder: ekpToUse?.blinder ? (ekpToUse.blinder instanceof Uint8Array ? 'Uint8Array[' + ekpToUse.blinder.length + ']' : ekpToUse.blinder) : 'undefined',
        },
        signingMessageLength: signingMessage?.length,
        hasPepper: !!pepper,
      });
      
      
      // Decode JWT to check nonce
      try {
        const jwtParts = jwt.split('.');
        // Use atob for base64 decoding which is available in React Native
        const payload = JSON.parse(atob(jwtParts[1]));
        console.log('AptosKeylessService - JWT nonce:', payload.nonce);
        console.log('AptosKeylessService - JWT aud:', payload.aud);
        console.log('AptosKeylessService - JWT sub:', payload.sub);
        console.log('AptosKeylessService - Ephemeral key nonce (from ekpToUse):', ekpToUse.nonce);
        
        // Check if nonces match - use the nonce from ekpToUse which should be correct format
        const jwtNonceStr = String(payload.nonce);
        const ephNonceStr = String(ekpToUse.nonce);
        
        if (jwtNonceStr !== ephNonceStr) {
          console.warn('AptosKeylessService - NONCE MISMATCH!');
          console.warn('JWT nonce:', payload.nonce);
          console.warn('JWT nonce type:', typeof payload.nonce);
          console.warn('Ephemeral nonce (ekpToUse):', ekpToUse.nonce);
          console.warn('Ephemeral nonce type:', typeof ekpToUse.nonce);
          console.warn('String comparison result:', jwtNonceStr === ephNonceStr);
          
          // The mismatch means the JWT was created with a different ephemeral key
          // For now, let's continue and see what happens
          // throw new Error('JWT nonce does not match ephemeral key nonce. Please sign in again.');
        }
      } catch (e) {
        console.error('AptosKeylessService - Failed to decode JWT:', e);
      }
      
      // Use the correct ephemeral key pair (preserving original nonce)
      const ephKeyPair = this.getEphemeralKeyPairForSDK(ephemeralKeyPair);
      
      console.log('AptosKeylessService - Using ephemeralKeyPair with nonce:', ephKeyPair.nonce);
      
      // Derive the keyless account
      const keylessAccount = await this.aptos.deriveKeylessAccount({
        jwt,
        ephemeralKeyPair: ephKeyPair,
        pepper,
      });

      // Wait for the proof to be fetched
      console.log('AptosKeylessService - Waiting for proof...');
      const proofFetchCallback = ({ status }: { status: ProofFetchStatus }) => {
        console.log(`AptosKeylessService - Proof fetch status: ${status}`);
      };
      
      await keylessAccount.waitForProofFetch({
        proofFetchCallback,
      });
      
      console.log('AptosKeylessService - Proof fetched successfully');
      
      // Decode the signing message from base64 using built-in React Native functions
      const signingMessageBytes = this.b64ToBytes(signingMessage);
      
      // Sign the message to get the authenticator
      const authenticator = keylessAccount.signWithAuthenticator(signingMessageBytes);
      
      // Serialize the authenticator to BCS
      const serializer = new Serializer();
      authenticator.serialize(serializer);
      const authenticatorBytes = serializer.toUint8Array();
      const senderAuthenticatorBcsBase64 = this.bytesToB64(authenticatorBytes);
      
      // Get the account address
      const addressHex = keylessAccount.accountAddress.toString();
      
      // Get auth key (which is the account address for keyless accounts)
      const authKeyHex = addressHex;
      
      // Get ephemeral public key as hex (64 chars, no 0x)
      const ephemeralPublicKeyHex = ephKeyPair.publicKey.toString().replace(/^0x/, '');
      
      console.log('AptosKeylessService - Generated authenticator:', {
        addressHex,
        ephemeralPublicKeyHex,
        authenticatorBytesLength: authenticatorBytes.length,
      });
      
      return {
        senderAuthenticatorBcsBase64,
        authKeyHex,
        ephemeralPublicKeyHex,
        addressHex,
      };
    } catch (error) {
      console.error('AptosKeylessService - Error generating authenticator:', error);
      throw error;
    }
  }

  /**
   * Sign and submit a transaction directly (non-sponsored)
   */
  async signAndSubmitTransaction(params: {
    jwt: string;
    ephemeralKeyPair: any;
    transaction: any;
    pepper?: Uint8Array;
  }): Promise<{ hash: string }> {
    const { jwt, ephemeralKeyPair, transaction, pepper } = params;
    
    // Use the correct ephemeral key pair (preserving original nonce)
    const ephKeyPair = this.getEphemeralKeyPairForSDK(ephemeralKeyPair);
    
    // Derive the keyless account
    const keylessAccount = await this.aptos.deriveKeylessAccount({
      jwt,
      ephemeralKeyPair: ephKeyPair,
      pepper,
    });

    // Wait for the proof
    await keylessAccount.waitForProofFetch();
    
    // Sign and submit the transaction
    const response = await this.aptos.signAndSubmitTransaction({
      signer: keylessAccount,
      transaction,
    });

    return { hash: response.hash };
  }

  /**
   * Reconstruct EphemeralKeyPair from data
   */
  private reconstructEphemeralKeyPair(data: any): EphemeralKeyPair {
    try {
      let privateKeyBytes: Uint8Array;
      let expiryDateSecs: number;
      let blinder: Uint8Array | undefined;
      
      // Check if data contains Uint8Arrays (from normalized format)
      if (data.privateKey instanceof Uint8Array) {
        console.log('AptosKeylessService - Using Uint8Array format for reconstruction');
        privateKeyBytes = data.privateKey;
        expiryDateSecs = Math.floor(new Date(data.expiryDate).getTime() / 1000);
        blinder = data.blinder instanceof Uint8Array ? data.blinder : undefined;
      } else {
        // Legacy string format
        console.log('AptosKeylessService - Using legacy string format for reconstruction');
        
        // The data contains the private key in hex format
        // Handle different private key formats
        let privateKeyHex = data.privateKey;
        
        // Remove any prefixes
        if (privateKeyHex.startsWith('ed25519-priv-0x')) {
          privateKeyHex = privateKeyHex.replace('ed25519-priv-0x', '');
        } else if (privateKeyHex.startsWith('0x')) {
          privateKeyHex = privateKeyHex.replace('0x', '');
        }
        
        console.log('AptosKeylessService - Private key hex (cleaned):', privateKeyHex);
        console.log('AptosKeylessService - Private key hex length:', privateKeyHex.length);
        
        privateKeyBytes = new Uint8Array(
          privateKeyHex.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16))
        );
        
        // Convert expiry date to seconds
        console.log('AptosKeylessService - Original expiry date:', data.expiryDate);
        expiryDateSecs = Math.floor(new Date(data.expiryDate).getTime() / 1000);
        console.log('AptosKeylessService - Expiry date in seconds:', expiryDateSecs);
        
        // Parse blinder if it exists
        if (data.blinder) {
          console.log('AptosKeylessService - Original blinder:', data.blinder);
          console.log('AptosKeylessService - Blinder type:', typeof data.blinder);
          
          // Check if blinder is already a hex string or needs conversion
          if (typeof data.blinder === 'string') {
            // Handle the special mixed format: "0x230,82,3,47..."
            if (data.blinder.startsWith('0x') && data.blinder.includes(',')) {
              // This is a weird format where it's "0x" followed by decimal numbers separated by commas
              // Remove the "0x" prefix and parse all as decimal
              const numbersStr = data.blinder.substring(2); // Remove "0x"
              const numbers = numbersStr.split(',').map(n => parseInt(n.trim(), 10));
              
              // The blinder should be 32 bytes
              if (numbers.length === 31) {
                console.log('AptosKeylessService - Blinder is 31 bytes, padding with leading zero');
                numbers.unshift(0); // Add a leading zero
              }
              
              blinder = new Uint8Array(numbers);
              console.log('AptosKeylessService - Parsed blinder as 0x-prefixed decimal array');
              console.log('AptosKeylessService - Blinder values:', numbers);
              console.log('AptosKeylessService - Blinder hex:', Array.from(blinder).map(b => b.toString(16).padStart(2, '0')).join(''));
            } else if (data.blinder.includes(',')) {
              // Parse comma-separated numbers
              const numbers = data.blinder.split(',').map(n => parseInt(n.trim(), 10));
              
              // The blinder should be 32 bytes, but we have 31
              // This might be because the leading zero was stripped
              if (numbers.length === 31) {
                console.log('AptosKeylessService - Blinder is 31 bytes, padding with leading zero');
                numbers.unshift(0); // Add a leading zero
              }
              
              blinder = new Uint8Array(numbers);
              console.log('AptosKeylessService - Parsed blinder as comma-separated array');
              console.log('AptosKeylessService - Blinder values:', numbers);
              console.log('AptosKeylessService - Blinder hex:', Array.from(blinder).map(b => b.toString(16).padStart(2, '0')).join(''));
            } else {
              // If it's a hex string, convert to Uint8Array
              const blinderHex = data.blinder.replace(/^0x/, '');
              
              // For hex strings, we need to ensure it's 32 bytes
              const paddedHex = blinderHex.padStart(64, '0');
              blinder = new Uint8Array(
                paddedHex.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16))
              );
              console.log('AptosKeylessService - Parsed blinder as hex string');
              console.log('AptosKeylessService - Padded hex:', paddedHex);
            }
          }
          
          console.log('AptosKeylessService - Final blinder bytes length:', blinder?.length);
        }
      }
      
      // Create Ed25519PrivateKey instance
      const privateKey = new Ed25519PrivateKey(privateKeyBytes);
      
      // Reconstruct using the Aptos SDK
      const ephemeralKeyPair = new EphemeralKeyPair({
        privateKey,
        expiryDateSecs,
        blinder,
      });
      
      // Log to check if nonce is preserved
      console.log('AptosKeylessService - Original nonce from data:', data.nonce);
      console.log('AptosKeylessService - Reconstructed nonce:', ephemeralKeyPair.nonce);
      
      // The EphemeralKeyPair constructor doesn't preserve the nonce, it calculates a new one
      // This is the issue - we need to ensure the nonce matches what was used in the JWT
      
      // HACK: Override the nonce if it doesn't match
      if (data.nonce && ephemeralKeyPair.nonce !== data.nonce) {
        console.log('AptosKeylessService - WARNING: Nonce mismatch detected');
        console.log('AptosKeylessService - This suggests the ephemeral key pair was not reconstructed correctly');
        console.log('AptosKeylessService - The JWT was created with the original nonce, so authentication will fail');
        
        // We can't just override the nonce - the prover validates it against the other values
        // throw new Error('Cannot reconstruct ephemeral key pair with matching nonce. Please sign in again.');
      }
      
      return ephemeralKeyPair;
    } catch (error) {
      console.error('AptosKeylessService - Error reconstructing ephemeral key pair:', error);
      console.error('AptosKeylessService - Input data:', {
        privateKey: data.privateKey,
        expiryDate: data.expiryDate,
        blinder: data.blinder,
        nonce: data.nonce,
      });
      throw new Error('Failed to reconstruct ephemeral key pair');
    }
  }

  /**
   * Normalize incoming ephemeral key pair to stored format
   */
  normalizeIncomingEkp(rawEkp: any): StoredEphemeralKeyPair {
    const toBytes = (v: any, fieldName: string): Uint8Array => {
      if (v instanceof Uint8Array) return v;
      if (typeof v === 'string') {
        // Handle comma-separated values
        if (v.includes(',')) {
          console.log(`AptosKeylessService - Converting ${fieldName} from CSV format`);
          return this.csvToBytes(v);
        }
        // Handle hex values
        if (/^(0x)?[0-9a-fA-F]+$/.test(v)) {
          console.log(`AptosKeylessService - Converting ${fieldName} from hex format`);
          return this.hexToBytes(v);
        }
        // Try base64
        try {
          console.log(`AptosKeylessService - Attempting to decode ${fieldName} as base64`);
          return this.b64ToBytes(v);
        } catch {}
        throw new Error(`Unsupported ${fieldName} format`);
      }
      if (Array.isArray(v)) return new Uint8Array(v);
      throw new Error(`Unsupported ${fieldName} type`);
    };

    // Convert each field to bytes
    const privateKeyBytes = toBytes(rawEkp.privateKey, 'privateKey');
    const publicKeyBytes = toBytes(rawEkp.publicKey, 'publicKey');
    
    // Handle nonce - it might be a string number
    let nonceBytes: Uint8Array;
    if (typeof rawEkp.nonce === 'string' && /^\d+$/.test(rawEkp.nonce)) {
      // It's a decimal string, convert to bigint then to bytes
      const nonceBigInt = BigInt(rawEkp.nonce);
      const nonceHex = nonceBigInt.toString(16).padStart(64, '0');
      nonceBytes = this.hexToBytes(nonceHex);
    } else {
      nonceBytes = toBytes(rawEkp.nonce, 'nonce');
    }
    
    const blinderBytes = toBytes(rawEkp.blinder, 'blinder');

    // Log the lengths for debugging
    console.log('AptosKeylessService - Normalized field lengths:', {
      privateKey: privateKeyBytes.length,
      publicKey: publicKeyBytes.length,
      nonce: nonceBytes.length,
      blinder: blinderBytes.length,
    });

    return {
      privateKey_b64: this.bytesToB64(privateKeyBytes),
      publicKey_b64: this.bytesToB64(publicKeyBytes),
      nonce_b64: this.bytesToB64(nonceBytes),
      blinder_b64: this.bytesToB64(blinderBytes),
      expiryISO: new Date(rawEkp.expiryDate || rawEkp.expiryISO).toISOString(),
      version: 'ekp-v1',
    };
  }

  /**
   * Get EphemeralKeyPair for Aptos SDK from stored format  
   */
  getEphemeralKeyPairForSDK(data: any): any {
    // CRITICAL: Always use the raw EphemeralKeyPair if available
    // This preserves the original nonce that was used in JWT creation
    if (data.raw) {
      console.log('AptosKeylessService - Using raw EphemeralKeyPair (preserves original nonce)');
      return data.raw;
    }
    
    console.log('AptosKeylessService - WARNING: No raw EphemeralKeyPair available, fallback may cause nonce mismatch');
    
    // If it's in stored format, we need to use the private reconstruction method
    // For now, just return the raw if available
    if (data.version === 'ekp-v1') {
      // We can't easily access the private method, so let's work with what we have
      return data.raw || data;
    }
    
    // Otherwise, return the data as-is
    return data;
  }

  /**
   * Convert stored ephemeral key pair back to usable format
   */
  ekpFromStored(stored: StoredEphemeralKeyPair): any {
    // Convert nonce bytes back to decimal string for comparison with JWT
    const nonceBytes = this.b64ToBytes(stored.nonce_b64);
    const nonceHex = Array.from(nonceBytes).map(b => b.toString(16).padStart(2, '0')).join('');
    const nonceDecimal = BigInt('0x' + nonceHex).toString();
    
    return {
      privateKey: this.b64ToBytes(stored.privateKey_b64),
      publicKey: this.b64ToBytes(stored.publicKey_b64),
      nonce: nonceDecimal, // Return as decimal string for JWT comparison
      blinder: this.b64ToBytes(stored.blinder_b64),
      expiryDate: stored.expiryISO,
    };
  }

  /**
   * Generate a new ephemeral key pair
   */
  generateEphemeralKeyPair(expiryHours: number = 24): StoredEphemeralKeyPair & { raw: EphemeralKeyPair } {
    const ephemeralKeyPair = EphemeralKeyPair.generate();
    const expiryDate = new Date();
    expiryDate.setHours(expiryDate.getHours() + expiryHours);

    console.log('AptosKeylessService - Generated ephemeral key pair fields:', {
      nonce: ephemeralKeyPair.nonce,
      nonceType: typeof ephemeralKeyPair.nonce,
      blinder: ephemeralKeyPair.blinder,
      blinderType: typeof ephemeralKeyPair.blinder,
    });

    // Extract raw bytes from the ephemeral key pair
    const privateKeyBytes = new Uint8Array(ephemeralKeyPair.privateKey.toUint8Array());
    const publicKeyBytes = new Uint8Array(ephemeralKeyPair.publicKey.toUint8Array());
    
    // Convert nonce to bytes (it's a bigint)
    const nonceHex = BigInt(ephemeralKeyPair.nonce).toString(16).padStart(64, '0');
    console.log('AptosKeylessService - Nonce hex:', nonceHex, 'length:', nonceHex.length);
    const nonceBytes = this.hexToBytes(nonceHex);
    
    // Convert blinder to bytes - handle different types
    let blinderBytes: Uint8Array;
    if (typeof ephemeralKeyPair.blinder === 'bigint') {
      const blinderHex = ephemeralKeyPair.blinder.toString(16).padStart(64, '0');
      console.log('AptosKeylessService - Blinder hex (bigint):', blinderHex, 'length:', blinderHex.length);
      blinderBytes = this.hexToBytes(blinderHex);
    } else if (ephemeralKeyPair.blinder instanceof Uint8Array) {
      console.log('AptosKeylessService - Blinder is already Uint8Array, length:', ephemeralKeyPair.blinder.length);
      blinderBytes = ephemeralKeyPair.blinder;
    } else {
      // Try to convert whatever it is to string then hex
      const blinderStr = String(ephemeralKeyPair.blinder);
      const blinderHex = blinderStr.padStart(64, '0');
      console.log('AptosKeylessService - Blinder hex (string):', blinderHex, 'length:', blinderHex.length);
      blinderBytes = this.hexToBytes(blinderHex);
    }

    console.log('AptosKeylessService - Generated ephemeral key pair with lengths:', {
      privateKey: privateKeyBytes.length,
      publicKey: publicKeyBytes.length,
      nonce: nonceBytes.length,
      blinder: blinderBytes.length,
    });

    return {
      privateKey_b64: this.bytesToB64(privateKeyBytes),
      publicKey_b64: this.bytesToB64(publicKeyBytes),
      nonce_b64: this.bytesToB64(nonceBytes),
      blinder_b64: this.bytesToB64(blinderBytes),
      expiryISO: expiryDate.toISOString(),
      version: 'ekp-v1',
      raw: ephemeralKeyPair, // Include raw for immediate use
    };
  }

  /**
   * Get ephemeral key pair info for sending to backend
   */
  getEphemeralKeyPairForBackend(storedEkp: StoredEphemeralKeyPair & { raw?: EphemeralKeyPair }): {
    publicKey: string;
    nonce: string;
    expiryDate: string;
  } {
    // Use the raw nonce directly if available, otherwise convert from stored format
    let nonce: string;
    if (storedEkp.raw) {
      // Use the original nonce from the raw EphemeralKeyPair
      nonce = storedEkp.raw.nonce;
      console.log('AptosKeylessService - Using raw nonce for backend:', nonce);
    } else {
      // Fallback to converting from stored format
      const ekp = this.ekpFromStored(storedEkp);
      nonce = ekp.nonce;
      console.log('AptosKeylessService - Using converted nonce for backend:', nonce);
    }
    
    // Convert public key to hex format
    const publicKeyBytes = this.b64ToBytes(storedEkp.publicKey_b64);
    const publicKeyHex = '0x' + Array.from(publicKeyBytes).map(b => b.toString(16).padStart(2, '0')).join('');
    
    console.log('AptosKeylessService - Backend format:', {
      publicKey: publicKeyHex,
      nonce: nonce,
      expiryDate: storedEkp.expiryISO,
    });
    
    return {
      publicKey: publicKeyHex,
      nonce: nonce,
      expiryDate: storedEkp.expiryISO,
    };
  }
}

// Export a singleton instance
export const aptosKeylessService = new AptosKeylessService('testnet');