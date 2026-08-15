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
import { Platform } from 'react-native';
import DeviceInfo from 'react-native-device-info';
import { apolloClient, AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { REPORT_BACKUP_STATUS } from '../apollo/queries';
import { gql } from '@apollo/client';
import { secureRandomBytes } from '../setup/entropyGuard';
import { CONFIO_DERIVATION_SPEC } from './derivationSpec';
import { deriveEvmKeyFromMasterSecret, DerivedEvmWallet, signEip191Message } from './evmWallet';
import { base64ToBytes, bytesToBase64, stringToUtf8Bytes, strictBase64ToBytes, NonCanonicalBase64Error } from '../utils/encoding';
import { AnalyticsService } from './analyticsService';
import { softClearInternetCredentials } from '../utils/keychainInternetCredentials';

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
  // Secrecy is not the requirement here, uniqueness is: a repeating nonce
  // under the same KEK breaks XSalsa20-Poly1305 outright, so this needs the
  // same guaranteed-CSPRNG source as the key material itself.
  const nonce = secureRandomBytes(24, 'a seed-wrapping nonce');
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
// BSC (savings chain) sibling wallet — derived alongside the Algorand key
// from the SAME inputs (confio/evm/v1 domain) and cached for the session.
// authService registers the address server-side (UpdateAccountBscAddress);
// the cUSD+ ramp and vault flows read it via getDerivedEvmWallet().
let lastDerivedEvmWallet: DerivedEvmWallet | null = null;

export function getDerivedEvmWallet(): DerivedEvmWallet | null {
  return lastDerivedEvmWallet;
}

/**
 * Derive the EVM (BSC) wallet WITH its private key for the ACTIVE account,
 * on demand — the signing-time analogue of algorandService.signTransactionBytes.
 * Same master secret + account context → the same user.bsc key on any device.
 * Never derives from a stale cache; the secret never leaves this module.
 *
 * Throws if no master secret exists (the user must have completed sign-in);
 * we never generate one here (allowGenerate: false).
 */
export async function getActiveEvmWallet(
  ctxOverride?: { type: 'personal' | 'business'; index: number; businessId?: string },
): Promise<DerivedEvmWallet> {
  const { oauthStorage } = await import('./oauthStorageService');
  const oauth = await oauthStorage.getOAuthSubject();
  if (!oauth?.subject || !oauth?.provider) {
    throw new Error('Missing OAuth subject/provider for EVM signing');
  }

  let ctx = ctxOverride;
  if (!ctx) {
    const { AuthService } = await import('./authService');
    ctx = await AuthService.getInstance().getActiveAccountContext();
  }

  const masterSecret = await getOrCreateMasterSecret(oauth.subject, undefined, {
    allowGenerate: false,
    provider: oauth.provider as 'google' | 'apple',
  });

  const opts = {
    accountType: ctx.type === 'business' ? 'business' : 'personal',
    accountIndex: ctx.index,
    businessId: ctx.businessId,
  } as const;
  const wallet = deriveEvmKeyFromMasterSecret(masterSecret, opts);
  if (ctxOverride) {
    // Emergency-exit sweep of a non-active account: persist the address
    // per-account but do NOT clobber the "last derived" slot the ramp and
    // vault flows read for the ACTIVE account.
    evmAddressMemory[evmAccountKey(opts)] = wallet.address;
    Keychain.setGenericPassword('evm_address', wallet.address, {
      service: `${EVM_ADDR_KEYCHAIN_SERVICE}_${evmAccountKey(opts)}`,
    }).catch(() => {});
  } else {
    cacheAndPersistEvmWallet(evmAccountKey(opts), wallet);
  }
  return wallet;
}

/**
 * ADDRESSES ONLY (never keys) for an arbitrary account context, derived
 * fully locally from the V2 master secret — the emergency exit uses this
 * to sweep every owned account while the server can't answer (ban/outage).
 * Returns nulls when no V2 master secret exists (legacy V1 session):
 * callers fall back to the per-account stored addresses.
 */
export async function deriveAddressesForContext(
  ctx: { type: 'personal' | 'business'; index: number; businessId?: string },
): Promise<{ algorand: string | null; evm: string | null }> {
  try {
    const { oauthStorage } = await import('./oauthStorageService');
    const oauth = await oauthStorage.getOAuthSubject();
    if (!oauth?.subject || !oauth?.provider) return { algorand: null, evm: null };
    const masterSecret = await getOrCreateMasterSecret(oauth.subject, undefined, {
      allowGenerate: false,
      provider: oauth.provider as 'google' | 'apple',
    });
    if (!masterSecret) return { algorand: null, evm: null };
    const opts = {
      accountType: ctx.type === 'business' ? 'business' : 'personal',
      accountIndex: ctx.index,
      businessId: ctx.businessId,
    } as const;
    return {
      algorand: deriveWalletV2(masterSecret, opts).address,
      evm: deriveEvmKeyFromMasterSecret(masterSecret, opts).address,
    };
  } catch {
    return { algorand: null, evm: null };
  }
}

// The ADDRESS (never key material) also persists in the keychain, PER
// ACCOUNT, so cold starts can display it: the fast wallet paths
// reconstruct from the cached ALGORAND seed, which by domain-separation
// design cannot produce the EVM key. Addresses are immutable per account
// (same inputs -> same address, forever); per-account storage just makes
// the DISPLAY always match the ACTIVE account — a single "last derived"
// slot could show a personal address while a business account is active.
const EVM_ADDR_KEYCHAIN_SERVICE = 'confio_evm_address_v1';

/** Same account-key grammar as useAccountManager: personal_0, business_<id>_0 */
export function evmAccountKey(opts: {
  accountType: 'personal' | 'business';
  accountIndex: number;
  businessId?: string;
}): string {
  return opts.accountType === 'business' && opts.businessId
    ? `business_${opts.businessId}_${opts.accountIndex}`
    : `${opts.accountType}_${opts.accountIndex}`;
}

const evmAddressMemory: Record<string, string> = {};

function cacheAndPersistEvmWallet(acctKey: string, wallet: DerivedEvmWallet): void {
  lastDerivedEvmWallet = wallet;
  evmAddressMemory[acctKey] = wallet.address;
  Keychain.setGenericPassword('evm_address', wallet.address, {
    service: `${EVM_ADDR_KEYCHAIN_SERVICE}_${acctKey}`,
  }).catch(() => {});
}

export async function getEvmAddressForDisplay(accountKey: string): Promise<string | null> {
  if (evmAddressMemory[accountKey]) return evmAddressMemory[accountKey];
  try {
    const stored = await Keychain.getGenericPassword({
      service: `${EVM_ADDR_KEYCHAIN_SERVICE}_${accountKey}`,
    });
    return stored ? stored.password : null;
  } catch {
    return null;
  }
}

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

  // NO savings-chain sibling here: legacy V1 (OAuth-salt) wallets have no
  // BSC address by design — V1 users never could deposit on BSC, and
  // registering a V1-derived address would only conflict with the V2 one
  // they get after master-secret migration.

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
const REENROLLMENT_ATTESTATION_FILENAME = 'confio_wallet_reenrollment_attestation_v1.json';
const APP_BACKUP_KEY = 'ConfioWallet_Backup_Key_v1_DoNotShare';
const DRIVE_SECURITY_HEADER = 'ADVERTENCIA DE SEGURIDAD: NUNCA COMPARTAS ESTA CLAVE CON NADIE.';
const ADDRESS_BOUND_SECRET_PREFIX = 'confio_master_secret_v2_address_';

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

interface DriveBackupCandidate {
  fileId: string;
  revisionId?: string;
  name: string;
  modifiedTime?: string;
  walletId?: string | null;
  deviceHint?: string;
}

interface OldestDriveBackupResult {
  foundAny: boolean;
  secret: Uint8Array | null;
  walletId: string | null;
  deviceHint?: string | null;
  foundDecryptable?: boolean;
  // Whether the manifest contains entries from other OAuth identities,
  // independent of which candidate the sort ended up picking. Used by
  // getOrCreateMasterSecret to loudly abort when a user is about to
  // overwrite/share a Drive that holds another identity's wallet.
  manifestHasAndroidEntry?: boolean;
  manifestHasIosEntry?: boolean;
  // Distinct V2 *base* files seen on the Drive (revisions of the same file
  // don't count, but two different `confio_wallet_v2_<id>.enc` filenames
  // do). Used as a fallback signal when the manifest is empty/stale and
  // can't tell us about cross-identity entries — if Drive has more than
  // one distinct V2 file, somebody else's wallet is sitting next to ours.
  distinctV2FileCount?: number;
}

function secretsEqual(a?: Uint8Array | null, b?: Uint8Array | null): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a[i] ^ b[i];
  }
  return diff === 0;
}

// Pure by construction: this is used to VALIDATE untrusted candidates (Drive
// blobs, keychain reads), so it must not cache or persist anything derived from
// a secret that may be rejected a moment later.
function derivePersonalV2Address(masterSecret: Uint8Array): string {
  return deriveV2KeyMaterial(masterSecret, {
    accountType: 'personal',
    accountIndex: 0,
  }).address;
}

// EVM sibling of derivePersonalV2Address. Anchor for BSC-only users
// (Algorand deprecated): their server-registered bsc_address is immutable,
// so a secret must derive to it before we accept it.
/**
 * The PURE half of V2 derivation: HKDF seed plus the Algorand keypair, with no
 * caching, no Keychain writes, no globals.
 *
 * deriveWalletV2 is deliberately impure — it also derives and PERSISTS the EVM
 * sibling. That makes it unusable for validation: checking a Drive candidate's
 * identity commitment with it cached the rejected candidate's EVM address into
 * memory and the Keychain, which getEvmAddressForDisplay then trusted. Anything
 * that merely needs to ask "what address does this secret produce?" must use
 * this function.
 */
export function deriveV2AddressPure(
  clientSecret: Uint8Array,
  opts: { accountType: string; accountIndex: number; businessId?: string }
): string {
  return deriveV2KeyMaterial(clientSecret, opts).address;
}

function deriveV2KeyMaterial(
  clientSecret: Uint8Array,
  opts: { accountType: string; accountIndex: number; businessId?: string }
): { address: string; seed32: Uint8Array; keyPair: nacl.SignKeyPair } {
  const saltInput = opts.businessId
    ? `confio_v2_salt_${opts.accountType}_${opts.businessId}_${opts.accountIndex}`
    : `confio_v2_salt_${opts.accountType}_${opts.accountIndex}`;
  const salt = sha256(utf8ToBytes(saltInput));
  const info = utf8ToBytes(`confio|v2|derived|${saltInput}`);
  const seed32 = hkdf(sha256, clientSecret, salt, info, 32);
  const keyPair = nacl.sign.keyPair.fromSeed(seed32);
  const algosdk = require('algosdk');
  return { address: algosdk.encodeAddress(keyPair.publicKey), seed32, keyPair };
}

function derivePersonalEvmAddress(masterSecret: Uint8Array): string {
  return deriveEvmKeyFromMasterSecret(masterSecret, {
    accountType: 'personal',
    accountIndex: 0,
  }).address.toLowerCase();
}

async function storeAddressBoundMasterSecret(
  credentialStorage: any,
  address: string | null | undefined,
  masterSecret: Uint8Array
): Promise<void> {
  if (!address) return;
  await credentialStorage.storeSecret(`${ADDRESS_BOUND_SECRET_PREFIX}${address}`, masterSecret);
}

/**
 * Every V2 master secret is exactly 32 bytes (generateRandomSecret). Anything
 * else reaching HKDF is corruption, a truncated read, or a foreign blob — and
 * a short secret silently shrinks the keyspace, which is precisely the class
 * of failure this file must never allow. Reject at every trust boundary
 * rather than deriving an address nobody can fund.
 */
export const MASTER_SECRET_BYTES = 32;

/**
 * Written over the legacy global alias once it has been migrated. It is
 * deliberately not a valid secret, so the strict read path reports it as
 * corruption — and the legacy handler has to recognise it to avoid bricking
 * anyone whose tombstone deletion failed. Compared BYTE-EXACT: a sentinel that
 * suppresses a fail-closed check must not be satisfiable by anything else.
 */
const MIGRATION_TOMBSTONE_BYTES = utf8ToBytes('MIGRATED_TOMBSTONE');

/**
 * Throw unless `secret` derives to whichever server-registered address(es) the
 * caller supplied. Anchors are the ONLY real defense against adopting the wrong
 * wallet — the Drive blob's own commitment is forgeable by anyone holding the
 * app constant — so every point that ACCEPTS a candidate calls this before
 * persisting, tombstoning or uploading anything.
 */
/**
 * ANCHOR SEMANTICS — read this before changing the comparisons.
 *
 * The Algorand address and the EVM address are BOTH deterministic functions of
 * the same 32-byte master secret (derivePersonalV2Address /
 * derivePersonalEvmAddress, both fixed at personal / index 0). So matching ONE
 * supplied anchor already proves the secret is the one that produced it: short
 * of a hash collision, no other secret derives to that address.
 *
 * That has a consequence worth stating plainly, because this code got it wrong
 * once: requiring EVERY anchor to match adds NO security. It cannot tell a
 * wrong wallet from a right one, because a secret matching the Algorand anchor
 * necessarily produces exactly one EVM address as well. What an all-anchors
 * rule DOES do is brick any user whose server row is internally inconsistent —
 * a bsc_address registered from a stale cache or the wrong account context —
 * by rejecting the very secret that matches their authoritative Algorand
 * address. A lockout with no compensating benefit.
 *
 * So: at least one supplied anchor must match. Disagreement BETWEEN anchors is
 * a stale server record — logged loudly for reconciliation, never fatal. No
 * anchors at all imposes no constraint (the deliberate clean-device restore).
 */
type AnchorVerdict = 'no-anchors' | 'match' | 'mismatch';

function anchorVerdict(
  secret: Uint8Array,
  options: { expectedAddress?: string | null; expectedEvmAddress?: string | null } | undefined
): AnchorVerdict {
  const wantAlgo = options?.expectedAddress || null;
  const wantEvm = options?.expectedEvmAddress ? options.expectedEvmAddress.toLowerCase() : null;
  if (!wantAlgo && !wantEvm) return 'no-anchors';

  const algoMatches = wantAlgo ? derivePersonalV2Address(secret) === wantAlgo : null;
  const evmMatches = wantEvm ? derivePersonalEvmAddress(secret) === wantEvm : null;

  if (algoMatches === true && evmMatches === false) {
    console.error('[MasterSecret] STALE SERVER RECORD: secret matches the registered Algorand address but not the BSC one. Accepting on the Algorand anchor; the BSC record needs reconciliation.');
  }
  if (evmMatches === true && algoMatches === false) {
    console.error('[MasterSecret] STALE SERVER RECORD: secret matches the registered BSC address but not the Algorand one. Accepting on the BSC anchor; the Algorand record needs reconciliation.');
  }

  return algoMatches === true || evmMatches === true ? 'match' : 'mismatch';
}

/** True unless the secret contradicts every anchor the caller supplied. */
function matchesAnchors(
  secret: Uint8Array,
  options: { expectedAddress?: string | null; expectedEvmAddress?: string | null } | undefined
): boolean {
  return anchorVerdict(secret, options) !== 'mismatch';
}

/**
 * Throwing form, for the points that ACCEPT a candidate: persistence,
 * tombstoning, deletion, upload. Anchors are the only real defense against
 * adopting the wrong wallet — the Drive blob's own commitment is forgeable by
 * anyone holding the app constant — so acceptance points assert here.
 */
function assertAnchors(
  secret: Uint8Array,
  options: { expectedAddress?: string | null; expectedEvmAddress?: string | null } | undefined,
  what: string
): void {
  if (anchorVerdict(secret, options) === 'mismatch') {
    throw new Error(
      'No encontramos el respaldo correcto de tu billetera. Intenta con la cuenta de Google donde guardaste tu respaldo o contáctanos para ayudarte.'
    );
  }
  console.log(`[MasterSecret] Anchor check passed for ${what}.`);
}

function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export class CorruptMasterSecretError extends Error {
  constructor(source: string, length: number) {
    super(
      `[MasterSecret] Stored secret from ${source} is ${length < 0 ? 'not canonical base64' : `${length} bytes, expected ${MASTER_SECRET_BYTES}`}. ` +
      'Refusing to continue: this is corruption, not absence, and generating a replacement would ' +
      'overwrite the only copy of a wallet that may hold funds.'
    );
    this.name = 'CorruptMasterSecretError';
  }
}

/**
 * Raised when a corrupt local secret could not be repaired from Drive. The
 * user-facing text is Spanish because this surfaces directly in sign-in.
 */
export class CorruptMasterSecretRecoveryError extends Error {
  constructor() {
    super(
      'Los datos de tu billetera en este dispositivo están dañados y no encontramos un respaldo válido en Google Drive. ' +
      'Inicia sesión con la cuenta de Google donde guardaste tu respaldo, o contáctanos para ayudarte.'
    );
    this.name = 'CorruptMasterSecretRecoveryError';
  }
}

/**
 * A secret read out of LOCAL storage (keychain).
 *
 * Absent is a normal state — a clean device, a first login — and returns null
 * so the caller can restore or generate. Present-but-wrong-length is NOT
 * absence: it is a truncated or corrupted read of something that may have been
 * a real wallet. Returning null there would send the caller down the
 * generation path, which overwrites the alias and destroys the only copy. So
 * that case throws and stops the flow.
 */
/**
 * Read key material and normalise every failure mode the repair path must
 * recognise. `retrieveSecretStrict` throws NonCanonicalBase64Error for a
 * malformed stored value; that is corruption exactly like a wrong length, and
 * the handlers below only know CorruptMasterSecretError — so convert it here
 * rather than letting a second error type escape the recovery logic.
 *
 * SecureStorageReadError is deliberately NOT converted: "could not read" is not
 * "corrupt", it must not enable repair-by-replacement, and it propagates.
 */
async function readMasterSecret(
  credentialStorage: any,
  key: string,
  source: string
): Promise<Uint8Array | null> {
  let raw: Uint8Array | null;
  try {
    raw = await credentialStorage.retrieveSecretStrict(key);
  } catch (error) {
    if (error instanceof NonCanonicalBase64Error) {
      throw new CorruptMasterSecretError(source, -1);
    }
    throw error;
  }
  return storedMasterSecret(raw, source);
}

function storedMasterSecret(
  secret: Uint8Array | null | undefined,
  source: string
): Uint8Array | null {
  if (!secret) return null;
  if (secret.length !== MASTER_SECRET_BYTES) {
    throw new CorruptMasterSecretError(source, secret.length);
  }
  return secret;
}

/**
 * A secret decrypted from a DRIVE backup candidate.
 *
 * Different contract from local storage: we are filtering a list of files, any
 * of which may be foreign or damaged. A wrong-length blob is skipped so the
 * scan can keep looking, rather than aborting the whole restore.
 */
function driveCandidateSecret(
  secret: Uint8Array | null | undefined,
  source: string
): Uint8Array | null {
  if (!secret) return null;
  if (secret.length !== MASTER_SECRET_BYTES) {
    console.warn(
      `[MasterSecret] Skipping ${secret.length}-byte candidate from ${source}; expected ${MASTER_SECRET_BYTES}.`
    );
    return null;
  }
  return secret;
}

async function retrieveAddressBoundMasterSecret(
  credentialStorage: any,
  address: string | null | undefined
): Promise<Uint8Array | null> {
  if (!address) return null;
  return readMasterSecret(
    credentialStorage,
    `${ADDRESS_BOUND_SECRET_PREFIX}${address}`,
    'address-bound keychain alias'
  );
}

async function tryStoreRecoveredSecret(
  credentialStorage: any,
  key: string,
  secret: Uint8Array,
  label: string
): Promise<boolean> {
  try {
    await credentialStorage.storeSecret(key, secret);
    return true;
  } catch (error) {
    console.warn(`[MasterSecret] Failed to persist recovered ${label}; continuing with Drive-backed in-memory secret.`, error);
    return false;
  }
}

async function tryStoreRecoveredAddressBoundSecret(
  credentialStorage: any,
  address: string | null | undefined,
  masterSecret: Uint8Array
): Promise<void> {
  if (!address) return;
  await tryStoreRecoveredSecret(
    credentialStorage,
    `${ADDRESS_BOUND_SECRET_PREFIX}${address}`,
    masterSecret,
    'address-bound secret'
  );
}

// Mutex to prevent race conditions during secret creation
let v2SecretMutex: Promise<void> = Promise.resolve();

/**
 * Generate a random V2 client secret using CSPRNG.
 * INTERNAL USE ONLY
 *
 * Straight from the platform CSPRNG, never via global.crypto — see
 * entropyGuard.ts for why that global cannot be trusted to be native-backed.
 */
function generateRandomSecret(): Uint8Array {
  return secureRandomBytes(32, 'a new wallet master secret');
}

/**
 * Simple UUID v4 generator using the existing CSPRNG
 */
function generateUUID(): string {
  const b = secureRandomBytes(16, 'a wallet id');
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
      const parsed = JSON.parse(content);
      // Valid JSON is not a valid manifest. Callers immediately do
      // `manifest.wallets.filter(...)`, so a malformed-but-parseable file threw
      // a TypeError deep in the restore path instead of degrading to "no
      // manifest". Treat anything unexpected as empty.
      if (parsed && Array.isArray(parsed.wallets)) {
        // Array.isArray is not enough: `{"wallets":[null]}` passes it and then
        // throws on the first `entry.id` dereference downstream, which denies
        // restore and migration until the file is repaired by hand. Drop
        // non-object entries instead of trusting the array's contents.
        // Normalise the fields we actually consume. Filtering out null was not
        // enough: `{"deviceHint": 1}` survives an object check and then throws
        // on `.toLowerCase()` downstream. Coerce or drop instead.
        //
        // An entry with no usable `id` is dropped outright rather than kept
        // with `id: undefined`. Consumers key off `wallets.length` and derive
        // hasBackup / Android-vs-iOS signals from the list, so an unusable
        // entry inflated the count, triggered pointless Drive scans, and could
        // contribute a device signal that fails an Apple restore closed.
        const wallets = parsed.wallets
          .filter((entry: any) => !!entry && typeof entry === 'object' && typeof entry.id === 'string' && entry.id.length > 0)
          .map((entry: any) => ({
            ...entry,
            id: entry.id,
            deviceHint: typeof entry.deviceHint === 'string' ? entry.deviceHint : undefined,
            // Reused verbatim when the manifest is rewritten, so a non-string
            // here would be persisted back into the file.
            createdAt: typeof entry.createdAt === 'string' ? entry.createdAt : undefined,
          }));
        if (wallets.length !== parsed.wallets.length) {
          console.warn(
            `[Manifest] Dropped ${parsed.wallets.length - wallets.length} malformed manifest entr${parsed.wallets.length - wallets.length === 1 ? 'y' : 'ies'}.`
          );
        }
        return { ...parsed, wallets } as WalletManifest;
      }
      console.warn('[Manifest] Parsed content is not a manifest; treating as empty.');
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
 * Re-download and fully validate the canonical backup, then persist a signed,
 * hash-bound Drive checkpoint before the destructive reenrollment transition.
 * The OAuth token and ciphertext stay client-side: reportBackupStatus remains
 * telemetry, not a backend authorization factor.
 */
export async function createWalletReenrollmentDriveAttestation(
  accessToken: string,
  challenge: string,
  bscAddress: string,
  bscPrivateKeyHex: string,
): Promise<{ ownershipSignature: string; backupSignature: string }> {
  const { googleDriveStorage } = await import('./googleDriveStorage');
  const manifestFiles = await googleDriveStorage.listFiles(accessToken, MANIFEST_FILENAME);
  if (manifestFiles.length === 0) throw new Error('Google Drive wallet manifest is missing');
  const newestManifest = [...manifestFiles].sort((a, b) => getBackupTime(b) - getBackupTime(a))[0];
  const manifest = JSON.parse(await googleDriveStorage.downloadFile(accessToken, newestManifest.id));
  if (!Array.isArray(manifest?.wallets) || manifest.wallets.length !== 1) {
    throw new Error('Google Drive wallet manifest is not canonical');
  }
  const walletId = manifest.wallets[0]?.id;
  if (typeof walletId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(walletId)) {
    throw new Error('Google Drive wallet id is invalid');
  }
  const backupFiles = await googleDriveStorage.listFiles(
    accessToken,
    `confio_wallet_v2_${walletId}.enc`,
  );
  if (backupFiles.length === 0) throw new Error('Google Drive wallet backup is missing');
  const newestBackup = [...backupFiles].sort((a, b) => getBackupTime(b) - getBackupTime(a))[0];
  const backup = await googleDriveStorage.downloadFile(accessToken, newestBackup.id);
  const prefix = `${DRIVE_SECURITY_HEADER}\n`;
  if (!backup.startsWith(prefix)) throw new Error('Google Drive wallet backup is invalid');
  const recovered = decryptBackupV2(backup.slice(prefix.length).trim(), APP_BACKUP_KEY);
  if (!recovered || derivePersonalEvmAddress(recovered).toLowerCase() !== bscAddress.toLowerCase()) {
    throw new Error('Google Drive wallet backup does not match the replacement wallet');
  }
  const backupSha256 = bytesToHex(sha256(utf8ToBytes(backup)));
  const backupChallenge = walletReenrollmentBackupChallenge(
    challenge,
    bscAddress,
    walletId,
    backupSha256,
  );
  const ownershipSignature = signEip191Message(challenge, bscPrivateKeyHex);
  const backupSignature = signEip191Message(backupChallenge, bscPrivateKeyHex);
  const content = JSON.stringify({
    version: 1,
    challenge,
    bscAddress: bscAddress.toLowerCase(),
    ownershipSignature,
    walletId,
    backupSha256,
    backupSignature,
    createdAt: new Date().toISOString(),
  });
  const files = await googleDriveStorage.listFiles(accessToken, REENROLLMENT_ATTESTATION_FILENAME);
  if (files.length > 0) {
    await googleDriveStorage.updateFile(accessToken, files[0].id, content);
  } else {
    await googleDriveStorage.createFile(accessToken, REENROLLMENT_ATTESTATION_FILENAME, content);
  }
  return { ownershipSignature, backupSignature };
}

function walletReenrollmentBackupChallenge(
  challenge: string,
  bscAddress: string,
  walletId: string,
  backupSha256: string,
): string {
  return [
    'Confio wallet Drive backup attestation v1',
    `challenge_sha256:${bytesToHex(sha256(utf8ToBytes(challenge)))}`,
    `bsc_address:${bscAddress.toLowerCase()}`,
    `wallet_id:${walletId}`,
    `backup_sha256:${backupSha256.toLowerCase()}`,
  ].join('\n');
}

function getBackupTime(candidate: { modifiedTime?: string }): number {
  const time = candidate.modifiedTime ? new Date(candidate.modifiedTime).getTime() : 0;
  return Number.isFinite(time) ? time : 0;
}

function extractWalletIdFromBackupName(name?: string): string | null {
  if (!name) return null;
  const match = name.match(/confio_wallet_v2_(.+?)\.enc/);
  return match?.[1] || null;
}

async function findOldestRestorableDriveBackup(
  accessToken: string,
  userSub: string,
  googleDriveStorage: any,
  AES: any,
  appBackupKey: string,
  Utf8: any,
  expectedAddress?: string | null,
  expectedEvmAddress?: string | null
): Promise<OldestDriveBackupResult> {
  // A candidate must derive to EVERY anchor the caller supplied, not any one
  // of them. Google login supplies both the Algorand and the BSC address, and
  // "any" let a candidate that matched Algorand but NOT the registered BSC
  // address be adopted — a different wallet on the savings chain. Callers with
  // only one anchor (BSC-only accounts have no Algorand address) are unchanged
  // because an absent anchor imposes no constraint. No anchors at all = accept
  // the oldest, which is the deliberate clean-device restore behaviour.
  // One definition of acceptance, shared with every other call site.
  const candidateMatchesAnchor = (decrypted: Uint8Array): boolean =>
    matchesAnchors(decrypted, { expectedAddress, expectedEvmAddress });
  const safeSub = bytesToHex(sha256(utf8ToBytes(userSub)));
  const legacyFilename = `confio_master_secret_v2_${safeSub}.json`;
  const manifest = await fetchManifest(googleDriveStorage, accessToken);
  const manifestById = new Map(
    manifest.wallets
      .filter(entry => !!entry.id)
      .map(entry => [entry.id, entry])
  );
  const androidWalletIds = new Set(
    manifest.wallets
      .filter(entry => (entry.deviceHint || '').toLowerCase().includes('android'))
      .map(entry => entry.id)
  );
  const manifestHasAndroidEntry = manifest.wallets.some(entry =>
    (entry.deviceHint || '').toLowerCase().includes('android')
  );
  const manifestHasIosEntry = manifest.wallets.some(entry => {
    const hint = (entry.deviceHint || '').toLowerCase();
    return hint.includes('ios') || hint.includes('iphone') || hint.includes('ipad');
  });

  // FAST PATH: when we know which address we're recovering AND the manifest
  // names some entries, try just those files' HEADs directly. The full scan
  // below (active + trashed listing + every revision + decrypt-every) costs
  // 10–30 Drive API calls on a slow mobile connection — exactly what made
  // the cold-start Android login (no BlockStore) feel stuck on
  // "Verificando seguridad del dispositivo...". The targeted path is 1
  // listFiles + 1 downloadFile per manifest entry.
  if ((expectedAddress || expectedEvmAddress) && manifest.wallets.length > 0) {
    for (const entry of manifest.wallets) {
      if (!entry.id) continue;
      const filename = `confio_wallet_v2_${entry.id}.enc`;
      try {
        const matches = await googleDriveStorage.listFiles(accessToken, filename);
        if (matches.length === 0) continue;
        const content = await googleDriveStorage.downloadFile(accessToken, matches[0].id);
        const decrypted = decryptBackup(content, AES, appBackupKey, Utf8);
        if (!decrypted) continue;
        const candidateAddress = derivePersonalV2Address(decrypted);
        if (candidateMatchesAnchor(decrypted)) {
          console.log('[MasterSecret] Fast-path matched manifest entry HEAD:', {
            id: entry.id,
            deviceHint: entry.deviceHint || 'unknown',
          });
          return {
            foundAny: true,
            secret: decrypted,
            walletId: entry.id,
            deviceHint: entry.deviceHint || null,
            foundDecryptable: true,
            manifestHasAndroidEntry,
            manifestHasIosEntry,
            // Fast path can't see all Drive files, so leave the count
            // undefined here — the caller's guards only apply on the
            // no-expectedAddress paths anyway.
          };
        }
        console.log('[MasterSecret] Fast-path entry did not match expected anchors; continuing.', {
          id: entry.id,
          candidateAddress,
          expectedAddress,
          expectedEvmAddress,
        });
      } catch (e) {
        console.warn('[MasterSecret] Fast-path failed for manifest entry; falling back to full scan.', entry.id, e);
      }
    }
  }

  const activeFiles = await googleDriveStorage.listFiles(accessToken);
  let trashedFiles: any[] = [];
  try {
    trashedFiles = await googleDriveStorage.listFiles(accessToken, undefined, true);
  } catch (e) {
    console.warn('[MasterSecret] Failed to list trashed Drive backups:', e);
  }

  const files = [...activeFiles, ...trashedFiles].filter((f: any) =>
    (f.name && f.name.startsWith('confio_wallet_v2_')) ||
    f.name === legacyFilename
  );

  // Count distinct V2 base files on this Drive (ignoring revisions and the
  // legacy `confio_master_secret_v2_<sub>.json`). This survives an empty
  // or stale manifest, which the manifest-tag heuristics don't.
  const v2WalletIds = new Set<string>();
  for (const f of files) {
    if (!f.name || !f.name.startsWith('confio_wallet_v2_') || !f.name.endsWith('.enc')) continue;
    const id = extractWalletIdFromBackupName(f.name);
    if (id) v2WalletIds.add(id);
  }
  const distinctV2FileCount = v2WalletIds.size;

  if (files.length === 0) {
    return {
      foundAny: false,
      secret: null,
      walletId: null,
      manifestHasAndroidEntry,
      manifestHasIosEntry,
      distinctV2FileCount,
    };
  }

  const candidates: DriveBackupCandidate[] = [];
  for (const file of files) {
    const walletId = extractWalletIdFromBackupName(file.name);
    const manifestEntry = walletId ? manifestById.get(walletId) : undefined;
    candidates.push({
      fileId: file.id,
      name: file.name,
      modifiedTime: file.modifiedTime || file.createdTime,
      walletId,
      deviceHint: manifestEntry?.deviceHint,
    });

    try {
      const revisions = await googleDriveStorage.listRevisions(accessToken, file.id);
      for (const revision of revisions || []) {
        candidates.push({
          fileId: file.id,
          revisionId: revision.id,
          name: `${file.name} [Rev ${revision.modifiedTime}]`,
          modifiedTime: revision.modifiedTime,
          walletId,
          deviceHint: manifestEntry?.deviceHint,
        });
      }
    } catch (e) {
      console.warn('[MasterSecret] Failed to list Drive backup revisions:', file.name, e);
    }
  }

  candidates.sort((a, b) => {
    const aAndroid = !!a.walletId && androidWalletIds.has(a.walletId);
    const bAndroid = !!b.walletId && androidWalletIds.has(b.walletId);
    if (aAndroid !== bAndroid) return aAndroid ? -1 : 1;
    return getBackupTime(a) - getBackupTime(b);
  });

  let foundDecryptable = false;
  for (const candidate of candidates) {
    try {
      const content = await googleDriveStorage.downloadFile(
        accessToken,
        candidate.fileId,
        candidate.revisionId
      );
      const decrypted = decryptBackup(content, AES, appBackupKey, Utf8);
      if (decrypted) {
        foundDecryptable = true;
        const candidateAddress = derivePersonalV2Address(decrypted);
        if (!candidateMatchesAnchor(decrypted)) {
          console.log('[MasterSecret] Skipping Drive backup candidate with non-matching address:', {
            name: candidate.name,
            candidateAddress,
            expectedAddress,
            expectedEvmAddress,
            deviceHint: candidate.deviceHint || 'unknown',
          });
          continue;
        }

        console.log('[MasterSecret] Restored oldest Drive V2 backup:', {
          name: candidate.name,
          modifiedTime: candidate.modifiedTime,
          walletId: candidate.walletId || 'legacy/no-id',
          deviceHint: candidate.deviceHint || 'unknown',
          address: candidateAddress,
        });
        return {
          foundAny: true,
          secret: decrypted,
          walletId: candidate.walletId || null,
          deviceHint: candidate.deviceHint || null,
          foundDecryptable,
          manifestHasAndroidEntry,
          manifestHasIosEntry,
          distinctV2FileCount,
        };
      }
    } catch (e) {
      console.warn('[MasterSecret] Failed to restore Drive backup candidate:', candidate.name, e);
    }
  }

  return {
    foundAny: true,
    secret: null,
    walletId: null,
    foundDecryptable,
    manifestHasAndroidEntry,
    manifestHasIosEntry,
    distinctV2FileCount,
  };
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
    await storeAddressBoundMasterSecret(
      credentialStorage,
      derivePersonalV2Address(decrypted),
      decrypted
    );

    // Also store the wallet ID if we have it, or try to derive it/fail gracefully
    // BUT we must overwrite the current wallet ID to prevent mismatch
    const isSyntheticRestoreId = !walletId || walletId === 'null' || walletId === 'legacy_rescue_option' || walletId.startsWith('deep_search_');
    if (walletId && !isSyntheticRestoreId) {
      await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(walletId));
    } else {
      // If restored from null ID, try to get ID from filename if possible?
      // confio_wallet_v2_ID.enc
      const match = filename.match(/confio_wallet_v2_(.+?)\.enc/);
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
 * STRATEGY: CANONICAL DRIVE BACKUP + UUID
 * 
 * 1. LOCAL: Check for existing `walletId` and `secret`.
 * 2. CLOUD (Restore): With Drive access, restore the oldest valid V2 backup
 *    automatically. There is no user picker and no "use current wallet" branch.
 * 3. CLOUD (Backup):
 *    - Sync the canonical secret and rewrite the manifest to exactly one entry.
 * 
 * @param userSub - Unique user identifier (OAuth Subject) to namespace local storage
 * @returns The master secret (32 bytes)
 */
export async function getOrCreateMasterSecret(
  userSub: string,
  accessToken?: string,
  options?: {
    allowGenerate?: boolean;
    provider?: 'google' | 'apple';
    expectedAddress?: string | null;
    /**
     * EVM (BSC) anchor for accounts with no Algorand address (Algorand
     * deprecated). Local and Drive-restored secrets must derive to this
     * personal-account EVM address; a matching restore also bypasses the
     * Apple cross-identity guard (which otherwise aborts every clean-device
     * restore because there is no local secret to compare against).
     */
    expectedEvmAddress?: string | null;
    requireCloudSync?: boolean;
    /**
     * Request-scoped backend JWT used by backup telemetry while a login has
     * deliberately not persisted its session yet (wallet reenrollment).
     * Keeping these fire-and-forget reports pinned prevents a late auth-link
     * cleanup from deleting the valid JWT persisted after reenrollment.
     */
    backupReportAuthToken?: string;
    /**
     * Reports whether the Drive backup upload in this call actually completed.
     * Never called when no accessToken is provided or when the fast path
     * returns without touching Drive — callers must default to "not synced".
     */
    onCloudSyncResult?: (synced: boolean) => void;
  }
): Promise<Uint8Array> {
  if (!userSub) {
    throw new Error('[MasterSecret] User Sub (OAuth ID) is required to secure the master secret.');
  }

  const safeSub = bytesToHex(sha256(utf8ToBytes(userSub)));
  const secretAlias = `confio_master_secret_v2_${safeSub}`;
  const walletIdKey = `confio_wallet_id_v2_${safeSub}`; // Store the UUID locally
  const legacyAlias = 'confio_master_secret';

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

    // =================================================================================
    // 1. LOCAL CHECK
    // =================================================================================
    // Corruption is a THIRD state, distinct from both "have it" and "absent".
    // Throwing here outright would be safe against overwriting, but it would
    // also brick the one thing that can repair the damage: an address-anchored
    // Drive restore. So record it, let the Drive scan below run, and forbid
    // generation at the end — the restore can rewrite the alias, and if no
    // valid backup turns up we refuse rather than mint a replacement.
    let localSecretCorrupt = false;
    let localSecret: Uint8Array | null = null;
    try {
      localSecret = await readMasterSecret(
        credentialStorage,
        secretAlias,
        'subject-bound keychain alias'
      );
    } catch (error) {
      if (!(error instanceof CorruptMasterSecretError)) throw error;
      console.error('[MasterSecret] Local secret is corrupt. Generation is now blocked; attempting anchored recovery.', error);
      localSecretCorrupt = true;

      // Repairing corruption REQUIRES an identity anchor. Without one, the
      // Drive scan accepts the oldest decryptable backup (the cross-identity
      // guard below is Apple-only), so a corrupt alias could be silently
      // replaced with a DIFFERENT wallet that happens to live in the same
      // Drive. Refuse instead — the caller can retry once it knows the address.
      if (!options?.expectedAddress && !options?.expectedEvmAddress) {
        throw new CorruptMasterSecretRecoveryError();
      }

      // A valid address-bound copy may still exist locally. The subject-bound
      // read is what was damaged; check the other alias before reaching for
      // Drive at all.
      //
      // That lookup validates too, so it can throw CorruptMasterSecretError of
      // its OWN — and letting that escape here meant damage to the SECOND alias
      // aborted the whole recovery before Drive was ever scanned. Swallow it:
      // a bad secondary copy is just an exhausted local option, not a reason to
      // give up on the backup that can actually repair this.
      let addressBound: Uint8Array | null = null;
      try {
        addressBound = await retrieveAddressBoundMasterSecret(
          credentialStorage,
          options.expectedAddress
        );
      } catch (secondaryError) {
        if (!(secondaryError instanceof CorruptMasterSecretError)) throw secondaryError;
        console.warn('[MasterSecret] Address-bound copy is also corrupt; falling through to Drive.', secondaryError);
      }

      // Same acceptance rule as everywhere else — this branch used to hand-roll
      // an Algorand-only comparison, clear the corruption flag and persist,
      // leaving the backstop to catch a partially-validated candidate after the
      // subject alias had already been rewritten.
      if (addressBound && matchesAnchors(addressBound, options)) {
        console.log('[MasterSecret] Repaired corrupt subject alias from the local address-bound copy.');
        localSecret = addressBound;
        localSecretCorrupt = false;
        await tryStoreRecoveredSecret(
          credentialStorage,
          secretAlias,
          localSecret,
          'corrupt subject-bound secret'
        );
      }
    }
    let localWalletIdBytes = await credentialStorage.retrieveSecret(walletIdKey);
    let localWalletId = localWalletIdBytes ? decodeUtf8(localWalletIdBytes) : null;

    if (localSecret && (options?.expectedAddress || options?.expectedEvmAddress)) {
      // EVERY supplied anchor must hold, not just the Algorand one. Google
      // login supplies both; checking only Algorand let a secret that derives
      // to the right Algorand address but the WRONG registered BSC address be
      // fast-pathed, persisted and returned.
      if (!matchesAnchors(localSecret, options)) {
        console.warn('[MasterSecret] Local subject-bound V2 secret does not match the server anchors. Checking address-bound restore alias.', {
          expectedAddress: options.expectedAddress,
          expectedEvmAddress: options.expectedEvmAddress,
        });
        // A damaged SECONDARY alias must not abort anchored Drive recovery —
        // same reasoning as the corruption handler above, different branch.
        // SecureStorageReadError still propagates: "could not read" is not
        // licence to keep going.
        let addressBoundSecret: Uint8Array | null = null;
        try {
          addressBoundSecret = await retrieveAddressBoundMasterSecret(
            credentialStorage,
            options.expectedAddress
          );
        } catch (secondaryError) {
          if (!(secondaryError instanceof CorruptMasterSecretError)) throw secondaryError;
          console.warn('[MasterSecret] Address-bound alias is corrupt; continuing to Drive recovery.', secondaryError);
        }
        // Validate BEFORE adopting and persisting. The alias is keyed by
        // address, but the value stored under it is not proof of anything —
        // accepting it unchecked wrote a possibly-wrong secret over the subject
        // alias, and the final anchor guard then rejected it AFTER the damage.
        if (addressBoundSecret && !matchesAnchors(addressBoundSecret, options)) {
          console.warn('[MasterSecret] Address-bound alias does not satisfy every server anchor; ignoring it.');
          addressBoundSecret = null;
        }

        if (addressBoundSecret) {
          localSecret = addressBoundSecret;
          await tryStoreRecoveredSecret(
            credentialStorage,
            secretAlias,
            localSecret,
            'subject-bound secret'
          );
          console.log('[MasterSecret] Recovered V2 secret from address-bound alias.');
        } else if (options.allowGenerate === false && !accessToken) {
          throw new Error(
            'Esta cuenta ya fue vinculada a otra billetera. Necesitamos recuperar esa billetera desde Google Drive antes de continuar.'
          );
        }
      } else {
        // Every supplied anchor holds. Safe to bind and fast-path.
        if (options.expectedAddress) {
          await storeAddressBoundMasterSecret(
            credentialStorage,
            options.expectedAddress,
            localSecret
          );
        }
        // FAST PATH: local secret already derives to the server's recorded
        // address. The Drive scan + cloud sync below would just re-upload the
        // same bytes with a new IV. On a slow network that costs 8–16 Drive
        // API calls per login and is what made "Verificando seguridad del
        // dispositivo..." appear stuck. Return the verified secret directly.
        //
        // NEVER take this shortcut when the caller demands a real upload
        // (requireCloudSync, e.g. enableDriveBackup): returning here used to
        // skip Section 4 entirely, so "backup verified" was reported to the
        // server while the user's Drive stayed empty — an unrecoverable
        // lockout once the local Keystore was wiped (user 10090).
        if (!options?.requireCloudSync) {
          console.log('[MasterSecret] Local secret matches every server anchor. Skipping Drive scan.');
          return localSecret;
        }
        console.log('[MasterSecret] Local secret matches every server anchor but cloud sync is required. Continuing to Drive backup.');
      }
    }

    // (The separate EVM-only anchored check that used to live here is gone: the
    // unified matchesAnchors block above covers it, and having two partial
    // checks was exactly how a candidate could satisfy one anchor and skip the
    // other.)

    // SANITY CHECK: Ensure we never use the string "null" or "undefined" as an ID
    if (localWalletId === 'null' || localWalletId === 'undefined') {
      console.warn('[MasterSecret] Detected corrupted wallet ID "null"/"undefined". Treating as missing.');
      localWalletId = null;
    }

    // --- ACL MIGRATION HOOK (iOS) ---
    // Only for a secret that has CLEARED every supplied anchor. Reaching here
    // with a mismatching localSecret is normal (the block above falls through
    // to Drive recovery), and rewriting it would persist the wrong secret and
    // report iCloud safety for it — before the final guards ever run.
    if (localSecret && Platform.OS === 'ios' && matchesAnchors(localSecret, options)) {
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
    // 2. CLOUD RESTORE
    // =================================================================================
    if (accessToken) {
      console.log('[MasterSecret] Drive available. Restoring oldest Drive V2 backup if present...');
      const restore = await findOldestRestorableDriveBackup(
        accessToken,
        userSub,
        googleDriveStorage,
        AES,
        APP_BACKUP_KEY,
        Utf8,
        options?.expectedAddress,
        options?.expectedEvmAddress
      );

      if (restore.secret) {
        const restoredAddress = derivePersonalV2Address(restore.secret);
        const restoredDeviceHint = (restore.deviceHint || '').toLowerCase();
        const restoredFromAndroid = restoredDeviceHint.includes('android');
        if (options?.expectedAddress && restoredAddress !== options.expectedAddress) {
          throw new Error(
            'El respaldo encontrado en Google Drive pertenece a otra billetera. Usa la cuenta de Google correcta o contacta a soporte.'
          );
        }

        // EVM anchor (BSC-only accounts): the restored secret must derive to
        // the server-registered BSC address. A verified match doubles as
        // proof this is the right wallet, so it bypasses the Apple
        // cross-identity guard below (a clean device has no local secret to
        // compare, which would otherwise abort every legitimate restore).
        let evmAnchorValidated = false;
        if (!options?.expectedAddress && options?.expectedEvmAddress) {
          const restoredEvm = derivePersonalEvmAddress(restore.secret);
          if (restoredEvm !== options.expectedEvmAddress.toLowerCase()) {
            throw new Error(
              'El respaldo encontrado en Google Drive pertenece a otra billetera. Usa la cuenta de Google correcta o contacta a soporte.'
            );
          }
          evmAnchorValidated = true;
        }

        // Cross-identity guards. Per the architectural rules: the
        //   differentiator is the OAuth PROVIDER, not the device platform.
        //   - Google Sign-In is always Google-derived (Android wallet IS
        //     the Drive backup; Google-on-iOS is still Google-derived).
        //     Multiple historical backups on the user's own Drive are
        //     normal — never abort.
        //   - Apple Sign-In creates a separate iOS-Keychain wallet that
        //     could collide with a pre-existing Google-derived backup on
        //     the same Drive. Abort when there's any signal of one.
        //
        // Triggered only on the no-`expectedAddress` paths (enableDrive,
        // new user). The login path with a known target address is
        // already protected by the address-filter inside
        // findOldestRestorableDriveBackup.
        const multipleV2BackupsOnDrive =
          typeof restore.distinctV2FileCount === 'number' &&
          restore.distinctV2FileCount > 1;

        if (
          options?.provider === 'apple' &&
          !options?.expectedAddress &&
          !evmAnchorValidated &&
          (restore.manifestHasAndroidEntry ||
            multipleV2BackupsOnDrive ||
            restoredFromAndroid ||
            !secretsEqual(localSecret, restore.secret))
        ) {
          throw new Error(
            'Este Google Drive ya guarda el respaldo de otra billetera Confío. Para respaldar esta billetera, elige otra cuenta de Google.'
          );
        }

        const keepUnanchoredLocal = !!localSecret &&
          !secretsEqual(localSecret, restore.secret) &&
          !options?.expectedAddress &&
          !options?.expectedEvmAddress;
        if (localSecret && !secretsEqual(localSecret, restore.secret)) {
          // Replacing a DIFFERENT local secret needs positive evidence that the
          // Drive copy is the right one. With no anchors, candidateMatchesAnchor
          // accepts the oldest decryptable blob, so an unanchored caller (a
          // BSC-only account, whose bsc_address is not yet on AccountType, has
          // no anchor to pass) could overwrite a perfectly good local wallet
          // and then upload it as canonical. Keep what we have instead.
          if (keepUnanchoredLocal && !options?.requireCloudSync) {
            console.warn('[MasterSecret] Drive holds a different secret but no anchor was supplied; keeping the local secret rather than replacing it.');
            return localSecret;
          }
          if (keepUnanchoredLocal) {
            // Reenrollment requires a real cloud checkpoint. Preserve the
            // local wallet, but continue to the upload section so its backup
            // and manifest become canonical instead of failing every retry.
            console.warn('[MasterSecret] Drive holds a different unanchored secret; required cloud sync will canonicalize the local wallet.');
          } else {
            console.log('[MasterSecret] Replacing local V2 secret with canonical Drive backup.');
          }
        }
        if (!keepUnanchoredLocal) {
          localSecret = restore.secret;
          localWalletId = restore.walletId || generateUUID();

          await tryStoreRecoveredSecret(
            credentialStorage,
            secretAlias,
            localSecret,
            'subject-bound secret'
          );
          await tryStoreRecoveredSecret(
            credentialStorage,
            walletIdKey,
            stringToUtf8Bytes(localWalletId),
            'wallet id'
          );
          await tryStoreRecoveredAddressBoundSecret(
            credentialStorage,
            restoredAddress,
            localSecret
          );

          const restoreReport = reportBackupStatus(
            'google_drive',
            options?.backupReportAuthToken,
          );
          if (options?.backupReportAuthToken) {
            // Reenrollment persists its JWT only after this function returns.
            // Finish the pinned report first so no auth cleanup can race that
            // later write even if the Apollo link behavior changes again.
            await restoreReport;
          } else {
            restoreReport.catch(e => console.warn('[BackupHealth] Drive restore report failed', e));
          }
        }
      } else if (restore.foundAny) {
        if ((options?.expectedAddress || options?.expectedEvmAddress) && restore.foundDecryptable) {
          throw new Error('No encontramos en este Google Drive el respaldo de la billetera registrada para esta cuenta.');
        }
        throw new Error('[MasterSecret] Existing Drive wallet backups were found but none could be decrypted; refusing to generate a replacement secret.');
      }
    }

    // FINAL ANCHOR BACKSTOP: every acceptance point above validates its own
    // candidate, but this is the last place before persistence and cloud sync,
    // so assert once more against EVERY supplied anchor. The two guards that
    // used to live here were mutually exclusive (`expectedAddress` vs
    // `!expectedAddress`), which meant a caller supplying BOTH — Google login
    // does — only ever had the Algorand half checked.
    if (localSecret) {
      assertAnchors(localSecret, options, 'the secret about to be persisted');
    }

    // =================================================================================
    // 3. GENERATION (If still missing)
    // =================================================================================
    if (!localSecret) {
      // The Drive restore above was this user's chance to repair a corrupt
      // alias. It did not, so stop: generating here would overwrite the only
      // copy of a wallet that may hold funds, which is strictly worse than
      // refusing to sign in.
      if (localSecretCorrupt) {
        throw new CorruptMasterSecretRecoveryError();
      }

      // NOTE: allowGenerate:false is checked AFTER the legacy-alias read, not
      // before it. Refusing here first meant a returning user whose only
      // surviving local copy was the legacy global alias could never migrate
      // it, even when it satisfied every server anchor — a recovery lockout
      // caused by the guard rather than by missing data. Reading the alias
      // generates nothing; only the else-branch below does.

      // Check Legacy Local (Migration from V1 Global).
      //
      // STRICT: this is key material, and the `else` branch below GENERATES a
      // replacement. Reading it leniently meant an unreadable Keychain or a
      // malformed value returned null, fell through, and minted a new wallet
      // over a funded legacy one — the exact loss condition the strict read
      // path exists to prevent.
      let legacyGlobalSecret: Uint8Array | null = null;
      try {
        legacyGlobalSecret = await readMasterSecret(
          credentialStorage,
          legacyAlias,
          'legacy global alias'
        );
      } catch (legacyErr) {
        // The tombstone written after a successful migration is deliberately
        // not a 32-byte secret, so it trips the corruption check. Distinguish
        // it from real damage: a tombstone means "already migrated, carry on";
        // anything else of the wrong length must still fail closed.
        if (!(legacyErr instanceof CorruptMasterSecretError)) throw legacyErr;
        const raw = await credentialStorage.retrieveSecret(legacyAlias);
        // Byte-exact, not string-compare: decodeUtf8 strips a UTF-8 BOM, so a
        // BOM-prefixed value would have passed as a tombstone. A sentinel that
        // suppresses a fail-closed check has to match exactly.
        const isTombstone = !!raw && bytesEqual(raw, MIGRATION_TOMBSTONE_BYTES);
        if (!isTombstone) throw legacyErr;
        console.log('[MasterSecret] Legacy alias holds a migration tombstone; treating as absent.');
      }

      // Anchor checks happen HERE, before anything is written. The final guard
      // further down runs too late to help: by then the legacy alias has been
      // tombstoned and deleted, or a fresh secret has been persisted and
      // queued for upload. Validate each candidate at the moment it is chosen.
      if (legacyGlobalSecret) {
        // A legacy secret that does not derive to the server's address is not
        // this account's wallet; migrating it would tombstone the original and
        // adopt the wrong one.
        assertAnchors(legacyGlobalSecret, options, 'the legacy global secret');

        console.log('[MasterSecret] Migrating Local Legacy Secret...');
        localSecret = legacyGlobalSecret;
        // Poison old
        await credentialStorage.storeSecret(legacyAlias, MIGRATION_TOMBSTONE_BYTES);
        await credentialStorage.deleteSecret(legacyAlias);
      } else {
        // No legacy secret to migrate, so from here on we would be GENERATING.
        if (options?.allowGenerate === false) {
          throw new Error('[MasterSecret] Existing wallet requires recovery; refusing to generate replacement secret.');
        }

        // An anchor means the server already knows this account's wallet, so
        // there is nothing legitimate to generate — a fresh random secret can
        // never derive to an address that already exists. enableDriveBackup
        // passes an anchor WITHOUT allowGenerate:false, so without this the
        // flow minted a replacement, persisted it over the alias and uploaded
        // it as the user's backup.
        if (options?.expectedAddress || options?.expectedEvmAddress) {
          throw new Error(
            'No encontramos el respaldo de tu billetera en este dispositivo. Inicia sesión con la cuenta de Google donde guardaste tu respaldo para recuperarla.'
          );
        }

        console.log('[MasterSecret] Generating NEW Secret...');
        localSecret = generateRandomSecret();
      }

      // Assign New UUID
      localWalletId = generateUUID();
      await credentialStorage.storeSecret(secretAlias, localSecret);
      await credentialStorage.storeSecret(walletIdKey, stringToUtf8Bytes(localWalletId));
      await storeAddressBoundMasterSecret(
        credentialStorage,
        derivePersonalV2Address(localSecret),
        localSecret
      );
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

        // Writes are v2 from here on; reads still accept v1 forever.
        const encryptedBody = encryptBackupV2(finalSecret, APP_BACKUP_KEY);
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

        const existingEntry = existingEntryIndex >= 0 ? manifest.wallets[existingEntryIndex] : null;

        const entry: WalletEntry = {
          id: finalId,
          createdAt: existingEntry?.createdAt || now,
          lastBackupAt: now,
          deviceHint: currentDeviceHint,
          providerHint: 'Google'
        };

        // 4c. Update Primary Pointer to the canonical restored/created wallet.
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
            const primaryContent = JSON.stringify({
              primary_wallet_id: finalId,
              updated_at: now,
              device_hint: currentDeviceHint
            });
            await googleDriveStorage.updateFile(accessToken, primaryFiles[0].id, primaryContent);
          }
        } catch (e) {
          console.warn('[MasterSecret] Failed to update primary pointer:', e);
        }

        // One Google Drive account must have one canonical wallet entry.
        // Historical duplicate files/revisions remain available for oldest-backup recovery,
        // but the manifest must never invite another active choice.
        manifest.wallets = [entry];

        await saveManifest(googleDriveStorage, accessToken, manifest);
        console.log(`[MasterSecret] Encrypted Backup Synced (ID: ${finalId})`);
        options?.onCloudSyncResult?.(true);

        // Drive Backup Report
        const backupReport = reportBackupStatus(
          'google_drive',
          options?.backupReportAuthToken,
        );
        if (options?.backupReportAuthToken) {
          await backupReport;
        } else {
          backupReport.catch(e => console.warn('[BackupHealth] Drive backup report failed', e));
        }

      } catch (syncErr: any) {
        AnalyticsService.logBackupFailed('google_drive', syncErr?.message || 'Unknown sync error');
        console.warn('[MasterSecret] Sync failed:', syncErr);
        options?.onCloudSyncResult?.(false);
        if (options?.requireCloudSync) {
          throw syncErr;
        }
      }
    }

    return finalSecret;

  } finally {
    resolveCurrentMutex!();
  }
}

// Helper: Decryption Logic
/**
 * Drive backup format v2: authenticated and versioned, with a
 * SELF-CONSISTENCY commitment (not an identity binding — read on).
 *
 * v1 was `AES.encrypt(base64(secret), passphrase)` — EVP_BytesToKey/MD5, CBC,
 * NO authentication — decoded through a LENIENT base64 decoder and checked only
 * for length. Two consequences, both of which showed up as real findings:
 *   - a damaged or tampered blob decrypts to garbage instead of failing;
 *   - an encrypted payload of `'!'.repeat(43) + '='` decodes to 32 ZERO bytes
 *     and passes a length check.
 *
 * v2 uses XSalsa20-Poly1305 (the same primitive wrapSeed already uses), so
 * tampering and corruption fail loudly instead of decoding into plausible
 * garbage. The payload also carries the addresses the secret derives to.
 *
 * WHAT THE COMMITMENT IS NOT: it is not a defense against substitution. The
 * key is `sha256` of a constant compiled into every build, so anyone holding
 * that constant can seal a valid envelope committing to any secret they choose.
 * The commitment catches accidental corruption and our own writer bugs; it
 * proves nothing about an adversary. The only real defense against adopting the
 * wrong wallet is the EXTERNAL address anchor, which is why corrupt-local
 * repair refuses to proceed without one. Do not let this field's existence
 * justify relaxing that requirement.
 *
 * The trust model is unchanged: the real access control remains the
 * appDataFolder OAuth-client ACL, not the cipher.
 */
interface BackupEnvelopeV2 {
  v: 2;
  alg: 'xsalsa20poly1305';
  nonce: string;
  ct: string;
}

function backupKeyBytes(passphrase: string): Uint8Array {
  return sha256(utf8ToBytes(passphrase));
}

function encryptBackupV2(secret: Uint8Array, passphrase: string): string {
  const nonce = secureRandomBytes(24, 'a Drive backup nonce');
  const inner = JSON.stringify({
    v: 2,
    secret: bytesToBase64(secret),
    // Identity commitment: whoever opens this can confirm the secret is the one
    // that belongs to these addresses, without asking our server.
    algo: derivePersonalV2Address(secret),
    evm: derivePersonalEvmAddress(secret),
  });
  const ct = nacl.secretbox(utf8ToBytes(inner), nonce, backupKeyBytes(passphrase));
  const envelope: BackupEnvelopeV2 = {
    v: 2,
    alg: 'xsalsa20poly1305',
    nonce: bytesToHex(nonce),
    ct: bytesToHex(ct),
  };
  return JSON.stringify(envelope);
}

function decryptBackupV2(body: string, passphrase: string): Uint8Array | null {
  let envelope: any;
  try {
    envelope = JSON.parse(body);
  } catch {
    return null; // not v2; caller falls back to the legacy format
  }
  if (!envelope || envelope.v !== 2 || envelope.alg !== 'xsalsa20poly1305') return null;

  const opened = nacl.secretbox.open(
    hexToBytes(envelope.ct),
    hexToBytes(envelope.nonce),
    backupKeyBytes(passphrase)
  );
  if (!opened) {
    // Authentication failure. Under v1 this same blob would have "decrypted"
    // to garbage and been length-checked; now it is rejected.
    console.warn('[MasterSecret] Drive backup failed authentication; rejecting.');
    return null;
  }

  try {
    const inner = JSON.parse(decodeUtf8(opened));
    const secret = strictBase64ToBytes(inner.secret, MASTER_SECRET_BYTES);
    // The commitment must match what the secret actually derives to; a blob
    // whose payload and claimed identity disagree is not usable.
    if (inner.algo !== derivePersonalV2Address(secret) || inner.evm !== derivePersonalEvmAddress(secret)) {
      console.warn('[MasterSecret] Drive backup identity commitment does not match its secret; rejecting.');
      return null;
    }
    return secret;
  } catch (e) {
    console.warn('[MasterSecret] Drive backup payload malformed; rejecting.', e);
    return null;
  }
}

function decryptBackup(content: string, AES: any, key: string, Utf8: any): Uint8Array | null {
  try {
    let clean = content.trim();
    if (clean.includes('ADVERTENCIA') || clean.includes('\n')) {
      clean = clean.split('\n').pop()!.trim();
    }
    // v2 first; a v1 blob is not JSON, so this returns null and we fall through.
    const v2 = decryptBackupV2(clean, key);
    if (v2) return v2;

    const bytes = AES.decrypt(clean, key);
    const b64 = bytes.toString(Utf8);
    if (!b64) return null;
    // STRICT decode on the legacy path too: base64-js maps junk to zero bytes,
    // so `'!'.repeat(43) + '='` used to sail through as 32 zero bytes here.
    // v1 blobs are unauthenticated, so this is the only integrity signal they
    // have. Existing backups must keep working — never stop reading v1.
    return driveCandidateSecret(
      strictBase64ToBytes(b64, MASTER_SECRET_BYTES),
      'Drive backup (legacy v1)'
    );
  } catch (e) {
    console.warn('Decryption failed:', e);
    return null;
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
  // Last line of defense. Every caller is supposed to have validated the
  // secret at its trust boundary, but this is the one function they all funnel
  // through, so enforce it here too: HKDF will happily stretch 4 bytes into a
  // valid-looking keypair, and the resulting address is indistinguishable from
  // a real one until funds are already in it.
  if (clientSecret?.length !== MASTER_SECRET_BYTES) {
    throw new Error(
      `[V2] Refusing to derive from a ${clientSecret?.length ?? 'missing'}-byte secret; expected ${MASTER_SECRET_BYTES}.`
    );
  }

  // Master Secret is already unique per-user (Random ONCE + Persist)
  // We use Info/Salt for domain separation between accounts (Personal vs Business)

  const { address, seed32, keyPair } = deriveV2KeyMaterial(clientSecret, opts);

  console.log('[DeriveV2] Wallet derived:', address);

  // Savings-chain sibling for V2: derived from the SAME master secret with
  // the EVM domain — without this, V2 (current-architecture) users would
  // never get a BSC address at all.
  try {
    cacheAndPersistEvmWallet(
      evmAccountKey({
        accountType: (opts.accountType === 'business' ? 'business' : 'personal'),
        accountIndex: opts.accountIndex,
        businessId: opts.businessId,
      }),
      deriveEvmKeyFromMasterSecret(clientSecret, opts),
    );
  } catch (e) {
    console.warn('[DeriveV2] EVM sibling derivation failed (non-fatal):', e);
  }

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
    // getDerivationPepper swallows every failure (no JWT, network down, server
    // error) and returns undefined. Falling back to '' here used to derive a
    // wallet from the OAuth claims and client salt ALONE — no server secret in
    // the mix, so the "wallet" was reproducible by anyone holding public
    // identity data, and it silently pointed at an address holding no funds.
    // Match the normal V1 path (deriveWallet below): refuse instead.
    if (!derivationPepper) {
      throw new Error('Missing derivation pepper: cannot restore legacy wallet without pepper. Ensure authentication and network are available.');
    }
    const salt = generateClientSalt(iss, sub, aud, accountType, accountIndex, businessId);

    // Explicitly use V1 logic
    return deriveDeterministicAlgorandKey({
      clientSalt: salt,
      derivationPepper,
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
      const { credentialStorage } = await import('./credentialStorage');

      // Namespace the key by User ID (sub) to support multi-user devices
      // Use SHA256 of subject for privacy and safe key characters
      const safeSub = bytesToHex(sha256(utf8ToBytes(sub)));
      // ROTATION: Using 'v2' suffix to obtain the CLEAN, ISOLATED key (ignoring previous corrupted state)
      const namespacedKey = `confio_master_secret_v2_${safeSub}`;

      // ONLY a confirmed null may fall through to V1. A read that FAILS —
      // locked Keychain, biometric-invalidated key, storage error — is not
      // evidence that no V2 secret exists, and treating it as such silently
      // hands the user a V1 wallet at a different address while their real
      // V2 wallet holds the funds. This try wraps the read and nothing else,
      // so a corruption throw or a derivation failure propagates instead of
      // being absorbed into the same fallback.
      let rawSecret: Uint8Array | null;
      try {
        rawSecret = await credentialStorage.retrieveSecretStrict(namespacedKey);
      } catch (readErr: any) {
        if (readErr instanceof NonCanonicalBase64Error) {
          throw new CorruptMasterSecretError('subject-bound keychain alias (derive path)', -1);
        }
        console.error('[WalletService] Could not read the V2 master secret; refusing to fall back to V1.', readErr);
        throw new Error(
          'No pudimos leer tu billetera guardada en este dispositivo. Cierra la app, ábrela de nuevo y vuelve a intentarlo.'
        );
      }

      const masterSecret = storedMasterSecret(
        rawSecret,
        'subject-bound keychain alias (derive path)'
      );

      // NOTE: We do NOT fallback to legacy global key here.
      // Migration from Legacy -> V2 Namespaced is handled exclusively by 'getOrCreateMasterSecret'.
      // If masterSecret is genuinely absent, we fall back to V1 (Pepper/Salt) logic below.

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
      }

      console.log('[WalletService] No V2 Master Secret found. Proceeding with Legacy V1 restoration...');
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
                accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY
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
            accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY
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

  getActiveSigningAddress(): string | null {
    try {
      const currentScope = this.currentScope.get('current');
      if (!currentScope) return null;

      const seedHex = this.inMemSeeds.get(currentScope);
      if (!seedHex) return null;

      const seed = hexToBytes(seedHex);
      const keyPair = nacl.sign.keyPair.fromSeed(seed);
      const algosdk = require('algosdk');
      return algosdk.encodeAddress(keyPair.publicKey);
    } catch (_error) {
      return null;
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
        await softClearInternetCredentials('wallet.confio.app');
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
export const reportBackupStatus = async (
  provider: 'google_drive' | 'icloud',
  pinnedAuthToken?: string,
): Promise<boolean> => {
  try {
    const deviceName = await DeviceInfo.getDeviceName();
    const { data } = await apolloClient.mutate({
      mutation: REPORT_BACKUP_STATUS,
      variables: {
        provider,
        device_name: deviceName,
        isVerified: true
      },
      context: {
        skipAuth: false,
        ...(pinnedAuthToken ? {
          pinnedAuthToken,
          skipProactiveRefresh: true,
        } : {}),
      }
    });
    if (!data?.reportBackupStatus?.success) {
      console.warn(
        '[BackupHealth] Server rejected backup status:',
        data?.reportBackupStatus?.error || 'Unknown error'
      );
      return false;
    }
    console.log(`[BackupHealth] Reported safe via ${provider}`);
    AnalyticsService.logBackupSuccess(provider, deviceName);
    return true;
  } catch (e) {
    console.warn('[BackupHealth] Failed to report status:', e);
    return false;
  }
};
