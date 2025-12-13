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
import { CONFIO_DERIVATION_SPEC } from './derivationSpec';
import { base64ToBytes, bytesToBase64, stringToUtf8Bytes } from '../utils/encoding';

const decodeUtf8 = (bytes: Uint8Array): string => {
  if (typeof TextDecoder !== 'undefined') {
    return new TextDecoder().decode(bytes);
  }
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    out += String.fromCharCode(bytes[i]);
  }
  return out;
};

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

  // Encode to base64 without relying on Buffer
  return bytesToBase64(stringToUtf8Bytes(JSON.stringify(blob)));
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
  const blob = JSON.parse(decodeUtf8(base64ToBytes(blobB64)));
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

  // Debug: trace derivation inputs without exposing secrets
  try {
    const derivPepperHash = bytesToHex(sha256(utf8ToBytes(String(derivationPepper))));
    console.log('[Derive][DEBUG] Inputs:', {
      provider,
      accountType,
      accountIndex,
      businessId: businessId ?? 'none',
      clientSaltPrefix: clientSalt.substring(0, 20) + '...',
      derivationPepperHashPrefix: derivPepperHash.substring(0, 16) + '...',
      extractSaltPrefix: bytesToHex(extractSalt).substring(0, 16) + '...',
      infoString: `${CONFIO_DERIVATION_SPEC.algoInfoPrefix}|${provider}|${accountType}|${accountIndex}|${businessId ?? ''}`,
    });
  } catch (e) {
    // best-effort debug only
  }

  // Derive 32-byte ed25519 seed using HKDF
  const seed32 = hkdf(sha256, ikm, extractSalt, info, 32);

  // Generate ed25519 keypair for Algorand
  const keyPair = nacl.sign.keyPair.fromSeed(seed32);

  // Encode Algorand address from public key (runtime require to avoid RN issues)
  const algosdk = require('algosdk');
  const address = algosdk.encodeAddress(keyPair.publicKey);

  // Debug: show derived address summary
  console.log('[Derive][DEBUG] Derived Algorand address:', address);

  return {
    address,
    privSeedHex: bytesToHex(seed32),
    publicKey: keyPair.publicKey
  };
}

// ============================================================================
// V2 CLIENT SECRET MANAGEMENT
// CRITICAL: Random ONCE + Persist + NEVER Overwrite
// ============================================================================

// Mutex to prevent race conditions during secret creation
let v2SecretMutex: Promise<void> = Promise.resolve();

/**
 * Generate a random V2 client secret using CSPRNG.
 * INTERNAL USE ONLY
 */
function generateRandomSecret(): Uint8Array {
  return randomBytes(32);
}

/**
 * Get-or-Create Master Secret.
 * 
 * ALIAS: confio_master_secret_{hash(userId)}
 * 
 * LOGIC:
 * 1. PERSISTENCE: Tries to read existing namespaced secret.
 * 2. MIGRATION: If missing, checks legacy global key. If found, copies it to namespaced key.
 * 3. GENERATION: If neither, generates 32 bytes of CSPRNG entropy (Random).
 * 4. SAFETY: Read-after-Write verification ensures persistence.
 * 
 * @param userSub - Unique user identifier (OAuth Subject) to namespace the secret
 * @returns The master secret (32 bytes)
 */
export async function getOrCreateMasterSecret(userSub: string, accessToken?: string): Promise<Uint8Array> {
  if (!userSub) {
    throw new Error('[MasterSecret] User Sub (OAuth ID) is required to secure the master secret.');
  }

  // Namespace the key for multi-user safety
  const safeSub = bytesToHex(sha256(utf8ToBytes(userSub)));
  // ROTATION: Using 'v2' suffix to obtain the CLEAN, ISOLATED key (ignoring previous corrupted state)
  const alias = `confio_master_secret_v2_${safeSub}`;
  const driveFilename = `confio_master_secret_v2_${safeSub}.json`; // JSON for drive
  const legacyAlias = 'confio_master_secret';

  console.log(`[MasterSecret] UserHash=${safeSub.substring(0, 8)}... Alias=${alias}`);

  // Mutex: wait for any in-progress creation to avoid race conditions
  await v2SecretMutex;

  let resolveCurrentMutex: () => void;
  v2SecretMutex = new Promise(resolve => { resolveCurrentMutex = resolve; });

  try {
    const { credentialStorage } = await import('./credentialStorage');
    const { googleDriveStorage } = await import('./googleDriveStorage');
    const AES = require('crypto-js/aes');
    const Utf8 = require('crypto-js/enc-utf8');

    // SECURITY: App-Side Encryption Key (Obfuscation Layer)
    // Prevents "Casual Snooping" or accidental modification in Drive UI.
    // NOTE: This is "Security by Obfuscation" as the key is in the app, but protects against server-side peeking.
    const APP_BACKUP_KEY = 'ConfioWallet_Backup_Key_v1_DoNotShare';

    // HEADER: Warning message strictly for human readers opening the file in Drive UI
    const DRIVE_SECURITY_HEADER = 'ADVERTENCIA DE SEGURIDAD: NUNCA COMPARTAS ESTA CLAVE CON NADIE, NI SIQUIERA CON SOPORTE. CONFÍO NUNCA TE PEDIRÁ ESTA CLAVE.';

    // =================================================================================
    // HYBRID CLOUD LOGIC (Android & iOS - Roaming/Multi-User)
    // Master Source: Google Drive (Encrypted)
    // Slave Source: Local Storage (BlockStore/Keychain)
    // =================================================================================
    if (accessToken) {
      console.log('[MasterSecret] AccessToken detected. Attempting Drive Sync...');
      try {
        // 1. Try to fetch from Drive (The Master Source)
        const files = await googleDriveStorage.listFiles(accessToken, driveFilename);

        if (files.length > 0) {
          console.log('[MasterSecret] Found backup in Drive! Downloading...');
          const fileId = files[0].id;
          const encryptedContent = await googleDriveStorage.downloadFile(accessToken, fileId);

          if (encryptedContent && encryptedContent.length > 10) {
            try {
              // DECRYPT: App Key
              console.log('[MasterSecret] Decrypting backup...');

              // PARSE: Strip header if present (Take the last non-empty line)
              // The file might contain the Security Warning on the first line.
              let contentToDecrypt = encryptedContent.trim();
              if (contentToDecrypt.includes('ADVERTENCIA') || contentToDecrypt.includes('\n')) {
                const lines = contentToDecrypt.split('\n');
                // The secret is the Encrypted Base64 string, usually the last line.
                contentToDecrypt = lines[lines.length - 1].trim();
              }

              const bytes = AES.decrypt(contentToDecrypt, APP_BACKUP_KEY);
              const originalSecretBase64 = bytes.toString(Utf8);

              if (!originalSecretBase64) throw new Error('Decryption resulted in empty string');

              const secretBytes = base64ToBytes(originalSecretBase64);

              // Sync DOWN to Local Cache
              console.log('[MasterSecret] Syncing Drive (Decrypted) -> Local Storage...');
              await credentialStorage.storeSecret(alias, secretBytes);
              return secretBytes;
            } catch (decryptErr) {
              console.error('[MasterSecret] Decryption Failed! Key mismatch or corrupted file.', decryptErr);
              // If decryption fails, we CANNOT use this file. We must fallback to local or user is stuck.
              // Dangerous to overwrite local if Drive is corrupt. 
              // We fall through to check local.
            }
          }
        } else {
          console.log('[MasterSecret] No backup in Drive.');
        }

        // 2. If not in Drive (or Decrypt Failed), check Local Cache
        // If found locally, we should UPLOAD it to Drive (Sync UP)
        const localSecret = await credentialStorage.retrieveSecret(alias);
        if (localSecret) {
          console.log('[MasterSecret] Found Local Secret. Uploading to Drive (Sync UP / Encrypted)...');
          const secretBase64 = bytesToBase64(localSecret);

          // ENCRYPT: App Key
          const encryptedBody = AES.encrypt(secretBase64, APP_BACKUP_KEY).toString();
          // HEADER: Add warning for humans
          const finalContent = `${DRIVE_SECURITY_HEADER}\n${encryptedBody}`;

          await googleDriveStorage.createFile(accessToken, driveFilename, finalContent);
          console.log('[MasterSecret] Sync UP Complete (Encrypted).');
          return localSecret;
        }

      } catch (driveErr) {
        console.warn('[MasterSecret] Drive Sync Failed (Network/Auth):', driveErr);
        // Fallthrough to Local Logic (Offline Mode)
      }
    }
    // =================================================================================

    // Step 1: Try to retrieve existing NAMESPACED secret FIRST (Local)
    const existingSecret = await credentialStorage.retrieveSecret(alias);
    if (existingSecret) {
      console.log(`[MasterSecret] Found existing namespaced secret (Length=${existingSecret.length})`);
      // If we are here and have accessToken, it means Sync UP might have failed previously or Drive was unreachable.
      // We could try async background upload here, but for now just return.
      return existingSecret;
    } else {
      console.log('[MasterSecret] No existing secret found at alias:', alias);
    }

    // Step 1.5: Check LEGACY global secret (Migration Path)
    // If we have a legacy secret but no namespaced one, we migrate it.
    console.log('[MasterSecret] Namespaced secret missing. Checking legacy global secret...');
    const legacySecret = await credentialStorage.retrieveSecret(legacyAlias);

    // Only accept 32-byte secrets. This filters out tombstones or corrupted data.
    if (legacySecret && legacySecret.length === 32) {
      console.log('[MasterSecret] Found legacy global secret. Migrating to namespaced key...');
      // Copy legacy secret to new alias
      await credentialStorage.storeSecret(alias, legacySecret);

      // Verify persistence of migration
      const verifiedMigration = await credentialStorage.retrieveSecret(alias);
      if (!verifiedMigration) {
        throw new Error('[MasterSecret] Migration failed: Could not read back migrated secret.');
      }

      // CRITICAL: Poison AND Delete legacy secret.
      // 1. Overwrite with tombstone to ensure even if delete fails, next read gets invalid data.
      await credentialStorage.storeSecret(legacyAlias, utf8ToBytes('MIGRATED_TOMBSTONE'));
      // 2. Delete it.
      await credentialStorage.deleteSecret(legacyAlias);
      console.log('[MasterSecret] Legacy global secret POISONED and DELETED from shared storage.');

      return legacySecret;
    } else if (legacySecret) {
      console.warn('[MasterSecret] Found legacy secret but invalid length (Tombstone?). Ignoring.');
    }

    // Step 2: No existing secret (Namespace or Legacy) - generate new random one
    console.log('[MasterSecret] No existing secret. Generating NEW random CSPRNG secret...');
    const newSecret = generateRandomSecret();

    // Step 3: Store it
    await credentialStorage.storeSecret(alias, newSecret);

    // HYBRID CLOUD SYNC: New Secret Created -> Upload to Drive
    // (Encrypted with App Key)
    if (accessToken) {
      try {
        console.log('[MasterSecret] New secret generated. Uploading to Drive (Sync UP / Encrypted)...');
        const secretBase64 = bytesToBase64(newSecret);

        // ENCRYPT: App Key
        const encryptedBody = AES.encrypt(secretBase64, APP_BACKUP_KEY).toString();
        // HEADER: Add warning for humans
        const finalContent = `${DRIVE_SECURITY_HEADER}\n${encryptedBody}`;

        await googleDriveStorage.createFile(accessToken, driveFilename, finalContent);
        console.log('[MasterSecret] Drive Upload Complete (Encrypted).');
      } catch (upErr) {
        console.warn('[MasterSecret] Failed to upload new secret to Drive:', upErr);
        // Non-fatal: Local storage succeeded, so we continue. Future launches will retry Sync UP.
      }
    }

    // Step 4: Verify read-after-write (Critical Safety Guard)
    const verifySecret = await credentialStorage.retrieveSecret(alias);

    if (!verifySecret) {
      throw new Error('[MasterSecret] CRITICAL: Persistence failed. Read returned null after write.');
    }

    // Verify bytes match exactly
    if (verifySecret.length !== newSecret.length) {
      throw new Error('[MasterSecret] CRITICAL: Read-after-write length mismatch!');
    }
    for (let i = 0; i < newSecret.length; i++) {
      if (verifySecret[i] !== newSecret[i]) {
        throw new Error('[MasterSecret] CRITICAL: Read-after-write byte mismatch!');
      }
    }

    console.log('[MasterSecret] New secret generated, stored, and verified.');

    // CLEANUP: Attempt to remove the corrupted/deprecated V1 namespaced key if it exists
    // This cleans up the "Shared Key" artifacts from previous failed migration attempts.
    try {
      const corruptedV1Key = `confio_master_secret_${safeSub}`;
      await credentialStorage.deleteSecret(corruptedV1Key);
      // Also try to delete the tombstone if it exists on legacy (optional, but keeps things tidy)
      // await credentialStorage.deleteSecret(legacyAlias); // Already handled above
    } catch (e) {
      // Ignore cleanup errors
    }

    return newSecret;

  } finally {
    resolveCurrentMutex!();
  }
}

/**
 * Legacy aliases - Deprecated
 */
export async function retrieveClientSecret(): Promise<Uint8Array | null> {
  console.warn('[V2] retrieveClientSecret is deprecated. Use getOrCreateMasterSecret()');
  return null;
}

export async function storeClientSecret(secret: Uint8Array): Promise<void> {
  console.warn('[V2] storeClientSecret is deprecated. Use getOrCreateMasterSecret()');
}

export async function generateClientSecret(): Promise<Uint8Array> {
  throw new Error('[V2] generateClientSecret is deprecated. Use getOrCreateMasterSecret()');
}

export async function getOrCreateSecret(): Promise<Uint8Array> {
  throw new Error('[V2] getOrCreateSecret is deprecated. Use getOrCreateMasterSecret()');
}

/**
 * DEV TOOL: Enumerate possible old aliases to search for lost secrets.
 * This checks various historical key names that might have been used.
 */
export async function enumerateV2Aliases(): Promise<{ alias: string; found: boolean; hasValue: boolean }[]> {
  const { credentialStorage } = await import('./credentialStorage');

  // Historical aliases that might have stored secrets
  const possibleAliases = [
    'confio_v2_secret',
    'v2_client_secret',
    'client_secret',
    'confio_secret',
    'wallet_secret',
    'CONFIO_V2_SECRET',
  ];

  const results: { alias: string; found: boolean; hasValue: boolean }[] = [];

  for (const alias of possibleAliases) {
    try {
      // Temporarily override the key
      const secret = await credentialStorage.retrieveSecret(alias);
      results.push({
        alias,
        found: true,
        hasValue: secret !== null && secret.length > 0
      });
    } catch (e) {
      results.push({
        alias,
        found: false,
        hasValue: false
      });
    }
  }

  console.log('[V2AliasEnum] Results:', results);
  return results;
}

/**
 * Derive V2 Wallet from Client Secret
 * Key = HKDF(ClientSecret, Salt=UserContext)
 */
export function deriveWalletV2(
  clientSecret: Uint8Array,
  opts: {
    // Identity context is ignored for V2 derivation (relies on MasterSecret uniqueness)
    iss?: string,
    sub?: string,
    aud?: string,
    accountType: string,
    accountIndex: number,
    businessId?: string
  }
): DerivedWallet {
  // Master Secret is already unique per-user (Random ONCE + Persist)
  // We use Info/Salt for domain separation between accounts (Personal vs Business)

  // Create salt from account context
  let saltInput: string;
  if (opts.businessId) {
    saltInput = `confio_v2_salt_${opts.accountType}_${opts.businessId}_${opts.accountIndex}`;
  } else {
    saltInput = `confio_v2_salt_${opts.accountType}_${opts.accountIndex}`;
  }
  const salt = sha256(utf8ToBytes(saltInput));

  // IKM = Client Secret (Master Secret)
  const ikm = clientSecret;

  // Info = Domain Separation
  const info = utf8ToBytes(`confio|v2|derived|${saltInput}`);

  // Derive Seed (HKDF-SHA256)
  const seed32 = hkdf(sha256, ikm, salt, info, 32);

  // Generate Keypair
  const keyPair = nacl.sign.keyPair.fromSeed(seed32);
  const algosdk = require('algosdk');
  const address = algosdk.encodeAddress(keyPair.publicKey);

  console.log('[DeriveV2] Wallet derived:', address);

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
  // Peppers are per-account. Never cache globally across contexts.
  private cachedDerivationPepperByContext: Map<string, string> = new Map();
  private cachedKekPepperByCtxAndVersion: Map<string, string> = new Map();

  private constructor() { }

  public static getInstance(): SecureDeterministicWalletService {
    if (!SecureDeterministicWalletService.instance) {
      SecureDeterministicWalletService.instance = new SecureDeterministicWalletService();
    }
    return SecureDeterministicWalletService.instance;
  }

  private makeAccountContextKey(accountType?: string, accountIndex?: number, businessId?: string | undefined): string {
    const type = accountType ?? 'personal';
    const idx = typeof accountIndex === 'number' ? accountIndex : 0;
    return businessId ? `${type}|${idx}|${businessId}` : `${type}|${idx}`;
  }

  async getDerivationPepper(opts?: { accountType?: string; accountIndex?: number; businessId?: string }): Promise<{ pepper: string | undefined }> {
    try {
      const ctxKey = this.makeAccountContextKey(opts?.accountType, opts?.accountIndex, opts?.businessId);
      // Fast path: return from session cache (per account context)
      if (this.cachedDerivationPepperByContext.has(ctxKey)) {
        return { pepper: this.cachedDerivationPepperByContext.get(ctxKey) } as any;
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
        const pepper = data.getDerivationPepper.pepper as string;
        this.cachedDerivationPepperByContext.set(ctxKey, pepper);
        return { pepper };
      }
      console.debug('Derivation pepper not provided');
      return { pepper: undefined };
    } catch (_) {
      console.debug('Skipping derivation pepper due to fetch error');
      return { pepper: undefined };
    }
  }

  async getKekPepper(requestVersion?: number, opts?: { accountType?: string; accountIndex?: number; businessId?: string }): Promise<{
    pepper: string | undefined;
    version: number;
    isRotated?: boolean;
    gracePeriodUntil?: string;
  }> {
    try {
      const versionToUse = requestVersion || 1;
      const ctxKey = this.makeAccountContextKey(opts?.accountType, opts?.accountIndex, opts?.businessId);
      const cacheKey = `${ctxKey}|v${versionToUse}`;
      // Fast path: return from session cache for requested version
      if (this.cachedKekPepperByCtxAndVersion.has(cacheKey)) {
        return { pepper: this.cachedKekPepperByCtxAndVersion.get(cacheKey), version: versionToUse } as any;
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
          this.cachedKekPepperByCtxAndVersion.set(`${ctxKey}|v${version}`, pepper);
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
   * Explicitly restore a Legacy V1 wallet.
   * This forces the V1 derivation logic (HKDF using Server Pepper + Client Salt).
   * Used during migration to access old funds.
   */
  async restoreLegacyV1Wallet(
    iss: string,
    sub: string,
    aud: string,
    provider: 'google' | 'apple',
    accountType: 'personal' | 'business',
    accountIndex: number,
    businessId?: string
  ): Promise<DerivedWallet> {
    console.log('[WalletService] Explicitly restoring Legacy V1 Wallet');
    const { pepper: derivationPepper } = await this.getDerivationPepper({ accountType, accountIndex, businessId });
    const salt = generateClientSalt(iss, sub, aud, accountType, accountIndex, businessId);

    // Explicitly use V1 logic
    return deriveDeterministicAlgorandKey({
      clientSalt: salt,
      derivationPepper: derivationPepper || '',
      provider,
      accountType,
      accountIndex,
      businessId
    });
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

      // ----------------------------------------------------------------------
      // V2 MIGRATION CHECK:
      // If a V2 Master Secret exists, use it immediately (Random ONCE + Persist).
      // This bypasses all legacy V1 overhead (Peppers, KEKs, Caching).
      // ----------------------------------------------------------------------
      try {
        const { credentialStorage } = await import('./credentialStorage');

        // Namespace the key by User ID (sub) to support multi-user devices
        // Use SHA256 of subject for privacy and safe key characters
        const safeSub = bytesToHex(sha256(utf8ToBytes(sub)));
        // ROTATION: Using 'v2' suffix to obtain the CLEAN, ISOLATED key (ignoring previous corrupted state)
        const namespacedKey = `confio_master_secret_v2_${safeSub}`;

        const masterSecret = await credentialStorage.retrieveSecret(namespacedKey);

        // NOTE: We do NOT fallback to legacy global key here. 
        // Migration from Legacy -> V2 Namespaced is handled exclusively by 'getOrCreateMasterSecret'.
        // If masterSecret is missing here, we fall back to V1 (Pepper/Salt) logic below.

        if (masterSecret) {
          console.log('[WalletService] ⚡️ V2 Master Secret found. Deriving V2 Wallet...');
          const wallet = deriveWalletV2(masterSecret, {
            iss, sub, aud, accountType, accountIndex, businessId
          });

          // Store seed in memory for session
          const memKey = scope;
          this.inMemSeeds.set(memKey, wallet.privSeedHex);
          this.currentScope.set('current', scope);

          console.log(`[WalletService] ✅ V2 Wallet restored: ${wallet.address}`);
          perfLog('Total wallet generation time (V2)');
          return wallet;
        } else {
          console.log('[WalletService] No V2 Master Secret found. Proceeding with Legacy V1 restoration...');
        }
      } catch (checkErr) {
        console.warn('[WalletService] Error checking V2 secret:', checkErr);
      }
      // ----------------------------------------------------------------------

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
            const { pepper: oldPepper } = await this.getKekPepper(storedPepperVersion, {
              accountType,
              accountIndex,
              businessId
            });

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
      // First decode as raw msgpack to see ALL fields
      console.log(`[SecureDeterministicWallet] Raw msgpack decode:`);
      const raw = algosdk.decodeObj(bytes);
      console.log(`[SecureDeterministicWallet] Raw fields:`, JSON.stringify(Object.keys(raw), null, 2));
      if (raw.apaa) console.log(`[SecureDeterministicWallet] Raw apaa (app args):`, raw.apaa);
      if (raw.apat) console.log(`[SecureDeterministicWallet] Raw apat (app accounts):`, raw.apat);
      if (raw.apbx) console.log(`[SecureDeterministicWallet] Raw apbx (boxes):`, raw.apbx);
      if (raw.snd) {
        const sndAddr = algosdk.encodeAddress(raw.snd);
        console.log(`[SecureDeterministicWallet] Raw snd (sender):`, sndAddr);
      }

      // Use algosdk's decodeUnsignedTransaction which returns a proper Transaction instance
      // This handles all the field mapping correctly
      const txn = algosdk.decodeUnsignedTransaction(bytes);

      // WORKAROUND: algosdk.decodeUnsignedTransaction doesn't properly decode boxes
      // So we manually copy them from the raw msgpack if they're missing
      if ((!txn.boxes || txn.boxes.length === 0) && raw.apbx && raw.apbx.length > 0) {
        console.log(`[SecureDeterministicWallet] WORKAROUND: Manually copying boxes from raw msgpack`);
        txn.boxes = raw.apbx.map((box: any) => ({
          appIndex: box.i || 0,
          name: box.n
        }));
        console.log(`[SecureDeterministicWallet] Copied ${txn.boxes.length} box references`);
      }

      // WORKAROUND: algosdk.decodeUnsignedTransaction doesn't set sender properly
      if (!txn.from && raw.snd) {
        const senderAddr = algosdk.encodeAddress(raw.snd);
        console.log(`[SecureDeterministicWallet] WORKAROUND: Setting sender from raw msgpack: ${senderAddr}`);
        txn.from = algosdk.decodeAddress(senderAddr);
      }

      // WORKAROUND: Copy app accounts if missing
      if ((!txn.appAccounts || txn.appAccounts.length === 0) && raw.apat && raw.apat.length > 0) {
        console.log(`[SecureDeterministicWallet] WORKAROUND: Manually copying app accounts from raw msgpack`);
        txn.appAccounts = raw.apat.map((addr: Uint8Array) => algosdk.decodeAddress(algosdk.encodeAddress(addr)));
      }

      // Log the transaction details
      console.log(`[SecureDeterministicWallet] Decoded transaction type: ${txn.type}`);
      console.log(`[SecureDeterministicWallet] Sender: ${txn.from?.toString()}`);
      console.log(`[SecureDeterministicWallet] All txn properties:`, Object.keys(txn));
      if (txn.appAccounts && txn.appAccounts.length > 0) {
        console.log(`[SecureDeterministicWallet] App Accounts: ${txn.appAccounts.map((a: any) => a.toString()).join(', ')}`);
      }
      if (txn.boxes && txn.boxes.length > 0) {
        console.log(`[SecureDeterministicWallet] Boxes: ${txn.boxes.length} references`);
        txn.boxes.forEach((box: any, i: number) => {
          const boxName = box.name;
          let boxBytes: Uint8Array;
          if (boxName instanceof Uint8Array) {
            boxBytes = boxName;
          } else if (Array.isArray(boxName)) {
            boxBytes = Uint8Array.from(boxName);
          } else if (typeof boxName === 'string') {
            boxBytes = stringToUtf8Bytes(boxName);
          } else {
            try {
              boxBytes = new Uint8Array(boxName);
            } catch (_e) {
              boxBytes = new Uint8Array([]);
            }
          }
          console.log(`[SecureDeterministicWallet]   Box ${i}: app=${box.appIndex}, name_hex=${bytesToHex(boxBytes)}`);
          // Try to decode as address
          try {
            const boxAddr = algosdk.encodeAddress(boxName);
            console.log(`[SecureDeterministicWallet]   Box ${i}: as address=${boxAddr}`);
          } catch (e) {
            console.log(`[SecureDeterministicWallet]   Box ${i}: length=${boxName.length} (not an address)`);
          }
        });
      } else {
        console.log(`[SecureDeterministicWallet] NO BOXES in decoded transaction!`);
      }

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

      // IMPORTANT: For sponsored transactions (txnOrBytes instanceof Uint8Array),
      // we CANNOT decode and re-encode because algosdk's decode/encode doesn't
      // preserve all fields correctly (especially boxes). Instead, we must sign
      // the raw bytes directly using the low-level signing approach.

      console.log('[SecureDeterministicWallet] About to sign transaction');
      console.log('[SecureDeterministicWallet] Transaction type:', txn.type);
      console.log('[SecureDeterministicWallet] Boxes before signing:', txn.boxes?.length || 0);
      if (txn.boxes && txn.boxes.length > 0) {
        txn.boxes.forEach((box: any, i: number) => {
          console.log(`[SecureDeterministicWallet]   Box ${i}:`, box);
        });
      }

      const algosdk = require('algosdk');

      if (txnOrBytes instanceof Uint8Array) {
        // For sponsored transactions: sign the raw bytes directly without decode/re-encode
        console.log('[SecureDeterministicWallet] Signing raw msgpack bytes (sponsored transaction)');

        // Build the "TX" prefix that Algorand uses
        const TX_PREFIX = stringToUtf8Bytes('TX');

        // Concatenate prefix + transaction bytes
        const toBeSigned = new Uint8Array(TX_PREFIX.length + txnOrBytes.length);
        toBeSigned.set(TX_PREFIX);
        toBeSigned.set(txnOrBytes, TX_PREFIX.length);

        // Sign with nacl
        const signature = nacl.sign.detached(toBeSigned, sk);

        // CRITICAL: We must NOT decode/re-encode the transaction!
        // The issue is that msgpack encoding is not deterministic - encoding the same
        // data can produce different bytes, and algosdk's encode/decode is changing
        // the box references!
        //
        // The correct approach: Build SignedTxn msgpack MANUALLY by concatenating:
        // 1. A msgpack map header for 2 items
        // 2. Key "sig" + signature bytes
        // 3. Key "txn" + ORIGINAL transaction bytes (not re-encoded!)

        // Let's manually build the msgpack structure
        // SignedTxn = Map { "sig": <64 bytes>, "txn": <original msgpack bytes> }

        // Msgpack format:
        // - fixmap with 2 items: 0x82
        // - key "sig" (3 chars): 0xa3 + "sig"
        // - value: bin 32 header (0xc4 0x20) + 64 bytes of signature (actually it's bin8 with 0xc4 0x40)
        // - key "txn" (3 chars): 0xa3 + "txn"
        // - value: the original transaction bytes AS-IS

        const result: number[] = [];

        // Map with 2 items
        result.push(0x82);

        // Key "sig" (fixstr 3)
        result.push(0xa3);
        result.push(...Array.from(stringToUtf8Bytes('sig')));

        // Signature value (bin8 format for 64 bytes)
        result.push(0xc4);  // bin 8
        result.push(64);    // length = 64
        result.push(...signature);

        // Key "txn" (fixstr 3)
        result.push(0xa3);
        result.push(...Array.from(stringToUtf8Bytes('txn')));

        // Transaction value: the ORIGINAL bytes without any modification
        result.push(...txnOrBytes);

        const signedTxn = new Uint8Array(result);

        console.log('[SecureDeterministicWallet] Raw transaction signed successfully');
        console.log('[SecureDeterministicWallet] Signed txn length:', signedTxn.length);
        console.log('[SecureDeterministicWallet] Original txn length:', txnOrBytes.length);
        console.log('[SecureDeterministicWallet] Signature length:', signature.length);
        return signedTxn;
      } else {
        // For regular Transaction objects: use the normal signing method
        console.log('[SecureDeterministicWallet] Signing Transaction object (regular transaction)');
        const signedTxn = txn.signTxn(sk);
        console.log('[SecureDeterministicWallet] Transaction signed successfully');
        return signedTxn;
      }
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

      // Clear pepper caches
      this.cachedDerivationPepperByContext.clear();
      this.cachedKekPepperByCtxAndVersion.clear();

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
