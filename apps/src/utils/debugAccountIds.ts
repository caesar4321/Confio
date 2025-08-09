/**
 * Debug utility to check account IDs and their consistency
 */
import { AccountManager } from './accountManager';
import { AuthService } from '../services/authService';
import * as Keychain from 'react-native-keychain';

export async function debugAccountIds() {
  console.log('========================================');
  console.log('🔍 DEBUG: Account IDs and Storage Keys');
  console.log('========================================\n');
  
  const accountManager = AccountManager.getInstance();
  const authService = AuthService.getInstance();
  
  try {
    // Get all stored accounts
    const accounts = await accountManager.getStoredAccounts();
    console.log(`📦 Found ${accounts.length} stored accounts:\n`);
    
    for (const account of accounts) {
      console.log(`\n--- Account: ${account.name} ---`);
      console.log(`ID: ${account.id}`);
      console.log(`Type: ${account.type}`);
      console.log(`Index: ${account.index}`);
      
      if (account.business) {
        console.log(`Business ID: ${account.business.id}`);
        console.log(`Business Name: ${account.business.name}`);
      }
      
      // Parse the account ID to check format
      try {
        const parsed = accountManager.parseAccountId(account.id);
        console.log('Parsed context:', {
          type: parsed.type,
          index: parsed.index,
          businessId: parsed.businessId
        });
        
        // Check what cache key would be generated for this account
        let algoAddressCacheKey: string;
        if (parsed.type === 'business' && parsed.businessId) {
          algoAddressCacheKey = `algo_address_business_${parsed.businessId}_${parsed.index}`;
        } else {
          algoAddressCacheKey = `algo_address_${parsed.type}_${parsed.index}`;
        }
        console.log(`Expected Algo address key: ${algoAddressCacheKey}`);
        
        // Check if an address exists with this key
        try {
          const credentials = await Keychain.getGenericPassword({
            service: 'com.confio.algorand.addresses',
            username: algoAddressCacheKey
          });
          
          if (credentials && credentials.password) {
            console.log(`✅ Has stored address: ${credentials.password}`);
          } else {
            console.log('❌ No stored address');
          }
        } catch (e) {
          console.log('❌ No stored address (error)');
        }
        
      } catch (parseError) {
        console.error(`❌ Failed to parse account ID: ${parseError}`);
      }
    }
    
    // Check active account
    console.log('\n\n📍 Active Account Context:');
    const activeContext = await accountManager.getActiveAccountContext();
    console.log('Active context:', activeContext);
    
    // Generate the expected account ID for the active context
    let expectedAccountId: string;
    if (activeContext.type === 'business' && activeContext.businessId) {
      expectedAccountId = `business_${activeContext.businessId}_${activeContext.index}`;
    } else {
      expectedAccountId = `${activeContext.type}_${activeContext.index}`;
    }
    console.log(`Expected account ID: ${expectedAccountId}`);
    
    // Find the matching account
    const activeAccount = accounts.find(acc => acc.id === expectedAccountId);
    if (activeAccount) {
      console.log('✅ Active account found:', activeAccount.name);
    } else {
      console.log('❌ Active account not found in stored accounts!');
      console.log('Available account IDs:', accounts.map(a => a.id));
    }
    
  } catch (error) {
    console.error('Error in debugAccountIds:', error);
  }
}

/**
 * Fix account IDs to ensure they include business IDs
 */
export async function fixAccountIds() {
  console.log('========================================');
  console.log('🔧 FIXING: Account IDs with Business IDs');
  console.log('========================================\n');
  
  const accountManager = AccountManager.getInstance();
  
  try {
    // Get all stored accounts
    const accounts = await accountManager.getStoredAccounts();
    console.log(`Found ${accounts.length} accounts to check\n`);
    
    for (const account of accounts) {
      if (account.type === 'business' && account.business?.id) {
        // Check if the account ID includes the business ID
        const expectedId = `business_${account.business.id}_${account.index}`;
        
        if (account.id !== expectedId) {
          console.log(`\n❌ Account ID mismatch for ${account.name}:`);
          console.log(`   Current ID: ${account.id}`);
          console.log(`   Expected ID: ${expectedId}`);
          console.log(`   Business ID: ${account.business.id}`);
          
          // Update the account with the correct ID
          const updatedAccount = { ...account, id: expectedId };
          
          // Delete the old account entry
          await accountManager.deleteAccount(account.id);
          
          // Store with the new ID
          await accountManager.storeAccount(updatedAccount);
          
          console.log(`   ✅ Fixed! New ID: ${expectedId}`);
        } else {
          console.log(`✅ ${account.name} has correct ID: ${account.id}`);
        }
      }
    }
    
    console.log('\n✅ Account ID fixing complete!');
    
  } catch (error) {
    console.error('Error fixing account IDs:', error);
  }
}