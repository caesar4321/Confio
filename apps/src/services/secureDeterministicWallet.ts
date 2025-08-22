/**
 * Secure Deterministic Wallet Service
 * 
 * Implements a truly non-custodial approach where:
 * 1. Client generates deterministic salt from OAuth claims + server pepper
 * 2. Server provides additional entropy (pepper) used inside the salt
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
import { apolloClient, AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { gql } from '@apollo/client';
import { randomBytes } from '@noble/hashes/utils';
import { Buffer } from 'buffer'; // RN polyfill for base64
import { CONFIO_DERIVATION_SPEC } from './derivationSpec';

// GraphQL mutations for peppers (per-account, derived from JWT context)
const GET_DERIVATION_PEPPER = gql`
  mutation GetDerivationPepper {
    getDerivationPepper {
      success
      pepper
      error
    }
  }
`;

const GET_KEK_PEPPER = gql`
  mutation GetKekPepper($requestVersion: Int) {
    getKekPepper(requestVersion: $requestVersion) {
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
 * Uses account context (type + index + businessId) as the identifier
 */
function makeCacheKey(accountType: string, accountIndex: number, businessId?: string): { server: string; username: string } {
  // Use a consistent server name like other services in the codebase
  // Create a unique identifier based on account context
  const accountId = businessId 
    ? `${accountType}_${businessId}_${accountIndex}`
    : `${accountType}_${accountIndex}`;
  
  return {
    server: 'wallet.confio.app',
    username: accountId.replace(/[^a-zA-Z0-9_]/g, '_')
  };
}

export interface DeriveWalletOptions {
  clientSalt: string;           // Client-generated deterministic salt (hash of OAuth claims; no pepper)
  derivationPepper: string;     // Non-rotating derivation pepper (HKDF extract salt)
  provider: 'google' | 'apple';
  accountType: 'personal' | 'business';
  accountIndex: number;         // 0, 1, 2...
  businessId?: string;          // when applicable
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
 * Uses OAuth claims + server pepper
 */
function deriveKEK(
  iss: string,
  sub: string,
  aud: string,
  serverPepper: string | undefined,
  scope: string
): Uint8Array {
  // Client-controlled input (deterministic from OAuth)
  // Use the actual audience claim passed in (Google web client ID or Apple bundle ID)
  const x_c = sha256(utf8ToBytes(
    `${canonicalize(iss)}|${sub}|${canonicalize(aud)}`
  ));
  
  // Salt includes server pepper for 2-of-2 security
  const salt = sha256(utf8ToBytes(`${CONFIO_DERIVATION_SPEC.kekSalt}|${serverPepper ?? ''}`));
  
  // Info includes scope for domain separation
  const info = utf8ToBytes(`${CONFIO_DERIVATION_SPEC.kekInfo}|${scope}`);
  
  return hkdf(sha256, x_c, salt, info, 32);
}

/**
 * Encrypt seed with KEK using XSalsa20-Poly1305
 */
function wrapSeed(
  seed32: Uint8Array,
  kek32: Uint8Array,
  pepperVersion: number = 1,
  meta?: { derivationPepperHash?: string; scope?: string; saltFingerprint?: string }
): string {
  const nonce = randomBytes(24);
  const ciphertext = nacl.secretbox(seed32, nonce, kek32);
  
  const blob = {
    v: '1',
    alg: 'xsalsa20poly1305',
    nonce: bytesToHex(nonce),
    ct: bytesToHex(ciphertext),
    createdAt: new Date().toISOString(),
    pepperVersion: String(pepperVersion), // Track server pepper version for re-wrap detection
    // Track derivation metadata to detect changes
    dp: meta?.derivationPepperHash || null,
    scope: meta?.scope || null,
    sf: meta?.saltFingerprint || null
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
  dp?: string | null;
  scope?: string | null;
  sf?: string | null;
} {
  const blob = JSON.parse(Buffer.from(blobB64, 'base64').toString('utf8'));
  return {
    pepperVersion: parseInt(blob.pepperVersion || '1'),
    nonce: blob.nonce,
    ct: blob.ct,
    createdAt: blob.createdAt,
    dp: blob.dp ?? null,
    scope: blob.scope ?? null,
    sf: blob.sf ?? null
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
    // Don't log as error since this is expected when cache is invalid
    // The calling code will handle this gracefully
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
 * - Domain separation prevents cross-chain attacks
 * - Versioned for future migration
 */
export function deriveDeterministicAlgorandKey(opts: DeriveWalletOptions): DerivedWallet {
  const { clientSalt, derivationPepper, provider, accountType, accountIndex, businessId } = opts;
  
  // The clientSalt already contains the hash of the OAuth claims
  // It was generated using generateClientSalt with the real OAuth issuer, subject, and audience
  // So we just need to use it directly in our key derivation
  

  // Create input key material
  // Since clientSalt already contains the hash of OAuth claims, we'll use it as part of the IKM
  // This ensures deterministic derivation based on the OAuth provider
  const ikmString = `${CONFIO_DERIVATION_SPEC.root}|${clientSalt}`;
  const ikm = sha256(utf8ToBytes(ikmString));

  // Use derivation pepper as HKDF extract salt (domain-separated)
  const extractSalt = sha256(utf8ToBytes(
    `${CONFIO_DERIVATION_SPEC.extract}|${derivationPepper}`
  ));

  // Domain separation and versioning
  // This ensures different keys for different contexts
  // Removed network to keep salt consistent across environments
  const info = utf8ToBytes(
    `${CONFIO_DERIVATION_SPEC.algoInfoPrefix}|${provider}|${accountType}|${accountIndex}|${businessId ?? ''}`
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
  // Session caches to avoid repeated GraphQL/keychain overhead
  private cachedDerivationPepper?: string;
  private cachedKekPepperByVersion: Map<number, string> = new Map();
  
  private constructor() {}
  
  public static getInstance(): SecureDeterministicWalletService {
    if (!SecureDeterministicWalletService.instance) {
      SecureDeterministicWalletService.instance = new SecureDeterministicWalletService();
    }
    return SecureDeterministicWalletService.instance;
  }

  async getDerivationPepper(): Promise<{ pepper: string | undefined }> {
    try {
      // Fast path: return from session cache
      if (this.cachedDerivationPepper) {
        return { pepper: this.cachedDerivationPepper };
      }
      // Require JWT to be present; otherwise skip
      try {
        const creds = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        if (!creds) {
          return { pepper: undefined };
        }
      } catch (_) {
        return { pepper: undefined };
      }
      const { data } = await apolloClient.mutate({ mutation: GET_DERIVATION_PEPPER });
      if (data?.getDerivationPepper?.success) {
        this.cachedDerivationPepper = data.getDerivationPepper.pepper;
        return { pepper: this.cachedDerivationPepper };
      }
      console.debug('Derivation pepper not provided');
      return { pepper: undefined };
    } catch (_) {
      console.debug('Skipping derivation pepper due to fetch error');
      return { pepper: undefined };
    }
  }

  async getKekPepper(requestVersion?: number): Promise<{ 
    pepper: string | undefined; 
    version: number;
    isRotated?: boolean;
    gracePeriodUntil?: string;
  }> {
    try {
      const versionToUse = requestVersion || 1;
      // Fast path: return from session cache for requested version
      if (this.cachedKekPepperByVersion.has(versionToUse)) {
        return { pepper: this.cachedKekPepperByVersion.get(versionToUse), version: versionToUse } as any;
      }
      // Require JWT to be present; otherwise skip
      try {
        const creds = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        if (!creds) {
          return { pepper: undefined, version: 1 };
        }
      } catch (_) {
        return { pepper: undefined, version: 1 };
      }
      const { data } = await apolloClient.mutate({ mutation: GET_KEK_PEPPER, variables: { requestVersion: versionToUse } });

      if (data?.getKekPepper?.success) {
        const pepper = data.getKekPepper.pepper;
        const version = data.getKekPepper.version || versionToUse || 1;
        if (pepper && version) {
          this.cachedKekPepperByVersion.set(version, pepper);
        }
        return {
          pepper: data.getKekPepper.pepper,
          version,
          isRotated: data.getKekPepper.isRotated,
          gracePeriodUntil: data.getKekPepper.gracePeriodUntil
        };
      }
      console.debug('KEK pepper not provided');
      return { pepper: undefined, version: 1 };
    } catch (error) {
      console.debug('Skipping KEK pepper due to fetch error');
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
   * Server will get user context from JWT token
   */
  async createOrRestoreWallet(
    iss: string,  // OAuth issuer (https://accounts.google.com or https://appleid.apple.com)
    sub: string,  // OAuth subject from Google/Apple
    aud: string,  // OAuth audience (client ID)
    provider: 'google' | 'apple',
    accountType: 'personal' | 'business' = 'personal',
    accountIndex: number = 0,
    businessId?: string,
    firebaseIdToken?: string
  ): Promise<DerivedWallet> {
    const startTime = Date.now();
    const perfLog = (step: string) => {
      console.log(`[WALLET-PERF] ${step}: ${Date.now() - startTime}ms`);
    };
    
    try {
      console.log(`Creating/restoring ${provider} wallet for account ${accountType}_${accountIndex}`);
      perfLog('Start');
      
      // Use the OAuth subject for deterministic derivation
      const scope = makeScope(provider, sub, accountType, accountIndex, businessId);
      const cacheKey = makeCacheKey(accountType, accountIndex, businessId);
      
      // Store current scope for this session
      this.currentScope.set('current', scope);
      
      // Get derivation pepper (REQUIRED for derivation salt)
      perfLog('Before derivation pepper');
      const { pepper: derivPepper } = await this.getDerivationPepper({
        firebaseIdToken,
        accountType,
        accountIndex,
        businessId
      });
      perfLog('Got derivation pepper');
      if (!derivPepper) {
        throw new Error('Missing derivation pepper: cannot derive wallet without pepper. Ensure authentication and network are available.');
      }

      // Get KEK pepper (for encryption)
      perfLog('Before KEK pepper');
      const { pepper: kekPepper, version: pepperVersion } = await this.getKekPepper(undefined, {
        firebaseIdToken,
        accountType,
        accountIndex,
        businessId
      });
      perfLog('Got KEK pepper');
      
      // Derive KEK for encryption
      const kek = deriveKEK(iss, sub, aud, kekPepper, scope);
      
      // Prepare fingerprints to validate cache correctness
      const canonicalIssuer = canonicalize(iss);
      const canonicalAudience = canonicalize(aud);
      const saltInput = businessId
        ? `${canonicalIssuer}_${sub}_${canonicalAudience}_${accountType}_${businessId}_${accountIndex}`
        : `${canonicalIssuer}_${sub}_${canonicalAudience}_${accountType}_${accountIndex}`;
      const saltFingerprint = bytesToHex(sha256(utf8ToBytes(saltInput)));

      // Try to load cached encrypted seed first (fast path <50ms)
      let wallet: DerivedWallet | null = null;
      const currentScope = scope;
      const derivPepperHash = bytesToHex(sha256(utf8ToBytes(String(derivPepper))));
      
      try {
        perfLog('Checking cache');
        const credentials = await Keychain.getInternetCredentials(cacheKey.server);
        if (credentials && credentials.username === cacheKey.username && credentials.password) {
          console.log('Found cached encrypted seed, checking version...');
          
          // Parse blob to get the pepper version it was encrypted with
          const blobMeta = parseSeedBlob(credentials.password);
          const storedPepperVersion = blobMeta.pepperVersion;
          const storedDerivPepperHash = blobMeta.dp || null;
          const storedScope = blobMeta.scope || null;
          const storedSaltFingerprint = blobMeta.sf || null;
          
          // If stored version differs from current, get the appropriate pepper
          let kekToUse = kek;
          let needsReWrap = false;
          
          if (storedPepperVersion !== pepperVersion) {
            console.log(`Stored pepper v${storedPepperVersion} differs from current v${pepperVersion}`);
            const { pepper: oldPepper } = await this.getKekPepper(storedPepperVersion);
            
            if (oldPepper) {
              // Derive KEK with the old pepper version
              kekToUse = deriveKEK(iss, sub, aud, oldPepper, scope);
              needsReWrap = true;
            } else {
              throw new Error(`Could not get pepper for version ${storedPepperVersion} - grace period may have expired`);
            }
          }
          
          // Decrypt with appropriate KEK
          const seed = unwrapSeed(credentials.password, kekToUse);

          // Validate derivation metadata; if missing or mismatched, force re-derive
          let derivationMatches = true;
          if (!storedDerivPepperHash || storedDerivPepperHash !== derivPepperHash) {
            derivationMatches = false;
            console.log('Derivation fingerprint mismatch or missing; will derive fresh');
          }
          if (storedScope && storedScope !== currentScope) {
            derivationMatches = false;
            console.log('Cached scope differs; will derive fresh');
          }
          if (!storedSaltFingerprint || storedSaltFingerprint !== saltFingerprint) {
            derivationMatches = false;
            console.log('Salt fingerprint mismatch or missing; will derive fresh');
          }
          
          if (derivationMatches) {
            // Recreate wallet from cached seed
            const keyPair = nacl.sign.keyPair.fromSeed(seed);
            const algosdk = require('algosdk');
            const address = algosdk.encodeAddress(keyPair.publicKey);
            wallet = {
              address,
              privSeedHex: bytesToHex(seed),
              publicKey: keyPair.publicKey
            };
            perfLog('Wallet restored from cache');
            console.log('Wallet restored from encrypted cache:', wallet.address);
          } else {
            // Treat as cache miss
            throw new Error('Stale derivation cache');
          }
          
          // Re-wrap with new pepper if needed
          if (needsReWrap) {
            console.log(`Re-wrapping seed with new pepper v${pepperVersion}...`);
            const newEncryptedBlob = wrapSeed(seed, kek, pepperVersion, { derivationPepperHash: derivPepperHash, scope: currentScope, saltFingerprint });
            await Keychain.setInternetCredentials(
              cacheKey.server, 
              cacheKey.username, 
              newEncryptedBlob,
              {
                accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY
              }
            );
            console.log('Seed re-wrapped successfully');
          }
        }
      } catch (cacheError: any) {
        // This is expected behavior when cache is invalid or KEK has changed
        console.log('Cache miss or decryption failed, will derive fresh:', cacheError?.message || cacheError);
      }
      
      // If cache miss or failed, derive fresh (slow path ~5s)
      if (!wallet) {
        perfLog('Cache miss - deriving fresh');
        console.log('Deriving wallet from OAuth claims (this may take a few seconds)...');
        
        // Use the OAuth claims directly
        
      // Generate client-controlled salt using the exact formula from README.md (no pepper inside)
        console.log('[SecureDeterministicWallet] Salt generation inputs:', {
          platform: require('react-native').Platform.OS,
          iss,
          sub,
          aud,
          accountType,
          accountIndex,
          businessId: businessId || 'none'
        });
        
        console.log('[SecureDeterministicWallet] Calling generateClientSalt with business_id:', businessId || 'undefined');
        
        const clientSalt = generateClientSalt(
          iss,        // OAuth issuer
          sub,        // OAuth subject
          aud,        // OAuth audience (client ID)
          accountType,
          accountIndex,
          businessId
        );
        
        console.log('[SecureDeterministicWallet] Generated client salt:', {
          saltPrefix: clientSalt.substring(0, 20) + '...',
          accountType,
          accountIndex,
          businessId: businessId || 'none',
          saltInputWouldBe: businessId 
            ? `${iss}_${sub}_${aud}_${accountType}_${businessId}_${accountIndex}`
            : `${iss}_${sub}_${aud}_${accountType}_${accountIndex}`
        });
        
        // Derive deterministic wallet
        perfLog('Starting key derivation');
        wallet = deriveDeterministicAlgorandKey({
          clientSalt,
          derivationPepper: derivPepper,
          provider,
          accountType,
          accountIndex,
          businessId
        });
        
        perfLog('Key derivation complete');
        console.log('Wallet derived successfully:', wallet.address);
        
        // Encrypt and cache the seed for next time
        perfLog('Encrypting for cache');
        const seed = hexToBytes(wallet.privSeedHex);
        const encryptedBlob = wrapSeed(seed, kek, pepperVersion, { derivationPepperHash: derivPepperHash, scope: currentScope, saltFingerprint });
        
        await Keychain.setInternetCredentials(
          cacheKey.server,
          cacheKey.username,
          encryptedBlob,
          {
            accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY
          }
        );
        
        console.log('Encrypted seed cached for fast future access');
      }
      
      // Store the seed in memory-only cache for this session (no plaintext keychain!)
      const memKey = scope; // Just use scope as the key, no user ID needed
      this.inMemSeeds.set(memKey, wallet.privSeedHex);
      this.currentScope.set('current', scope); // Track current scope
      console.log(`Seed stored in memory cache with scope: ${scope}`);
      
      perfLog('Total wallet generation time');
      return wallet;
    } catch (error) {
      console.error('Error creating/restoring wallet:', error);
      throw error;
    }
  }

  // REMOVED: getMemorySeed method - not used anywhere and referenced Firebase UID
  // Keeping empty method to avoid breaking any potential references
  private getMemorySeed(userId: string, scope?: string): string | null {
    console.warn('getMemorySeed is deprecated and should not be used');
    return null;
  }

  /**
   * Decode transaction bytes to Transaction instance
   * Ensures we get a signable Transaction object
   */
  private decodeTxn(bytes: Uint8Array): any {
    const algosdk = require('algosdk');
    
    console.log(`[SecureDeterministicWallet] Decoding transaction of ${bytes.length} bytes`);
    console.log(`[SecureDeterministicWallet] First 10 bytes: ${Array.from(bytes.slice(0, 10)).map(b => '0x' + b.toString(16).padStart(2, '0')).join(' ')}`);
    
    try {
      // Use algosdk's decodeUnsignedTransaction which returns a proper Transaction instance
      // This handles all the field mapping correctly
      const txn = algosdk.decodeUnsignedTransaction(bytes);
      
      // Verify it has the signTxn method
      if (typeof txn.signTxn !== 'function') {
        throw new Error('Decoded transaction does not have signTxn method');
      }
      
      return txn;
    } catch (error) {
      console.error('[SecureDeterministicWallet] Failed to decode transaction:', error);
      console.error('[SecureDeterministicWallet] Bytes that failed:', bytes);
      throw error;
    }
  }

  /**
   * Sign a transaction with the stored wallet
   * Handles both Transaction objects and raw msgpack bytes
   */
  async signTransaction(
    txnOrBytes: any // Transaction or Uint8Array
  ): Promise<Uint8Array> {
    try {
      // Get seed from memory cache using the current scope
      const currentScope = this.currentScope.get('current');
      if (!currentScope) {
        throw new Error('No active wallet scope. Please switch to an account first.');
      }
      
      const seedHex = this.inMemSeeds.get(currentScope);
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
    } catch (error: any) {
      const msg = String(error?.message || error);
      if (msg.includes('No active wallet scope')) {
        console.info('[WALLET][INFO] No active wallet scope (will restore/create wallet and retry)');
      } else if (msg.includes('No wallet seed in memory')) {
        console.info('[WALLET][INFO] No wallet seed in memory (will restore/create wallet and retry)');
      } else {
        console.error('Error signing transaction:', error);
      }
      throw error;
    }
  }

  /**
   * Clear ALL wallet data (we don't support multi-user on same device)
   * This is called on sign-out to ensure complete cleanup
   */
  async clearWallet(): Promise<void> {
    try {
      console.log('Clearing ALL wallet data from memory and keychain...');
      
      // Clear ALL in-memory seeds (no multi-user support)
      this.inMemSeeds.clear();
      
      // Clear ALL scope tracking
      this.currentScope.clear();
      
      // Clear ALL user tracking
      this.cacheKeysPerUser.clear();
      
      // Clear ALL encrypted cache from keychain
      // Since all wallets for this app use the same server 'wallet.confio.app',
      // calling resetInternetCredentials will clear ALL wallet entries at once
      try {
        await Keychain.resetInternetCredentials({ server: 'wallet.confio.app' });
        console.log('Cleared ALL wallet entries from keychain for server: wallet.confio.app');
      } catch (err: any) {
        // Server might not have any entries, which is fine
        console.log('Could not clear wallet.confio.app:', err?.message || err);
      }
      
      console.log('ALL wallet data cleared from memory and keychain');
    } catch (error) {
      console.error('Error clearing wallet:', error);
    }
  }
}

// Export singleton instance
export const secureDeterministicWallet = SecureDeterministicWalletService.getInstance();
