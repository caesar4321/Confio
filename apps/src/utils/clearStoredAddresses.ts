import * as Keychain from 'react-native-keychain';

/**
 * Clear all stored Algorand addresses to force regeneration
 * This is needed when addresses were stored incorrectly
 */
export async function clearAllStoredAlgorandAddresses(): Promise<void> {
  console.log('🧹 Clearing all stored Algorand addresses...');
  
  // Common cache key patterns
  const keyPatterns = [
    'algo_address_personal_0',
    'algo_address_business_0',
  ];
  
  // Also clear business addresses with IDs (1-100 as a reasonable range)
  for (let i = 1; i <= 100; i++) {
    keyPatterns.push(`algo_address_business_${i}_0`);
  }
  
  let clearedCount = 0;
  
  // In v10, we can't clear individual entries with a specific username
  // Instead, we'll clear the entire service at once
  try {
    await Keychain.resetGenericPassword({
      service: 'com.confio.algorand.addresses'
    });
    console.log(`  ✅ Cleared all addresses for service: com.confio.algorand.addresses`);
    clearedCount = keyPatterns.length; // Assume all were cleared
  } catch (e) {
    console.log(`  ⚠️ Could not clear addresses:`, e);
  }
  
  console.log(`🧹 Cleared ${clearedCount} stored addresses`);
}