// Futuros reads for the screens. Each document is its own query (see
// services/perps): against a server without Futuros only these fail, and a
// failure reads as "not available", never as zero.

import { useEffect, useMemo, useRef } from 'react';
import { AppState } from 'react-native';
import { useQuery } from '@apollo/client';

import { useAuthReady } from '../contexts/AuthContext';
import {
  GET_PERPS_CANDLES,
  GET_PERPS_CAPABILITIES,
  GET_PERPS_MARKETS,
  GET_PERPS_POSITIONS,
  GET_PERPS_RECENT_POSITIONS,
  PerpMarket,
  PerpPosition,
  PerpsCapabilities,
} from '../services/perps';

/** Back in the foreground: read again at once (prices moved while away;
 *  polls don't run in the background), not at the next poll tick. */
const useRefetchOnForeground = (refetch: () => Promise<unknown>, enabled: boolean) => {
  const latest = useRef(refetch);
  latest.current = refetch;
  useEffect(() => {
    if (!enabled) return undefined;
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') latest.current().catch(() => {});
    });
    return () => sub.remove();
  }, [enabled]);
};

export const usePerpsCapabilities = (skip = false) => {
  const authReady = useAuthReady();
  const { data, loading, refetch } = useQuery(GET_PERPS_CAPABILITIES, {
    fetchPolicy: 'cache-and-network',
    skip: skip || !authReady,
  });
  const capabilities: PerpsCapabilities | null = data?.perpsCapabilities ?? null;
  return { capabilities, loading: loading && !data, refetch };
};

export const usePerpsMarkets = (enabled: boolean) => {
  const { data, loading, refetch } = useQuery(GET_PERPS_MARKETS, {
    fetchPolicy: 'cache-and-network',
    pollInterval: enabled ? 15_000 : 0,
    skip: !enabled,
  });
  useRefetchOnForeground(refetch, enabled);
  const markets: PerpMarket[] = useMemo(() => data?.perpsMarkets ?? [], [data]);
  const byCoin = (coin: string) => markets.find((m) => m.coin === coin);
  return { markets, byCoin, loading: loading && !data, refetch };
};

/** `positions` is null while unknown (not loaded, Hyperliquid unreadable). */
export const usePerpsPositions = (enabled: boolean, { includeDone = false, pollMs = 10_000, doneLimit }:
  { includeDone?: boolean; pollMs?: number; doneLimit?: number } = {}) => {
  const authReady = useAuthReady();
  // doneLimit: closed positions too, only the N most recent.
  const { data: current, previousData, loading, error, refetch } = useQuery(
    doneLimit != null ? GET_PERPS_RECENT_POSITIONS : GET_PERPS_POSITIONS, {
    variables: doneLimit != null ? { doneLimit } : { includeDone },
    fetchPolicy: 'cache-and-network',
    pollInterval: enabled ? pollMs : 0,
    skip: !enabled || !authReady,
  });
  useRefetchOnForeground(refetch, enabled && authReady);
  // A longer page keeps showing the shorter one until it lands.
  const data = current ?? (loading ? previousData : undefined);
  const positions: PerpPosition[] | null = data ? data.perpsPositions ?? null : null;
  // Asked and not answered (Hyperliquid unreadable, or the query failed):
  // "we don't know", never "you have nothing".
  // An older server without Futuros rejects the field: nobody holds any there.
  // (Also inside graphQLErrors, or an HTTP 400's networkError.result.errors.)
  const unsupported = [error?.message, ...((error as any)?.graphQLErrors ?? []).map((g: any) => g?.message),
    ...((error as any)?.networkError?.result?.errors ?? []).map((g: any) => g?.message)]
    // Only the root field missing means "no Futuros here": a missing sub-field
    // (an older server than this build) is unknown, never "you have nothing".
    .some((m) => /Cannot query field "perpsPositions"/.test(String(m ?? '')));
  const unknown = enabled && authReady && !loading
    && ((Boolean(error) && !unsupported) || (Boolean(data) && data.perpsPositions == null));
  return { positions, loading: loading && !data, unknown, refetch };
};

export type PerpsRange = '1D' | '1W' | '1M' | '3M' | '1Y';
export const PERPS_RANGES: PerpsRange[] = ['1D', '1W', '1M', '3M', '1Y'];
export const PERPS_RANGE_LABELS: Record<PerpsRange, string> = {
  '1D': '1 día', '1W': '1 semana', '1M': '1 mes', '3M': '3 meses', '1Y': '1 año',
};

export const usePerpsCandles = (coin: string | undefined, range: PerpsRange) => {
  const authReady = useAuthReady();
  const { data, loading, error } = useQuery(GET_PERPS_CANDLES, {
    variables: { coin, range },
    skip: !coin || !authReady,
    fetchPolicy: 'cache-and-network',
    pollInterval: 60_000,
  });
  return useMemo(() => {
    const rows: { timestamp: number; close: number }[] = data?.perpsCandles ?? [];
    return {
      closes: rows.map((r) => r.close),
      loading: loading && !data,
      failed: Boolean(error) || data?.perpsCandles === null,
    };
  }, [data, loading, error]);
};
