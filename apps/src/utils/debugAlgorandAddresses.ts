/**
 * Debug utility to list and test Algorand address storage
 */
import * as Keychain from 'react-native-keychain';
import { AccountManager } from '../services/accountManager';

export async function debugListAllStoredAddresses() {
  console.log('========================================');
  console.log('🔍 DEBUG: Listing ALL stored Algorand addresses');
  console.log('========================================\n');
  
  try {
    // List all possible account patterns
    const patterns = [
      // Personal accounts
      { key: 'algo_address_personal_0', desc: 'Personal Account (Index 0)' },
      { key: 'algo_address_personal_1', desc: 'Personal Account (Index 1)' },
      
      // Business accounts with IDs
      { key: 'algo_address_business_1_0', desc: 'Business 1 (Index 0)' },
      { key: 'algo_address_business_2_0', desc: 'Business 2 (Index 0)' },
      { key: 'algo_address_business_3_0', desc: 'Business 3 (Index 0)' },
      { key: 'algo_address_business_4_0', desc: 'Business 4 (Index 0)' },
      { key: 'algo_address_business_5_0', desc: 'Business 5 (Index 0)' },
      { key: 'algo_address_business_6_0', desc: 'Business 6 (Index 0)' },
      { key: 'algo_address_business_7_0', desc: 'Business 7 (Index 0)' },
      { key: 'algo_address_business_8_0', desc: 'Business 8 (Index 0)' },
      { key: 'algo_address_business_9_0', desc: 'Business 9 (Index 0)' },
      { key: 'algo_address_business_10_0', desc: 'Business 10 (Index 0)' },
    ];
    
    console.log('📦 Checking stored addresses with service: com.confio.algorand.addresses\n');
    
    let foundCount = 0;
    const foundAddresses: { key: string; address: string; desc: string }[] = [];
    
    for (const pattern of patterns) {
      try {
        const credentials = await Keychain.getGenericPassword({
          service: 'com.confio.algorand.addresses',
          username: pattern.key
        });
        
        if (credentials && credentials.password) {
          foundCount++;
          const address = credentials.password;
          console.log(`✅ ${pattern.desc}`);
          console.log(`   Key: ${pattern.key}`);
          console.log(`   Address: ${address}\n`);
          
          foundAddresses.push({
            key: pattern.key,
            address: address,
            desc: pattern.desc
          });
        }
      } catch (e) {
        // Key doesn't exist - this is normal
      }
    }
    
    if (foundCount === 0) {
      console.log('❌ No stored Algorand addresses found in keychain!\n');
    } else {
      console.log(`\n📊 Summary: Found ${foundCount} stored addresses\n`);
      
      // Check for duplicates
      const addressMap = new Map<string, string[]>();
      foundAddresses.forEach(item => {
        if (!addressMap.has(item.address)) {
          addressMap.set(item.address, []);
        }
        addressMap.get(item.address)!.push(item.desc);
      });
      
      const duplicates = Array.from(addressMap.entries()).filter(([_, descs]) => descs.length > 1);
      if (duplicates.length > 0) {
        console.log('⚠️ WARNING: Duplicate addresses found!');
        duplicates.forEach(([address, descs]) => {
          console.log(`\n   Address: ${address}`);
          console.log('   Used by:');
          descs.forEach(desc => console.log(`     - ${desc}`));
        });
      } else {
        console.log('✅ All stored addresses are unique!');
      }
    }
    
    // Also check current account context
    console.log('\n========================================');
    console.log('📍 Current Account Context');
    console.log('========================================\n');
    
    try {
      const accountManager = AccountManager.getInstance();
      const context = await accountManager.getActiveAccountContext();
      console.log('Active Account:', {
        type: context.type,
        index: context.index,
        businessId: context.businessId
      });
      
      // Generate expected cache key
      let expectedKey: string;
      if (context.type === 'business' && context.businessId) {
        expectedKey = `algo_address_business_${context.businessId}_${context.index}`;
      } else {
        expectedKey = `algo_address_${context.type}_${context.index}`;
      }
      console.log('Expected cache key:', expectedKey);
      
      // Check if this account has a stored address
      const found = foundAddresses.find(item => item.key === expectedKey);
      if (found) {
        console.log('✅ Active account has stored address:', found.address);
      } else {
        console.log('❌ Active account has NO stored address!');
      }
    } catch (error) {
      console.error('Error getting account context:', error);
    }
    
  } catch (error) {
    console.error('Error in debugListAllStoredAddresses:', error);
  }
}

export async function debugClearSpecificAddress(cacheKey: string) {
  console.log(`🗑️ Clearing address with key: ${cacheKey}`);
  try {
    await Keychain.resetGenericPassword({
      service: 'com.confio.algorand.addresses',
      username: cacheKey
    });
    console.log('✅ Address cleared');
  } catch (error) {
    console.error('Error clearing address:', error);
  }
}

export async function debugStoreTestAddress(cacheKey: string, address: string) {
  console.log(`📝 Storing test address with key: ${cacheKey}`);
  try {
    await Keychain.setGenericPassword(
      cacheKey,
      address,
      {
        service: 'com.confio.algorand.addresses',
        accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
      }
    );
    console.log('✅ Test address stored');
    
    // Verify it was stored
    const credentials = await Keychain.getGenericPassword({
      service: 'com.confio.algorand.addresses',
      username: cacheKey
    });
    
    if (credentials && credentials.password === address) {
      console.log('✅ Verification successful - address retrieved correctly');
    } else {
      console.log('❌ Verification failed - address not retrieved correctly');
    }
  } catch (error) {
    console.error('Error storing test address:', error);
  }
}