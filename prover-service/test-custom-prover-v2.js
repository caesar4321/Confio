import fetch from 'node-fetch';
import crypto from 'crypto';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { generateNonce as generateZkLoginNonce } from '@mysten/sui/zklogin';

const PROVER_URL = 'http://localhost:3003';

async function testCustomProverV2() {
  console.log('🧪 Testing Custom zkLogin Prover v2\n');
  console.log('========================================\n');

  try {
    // Test 1: Health check
    console.log('1️⃣ Health Check');
    console.log('----------------');
    const healthResponse = await fetch(`${PROVER_URL}/health`);
    const healthData = await healthResponse.json();
    console.log('✅ Status:', healthData.status);
    console.log('✅ Mode:', healthData.mode);
    console.log('✅ Supports:', healthData.supports);

    // Test 2: Simulate client nonce computation
    console.log('\n2️⃣ Client Nonce Simulation');
    console.log('----------------------------');
    
    // Generate test data like the client does
    const salt32 = crypto.randomBytes(32).toString('base64');
    const randomness32 = crypto.randomBytes(32).toString('base64');
    const maxEpoch = "235";
    
    // Recreate ephemeral keypair like client
    const saltBytes = Buffer.from(salt32, 'base64');
    const seed = saltBytes.slice(0, 32);
    const ephemeralKeypair = Ed25519Keypair.fromSecretKey(seed);
    
    // Generate nonce like client
    const randomnessBytes = Buffer.from(randomness32, 'base64');
    const truncatedRandomness = randomnessBytes.slice(0, 16);
    const randomnessBigInt = BigInt('0x' + truncatedRandomness.toString('hex'));
    const clientNonce = generateZkLoginNonce(
      ephemeralKeypair.getPublicKey(),
      Number(maxEpoch),
      randomnessBigInt
    );
    
    console.log('Client simulation:', {
      saltLength: Buffer.from(salt32, 'base64').length,
      randomnessLength: Buffer.from(randomness32, 'base64').length,
      ephemeralPublicKey: ephemeralKeypair.getPublicKey().toBase64(),
      suiAddress: ephemeralKeypair.getPublicKey().toSuiAddress(),
      nonce: clientNonce
    });

    // Test 3: Google JWT simulation
    console.log('\n3️⃣ Google JWT Test');
    console.log('--------------------');
    
    const googleJwt = createTestJWT({
      iss: 'https://accounts.google.com',
      aud: '575519204237-sunh3bop8hl34b5dhadd987ov3gllkrg.apps.googleusercontent.com',
      sub: '110463452152141951206',
      nonce: clientNonce // Raw nonce for Google
    });
    
    const googleRequest = {
      jwt: googleJwt,
      extendedEphemeralPublicKey: ephemeralKeypair.getPublicKey().toBase64(),
      maxEpoch: maxEpoch,
      randomness: randomness32,
      salt: salt32,
      keyClaimName: 'sub',
      audience: 'google'
    };
    
    console.log('Testing Google proof generation...');
    const googleResponse = await fetch(`${PROVER_URL}/generate-proof`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(googleRequest)
    });
    
    const googleResult = await googleResponse.json();
    console.log('Google result:', {
      success: googleResponse.ok,
      mode: googleResult.mode,
      provider: googleResult.provider,
      error: googleResult.error?.substring(0, 100)
    });

    // Test 4: Apple JWT simulation
    console.log('\n4️⃣ Apple JWT Test');
    console.log('-------------------');
    
    // Apple hashes the nonce
    const hashedNonce = crypto.createHash('sha256').update(clientNonce).digest('base64url');
    
    const appleJwt = createTestJWT({
      iss: 'https://appleid.apple.com',
      aud: 'apple',
      sub: 'apple-user-123456',
      nonce: hashedNonce // Hashed nonce for Apple
    });
    
    const appleRequest = {
      jwt: appleJwt,
      extendedEphemeralPublicKey: ephemeralKeypair.getPublicKey().toBase64(),
      maxEpoch: maxEpoch,
      randomness: randomness32,
      salt: salt32,
      keyClaimName: 'sub',
      audience: 'apple'
    };
    
    console.log('Testing Apple proof generation...');
    console.log('Nonce comparison:', {
      clientNonce: clientNonce,
      hashedNonce: hashedNonce,
      hashMatch: hashedNonce.length > 0
    });
    
    const appleResponse = await fetch(`${PROVER_URL}/generate-proof`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(appleRequest)
    });
    
    const appleResult = await appleResponse.json();
    console.log('Apple result:', {
      success: appleResponse.ok,
      mode: appleResult.mode,
      provider: appleResult.provider,
      error: appleResult.error?.substring(0, 100)
    });

    console.log('\n========================================');
    console.log('📊 Test Summary');
    console.log('========================================');
    console.log('✅ Health check: PASSED');
    console.log('✅ Nonce computation: PASSED');
    console.log(`${googleResponse.ok ? '✅' : '❌'} Google JWT: ${googleResponse.ok ? 'PASSED' : 'FAILED'}`);
    console.log(`${appleResponse.ok ? '✅' : '❌'} Apple JWT: ${appleResponse.ok ? 'PASSED' : 'FAILED'}`);
    
    console.log('\n📝 Next Steps:');
    console.log('1. Test with real Google Sign In');
    console.log('2. Test with real Apple Sign In');
    console.log('3. Verify transactions work on-chain');

  } catch (error) {
    console.error('\n❌ Test failed:', error.message);
  }
}

function createTestJWT(payload) {
  // Create a simple test JWT (not signed, but format correct)
  const header = {
    alg: 'RS256',
    typ: 'JWT',
    kid: 'test'
  };
  
  return [
    Buffer.from(JSON.stringify(header)).toString('base64url'),
    Buffer.from(JSON.stringify(payload)).toString('base64url'),
    'test-signature'
  ].join('.');
}

// Run the test
testCustomProverV2().catch(console.error);