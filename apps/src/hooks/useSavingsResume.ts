// Finish pending cUSD+ mints whenever the app comes to the foreground.
//
// Same "retry on every re-foreground" contract as the USDC→cUSD auto-swap:
// if the app closed after a conversion's USDT arrived on BSC but before the
// mint, the next foreground completes leg C. Mounted by the savings surfaces
// (AhorrosScreen) — scoped to when the user is in the savings context, not a
// global listener.

import { useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { gql, useQuery } from '@apollo/client';
import { resumeSavingsMints } from '../services/savingsLegC';

const VAULT_ADDRESS = gql`
  query CusdPlusVaultAddress {
    cusdPlusConvertParams {
      vaultAddress
    }
  }
`;

export const useSavingsResume = (): void => {
  const { data } = useQuery(VAULT_ADDRESS, { fetchPolicy: 'cache-first' });
  const vaultAddress: string | undefined = data?.cusdPlusConvertParams?.vaultAddress;
  const appState = useRef(AppState.currentState);

  useEffect(() => {
    if (!vaultAddress) return;
    // Run once on mount (covers the case where the app was already active).
    resumeSavingsMints(vaultAddress);

    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (appState.current.match(/inactive|background/) && next === 'active') {
        resumeSavingsMints(vaultAddress);
      }
      appState.current = next;
    });
    return () => sub.remove();
  }, [vaultAddress]);
};
