import {
  Aptos,
  AptosConfig,
  EphemeralKeyPair,
  Ed25519PrivateKey,
} from '@aptos-labs/ts-sdk';
import * as jose from 'jose';
import crypto from 'crypto';
import { config } from '../config';
import logger from '../logger';
import {
  EphemeralKeyPairData,
  KeylessAccountData,
  DeriveAccountRequest,
} from '../types';
import { ephemeralKeyStore } from './ephemeralKeyStore';

export class KeylessService {
  private aptos: Aptos;

  constructor() {
    const aptosConfig = new AptosConfig({ network: config.aptos.network });
    this.aptos = new Aptos(aptosConfig);
  }

  /**
   * Generate a new ephemeral key pair
   */
  async generateEphemeralKeyPair(expiryHours: number = 24): Promise<EphemeralKeyPairData & { keyId: string }> {
    try {
      const ephemeralKeyPair = EphemeralKeyPair.generate();
      const expiryDate = new Date();
      expiryDate.setHours(expiryDate.getHours() + expiryHours);

      // Generate a unique ID for this key pair
      const keyId = crypto.randomBytes(16).toString('hex');
      
      // Store the actual key pair object
      ephemeralKeyStore.store(keyId, ephemeralKeyPair);

      const nonce = ephemeralKeyPair.nonce;
      const blinder = ephemeralKeyPair.blinder.toString();

      return {
        keyId, // Include the ID so we can retrieve the key pair later
        privateKey: (ephemeralKeyPair as any).privateKey.toString(),
        publicKey: (ephemeralKeyPair as any).publicKey.toString(),
        expiryDate: expiryDate.toISOString(),
        nonce,
        blinder,
      };
    } catch (error) {
      logger.error('Error generating ephemeral key pair:', error);
      throw new Error('Failed to generate ephemeral key pair');
    }
  }

  /**
   * Generate a deterministic ephemeral key pair from a seed
   * This ensures the same seed always produces the same address
   */
  async generateDeterministicEphemeralKeyPair(
    seed: string, 
    expiryHours: number = 24
  ): Promise<EphemeralKeyPairData & { keyId: string }> {
    try {
      // Create a deterministic seed by hashing the input seed
      const hash = crypto.createHash('sha256').update(seed).digest();
      
      // Create a private key from the hash (first 32 bytes)
      const privateKey = new Ed25519PrivateKey(hash.slice(0, 32));
      
      // Generate deterministic nonce from seed
      const nonceHash = crypto.createHash('sha256').update(`nonce-${seed}`).digest();
      const nonce = nonceHash.toString('hex').substring(0, 32);
      
      // Create ephemeral key pair with deterministic values
      // Note: This is a workaround since EphemeralKeyPair doesn't have a fromSeed method
      const ephemeralKeyPair = {
        privateKey: privateKey,
        publicKey: privateKey.publicKey(),
        nonce: nonce,
        blinder: BigInt('0x' + crypto.createHash('sha256').update(`blinder-${seed}`).digest('hex')),
        expiryDate: new Date(Date.now() + expiryHours * 60 * 60 * 1000),
      };
      
      const expiryDate = new Date();
      expiryDate.setHours(expiryDate.getHours() + expiryHours);

      // Generate a deterministic key ID from the seed
      const keyId = crypto.createHash('sha256').update(`keyid-${seed}`).digest('hex').substring(0, 32);
      
      // Store a compatible ephemeral key pair object
      // We'll need to create a proper EphemeralKeyPair instance for storage
      const fullKeyPair = Object.assign(
        Object.create(EphemeralKeyPair.prototype),
        ephemeralKeyPair
      );
      ephemeralKeyStore.store(keyId, fullKeyPair);

      return {
        keyId,
        privateKey: privateKey.toString(),
        publicKey: ephemeralKeyPair.publicKey.toString(),
        expiryDate: expiryDate.toISOString(),
        nonce,
        blinder: ephemeralKeyPair.blinder.toString(),
      };
    } catch (error) {
      logger.error('Error generating deterministic ephemeral key pair:', error);
      throw error;
    }
  }

  /**
   * Generate OAuth URL with proper nonce
   */
  async generateOAuthUrl(
    provider: 'google' | 'apple',
    clientId: string,
    redirectUri: string,
    ephemeralKeyPairData: EphemeralKeyPairData
  ): Promise<string> {
    try {
      const providerConfig = config.oauth.providers[provider];
      if (!providerConfig) {
        throw new Error(`Unsupported provider: ${provider}`);
      }

      // Reconstruct ephemeral key pair from data
      const ephemeralKeyPair = this.reconstructEphemeralKeyPair(ephemeralKeyPairData);
      
      // Generate state for CSRF protection
      const state = crypto.randomBytes(32).toString('hex');

      const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: providerConfig.scope,
        nonce: ephemeralKeyPair.nonce,
        state,
      });

      // Apple requires additional parameters
      if (provider === 'apple') {
        params.append('response_mode', 'form_post');
      }

      return `${providerConfig.authUrl}?${params.toString()}`;
    } catch (error) {
      logger.error('Error generating OAuth URL:', error);
      throw new Error('Failed to generate OAuth URL');
    }
  }

  /**
   * Derive a Keyless account from JWT and ephemeral key pair
   */
  async deriveKeylessAccount(request: DeriveAccountRequest): Promise<KeylessAccountData> {
    try {
      // Decode JWT to validate
      const decodedJwt = jose.decodeJwt(request.jwt);
      if (!decodedJwt.sub || !decodedJwt.aud || !decodedJwt.iss) {
        throw new Error('Invalid JWT: missing required claims');
      }

      // Try to retrieve the stored key pair first
      let ephemeralKeyPair: EphemeralKeyPair;
      
      if ('keyId' in request.ephemeralKeyPair && request.ephemeralKeyPair.keyId) {
        const storedKeyPair = ephemeralKeyStore.retrieve(request.ephemeralKeyPair.keyId);
        if (storedKeyPair) {
          ephemeralKeyPair = storedKeyPair;
          logger.info('Using stored ephemeral key pair');
        } else {
          logger.warn('Stored key pair not found, reconstructing from data');
          ephemeralKeyPair = this.reconstructEphemeralKeyPair(request.ephemeralKeyPair);
        }
      } else {
        ephemeralKeyPair = this.reconstructEphemeralKeyPair(request.ephemeralKeyPair);
      }
      
      const jwtNonce = typeof decodedJwt.nonce === 'string' ? decodedJwt.nonce : String(decodedJwt.nonce);
      logger.info('JWT nonce:', jwtNonce);
      logger.info('Ephemeral key nonce:', String(ephemeralKeyPair.nonce));
      logger.info('Nonces match:', jwtNonce === String(ephemeralKeyPair.nonce));

      // Derive the Keyless account
      const keylessAccount = await this.aptos.deriveKeylessAccount({
        jwt: request.jwt,
        ephemeralKeyPair,
        pepper: request.pepper,
      });

      // Wait for the proof to be fetched
      await keylessAccount.waitForProofFetch();
      
      // Log the pepper for debugging
      logger.info('Keyless account derived successfully');
      logger.info('Address:', keylessAccount.accountAddress.toString());
      
      // Try to access the pepper from the KeylessAccount instance
      // The pepper might be stored as a property on the keylessAccount object
      const derivedPepper = (keylessAccount as any).pepper || request.pepper;
      if (derivedPepper && !request.pepper) {
        logger.info('Pepper fetched from pepper service:', derivedPepper);
      }

      return {
        address: keylessAccount.accountAddress.toString(),
        publicKey: keylessAccount.publicKey.toString(),
        jwt: request.jwt,
        ephemeralKeyPair: request.ephemeralKeyPair,
        pepper: derivedPepper,
      };
    } catch (error) {
      logger.error('Error deriving keyless account:', error);
      throw new Error(`Failed to derive keyless account: ${error}`);
    }
  }

  /**
   * Sign and submit a transaction using Keyless account
   */
  async signAndSubmitTransaction(
    jwt: string,
    ephemeralKeyPairData: EphemeralKeyPairData,
    transaction: any,
    pepper?: string
  ): Promise<any> {
    try {
      // Derive the keyless account again (stateless service)
      await this.deriveKeylessAccount({
        jwt,
        ephemeralKeyPair: ephemeralKeyPairData,
        pepper,
      });

      // Reconstruct the account object
      const ephemeralKeyPair = this.reconstructEphemeralKeyPair(ephemeralKeyPairData);
      const account = await this.aptos.deriveKeylessAccount({
        jwt,
        ephemeralKeyPair,
        pepper,
      });

      // Sign and submit the transaction
      const response = await this.aptos.signAndSubmitTransaction({
        signer: account,
        transaction,
      });

      return {
        ...response,
        hash: response.hash,
      };
    } catch (error) {
      logger.error('Error signing and submitting transaction:', error);
      throw new Error(`Failed to sign and submit transaction: ${error}`);
    }
  }

  /**
   * Get account balance for multiple tokens
   */
  async getAccountBalance(address: string): Promise<{ [key: string]: string }> {
    try {
      const balances: { [key: string]: string } = {};
      
      // Get all resources to see what coin stores exist
      try {
        const resources = await this.aptos.getAccountResources({
          accountAddress: address,
        });
        
        logger.info(`Found ${resources.length} resources for ${address}`);
        
        // Look for any CoinStore resources
        for (const resource of resources) {
          if (resource.type.includes('coin::CoinStore')) {
            logger.info(`Found CoinStore: ${resource.type}`);
            const coinData = resource.data as any;
            if (coinData.coin && coinData.coin.value) {
              logger.info(`Coin value: ${coinData.coin.value}`);
              
              // Check if this looks like USDC
              if (resource.type.includes('69091fbab5f7d635ee7ac5098cf0c1efbe31d68fec0f2cd565e8d168daf52832')) {
                balances.usdc = coinData.coin.value;
                logger.info(`USDC balance found: ${balances.usdc}`);
              }
            }
          }
        }
        
        // Set defaults if not found
        if (!balances.usdc) balances.usdc = '0';
        
      } catch (e) {
        logger.error(`Error getting resources for ${address}: ${e}`);
        balances.usdc = '0';
      }
      
      // cUSD and CONFIO not yet deployed
      balances.cusd = '0';
      balances.confio = '0';

      return balances;
    } catch (error) {
      logger.error('Error getting account balances:', error);
      // Return zeros if account doesn't exist or other errors
      return {
        usdc: '0',
        cusd: '0',
        confio: '0'
      };
    }
  }

  /**
   * Reconstruct EphemeralKeyPair from data
   */
  private reconstructEphemeralKeyPair(data: EphemeralKeyPairData): EphemeralKeyPair {
    try {
      // The data contains the private key in hex format
      // We need to reconstruct the EphemeralKeyPair from the private key
      const privateKeyHex = data.privateKey.replace('0x', '');
      const privateKeyBytes = new Uint8Array(privateKeyHex.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16)));
      
      // Reconstruct using the Aptos SDK method
      const ephemeralKeyPair = new EphemeralKeyPair({
        privateKey: new Ed25519PrivateKey(privateKeyBytes),
        expiryDateSecs: Math.floor(new Date(data.expiryDate).getTime() / 1000), // Convert to Unix timestamp
        blinder: data.blinder ? new Uint8Array(data.blinder.split(',').map(b => parseInt(b))) : undefined, // Convert blinder array
      });
      
      // The nonce should match the one that was used when generating the key
      // Check if the reconstructed nonce matches the original
      if (String(ephemeralKeyPair.nonce) !== String(data.nonce)) {
        logger.error('Nonce mismatch after reconstruction!');
        logger.error('Original nonce:', data.nonce);
        logger.error('Reconstructed nonce:', String(ephemeralKeyPair.nonce));
        
        // Try to manually set the nonce if possible
        // This is a workaround - the SDK should handle this properly
        // Make sure it's a string, not an object
        const nonceString = typeof data.nonce === 'string' 
          ? data.nonce 
          : typeof data.nonce === 'object' && data.nonce !== null
            ? Object.values(data.nonce).join('')
            : String(data.nonce);
        (ephemeralKeyPair as any).nonce = nonceString;
      }
      
      logger.debug('Final ephemeral key pair nonce:', String(ephemeralKeyPair.nonce));
      
      return ephemeralKeyPair;
    } catch (error) {
      logger.error('Error reconstructing ephemeral key pair:', error);
      throw new Error('Failed to reconstruct ephemeral key pair');
    }
  }
}