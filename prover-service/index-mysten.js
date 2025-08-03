import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import fetch from 'node-fetch';

// Load environment variables
dotenv.config();

const app = express();
const port = process.env.PORT || 3001;
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Mysten's external zkLogin prover URL
const MYSTEN_PROVER_URL = 'https://prover-dev.mystenlabs.com/v1';

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    mode: 'mysten-external',
    timestamp: new Date().toISOString()
  });
});

// Main proof generation endpoint - proxy to Mysten's prover
app.post('/generate-proof', async (req, res) => {
  try {
    const {
      jwt,
      extendedEphemeralPublicKey,
      maxEpoch,
      randomness,
      salt,
      keyClaimName,
      audience
    } = req.body;

    // Log request (with sensitive data truncated)
    console.log('📥 Proof generation request:', {
      jwt: jwt ? jwt.substring(0, 20) + '...' : 'undefined',
      extendedEphemeralPublicKey: extendedEphemeralPublicKey ? '✓' : '✗',
      maxEpoch,
      randomness: randomness ? '✓' : '✗',
      salt: salt ? '✓' : '✗',
      keyClaimName,
      audience
    });

    // Validate required fields
    const missingFields = [];
    if (!jwt) missingFields.push('jwt');
    if (!extendedEphemeralPublicKey) missingFields.push('extendedEphemeralPublicKey');
    if (!maxEpoch) missingFields.push('maxEpoch');
    if (!randomness) missingFields.push('randomness');
    if (!salt) missingFields.push('salt');
    
    if (missingFields.length > 0) {
      throw new Error(`Missing required fields: ${missingFields.join(', ')}`);
    }

    console.log('🔐 Forwarding to Mysten zkLogin prover...');
    const startTime = Date.now();

    // Forward request to Mysten's prover
    const response = await fetch(MYSTEN_PROVER_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        jwt,
        extendedEphemeralPublicKey,
        maxEpoch,
        randomness,
        salt,
        keyClaimName: keyClaimName || 'sub',
        // Note: Mysten's prover doesn't use the audience parameter
      }),
    });

    const responseText = await response.text();
    const duration = Date.now() - startTime;

    if (!response.ok) {
      console.error('❌ Mysten prover error:', response.status, responseText);
      return res.status(response.status).json({
        error: 'Proof generation failed',
        details: responseText,
        code: 'MYSTEN_PROVER_ERROR'
      });
    }

    const result = JSON.parse(responseText);
    console.log(`✅ Proof generated successfully in ${duration}ms`);

    // Return in the expected format
    res.json({ 
      proof: result,
      mode: 'mysten-external',
      duration_ms: duration
    });

  } catch (error) {
    console.error('❌ Request error:', error);
    res.status(400).json({
      error: error.message,
      code: 'REQUEST_ERROR'
    });
  }
});

// Start server
app.listen(port, () => {
  console.log(`\n🚀 zkLogin Prover Service (Mysten External) listening on port ${port}`);
  console.log('✅ Using Mysten\'s external zkLogin prover');
  console.log('   Works with standard OAuth providers (Google, Facebook, Twitch)');
  console.log('   Note: Apple OAuth via Firebase may not work due to nonce limitations');
  console.log(`\n📡 Endpoints:`);
  console.log(`   POST http://localhost:${port}/generate-proof`);
  console.log(`   GET  http://localhost:${port}/health`);
});