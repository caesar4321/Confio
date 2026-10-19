import { useEffect, useState } from 'react';

import { getStockFeePolicy, subscribeStockFeePolicy } from '../services/ondoStocks';
import { StockFeePolicy } from '../services/stockFeeMath';

/** Confío's stock fee as the server currently has it (null while loading or
 * when trading is unavailable — the screens then show no fee line). */
export const useStockFeePolicy = (): StockFeePolicy | null => {
  const [policy, setPolicy] = useState<StockFeePolicy | null>(null);
  useEffect(() => {
    let cancelled = false;
    getStockFeePolicy()
      .then((p) => { if (!cancelled) setPolicy(p); })
      .catch(() => { if (!cancelled) setPolicy(null); });
    // Execution re-reads the fee; if it changed, show the new one so the
    // person confirms again against what will actually be charged.
    const unsubscribe = subscribeStockFeePolicy((p) => { if (!cancelled) setPolicy(p); });
    return () => { cancelled = true; unsubscribe(); };
  }, []);
  return policy;
};
