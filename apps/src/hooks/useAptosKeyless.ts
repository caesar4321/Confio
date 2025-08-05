import { useState, useCallback, useEffect } from 'react';
import { AptosKeylessService, KeylessAccount } from '../services/aptosKeylessService';

export interface UseAptosKeylessReturn {
  loading: boolean;
  error: Error | null;
  keylessAccount: KeylessAccount | null;
  balance: { apt: string } | null;
  isSignedIn: boolean;
  signInWithGoogle: () => Promise<KeylessAccount>;
  signInWithApple: () => Promise<KeylessAccount>;
  signOut: () => Promise<void>;
  refreshBalance: () => Promise<void>;
  signAndSubmitTransaction: (transaction: any) => Promise<any>;
}

export const useAptosKeyless = (): UseAptosKeylessReturn => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [keylessAccount, setKeylessAccount] = useState<KeylessAccount | null>(null);
  const [balance, setBalance] = useState<{ apt: string } | null>(null);

  const keylessService = AptosKeylessService.getInstance();

  // Initialize service on mount
  useEffect(() => {
    const initializeService = async () => {
      try {
        await keylessService.initialize();
        const account = keylessService.getCurrentAccount();
        if (account) {
          setKeylessAccount(account);
          // Fetch initial balance
          await refreshBalance();
        }
      } catch (err) {
        console.error('[useAptosKeyless] Initialization error:', err);
      }
    };

    initializeService();
  }, []);

  // Refresh balance
  const refreshBalance = useCallback(async () => {
    try {
      const account = keylessService.getCurrentAccount();
      if (account) {
        const balanceData = await keylessService.getBalance();
        setBalance(balanceData);
      }
    } catch (err) {
      console.error('[useAptosKeyless] Error fetching balance:', err);
    }
  }, []);

  // Sign in with Google
  const signInWithGoogle = useCallback(async (): Promise<KeylessAccount> => {
    try {
      setLoading(true);
      setError(null);
      
      const account = await keylessService.signInWithGoogle();
      setKeylessAccount(account);
      
      // Fetch balance after sign in
      await refreshBalance();
      
      return account;
    } catch (err) {
      const error = err as Error;
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, [refreshBalance]);

  // Sign in with Apple
  const signInWithApple = useCallback(async (): Promise<KeylessAccount> => {
    try {
      setLoading(true);
      setError(null);
      
      const account = await keylessService.signInWithApple();
      setKeylessAccount(account);
      
      // Fetch balance after sign in
      await refreshBalance();
      
      return account;
    } catch (err) {
      const error = err as Error;
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, [refreshBalance]);

  // Sign out
  const signOut = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      await keylessService.signOut();
      setKeylessAccount(null);
      setBalance(null);
    } catch (err) {
      const error = err as Error;
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  // Sign and submit transaction
  const signAndSubmitTransaction = useCallback(async (transaction: any) => {
    try {
      setLoading(true);
      setError(null);
      
      const result = await keylessService.signAndSubmitTransaction(transaction);
      
      // Refresh balance after transaction
      await refreshBalance();
      
      return result;
    } catch (err) {
      const error = err as Error;
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, [refreshBalance]);

  return {
    loading,
    error,
    keylessAccount,
    balance,
    isSignedIn: keylessService.isSignedIn(),
    signInWithGoogle,
    signInWithApple,
    signOut,
    refreshBalance,
    signAndSubmitTransaction,
  };
};