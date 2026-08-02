import { useCallback, useMemo, useState } from 'react';
import { useQuery, useMutation, gql } from '@apollo/client';
import { Alert } from 'react-native';
import algorandService from '../services/algorandService';
import { Buffer } from 'buffer';
import { useAccount } from '../contexts/AccountContext';

const GET_PAYROLL_DELEGATES = gql`
  query GetPayrollDelegates {
    payrollDelegates
  }
`;

// Deliberately its OWN document, never merged into the queries above: one
// field an older server doesn't know fails the WHOLE query it sits in, and
// these screens still have to render a vault and a delegate list against a
// server that predates the rail. Unknown here → `status` is null and every
// consumer falls back to the address list.
const GET_PAYROLL_RAIL_STATUS = gql`
  query GetPayrollRailStatus {
    payrollRailStatus {
      rail
      executionRail
      tokenType
      vaultBalanceUsd
      fundableBalanceUsd
      activated
      delegateEmployeeIds
    }
  }
`;

export type PayrollRail = 'bsc' | 'algorand';

/** null/undefined stay null — only a real number becomes a number. */
const num = (v: any): number | null =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v);

export interface PayrollRailStatus {
  /** Where the money currently IS — drives the vault hero and its label. */
  rail: PayrollRail;
  /** Where NEW work executes — drives which balance a top-up spends and
   * which instrument gets funded. Differs from `rail` only while the kill
   * switch is on with money still parked on BSC, and in exactly that window
   * showing one and acting on the other moves funds the user never saw. */
  executionRail: PayrollRail;
  tokenType: string;
  /** null = the chain did not answer and nothing was cached. NOT zero —
   * rendering "$0.00" for "we don't know" tells a business its payroll float
   * is gone. Screens show "—" instead. */
  vaultBalanceUsd: number | null;
  fundableBalanceUsd: number | null;
  /** null = indeterminate (partial delegate read); don't offer activation. */
  activated: boolean | null;
  delegateEmployeeIds: string[];
}

/** cUSD+ is an instrument, not a currency unit — an accumulating share that
 * drifts above $1 — so payroll amounts are always dollars and the rail is
 * signalled payment-method style (logo + name) beside them.
 *
 * `known: false` when the rail hasn't resolved (first paint, a transient
 * status error, an older server). Callers must HIDE the instrument row then
 * rather than print a guess: defaulting the unknown case to cUSD+ labelled
 * legacy balances with the wrong instrument, which is worse than saying
 * nothing while the dollar amount stays correct either way. */
export const payrollInstrument = (rail?: PayrollRail | null) => {
  if (rail === 'algorand') {
    return { name: 'Confío Dollar', short: 'cUSD', isPlus: false, known: true };
  }
  if (rail === 'bsc') {
    return { name: 'Confío Dollar+', short: 'cUSD+', isPlus: true, known: true };
  }
  return { name: '', short: '', isPlus: true, known: false };
};

const SET_BUSINESS_DELEGATES = gql`
  mutation SetBusinessDelegates($businessAccount: String!, $add: [String!]!, $remove: [String!]!, $signedTransaction: String) {
    setBusinessDelegates(businessAccount: $businessAccount, add: $add, remove: $remove, signedTransaction: $signedTransaction) {
      success
      errors
      unsignedTransactionB64
      transactionHash
    }
  }
`;

export const usePayrollDelegates = () => {
  const { activeAccount } = useAccount();
  const skip = !activeAccount || activeAccount.type !== 'business';
  const { data, loading, refetch } = useQuery(GET_PAYROLL_DELEGATES, {
    skip,
    fetchPolicy: 'network-only', // Always fetch fresh data from server
  });
  const {
    data: statusData,
    loading: statusLoading,
    refetch: refetchStatus,
  } = useQuery(GET_PAYROLL_RAIL_STATUS, {
    // Not `skip` — a delegate approving payroll from their PERSONAL account
    // has no business context but still needs to know which rail (and which
    // escrow) they are looking at. The resolver finds their business.
    skip: !activeAccount,
    fetchPolicy: 'network-only',
    // An old server answers "Cannot query field payrollRailStatus"; that has
    // to leave the screens on the legacy path, not blank them.
    errorPolicy: 'all',
  });
  const [mutateDelegates, { loading: mutating }] = useMutation(SET_BUSINESS_DELEGATES);
  const [activatedOverride, setActivatedOverride] = useState(false);

  // Keep as raw address strings so screens can compare directly
  const delegates = useMemo(() => data?.payrollDelegates || [], [data]);
  const status: PayrollRailStatus | null = useMemo(() => {
    const s = statusData?.payrollRailStatus;
    if (!s?.rail) return null;
    return {
      rail: s.rail === 'bsc' ? 'bsc' : 'algorand',
      executionRail: (s.executionRail ?? s.rail) === 'bsc' ? 'bsc' : 'algorand',
      tokenType: s.tokenType || 'CUSD',
      vaultBalanceUsd: num(s.vaultBalanceUsd),
      fundableBalanceUsd: num(s.fundableBalanceUsd),
      activated: s.activated === null || s.activated === undefined ? null : !!s.activated,
      delegateEmployeeIds: (s.delegateEmployeeIds || []).map(String),
    };
  }, [statusData]);
  const isActivated = useMemo(() => {
    if (activatedOverride) return true;
    // An indeterminate answer must not route a live business back into the
    // setup wizard, so treat null as "activated" and let the real gate — the
    // contract refusing a non-delegate's signature — do the work.
    if (status) return status.activated !== false;
    return delegates.length > 0;
  }, [status, delegates, activatedOverride]);

  const refetchAll = useCallback(async () => {
    // The status query must never take the whole refresh down with it.
    await Promise.all([
      refetch?.(),
      refetchStatus?.().catch(() => undefined),
    ]);
  }, [refetch, refetchStatus]);

  /** Allowlist signers on ConfioPayrollVault — the BSC meaning of
   * "activate payroll". Returns null when the rail is dark so callers fall
   * through to the Algorand box flow. */
  const activateOnBsc = useCallback(
    async (delegateUserIds: string[]) => {
      const { runBscPayrollAdmin, bscPayrollErrorMessage } = await import('../services/bscPayroll');
      try {
        // ONE sponsored batch for every signer. includeSelf covers the person
        // activating: payout digests are signed with a PERSONAL key, so an
        // owner who allowlisted only their employees could not pay their own
        // payroll — the contract accepts the business EOA or a delegate, and
        // the owner signs as neither.
        const { txHash } = await runBscPayrollAdmin({
          action: 'set_delegate',
          delegateUserIds,
          includeSelf: true,
          allowed: true,
        });
        await refetchAll();
        setActivatedOverride(true);
        return { success: true, txId: txHash };
      } catch (e: any) {
        const code = e?.message || '';
        const railDark = code === 'bsc_payroll_disabled'
          || code === 'payroll_vault_not_configured'
          || code === 'vault_not_configured';
        // NOT sponsored_rail_unavailable — see PayrollTopUpScreen.
        if (railDark) return null;
        return { success: false, error: bscPayrollErrorMessage(code) };
      }
    },
    [refetchAll],
  );

  const activatePayroll = useCallback(
    async (ownerAddress?: string, delegateAddresses?: string[], delegateUserIds?: string[]) => {
      if (!activeAccount || activeAccount.type !== 'business') {
        Alert.alert('Solo negocios', 'Cambia a una cuenta de negocio para activar nómina.', [{ text: 'OK' }]);
        return { success: false, error: 'Solo negocios' };
      }
      const bsc = await activateOnBsc(delegateUserIds || []);
      if (bsc) return bsc;
      const businessAddr = activeAccount.algorandAddress || (activeAccount as any).address;
      const delegateAddr = activeAccount?.ownerAddress || activeAccount?.algorandAddress || businessAddr;
      if (!businessAddr) {
        Alert.alert('Dirección faltante', 'No se encontró la dirección de la cuenta de negocio.', [{ text: 'OK' }]);
        return { success: false, error: 'Dirección faltante' };
      }
      // Always include business + delegate (personal) so allowlist gets created for payouts
      const adds = [businessAddr, delegateAddr]
        .concat(ownerAddress ? [ownerAddress] : [])
        .concat(delegateAddresses || []);
      try {
        // Step 1: ask server for unsigned txn
        const prepRes = await mutateDelegates({
          variables: { businessAccount: businessAddr, add: adds, remove: [], signedTransaction: null },
        });
        const prepData = prepRes.data?.setBusinessDelegates;
        const unsignedB64 = prepData?.unsignedTransactionB64;
        if (!prepData?.success || !unsignedB64) {
          const msg =
            prepData?.errors?.filter(Boolean).join('\n') ||
            prepRes.errors?.map((e: any) => e.message).join('\n') ||
            'No se pudo preparar la activación.';
          return { success: false, error: msg };
        }
        // Step 2: sign client-side
        const unsignedBytes = Uint8Array.from(Buffer.from(unsignedB64, 'base64'));
        const signedBytes = await algorandService.signTransactionBytes(unsignedBytes);
        const signedB64 = Buffer.from(signedBytes).toString('base64');
        // Step 3: submit
        const submitRes = await mutateDelegates({
          variables: { businessAccount: businessAddr, add: adds, remove: [], signedTransaction: signedB64 },
        });
        const submitData = submitRes.data?.setBusinessDelegates;
        const ok = submitData?.success;
        const txId = submitData?.transactionHash;
        if (!ok) {
          const msg =
            submitData?.errors?.filter(Boolean).join('\n') ||
            submitRes.errors?.map((e: any) => e.message).join('\n') ||
            'No se pudo activar nómina.';
          return { success: false, error: msg };
        }
        await refetch();
        setActivatedOverride(true);
        return { success: true, txId };
      } catch (e: any) {
        console.error('activatePayroll error', e);
        return { success: false, error: e?.message || 'No se pudo activar nómina.' };
      }
    },
    [activeAccount, mutateDelegates, refetch, activateOnBsc],
  );

  return {
    delegates,
    status,
    rail: status?.rail ?? null,
    executionRail: status?.executionRail ?? null,
    instrument: payrollInstrument(status?.rail),
    loading: loading || statusLoading || mutating,
    isActivated,
    activatePayroll,
    activateOnBsc,
    refetch: refetchAll,
  };
};
