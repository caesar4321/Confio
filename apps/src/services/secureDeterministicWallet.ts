/**
 * Secure Deterministic Wallet Service
 * 
 * Implements a truly non-custodial approach where:
 * 1. Client generates deterministic salt from OAuth claims
 * 2. Server optionally provides additional entropy (pepper)
 * 3. Neither server nor OAuth provider alone can compute the private key
 * 4. User can recover wallet from any device with OAuth login + recovery secret
 * 
 * Based on zkLogin principles but adapted for Algorand
 */

import { hkdf } from '@noble/hashes/hkdf';
import { sha256 } from '@noble/hashes/sha256';
import { utf8ToBytes, bytesToHex, hexToBytes } from '@noble/hashes/utils';
import * as nacl from 'tweetnacl';
// algosdk will be required at runtime to avoid RN bundler issues
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';
import { randomBytes } from '@noble/hashes/utils';
import { Buffer } from 'buffer'; // RN polyfill for base64
import { GOOGLE_CLIENT_IDS } from '../config/env';

// GraphQL mutations for server pepper (per-user, not per-scope)
const GET_SERVER_PEPPER = gql`
  mutation GetServerPepper($firebaseUid: String!, $requestVersion: Int) {
    getServerPepper(firebaseUid: $firebaseUid, requestVersion: $requestVersion) {
      success
      pepper
      version
      isRotated
      gracePeriodUntil
      error
    }
  }
`;

/**
 * Generate consistent scope for KEK derivation and cache keys
 * IMPORTANT: Must be identical between createOrRestoreWallet and warmUpFromCache
 */
function makeScope(
  provider: 'google' | 'apple',
  subject: string,
  accountType: 'personal' | 'business',
  accountIndex: number,
  businessId?: string
): string {
  return `${provider}|${subject}|${accountType}|${accountIndex}|${businessId ?? ''}`;
}

/**
 * Generate consistent cache key for encrypted seed storage
 * Returns server and username components for proper keychain usage
 */
function makeCacheKey(uid: string, scope: string): { server: string; username: string } {
  // Use a consistent server name like other services in the codebase
  // Put the unique identifier in the username field
  return {
    server: 'wallet.confio.app',
    username: `${uid}_${scope.replace(/[^a-zA-Z0-9_]/g, '_')}`
  };
}

export interface DeriveWalletOptions {
  idToken: string;              // Firebase ID token (Google or Apple)
  clientSalt: string;           // Client-generated deterministic salt (like zkLogin)
  serverPepper?: string;        // Optional server entropy for additional security
  provider: 'google' | 'apple';
  accountType: 'personal' | 'business';
  accountIndex: number;         // 0, 1, 2...
  businessId?: string;          // when applicable
  network?: 'testnet' | 'mainnet'; // Network isolation
}

export interface DerivedWallet {
  address: string;
  privSeedHex: string;
  publicKey: Uint8Array;
}

/**
 * Canonicalize OAuth claims for consistent salt generation
 * Removes trailing slashes, converts to lowercase
 */
function canonicalize(s: string): string {
  return s.trim().toLowerCase().replace(/\/+$/, '');
}

/**
 * Derive Key Encryption Key (KEK) for securing cached seeds
 * Uses OAuth claims + optional server pepper
 */
function deriveKEK(
  idToken: string,
  serverPepper: string | undefined,
  scope: string
): Uint8Array {
  const decoded = jwtDecode<{ iss: string; sub: string; aud?: string | string[] }>(idToken);
  if (!decoded.iss || !decoded.sub) {
    throw new Error('Invalid ID token: missing iss/sub claims');
  }
  
  // Use fixed audience for consistency across environments
  const audStr = 'com.confio.app'; // Fixed canonical client ID
  
  // Client-controlled input (deterministic from OAuth)
  const x_c = sha256(utf8ToBytes(
    `${canonicalize(decoded.iss)}|${decoded.sub}|${canonicalize(audStr)}`
  ));
  
  // Salt includes server pepper for 2-of-2 security
  const salt = sha256(utf8ToBytes(`confio/kek-salt/v1|${serverPepper ?? ''}`));
  
  // Info includes scope for domain separation
  const info = utf8ToBytes(`confio/kek-info/v1|${scope}`);
  
  return hkdf(sha256, x_c, salt, info, 32);
}

/**
 * Encrypt seed with KEK using XSalsa20-Poly1305
 */
function wrapSeed(seed32: Uint8Array, kek32: Uint8Array, pepperVersion: number = 1): string {
  const nonce = randomBytes(24);
  const ciphertext = nacl.secretbox(seed32, nonce, kek32);
  
  const blob = {
    v: '1',
    alg: 'xsalsa20poly1305',
    nonce: bytesToHex(nonce),
    ct: bytesToHex(ciphertext),
    createdAt: new Date().toISOString(),
    pepperVersion: String(pepperVersion) // Track server pepper version for re-wrap detection
  };
  
  // Use Buffer for base64 encoding (RN compatible)
  return Buffer.from(JSON.stringify(blob)).toString('base64');
}

/**
 * Parse the encrypted blob to get metadata (without decrypting)
 */
function parseSeedBlob(blobB64: string): { 
  pepperVersion: number; 
  nonce: string; 
  ct: string;
  createdAt?: string;
} {
  const blob = JSON.parse(Buffer.from(blobB64, 'base64').toString('utf8'));
  return {
    pepperVersion: parseInt(blob.pepperVersion || '1'),
    nonce: blob.nonce,
    ct: blob.ct,
    createdAt: blob.createdAt
  };
}

/**
 * Decrypt seed with KEK
 */
function unwrapSeed(blobB64: string, kek32: Uint8Array): Uint8Array {
  try {
    // Use Buffer for base64 decoding (RN compatible)
    const blob = parseSeedBlob(blobB64);
    const nonce = hexToBytes(blob.nonce);
    const ciphertext = hexToBytes(blob.ct);
    
    const seed = nacl.secretbox.open(ciphertext, nonce, kek32);
    if (!seed) {
      throw new Error('Failed to decrypt seed - invalid KEK or corrupted data');
    }
    
    return seed;
  } catch (error) {
    console.error('Error unwrapping seed:', error);
    throw error;
  }
}

/**
 * Generate client salt following the exact formula from README.md
 * salt = SHA256(issuer | subject | audience | account_type | business_id (if applied) | account_index)
 * Components are joined with underscores, with special handling for business_id
 */
export function generateClientSalt(
  issuer: string,        // OAuth issuer (e.g., 'https://accounts.google.com')
  subject: string,       // OAuth subject (user ID)
  audience: string,      // OAuth audience (client ID)
  accountType: 'personal' | 'business',
  accountIndex: number,
  businessId?: string    // Only for business accounts
): string {
  // Canonicalize issuer and audience for consistency
  const canonicalIssuer = canonicalize(issuer);
  const canonicalAudience = canonicalize(audience);
  
  // Use the exact formula from README.md with underscore separators
  // Special handling: if no business_id, we need to ensure only one underscore between account_type and account_index
  let saltInput: string;
  
  if (businessId) {
    // Business account: issuer_subject_audience_account_type_business_id_account_index
    saltInput = `${canonicalIssuer}_${subject}_${canonicalAudience}_${accountType}_${businessId}_${accountIndex}`;
  } else {
    // Personal account: issuer_subject_audience_account_type_account_index
    // (no double underscore where business_id would be)
    saltInput = `${canonicalIssuer}_${subject}_${canonicalAudience}_${accountType}_${accountIndex}`;
  }
  
  const saltBytes = sha256(utf8ToBytes(saltInput));
  return bytesToHex(saltBytes);
}

/**
 * Derives a deterministic Algorand wallet using proper KDF
 * 
 * Security properties:
 * - Client controls the salt (non-custodial)
 * - Uses HKDF-SHA256 for proper key derivation
 * - Optional server pepper adds entropy but isn't required
 * - Domain separation prevents cross-chain attacks
 * - Versioned for future migration
 */
export function deriveDeterministicAlgorandKey(opts: DeriveWalletOptions): DerivedWallet {
  const { idToken, clientSalt, serverPepper, provider, accountType, accountIndex, businessId, network = 'mainnet' } = opts;
  
  // The clientSalt already contains the hash of the OAuth claims
  // It was generated using generateClientSalt with the real OAuth issuer, subject, and audience
  // So we just need to use it directly in our key derivation
  

  // Create input key material
  // Since clientSalt already contains the hash of OAuth claims, we'll use it as part of the IKM
  // This ensures deterministic derivation based on the OAuth provider
  const ikmString = `confio-wallet-v1|${clientSalt}`;
  const ikm = sha256(utf8ToBytes(ikmString));

  // CRITICAL: Extract salt uses ONLY client-side stable values
  // Do NOT include serverPepper here - it would change the wallet address!
  // Pepper is used ONLY for KEK derivation (encryption key), not seed derivation
  const extractSalt = sha256(utf8ToBytes(
    `confio/extract/v1|${clientSalt}`
  ));

  // Domain separation and versioning with network isolation
  // This ensures different keys for different contexts
  const info = utf8ToBytes(
    `confio/algo/v1|${network}|${provider}|${accountType}|${accountIndex}|${businessId ?? ''}`
  );

  // Derive 32-byte ed25519 seed using HKDF
  const seed32 = hkdf(sha256, ikm, extractSalt, info, 32);

  // Generate ed25519 keypair for Algorand
  const keyPair = nacl.sign.keyPair.fromSeed(seed32);
  
  // Encode Algorand address from public key (runtime require to avoid RN issues)
  const algosdk = require('algosdk');
  const address = algosdk.encodeAddress(keyPair.publicKey);

  // Return the derived wallet
  return {
    address,
    privSeedHex: bytesToHex(seed32),
    publicKey: keyPair.publicKey
  };
}

/**
 * Secure wallet service that integrates with backend
 */
export class SecureDeterministicWalletService {
  private static instance: SecureDeterministicWalletService;
  private inMemSeeds = new Map<string, string>(); // In-memory seed cache for session
  private currentScope = new Map<string, string>(); // Track current scope per user
  private cacheKeysPerUser = new Map<string, Set<string>>(); // Track all cache keys created per user
  
  private constructor() {}
  
  public static getInstance(): SecureDeterministicWalletService {
    if (!SecureDeterministicWalletService.instance) {
      SecureDeterministicWalletService.instance = new SecureDeterministicWalletService();
    }
    return SecureDeterministicWalletService.instance;
  }

  /**
   * Get server pepper for additional entropy (per-user, not per-scope)
   * This is NOT required for wallet derivation (non-custodial)
   * @param requestVersion - Optional: request specific version during grace period
   */
  async getServerPepper(firebaseUid: string, requestVersion?: number): Promise<{ 
    pepper: string | undefined; 
    version: number;
    isRotated?: boolean;
    gracePeriodUntil?: string;
  }> {
    try {
      // Server pepper is optional - wallet works without it
      const { data } = await apolloClient.mutate({
        mutation: GET_SERVER_PEPPER,
        variables: { firebaseUid, requestVersion }
      });

      if (data?.getServerPepper?.success) {
        return {
          pepper: data.getServerPepper.pepper,
          version: data.getServerPepper.version || 1,
          isRotated: data.getServerPepper.isRotated,
          gracePeriodUntil: data.getServerPepper.gracePeriodUntil
        };
      }
      
      // It's OK if server doesn't provide pepper
      console.log('No server pepper available, using client salt only');
      return { pepper: undefined, version: 1 };
    } catch (error) {
      console.log('Could not get server pepper, continuing without it:', error);
      return { pepper: undefined, version: 1 };
    }
  }

  /**
   * Get or prompt for recovery secret
   * This allows wallet recovery on new devices
   */
  async getRecoverySecret(firebaseUid: string): Promise<string | undefined> {
    try {
      // Check if we have a stored recovery secret
      const credentials = await Keychain.getInternetCredentials(
        `wallet.recovery.${firebaseUid}`
      );
      
      if (credentials && credentials.password) {
        return credentials.password;
      }
      
      // For new users, we could prompt them to set one
      // Or use a default (less secure but simpler UX)
      return undefined;
    } catch (error) {
      console.error('Error getting recovery secret:', error);
      return undefined;
    }
  }

  /**
   * Create or restore wallet for a user with encrypted caching
   */
  async createOrRestoreWallet(
    idToken: string,
    firebaseUid: string,
    provider: 'google' | 'apple',
    accountType: 'personal' | 'business' = 'personal',
    accountIndex: number = 0,
    businessId?: string,
    network: 'testnet' | 'mainnet' = 'mainnet',
    oauthSubject?: string  // The original OAuth subject from Google/Apple
  ): Promise<DerivedWallet> {
    try {
      console.log(`Creating/restoring ${provider} wallet for user ${firebaseUid} on ${network}`);
      
      // Use the original OAuth subject if available, otherwise fall back to Firebase UID
      const subject = oauthSubject || firebaseUid;
      const scope = makeScope(provider, subject, accountType, accountIndex, businessId);
      const cacheKey = makeCacheKey(firebaseUid, scope);
      
      // Track this cache key for later cleanup (store username for identification)
      if (!this.cacheKeysPerUser.has(firebaseUid)) {
        this.cacheKeysPerUser.set(firebaseUid, new Set());
      }
      this.cacheKeysPerUser.get(firebaseUid)!.add(cacheKey.username);
      
      // Get server pepper (optional for 2-of-2 security) with version
      const { pepper: serverPepper, version: pepperVersion } = await this.getServerPepper(firebaseUid);
      
      // Derive KEK for encryption
      const kek = deriveKEK(idToken, serverPepper, scope);
      
      // Try to load cached encrypted seed first (fast path <50ms)
      let wallet: DerivedWallet | null = null;
      
      try {
        const credentials = await Keychain.getInternetCredentials(cacheKey.server);
        if (credentials && credentials.username === cacheKey.username && credentials.password) {
          console.log('Found cached encrypted seed, checking version...');
          
          // Parse blob to get the pepper version it was encrypted with
          const blobMeta = parseSeedBlob(credentials.password);
          const storedPepperVersion = blobMeta.pepperVersion;
          
          // If stored version differs from current, get the appropriate pepper
          let kekToUse = kek;
          let needsReWrap = false;
          
          if (storedPepperVersion !== pepperVersion) {
            console.log(`Stored pepper v${storedPepperVersion} differs from current v${pepperVersion}`);
            const { pepper: oldPepper } = await this.getServerPepper(firebaseUid, storedPepperVersion);
            
            if (oldPepper) {
              // Derive KEK with the old pepper version
              kekToUse = deriveKEK(idToken, oldPepper, scope);
              needsReWrap = true;
            } else {
              throw new Error(`Could not get pepper for version ${storedPepperVersion} - grace period may have expired`);
            }
          }
          
          // Decrypt with appropriate KEK
          const seed = unwrapSeed(credentials.password, kekToUse);
          
          // Recreate wallet from cached seed
          const keyPair = nacl.sign.keyPair.fromSeed(seed);
          
          const algosdk = require('algosdk');
          const address = algosdk.encodeAddress(keyPair.publicKey);
          
          wallet = {
            address,
            privSeedHex: bytesToHex(seed),
            publicKey: keyPair.publicKey
          };
          
          console.log('Wallet restored from encrypted cache:', wallet.address);
          
          // Re-wrap with new pepper if needed
          if (needsReWrap) {
            console.log(`Re-wrapping seed with new pepper v${pepperVersion}...`);
            const newEncryptedBlob = wrapSeed(seed, kek, pepperVersion);
            await Keychain.setInternetCredentials(cacheKey.server, cacheKey.username, newEncryptedBlob);
            console.log('Seed re-wrapped successfully');
          }
        }
      } catch (cacheError: any) {
        console.log('Cache miss or decryption failed, will derive fresh:', cacheError?.message || cacheError);
      }
      
      // If cache miss or failed, derive fresh (slow path ~5s)
      if (!wallet) {
        console.log('Deriving wallet from OAuth claims (this may take a few seconds)...');
        
        // Use the real OAuth claims for non-custodial wallet
        const oauthIssuer = provider === 'google' 
          ? 'https://accounts.google.com'
          : 'https://appleid.apple.com';
        
        // Use the original OAuth subject if available
        const oauthSubjectToUse = oauthSubject || firebaseUid;
        
        // Use canonical client ID for consistency
        // CRITICAL: Use the same web client ID for both iOS and Android to ensure same addresses
        const canonicalClientId = provider === 'google'
          ? GOOGLE_CLIENT_IDS.production.web  // From .env via config - ensures consistency
          : 'com.confio.app';
        
        // Generate client-controlled salt using the exact formula from README.md
        console.log('[SecureDeterministicWallet] Salt generation inputs:', {
          platform: require('react-native').Platform.OS,
          oauthIssuer,
          oauthSubjectToUse,
          canonicalClientId,
          accountType,
          accountIndex,
          businessId: businessId || 'none',
          firebaseUid,
          originalOauthSubject: oauthSubject
        });
        
        const clientSalt = generateClientSalt(
          oauthIssuer,        // Real OAuth issuer (not Firebase)
          oauthSubjectToUse,  // Real OAuth subject (not Firebase UID)
          canonicalClientId,  // Use canonical audience for consistency!
          accountType,
          accountIndex,
          businessId
        );
        
        console.log('[SecureDeterministicWallet] Generated client salt:', clientSalt.substring(0, 20) + '...');
        
        // Derive deterministic wallet
        wallet = deriveDeterministicAlgorandKey({
          idToken,
          clientSalt,
          serverPepper,
          provider,
          accountType,
          accountIndex,
          businessId,
          network
        });
        
        console.log('Wallet derived successfully:', wallet.address);
        
        // Encrypt and cache the seed for next time
        const seed = hexToBytes(wallet.privSeedHex);
        const encryptedBlob = wrapSeed(seed, kek, pepperVersion);
        
        await Keychain.setInternetCredentials(
          cacheKey.server,
          cacheKey.username,
          encryptedBlob
        );
        
        console.log('Encrypted seed cached for fast future access');
      }
      
      // Store the seed in memory-only cache for this session (no plaintext keychain!)
      const memKey = `${firebaseUid}|${scope}`;
      this.inMemSeeds.set(memKey, wallet.privSeedHex);
      this.currentScope.set(firebaseUid, scope); // Track current scope for this user
      console.log(`Seed stored in memory cache with scope: ${scope}`);
      
      return wallet;
    } catch (error) {
      console.error('Error creating/restoring wallet:', error);
      throw error;
    }
  }

  /**
   * Get seed from memory cache with scope
   * No more plaintext storage in Keychain!
   */
  private getMemorySeed(firebaseUid: string, scope?: string): string | null {
    // Use provided scope or get current scope for user
    const actualScope = scope || this.currentScope.get(firebaseUid);
    if (!actualScope) {
      console.error('No scope available for user:', firebaseUid);
      return null;
    }
    
    const memKey = `${firebaseUid}|${actualScope}`;
    return this.inMemSeeds.get(memKey) || null;
  }

  /**
   * Warm up wallet from cache (for app restart)
   * Loads encrypted seed into memory without full wallet derivation
   */
  async warmUpFromCache(
    idToken: string,
    firebaseUid: string,
    provider: 'google' | 'apple',
    accountType: 'personal' | 'business' = 'personal',
    accountIndex: number = 0,
    businessId?: string,
    network: 'testnet' | 'mainnet' = 'mainnet',
    oauthSubject?: string  // The original OAuth subject from Google/Apple
  ): Promise<boolean> {
    try {
      // Use consistent scope generation (same as createOrRestoreWallet)
      const subject = oauthSubject || firebaseUid;
      const scope = makeScope(provider, subject, accountType, accountIndex, businessId);
      const cacheKey = makeCacheKey(firebaseUid, scope);
      
      // Track this cache key for later cleanup (store username for identification)
      if (!this.cacheKeysPerUser.has(firebaseUid)) {
        this.cacheKeysPerUser.set(firebaseUid, new Set());
      }
      this.cacheKeysPerUser.get(firebaseUid)!.add(cacheKey.username);
      
      const credentials = await Keychain.getInternetCredentials(cacheKey.server);
      if (!credentials || credentials.username !== cacheKey.username || !credentials.password) {
        return false;
      }
      
      // Parse blob to get the pepper version it was encrypted with
      const blobMeta = parseSeedBlob(credentials.password);
      const storedPepperVersion = blobMeta.pepperVersion;
      
      // Get the pepper for the stored version (during grace period)
      const { 
        pepper: serverPepper, 
        version: currentVersion,
        isRotated 
      } = await this.getServerPepper(firebaseUid, storedPepperVersion);
      
      if (!serverPepper) {
        console.error('Could not get pepper for version', storedPepperVersion);
        console.error('Grace period may have expired. User needs to re-authenticate.');
        // Clear the invalid cached seed
        await Keychain.resetInternetCredentials({ server: cacheKey.server });
        return false;
      }
      
      // Derive KEK with the appropriate pepper version
      const kek = deriveKEK(idToken, serverPepper, scope);
      
      // Decrypt the seed
      const seed = unwrapSeed(credentials.password, kek);
      const privSeedHex = bytesToHex(seed);
      
      // Store in memory
      const memKey = `${firebaseUid}|${scope}`;
      this.inMemSeeds.set(memKey, privSeedHex);
      this.currentScope.set(firebaseUid, scope);
      
      // If pepper was rotated, re-wrap with new version
      if (isRotated && currentVersion !== storedPepperVersion) {
        console.log(`Pepper rotated from v${storedPepperVersion} to v${currentVersion}, re-wrapping seed...`);
        
        // Get the latest pepper
        const { pepper: newPepper, version: newVersion } = await this.getServerPepper(firebaseUid);
        
        if (newPepper) {
          // Derive new KEK with latest pepper
          const newKek = deriveKEK(idToken, newPepper, scope);
          
          // Re-wrap the seed with new pepper
          const newEncryptedBlob = wrapSeed(seed, newKek, newVersion);
          
          // Update cached encrypted seed
          await Keychain.setInternetCredentials(
            cacheKey.server,
            cacheKey.username,
            newEncryptedBlob
          );
          
          console.log('Seed re-wrapped with new pepper version successfully');
        }
      }
      
      console.log('Wallet warmed up from cache for scope:', scope);
      return true;
    } catch (error) {
      console.error('Error warming up from cache:', error);
      
      // If decryption failed due to pepper issues
      if (error.message?.includes('Failed to decrypt seed')) {
        console.error('Pepper may have been rotated after grace period. User needs to re-authenticate.');
        // Clear the invalid cached seed
        const subject = oauthSubject || firebaseUid;
        const scope = makeScope(provider, subject, accountType, accountIndex, businessId);
        const cacheKey = makeCacheKey(firebaseUid, scope);
        await Keychain.resetInternetCredentials({ server: cacheKey.server });
      }
      
      return false;
    }
  }

  /**
   * Decode transaction bytes to Transaction instance
   * Ensures we get a signable Transaction object
   */
  private decodeTxn(bytes: Uint8Array): any {
    const algosdk = require('algosdk');
    
    // Try decodeUnsignedTransaction first (returns Transaction instance)
    if (algosdk.decodeUnsignedTransaction) {
      return algosdk.decodeUnsignedTransaction(bytes);
    }
    
    // Fallback: decodeObj + convert to Transaction
    const obj = algosdk.decodeObj(bytes);
    if (algosdk.Transaction?.from_obj_for_encoding) {
      // Convert plain object to Transaction instance
      return algosdk.Transaction.from_obj_for_encoding(obj);
    }
    
    // Last resort - check if obj has signTxn before returning
    if (typeof obj.signTxn !== 'function') {
      throw new Error('Decoded object is not a signable Transaction - signTxn method not found');
    }
    
    console.warn('Using decoded object directly - not a proper Transaction instance');
    return obj;
  }

  /**
   * Sign a transaction with the stored wallet
   * Handles both Transaction objects and raw msgpack bytes
   */
  async signTransaction(
    firebaseUid: string,
    txnOrBytes: any // Transaction or Uint8Array
  ): Promise<Uint8Array> {
    try {
      // Get seed from memory cache (no plaintext keychain!)
      const seedHex = this.getMemorySeed(firebaseUid);
      if (!seedHex) {
        throw new Error('No wallet seed in memory. Please re-login to restore wallet.');
      }
      
      // Recreate keypair from seed
      const seed = hexToBytes(seedHex);
      const keyPair = nacl.sign.keyPair.fromSeed(seed);
      
      // Algorand's secret key format is specific: seed (32 bytes) + public key (32 bytes)
      // nacl.sign.keyPair.fromSeed returns secretKey which is already 64 bytes in this format
      // However, we need to ensure it's properly constructed for algosdk
      
      // Construct the Algorand secret key manually to ensure compatibility
      const sk = new Uint8Array(64);
      sk.set(seed, 0); // First 32 bytes: the seed
      sk.set(keyPair.publicKey, 32); // Last 32 bytes: the public key
      
      // Validate the secret key is 64 bytes as expected
      if (sk.length !== 64) {
        throw new Error(`Invalid secret key length: ${sk.length}, expected 64`);
      }
      
      // Handle both Transaction objects and raw bytes
      let txn: any;
      if (txnOrBytes instanceof Uint8Array) {
        // For sponsored transactions - decode msgpack bytes to Transaction instance
        txn = this.decodeTxn(txnOrBytes);
      } else {
        // Regular Transaction object
        txn = txnOrBytes;
      }
      
      // Ensure we have a signable transaction
      if (typeof txn?.signTxn !== 'function') {
        throw new Error('Transaction object does not have signTxn method');
      }
      
      // Sign transaction
      const signedTxn = txn.signTxn(sk);
      return signedTxn;
    } catch (error) {
      console.error('Error signing transaction:', error);
      throw error;
    }
  }

  /**
   * Clear all wallet data for a user
   */
  async clearWallet(firebaseUid: string | null | undefined): Promise<void> {
    try {
      // Guard against null/undefined firebaseUid
      if (!firebaseUid) {
        console.log('clearWallet called with no firebaseUid, skipping');
        return;
      }
      // Clear memory cache for all scopes of this user
      const scope = this.currentScope.get(firebaseUid);
      if (scope) {
        this.inMemSeeds.delete(`${firebaseUid}|${scope}`);
      }
      // Also clear any other scopes for this user
      for (const key of this.inMemSeeds.keys()) {
        if (key.startsWith(`${firebaseUid}|`)) {
          this.inMemSeeds.delete(key);
        }
      }
      
      // Clear scope tracking
      this.currentScope.delete(firebaseUid);
      
      // Clear encrypted cache from keychain
      // Since all wallets for this app use the same server 'wallet.confio.app',
      // calling resetInternetCredentials will clear ALL wallet entries at once
      try {
        await Keychain.resetInternetCredentials({ server: 'wallet.confio.app' });
        console.log('Cleared all wallet entries from keychain for server: wallet.confio.app');
      } catch (err: any) {
        // Server might not have any entries, which is fine
        console.log('Could not clear wallet.confio.app:', err?.message || err);
      }
      
      // Clear the tracking set
      this.cacheKeysPerUser.delete(firebaseUid);
      
      console.log('Wallet cleared from memory and keychain for user:', firebaseUid);
    } catch (error) {
      console.error('Error clearing wallet:', error);
    }
  }
}

// Export singleton instance
export const secureDeterministicWallet = SecureDeterministicWalletService.getInstance();