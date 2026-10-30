import { NativeModules, Platform } from 'react-native';
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

type CloudKitState = 'proven' | 'no_icloud_account' | 'icloud_restricted' | 'failed';

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

async function reportState(state: CloudKitState, token: string, walletHashes?: string[]): Promise<boolean> {
  const { REPORT_CLOUDKIT_BACKUP } = await import('../apollo/queries');
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.mutate({
    mutation: REPORT_CLOUDKIT_BACKUP,
    variables: { state, walletHashes },
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

async function runCloudKitBackup(): Promise<void> {
  const backup = nativeBackup();
  if (!backup) return;
  const { oauthStorage } = await import('./oauthStorageService');
  const { AuthService } = await import('./authService');
  const { getCloudKitBackupMaterial } = await import('./secureDeterministicWallet');
  const oauth = await oauthStorage.getOAuthSubject();
  const token = await AuthService.getInstance().getToken();
  if (!oauth?.subject || !token) return;
  const userId = jwtDecode<{ user_id?: string | number }>(token)?.user_id;
  if (!userId) return;
  const material = await getCloudKitBackupMaterial(oauth.subject);
  if (!material) return;

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
    return;
  }
  if (status !== 'available') return;

  const iCloudUser = await withTimeout<string>(backup.userHash());
  if (marker?.iCloudUser === iCloudUser && marker.acknowledged) return;

  if (marker?.iCloudUser !== iCloudUser) {
    try {
      await uploadAndVerify(backup, material);
    } catch (error) {
      console.warn('[CloudKitBackup] Backup not proven:', error);
      await reportState('failed', token);
      return;
    }
    await Keychain.setGenericPassword('cloudkit', JSON.stringify({ iCloudUser, acknowledged: false }), { service });
  }
  // Storing and acknowledging are separate steps: a lost report must retry
  // without hiding behind a marker that says the work is done.
  if (await reportState('proven', token, walletHashes)) {
    await Keychain.setGenericPassword('cloudkit', JSON.stringify({ iCloudUser, acknowledged: true }), { service });
  }
}

let running: Promise<void> | null = null;

/** Runs at every app entry and never blocks it. */
export function ensureCloudKitBackup(): Promise<void> {
  if (!running) {
    running = runCloudKitBackup()
      .catch(error => console.warn('[CloudKitBackup] Skipped, will retry:', error))
      .finally(() => { running = null; });
  }
  return running;
}
