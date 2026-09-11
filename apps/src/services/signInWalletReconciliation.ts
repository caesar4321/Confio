import { gql } from '@apollo/client';
import { WalletRecoveryError } from './walletRecoveryErrors';

const PREPARE = gql`
  mutation PrepareWalletReconciliation($firebaseIdToken: String!, $bscAddress: String) {
    prepareWalletReconciliation(firebaseIdToken: $firebaseIdToken, bscAddress: $bscAddress) {
      success error grant challenge
      accounts { accountId accountType accountIndex businessId algorandAddress bscAddress isKeylessMigrated }
    }
  }
`;
const COMPLETE = gql`
  mutation CompleteWalletReconciliation($grant: String!, $signature: String!, $wallets: [WalletReconciliationProofInput!]!) {
    completeWalletReconciliation(grant: $grant, signature: $signature, wallets: $wallets) {
      success error bscAddress
      accounts { accountId accountType accountIndex businessId algorandAddress bscAddress isKeylessMigrated }
    }
  }
`;

type Registration = {
  accountId: string; accountType: 'personal' | 'business'; accountIndex: number;
  businessId?: string | null; algorandAddress?: string | null; bscAddress?: string | null;
  isKeylessMigrated?: boolean;
};

function registrations(value: unknown): Registration[] {
  if (!Array.isArray(value) || !value.length) throw new Error('RECONCILE-ACCOUNTS');
  const ids = new Set<string>();
  const contexts = new Set<string>();
  for (const row of value) {
    if (!row || typeof row.accountId !== 'string' || !/^\d+$/.test(row.accountId)
        || !['personal', 'business'].includes(row.accountType)
        || !Number.isSafeInteger(row.accountIndex) || row.accountIndex < 0
        || (row.accountType === 'business' && (typeof row.businessId !== 'string' || !/^\d+$/.test(row.businessId)))
        || (row.accountType === 'personal' && row.businessId != null)
        || (row.algorandAddress != null && typeof row.algorandAddress !== 'string')
        || (row.bscAddress != null && typeof row.bscAddress !== 'string')
        || ids.has(row.accountId)) throw new Error('RECONCILE-ACCOUNTS');
    const key = `${row.accountType}:${row.accountIndex}:${row.businessId || ''}`;
    if (contexts.has(key)) throw new Error('RECONCILE-ACCOUNTS');
    contexts.add(key);
    ids.add(row.accountId);
  }
  if (!value.some(row => row.accountType === 'personal' && row.accountIndex === 0)) {
    throw new Error('RECONCILE-ACCOUNTS');
  }
  return value;
}

export function walletAccountChallenge(challenge: string, accountId: string, address: string) {
  return `${challenge}\nAccount: ${accountId}\nAddress: ${address.toLowerCase()}`;
}

export function candidateMatchesRegistration(
  candidate: { algorandAddress: string; bscAddress: string },
  registration: { algorandAddress?: string | null; bscAddress?: string | null },
) {
  return (!registration.algorandAddress || candidate.algorandAddress === registration.algorandAddress)
    && (!registration.bscAddress || candidate.bscAddress.toLowerCase() === registration.bscAddress.toLowerCase());
}

/** Runs inside social sign-in, with its request-scoped JWT. No setup UI and no
 * balance inspection. Failure never turns a missing backup into a new secret.
 */
export async function reconcileSignInWallet(options: {
  provider: 'google' | 'apple'; subject: string; firebaseToken: string;
  authData: any; client: any; getGoogleDriveToken: () => Promise<string | null>;
  beforeWalletChange: () => Promise<void>;
  /** Read-only anchored V1 probe supplied by Google sign-in; never writes keys. */
  getLegacyV1Address?: (account: Registration) => Promise<string | null>;
}): Promise<boolean> {
  const { authData, provider, subject, client } = options;
  if (authData.isNewUser) return false;
  const { getSignInWalletCandidate, reportBackupStatus, clearReconciledLegacyWallets } = await import('./secureDeterministicWallet');
  let candidate: Awaited<ReturnType<typeof getSignInWalletCandidate>> | undefined;
  let restoredLegacyBackup = false;
  const acknowledgeBackup = async () => {
    const acknowledged = await reportBackupStatus(
      provider === 'google' ? 'google_drive' : 'icloud', authData.accessToken,
    );
    if (!acknowledged) throw new Error('No pudimos confirmar el respaldo. Vuelve a iniciar sesión. Código: RECONCILE-BACKUP-REPORT.');
    await candidate?.clearPendingBackupReport();
    authData.requiresBackupCompletion = false;
  };
  try {
    candidate = await getSignInWalletCandidate(subject);
  } catch (error: any) {
    // A corrupt Keychain copy may be repaired by the canonical Google backup.
    // Permission/locked-storage errors must not be treated as missing keys.
    if (provider !== 'google' || error?.name !== 'CorruptMasterSecretError') throw error;
  }
  const context = { pinnedAuthToken: authData.accessToken, skipProactiveRefresh: true };
  const prepare = async (bscAddress?: string) => {
    const response = await client.mutate({
      mutation: PREPARE, context,
      variables: { firebaseIdToken: options.firebaseToken, bscAddress },
    });
    const proof = response.data?.prepareWalletReconciliation;
    if (!proof?.success) {
      throw new Error('No pudimos autorizar tu billetera. Vuelve a iniciar sesión. Código: RECONCILE-AUTH.');
    }
    return { ...proof, accounts: registrations(proof.accounts) };
  };
  // Server-owned inventory includes sibling-only mismatches and excludes
  // employee access. Never infer ownership from the active UI context.
  let proof = await prepare(candidate?.bscAddress);
  let accounts: Registration[] = proof.accounts;
  // Legacy primary-only reenrollment cannot replace a user-wide master when
  // siblings exist. Revoke even on empty/V1 early-return paths below.
  if (accounts.length > 1) authData.walletReenrollmentAllowed = false;
  const applyPrimaryRegistration = () => {
    const primary = accounts.find(row => row.accountType === 'personal' && row.accountIndex === 0)!;
    authData.user.algorandAddress = primary.algorandAddress || null;
    authData.user.bscAddress = primary.bscAddress || null;
    authData.isKeylessMigrated = !!primary.isKeylessMigrated;
  };
  if (!accounts.some(row => row.algorandAddress || row.bscAddress)) return false;
  if (provider === 'google' && candidate === null && options.getLegacyV1Address
      && accounts.every(row => !row.isKeylessMigrated && !row.bscAddress)) {
    // A genuine deterministic V1 account needs no Drive authorization to
    // reproduce its keys. Check every owned anchor, not just personal/0.
    // Corrupt/known V2 material never reaches this absence-only shortcut.
    const legacyMatches = await Promise.all(accounts.filter(row => !!row.algorandAddress).map(async row => {
      try {
        return await options.getLegacyV1Address!(row) === row.algorandAddress;
      } catch {
        return false; // Canonical Drive recovery can still succeed.
      }
    }));
    if (legacyMatches.every(Boolean)) {
      applyPrimaryRegistration();
      return false;
    }
  }
  const matchesAll = () => !!candidate && accounts.every(row =>
    // A missing primary anchor must not bypass registration just because a
    // sibling happens to match the candidate.
    (!(row.accountType === 'personal' && row.accountIndex === 0) || !!(row.algorandAddress || row.bscAddress))
      && candidateMatchesRegistration(candidate!.forAccount(row), row));
  const publishAll = async () => {
    if (accounts.every(row => !row.algorandAddress && row.isKeylessMigrated)) {
      await clearReconciledLegacyWallets(accounts);
    }
    for (const row of accounts) {
      if (row.accountType !== 'personal' || row.accountIndex !== 0) await candidate!.forAccount(row).publish();
    }
    // The sign-in session is personal/0, not whichever sibling was last.
    await candidate!.publish();
  };
  // A matching Google key may never have finished its first cloud upload.
  // Keep the server's backup requirement so ordinary login can reach setup;
  // requiring a pre-existing Drive file here would lock that user out.
  if (candidate && matchesAll()
      && (provider === 'google' || !authData.requiresBackupCompletion)) {
    if (provider === 'google' && await candidate.hasPendingBackupReport()) {
      await acknowledgeBackup();
    }
    await publishAll();
    applyPrimaryRegistration();
    return false;
  }
  if (provider === 'google') {
    const token = await options.getGoogleDriveToken();
    if (!token) throw new Error('Autoriza Google Drive con la misma cuenta para recuperar tu billetera.');
    try {
      candidate = await getSignInWalletCandidate(subject, token);
    } catch (error) {
      if (error instanceof WalletRecoveryError && error.code === 'missing') {
        try {
          // Old subject-named backup formats can restore only an already
          // registered wallet. The candidate reader validates every anchor;
          // this is never permission to choose a replacement from history.
          candidate = await getSignInWalletCandidate(subject, token, { legacyRegistrations: accounts });
          restoredLegacyBackup = true;
        } catch (legacyError) {
          if (candidate === null && accounts.every(row => !row.isKeylessMigrated && !row.bscAddress)
              && legacyError instanceof WalletRecoveryError && legacyError.code === 'missing') return false;
          throw legacyError;
        }
      } else {
        // Never fall back from an unreadable or unreachable canonical backup.
        throw error;
      }
    }
  }
  // An unmigrated Apple account may still use the reproducible V1 path.
  // No automatic Google authorization and no random replacement on missing keys.
  if (!candidate) {
    if (accounts.some(row => row.isKeylessMigrated || row.bscAddress)) {
      throw new Error('No pudimos recuperar tu billetera desde el llavero de Apple. Verifica iCloud y vuelve a intentarlo. Código: RECOVERY-APPLE-KEYCHAIN.');
    }
    return false;
  }
  if (matchesAll()) {
    await candidate.persist();
    await acknowledgeBackup();
    await publishAll();
    applyPrimaryRegistration();
    return false;
  }
  if (restoredLegacyBackup) throw new WalletRecoveryError('mismatch');
  // A Drive restore can change the primary candidate after inventory discovery.
  // Refresh the bound inventory and grant before signing any replacement.
  proof = await prepare(candidate.bscAddress);
  accounts = proof.accounts;
  if (accounts.length > 1) authData.walletReenrollmentAllowed = false;
  if (!proof?.success || !proof.grant || !proof.challenge) {
    throw new Error('No pudimos autorizar tu billetera. Vuelve a iniciar sesión. Código: RECONCILE-AUTH.');
  }
  // Read back Keychain BEFORE changing the registration. A failed server call
  // can be retried with the same canonical secret; no new secret is generated.
  // Remove any older session too: a hard kill must not pair its JWT with the
  // newly persisted secret before server registration has committed.
  await options.beforeWalletChange();
  await candidate.persist();
  const wallets = accounts.map(row => {
    const wallet = candidate!.forAccount(row);
    return { accountId: row.accountId, bscAddress: wallet.bscAddress,
      signature: wallet.sign(walletAccountChallenge(proof.challenge, row.accountId, wallet.bscAddress)) };
  });
  const completed = await client.mutate({
    mutation: COMPLETE, context,
    variables: { grant: proof.grant, signature: candidate.sign(proof.challenge), wallets },
  });
  const result = completed.data?.completeWalletReconciliation;
  if (!result?.success || result.bscAddress?.toLowerCase() !== candidate.bscAddress.toLowerCase()) {
    throw new Error('No pudimos registrar tu billetera recuperada. Vuelve a iniciar sesión. Código: RECONCILE-COMMIT.');
  }
  const committed = registrations(result.accounts);
  if (committed.length !== accounts.length || accounts.some(row => {
    const active = committed.find(item => item.accountId === row.accountId);
    return !active || active.accountType !== row.accountType || active.accountIndex !== row.accountIndex
      || active.businessId !== row.businessId || active.algorandAddress || !active.isKeylessMigrated
      || active.bscAddress?.toLowerCase() !== candidate!.forAccount(row).bscAddress.toLowerCase();
  })) throw new Error('No pudimos verificar todas tus billeteras. Vuelve a iniciar sesión. Código: RECONCILE-COMMIT.');
  accounts = committed;
  authData.user.algorandAddress = null;
  authData.user.bscAddress = candidate.bscAddress;
  authData.isKeylessMigrated = true;
  authData.walletReenrollmentAllowed = false;
  await acknowledgeBackup();
  await publishAll();
  return true;
}
