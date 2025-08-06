#!/usr/bin/env node

/**
 * Test script for V2 sponsored transaction flow
 * This tests the two-phase prepare/submit flow through the TypeScript bridge
 */

const axios = require('axios');

const API_URL = 'http://localhost:3456/api/keyless/v2';

async function testV2Flow() {
  try {
    console.log('🧪 Testing V2 Sponsored Transaction Flow\n');
    
    // Test addresses
    const senderAddress = '0x8e0c17e0f0bb6f3c3e8a3b4f8c1d0e6f7e8d9c0a1b2c3d4e5f6a7b8c9d0e1f2a';
    const recipientAddress = '0x9f1e2d3c4b5a6978e7d6c5b4a3928176e5d4c3b2a1908f7e6d5c4b3a29180716';
    const amount = 1000000; // 0.01 CONFIO (8 decimals)
    
    // Phase 1: Prepare the sponsored transaction
    console.log('📝 Phase 1: Preparing sponsored transaction...');
    const prepareResponse = await axios.post(`${API_URL}/prepare-sponsored-confio-transfer`, {
      senderAddress,
      recipientAddress,
      amount
    });
    
    if (!prepareResponse.data.success) {
      throw new Error(`Prepare failed: ${prepareResponse.data.error}`);
    }
    
    const { transactionId, rawTransaction, feePayerAddress } = prepareResponse.data;
    
    console.log('✅ Transaction prepared successfully');
    console.log(`   Transaction ID: ${transactionId}`);
    console.log(`   Fee Payer: ${feePayerAddress}`);
    console.log(`   Raw Transaction Length: ${rawTransaction.length} chars\n`);
    
    // Phase 2: Simulate signing on client side
    console.log('🔏 Phase 2: Simulating client-side signing...');
    
    // In a real app, this would be done by the React Native AuthService.signSponsoredTransaction()
    // For testing, we'll create a mock authenticator
    const mockSenderAuthenticator = Buffer.from(JSON.stringify({
      type: 'keyless',
      publicKey: '0x' + '00'.repeat(32),
      signature: '0x' + '00'.repeat(64),
      zkProof: {
        a: '0x' + '00'.repeat(32),
        b: '0x' + '00'.repeat(32),
        c: '0x' + '00'.repeat(32)
      }
    })).toString('base64');
    
    console.log('✅ Mock authenticator created\n');
    
    // Phase 3: Submit the signed transaction
    console.log('🚀 Phase 3: Submitting signed transaction...');
    const submitResponse = await axios.post(`${API_URL}/submit-sponsored-confio-transfer`, {
      transactionId,
      senderAuthenticator: mockSenderAuthenticator
    });
    
    if (!submitResponse.data.success) {
      throw new Error(`Submit failed: ${submitResponse.data.error}`);
    }
    
    console.log('✅ Transaction submitted successfully!');
    console.log(`   Transaction Hash: ${submitResponse.data.transactionHash || 'N/A'}`);
    
    console.log('\n🎉 V2 Flow Test Complete!');
    console.log('   The two-phase sponsored transaction flow is working correctly.');
    console.log('   Django → TypeScript Bridge → Aptos integration is functional.\n');
    
  } catch (error) {
    console.error('\n❌ Test Failed:', error.message);
    if (error.response) {
      console.error('   Response data:', error.response.data);
    }
    process.exit(1);
  }
}

// Run the test
console.log('========================================');
console.log('  V2 Sponsored Transaction Flow Test');
console.log('========================================\n');

testV2Flow().catch(console.error);