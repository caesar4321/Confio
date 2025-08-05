import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useZkLogin } from '../hooks/useZkLogin';
import { useAptosKeyless } from '../hooks/useAptosKeyless';

export type BlockchainNetwork = 'sui' | 'aptos';

interface BlockchainAuthContextValue {
  // Network selection
  currentNetwork: BlockchainNetwork;
  setCurrentNetwork: (network: BlockchainNetwork) => void;
  
  // Authentication states
  isAuthenticated: boolean;
  isLoading: boolean;
  
  // Sui zkLogin
  suiAccount: any | null;
  suiBalance: string | null;
  
  // Aptos Keyless
  aptosAccount: any | null;
  aptosBalance: string | null;
  
  // Authentication methods
  signInWithGoogle: () => Promise<void>;
  signInWithApple: () => Promise<void>;
  signOut: () => Promise<void>;
  
  // Transaction methods
  sendTransaction: (params: any) => Promise<any>;
  
  // Balance refresh
  refreshBalances: () => Promise<void>;
}

const BlockchainAuthContext = createContext<BlockchainAuthContextValue | undefined>(undefined);

export const BlockchainAuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [currentNetwork, setCurrentNetwork] = useState<BlockchainNetwork>('aptos'); // Default to Aptos
  
  // Sui zkLogin hook
  const {
    loading: suiLoading,
    error: suiError,
    zkLoginData: suiAccount,
    signInWithGoogle: suiSignInWithGoogle,
    signInWithApple: suiSignInWithApple,
    signOut: suiSignOut,
  } = useZkLogin();
  
  // Aptos Keyless hook
  const {
    loading: aptosLoading,
    error: aptosError,
    keylessAccount: aptosAccount,
    balance: aptosBalanceData,
    signInWithGoogle: aptosSignInWithGoogle,
    signInWithApple: aptosSignInWithApple,
    signOut: aptosSignOut,
    refreshBalance: refreshAptosBalance,
    signAndSubmitTransaction: aptosSubmitTransaction,
  } = useAptosKeyless();
  
  // Derived states
  const isAuthenticated = currentNetwork === 'sui' ? !!suiAccount : !!aptosAccount;
  const isLoading = suiLoading || aptosLoading;
  
  // Sign in with Google
  const signInWithGoogle = async () => {
    try {
      if (currentNetwork === 'sui') {
        await suiSignInWithGoogle();
      } else {
        await aptosSignInWithGoogle();
      }
    } catch (error) {
      console.error(`[BlockchainAuth] ${currentNetwork} Google sign in error:`, error);
      throw error;
    }
  };
  
  // Sign in with Apple
  const signInWithApple = async () => {
    try {
      if (currentNetwork === 'sui') {
        await suiSignInWithApple();
      } else {
        await aptosSignInWithApple();
      }
    } catch (error) {
      console.error(`[BlockchainAuth] ${currentNetwork} Apple sign in error:`, error);
      throw error;
    }
  };
  
  // Sign out
  const signOut = async () => {
    try {
      if (currentNetwork === 'sui') {
        await suiSignOut();
      } else {
        await aptosSignOut();
      }
    } catch (error) {
      console.error(`[BlockchainAuth] ${currentNetwork} sign out error:`, error);
      throw error;
    }
  };
  
  // Send transaction (network-specific)
  const sendTransaction = async (params: any) => {
    try {
      if (currentNetwork === 'sui') {
        // TODO: Implement Sui transaction
        throw new Error('Sui transactions not yet implemented in this context');
      } else {
        return await aptosSubmitTransaction(params);
      }
    } catch (error) {
      console.error(`[BlockchainAuth] ${currentNetwork} transaction error:`, error);
      throw error;
    }
  };
  
  // Refresh balances
  const refreshBalances = async () => {
    try {
      if (currentNetwork === 'sui') {
        // TODO: Implement Sui balance refresh
        console.log('[BlockchainAuth] Sui balance refresh not yet implemented');
      } else {
        await refreshAptosBalance();
      }
    } catch (error) {
      console.error(`[BlockchainAuth] Error refreshing ${currentNetwork} balance:`, error);
    }
  };
  
  // Switch network handler
  const handleNetworkSwitch = async (network: BlockchainNetwork) => {
    if (network === currentNetwork) return;
    
    // Sign out from current network before switching
    if (isAuthenticated) {
      await signOut();
    }
    
    setCurrentNetwork(network);
  };
  
  // Get balance for current network
  const getSuiBalance = (): string | null => {
    // TODO: Extract balance from suiAccount
    return suiAccount?.balance || null;
  };
  
  const getAptosBalance = (): string | null => {
    return aptosBalanceData?.apt || null;
  };
  
  const value: BlockchainAuthContextValue = {
    // Network
    currentNetwork,
    setCurrentNetwork: handleNetworkSwitch,
    
    // Auth states
    isAuthenticated,
    isLoading,
    
    // Sui
    suiAccount,
    suiBalance: getSuiBalance(),
    
    // Aptos
    aptosAccount,
    aptosBalance: getAptosBalance(),
    
    // Methods
    signInWithGoogle,
    signInWithApple,
    signOut,
    sendTransaction,
    refreshBalances,
  };
  
  return (
    <BlockchainAuthContext.Provider value={value}>
      {children}
    </BlockchainAuthContext.Provider>
  );
};

// Hook to use blockchain auth context
export const useBlockchainAuth = () => {
  const context = useContext(BlockchainAuthContext);
  if (!context) {
    throw new Error('useBlockchainAuth must be used within BlockchainAuthProvider');
  }
  return context;
};