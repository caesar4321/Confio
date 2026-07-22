// Sweep mis-deposited BNB into USDT whenever the app comes to the foreground.
//
// Same "retry on every re-foreground" contract as useSavingsResume: the
// service itself is idempotent (balance below threshold → no-op), so firing
// on mount + foreground is safe. Mounted on HomeScreen next to the Algorand
// useAutoSwap — mis-deposits should sweep wherever the user lands, not only
// on the savings surfaces. Silent by design (dollar-app grammar): the swap's
// USDT output surfaces through the normal deposit pipeline, not a modal.
//
// The master gate lives server-side (bnbAutoConvertEnabled): no build can
// start sweeping before the rollout flips it, and support can kill it
// remotely without a release.

import { useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { gql, useQuery } from '@apollo/client';
import { maybeAutoConvertBnb } from '../services/bnbAutoConvert';

const BNB_AUTOCONVERT_PARAMS = gql`
  query BnbAutoConvertParams {
    cusdPlusConvertParams {
      bnbAutoConvertEnabled
      pancakeRouter
      bnbAutoConvertMinSwapWei
      bnbAutoConvertKeepWei
      bnbAutoConvertSlippageBps
      vaultAddress
    }
  }
`;

export const useBnbAutoConvert = (isAuthenticated: boolean): void => {
  const { data } = useQuery(BNB_AUTOCONVERT_PARAMS, {
    fetchPolicy: 'cache-first',
    skip: !isAuthenticated,
  });
  const params = data?.cusdPlusConvertParams;
  const appState = useRef(AppState.currentState);
  const inFlight = useRef(false);

  useEffect(() => {
    if (!isAuthenticated || !params?.bnbAutoConvertEnabled || !params?.pancakeRouter) return;

    const run = async () => {
      if (inFlight.current) return; // one sweep at a time
      inFlight.current = true;
      try {
        const txHash = await maybeAutoConvertBnb({
          router: params.pancakeRouter,
          minSwapWei: BigInt(params.bnbAutoConvertMinSwapWei || '0'),
          keepWei: BigInt(params.bnbAutoConvertKeepWei || '0'),
          slippageBps: BigInt(params.bnbAutoConvertSlippageBps ?? 100),
          vaultAddress: params.vaultAddress || undefined,
        });
        if (txHash) {
          console.log('[BnbAutoConvert] swept mis-deposited BNB → USDT:', txHash);
        }
      } catch (e) {
        // Fire-and-forget: the next foreground retries. Chain errors here
        // must never disturb the screen that mounted us.
        console.warn('[BnbAutoConvert] sweep attempt failed:', e);
      } finally {
        inFlight.current = false;
      }
    };

    // Run once on mount (covers the case where the app was already active).
    run();

    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (appState.current.match(/inactive|background/) && next === 'active') {
        run();
      }
      appState.current = next;
    });
    return () => sub.remove();
  }, [isAuthenticated, params?.bnbAutoConvertEnabled, params?.pancakeRouter,
      params?.bnbAutoConvertMinSwapWei, params?.bnbAutoConvertKeepWei,
      params?.bnbAutoConvertSlippageBps, params?.vaultAddress]);
};
