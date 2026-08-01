// Finish pending cUSD+ mints whenever the app comes to the foreground.
//
// Same "retry on every re-foreground" contract as the USDC→cUSD auto-swap:
// if the app closed after a conversion's USDT arrived on BSC but before the
// mint, the next foreground completes leg C. Mounted by the savings surfaces
// (SavingsScreen) — scoped to when the user is in the savings context, not a
// global listener.

import { useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { gql, useQuery } from '@apollo/client';
import { resumeSavingsMints, subscribeSavingsMinting } from '../services/savingsLegC';

const VAULT_ADDRESS = gql`
  query CusdPlusVaultAddress {
    cusdPlusConvertParams {
      vaultAddress
    }
  }
`;

/**
 * `enabled` scopes the listener to the savings context (the hook's original
 * contract, when SavingsScreen was its only mount point). Returns whether a
 * mint is in flight so the surface can show the auto-swap spinner — the mint
 * is a sponsored on-chain batch that takes seconds, and without feedback the
 * balance appears to change on its own.
 */
export const useSavingsResume = (enabled: boolean = true): { mintingSavings: boolean } => {
  const { data } = useQuery(VAULT_ADDRESS, { fetchPolicy: 'cache-first' });
  const vaultAddress: string | undefined = data?.cusdPlusConvertParams?.vaultAddress;
  const appState = useRef(AppState.currentState);
  const [mintingSavings, setMintingSavings] = useState(false);

  // Shared module state, so every mounted surface shows the spinner even when
  // a different one won the race to actually run the mint. Unsubscribing on
  // unmount is what keeps a late finish from touching a dead screen.
  useEffect(() => subscribeSavingsMinting(setMintingSavings), []);

  useEffect(() => {
    if (!vaultAddress || !enabled) return;
    // Run once on mount (covers the case where the app was already active).
    resumeSavingsMints(vaultAddress);

    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (appState.current.match(/inactive|background/) && next === 'active') {
        resumeSavingsMints(vaultAddress);
      }
      appState.current = next;
    });
    return () => sub.remove();
  }, [vaultAddress, enabled]);

  return { mintingSavings };
};
