// Return the person's own dollars stranded on their address on another
// network (a refunded top-up or receive) to their balance, whenever the app
// comes to the foreground.
//
// Same contract as useBnbAutoConvert: silent, idempotent, retried on every
// re-foreground. The server answers 'none' for employees, viewers and when
// the switch is off; the arriving USDT surfaces through the normal deposit
// pipeline (and from there into Dollar+), never as a modal. The person signs
// one USDC authorization that only Relay's receiver can use; the app checks
// sender, receiver and amount before signing (services/polygonReturn.ts).

import { useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { fetchPolygonReturn, preparePolygonReturn, signAndSubmitPolygonReturn } from '../services/polygonReturn';

// A refused or failed attempt (amount too small for the route, Relay down)
// waits this long before the next try, so foregrounding is not a quote loop.
const RETRY_AFTER_MS = 10 * 60 * 1000;

export const usePolygonReturn = (isAuthenticated: boolean, accountId: string | undefined): void => {
  const appState = useRef(AppState.currentState);
  const inFlight = useRef(false);
  const failedAt = useRef<Record<string, number>>({});

  useEffect(() => {
    if (!isAuthenticated || !accountId) return;

    const run = async () => {
      if (inFlight.current) return;
      if (Date.now() - (failedAt.current[accountId] || 0) < RETRY_AFTER_MS) return;
      inFlight.current = true;
      try {
        const status = await fetchPolygonReturn();
        if (status?.state !== 'available') return;
        const { permit, error } = await preparePolygonReturn();
        if (!permit) {
          failedAt.current[accountId] = Date.now();
          console.warn('[PolygonReturn] prepare refused:', error);
          return;
        }
        const result = await signAndSubmitPolygonReturn(permit);
        if (!result.ok) {
          failedAt.current[accountId] = Date.now();
          console.warn('[PolygonReturn] submit failed:', result.error);
          return;
        }
        console.log('[PolygonReturn] returning', permit.amount, 'to the balance');
      } catch (e) {
        failedAt.current[accountId] = Date.now();
        console.warn('[PolygonReturn] attempt failed:', e);
      } finally {
        inFlight.current = false;
      }
    };

    run();
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (appState.current.match(/inactive|background/) && next === 'active') run();
      appState.current = next;
    });
    return () => sub.remove();
  }, [isAuthenticated, accountId]);
};
