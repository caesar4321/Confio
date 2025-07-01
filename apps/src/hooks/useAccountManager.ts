import { useState, useEffect, useCallback } from 'react';
import { AuthService } from '../services/authService';
import { AccountManager, AccountContext, StoredAccount } from '../utils/accountManager';

export interface UseAccountManagerReturn {
  // Account state
  activeAccount: StoredAccount | null;
  accounts: StoredAccount[];
  isLoading: boolean;
  
  // Account actions
  switchAccount: (accountId: string) => Promise<void>;
  createAccount: (
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ) => Promise<StoredAccount>;
  updateAccount: (accountId: string, updates: Partial<StoredAccount>) => Promise<void>;
  deleteAccount: (accountId: string) => Promise<void>;
  
  // Utility functions
  getActiveAccountContext: () => Promise<AccountContext>;
  refreshAccounts: () => Promise<void>;
}

export const useAccountManager = (): UseAccountManagerReturn => {
  const [activeAccount, setActiveAccount] = useState<StoredAccount | null>(null);
  const [accounts, setAccounts] = useState<StoredAccount[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const authService = AuthService.getInstance();
  const accountManager = AccountManager.getInstance();

  // Load accounts on mount
  useEffect(() => {
    loadAccounts();
  }, []);

  const loadAccounts = useCallback(async () => {
    try {
      setIsLoading(true);
      
      // Get all stored accounts
      const storedAccounts = await authService.getStoredAccounts();
      setAccounts(storedAccounts);
      
      // If no accounts exist, that's expected - accounts should only be created after proper zkLogin authentication
      if (storedAccounts.length === 0) {
        console.log('useAccountManager - No accounts found - this is expected if no zkLogin authentication has been completed');
        console.log('useAccountManager - Accounts will be created after proper server-side authentication (InitializeZkLogin/FinalizeZkLogin)');
      }
      
      // Get active account context
      const activeContext = await authService.getActiveAccountContext();
      const activeAccountId = accountManager.generateAccountId(activeContext.type, activeContext.index);
      
      console.log('loadAccounts - Active context:', {
        activeContextType: activeContext.type,
        activeContextIndex: activeContext.index,
        generatedAccountId: activeAccountId,
        storedAccountsCount: storedAccounts.length,
        storedAccountIds: storedAccounts.map(acc => acc.id)
      });
      
      // Find the active account
      const active = storedAccounts.find(acc => acc.id === activeAccountId);
      
      console.log('loadAccounts - Found active account:', {
        foundActive: !!active,
        activeAccountId: active?.id,
        activeAccountType: active?.type,
        activeAccountIndex: active?.index
      });
      
      setActiveAccount(active || null);
    } catch (error) {
      console.error('Error loading accounts:', error);
    } finally {
      setIsLoading(false);
    }
  }, [authService, accountManager]);

  const switchAccount = useCallback(async (accountId: string) => {
    try {
      console.log('useAccountManager - switchAccount called with:', accountId);
      setIsLoading(true);
      
      // Switch account in auth service
      await authService.switchAccount(accountId);
      
      console.log('useAccountManager - switchAccount completed, reloading accounts');
      
      // Reload accounts to get updated state
      await loadAccounts();
    } catch (error) {
      console.error('Error switching account:', error);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, [authService, loadAccounts]);

  const createAccount = useCallback(async (
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ): Promise<StoredAccount> => {
    try {
      const newAccount = await authService.createAccount(name, avatar, phone, category);
      
      // Reload accounts to include the new one
      await loadAccounts();
      
      return newAccount;
    } catch (error) {
      console.error('Error creating account:', error);
      throw error;
    }
  }, [authService, loadAccounts]);

  const updateAccount = useCallback(async (accountId: string, updates: Partial<StoredAccount>) => {
    try {
      await accountManager.updateAccount(accountId, updates);
      
      // Reload accounts to get updated state
      await loadAccounts();
    } catch (error) {
      console.error('Error updating account:', error);
      throw error;
    }
  }, [accountManager, loadAccounts]);

  const deleteAccount = useCallback(async (accountId: string) => {
    try {
      await accountManager.deleteAccount(accountId);
      
      // Reload accounts to get updated state
      await loadAccounts();
    } catch (error) {
      console.error('Error deleting account:', error);
      throw error;
    }
  }, [accountManager, loadAccounts]);

  const getActiveAccountContext = useCallback(async (): Promise<AccountContext> => {
    return await authService.getActiveAccountContext();
  }, [authService]);

  const refreshAccounts = useCallback(async () => {
    await loadAccounts();
  }, [loadAccounts]);

  return {
    activeAccount,
    accounts,
    isLoading,
    switchAccount,
    createAccount,
    updateAccount,
    deleteAccount,
    getActiveAccountContext,
    refreshAccounts,
  };
}; 