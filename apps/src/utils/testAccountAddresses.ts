/**
 * Test utility to verify address generation and storage for different accounts
 */
import { AuthService } from '../services/authService';
import { AccountManager } from '../services/accountManager';
import { debugListAllStoredAddresses } from './debugAlgorandAddresses';

export async function testAccountAddresses() {
  console.log('========================================');
  console.log('🧪 TESTING ACCOUNT ADDRESS SYSTEM');
  console.log('========================================\n');
  
  const authService = AuthService.getInstance();
  const accountManager = AccountManager.getInstance();
  
  try {
    // First, list current state
    console.log('📊 INITIAL STATE:\n');
    await debugListAllStoredAddresses();
    
    // Get current account
    const currentContext = await accountManager.getActiveAccountContext();
    console.log('\n📍 Current account context:', currentContext);
    
    // Test getting address for current account
    console.log('\n🔍 Testing getAlgorandAddress() for current account...');
    const currentAddress = await authService.getAlgorandAddress();
    console.log('Current account address:', currentAddress || '(empty - no address)');
    
    // Get all stored accounts to test switching
    console.log('\n📋 Getting all stored accounts...');
    const accounts = await authService.getStoredAccounts();
    console.log(`Found ${accounts.length} accounts`);
    
    // Try switching to each account and checking addresses
    console.log('\n🔄 Testing account switching and address retrieval:\n');
    
    for (const account of accounts) {
      const accountType = account.is_business ? 'business' : 'personal';
      const businessId = account.business?.id;
      const accountName = account.is_business ? account.business?.name : 'Personal Account';
      
      console.log(`\n--- Testing: ${accountName} ---`);
      console.log(`Account ID: ${account.id}`);
      console.log(`Type: ${accountType}`);
      console.log(`Business ID: ${businessId || 'N/A'}`);
      
      // Switch to this account
      try {
        await authService.switchAccount(account.id);
        console.log('✅ Switched to account');
        
        // Get the address after switching
        const address = await authService.getAlgorandAddress();
        console.log(`Address: ${address || '(empty - no address)'}`);
        
        // Verify the account context changed
        const newContext = await accountManager.getActiveAccountContext();
        console.log('New context:', {
          type: newContext.type,
          index: newContext.index,
          businessId: newContext.businessId
        });
        
      } catch (error) {
        console.error(`❌ Error switching to account ${account.id}:`, error);
      }
    }
    
    // Final state
    console.log('\n\n📊 FINAL STATE:\n');
    await debugListAllStoredAddresses();
    
    // Switch back to original account
    if (currentContext) {
      console.log('\n↩️ Switching back to original account...');
      const originalAccount = accounts.find(acc => {
        if (currentContext.type === 'personal' && !acc.is_business) {
          return true;
        }
        if (currentContext.type === 'business' && acc.is_business && 
            acc.business?.id === currentContext.businessId) {
          return true;
        }
        return false;
      });
      
      if (originalAccount) {
        await authService.switchAccount(originalAccount.id);
        console.log('✅ Switched back to original account');
      }
    }
    
  } catch (error) {
    console.error('Error in testAccountAddresses:', error);
  }
}

/**
 * Force regenerate addresses for all accounts
 * WARNING: This will clear and regenerate all addresses!
 */
export async function forceRegenerateAllAddresses() {
  console.log('⚠️ WARNING: This will regenerate ALL account addresses!');
  console.log('This requires the OAuth subject to be available.');
  
  const authService = AuthService.getInstance();
  const accountManager = AccountManager.getInstance();
  
  try {
    // Get all accounts
    const accounts = await authService.getStoredAccounts();
    console.log(`Found ${accounts.length} accounts to regenerate addresses for`);
    
    // Clear all existing addresses first
    const { clearAllAlgorandAddresses } = await import('./clearAlgorandAddresses');
    await clearAllAlgorandAddresses();
    
    // Regenerate for each account
    for (const account of accounts) {
      const accountName = account.is_business ? account.business?.name : 'Personal Account';
      console.log(`\nRegenerating address for: ${accountName}`);
      
      try {
        // Switch to account (this should trigger address generation)
        await authService.switchAccount(account.id);
        
        // Get the new address
        const address = await authService.getAlgorandAddress();
        console.log(`✅ New address: ${address || '(failed to generate)'}`);
        
      } catch (error) {
        console.error(`❌ Error regenerating for ${accountName}:`, error);
      }
    }
    
    console.log('\n✅ Address regeneration complete!');
    await debugListAllStoredAddresses();
    
  } catch (error) {
    console.error('Error in forceRegenerateAllAddresses:', error);
  }
}