import Keychain from 'react-native-keychain';

export type AccountType = 'personal' | 'business';

export interface AccountContext {
  type: AccountType;
  index: number;
}

export interface StoredAccount {
  id: string;
  type: AccountType;
  index: number;
  name: string;
  avatar: string;
  phone?: string;
  category?: string;
  suiAddress?: string;
  createdAt: string;
  isActive: boolean;
}

const ACCOUNT_KEYCHAIN_SERVICE = 'com.confio.accounts';

/**
 * Account Manager for handling multi-account functionality
 * Supports personal and business accounts with indices
 */
export class AccountManager {
  private static instance: AccountManager;

  private constructor() {}

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
   */
  public parseAccountId(accountId: string): AccountContext {
    // Handle empty or invalid account ID
    if (!accountId || accountId.trim() === '') {
      throw new Error(`Invalid account ID format: empty or null value`);
    }

    const [type, indexStr] = accountId.split('_');
    const index = parseInt(indexStr, 10);
    
    if (!type || isNaN(index) || (type !== 'personal' && type !== 'business')) {
      throw new Error(`Invalid account ID format: "${accountId}" (expected format: "personal_0" or "business_0")`);
    }
    
    return {
      type: type as AccountType,
      index
    };
  }

  /**
   * Get the currently active account context
   * Defaults to personal_0 if no active account is set
   */
  public async getActiveAccountContext(): Promise<AccountContext> {
    try {
      console.log('AccountManager - getActiveAccountContext: retrieving from Keychain');
      
      const credentials = await Keychain.getGenericPassword({
        service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`
      });

      if (credentials === false) {
        console.log('AccountManager - No active account found in Keychain, returning default');
        // No active account set, return default
        return this.getDefaultAccountContext();
      }

      const activeAccountId = credentials.password;
      
      console.log('AccountManager - Retrieved active account ID from Keychain:', activeAccountId);
      
      // Check if the account ID is empty or invalid
      if (!activeAccountId || activeAccountId.trim() === '') {
        console.log('AccountManager - Empty active account ID found, returning default');
        return this.getDefaultAccountContext();
      }

      const context = this.parseAccountId(activeAccountId);
      console.log('AccountManager - Parsed active account context:', {
        accountId: activeAccountId,
        contextType: context.type,
        contextIndex: context.index
      });
      
      return context;
    } catch (error) {
      console.error('Error getting active account context:', error);
      // Return default on error
      return this.getDefaultAccountContext();
    }
  }

  /**
   * Set the active account context
   */
  public async setActiveAccountContext(context: AccountContext): Promise<void> {
    try {
      const accountId = this.generateAccountId(context.type, context.index);
      
      console.log('AccountManager - setActiveAccountContext:', {
        contextType: context.type,
        contextIndex: context.index,
        generatedAccountId: accountId
      });
      
      await Keychain.setGenericPassword(
        'account_data',
        accountId,
        {
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      
      console.log('AccountManager - Active account context stored in Keychain');
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
    console.log('AccountManager - Starting cleanup of corrupted data');
    
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
              const parsed = JSON.parse(credentials.password);
              console.log(`AccountManager - Valid account data found for ${accountId}:`, {
                type: parsed.type,
                index: parsed.index,
                name: parsed.name
              });
            } catch (parseError) {
              console.log(`AccountManager - Corrupted data found for ${accountId}, removing...`);
              console.log(`AccountManager - Raw data: "${credentials.password}"`);
              
              // Remove the corrupted entry
              await Keychain.setGenericPassword(
                'account_data',
                '',
                {
                  service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`,
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                }
              );
            }
          }
        } catch (error) {
          // Account doesn't exist, continue
          console.log(`AccountManager - No data found for ${accountId}`);
        }
      }
      
      console.log('AccountManager - Cleanup completed');
    } catch (error) {
      console.error('AccountManager - Error during cleanup:', error);
    }
  }

  /**
   * Get all stored accounts
   */
  public async getStoredAccounts(): Promise<StoredAccount[]> {
    console.log('AccountManager - getStoredAccounts: starting to retrieve accounts');
    
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
              console.log(`AccountManager - No account found for ${accountId}`);
              break;
            }
            
            if (!credentials.password) {
              console.log(`AccountManager - Empty password for ${accountId}, skipping`);
              index++;
              continue;
            }
            
            // Try to parse the JSON data
            let account: StoredAccount;
            try {
              account = JSON.parse(credentials.password) as StoredAccount;
            } catch (parseError) {
              console.log(`AccountManager - Corrupted data for ${accountId}, removing and skipping:`, parseError);
              console.log(`AccountManager - Raw data: "${credentials.password}"`);
              
              // Remove the corrupted entry
              await Keychain.setGenericPassword(
                'account_data',
                '',
                {
                  service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`,
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                }
              );
              
              index++;
              continue;
            }
            
            // Validate the parsed account data
            if (!account.id || !account.type || typeof account.index !== 'number' || !account.name) {
              console.log(`AccountManager - Invalid account data for ${accountId}, removing:`, account);
              
              // Remove the invalid entry
              await Keychain.setGenericPassword(
                'account_data',
                '',
                {
                  service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`,
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                }
              );
              
              index++;
              continue;
            }
            
            console.log(`AccountManager - Found valid account: ${accountId}`, {
              accountType: account.type,
              accountIndex: account.index,
              accountName: account.name
            });
            accounts.push(account);
            index++;
          } catch (error) {
            // Account doesn't exist or error occurred, move to next
            console.log(`AccountManager - Error retrieving account ${accountId}:`, error);
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

      console.log('AccountManager - getStoredAccounts: retrieved accounts:', {
        totalCount: sortedAccounts.length,
        accounts: sortedAccounts.map(acc => ({ id: acc.id, type: acc.type, index: acc.index, name: acc.name }))
      });

      return sortedAccounts;
    } catch (error) {
      console.error('Error getting stored accounts:', error);
      return [];
    }
  }

  /**
   * Store an account
   */
  public async storeAccount(account: StoredAccount): Promise<void> {
    try {
      console.log('AccountManager - storeAccount: storing account:', {
        id: account.id,
        type: account.type,
        index: account.index,
        name: account.name
      });
      
      const accountJson = JSON.stringify(account);
      console.log('AccountManager - storeAccount: JSON data to store:', accountJson);
      
      // Try a different approach - use the account ID as the service name
      await Keychain.setGenericPassword(
        'account_data',
        accountJson,
        {
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_${account.id}`,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      
      console.log('AccountManager - storeAccount: account stored successfully');
      
      // Verify the storage by immediately retrieving it
      try {
        const storedCredentials = await Keychain.getGenericPassword({
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_${account.id}`
        });
        
        if (storedCredentials && storedCredentials.password) {
          console.log('AccountManager - storeAccount: verification - stored data:', storedCredentials.password);
          
          // Try to parse it to make sure it's valid JSON
          const parsed = JSON.parse(storedCredentials.password);
          console.log('AccountManager - storeAccount: verification - parsed successfully:', {
            id: parsed.id,
            type: parsed.type,
            index: parsed.index,
            name: parsed.name
          });
        } else {
          console.log('AccountManager - storeAccount: verification - no data found after storage');
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
    
    console.log('AccountManager - getNextAvailableIndex:', {
      requestedType: type,
      totalAccounts: accounts.length,
      personalAccounts: accounts.filter(acc => acc.type === 'personal').length,
      businessAccounts: accounts.filter(acc => acc.type === 'business').length,
      allAccounts: accounts.map(acc => ({ id: acc.id, type: acc.type, index: acc.index }))
    });
    
    if (type === 'personal') {
      // Only allow 1 personal account (index 0)
      const personalAccounts = accounts.filter(acc => acc.type === 'personal');
      if (personalAccounts.length > 0) {
        console.log('AccountManager - Personal account already exists:', personalAccounts[0]);
        throw new Error('Only one personal account is allowed per user');
      }
      console.log('AccountManager - No personal account found, returning index 0');
      return 0;
    } else {
      // For business accounts, start from 0 and increment
      const businessAccounts = accounts.filter(acc => acc.type === 'business');
      
      if (businessAccounts.length === 0) {
        console.log('AccountManager - No business accounts found, returning index 0');
        return 0;
      }
      
      const maxIndex = Math.max(...businessAccounts.map(acc => acc.index));
      console.log('AccountManager - Business accounts found, returning index:', maxIndex + 1);
      return maxIndex + 1;
    }
  }

  /**
   * Create a new account
   * Automatically determines account type: personal if no accounts exist, business otherwise
   */
  public async createAccount(
    type: AccountType,
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ): Promise<StoredAccount> {
    const accounts = await this.getStoredAccounts();
    
    // If no accounts exist, force type to be personal
    if (accounts.length === 0) {
      type = 'personal';
    } else {
      // If accounts exist, force type to be business
      type = 'business';
    }
    
    const index = await this.getNextAvailableIndex(type);
    const id = this.generateAccountId(type, index);
    
    const account: StoredAccount = {
      id,
      type,
      index,
      name,
      avatar,
      phone,
      category,
      createdAt: new Date().toISOString(),
      isActive: false
    };

    await this.storeAccount(account);
    return account;
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
      console.log('AccountManager - deleteAccount: deleting account:', accountId);
      
      // Delete the specific account by setting it to empty string
      await Keychain.setGenericPassword(
        'account_data',
        '',
        {
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_${accountId}`,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      
      console.log('AccountManager - deleteAccount: account deleted successfully:', accountId);
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
      console.log('AccountManager - clearAllAccounts: starting cleanup');
      
      // Clear active account context
      await Keychain.setGenericPassword(
        'account_data',
        '',
        {
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      
      // Clear all stored accounts by iterating through them
      const accounts = await this.getStoredAccounts();
      console.log('AccountManager - clearAllAccounts: found accounts to clear:', accounts.length);
      
      for (const account of accounts) {
        console.log('AccountManager - clearAllAccounts: clearing account:', account.id);
        await this.deleteAccount(account.id);
      }
      
      console.log('AccountManager - clearAllAccounts: cleanup completed');
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
      console.log('AccountManager - resetActiveAccount: resetting active account');
      
      // Set empty string to clear the active account
      await Keychain.setGenericPassword(
        'account_data',
        '',
        {
          service: `${ACCOUNT_KEYCHAIN_SERVICE}_active`,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      
      console.log('AccountManager - resetActiveAccount: active account reset successfully');
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
   * This should only be called after proper zkLogin authentication
   */
  public async initializeDefaultAccount(): Promise<StoredAccount | null> {
    console.log('AccountManager - initializeDefaultAccount: starting initialization');
    
    // First, clean up any corrupted data
    await this.cleanupCorruptedData();
    
    const accounts = await this.getStoredAccounts();
    console.log('AccountManager - initializeDefaultAccount: accounts after cleanup:', {
      count: accounts.length,
      accounts: accounts.map(acc => ({ id: acc.id, type: acc.type, index: acc.index, name: acc.name }))
    });
    
    if (accounts.length === 0) {
      console.log('AccountManager - initializeDefaultAccount: no accounts found, returning null');
      console.log('AccountManager - Note: Default accounts should only be created after proper zkLogin authentication');
      return null;
    }
    
    console.log('AccountManager - initializeDefaultAccount: returning first existing account:', {
      id: accounts[0].id,
      type: accounts[0].type,
      index: accounts[0].index,
      name: accounts[0].name
    });
    
    // Return the first account (should be personal_0)
    return accounts[0];
  }
} 