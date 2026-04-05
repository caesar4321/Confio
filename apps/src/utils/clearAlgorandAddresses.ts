/**
 * Utility to clear all stored Algorand addresses
 * This ensures we start fresh and addresses are properly generated per account
 */
import * as Keychain from 'react-native-keychain';

export async function clearAllAlgorandAddresses(): Promise<void> {
  // With per-account generic password services, clear by known key patterns
  const patterns = [
    'algo_address_personal_0',
    // A reasonable range for business IDs; adjust if needed
    ...Array.from({ length: 200 }, (_, i) => `algo_address_business_${i + 1}_0`),
  ];

  let cleared = 0;
  for (const key of patterns) {
    const service = `com.confio.algorand.addresses.${key}`;
    try {
      await Keychain.resetGenericPassword({ service });
      cleared += 1;
    } catch {}
  }
}

/**
 * Debug function to list all stored Algorand addresses
 */
export async function listStoredAlgorandAddresses(): Promise<void> {
  const samples = [
    { key: 'algo_address_personal_0', desc: 'Personal Account' },
    { key: 'algo_address_business_1_0', desc: 'Business 1' },
    { key: 'algo_address_business_19_0', desc: 'Business 19' },
    { key: 'algo_address_business_2_0', desc: 'Business 2' },
  ];

  for (const s of samples) {
    const service = `com.confio.algorand.addresses.${s.key}`;
    try {
      await Keychain.getGenericPassword({ service });
    } catch {
    }
  }
}
