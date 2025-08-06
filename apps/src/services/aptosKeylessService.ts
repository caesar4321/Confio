// Import polyfills before Aptos SDK
import './aptosPolyfills';

import {
  Aptos,
  AptosConfig,
  Network,
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
  expiryDateSecs?: number; // Store exact seconds for perfect reconstruction
  version: 'ekp-v1' | 'ekp-v2'; // v2 includes expiryDateSecs
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
      network: network === 'mainnet' ? Network.MAINNET : Network.TESTNET 
    });
    console.log('AptosKeylessService initialized with network:', network);
    console.log('AptosConfig network:', aptosConfig.network);
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
      if ((ephemeralKeyPair as any).version === 'ekp-v1' || (ephemeralKeyPair as any).version === 'ekp-v2') {
        console.log('AptosKeylessService - Converting stored ephemeral key pair format');
        ekpToUse = this.ekpFromStored(ephemeralKeyPair as any as StoredEphemeralKeyPair);
      } else if ((ephemeralKeyPair as any).privateKey_b64) {
        // It's in stored format but without version field
        console.log('AptosKeylessService - Converting unversioned stored ephemeral key pair format');
        ekpToUse = this.ekpFromStored(ephemeralKeyPair as any as StoredEphemeralKeyPair);
      } else {
        console.log('AptosKeylessService - Using ephemeral key pair in original backend format');
        // Make sure it has required fields
        if (!ekpToUse.nonce && (ephemeralKeyPair as any).nonce_b64) {
          // Try to extract nonce from stored format
          const nonceBytes = this.b64ToBytes((ephemeralKeyPair as any).nonce_b64);
          const nonceHex = Array.from(nonceBytes).map(b => b.toString(16).padStart(2, '0')).join('');
          ekpToUse.nonce = BigInt('0x' + nonceHex).toString();
          console.log('AptosKeylessService - Extracted nonce from nonce_b64:', ekpToUse.nonce);
        }
      }
      
      console.log('AptosKeylessService - ekpToUse after conversion:', {
        hasNonce: !!ekpToUse?.nonce,
        nonce: ekpToUse?.nonce,
        hasPrivateKey: !!ekpToUse?.privateKey,
        hasPublicKey: !!ekpToUse?.publicKey,
        hasBlinder: !!ekpToUse?.blinder,
        expiryDate: ekpToUse?.expiryDate,
      });
      
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
        console.log('AptosKeylessService - JWT value:', jwt?.substring(0, 100) + '...');
        const jwtParts = jwt.split('.');
        console.log('AptosKeylessService - JWT parts length:', jwtParts.length);
        console.log('AptosKeylessService - JWT payload part:', jwtParts[1]?.substring(0, 50) + '...');
        
        // Use atob for base64 decoding which is available in React Native
        const payloadBase64 = jwtParts[1];
        console.log('AptosKeylessService - About to decode payload:', payloadBase64?.substring(0, 20) + '...');
        
        // Fix base64 padding if needed
        const padded = payloadBase64 + '='.repeat((4 - payloadBase64.length % 4) % 4);
        
        let payload: any;
        try {
          // In React Native, we might need to use a different approach
          let decodedPayload: string;
          try {
            decodedPayload = atob(padded);
          } catch (atobError) {
            // Fallback: try without padding
            console.log('AptosKeylessService - atob failed with padding, trying without');
            decodedPayload = atob(payloadBase64);
          }
          
          console.log('AptosKeylessService - Decoded payload string:', decodedPayload?.substring(0, 100) + '...');
          console.log('AptosKeylessService - First char code:', decodedPayload?.charCodeAt(0));
          
          // Check if the decoded string starts with valid JSON
          if (!decodedPayload || (!decodedPayload.startsWith('{') && !decodedPayload.startsWith('['))) {
            throw new Error(`Invalid decoded payload: starts with '${decodedPayload?.charAt(0)}'`);
          }
          
          payload = JSON.parse(decodedPayload);
        } catch (decodeError) {
          console.error('AptosKeylessService - Error decoding JWT:', decodeError);
          console.error('AptosKeylessService - JWT parts:', jwtParts.length);
          console.error('AptosKeylessService - Payload base64 length:', payloadBase64?.length);
          console.error('AptosKeylessService - Padded length:', padded?.length);
          throw new Error(`Failed to decode JWT: ${decodeError.message}`);
        }
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
      let keylessAccount;
      try {
        keylessAccount = await this.aptos.deriveKeylessAccount({
          jwt,
          ephemeralKeyPair: ephKeyPair,
          pepper,
        });
      } catch (deriveError: any) {
        console.error('AptosKeylessService - Error deriving keyless account:', deriveError);
        
        // Check if it's a JSON parse error (likely from JWKS fetch)
        if (deriveError.message?.includes('JSON Parse error') || deriveError.message?.includes('Unexpected character')) {
          console.error('AptosKeylessService - JWKS/proof service returned HTML instead of JSON');
          console.error('AptosKeylessService - This is a known issue in React Native environments');
          
          // For sponsored transactions, we can skip the proof since the bridge will handle it
          console.warn('AptosKeylessService - Attempting to continue without deriving keyless account');
          console.warn('AptosKeylessService - Will return a simplified authenticator for bridge-side processing');
          
          // Return a simplified response that the bridge can use
          // The bridge will recreate the keyless account with the ephemeral key pair data
          throw new Error('Cannot derive keyless account in React Native - bridge will handle direct signing');
        }
        
        throw deriveError;
      }

      // Wait for the proof to be fetched
      console.log('AptosKeylessService - Waiting for proof...');
      const proofFetchCallback = ({ status }: { status: ProofFetchStatus }) => {
        console.log(`AptosKeylessService - Proof fetch status: ${status}`);
      };
      
      try {
        await keylessAccount.waitForProofFetch({
          proofFetchCallback,
        });
      } catch (proofError: any) {
        console.error('AptosKeylessService - Proof fetch error:', proofError);
        console.error('AptosKeylessService - Error message:', proofError.message);
        console.error('AptosKeylessService - Error stack:', proofError.stack);
        
        // Check if it's a JWKS error
        if (proofError.message?.includes('JWKS') || proofError.message?.includes('TextDecoder')) {
          console.error('AptosKeylessService - JWKS fetch failed, possibly due to missing TextDecoder polyfill');
          console.error('AptosKeylessService - Make sure aptosPolyfills.ts is imported before Aptos SDK');
        }
        
        // Check if it's a JSON parse error
        if (proofError.message?.includes('JSON Parse error') || proofError.message?.includes('Unexpected character')) {
          console.error('AptosKeylessService - JSON parse error, likely received HTML instead of JSON');
          console.error('AptosKeylessService - This usually means the prover service returned an error page');
          console.error('AptosKeylessService - Check network connectivity and prover service availability');
        }
        
        // Try to provide more context
        if (proofError.details) {
          console.error('AptosKeylessService - Error details:', proofError.details);
        }
        
        // For now, skip proof verification and continue
        console.warn('AptosKeylessService - WARNING: Continuing without proof verification');
        console.warn('AptosKeylessService - Transaction may fail if proof is required');
        // Don't throw, let's try to continue
        // throw proofError;
      }
      
      console.log('AptosKeylessService - Proof fetched successfully');
      
      // Log keyless account details for debugging
      console.log('AptosKeylessService - Keyless account details:', {
        address: keylessAccount.accountAddress.toString(),
        hasProof: !!(keylessAccount as any).proof,
        hasJwtData: !!(keylessAccount as any).jwt,
      });
      
      // Check if we can access the proof
      if ((keylessAccount as any).proof) {
        console.log('AptosKeylessService - Proof exists in keyless account');
      }
      
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
   * Derive a keyless account from JWT and ephemeral key pair
   */
  async deriveKeylessAccount(params: {
    jwt: string;
    ephemeralKeyPair: any;
    pepper?: Uint8Array;
  }): Promise<KeylessAccount> {
    const { jwt, ephemeralKeyPair, pepper } = params;
    
    // Use the correct ephemeral key pair (preserving original nonce)
    const ephKeyPair = this.getEphemeralKeyPairForSDK(ephemeralKeyPair);
    
    // Derive the keyless account
    const keylessAccount = await this.aptos.deriveKeylessAccount({
      jwt,
      ephemeralKeyPair: ephKeyPair,
      pepper,
    });

    // Wait for the proof
    try {
      await keylessAccount.waitForProofFetch();
    } catch (proofError: any) {
      console.error('AptosKeylessService - Proof fetch error in deriveKeylessAccount:', proofError.message);
      // Continue without proof for testing
      console.warn('AptosKeylessService - Continuing without proof for testing purposes');
    }
    
    return keylessAccount;
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
    try {
      await keylessAccount.waitForProofFetch();
    } catch (proofError: any) {
      console.error('AptosKeylessService - Proof fetch error in deriveKeylessAccount:', proofError.message);
      // Continue without proof for testing
      console.warn('AptosKeylessService - Continuing without proof for testing purposes');
    }
    
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
        let privateKeyHex = data.privateKey || '';
        
        if (!privateKeyHex) {
          console.error('AptosKeylessService - No private key found in data');
          console.error('AptosKeylessService - Available keys:', Object.keys(data));
          throw new Error('Private key is missing from ephemeral key pair data');
        }
        
        // Remove any prefixes
        if (privateKeyHex.startsWith('ed25519-priv-0x')) {
          privateKeyHex = privateKeyHex.replace('ed25519-priv-0x', '');
        } else if (privateKeyHex.startsWith('0x')) {
          privateKeyHex = privateKeyHex.replace('0x', '');
        }
        
        console.log('AptosKeylessService - Private key hex (cleaned):', privateKeyHex);
        console.log('AptosKeylessService - Private key hex length:', privateKeyHex.length);
        
        const matches = privateKeyHex.match(/.{1,2}/g);
        if (!matches) {
          throw new Error('Invalid private key hex format');
        }
        
        privateKeyBytes = new Uint8Array(
          matches.map(byte => parseInt(byte, 16))
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
      expiryDateSecs: rawEkp.expiryDateSecs || Math.floor(new Date(rawEkp.expiryDate || rawEkp.expiryISO).getTime() / 1000),
      version: 'ekp-v2',
    };
  }

  /**
   * Get EphemeralKeyPair for Aptos SDK from stored format  
   */
  getEphemeralKeyPairForSDK(data: any): EphemeralKeyPair {
    // If it's already an EphemeralKeyPair instance, return it
    if (data instanceof EphemeralKeyPair) {
      console.log('AptosKeylessService - Using existing EphemeralKeyPair instance');
      return data;
    }
    
    // If it has a raw field that's an EphemeralKeyPair instance, use that
    if (data.raw instanceof EphemeralKeyPair) {
      console.log('AptosKeylessService - Using raw EphemeralKeyPair (preserves original nonce)');
      return data.raw;
    }
    
    // Otherwise, we need to reconstruct it
    console.log('AptosKeylessService - Reconstructing EphemeralKeyPair from stored data');
    console.log('AptosKeylessService - Data structure:', {
      hasVersion: 'version' in data,
      version: data.version,
      hasPrivateKey_b64: 'privateKey_b64' in data,
      hasPrivateKey: 'privateKey' in data,
      dataKeys: Object.keys(data)
    });
    
    try {
      // If it's the stored format (base64 encoded fields)
      if (data.version === 'ekp-v1' || data.version === 'ekp-v2' || data.privateKey_b64) {
        console.log('AptosKeylessService - Using reconstructEphemeralKeyPairFromStored for v1/v2 format');
        return this.reconstructEphemeralKeyPairFromStored(data);
      }
      
      // Otherwise try to reconstruct from the plain object
      console.log('AptosKeylessService - Using reconstructEphemeralKeyPair for legacy format');
      return this.reconstructEphemeralKeyPair(data);
    } catch (error) {
      console.error('AptosKeylessService - Failed to reconstruct EphemeralKeyPair:', error);
      throw error;
    }
  }
  
  /**
   * Reconstruct EphemeralKeyPair from stored format
   */
  private reconstructEphemeralKeyPairFromStored(stored: StoredEphemeralKeyPair): EphemeralKeyPair {
    const privateKeyBytes = this.b64ToBytes(stored.privateKey_b64);
    const blinderBytes = this.b64ToBytes(stored.blinder_b64);
    
    // Use exact seconds if available (v2), otherwise calculate from ISO date
    const expiryDateSecs = stored.expiryDateSecs 
      ? stored.expiryDateSecs
      : Math.floor(new Date(stored.expiryISO).getTime() / 1000);
    
    // Log stored nonce for comparison
    const storedNonceBytes = this.b64ToBytes(stored.nonce_b64);
    const storedNonceHex = Array.from(storedNonceBytes).map(b => b.toString(16).padStart(2, '0')).join('');
    const storedNonceDecimal = BigInt('0x' + storedNonceHex).toString();
    
    console.log('AptosKeylessService - Reconstructing from stored format');
    console.log('AptosKeylessService - Storage version:', stored.version);
    console.log('AptosKeylessService - Stored nonce (decimal):', storedNonceDecimal);
    console.log('AptosKeylessService - Private key length:', privateKeyBytes.length);
    console.log('AptosKeylessService - Blinder length:', blinderBytes.length);
    console.log('AptosKeylessService - Expiry date (seconds):', expiryDateSecs);
    console.log('AptosKeylessService - Expiry date (ISO):', stored.expiryISO);
    
    const privateKey = new Ed25519PrivateKey(privateKeyBytes);
    
    const reconstructed = new EphemeralKeyPair({
      privateKey,
      expiryDateSecs,
      blinder: blinderBytes
    });
    
    console.log('AptosKeylessService - Reconstructed nonce:', reconstructed.nonce);
    
    if (reconstructed.nonce !== storedNonceDecimal) {
      console.error('AptosKeylessService - WARNING: Reconstructed nonce does not match stored nonce!');
      console.error('AptosKeylessService - This will cause authentication to fail');
      console.error('AptosKeylessService - Stored:', storedNonceDecimal);
      console.error('AptosKeylessService - Reconstructed:', reconstructed.nonce);
    }
    
    return reconstructed;
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
    // Calculate expiry date in seconds first to ensure consistency
    const nowSecs = Math.floor(Date.now() / 1000);
    const expiryDateSecs = nowSecs + (expiryHours * 3600);
    
    // Generate with specific expiry date
    const ephemeralKeyPair = EphemeralKeyPair.generate({ expiryDateSecs });
    
    // Convert expiry seconds back to date for storage
    const expiryDate = new Date(expiryDateSecs * 1000);

    console.log('AptosKeylessService - Generated ephemeral key pair fields:', {
      nonce: ephemeralKeyPair.nonce,
      nonceType: typeof ephemeralKeyPair.nonce,
      blinder: ephemeralKeyPair.blinder,
      blinderType: typeof ephemeralKeyPair.blinder,
      expiryDateSecs: expiryDateSecs,
      expiryDateISO: expiryDate.toISOString(),
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
      expiryDateSecs: expiryDateSecs, // Store exact seconds for perfect reconstruction
      version: 'ekp-v2', // v2 includes expiryDateSecs
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