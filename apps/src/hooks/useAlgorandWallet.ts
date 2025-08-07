/**
 * React Hook for Algorand Wallet Integration
 * 
 * This hook provides easy access to Algorand wallet functionality
 * for authenticated Firebase users.
 */

import { useState, useEffect, useCallback } from 'react';
import { algorandExtension, AlgorandWalletInfo } from '../services/algorandExtension';
import authService from '../services/authService';

export interface UseAlgorandWalletReturn {
  // Wallet info
  walletInfo: AlgorandWalletInfo | null;
  isLoading: boolean;
  error: string | null;
  
  // Actions
  setupWallet: () => Promise<void>;
  refreshBalance: () => Promise<void>;
  sendTransaction: (to: string, amount: number, note?: string) => Promise<string | null>;
  
  // Status
  hasWallet: boolean;
  isAuthenticated: boolean;
}

export function useAlgorandWallet(): UseAlgorandWalletReturn {
  const [walletInfo, setWalletInfo] = useState<AlgorandWalletInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Check authentication status
  useEffect(() => {
    const checkAuth = () => {
      const isSignedIn = authService.isSignedIn();
      setIsAuthenticated(isSignedIn);
    };

    checkAuth();
    
    // You could add an event listener here for auth state changes
  }, []);

  // Setup Algorand wallet for authenticated user
  const setupWallet = useCallback(async () => {
    if (!isAuthenticated) {
      setError('User must be authenticated first');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const wallet = await algorandExtension.setupAlgorandWallet();
      
      if (wallet) {
        setWalletInfo(wallet);
        
        if (wallet.isNew) {
          console.log('New Algorand wallet created:', wallet.address);
        } else {
          console.log('Existing Algorand wallet loaded:', wallet.address);
        }
      } else {
        setError('Failed to setup Algorand wallet');
      }
    } catch (err: any) {
      console.error('Error setting up Algorand wallet:', err);
      setError(err.message || 'Failed to setup wallet');
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  // Auto-setup wallet when user is authenticated
  useEffect(() => {
    if (isAuthenticated && !walletInfo && !isLoading) {
      setupWallet();
    }
  }, [isAuthenticated, walletInfo, isLoading, setupWallet]);

  // Refresh balance
  const refreshBalance = useCallback(async () => {
    if (!walletInfo) return;

    try {
      const balance = await algorandExtension.getBalance();
      setWalletInfo(prev => prev ? { ...prev, balance } : null);
    } catch (err: any) {
      console.error('Error refreshing balance:', err);
      setError('Failed to refresh balance');
    }
  }, [walletInfo]);

  // Send transaction
  const sendTransaction = useCallback(async (
    to: string,
    amount: number,
    note?: string
  ): Promise<string | null> => {
    if (!walletInfo) {
      setError('No wallet available');
      return null;
    }

    setIsLoading(true);
    setError(null);

    try {
      const txId = await algorandExtension.sendTransaction(to, amount, note);
      
      if (txId) {
        console.log('Transaction sent:', txId);
        // Refresh balance after transaction
        await refreshBalance();
      }
      
      return txId;
    } catch (err: any) {
      console.error('Error sending transaction:', err);
      setError(err.message || 'Failed to send transaction');
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [walletInfo, refreshBalance]);

  return {
    walletInfo,
    isLoading,
    error,
    setupWallet,
    refreshBalance,
    sendTransaction,
    hasWallet: !!walletInfo,
    isAuthenticated
  };
}