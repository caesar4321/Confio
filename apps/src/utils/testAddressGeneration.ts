/**
 * Test utility to verify that different accounts generate different addresses
 */

import { generateClientSalt, deriveDeterministicAlgorandKey } from '../services/secureDeterministicWallet';

export function testAddressGeneration() {
  console.log('========================================');
  console.log('Testing Address Generation for Different Accounts');
  console.log('========================================\n');
  
  // Test parameters
  const issuer = 'https://accounts.google.com';
  const subject = '110463609049583555194'; // Example Google OAuth subject
  const audience = 'test-client-id';
  const idToken = 'dummy-token';
  const provider = 'google' as const;
  const network = 'mainnet' as const;
  
  // Test 1: Personal Account (Index 0)
  console.log('1. Personal Account (Index 0)');
  const personalSalt = generateClientSalt(issuer, subject, audience, 'personal', 0);
  console.log('   Salt:', personalSalt.substring(0, 16) + '...');
  
  const personalWallet = deriveDeterministicAlgorandKey({
    idToken,
    clientSalt: personalSalt,
    provider,
    accountType: 'personal',
    accountIndex: 0,
    network
  });
  console.log('   Address:', personalWallet.address);
  console.log('');
  
  // Test 2: Business Account 1 (Business ID: 123)
  console.log('2. Business Account 1 (Business ID: 123)');
  const business1Salt = generateClientSalt(issuer, subject, audience, 'business', 0, '123');
  console.log('   Salt:', business1Salt.substring(0, 16) + '...');
  
  const business1Wallet = deriveDeterministicAlgorandKey({
    idToken,
    clientSalt: business1Salt,
    provider,
    accountType: 'business',
    accountIndex: 0,
    businessId: '123',
    network
  });
  console.log('   Address:', business1Wallet.address);
  console.log('');
  
  // Test 3: Business Account 2 (Business ID: 456)
  console.log('3. Business Account 2 (Business ID: 456)');
  const business2Salt = generateClientSalt(issuer, subject, audience, 'business', 0, '456');
  console.log('   Salt:', business2Salt.substring(0, 16) + '...');
  
  const business2Wallet = deriveDeterministicAlgorandKey({
    idToken,
    clientSalt: business2Salt,
    provider,
    accountType: 'business',
    accountIndex: 0,
    businessId: '456',
    network
  });
  console.log('   Address:', business2Wallet.address);
  console.log('');
  
  // Test 4: Personal Account (Index 1) - if user had multiple personal accounts
  console.log('4. Personal Account (Index 1)');
  const personal2Salt = generateClientSalt(issuer, subject, audience, 'personal', 1);
  console.log('   Salt:', personal2Salt.substring(0, 16) + '...');
  
  const personal2Wallet = deriveDeterministicAlgorandKey({
    idToken,
    clientSalt: personal2Salt,
    provider,
    accountType: 'personal',
    accountIndex: 1,
    network
  });
  console.log('   Address:', personal2Wallet.address);
  console.log('');
  
  // Verification
  console.log('========================================');
  console.log('Verification Results:');
  console.log('========================================');
  
  const addresses = [
    { name: 'Personal (0)', addr: personalWallet.address },
    { name: 'Business 123', addr: business1Wallet.address },
    { name: 'Business 456', addr: business2Wallet.address },
    { name: 'Personal (1)', addr: personal2Wallet.address }
  ];
  
  const uniqueAddresses = new Set(addresses.map(a => a.addr));
  
  if (uniqueAddresses.size === addresses.length) {
    console.log('✅ SUCCESS: All accounts have unique addresses!');
  } else {
    console.log('❌ FAILURE: Some accounts share the same address!');
    console.log('\nAddress comparison:');
    addresses.forEach((a, i) => {
      addresses.forEach((b, j) => {
        if (i < j && a.addr === b.addr) {
          console.log(`   ${a.name} === ${b.name}: ${a.addr}`);
        }
      });
    });
  }
  
  console.log('\nAll addresses:');
  addresses.forEach(a => {
    console.log(`   ${a.name}: ${a.addr}`);
  });
}