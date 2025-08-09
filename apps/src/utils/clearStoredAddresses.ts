import * as Keychain from 'react-native-keychain';

/**
 * Clear all stored Algorand addresses to force regeneration
 * This is needed when addresses were stored incorrectly
 */
export async function clearAllStoredAlgorandAddresses(): Promise<void> {
  console.log('🧹 Clearing all stored Algorand addresses...');
  
  // Clear per-account services introduced to avoid overwrites
  const keyPatterns: string[] = ['algo_address_personal_0'];
  for (let i = 1; i <= 200; i++) keyPatterns.push(`algo_address_business_${i}_0`);

  let cleared = 0;
  for (const key of keyPatterns) {
    const service = `com.confio.algorand.addresses.${key}`;
    try {
      await Keychain.resetGenericPassword({ service });
      cleared += 1;
      console.log(`  Cleared: ${service}`);
    } catch {}
  }

  console.log(`🧹 Cleared ${cleared} stored addresses`);
}
