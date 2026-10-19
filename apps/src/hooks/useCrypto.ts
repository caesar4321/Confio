// Bitcoin & gold reads for the screens. Each field is its own query (see
// services/cryptoTrading): against a server without it only that query
// fails, and a failure reads as "not available", never as zero.

import { useMemo } from 'react';
import { useQuery } from '@apollo/client';

import { useAuthReady } from '../contexts/AuthContext';
import {
  CryptoAsset,
  CryptoCapabilities,
  CryptoHolding,
  GET_CRYPTO_CAPABILITIES,
  GET_CRYPTO_HOLDINGS,
  GET_CRYPTO_MARKET,
} from '../services/cryptoTrading';

export const useCryptoCapabilities = (skip = false) => {
  const authReady = useAuthReady();
  const { data, loading, refetch } = useQuery(GET_CRYPTO_CAPABILITIES, {
    fetchPolicy: 'cache-and-network',
    skip: skip || !authReady,
  });
  const capabilities: CryptoCapabilities | null = data?.cryptoCapabilities ?? null;
  return { capabilities, loading: loading && !data, refetch };
};

export const useCryptoMarket = (enabled: boolean) => {
  const { data, loading, refetch } = useQuery(GET_CRYPTO_MARKET, {
    fetchPolicy: 'cache-and-network',
    pollInterval: enabled ? 60_000 : 0,
    skip: !enabled,
  });
  const assets: CryptoAsset[] = useMemo(() => data?.cryptoMarket?.assets ?? [], [data]);
  const bySymbol = (symbol: string) => assets.find((a) => a.symbol === symbol);
  return { assets, bySymbol, loading: loading && !data, refetch };
};

/** `holdings` is null while unknown (not loaded, scan failed): never zero. */
export const useCryptoHoldings = (skip = false, pollMs = 60_000) => {
  const authReady = useAuthReady();
  const { data, loading, refetch } = useQuery(GET_CRYPTO_HOLDINGS, {
    fetchPolicy: 'cache-and-network',
    pollInterval: skip ? 0 : pollMs,
    skip: skip || !authReady,
  });
  const holdings: CryptoHolding[] | null = data ? data.cryptoHoldings ?? null : null;
  return { holdings, loading: loading && !data, refetch };
};
