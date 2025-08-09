/**
 * Utility to clear all stored Algorand addresses
 * This ensures we start fresh and addresses are properly generated per account
 */
import * as Keychain from 'react-native-keychain';

export async function clearAllAlgorandAddresses(): Promise<void> {
  console.log('🧹 Clearing all stored Algorand addresses...');
  
  try {
    // Get all stored credentials
    const allServices = await Keychain.getAllInternetPasswordsForServer('com.confio.algorand.addresses');
    
    if (allServices && allServices.length > 0) {
      console.log(`Found ${allServices.length} stored addresses to clear`);
      
      // Clear each one
      for (const service of allServices) {
        await Keychain.resetInternetCredentials({ server: service.server });
        console.log(`Cleared address for: ${service.username}`);
      }
    }
    
    // Also try clearing with the service name directly
    await Keychain.resetGenericPassword({ service: 'com.confio.algorand.addresses' });
    
    console.log('✅ All Algorand addresses cleared');
  } catch (error) {
    console.error('Error clearing Algorand addresses:', error);
    
    // Try alternative approach - clear common patterns
    const commonKeys = [
      'algo_address_personal_0',
      'algo_address_business_1_0',
      'algo_address_business_2_0',
      'algo_address_business_3_0',
      'algo_address_business_4_0',
      'algo_address_business_5_0',
    ];
    
    for (const key of commonKeys) {
      try {
        await Keychain.resetGenericPassword({ service: 'com.confio.algorand.addresses', username: key });
        console.log(`Cleared: ${key}`);
      } catch (e) {
        // Ignore errors for non-existent keys
      }
    }
  }
}

/**
 * Debug function to list all stored Algorand addresses
 */
export async function listStoredAlgorandAddresses(): Promise<void> {
  console.log('📋 Listing all stored Algorand addresses...');
  
  try {
    // Try to retrieve addresses for common account patterns
    const patterns = [
      { key: 'algo_address_personal_0', desc: 'Personal Account' },
      { key: 'algo_address_business_1_0', desc: 'Business 1' },
      { key: 'algo_address_business_2_0', desc: 'Business 2' },
      { key: 'algo_address_business_3_0', desc: 'Business 3' },
      { key: 'algo_address_business_4_0', desc: 'Business 4' },
      { key: 'algo_address_business_5_0', desc: 'Business 5' },
    ];
    
    for (const pattern of patterns) {
      try {
        const credentials = await Keychain.getGenericPassword({
          service: 'com.confio.algorand.addresses',
          username: pattern.key
        });
        
        if (credentials && credentials.password) {
          console.log(`✓ ${pattern.desc} (${pattern.key}): ${credentials.password}`);
        }
      } catch (e) {
        // Key doesn't exist
      }
    }
  } catch (error) {
    console.error('Error listing addresses:', error);
  }
}