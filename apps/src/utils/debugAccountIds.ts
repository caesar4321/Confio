/**
 * Debug utility to check account IDs and their consistency
 */
import { AccountManager } from './accountManager';
import { AuthService } from '../services/authService';
import * as Keychain from 'react-native-keychain';

export async function debugAccountIds() {
  const accountManager = AccountManager.getInstance();
  AuthService.getInstance();
  
  try {
    // Get all stored accounts
    const accounts = await accountManager.getStoredAccounts();
    
    for (const account of accounts) {
      // Parse the account ID to check format
      try {
        const parsed = accountManager.parseAccountId(account.id);
        
        // Check what cache key would be generated for this account
        let algoAddressCacheKey: string;
        if (parsed.type === 'business' && parsed.businessId) {
          algoAddressCacheKey = `algo_address_business_${parsed.businessId}_${parsed.index}`;
        } else {
          algoAddressCacheKey = `algo_address_${parsed.type}_${parsed.index}`;
        }
        
        // Check if an address exists with this key
        try {
          const credentials = await Keychain.getGenericPassword({
            service: 'com.confio.algorand.addresses',
            username: algoAddressCacheKey
          });
        } catch (e) {
        }
        
      } catch (parseError) {
        console.error(`❌ Failed to parse account ID: ${parseError}`);
      }
    }
    
    // Check active account
    const activeContext = await accountManager.getActiveAccountContext();
    
    // Generate the expected account ID for the active context
    let expectedAccountId: string;
    if (activeContext.type === 'business' && activeContext.businessId) {
      expectedAccountId = `business_${activeContext.businessId}_${activeContext.index}`;
    } else {
      expectedAccountId = `${activeContext.type}_${activeContext.index}`;
    }
    
    // Find the matching account
    const activeAccount = accounts.find(acc => acc.id === expectedAccountId);
    void activeAccount;
    
  } catch (error) {
    console.error('Error in debugAccountIds:', error);
  }
}

/**
 * Fix account IDs to ensure they include business IDs
 */
export async function fixAccountIds() {
  const accountManager = AccountManager.getInstance();
  
  try {
    // Get all stored accounts
    const accounts = await accountManager.getStoredAccounts();
    
    for (const account of accounts) {
      if (account.type === 'business' && account.business?.id) {
        // Check if the account ID includes the business ID
        const expectedId = `business_${account.business.id}_${account.index}`;
        
        if (account.id !== expectedId) {
          // Update the account with the correct ID
          const updatedAccount = { ...account, id: expectedId };
          
          // Delete the old account entry
          await accountManager.deleteAccount(account.id);
          
          // Store with the new ID
          await accountManager.storeAccount(updatedAccount);
        }
      }
    }
  } catch (error) {
    console.error('Error fixing account IDs:', error);
  }
}
