import Keychain from 'react-native-keychain';

export type AccountType = 'personal' | 'business';

export interface AccountContext {
  type: AccountType;
  index: number;
  businessId?: string;
  employeeRole?: 'owner' | 'cashier' | 'manager' | 'admin';
  permissions?: {
    acceptPayments: boolean;
    viewTransactions: boolean;
    viewBalance: boolean;
    sendFunds: boolean;
    manageEmployees: boolean;
    viewBusinessAddress: boolean;
    viewAnalytics: boolean;
  };
}

export interface StoredAccount {
  id: string;
  type: AccountType;
  index: number;
  name: string;
  avatar: string;
  phone?: string;
  category?: string;
  algorandAddress?: string;
  createdAt: string;
  isActive: boolean;
  isEmployee?: boolean;
  employeeRole?: 'cashier' | 'manager' | 'admin';
  employeePermissions?: {
    acceptPayments: boolean;
    viewTransactions: boolean;
    viewBalance: boolean;
    sendFunds: boolean;
    manageEmployees: boolean;
    viewBusinessAddress: boolean;
    viewAnalytics: boolean;
  };
  employeeRecordId?: string;
  business?: {
    id: string;
    name: string;
    description?: string;
    category: string;
    businessRegistrationNumber?: string;
    address?: string;
    createdAt: string;
  };
}

const ACCOUNT_KEYCHAIN_SERVICE = 'com.confio.accounts';

/**
 * Account Manager for handling multi-account functionality
 * Supports personal and business accounts with indices
 */
export class AccountManager {
  private static instance: AccountManager;
  private cachedActiveContext: AccountContext | null = null;

  private constructor() { }

  public static getInstance(): AccountManager {
    if (!AccountManager.instance) {
      AccountManager.instance = new AccountManager();
    }
    return AccountManager.instance;
  }

  /**
   * Get the default account context (personal 0)
   */
  public getDefaultAccountContext(): AccountContext {
    return {
      type: 'personal',
      index: 0
    };
  }

  /**
   * Generate a unique account ID from type and index
   */
  public generateAccountId(type: AccountType, index: number): string {
    return `${type}_${index}`;
  }

  /**
   * Parse account ID to get type and index
   * Supports: personal_{index} and business_{businessId}_{index}
   */
  public parseAccountId(accountId: string): AccountContext {
    // Handle empty or invalid account ID
    if (!accountId || accountId.trim() === '') {
      throw new Error(`Invalid account ID format: empty or null value`);
    }

    const parts = accountId.split('_');

    if (parts.length === 2 && parts[0].toLowerCase() === 'personal') {
      // Personal format: personal_index
      const [type, indexStr] = parts;
      const index = parseInt(indexStr, 10);

      if (isNaN(index)) {
        throw new Error(`Invalid account ID format: "${accountId}" (expected format: "personal_0")`);
      }

      return {
        type: 'personal' as AccountType,
        index
      };
    } else if (parts.length === 3 && parts[0].toLowerCase() === 'business') {
      // Business format: business_businessId_index
      const [type, businessIdStr, indexStr] = parts;
      const businessId = businessIdStr;
      const index = parseInt(indexStr, 10);

      if (!businessId || isNaN(index)) {
        throw new Error(`Invalid account ID format: "${accountId}" (expected format: "business_19_0")`);
      }

      return {
        type: 'business' as AccountType,
        index,
        businessId
      };
    } else {
      throw new Error(`Invalid account ID format: "${accountId}" (expected format: "personal_0" or "business_19_0")`);
    }
  }

  /**
   * Get the currently active account context
   * Defaults to personal_0 if no active account is set
   */
  public async getActiveAccountContext(): Promise<AccountContext> {
    try {
      // Use in-memory cache to avoid repeated Keychain reads
      if (this.cachedActiveContext) {
        return this.cachedActiveContext;
      }

      const credentials = await Keychain.getGenericPassword({
        service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`
      });

      if (credentials === false) {
        // No active account set, return default
        return this.getDefaultAccountContext();
      }

      const activeAccountId = credentials.password;

      // Check if the account ID is empty or invalid
      if (!activeAccountId || activeAccountId.trim() === '') {
        return this.getDefaultAccountContext();
      }

      const context = this.parseAccountId(activeAccountId);

      this.cachedActiveContext = context;
      return this.cachedActiveContext;
    } catch (error) {
      console.error('AccountManager - Error getting active account context from Keychain:', error);
      // Return default on error, but log it as a warning so we know it happened
      return this.getDefaultAccountContext();
    }
  }

  /**
   * Set the active account context
   */
  public async setActiveAccountContext(context: AccountContext): Promise<void> {
    try {
      // Generate the full account ID including business_id for business accounts
      let accountId: string;
      if (context.type === 'business' && context.businessId) {
        accountId = `business_${context.businessId}_${context.index}`;
      } else {
        accountId = this.generateAccountId(context.type, context.index);
      }

      await Keychain.setGenericPassword(
        'account_data',
        accountId,
        {
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`,
          accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK
        }
      );

      // Update cache to reflect the latest context
      this.cachedActiveContext = context;
    } catch (error) {
      console.error('Error setting active account context:', error);
      throw error;
    }
  }

  /**
   * Clean up corrupted Keychain data
   * This method removes any corrupted account entries from the Keychain
   */
  public async cleanupCorruptedData(): Promise<void> {
    try {
      // Try to retrieve all possible account IDs that might exist
      const possibleAccountIds = [
        'personal_0',
        'business_0',
        'business_1',
        'business_2',
        'business_3',
        'business_4',
        'business_5'
      ];

      for (const accountId of possibleAccountIds) {
        try {
          const credentials = await Keychain.getGenericPassword({
            service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`
          });

          if (credentials && credentials.password) {
            // Try to parse the data to see if it's valid JSON
            try {
              JSON.parse(credentials.password);
            } catch (parseError) {
              // Remove the corrupted entry
              await Keychain.resetGenericPassword({
                service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`
              });
            }
          }
        } catch {
          // Account doesn't exist, continue
        }
      }
    } catch (error) {
      console.error('AccountManager - Error during cleanup:', error);
    }
  }

  /**
   * Get all stored accounts
   */
  public async getStoredAccounts(): Promise<StoredAccount[]> {
    try {
      const accounts: StoredAccount[] = [];

      // Try to retrieve accounts for both types
      for (const type of ['personal', 'business'] as AccountType[]) {
        let index = 0;

        while (index < 10) { // Limit to prevent infinite loops
          const accountId = this.generateAccountId(type, index);

          try {
            const credentials = await Keychain.getGenericPassword({
              service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`
            });

            if (credentials === false) {
              // No more accounts of this type
              break;
            }

            if (!credentials.password) {
              index++;
              continue;
            }

            // Try to parse the JSON data
            let account: StoredAccount;
            try {
              account = JSON.parse(credentials.password) as StoredAccount;
            } catch (parseError) {
              // Remove the corrupted entry
              await Keychain.resetGenericPassword({
                service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`
              });

              index++;
              continue;
            }

            // Validate the parsed account data
            if (!account.id || !account.type || typeof account.index !== 'number' || !account.name) {
              // Remove the invalid entry
              await Keychain.resetGenericPassword({
                service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`
              });

              index++;
              continue;
            }

            accounts.push(account);
            index++;
          } catch {
            // Account doesn't exist or error occurred, move to next
            break;
          }
        }
      }

      const sortedAccounts = accounts.sort((a, b) => {
        // Sort by type (personal first), then by index
        if (a.type !== b.type) {
          return a.type === 'personal' ? -1 : 1;
        }
        return a.index - b.index;
      });

      return sortedAccounts;
    } catch (error) {
      console.error('Error getting stored accounts:', error);
      return [];
    }
  }

  /**
   * Sync server accounts with local storage
   * This method updates local account storage with server data
   */
  public async syncServerAccounts(serverAccounts: any[]): Promise<void> {
    try {
      // Clear existing accounts
      await this.clearAllAccounts();

      // Store server accounts locally
      for (const serverAccount of serverAccounts) {
        const account: StoredAccount = {
          id: serverAccount.accountId,
          type: serverAccount.accountType,
          index: serverAccount.accountIndex,
          name: serverAccount.business?.name || `Account ${serverAccount.accountIndex}`,
          avatar: serverAccount.business?.name?.charAt(0).toUpperCase() || 'A',
          category: serverAccount.business?.category,
          algorandAddress: serverAccount.algorandAddress,
          createdAt: serverAccount.createdAt,
          isActive: false
        };

        await this.storeAccount(account);
      }

      // Set the first account as active if no active account exists
      if (serverAccounts.length > 0) {
        try {
          await this.getActiveAccountContext();
        } catch (error) {
          // No active account, set the first one
          const firstAccount = serverAccounts[0];
          await this.setActiveAccountContext({
            type: firstAccount.accountType,
            index: firstAccount.accountIndex
          });
        }
      }
    } catch (error) {
      console.error('Error syncing server accounts:', error);
      throw error;
    }
  }

  /**
   * Store an account
   */
  public async storeAccount(account: StoredAccount): Promise<void> {
    try {
      const accountJson = JSON.stringify(account);

      // Try a different approach - use the account ID as the service name
      await Keychain.setGenericPassword(
        'account_data',
        accountJson,
        {
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_${account.id}`,
          accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK
        }
      );

      // Verify the storage by immediately retrieving it
      try {
        const storedCredentials = await Keychain.getGenericPassword({
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_${account.id}`
        });

        if (storedCredentials && storedCredentials.password) {
          // Try to parse it to make sure it's valid JSON
          JSON.parse(storedCredentials.password);
        }
      } catch (verifyError) {
        console.error('AccountManager - storeAccount: verification failed:', verifyError);
      }
    } catch (error) {
      console.error('Error storing account:', error);
      throw error;
    }
  }

  /**
   * Get the next available index for a given account type
   * For personal accounts: only allow 1 (index 0)
   * For business accounts: start from 0 and increment
   */
  public async getNextAvailableIndex(type: AccountType): Promise<number> {
    const accounts = await this.getStoredAccounts();

    if (type === 'personal') {
      // Only allow 1 personal account (index 0)
      const personalAccounts = accounts.filter(acc => acc.type === 'personal');
      if (personalAccounts.length > 0) {
        throw new Error('Only one personal account is allowed per user');
      }
      return 0;
    } else {
      // For business accounts, start from 0 and increment
      const businessAccounts = accounts.filter(acc => acc.type === 'business');

      if (businessAccounts.length === 0) {
        return 0;
      }

      const maxIndex = Math.max(...businessAccounts.map(acc => acc.index));
      return maxIndex + 1;
    }
  }

  /**
   * Create a new account
   * NOTE: This method is deprecated. Account creation should be done through server mutations.
   * This method is kept for backward compatibility but should not be used for new accounts.
   */
  public async createAccount(
    type: AccountType,
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ): Promise<StoredAccount> {
    console.warn('AccountManager.createAccount is deprecated. Use server mutations for account creation.');

    // For backward compatibility, return a mock account
    // This should not be used for actual account creation
    return {
      id: 'deprecated_method',
      type: type,
      index: 0,
      name: name,
      avatar: avatar,
      phone: phone,
      category: category,
      createdAt: new Date().toISOString(),
      isActive: false
    };
  }

  /**
   * Update an existing account
   */
  public async updateAccount(accountId: string, updates: Partial<StoredAccount>): Promise<void> {
    const accounts = await this.getStoredAccounts();
    const account = accounts.find(acc => acc.id === accountId);

    if (!account) {
      throw new Error(`Account not found: ${accountId}`);
    }

    const updatedAccount = { ...account, ...updates };
    await this.storeAccount(updatedAccount);
  }

  /**
   * Delete an account
   */
  public async deleteAccount(accountId: string): Promise<void> {
    try {
      // Delete the specific account using resetGenericPassword (works on both iOS and Android)
      await Keychain.resetGenericPassword({
        service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`
      });
    } catch (error) {
      console.error('Error deleting account:', error);
      throw error;
    }
  }

  /**
   * Clear all account data (useful for sign out)
   */
  public async clearAllAccounts(): Promise<void> {
    try {
      // Clear active account context using resetGenericPassword
      await Keychain.resetGenericPassword({
        service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`
      });

      // Clear all stored accounts by iterating through them
      const accounts = await this.getStoredAccounts();

      for (const account of accounts) {
        await this.deleteAccount(account.id);
      }
    } catch (error) {
      console.error('Error clearing all accounts:', error);
      throw error;
    }
  }

  /**
   * Reset active account to default (useful for fixing corrupted data)
   */
  public async resetActiveAccount(): Promise<void> {
    try {
      // Clear the active account using resetGenericPassword
      await Keychain.resetGenericPassword({
        service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`
      });
    } catch (error) {
      console.error('Error resetting active account:', error);
      throw error;
    }
  }

  /**
   * Get account by ID
   */
  public async getAccount(accountId: string): Promise<StoredAccount | null> {
    const accounts = await this.getStoredAccounts();
    return accounts.find(acc => acc.id === accountId) || null;
  }

  /**
   * Check if an account exists
   */
  public async accountExists(accountId: string): Promise<boolean> {
    const account = await this.getAccount(accountId);
    return account !== null;
  }

  /**
   * Initialize default account if no accounts exist
   * This should only be called after proper authentication
   */
  public async initializeDefaultAccount(): Promise<StoredAccount | null> {
    // First, clean up any corrupted data
    await this.cleanupCorruptedData();

    const accounts = await this.getStoredAccounts();

    if (accounts.length === 0) {
      return null;
    }

    // Return the first account (should be personal_0)
    return accounts[0];
  }
} 
