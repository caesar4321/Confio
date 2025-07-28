import React, { createContext, useContext } from 'react';
import { useAccountManager, UseAccountManagerReturn } from '../hooks/useAccountManager';

// Create the context
const AccountContext = createContext<UseAccountManagerReturn | null>(null);

// Provider component
export const AccountProvider = ({ children }: { children: React.ReactNode }) => {
  const account = useAccountManager(); // Single instance of the hook
  return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
};

// Hook to use the context
export const useAccount = () => {
  const ctx = useContext(AccountContext);
  if (!ctx) {
    console.error("useAccount called outside <AccountProvider>. Stack trace:");
    console.error(new Error().stack);
    throw new Error("useAccount must be used inside <AccountProvider>");
  }
  return ctx;
}; 