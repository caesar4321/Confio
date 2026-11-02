// Bitcoin & gold reads for the screens. Each field is its own query (see
// services/cryptoTrading): against a server without it only that query
// fails, and a failure reads as "not available", never as zero.

import { useMemo } from 'react';
import { gql, useQuery } from '@apollo/client';

import { DEX_TRADING_UI_ENABLED } from '../config/features';
import { useAuthReady } from '../contexts/AuthContext';
import {
  CryptoAsset,
  CryptoCapabilities,
  CryptoHolding,
  GET_CRYPTO_CAPABILITIES,
  GET_CRYPTO_HOLDINGS,
  GET_CRYPTO_MARKET,
} from '../services/cryptoTrading';
import { GmRange, gmApiRangeFor, gmOhlcState } from './useGmMarket';

/** Apollo's refetch() runs even for a skipped query: a binary without the DEX
 *  surfaces hands out this instead, so it never sends these queries at all. */
const noRefetch = (): Promise<any> => Promise.resolve(undefined);

export const useCryptoCapabilities = (skip = false) => {
  const authReady = useAuthReady();
  const { data, loading, refetch } = useQuery(GET_CRYPTO_CAPABILITIES, {
    fetchPolicy: 'cache-and-network',
    // No DEX UI in this binary: never even ask (every consumer reads null).
    skip: skip || !authReady || !DEX_TRADING_UI_ENABLED,
  });
  const capabilities: CryptoCapabilities | null = data?.cryptoCapabilities ?? null;
  return { capabilities, loading: loading && !data, refetch: DEX_TRADING_UI_ENABLED ? refetch : noRefetch };
};

export const useCryptoMarket = (enabled: boolean) => {
  const { data, loading, refetch } = useQuery(GET_CRYPTO_MARKET, {
    fetchPolicy: 'cache-and-network',
    pollInterval: enabled && DEX_TRADING_UI_ENABLED ? 60_000 : 0,
    skip: !enabled || !DEX_TRADING_UI_ENABLED,
  });
  const assets: CryptoAsset[] = useMemo(() => data?.cryptoMarket?.assets ?? [], [data]);
  const bySymbol = (symbol: string) => assets.find((a) => a.symbol === symbol);
  return { assets, bySymbol, loading: loading && !data, refetch: DEX_TRADING_UI_ENABLED ? refetch : noRefetch };
};

/** `holdings` is null while unknown (not loaded, scan failed): never zero. */
export const useCryptoHoldings = (skip = false, pollMs = 60_000) => {
  const authReady = useAuthReady();
  // Read in every binary: what a member holds is their money, and Home's
  // total stays whole (an iOS binary names it "otros").
  const { data, loading, refetch } = useQuery(GET_CRYPTO_HOLDINGS, {
    fetchPolicy: 'cache-and-network',
    pollInterval: skip ? 0 : pollMs,
    skip: skip || !authReady,
  });
  const holdings: CryptoHolding[] | null = data ? data.cryptoHoldings ?? null : null;
  return { holdings, loading: loading && !data, refetch };
};

// Range chart for the detail screen: same ranges and slicing as stocks
// (1H/6H/12H cut from 1D's 15-minute candles). Display only; trades are
// priced by PancakeSwap. Its own query: an older server fails only this.
const GET_CRYPTO_OHLC = gql`
  query CryptoOhlc($symbol: String!, $range: String) {
    cryptoOhlc(symbol: $symbol, range: $range) {
      timestamp
      close
    }
  }
`;

export const useCryptoOhlc = (symbol: string | undefined, range: GmRange, enabled = true) => {
  const authReady = useAuthReady();
  const { data, loading, error } = useQuery(GET_CRYPTO_OHLC, {
    variables: { symbol, range: gmApiRangeFor(range) },
    skip: !enabled || !symbol || !authReady || !DEX_TRADING_UI_ENABLED,
    fetchPolicy: 'cache-and-network',
    pollInterval: 300_000,
  });
  return useMemo(
    () => gmOhlcState(data?.cryptoOhlc ?? [], range, enabled, loading, !!error || data?.cryptoOhlc === null),
    [data, loading, error, enabled, range],
  );
};
