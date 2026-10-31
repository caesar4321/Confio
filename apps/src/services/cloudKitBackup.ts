import { Alert, NativeModules, Platform } from 'react-native';
import * as Keychain from 'react-native-keychain';
import { jwtDecode } from 'jwt-decode';
import { sha256 } from '@noble/hashes/sha256';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils';

/**
 * The wallet's CloudKit copy on iOS. Unlike the synchronizable Keychain item,
 * this one can be proven: every upload is read back from Apple's servers
 * before anyone is told it exists. See docs/designs/icloud-cloudkit-wallet-backup.md.
 */
const CLOUD_TIMEOUT_MS = 15_000;
// CKError.quotaExceeded: the record counts against the person's own iCloud plan.
const ICLOUD_FULL_CODE = 'CK_25';

type CloudKitState = 'proven' | 'no_icloud_account' | 'icloud_restricted' | 'icloud_full' | 'failed';

const nativeBackup = () => (Platform.OS === 'ios' ? NativeModules.ConfioCloudBackup : undefined);

function withTimeout<T>(call: Promise<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('CLOUDKIT-TIMEOUT')), CLOUD_TIMEOUT_MS);
    call.then(resolve, reject).finally(() => clearTimeout(timer));
  });
}

export const cloudKitAddressHash = (address: string) =>
  bytesToHex(sha256(utf8ToBytes(address.toLowerCase())));
const recordName = (address: string) => `wallet-${cloudKitAddressHash(address)}`;

/**
 * Backup bodies stored under these addresses. `unknown` means iCloud could not
 * answer, which is never the same as an empty result: a caller must not treat
 * it as proof that no backup exists.
 */
export async function findCloudKitBackups(
  addresses: Array<string | null | undefined>,
): Promise<{ payloads: string[]; unknown: boolean }> {
  const backup = nativeBackup();
  if (!backup) return { payloads: [], unknown: false };
  let status: string;
  try {
    status = await withTimeout<string>(backup.accountStatus());
  } catch {
    return { payloads: [], unknown: true };
  }
  if (status === 'noAccount' || status === 'restricted') return { payloads: [], unknown: false };
  if (status !== 'available') return { payloads: [], unknown: true };
  const payloads: string[] = [];
  let unknown = false;
  for (const address of addresses) {
    if (!address) continue;
    try {
      const payload = await withTimeout<string | null>(backup.fetch(recordName(address)));
      if (payload) payloads.push(payload);
    } catch {
      unknown = true;
    }
  }
  return { payloads, unknown };
}

async function reportState(
  state: CloudKitState, token: string, walletHashes?: string[], errorCode?: string,
): Promise<boolean> {
  const { REPORT_CLOUDKIT_BACKUP } = await import('../apollo/queries');
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.mutate({
    mutation: REPORT_CLOUDKIT_BACKUP,
    variables: { state, walletHashes, errorCode },
    context: { pinnedAuthToken: token, skipProactiveRefresh: true },
  });
  return !!data?.reportCloudkitBackup?.success;
}

async function uploadAndVerify(
  backup: any,
  material: { bscAddress: string; algorandAddress: string; payload: string; holdsThisSecret: (body: string) => boolean },
) {
  for (const address of [material.bscAddress, material.algorandAddress]) {
    const name = recordName(address);
    await withTimeout(backup.insert(name, material.payload));
    // From the server, not from the write result. An existing record is only
    // accepted when it really holds this secret, and is never replaced.
    const stored = await withTimeout<string | null>(backup.fetch(name));
    if (!stored || !material.holdsThisSecret(stored)) throw new Error('CLOUDKIT-READBACK');
  }
}

let storageFull = false;

/** Resolves true while the person's iCloud is known to be full and nothing is stored. */
async function runCloudKitBackup(): Promise<boolean> {
  const backup = nativeBackup();
  if (!backup) return false;
  const { oauthStorage } = await import('./oauthStorageService');
  const { AuthService } = await import('./authService');
  const { getCloudKitBackupMaterial } = await import('./secureDeterministicWallet');
  const oauth = await oauthStorage.getOAuthSubject();
  const token = await AuthService.getInstance().getToken();
  if (!oauth?.subject || !token) return storageFull;
  const userId = jwtDecode<{ user_id?: string | number }>(token)?.user_id;
  if (!userId) return storageFull;
  const material = await getCloudKitBackupMaterial(oauth.subject);
  if (!material) return storageFull;

  const walletHashes = [material.bscAddress, material.algorandAddress].map(cloudKitAddressHash);
  // Keyed by user too: after deleting an account and signing up again, the same
  // wallet belongs to a new account the server has no proof for.
  const service = `confio_cloudkit_backup_v1_${userId}_${walletHashes[0]}`;
  const stored = await Keychain.getGenericPassword({ service });
  const marker = stored ? JSON.parse(stored.password) : null;

  const status = await withTimeout<string>(backup.accountStatus());
  if (status === 'noAccount' || status === 'restricted') {
    // The server is about to hear this; proof must be sent again when iCloud returns.
    if (marker?.acknowledged) {
      await Keychain.setGenericPassword('cloudkit', JSON.stringify({ ...marker, acknowledged: false }), { service });
    }
    await reportState(status === 'noAccount' ? 'no_icloud_account' : 'icloud_restricted', token);
    return false;
  }
  if (status !== 'available') return storageFull;

  const iCloudUser = await withTimeout<string>(backup.userHash());
  if (marker?.iCloudUser === iCloudUser && marker.acknowledged) return false;

  if (marker?.iCloudUser !== iCloudUser) {
    try {
      await uploadAndVerify(backup, material);
    } catch (error: any) {
      console.warn('[CloudKitBackup] Backup not proven:', error);
      const code = String(error?.code || error?.message || '');
      const full = code === ICLOUD_FULL_CODE;
      // The person must hear about a full iCloud even if this report is lost.
      await reportState(full ? 'icloud_full' : 'failed', token, undefined, code).catch(() => false);
      // Any other failure says nothing about the space: keep what we knew.
      return full || storageFull;
    }
    await Keychain.setGenericPassword('cloudkit', JSON.stringify({ iCloudUser, acknowledged: false }), { service });
  }
  // Storing and acknowledging are separate steps: a lost report must retry
  // without hiding behind a marker that says the work is done.
  if (await reportState('proven', token, walletHashes)) {
    await Keychain.setGenericPassword('cloudkit', JSON.stringify({ iCloudUser, acknowledged: true }), { service });
  }
  return false;
}

let running: Promise<void> | null = null;
let noticeOpen = false;

function warnStorageFull() {
  if (noticeOpen) return;
  noticeOpen = true;
  Alert.alert(
    'Tu respaldo no se guardó en la nube',
    'Tu iCloud no tiene espacio, así que tu billetera no quedó respaldada. Si pierdes este teléfono o se daña, podrías perder tu dinero para siempre.\n\nLibera espacio en iCloud desde Ajustes > tu nombre > iCloud. Tu respaldo necesita muy poco.',
    [
      { text: 'Entendido', style: 'cancel', onPress: () => { noticeOpen = false; } },
      { text: 'Ya liberé espacio', onPress: () => { noticeOpen = false; void ensureCloudKitBackup(); } },
    ],
  );
}

/** Runs at every app entry and never blocks it. */
export function ensureCloudKitBackup(): Promise<void> {
  if (!running) {
    running = runCloudKitBackup()
      .then(full => {
        storageFull = full;
        if (full) warnStorageFull();
      })
      .catch(error => console.warn('[CloudKitBackup] Skipped, will retry:', error))
      .finally(() => { running = null; });
  }
  return running;
}

/** A return from the background is an app open too, for someone still at risk. */
export function retryFullCloudKitBackup(): Promise<void> {
  return storageFull ? ensureCloudKitBackup() : Promise.resolve();
}
