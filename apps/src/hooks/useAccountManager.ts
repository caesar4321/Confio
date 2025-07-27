import React, { useState, useCallback, useEffect } from 'react';
import { useApolloClient, useQuery } from '@apollo/client';
import { GET_USER_ACCOUNTS } from '../apollo/queries';
import { AuthService } from '../services/authService';
import { AccountManager, StoredAccount, AccountContext } from '../utils/accountManager';
import { useAuth } from '../contexts/AuthContext';

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
  syncWithServer: (serverAccounts: any[]) => Promise<void>;
}

export const useAccountManager = (): UseAccountManagerReturn => {
  const [activeAccount, setActiveAccount] = useState<StoredAccount | null>(null);
  const [accounts, setAccounts] = useState<StoredAccount[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [activeAccountContext, setActiveAccountContext] = useState<AccountContext | null>(null);

  const authService = AuthService.getInstance();
  const accountManager = AccountManager.getInstance();
  const apolloClient = useApolloClient();
  const { profileData } = useAuth();
  
  // Debug profile loading
  console.log('useAccountManager - Profile state:', {
    profileDataLoaded: !!profileData,
    currentAccountType: profileData?.currentAccountType,
    userProfileName: profileData?.userProfile?.firstName || profileData?.userProfile?.username,
    businessProfileName: profileData?.businessProfile?.name,
    userProfileId: profileData?.userProfile?.id,
    businessProfileId: profileData?.businessProfile?.id
  });

  // Fetch accounts from server using GraphQL
  const { data: serverAccountsData, loading: serverLoading, error: serverError, refetch: refetchServerAccounts } = useQuery(GET_USER_ACCOUNTS, {
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
  });

  const loadAccounts = useCallback(async () => {
    try {
      setIsLoading(true);
      
      // Get server accounts
      const serverAccounts = serverAccountsData?.userAccounts || [];
      console.log('useAccountManager - Server accounts data:', {
        serverAccountsData: !!serverAccountsData,
        userAccounts: serverAccounts,
        accountsCount: serverAccounts.length,
        accountTypes: serverAccounts.map((acc: any) => acc.accountType),
        rawServerData: JSON.stringify(serverAccountsData, null, 2)
      });
      
      // Convert server accounts to StoredAccount format
      const convertedAccounts: StoredAccount[] = serverAccounts.map((serverAcc: any) => {
        // Use server-provided display_name and avatar_letter for all accounts
        const displayName = serverAcc.displayName || 'Account';
        const avatar = serverAcc.avatarLetter || displayName.charAt(0).toUpperCase();
        
        // Extract the base name without the "Personal -" or "Negocio -" prefix
        const baseName = displayName.replace(/^(Personal|Negocio) - /, '');
        
        console.log('useAccountManager - Account conversion:', {
          accountId: serverAcc.accountId,
          accountType: serverAcc.accountType,
          displayName,
          baseName,
          avatar,
          serverDisplayName: serverAcc.displayName,
          serverAvatarLetter: serverAcc.avatarLetter,
          rawServerAccount: JSON.stringify(serverAcc, null, 2)
        });
        
        // Ensure accountType is properly set and normalized
        const accountType = serverAcc.accountType || 'personal';
        const normalizedType = accountType.toLowerCase() as 'personal' | 'business';
        
        const convertedAccount = {
          id: serverAcc.id, // Use serverAcc.id instead of serverAcc.accountId
          name: baseName, // Use the base name without the prefix for display
          type: normalizedType,
          index: serverAcc.accountIndex,
          phone: normalizedType === 'personal' ? profileData?.userProfile?.phoneNumber : undefined,
          category: serverAcc.business?.category,
          avatar: avatar,
          suiAddress: serverAcc.suiAddress,
          createdAt: serverAcc.createdAt,
          isActive: true,
          business: serverAcc.business ? {
            id: serverAcc.business.id,
            name: serverAcc.business.name,
            description: serverAcc.business.description,
            category: serverAcc.business.category,
            businessRegistrationNumber: serverAcc.business.businessRegistrationNumber,
            address: serverAcc.business.address,
            createdAt: serverAcc.business.createdAt,
          } : undefined,
        };
        
        console.log('useAccountManager - Converted account:', {
          originalAccountType: serverAcc.accountType,
          normalizedType,
          convertedAccount: {
            id: convertedAccount.id,
            type: convertedAccount.type,
            name: convertedAccount.name,
            businessId: convertedAccount.business?.id
          }
        });
        
        return convertedAccount;
      });
      
      // Sort accounts: personal first, then business by index
      const sortedAccounts = convertedAccounts.sort((a, b) => {
        // Personal accounts get priority (0), business accounts get lower priority (1)
        const aPriority = a.type.toLowerCase() === 'personal' ? 0 : 1;
        const bPriority = b.type.toLowerCase() === 'personal' ? 0 : 1;
        
        if (aPriority !== bPriority) {
          return aPriority - bPriority;
        }
        
        // If same type, sort by index
        return a.index - b.index;
      });
      
      setAccounts(sortedAccounts);
      
      // Get active account context BEFORE deciding to create default account
      const activeContext = await authService.getActiveAccountContext();
      
      // Only create default personal account if no server accounts AND Keychain says personal
      if (convertedAccounts.length === 0 && activeContext.type === 'personal') {
        console.log('useAccountManager - No server accounts found AND Keychain says personal, creating default personal account');
        
        // Create a default personal account with user profile data
        const displayName = profileData?.userProfile?.firstName || profileData?.userProfile?.username || 'Personal';
        const avatar = displayName.charAt(0).toUpperCase();
        const defaultAccount: StoredAccount = {
          id: 'personal_0',
          name: displayName,
          type: 'personal',
          index: 0,
          phone: profileData?.userProfile?.phoneNumber || undefined,
          category: undefined,
          avatar: avatar,
          suiAddress: '', // Will be set during zkLogin finalization
          createdAt: new Date().toISOString(),
          isActive: true,
        };
        
        convertedAccounts.push(defaultAccount);
        console.log('useAccountManager - Created default personal account:', defaultAccount);
      } else if (convertedAccounts.length === 0) {
        console.log('useAccountManager - No server accounts found but Keychain says', activeContext.type, '- waiting for server data');
      }
      
      // Use the activeContext we already got above
      const activeAccountId = accountManager.generateAccountId(activeContext.type, activeContext.index);
      
      console.log('loadAccounts - Active context:', {
        activeContextType: activeContext.type,
        activeContextIndex: activeContext.index,
        generatedAccountId: activeAccountId,
        serverAccountsCount: convertedAccounts.length,
        serverAccountIds: convertedAccounts.map(acc => acc.id)
      });
      
      // Find the active account by matching type and index instead of ID
      const active = convertedAccounts.find(acc => 
        acc.type === activeContext.type && acc.index === activeContext.index
      );
      
      console.log('loadAccounts - Found active account:', {
        foundActive: !!active,
        activeAccountId: active?.id,
        activeAccountType: active?.type,
        activeAccountIndex: active?.index,
        activeAccountName: active?.name,
        activeAccountAvatar: active?.avatar,
        allAccountIds: convertedAccounts.map(acc => acc.id),
        searchingFor: `${activeContext.type}_${activeContext.index}`
      });
      
      if (active) {
        setActiveAccount(active);
        console.log('loadAccounts - setActiveAccount called with:', active);
        
        // Note: Profile refresh is handled by AuthContext, not here
        // This prevents circular dependencies and unnecessary network requests
      } else {
        console.warn(
          '[AccountMgr] Active account ID', activeAccountId,
          'not present in convertedAccounts:', convertedAccounts.map(acc => acc.id)
        );
        // Do NOT reset to null here; keep the old value until we know more
        console.log('loadAccounts - Keeping existing activeAccount, not setting to null');
      }
      
      // Debug the active account state
      if (active) {
        console.log('loadAccounts - Active account details:', {
          id: active.id,
          type: active.type,
          name: active.name,
          typeIsDefined: active.type !== undefined,
          typeIsString: typeof active.type === 'string',
          typeValue: active.type
        });
      } else {
        console.log('loadAccounts - No active account found, setting to null');
      }
    } catch (error) {
      console.error('Error loading accounts:', error);
    } finally {
      setIsLoading(false);
    }
  }, [authService, accountManager, serverAccountsData, profileData]);

  // Load accounts on mount and when server data or user profile changes
  useEffect(() => {
    loadAccounts();
  }, [serverAccountsData, profileData]);

  // Reload accounts when active account context changes (for account switching)
  useEffect(() => {
    if (activeAccountContext) {
      // Instead of calling loadAccounts directly, just refetch server data
      refetchServerAccounts();
    }
  }, [activeAccountContext, refetchServerAccounts]);

  // Load initial active account context on mount
  useEffect(() => {
    const loadInitialContext = async () => {
      try {
        const context = await authService.getActiveAccountContext();
        setActiveAccountContext(context);
      } catch (error) {
        console.error('Error loading initial account context:', error);
      }
    };
    
    loadInitialContext();
  }, [authService]);

  const switchAccount = useCallback(async (accountId: string) => {
    try {
      console.log('useAccountManager - switchAccount called with:', accountId);
      setIsLoading(true);
      
      // Directly update the active account state for immediate UI update
      const serverAccounts = serverAccountsData?.userAccounts || [];
      const convertedAccounts: StoredAccount[] = serverAccounts.map((serverAcc: any) => {
        const displayName = serverAcc.displayName || 'Account';
        const avatar = serverAcc.avatarLetter || (displayName ? displayName.charAt(0).toUpperCase() : 'A');
        const accountType = serverAcc.accountType || 'personal';
        
        // Extract the base name without the "Personal -" or "Negocio -" prefix
        const baseName = displayName.replace(/^(Personal|Negocio) - /, '');
        
        // 🔥 IMPORTANT: Normalize the account type to lowercase
        const normalizedType = accountType.toLowerCase() as 'personal' | 'business';
        
        console.log('🔄 switchAccount - Converting account:', {
          accountId: serverAcc.id, // Use serverAcc.id instead of serverAcc.accountId
          originalType: accountType,
          normalizedType,
          baseName
        });
        
        return {
          id: serverAcc.id, // Use serverAcc.id instead of serverAcc.accountId
          name: baseName,
          type: normalizedType, // 👈 Use normalized type here
          index: serverAcc.accountIndex || 0,
          phone: normalizedType === 'personal' ? profileData?.userProfile?.phoneNumber : undefined,
          category: serverAcc.business?.category,
          avatar: avatar,
          suiAddress: serverAcc.suiAddress || '',
          createdAt: serverAcc.createdAt || new Date().toISOString(),
          isActive: true,
          business: serverAcc.business ? {
            id: serverAcc.business.id,
            name: serverAcc.business.name,
            description: serverAcc.business.description,
            category: serverAcc.business.category,
            businessRegistrationNumber: serverAcc.business.businessRegistrationNumber,
            address: serverAcc.business.address,
            createdAt: serverAcc.business.createdAt,
          } : undefined,
        };
      });
      
      // Find the new active account by server ID
      const newActiveAccount = convertedAccounts.find(acc => acc.id === accountId);
      if (newActiveAccount) {
        console.log('✅ useAccountManager - Setting active account with normalized type:', {
          id: newActiveAccount.id,
          type: newActiveAccount.type,
          name: newActiveAccount.name,
          typeIsLowercase: newActiveAccount.type === newActiveAccount.type.toLowerCase()
        });
        setActiveAccount(newActiveAccount);
        console.log('useAccountManager - setActiveAccount called successfully');
        
        // Switch account in auth service with the generated account ID
        const generatedAccountId = `${newActiveAccount.type}_${newActiveAccount.index}`;
        await authService.switchAccount(generatedAccountId, apolloClient);
        
        // Get the new active account context
        const newActiveContext = await authService.getActiveAccountContext();
        console.log('useAccountManager - New active context:', newActiveContext);
        
        // Update the active account context state
        setActiveAccountContext(newActiveContext);
        
        // Small delay to ensure the new JWT token is propagated
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Clear Apollo cache to ensure fresh data with new account context
        try {
          // Use resetStore instead of clearStore - it clears cache AND refetches active queries
          await apolloClient.resetStore();
          console.log('useAccountManager - Apollo store reset after account switch');
        } catch (error) {
          console.log('useAccountManager - Error resetting Apollo store:', error);
          // If resetStore fails, try cache eviction as fallback
          try {
            apolloClient.cache.evict({});
            apolloClient.cache.gc();
            console.log('useAccountManager - Cache evicted as fallback');
          } catch (evictError) {
            console.log('useAccountManager - Error evicting cache:', evictError);
          }
        }
        
        // Note: Profile refresh is handled by AuthContext, not here
        // This prevents circular dependencies and unnecessary network requests
      } else {
        console.log('useAccountManager - Could not find account with ID:', accountId);
        console.log('useAccountManager - Available accounts:', convertedAccounts.map(acc => acc.id));
      }
      
      console.log('useAccountManager - switchAccount completed');
    } catch (error) {
      console.error('Error switching account:', error);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, [authService, serverAccountsData, profileData]);

  const createAccount = useCallback(async (
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ): Promise<StoredAccount> => {
    throw new Error(
      'Account creation through useAccountManager is not supported. ' +
      'Use server mutations (e.g., CREATE_BUSINESS) for account creation. ' +
      'The client should only manage existing accounts from the server.'
    );
  }, []);

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
    try {
      // Just refetch server data - Apollo's cache updates automatically
      await refetchServerAccounts();
      // Removed loadAccounts() call - it causes the blink
      // The useEffect watching serverAccountsData will handle updates automatically
    } catch (error) {
      console.error('Error refreshing accounts from server:', error);
    }
  }, [refetchServerAccounts]);

  const syncWithServer = useCallback(async (serverAccounts: any[]) => {
    try {
      // Since we're now fetching directly from the server, we just need to refetch
      await refetchServerAccounts();
    } catch (error) {
      console.error('Error syncing with server:', error);
      throw error;
    }
  }, [refetchServerAccounts]);

  // Combine loading states
  const combinedLoading = isLoading || serverLoading;

  return {
    activeAccount,
    accounts,
    isLoading: combinedLoading,
    switchAccount,
    createAccount,
    updateAccount,
    deleteAccount,
    getActiveAccountContext,
    refreshAccounts,
    syncWithServer,
  };
}; 