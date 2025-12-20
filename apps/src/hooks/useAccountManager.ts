import React, { useState, useCallback, useEffect, useMemo } from 'react';
import { useApolloClient, useQuery } from '@apollo/client';
import { GET_USER_ACCOUNTS } from '../apollo/queries';
import { AuthService } from '../services/authService';
import { AccountManager, StoredAccount, AccountContext } from '../utils/accountManager';
import { useAuth } from '../contexts/AuthContext';
import { waitForAuthReady } from '../contexts/AuthContext';

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
  const [authGatePassed, setAuthGatePassed] = useState(false);

  const authService = AuthService.getInstance();
  const accountManager = AccountManager.getInstance();
  const apolloClient = useApolloClient();
  const { profileData, refreshProfile, isAuthenticated, isLoading: authLoading, accountContextTick } = useAuth();

  // Helpers
  const dedupeById = useCallback((list: StoredAccount[]): StoredAccount[] => {
    const m = new Map<string, StoredAccount>();
    list.forEach(a => m.set(a.id, a));
    return Array.from(m.values());
  }, []);

  const ensureActiveAccountFrom = useCallback(async (list: StoredAccount[]) => {
    try {
      const ctx = await authService.getActiveAccountContext();
      const expectedId = ctx.type === 'business' && ctx.businessId
        ? `business_${ctx.businessId}_${ctx.index}`
        : `personal_${ctx.index}`;
      const pick = list.find(a => a.id === expectedId) || list[0];
      if (pick) {
        // Pass context explicitly to ensure address matches the account we're picking
        // Since we don't have the full context object easily available for 'pick' here,
        // we use the one we just fetched which SHOULD match 'pick' if the logic holds.
        // But to be safer, let's reconstruct context from 'pick'
        const pickContext: AccountContext = {
          type: pick.type,
          index: pick.index,
          businessId: pick.business?.id
        };
        const addr = await authService.getAlgorandAddress(pickContext);
        setActiveAccount({ ...pick, algorandAddress: addr ?? '' });
      }
    } catch { }
  }, [authService]);

  // Debug profile loading
  console.log('useAccountManager - Profile state:', {
    profileDataLoaded: !!profileData,
    currentAccountType: profileData?.currentAccountType,
    userProfileName: profileData?.userProfile?.firstName || profileData?.userProfile?.username,
    businessProfileName: profileData?.businessProfile?.name,
    userProfileId: profileData?.userProfile?.id,
    businessProfileId: profileData?.businessProfile?.id
  });

  // Delay any server-bound account queries until the auth gate is truly ready
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try { await waitForAuthReady(); } catch { }
      if (!cancelled) setAuthGatePassed(true);
    })();
    return () => { cancelled = true; };
  }, []);

  // Fetch accounts from server using GraphQL
  const { data: serverAccountsData, loading: serverLoading, error: serverError, refetch: refetchServerAccounts } = useQuery(GET_USER_ACCOUNTS, {
    // Fully disable the implicit watch on cold start; we'll drive hydration manually
    skip: true,
  } as any);

  // Convert raw server account objects to StoredAccount[]
  const convertServerAccounts = useCallback((serverAccounts: any[]): StoredAccount[] => {
    const converted: StoredAccount[] = serverAccounts
      .filter((acc: any) => acc != null)
      .map((serverAcc: any) => {
        const displayName = serverAcc.displayName || 'Account';
        const avatar = serverAcc.avatarLetter || displayName.charAt(0).toUpperCase();
        const baseName = displayName.replace(/^(Personal|Negocio) - /, '');
        const accountType = (serverAcc.accountType || 'personal').toLowerCase() as 'personal' | 'business';
        let accountId: string;
        if (accountType === 'personal') accountId = 'personal_0';
        else if (serverAcc.business?.id) accountId = `business_${serverAcc.business.id}_0`;
        else accountId = `${accountType}_${serverAcc.id}_0`;
        const convertedAccount: StoredAccount = {
          id: accountId,
          name: baseName,
          type: accountType,
          index: 0,
          phone: accountType === 'personal' ? profileData?.userProfile?.phoneNumber : undefined,
          category: serverAcc.business?.category,
          avatar,
          algorandAddress: '',
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
            createdAt: serverAcc.business.createdAt || new Date().toISOString(),
          } : undefined,
        };
        return convertedAccount;
      });
    // Sort accounts: personal first, then business by index
    return converted.sort((a, b) => {
      const aPriority = a.type === 'personal' ? 0 : 1;
      const bPriority = b.type === 'personal' ? 0 : 1;
      if (aPriority !== bPriority) return aPriority - bPriority;
      return a.index - b.index;
    });
  }, [profileData?.userProfile?.phoneNumber]);

  const loadAccounts = useCallback(async () => {
    try {
      setIsLoading(true);
      // Ensure we have a fresh, finalized access token before reading/using server data
      try { await waitForAuthReady(); } catch { }

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
      const convertedAccounts: StoredAccount[] = dedupeById(convertServerAccounts(serverAccounts));
      setAccounts(convertedAccounts);

      // Get active account context BEFORE deciding to create default account
      const activeContext = await authService.getActiveAccountContext();

      // If no server accounts, create a temporary default personal account so UI isn't blank
      if (convertedAccounts.length === 0) {
        console.log('useAccountManager - No server accounts found, creating temporary default personal account for display');

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
        // Pass explicit context to avoid drift
        const currentAddress = await authService.getAlgorandAddress({
          type: active.type,
          index: active.index,
          businessId: active.business?.id
        });
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
        // As a safety, ensure we still have a valid activeAccount selection
        await ensureActiveAccountFrom(convertedAccounts);
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
  }, [authService, accountManager, serverAccountsData, profileData, dedupeById, ensureActiveAccountFrom]);

  /* MOVED HERE TO FIX HOISTING ISSUE */
  const refreshAccounts = useCallback(async () => {
    try {
      console.log('refreshAccounts: forcing network fetch of userAccounts');
      // Ensure tokens are fresh/finalized before forcing any network fetch
      try { await waitForAuthReady(); } catch { }
      // Seed fast placeholder into AccountContext so UI never empties
      try {
        const ctx = await authService.getActiveAccountContext();
        const seedName = ctx.type === 'business'
          ? (profileData?.businessProfile?.name || 'Negocio')
          : (profileData?.userProfile?.firstName || profileData?.userProfile?.username || 'Personal');
        const seedAvatar = (seedName || 'N').charAt(0).toUpperCase();
        const seedId = ctx.type === 'business' && ctx.businessId
          ? `business_${ctx.businessId}_${ctx.index}`
          : `personal_${ctx.index}`;
        const seed: StoredAccount = {
          id: seedId,
          name: seedName,
          type: ctx.type,
          index: ctx.index,
          phone: ctx.type === 'personal' ? profileData?.userProfile?.phoneNumber : undefined,
          category: profileData?.businessProfile?.category,
          avatar: seedAvatar,
          algorandAddress: '',
          createdAt: new Date().toISOString(),
          isActive: true,
        } as StoredAccount;
        setAccounts(prev => (prev.length === 0 ? [seed] : prev));
      } catch { }
      const { GET_USER_ACCOUNTS } = await import('../apollo/queries');

      // First attempt
      const result1 = await apolloClient.query({
        query: GET_USER_ACCOUNTS,
        fetchPolicy: 'no-cache',
        errorPolicy: 'all',
        context: { fetchOptions: { cache: 'no-store' } as any, skipProactiveRefresh: true },
      });
      const list1 = result1?.data?.userAccounts || [];
      console.log('refreshAccounts: first result count =', list1.length);
      if ((result1 as any)?.errors?.length) {
        console.warn('GET_USER_ACCOUNTS errors:', (result1 as any).errors.map((e: any) => e.message));
      }

      let serverAccounts = list1;
      if (serverAccounts.length === 0) {
        // Retry quickly once to beat any just-switched-context race
        await new Promise((r) => setTimeout(r, 300));
        const result2 = await apolloClient.query({
          query: GET_USER_ACCOUNTS,
          fetchPolicy: 'no-cache',
          errorPolicy: 'all',
          context: { fetchOptions: { cache: 'no-store' } as any, skipProactiveRefresh: true },
        });
        const list2 = result2?.data?.userAccounts || [];
        console.log('refreshAccounts: retry result count =', list2.length);
        if ((result2 as any)?.errors?.length) {
          console.warn('GET_USER_ACCOUNTS retry errors:', (result2 as any).errors.map((e: any) => e.message));
        }
        serverAccounts = list2;
      }

      const converted = dedupeById(convertServerAccounts(serverAccounts));
      console.log('refreshAccounts: converted accounts =', converted.map(a => a.id));

      // Always provide at least one safe placeholder so header/menu never disappears.
      // If we have a business profile available, include it too so the menu shows both entries.
      if (converted.length > 0) {
        setAccounts(converted);
        try {
          await ensureActiveAccountFrom(converted);
        } catch { }
      } else {
        const personalName = profileData?.userProfile?.firstName || profileData?.userProfile?.username || 'Personal';
        const personalAvatar = (personalName || 'P').charAt(0).toUpperCase();
        const placeholders: StoredAccount[] = [
          {
            id: 'personal_0',
            name: personalName,
            type: 'personal',
            index: 0,
            phone: profileData?.userProfile?.phoneNumber || undefined,
            category: undefined,
            avatar: personalAvatar,
            algorandAddress: '',
            createdAt: new Date().toISOString(),
            isActive: true,
          }
        ];
        const bp = (profileData as any)?.businessProfile;
        if (bp?.id && bp?.name) {
          placeholders.push({
            id: `business_${bp.id}_0`,
            name: bp.name,
            type: 'business',
            index: 0,
            phone: undefined,
            category: bp.category,
            avatar: (bp.name || 'N').charAt(0).toUpperCase(),
            algorandAddress: '',
            createdAt: new Date().toISOString(),
            isActive: true,
          } as StoredAccount);
        }
        setAccounts(prev => (prev.length > 0 ? prev : placeholders));
        try {
          await ensureActiveAccountFrom(placeholders);
        } catch { }
      }
    } catch (error) {
      console.error('Error refreshing accounts from server:', error);
    }
  }, [apolloClient, convertServerAccounts, profileData?.userProfile?.firstName, profileData?.userProfile?.username, profileData?.userProfile?.phoneNumber, dedupeById, ensureActiveAccountFrom]);

  // Load accounts on mount and when server data changes
  useEffect(() => {
    if (authGatePassed && isAuthenticated && !authLoading) {
      // Kick a manual refresh as the single source of truth
      refreshAccounts();
    }
  }, [authGatePassed, isAuthenticated, authLoading, refreshAccounts]);

  // Late-arriving business profile: if we only have personal (or nothing), add a business placeholder
  useEffect(() => {
    if (!isAuthenticated) return;
    const bp: any = (profileData as any)?.businessProfile;
    if (!bp?.id || !bp?.name) return;
    setAccounts(prev => {
      const hasBusiness = prev.some(a => a.type === 'business');
      if (hasBusiness) return prev;
      if (prev.length > 1) return prev; // already populated sufficiently
      const placeholder = {
        id: `business_${bp.id}_0`,
        name: bp.name,
        type: 'business' as const,
        index: 0,
        phone: undefined,
        category: bp.category,
        avatar: (bp.name || 'N').charAt(0).toUpperCase(),
        algorandAddress: '',
        createdAt: new Date().toISOString(),
        isActive: true,
      } as StoredAccount;
      return [...prev, placeholder];
    });
    (async () => {
      try {
        const ctx = await authService.getActiveAccountContext();
        if (ctx.type === 'business' && ctx.businessId) {
          const expectedId = `business_${ctx.businessId}_${ctx.index}`;
          // Pass context explicitly
          const addr = await authService.getAlgorandAddress(ctx);
          setActiveAccount(prev => prev && prev.id === expectedId ? prev : ({
            id: expectedId,
            name: bp.name,
            type: 'business',
            index: ctx.index,
            phone: undefined,
            category: bp.category,
            avatar: (bp.name || 'N').charAt(0).toUpperCase(),
            algorandAddress: addr ?? '',
            createdAt: new Date().toISOString(),
            isActive: true,
          } as StoredAccount));
        }
      } catch { }
    })();
  }, [isAuthenticated, profileData?.businessProfile?.id, profileData?.businessProfile?.name, profileData?.businessProfile?.category]);

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

  // Whenever JWT account context changes (via AuthContext), force-refresh accounts from server
  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      console.log('useAccountManager - accountContextTick changed, refreshing accounts');
      refreshAccounts();
    }
  }, [accountContextTick, isAuthenticated, authLoading, refreshAccounts]);

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
        // Avoid resetStore() during in-flight queries (causes invariant error)
        try {
          apolloClient.stop(); // stop polls/in-flight operations
          await apolloClient.clearStore(); // clear cache without auto-refetch
          apolloClient.reFetchObservableQueries(); // restart and refetch active observers
          console.log('useAccountManager - Apollo store cleared after account switch');
        } catch (error) {
          console.log('useAccountManager - Error clearing Apollo store:', error);
          // Fallback to cache eviction
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
        // Pass explicit context for the NEW active account
        const computedAddress = await authService.getAlgorandAddress({
          type: newActiveAccount.type,
          index: newActiveAccount.index,
          businessId: newActiveAccount.business?.id
        });
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



  const syncWithServer = useCallback(async (serverAccounts: any[]) => {
    try {
      // Convert and populate context immediately
      const converted = convertServerAccounts(serverAccounts || []);
      if (converted.length > 0) {
        setAccounts(converted);
        try { await ensureActiveAccountFrom(converted); } catch { }
      } else {
        // Maintain at least a minimal placeholder
        setAccounts(prev => prev.length > 0 ? prev : [
          {
            id: 'personal_0',
            name: profileData?.userProfile?.firstName || profileData?.userProfile?.username || 'Personal',
            type: 'personal',
            index: 0,
            phone: profileData?.userProfile?.phoneNumber || undefined,
            category: undefined,
            avatar: (profileData?.userProfile?.firstName || profileData?.userProfile?.username || 'P').charAt(0).toUpperCase(),
            algorandAddress: '',
            createdAt: new Date().toISOString(),
            isActive: true,
          }
        ]);
      }
    } catch (error) {
      console.error('Error syncing with server:', error);
      throw error;
    }
  }, [convertServerAccounts, authService, profileData?.userProfile?.firstName, profileData?.userProfile?.username, profileData?.userProfile?.phoneNumber]);

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
