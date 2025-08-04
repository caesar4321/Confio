import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { zkLoginProver } from './custom-zklogin-prover.js';

// Load environment variables
dotenv.config();

const app = express();
const port = 3001;

// Enable CORS for all routes
app.use(cors());
app.use(express.json());

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    mode: process.env.USE_MOCK_PROVER === 'true' ? 'mock' : 'external',
    proverUrl: process.env.EC2_PROVER_URL || 'none',
    timestamp: new Date().toISOString(),
    saltSupport: '32-byte',
    customProver: true
  });
});

// Helper: decode base64 → Uint8Array with length validation
function b64ToBuf(s, fieldName) {
  try {
    const buf = Buffer.from(s, 'base64');
    if (buf.length !== 32) {
      throw new Error(`Expected 32 bytes for ${fieldName}, got ${buf.length}`);
    }
    return new Uint8Array(buf);
  } catch (error) {
    throw new Error(`Base64 decoding failed for ${fieldName}: ${error.message} (input: ${s})`);
  }
}

// Helper: validate JWT and extract parts
function validateJwt(jwt) {
  try {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
      throw new Error('Invalid JWT: Must have three parts');
    }
    const [header, payload, signature] = parts;
    const payloadObj = JSON.parse(Buffer.from(payload, 'base64url').toString());
    if (!payloadObj.sub || !payloadObj.aud || !payloadObj.iss) {
      throw new Error('Invalid JWT: Missing required claims (sub, aud, iss)');
    }
    return { header, payload, payloadObj };
  } catch (error) {
    throw new Error(`JWT validation failed: ${error.message}`);
  }
}

// Endpoint to generate zkLogin proof
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

    // Log the request body with sensitive data truncated
    console.log('Request body:', {
      jwt: jwt ? jwt.substring(0, 20) + '...' : 'undefined',
      extendedEphemeralPublicKey: extendedEphemeralPublicKey ? extendedEphemeralPublicKey.substring(0, 20) + '...' : 'undefined',
      maxEpoch,
      randomness: randomness ? randomness.substring(0, 20) + '...' : 'undefined',
      salt: salt ? salt.substring(0, 20) + '...' : 'undefined',
      keyClaimName,
      audience
    });

    // Validate required fields and provide specific error messages
    const missingFields = [];
    if (!jwt) missingFields.push('jwt');
    if (!extendedEphemeralPublicKey) missingFields.push('extendedEphemeralPublicKey');
    if (!maxEpoch) missingFields.push('maxEpoch');
    if (!randomness) missingFields.push('randomness');
    if (!salt) missingFields.push('salt');
    if (!keyClaimName) missingFields.push('keyClaimName');
    if (!audience) missingFields.push('audience');
    
    if (missingFields.length > 0) {
      throw new Error(`Missing required fields: ${missingFields.join(', ')}`);
    }

    // Validate JWT and extract parts
    const { header, payload, payloadObj } = validateJwt(jwt);
    const sub = payloadObj.sub;
    console.log('Extracted sub claim:', sub);

    // Use custom zkLogin prover with 32-byte salt support
    try {
      console.log('🔐 Using custom zkLogin prover with 32-byte salt support...');
      
      const result = await zkLoginProver.generateProof({
        jwt,
        extendedEphemeralPublicKey,
        maxEpoch,
        randomness,
        salt,
        keyClaimName,
        audience
      });
      
      // Return the proof and Sui address
      res.json({
        proof: result.proof,
        suiAddress: result.suiAddress,
        headerBase64: header,
        issBase64Details: Buffer.from(JSON.stringify({
          iss: payloadObj.iss,
          aud: payloadObj.aud,
          sub: payloadObj.sub
        })).toString('base64'),
        warning: result.warning,
        note: result.note
      });
      
    } catch (error) {
      console.error('❌ Custom prover error:', error);
      
      // If it's a configuration error, provide helpful instructions
      if (error.message.includes('not yet implemented')) {
        throw new Error(
          'zkLogin prover configuration needed.\n\n' +
          '⚠️  Options to enable zkLogin proofs:\n\n' +
          '1. **Use mock proofs for testing:**\n' +
          '   - Set USE_MOCK_PROVER=true in .env\n' +
          '   - This allows testing the flow without real proofs\n\n' +
          '2. **Use EC2 Docker prover when available:**\n' +
          '   - Start the EC2 instance with Docker prover\n' +
          '   - Update EC2_PROVER_URL in .env\n' +
          '   - Set USE_MOCK_PROVER=false\n\n' +
          '3. **Build custom prover (future):**\n' +
          '   - Requires zkLogin circuit files from Sui\n' +
          '   - Will support full 32-byte salt natively\n'
        );
      }
      
      throw error;
    }
  } catch (error) {
    console.error('Error generating proof:', error);
    res.status(400).json({
      error: error.message,
      stack: process.env.NODE_ENV === 'development' ? error.stack : undefined
    });
  }
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  console.error('Error stack:', err.stack);
  res.status(500).json({
    error: 'Internal server error',
    details: err.message,
    stack: process.env.NODE_ENV === 'development' ? err.stack : undefined
  });
});

// Start the server
app.listen(port, () => {
  const mode = process.env.USE_MOCK_PROVER === 'true' ? 'MOCK' : 'EXTERNAL';
  console.log(`\n🚀 Custom zkLogin Prover Service listening at http://localhost:${port}`);
  console.log(`🔐 Mode: ${mode}`);
  console.log(`🧱 Salt support: 32-byte (maintains wallet compatibility)`);
  
  if (process.env.USE_MOCK_PROVER === 'true') {
    console.log('\n⚠️  Running in MOCK mode - proofs will not validate on-chain!');
    console.log('   This is suitable for development and testing.');
  } else if (process.env.EC2_PROVER_URL) {
    console.log(`\n🌐 Using external prover: ${process.env.EC2_PROVER_URL}`);
    console.log('   32-byte values will be adapted for compatibility.');
  } else {
    console.log('\n⚠️  No prover configured! Set either:');
    console.log('   - USE_MOCK_PROVER=true for development');
    console.log('   - EC2_PROVER_URL for external prover');
  }
}); 