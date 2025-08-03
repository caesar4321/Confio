import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';

// Load environment variables
dotenv.config();

const app = express();
const port = process.env.PORT || 3001;
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    mode: 'mock',
    timestamp: new Date().toISOString()
  });
});

// Main proof generation endpoint
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

    // Generate mock proof (same format as working before)
    console.warn('⚠️  Using MOCK zkLogin proof - transactions will fail on mainnet!');
    const mockProof = {
      a: [
        "0x1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2",
        "0x2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b"
      ],
      b: [
        [
          "0x3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
          "0x4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d"
        ],
        [
          "0x5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e",
          "0x6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f"
        ]
      ],
      c: [
        "0x7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a",
        "0x8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b"
      ]
    };
    
    // Log parameter sizes for debugging
    console.log('Parameter sizes:', {
      randomness_bytes: Buffer.from(randomness, 'base64').length,
      salt_bytes: Buffer.from(salt, 'base64').length
    });
    
    // Calculate Sui address from ephemeral public key (mock implementation)
    const ephemeralPublicKeyBytes = Buffer.from(extendedEphemeralPublicKey, 'base64');
    const suiAddress = "0x" + ephemeralPublicKeyBytes.toString('hex');
    
    return res.json({ 
      proof: mockProof,
      suiAddress: suiAddress,
      mode: 'mock'
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
  console.log(`\n🚀 zkLogin Prover Service (Mock) listening on port ${port}`);
  console.log('⚠️  Running in MOCK mode - proofs will not be valid on mainnet!');
  console.log('   This is for development only');
  console.log('   Deploy Docker prover on EC2 for production use');
  console.log(`\n📡 Endpoints:`);
  console.log(`   POST http://localhost:${port}/generate-proof`);
  console.log(`   GET  http://localhost:${port}/health`);
});