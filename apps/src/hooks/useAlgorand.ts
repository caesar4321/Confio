import { useCallback } from 'react';
import { Buffer } from 'buffer';
import algorandService from '../services/algorandService';

type UseAlgorandResult = {
  signTransactions: (transactionsB64: string[]) => Promise<string[]>;
};

// Minimal hook to sign Algorand transactions using the deterministic wallet service
export const useAlgorand = (): UseAlgorandResult => {
  const signTransactions = useCallback(async (transactionsB64: string[]) => {
    if (!transactionsB64 || transactionsB64.length === 0) return [];

    const signed: string[] = [];

    for (const txnB64 of transactionsB64) {
      if (!txnB64) continue;
      const txnBytes = Uint8Array.from(Buffer.from(txnB64, 'base64'));
      const signedBytes = await algorandService.signTransactionBytes(txnBytes);
      signed.push(Buffer.from(signedBytes).toString('base64'));
    }

    return signed;
  }, []);

  return { signTransactions };
};
