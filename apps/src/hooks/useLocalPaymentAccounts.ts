import { useMemo } from 'react';
import { useQuery } from '@apollo/client';

import { GET_MY_PAYMENT_ACCOUNTS } from '../apollo/queries';

/**
 * The local-currency accounts Confío has opened FOR the user (Cobre Bre-B in
 * Colombia, Infinia virtual accounts elsewhere) — the receiving side of the
 * local rails.
 *
 * Everything here fails soft. Both providers sit behind server flags that
 * default to False (`COBRE_PAYMENT_ACCOUNTS_ENABLED`,
 * `INFINIA_PAYMENT_ACCOUNTS_ENABLED`), so on every build shipped so far this
 * query legitimately returns nothing. A receive surface finding no account is
 * the NORMAL case, not an error state, and it must never surface a failure
 * banner or block the screen it renders inside.
 */

export type LocalAccountStatus = 'pending' | 'active' | 'suspended' | 'rejected' | 'closed' | 'failed';

export interface LocalFundingInstruction {
  internalId: string;
  kind: string;
  status: LocalAccountStatus;
  /** The Bre-B key / CLABE / alias itself. Empty until the provider registers it. */
  displayValue: string;
  /** Name the SENDER sees on the transfer — the trust signal when sharing. */
  holderDisplayName: string;
}

export interface LocalPaymentAccount {
  internalId: string;
  provider: string;
  country: string;
  asset: string;
  status: LocalAccountStatus;
  ownershipStructure: string;
  availableBalance: string;
  fundingInstructions: LocalFundingInstruction[];
  capabilities: { capability: string; status: string }[];
}

export const useLocalPaymentAccounts = () => {
  const { data, loading, refetch } = useQuery(GET_MY_PAYMENT_ACCOUNTS, {
    fetchPolicy: 'cache-and-network',
    // 'all' keeps partial data usable and hands us the error instead of
    // throwing. Deliberately swallowed: a server without this schema yet is
    // indistinguishable from a user with no accounts, and both mean the same
    // thing to the UI — show the activation path.
    errorPolicy: 'all',
    onError: () => {},
  });

  const accounts: LocalPaymentAccount[] = useMemo(
    () => (data?.myPaymentAccounts || []) as LocalPaymentAccount[],
    [data?.myPaymentAccounts],
  );

  // "Usable right now" is stricter than `status === 'active'`: an account can
  // be open while its Bre-B key is still PROCESSING at the provider, and a
  // key with no `displayValue` is nothing the user can share or be paid at.
  const receivable = useMemo(
    () =>
      accounts.filter(
        account =>
          account.status === 'active' &&
          account.fundingInstructions.some(
            instruction => instruction.status === 'active' && !!instruction.displayValue,
          ),
      ),
    [accounts],
  );

  return {
    accounts,
    receivable,
    hasAnyAccount: accounts.length > 0,
    // Only a FIRST load with nothing cached is worth blocking a row for;
    // background refetches must not flicker the entry points.
    loading: loading && accounts.length === 0,
    refetch,
  };
};
