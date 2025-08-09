import React, { useState, useCallback, useEffect, useMemo } from 'react';
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
  const [isLoading, setIsLoading] = useState(false); // Start as false since query handles loading
  const [activeAccountContext, setActiveAccountContext] = useState<AccountContext | null>(null);

  const authService = AuthService.getInstance();
  const accountManager = AccountManager.getInstance();
  const apolloClient = useApolloClient();
  const { profileData, refreshProfile } = useAuth();
  
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
    fetchPolicy: 'cache-and-network', // Get cached data first, then update with fresh data
    errorPolicy: 'all',
    notifyOnNetworkStatusChange: false, // Prevent re-renders during background refetch
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
        isEmployee: serverAccounts.map((acc: any) => acc.isEmployee),
        accountIds: serverAccounts.map((acc: any) => acc.id),
        serverError: serverError?.message || 'none',
      });
      
      // Convert server accounts to StoredAccount format
      // Filter out any null accounts first
      const convertedAccounts: StoredAccount[] = serverAccounts
        .filter((acc: any) => acc != null)
        .map((serverAcc: any) => {
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
        
        // Generate proper ID based on account type
        let accountId: string;
        if (normalizedType === 'personal') {
          accountId = 'personal_0';
        } else if (normalizedType === 'business' && serverAcc.business?.id) {
          // For business accounts, include business_id to ensure uniqueness
          accountId = `business_${serverAcc.business.id}_0`;
        } else {
          // Fallback - shouldn't happen
          accountId = `${normalizedType}_${serverAcc.id}_0`;
        }
        
        const convertedAccount: StoredAccount = {
          id: accountId, // Use proper format with business_id for uniqueness
          name: baseName, // Use the base name without the prefix for display
          type: normalizedType,
          index: 0, // Always 0 for both personal and business accounts
          phone: normalizedType === 'personal' ? profileData?.userProfile?.phoneNumber : undefined,
          category: serverAcc.business?.category,
          avatar: avatar,
          algorandAddress: '', // Client will compute this on-demand
          createdAt: serverAcc.createdAt,
          isActive: true,
          isEmployee: serverAcc.isEmployee || false,
          employeeRole: serverAcc.employeeRole,
          employeePermissions: serverAcc.employeePermissions,
          employeeRecordId: serverAcc.employeeRecordId,
          business: serverAcc.business ? {
            id: serverAcc.business.id,
            name: serverAcc.business.name,
            category: serverAcc.business.category,
          } : undefined,
        };
        
        console.log('useAccountManager - Converted account:', {
          originalAccountType: serverAcc.accountType,
          normalizedType,
          convertedAccount: {
            id: convertedAccount.id,
            type: convertedAccount.type,
            name: convertedAccount.name,
            businessId: convertedAccount.business?.id,
            isEmployee: convertedAccount.isEmployee,
            employeeRole: convertedAccount.employeeRole,
            employeePermissions: convertedAccount.employeePermissions
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
          algorandAddress: '', // Will be set during authentication
          createdAt: new Date().toISOString(),
          isActive: true,
        };
        
        convertedAccounts.push(defaultAccount);
        console.log('useAccountManager - Created default personal account:', defaultAccount);
      } else if (convertedAccounts.length === 0) {
        console.log('useAccountManager - No server accounts found but Keychain says', activeContext.type, '- waiting for server data');
      }
      
      // Generate the expected active account ID from context
      let expectedActiveAccountId: string;
      if (activeContext.type === 'business' && activeContext.businessId) {
        expectedActiveAccountId = `business_${activeContext.businessId}_${activeContext.index}`;
      } else {
        expectedActiveAccountId = accountManager.generateAccountId(activeContext.type, activeContext.index);
      }
      
      console.log('loadAccounts - Active context:', {
        activeContextType: activeContext.type,
        activeContextIndex: activeContext.index,
        activeContextBusinessId: activeContext.businessId,
        expectedActiveAccountId: expectedActiveAccountId,
        serverAccountsCount: convertedAccounts.length,
        serverAccountIds: convertedAccounts.map(acc => acc.id)
      });
      
      // Find the active account by exact ID match
      const active = convertedAccounts.find(acc => acc.id === expectedActiveAccountId);
      
      console.log('loadAccounts - Found active account:', {
        foundActive: !!active,
        expectedActiveAccountId: expectedActiveAccountId,
        actualActiveAccountId: active?.id,
        activeAccountType: active?.type,
        activeAccountIndex: active?.index,
        activeAccountName: active?.name,
        activeAccountAvatar: active?.avatar,
        allAccountIds: convertedAccounts.map(acc => acc.id)
      });
      
      if (active) {
        // Get the address for the active account (may already be computed)
        const currentAddress = await authService.getAlgorandAddress();
        const activeWithAddress = {
          ...active,
          algorandAddress: currentAddress || ''
        };
        
        setActiveAccount(activeWithAddress);
        console.log('loadAccounts - setActiveAccount called with:', {
          ...active,
          addressPreview: currentAddress ? currentAddress.substring(0, 10) + '...' : 'none'
        });
        
        // Note: Profile refresh is handled by AuthContext, not here
        // This prevents circular dependencies and unnecessary network requests
      } else {
        console.warn(
          '[AccountMgr] Expected active account ID', expectedActiveAccountId,
          'not found in convertedAccounts:', convertedAccounts.map(acc => acc.id)
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

  // Load accounts on mount and when server data changes
  useEffect(() => {
    // Load accounts when server data is available or error occurs
    if (!serverLoading && (serverAccountsData || serverError)) {
      loadAccounts();
    }
  }, [serverAccountsData, serverLoading, serverError, loadAccounts]);

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
      const convertedAccounts: StoredAccount[] = serverAccounts
        .filter((acc: any) => acc != null)
        .map((serverAcc: any) => {
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
          baseName,
          isEmployee: serverAcc.isEmployee,
          accountIndex: serverAcc.accountIndex
        });
        
        // Generate proper ID based on account type
        let accountId: string;
        if (normalizedType === 'personal') {
          accountId = 'personal_0';
        } else if (normalizedType === 'business' && serverAcc.business?.id) {
          // For business accounts, include business_id to ensure uniqueness
          accountId = `business_${serverAcc.business.id}_0`;
        } else {
          // Fallback - shouldn't happen
          accountId = `${normalizedType}_${serverAcc.id}_0`;
        }
        
        return {
          id: accountId, // Use proper format with business_id for uniqueness
          name: baseName,
          type: normalizedType, // 👈 Use normalized type here
          index: 0, // Always 0 for current system
          phone: normalizedType === 'personal' ? profileData?.userProfile?.phoneNumber : undefined,
          category: serverAcc.business?.category,
          avatar: avatar,
          algorandAddress: '', // Client will compute this on-demand
          createdAt: serverAcc.createdAt || new Date().toISOString(),
          isActive: true,
          isEmployee: serverAcc.isEmployee || false,
          employeeRole: serverAcc.employeeRole,
          employeePermissions: serverAcc.employeePermissions,
          employeeRecordId: serverAcc.employeeRecordId,
          business: serverAcc.business ? {
            id: serverAcc.business.id,
            name: serverAcc.business.name,
            category: serverAcc.business.category,
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
        
        // Switch account in auth service
        // Use the server-provided ID directly for ALL accounts
        console.log('useAccountManager - About to call authService.switchAccount with:', {
          accountId: newActiveAccount.id,
          accountType: newActiveAccount.type,
          businessId: newActiveAccount.business?.id,
          isEmployee: newActiveAccount.isEmployee
        });
        await authService.switchAccount(newActiveAccount.id, apolloClient);
        
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
        
        // Refresh profile data to match the new account context
        try {
          if (newActiveAccount.type === 'business' && newActiveAccount.business?.id) {
            await refreshProfile('business', newActiveAccount.business.id);
            console.log('useAccountManager - Refreshed business profile after account switch');
          } else {
            await refreshProfile('personal');
            console.log('useAccountManager - Refreshed personal profile after account switch');
          }
        } catch (error) {
          console.error('useAccountManager - Error refreshing profile after account switch:', error);
        }
        
        // Get the computed address after the switch
        // Address computation happens during authService.switchAccount while loading spinner is active
        const computedAddress = await authService.getAlgorandAddress();
        if (computedAddress) {
          const activeWithAddress = {
            ...newActiveAccount,
            algorandAddress: computedAddress
          };
          setActiveAccount(activeWithAddress);
          console.log('useAccountManager - Account has address after switch:', {
            addressPreview: computedAddress.substring(0, 10) + '...'
          });
        }
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