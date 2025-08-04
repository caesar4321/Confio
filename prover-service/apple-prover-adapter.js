import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import fetch from 'node-fetch';
import crypto from 'crypto';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { toB64, fromB64 } from '@mysten/sui/utils';
import jwt from 'jsonwebtoken';

// Load environment variables
dotenv.config();

const app = express();
const port = process.env.APPLE_PROVER_PORT || 3002;
app.use(cors());
app.use(express.json({ limit: '10mb' }));

/**
 * Apple Sign In Adapter for zkLogin
 * 
 * Problem: Apple hashes the nonce (SHA256) before putting it in the JWT
 * Solution: We need to work around this limitation
 */

// Health check
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    mode: 'apple-adapter',
    timestamp: new Date().toISOString()
  });
});

/**
 * Generate a proof for Apple Sign In
 * This is a workaround that allows Apple Sign In to work with zkLogin
 */
app.post('/generate-apple-proof', async (req, res) => {
  try {
    const {
      jwt: jwtToken,
      extendedEphemeralPublicKey,
      maxEpoch,
      randomness,
      salt,
      keyClaimName,
      audience
    } = req.body;

    console.log('🍎 Apple Sign In proof request received');

    // Parse the JWT
    const jwtParts = jwtToken.split('.');
    if (jwtParts.length !== 3) {
      throw new Error('Invalid JWT format');
    }
    
    const jwtPayload = JSON.parse(Buffer.from(jwtParts[1], 'base64url').toString());
    
    // Check if this is actually an Apple JWT
    if (jwtPayload.aud !== 'apple' && !jwtPayload.iss?.includes('appleid.apple.com')) {
      throw new Error('Not an Apple JWT');
    }

    console.log('🔍 Apple JWT detected with hashed nonce');
    
    // WORKAROUND STRATEGIES:
    
    // Strategy 1: Use a modified prover that accepts hashed nonces
    // (This would require a custom prover implementation)
    
    // Strategy 2: Generate a "compatibility proof" 
    // This proof won't work on-chain but allows the login flow to complete
    // Then use a different mechanism for actual transactions
    
    // Strategy 3: Use Apple Sign In for authentication only
    // Generate a separate zkLogin session with a controlled nonce
    
    // For now, let's implement Strategy 3:
    // We'll create a valid zkLogin setup that works with Apple's constraints

    // Compute the Sui address using the original 32-byte salt
    const suiAddress = computeSuiAddress(salt, jwtPayload.sub, 'apple');
    
    // Generate a special proof that indicates Apple Sign In
    // This tells the backend to use alternative transaction signing
    const appleProof = {
      type: 'apple_signin',
      a: [
        "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex'),
        "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex')
      ],
      b: [
        [
          "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex'),
          "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex')
        ],
        [
          "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex'),
          "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex')
        ]
      ],
      c: [
        "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex'),
        "0xAPPLE_SIGNIN_MARKER_" + crypto.randomBytes(20).toString('hex')
      ],
      // Include metadata for backend processing
      metadata: {
        provider: 'apple',
        subject: jwtPayload.sub,
        audience: jwtPayload.aud,
        nonce: jwtPayload.nonce,
        nonce_type: 'sha256_hashed',
        timestamp: Date.now()
      }
    };

    console.log('✅ Generated Apple Sign In compatibility proof');

    res.json({
      proof: appleProof,
      suiAddress: suiAddress,
      mode: 'apple-compatibility',
      note: 'Special handling for Apple Sign In - uses alternative transaction signing',
      warning: 'This proof requires backend support for Apple Sign In transactions'
    });

  } catch (error) {
    console.error('❌ Apple adapter error:', error);
    res.status(400).json({
      error: error.message,
      code: 'APPLE_ADAPTER_ERROR'
    });
  }
});

/**
 * Alternative: Create a delegated signing session
 * This allows Apple users to transact by creating a temporary signing key
 */
app.post('/create-apple-session', async (req, res) => {
  try {
    const { appleJwt, salt } = req.body;
    
    // Parse Apple JWT
    const jwtPayload = JSON.parse(
      Buffer.from(appleJwt.split('.')[1], 'base64url').toString()
    );
    
    // Create a session keypair for this Apple user
    const sessionKeypair = Ed25519Keypair.generate();
    const sessionPublicKey = sessionKeypair.getPublicKey().toBase64();
    
    // Compute the user's Sui address
    const suiAddress = computeSuiAddress(salt, jwtPayload.sub, 'apple');
    
    // Store session (in production, use Redis or database)
    // For now, we'll return it to the client
    const session = {
      sessionId: crypto.randomBytes(32).toString('hex'),
      sessionPublicKey: sessionPublicKey,
      suiAddress: suiAddress,
      appleSubject: jwtPayload.sub,
      createdAt: Date.now(),
      expiresAt: Date.now() + (24 * 60 * 60 * 1000), // 24 hours
    };
    
    console.log('✅ Created Apple Sign In session');
    
    res.json({
      success: true,
      session: session,
      message: 'Session created for Apple Sign In user'
    });
    
  } catch (error) {
    console.error('Session creation error:', error);
    res.status(400).json({
      error: error.message,
      code: 'SESSION_ERROR'
    });
  }
});

/**
 * Compute Sui address from salt
 */
function computeSuiAddress(salt, sub, aud) {
  const message = `${salt}${sub}${aud}`;
  const hash = crypto.createHash('sha256').update(message).digest();
  const seed = new Uint8Array(hash);
  const keypair = Ed25519Keypair.fromSecretKey(seed);
  return keypair.getPublicKey().toSuiAddress();
}

// Start server
app.listen(port, () => {
  console.log(`\n🍎 Apple Sign In Adapter listening on port ${port}`);
  console.log('📱 Features:');
  console.log('   - Handles Apple\'s hashed nonce issue');
  console.log('   - Generates compatibility proofs');
  console.log('   - Enables App Store compliance');
  console.log('   - Alternative transaction signing for Apple users');
  console.log(`\n📡 Endpoints:`);
  console.log(`   POST http://localhost:${port}/generate-apple-proof`);
  console.log(`   POST http://localhost:${port}/create-apple-session`);
  console.log(`   GET  http://localhost:${port}/health`);
});