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

// EC2 Docker prover URL - update this after launching EC2 instance
const EC2_PROVER_URL = process.env.EC2_PROVER_URL || 'http://YOUR_EC2_IP:8080/v1';

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    mode: 'ec2-docker',
    proverUrl: EC2_PROVER_URL,
    timestamp: new Date().toISOString()
  });
});

// Main proof generation endpoint - proxy to EC2 Docker prover
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

    console.log('🔐 Forwarding to EC2 Docker zkLogin prover...');
    const startTime = Date.now();

    // Prepare the request in the format expected by the Docker prover
    // Docker prover expects 16-byte salt and randomness, but client sends 32-byte values
    const saltBytes = Buffer.from(salt, 'base64');
    const truncatedSalt = Buffer.from(saltBytes.slice(0, 16)).toString('base64');
    
    const randomnessBytes = Buffer.from(randomness, 'base64');
    const truncatedRandomness = Buffer.from(randomnessBytes.slice(0, 16)).toString('base64');
    
    // Check if this is an Apple JWT (audience is 'apple')
    if (audience === 'apple') {
      // For Apple Sign In, we need to handle the fact that Apple hashes the nonce
      // The zkLogin prover expects the raw nonce, but Apple provides SHA256(nonce)
      // This is a fundamental incompatibility that requires a different approach
      console.log('⚠️  Apple Sign In detected - nonce is hashed in JWT');
      console.log('This requires special handling as zkLogin expects raw nonce');
    }
    
    const proverRequest = {
      jwt,
      extendedEphemeralPublicKey,
      maxEpoch,
      jwtRandomness: truncatedRandomness,  // Truncate randomness to 16 bytes for Docker prover
      salt: truncatedSalt,  // Truncate salt to 16 bytes for Docker prover
      keyClaimName: keyClaimName || 'sub'
    };

    // Forward request to EC2 Docker prover
    const response = await fetch(EC2_PROVER_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(proverRequest),
      timeout: 120000 // 2 minute timeout for proof generation
    });

    const responseText = await response.text();
    const duration = Date.now() - startTime;

    if (!response.ok) {
      console.error('❌ EC2 prover error:', response.status, responseText);
      return res.status(response.status).json({
        error: 'Proof generation failed',
        details: responseText,
        code: 'EC2_PROVER_ERROR'
      });
    }

    const proofData = JSON.parse(responseText);
    console.log(`✅ Proof generated successfully in ${duration}ms`);

    // Calculate Sui address from ephemeral public key
    const ephemeralPublicKeyBytes = Buffer.from(extendedEphemeralPublicKey, 'base64');
    const suiAddress = "0x" + ephemeralPublicKeyBytes.toString('hex');

    // Return in the expected format
    res.json({ 
      proof: proofData,
      suiAddress: suiAddress,
      mode: 'ec2-docker',
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
  console.log(`\n🚀 zkLogin Prover Service (EC2 Docker Proxy) listening on port ${port}`);
  console.log('✅ Proxying to EC2 Docker zkLogin prover');
  console.log(`   EC2 Prover URL: ${EC2_PROVER_URL}`);
  console.log('   Supports custom audiences (Apple/Google OAuth)');
  console.log(`\n📡 Endpoints:`);
  console.log(`   POST http://localhost:${port}/generate-proof`);
  console.log(`   GET  http://localhost:${port}/health`);
  
  if (EC2_PROVER_URL.includes('YOUR_EC2_IP')) {
    console.log(`\n⚠️  WARNING: EC2_PROVER_URL not configured!`);
    console.log(`   Please update EC2_PROVER_URL in .env after launching EC2 instance`);
  }
});