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
import { Platform, Alert } from 'react-native';
import DeviceInfo from 'react-native-device-info';
import { apolloClient, AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { REPORT_BACKUP_STATUS } from '../apollo/queries';
import { gql } from '@apollo/client';
import { randomBytes } from '@noble/hashes/utils';
import { CONFIO_DERIVATION_SPEC } from './derivationSpec';
import { base64ToBytes, bytesToBase64, stringToUtf8Bytes } from '../utils/encoding';
import { AnalyticsService } from './analyticsService';

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
// V2 CLIENT SECRET MANAGEMENT (MANIFEST STRATEGY)
// ============================================================================

const MANIFEST_FILENAME = 'confio_wallet_manifest_v2.json';

interface WalletEntry {
  id: string;             // UUID
  createdAt: string;      // ISO String
  lastBackupAt: string;   // ISO String
  deviceHint: string;     // e.g. "iOS", "Android"
  providerHint: string;   // "Google" (since this is Drive)
}

interface WalletManifest {
  wallets: WalletEntry[];
}

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
 * Simple UUID v4 generator using the existing CSPRNG
 */
function generateUUID(): string {
  const b = randomBytes(16);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = bytesToHex(b);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Helper to fetch and parse the manifest
 */
async function fetchManifest(googleDriveStorage: any, accessToken: string): Promise<WalletManifest> {
  try {
    const files = await googleDriveStorage.listFiles(accessToken, MANIFEST_FILENAME);
    if (files.length > 0) {
      const content = await googleDriveStorage.downloadFile(accessToken, files[0].id);
      return JSON.parse(content) as WalletManifest;
    }
  } catch (e) {
    console.warn('[Manifest] Fetch failed or empty:', e);
  }
  return { wallets: [] };
}

/**
 * Helper to save the manifest (Overwrite)
 */
async function saveManifest(googleDriveStorage: any, accessToken: string, manifest: WalletManifest): Promise<void> {
  const content = JSON.stringify(manifest, null, 2);
  // Search for existing file to update (overwrite)
  const files = await googleDriveStorage.listFiles(accessToken, MANIFEST_FILENAME);
  if (files.length > 0) {
    await googleDriveStorage.updateFile(accessToken, files[0].id, content);
  } else {
    await googleDriveStorage.createFile(accessToken, MANIFEST_FILENAME, content);
  }
}

/**
 * Check for existing backups in Google Drive.
 * This checks both the current manifest and legacy files for backward compatibility.
 * 
 * @param accessToken - Google Drive access token
 * @param userSub - OAuth subject (for checking legacy files)
 * @returns Object with hasBackup flag, entries, and cross-platform detection
 */
export async function checkExistingBackups(
  accessToken: string,
  userSub?: string
): Promise<{
  hasBackup: boolean;
  entries: WalletEntry[];
  hasLegacy: boolean;
  hasCrossPlatformBackup: boolean;
  crossPlatformEntries: WalletEntry[];
}> {
  const { googleDriveStorage } = await import('./googleDriveStorage');

  // Check current manifest
  const manifest = await fetchManifest(googleDriveStorage, accessToken);

  // Check for legacy files (backward compatibility) and run DEEP SEARCH
  let hasLegacy = false;
  if (userSub) {
    const safeSub = bytesToHex(sha256(utf8ToBytes(userSub))).slice(0, 64);
    const legacyFilename = `confio_master_secret_v2_${safeSub}.json`;
    try {
      const legacyFiles = await googleDriveStorage.listFiles(accessToken, legacyFilename);
      hasLegacy = legacyFiles.length > 0;
      if (hasLegacy) {
        console.log('[checkExistingBackups] Found legacy backup file:', legacyFilename);
      }
      const crossPlatformEntries = manifest.wallets.filter(entry => {
        const deviceHint = entry.deviceHint?.toLowerCase() || '';

        // Check if the backup is from a different platform
        // Method 1: Check for platform in parentheses (standard format)
        const hasAndroidMarker = deviceHint.includes('(android)') || deviceHint.includes('android');
        const hasIOSMarker = deviceHint.includes('(ios)') || deviceHint.includes('ios') ||
          deviceHint.includes('iphone') || deviceHint.includes('ipad');

        // EXCEPTION: "Legacy iOS Backup" is effectively cross-platform if we are on Android, 
        // but on iOS it's native. However, we ALWAYS want to show it if we are looking for lost data.
        if (deviceHint.includes('legacy ios backup')) {
          return true; // Treat as interesting/cross-platform to ensure modal shows
        }

        console.log('[checkExistingBackups] Entry check:', {
          entryId: entry.id,
          deviceHint,
          hasAndroidMarker,
          hasIOSMarker,
          currentPlatform: Platform.OS,
          isCrossPlatform: (Platform.OS === 'ios' && hasAndroidMarker) ||
            (Platform.OS === 'android' && hasIOSMarker)
        });

        if (Platform.OS === 'ios' && hasAndroidMarker && !hasIOSMarker) {
          return true;
        }
        if (Platform.OS === 'android' && hasIOSMarker && !hasAndroidMarker) {
          return true;
        }
        return false;
      });

      const hasCrossPlatformBackup = crossPlatformEntries.length > 0;

      console.log('[checkExistingBackups] Results:', {
        totalEntries: manifest.wallets.length,
        hasLegacy,
        hasCrossPlatformBackup,
        crossPlatformCount: crossPlatformEntries.length,
        currentPlatform: Platform.OS
      });

      return {
        hasBackup: manifest.wallets.length > 0 || hasLegacy,
        entries: manifest.wallets,
        hasLegacy,
        hasCrossPlatformBackup,
        crossPlatformEntries
      };
    } catch (e) {
      console.error('[checkExistingBackups] Error during backup check:', e);
      return {
        hasBackup: manifest.wallets.length > 0, // Still return manifest results even if legacy check fails
        entries: manifest.wallets,
        hasLegacy: false,
        hasCrossPlatformBackup: false,
        crossPlatformEntries: []
      };
    }
  }

  // If no userSub, or if the try block above didn't execute/return, return manifest results only
  return {
    hasBackup: manifest.wallets.length > 0,
    entries: manifest.wallets,
    hasLegacy: false,
    hasCrossPlatformBackup: false,
    crossPlatformEntries: []
  };
}

/**
 * Force-restore wallet from a specific backup in Google Drive.
 * This OVERWRITES the current local secret with the backup.
 * 
 * Use this for cross-platform restoration where user already has a local wallet
 * but wants to restore from another platform's backup.
 * 
 * @param accessToken - Google Drive access token
 * @param walletId - The wallet ID to restore (from manifest entry)
 * @param userSub - OAuth subject (for creating local alias)
 */
export async function restoreFromBackup(
  accessToken: string,
  walletId: string | null | undefined,
  userSub: string,
  lastBackupAt?: string
): Promise<boolean> {
  try {
    console.log('[restoreFromBackup] Starting restore for wallet:', walletId, 'timestamp:', lastBackupAt);

    const { googleDriveStorage } = await import('./googleDriveStorage');
    const { credentialStorage } = await import('./credentialStorage');
    const CryptoJS = (await import('crypto-js')) as any;
    const AES = CryptoJS.AES;
    const Utf8 = CryptoJS.enc.Utf8;

    // Same key used in getOrCreateMasterSecret
    const APP_BACKUP_KEY = 'ConfioWallet_Backup_Key_v1_DoNotShare';

    // Build the local aliases
    const safeSub = bytesToHex(sha256(utf8ToBytes(userSub)));
    const secretAlias = `confio_master_secret_v2_${safeSub}`;
    const walletIdKey = `confio_wallet_id_v2_${safeSub}`;

    let filename: string;
    let files: any[];
    let fileToRestore: any;

    // BULK SCAN: User requested to check all revisions for unique keys
    if (walletId && walletId.startsWith('SCAN_ALL_REVISIONS_')) {
      const fileId = walletId.replace('SCAN_ALL_REVISIONS_', '');
      console.log(`[restoreFromBackup] BULK SCAN STARTING for file: ${fileId}`);
      try {
        const revisions = await googleDriveStorage.listRevisions(accessToken, fileId);
        console.log(`[restoreFromBackup] Found ${revisions.length} revisions to scan.`);
        const uniqueParams = new Set<string>();

        // Iterate newest to oldest
        revisions.sort((a: any, b: any) => new Date(b.modifiedTime).getTime() - new Date(a.modifiedTime).getTime());

        for (const [index, rev] of revisions.entries()) {
          try {
            const content = await googleDriveStorage.downloadFile(accessToken, fileId, rev.id);
            const decrypted = decryptBackup(content, AES, APP_BACKUP_KEY, Utf8);
            if (decrypted) {
              // Hash the secret to identify uniqueness without logging the raw secret
              const hash = bytesToHex(sha256(decrypted));
              const isNew = !uniqueParams.has(hash);
              if (isNew) uniqueParams.add(hash);

              console.log(`[Scan] 🕒 Rev ${index + 1} (${rev.modifiedTime}): KeyHash=${hash.slice(0, 8)}... ${isNew ? '✨ NEW UNIQUE KEY' : '(Duplicate)'}`);
            } else {
              console.log(`[Scan] ❌ Rev ${index + 1}: Decryption Failed`);
            }
          } catch (e) {
            console.log(`[Scan] ⚠️ Rev ${index + 1}: Error ${e}`);
          }
        }
        console.log(`[Scan] COMPLETED. Found ${uniqueParams.size} UNIQUE keys across ${revisions.length} revisions.`);
        // Don't restore anything, just return false (user stays on screen)
        return false;
      } catch (err) {
        console.error('[restoreFromBackup] Bulk scan failed:', err);
        return false;
      }
    }

    // TIME MACHINE RESTORE: Explicit revision selected by user
    if (walletId && walletId.startsWith('time_machine_')) {
      const parts = walletId.replace('time_machine_', '').split('_REV_');
      if (parts.length === 2) {
        const fileId = parts[0];
        const revisionId = parts[1];
        console.log(`[restoreFromBackup] TIME MACHINE: Restoring specific revision. File: ${fileId}, Rev: ${revisionId}`);
        const content = await googleDriveStorage.downloadFile(accessToken, fileId, revisionId);
        fileToRestore = { name: 'Time Machine Backup', id: fileId }; // Mock file object for logging
        // Decrypt and Restore
        console.log(`[restoreFromBackup] Downloading content from Time Machine selection...`);
        const decrypted = decryptBackup(content, AES, APP_BACKUP_KEY, Utf8);
        if (!decrypted) {
          console.error('[restoreFromBackup] Failed to decrypt Time Machine backup');
          return false;
        }
        console.log('[restoreFromBackup] Backup decrypted successfully, storing locally...');
        await credentialStorage.storeSecret(secretAlias, decrypted);
        // We don't have a specific wallet ID for a revision, so we'll use the file ID as a hint (BUT NEVER 'null' string)
        const safeRestoreId = `time_machine_rev_${fileId}`;
        await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(safeRestoreId));
        return true;
      }
    }

    // Handle null/undefined wallet ID or string 'null', OR the special orphaned file ID, OR Deep Search candidates
    if (!walletId || walletId === 'null' || walletId === 'legacy_rescue_option' || walletId?.startsWith('deep_search_')) {
      console.log(`[restoreFromBackup] Wallet ID is ${walletId} (Legacy/Rescue/DeepSearch), fetching ALL AppData files to find match...`);

      // If it's a specific Deep Search file, we might already have the ID
      let specificFileId: string | null = null;
      if (walletId?.startsWith('deep_search_')) {
        specificFileId = walletId.replace('deep_search_', '');
        console.log(`[restoreFromBackup] DEEP SEARCH TARGET: ${specificFileId}`);
      }

      // List ALL files in AppData folder (Active + Trash)
      const activeFiles = await googleDriveStorage.listFiles(accessToken);
      let trashedFiles: any[] = [];
      try {
        trashedFiles = await googleDriveStorage.listFiles(accessToken, undefined, true);
        console.log(`[restoreFromBackup] Found ${trashedFiles.length} files in TRASH.`);
      } catch (e) {
        console.warn('[restoreFromBackup] Failed to list trash:', e);
      }

      const allFiles = [...activeFiles, ...trashedFiles];

      const legacyFilename = `confio_master_secret_v2_${safeSub}.json`;

      // Filter for relevant files
      if (specificFileId) {
        // Deep Search: Only look for the specific file we clicked on
        files = allFiles.filter((f: any) => f.id === specificFileId);
      } else {
        // Legacy Rescue: Look for standard V2 or Legacy JSON
        files = allFiles.filter((f: any) =>
          (f.name && f.name.startsWith('confio_wallet_v2_')) ||
          (f.name === legacyFilename)
        );
      }

      console.log('[restoreFromBackup] Found candidate backup files:', files.map((f: any) => `${f.name} (${f.modifiedTime})`));

      if (files.length === 0) {
        console.error('[restoreFromBackup] No matching backup files found (V2 or Legacy)');
        return false;
      }

      // FETCH REVISIONS to support recovery of overwritten files
      const allCandidates: any[] = [];
      for (const f of files) {
        // Add the file itself
        allCandidates.push({ ...f, fileId: f.id });

        // Fetch revisions
        try {
          const revisions = await googleDriveStorage.listRevisions(accessToken, f.id);
          if (revisions && revisions.length > 0) {
            console.log(`[restoreFromBackup] Found ${revisions.length} revisions for ${f.name}`);
            revisions.forEach((r: any) => {
              allCandidates.push({
                fileId: f.id,
                revisionId: r.id,
                name: `${f.name} [Rev ${r.modifiedTime}]`,
                modifiedTime: r.modifiedTime,
                isRevision: true
              });
            });
          }
        } catch (e) {
          console.warn('[restoreFromBackup] Failed to fetch revisions for', f.name, e);
        }
      }

      console.log('[restoreFromBackup] Total candidates (Files + Revisions):', allCandidates.length);

      // LEGACY RESCUE: If null ID and we have multiple candidates (revisions),
      // We assume the user is trying to recover an overwritten legacy wallet.
      // We FORCE the oldest revision, ignoring the manifest timestamp (which might point to the overwrite).
      if ((!walletId || walletId === 'null' || walletId === 'legacy_rescue_option' || walletId?.startsWith('deep_search_')) && allCandidates.length > 1) {
        console.log('[restoreFromBackup] LEGACY RESCUE: Forcing oldest revision to recover lost wallet.');
        allCandidates.sort((a: any, b: any) => {
          return new Date(a.modifiedTime || 0).getTime() - new Date(b.modifiedTime || 0).getTime();
        });
        fileToRestore = allCandidates[0];
        console.log(`[restoreFromBackup] Rescuing revision: ${fileToRestore.name} (${fileToRestore.modifiedTime})`);
      }
      // If we have lastBackupAt AND didn't just force a rescue, try to match by timestamp
      else if (lastBackupAt) {
        // Parse the target timestamp
        const targetTime = new Date(lastBackupAt).getTime();

        console.log(`[restoreFromBackup] Target Timestamp: ${lastBackupAt} (${targetTime})`);

        let bestMatch: any = null;
        let minDiff = Infinity;

        // Tolerance: 60 mins
        const TOLERANCE_MS = 60 * 60 * 1000;

        allCandidates.forEach(f => {
          const fTime = new Date(f.modifiedTime || 0).getTime();
          const diff = Math.abs(fTime - targetTime);
          console.log(`[restoreFromBackup] Candidate: ${f.name} | Time: ${f.modifiedTime} | Diff: ${diff / 1000}s`);

          if (diff < minDiff) {
            // We track global minDiff to find "closest" match. 
            minDiff = diff;
            bestMatch = f;
          }
        });

        if (bestMatch && minDiff < TOLERANCE_MS) {
          console.log(`[restoreFromBackup] Found matching file/revision (diff ${minDiff}ms):`, bestMatch.name);
          fileToRestore = bestMatch;
        } else {
          console.log('[restoreFromBackup] No close timestamp match found within tolerance. Falling back to most recent file/revision.');
          allCandidates.sort((a: any, b: any) => {
            const timeA = new Date(a.modifiedTime || 0).getTime();
            const timeB = new Date(b.modifiedTime || 0).getTime();
            return timeB - timeA;
          });
          fileToRestore = allCandidates[0];
        }

      } else {
        // No timestamp provided, use most recent
        allCandidates.sort((a: any, b: any) => {
          const timeA = new Date(a.modifiedTime || 0).getTime();
          const timeB = new Date(b.modifiedTime || 0).getTime();
          return timeB - timeA;
        });
        fileToRestore = allCandidates[0];
      }

      filename = fileToRestore.name;
    } else {
      // Download the specific backup file
      filename = `confio_wallet_v2_${walletId}.enc`;
      console.log('[restoreFromBackup] Downloading backup file:', filename);
      files = await googleDriveStorage.listFiles(accessToken, filename);
      fileToRestore = files[0];
    }

    if (!fileToRestore) {
      console.error('[restoreFromBackup] Backup file not found:', filename);
      return false;
    }

    console.log(`[restoreFromBackup] Downloading content from ${fileToRestore.name} (Rev: ${fileToRestore.revisionId || 'LATEST'})`);
    const content = await googleDriveStorage.downloadFile(
      accessToken,
      fileToRestore.fileId || fileToRestore.id,
      fileToRestore.revisionId
    );

    // Decrypt the backup
    const decrypted = decryptBackup(content, AES, APP_BACKUP_KEY, Utf8);
    if (!decrypted) {
      console.error('[restoreFromBackup] Failed to decrypt backup');
      return false;
    }

    console.log('[restoreFromBackup] Backup decrypted successfully, storing locally...');

    // Store the restored secret locally (overwrites existing)
    await credentialStorage.storeSecret(secretAlias, decrypted);

    // Also store the wallet ID if we have it, or try to derive it/fail gracefully
    // BUT we must overwrite the current wallet ID to prevent mismatch
    if (walletId) {
      await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(walletId));
    } else {
      // If restored from null ID, try to get ID from filename if possible?
      // confio_wallet_v2_ID.enc
      const match = filename.match(/confio_wallet_v2_(.+)\.enc/);
      if (match && match[1]) {
        await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(match[1]));
        console.log('[restoreFromBackup] Restored wallet ID from filename:', match[1]);
      }
    }

    console.log('[restoreFromBackup] Wallet restored successfully');

    // Report backup status
    await reportBackupStatus('google_drive');

    return true;
  } catch (error) {
    console.error('[restoreFromBackup] Error:', error);
    return false;
  }
}

/**
 * Get-or-Create Master Secret.
 * 
 * STRATEGY: MANIFEST + UUID (Safe Roaming)
 * 
 * 1. LOCAL: Check for existing `walletId` and `secret`.
 * 2. CLOUD (Restore): If Local missing, read Manifest.
 *    - If entries found -> Prompt User -> Download specific UUID file.
 * 3. CLOUD (Backup):
 *    - If Local exists (or created) -> Ensure entry in Manifest -> Upload unique file.
 * 
 * @param userSub - Unique user identifier (OAuth Subject) to namespace local storage
 * @returns The master secret (32 bytes)
 */
export async function getOrCreateMasterSecret(userSub: string, accessToken?: string): Promise<Uint8Array> {
  if (!userSub) {
    throw new Error('[MasterSecret] User Sub (OAuth ID) is required to secure the master secret.');
  }

  const safeSub = bytesToHex(sha256(utf8ToBytes(userSub)));
  const secretAlias = `confio_master_secret_v2_${safeSub}`;
  const walletIdKey = `confio_wallet_id_v2_${safeSub}`; // Store the UUID locally
  const legacyAlias = 'confio_master_secret';

  // Legacy dynamic filename for migration check
  const legacyDriveFilename = `confio_wallet_id_v2_${safeSub}.json`; // Corrected based on file content observation if needed, but keeping logic
  // actually line 821 was `confio_master_secret_v2_${safeSub}.json`. Kept as is.

  // PRIMARY POINTER: Single Source of Truth for the "Main" wallet of this Google Account
  const PRIMARY_POINTER_FILENAME = 'confio_wallet_primary.json';

  console.log(`[MasterSecret] UserHash=${safeSub.substring(0, 8)}... Alias=${secretAlias}`);



  // Mutex: wait for any in-progress creation to avoid race conditionsolveCurrentMutex: () => void;
  await v2SecretMutex;
  let resolveCurrentMutex: () => void;
  v2SecretMutex = new Promise(resolve => { resolveCurrentMutex = resolve; });

  try {
    const { credentialStorage } = await import('./credentialStorage');
    const { googleDriveStorage } = await import('./googleDriveStorage');
    const AES = require('crypto-js/aes');
    const Utf8 = require('crypto-js/enc-utf8');
    const APP_BACKUP_KEY = 'ConfioWallet_Backup_Key_v1_DoNotShare';
    const DRIVE_SECURITY_HEADER = 'ADVERTENCIA DE SEGURIDAD: NUNCA COMPARTAS ESTA CLAVE CON NADIE.';

    // =================================================================================
    // 1. LOCAL CHECK
    // =================================================================================
    let localSecret = await credentialStorage.retrieveSecret(secretAlias);
    let localWalletIdBytes = await credentialStorage.retrieveSecret(walletIdKey);
    let localWalletId = localWalletIdBytes ? decodeUtf8(localWalletIdBytes) : null;

    // SANITY CHECK: Ensure we never use the string "null" or "undefined" as an ID
    if (localWalletId === 'null' || localWalletId === 'undefined') {
      console.warn('[MasterSecret] Detected corrupted wallet ID "null"/"undefined". Treating as missing.');
      localWalletId = null;
    }

    // --- ACL MIGRATION HOOK (iOS) ---
    if (localSecret && Platform.OS === 'ios') {
      const ACL_FLAG_KEY = 'v2_acl_migration_complete_v1';
      const currentFlag = await credentialStorage.retrieveSecret(ACL_FLAG_KEY);
      if (!currentFlag) {
        // Re-write to relax security policy if needed
        await credentialStorage.storeSecret(secretAlias, localSecret);
        if (localWalletId) await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(localWalletId));
        await credentialStorage.storeSecret(ACL_FLAG_KEY, new Uint8Array([1]));
      }

      // Implicit iCloud Safety Report
      reportBackupStatus('icloud').catch(e => console.warn('[BackupHealth] iCloud report failed', e));
    }
    // -------------------------------

    // =================================================================================
    // 2. CLOUD RESTORE (If Local is Missing)
    // =================================================================================
    if (!localSecret && accessToken) {
      console.log('[MasterSecret] Local secret missing. checking Manifest...');
      const manifest = await fetchManifest(googleDriveStorage, accessToken);
      let targetWallet: WalletEntry | null = null;

      // 2.0 Check for Primary Pointer (Option B Strategy)
      // This allows us to auto-select the "main" wallet even if multiple exist in manifest
      try {
        const primaryFiles = await googleDriveStorage.listFiles(accessToken, PRIMARY_POINTER_FILENAME);
        if (primaryFiles.length > 0) {
          const primaryContent = await googleDriveStorage.downloadFile(accessToken, primaryFiles[0].id);
          const primaryJson = JSON.parse(primaryContent);
          if (primaryJson && primaryJson.primary_wallet_id) {
            console.log('[MasterSecret] Found Primary Wallet Pointer:', primaryJson.primary_wallet_id);
            const primaryMatch = manifest.wallets.find(w => w.id === primaryJson.primary_wallet_id);
            if (primaryMatch) {
              console.log('[MasterSecret] Primary wallet found in manifest. Auto-selecting.');
              targetWallet = primaryMatch;
            } else {
              console.warn('[MasterSecret] Primary wallet ID pointer exists, but not found in manifest? Strange.');
            }
          }
        }
      } catch (e) {
        console.warn('[MasterSecret] Failed to check primary pointer:', e);
      }

      if (targetWallet) {
        // Already found via Primacy Check
      } else if (manifest.wallets.length === 0) {
        // 2a. Check Legacy Migration
        console.log('[MasterSecret] Manifest empty. Checking Legacy Backup...');
        const legacyFiles = await googleDriveStorage.listFiles(accessToken, legacyDriveFilename);
        if (legacyFiles.length > 0) {
          console.log('[MasterSecret] Found Legacy Backup. Importing...');
          // Download Legacy
          const content = await googleDriveStorage.downloadFile(accessToken, legacyFiles[0].id);
          // Decrypt logic (shared)
          const decrypted = decryptBackup(content, AES, APP_BACKUP_KEY, Utf8);
          if (decrypted) {
            // Generate New UUID for it
            const newId = generateUUID();
            const now = new Date().toISOString();

            // Save Local
            await credentialStorage.storeSecret(secretAlias, decrypted);
            await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(newId));

            localSecret = decrypted;
            localWalletId = newId;

            // Add to Manifest (Will be saved in Step 3)
            const deviceName = await DeviceInfo.getDeviceName();
            manifest.wallets.push({
              id: newId,
              createdAt: now,
              lastBackupAt: now,
              deviceHint: `${deviceName} (${Platform.OS})`, // "iPhone 15 (ios)"
              providerHint: 'Google'
            });
            // Mark as dirty to ensure upload happen in Step 3
          }
        }
      } else if (manifest.wallets.length === 1) {
        // 2b. Single Wallet - Auto Restore
        console.log('[MasterSecret] Single wallet found. Auto-restoring...');
        targetWallet = manifest.wallets[0];
      } else {
        // 2c. Multiple Wallets - Prompt User
        console.log('[MasterSecret] Multiple wallets found. Prompting...');
        const choice = await promptUserForWalletSelection(manifest.wallets);
        if (choice === 'new') {
          // Proceed to Generate New
        } else {
          targetWallet = manifest.wallets.find(w => w.id === choice) || null;
        }
      }

      // Execute Restore if Target Selected
      if (targetWallet) {
        const filename = `confio_wallet_v2_${targetWallet.id}.enc`;
        const files = await googleDriveStorage.listFiles(accessToken, filename);
        if (files.length > 0) {
          const content = await googleDriveStorage.downloadFile(accessToken, files[0].id);
          const decrypted = decryptBackup(content, AES, APP_BACKUP_KEY, Utf8);
          if (decrypted) {
            await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(targetWallet.id));
            localSecret = decrypted;
            localWalletId = targetWallet.id;

            // Drive Restore Report
            reportBackupStatus('google_drive').catch(e => console.warn('[BackupHealth] Drive restore report failed', e));
          }
        }
      }
    }

    // =================================================================================
    // 3. GENERATION (If still missing)
    // =================================================================================
    if (!localSecret) {
      // Check Legacy Local (Migration from V1 Global)
      const legacyGlobalSecret = await credentialStorage.retrieveSecret(legacyAlias);
      if (legacyGlobalSecret && legacyGlobalSecret.length === 32) {
        console.log('[MasterSecret] Migrating Local Legacy Secret...');
        localSecret = legacyGlobalSecret;
        // Poison old
        await credentialStorage.storeSecret(legacyAlias, utf8ToBytes('MIGRATED_TOMBSTONE'));
        await credentialStorage.deleteSecret(legacyAlias);
      } else {
        console.log('[MasterSecret] Generating NEW Secret...');
        localSecret = generateRandomSecret();
      }

      // Assign New UUID
      localWalletId = generateUUID();
      await credentialStorage.storeSecret(secretAlias, localSecret);
      await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(localWalletId));
    }

    // Ensure ID exists if we have a secret but no ID (e.g. after Legacy Restore)
    if (localSecret && !localWalletId) {
      console.log('[MasterSecret] Local secret exists but ID missing (Legacy Migration). Generating new ID...');
      localWalletId = generateUUID();
      await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(localWalletId));
    }

    // Local vars guaranteed populated now
    const finalSecret = localSecret!;
    const finalId = localWalletId!;

    // =================================================================================
    // 4. CLOUD SYNC (BACKUP)
    // =================================================================================
    if (accessToken) {
      AnalyticsService.logBackupAttempt('google_drive');
      try {
        // Refresh Manifest to get latest state
        const manifest = await fetchManifest(googleDriveStorage, accessToken);
        const existingEntryIndex = manifest.wallets.findIndex(w => w.id === finalId);
        const now = new Date().toISOString();

        // 4a. Upload Encrypted File (Unique Name)
        // CRITICAL SAFEGUARD: Never overwrite the legacy/null file
        if (!finalId || finalId === 'null' || finalId === 'undefined') {
          throw new Error('[MasterSecret] CRITICAL: Attempted to save backup with invalid ID. Aborting to protect legacy data.');
        }

        const filename = `confio_wallet_v2_${finalId}.enc`;

        // DOUBLE CHECK: Explicitly block the known legacy filename
        if (filename === 'confio_wallet_v2_null.enc') {
          throw new Error('[MasterSecret] CRITICAL: Attempted to overwrite legacy backup file. Aborting.');
        }

        const secretBase64 = bytesToBase64(finalSecret);
        const encryptedBody = AES.encrypt(secretBase64, APP_BACKUP_KEY).toString();
        const finalContent = `${DRIVE_SECURITY_HEADER}\n${encryptedBody}`;

        // Always overwrite/update the specific file for *this* wallet ID
        // (Safe because ID is unique to this wallet lineage)
        const fileList = await googleDriveStorage.listFiles(accessToken, filename);
        if (fileList.length > 0) {
          await googleDriveStorage.updateFile(accessToken, fileList[0].id, finalContent);
        } else {
          await googleDriveStorage.createFile(accessToken, filename, finalContent);
        }

        // 4b. Update Manifest
        const deviceName = await DeviceInfo.getDeviceName();

        const currentDeviceHint = `${deviceName} (${Platform.OS})`; // e.g. "Pixel 8 (android)"

        // DEDUPLICATION: Check if we already have a backup for THIS device
        // If so, we overwrite that entry instead of creating a huge list of duplicates.
        // We match by deviceHint (which includes Model + OS).
        const existingDeviceIndex = manifest.wallets.findIndex(w => w.deviceHint === currentDeviceHint);

        // Determine which index to update (ID match takes precedence, then Device match)
        let indexToUpdate = existingEntryIndex;
        if (indexToUpdate === -1 && existingDeviceIndex >= 0) {
          console.log(`[MasterSecret] Found existing backup slot for device '${currentDeviceHint}'. Updating it.`);
          indexToUpdate = existingDeviceIndex;
        }

        const entry: WalletEntry = {
          id: finalId,
          // If we are updating an existing slot, keep its creation date to show history?
          // actually, if it's a NEW wallet ID (re-install), it's effectively a new wallet.
          // Let's rely on 'now' for simplicity unless it's strictly the same wallet ID.
          createdAt: existingEntryIndex >= 0 ? manifest.wallets[existingEntryIndex].createdAt : now,
          lastBackupAt: now,
          deviceHint: currentDeviceHint,
          providerHint: 'Google'
        };

        // 4c. Update Primary Pointer (If missing)
        try {
          const primaryFiles = await googleDriveStorage.listFiles(accessToken, PRIMARY_POINTER_FILENAME);
          if (primaryFiles.length === 0) {
            console.log('[MasterSecret] No Primary Pointer found. Setting THIS wallet as Primary:', finalId);
            const primaryContent = JSON.stringify({
              primary_wallet_id: finalId,
              created_at: now,
              device_hint: currentDeviceHint
            });
            await googleDriveStorage.createFile(accessToken, PRIMARY_POINTER_FILENAME, primaryContent);
          } else {
            console.log('[MasterSecret] Primary Pointer already exists. Respecting existing primary.');
            // OPTIONAL: If we want to support "Switch Primary", we'd update it here.
            // For now, "First Come First Served" (Option B).
          }
        } catch (e) {
          console.warn('[MasterSecret] Failed to update primary pointer:', e);
        }

        if (indexToUpdate >= 0) {
          manifest.wallets[indexToUpdate] = entry;
        } else {
          manifest.wallets.push(entry);
        }

        await saveManifest(googleDriveStorage, accessToken, manifest);
        console.log(`[MasterSecret] Encrypted Backup Synced (ID: ${finalId})`);

        // Drive Backup Report
        reportBackupStatus('google_drive').catch(e => console.warn('[BackupHealth] Drive backup report failed', e));

      } catch (syncErr: any) {
        AnalyticsService.logBackupFailed('google_drive', syncErr?.message || 'Unknown sync error');
        console.warn('[MasterSecret] Sync failed:', syncErr);
      }
    }

    return finalSecret;

  } finally {
    resolveCurrentMutex!();
  }
}

// Helper: Decryption Logic
function decryptBackup(content: string, AES: any, key: string, Utf8: any): Uint8Array | null {
  try {
    let clean = content.trim();
    if (clean.includes('ADVERTENCIA') || clean.includes('\n')) {
      clean = clean.split('\n').pop()!.trim();
    }
    const bytes = AES.decrypt(clean, key);
    const b64 = bytes.toString(Utf8);
    if (!b64) return null;
    return base64ToBytes(b64);
  } catch (e) {
    console.warn('Decryption failed:', e);
    return null;
  }
}

// Helper: User Prompt
async function promptUserForWalletSelection(wallets: WalletEntry[]): Promise<string> {
  return new Promise((resolve) => {
    // Sort by lastBackup (newest first)
    const sorted = [...wallets].sort((a, b) => new Date(b.lastBackupAt).getTime() - new Date(a.lastBackupAt).getTime());

    // Take top 2 for display, plus 'New'
    const options = sorted.slice(0, 2).map(w => ({
      text: `${w.deviceHint} (${w.createdAt.substring(0, 10)})`,
      onPress: () => resolve(w.id)
    }));

    options.push({
      text: 'Crear Nueva (Separada)',
      onPress: () => resolve('new')
    });

    Alert.alert(
      'Multiples Billeteras',
      'Encontramos varias copias de seguridad. ¿Cual quieres restaurar?',
      options,
      { cancelable: false }
    );
  });
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


/**
 * Reports backup status to the server.
 */
export const reportBackupStatus = async (provider: 'google_drive' | 'icloud') => {
  try {
    const deviceName = await DeviceInfo.getDeviceName();
    await apolloClient.mutate({
      mutation: REPORT_BACKUP_STATUS,
      variables: {
        provider,
        device_name: deviceName,
        isVerified: true
      },
      context: { skipAuth: false }
    });
    console.log(`[BackupHealth] Reported safe via ${provider}`);
    AnalyticsService.logBackupSuccess(provider, deviceName);
  } catch (e) {
    console.warn('[BackupHealth] Failed to report status:', e);
  }
};
