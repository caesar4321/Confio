import * as Keychain from 'react-native-keychain';
import { AccountType } from '../types';

/**
 * Clear all stored Algorand addresses to force regeneration
 * This is needed when addresses were stored incorrectly
 */
export async function clearAllStoredAlgorandAddresses(accounts?: AccountType[]): Promise<void> {
  console.log('🧹 Clearing all stored Algorand addresses...');
  
  const keyPatterns: string[] = [];
  
  if (accounts && accounts.length > 0) {
    // Clear only the accounts that actually exist
    for (const account of accounts) {
      if (account.accountType === 'personal') {
        keyPatterns.push(`algo_address_personal_${account.accountIndex}`);
      } else if (account.accountType === 'business' && account.business?.id) {
        keyPatterns.push(`algo_address_business_${account.business.id}_${account.accountIndex}`);
      }
    }
  } else {
    // Fallback: clear common patterns if no accounts provided
    // Most users have 1 personal and 0-3 business accounts
    keyPatterns.push('algo_address_personal_0');
    // Check up to 10 business accounts as a reasonable fallback
    for (let i = 1; i <= 10; i++) {
      keyPatterns.push(`algo_address_business_${i}_0`);
    }
  }

  let cleared = 0;
  for (const key of keyPatterns) {
    const service = `com.confio.algorand.addresses.${key}`;
    try {
      await Keychain.resetGenericPassword({ service });
      cleared += 1;
      console.log(`  Cleared: ${service}`);
    } catch {
      // Silently ignore - the key might not exist
    }
  }

  console.log(`🧹 Cleared ${cleared} stored addresses`);
}
