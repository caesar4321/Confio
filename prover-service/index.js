import express from 'express';
import cors from 'cors';
import { randomBytes } from 'crypto';
import { SuiClient } from '@mysten/sui/client';
import { getZkLoginSignature, genAddressSeed } from '@mysten/zklogin';

const app = express();
const port = 3001;

// Enable CORS for all routes
app.use(cors());
app.use(express.json());

// BN254 field modulus
const BN254_MODULUS = BigInt('21888242871839275222246405745257275088548364400416034343698204186575808495617');

// Helper: decode base64 → Buffer with length validation
function b64ToBytes(s, fieldName) {
  try {
    const buf = Buffer.from(s, 'base64');
    if (buf.length !== 32) {
      throw new Error(`Expected 32 bytes for ${fieldName}, got ${buf.length}`);
    }
    return buf;
  } catch (error) {
    throw new Error(`Base64 decoding failed for ${fieldName}: ${error.message} (input: ${s})`);
  }
}

// Helper: extract sub from JWT
function extractSubFromJwt(jwt) {
  try {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
      throw new Error('Invalid JWT: Must have three parts');
    }
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    if (!payload.sub) {
      throw new Error('JWT does not contain a "sub" claim');
    }
    return payload.sub;
  } catch (error) {
    throw new Error(`Failed to extract sub from JWT: ${error.message}`);
  }
}

// Helper: validate JWT
function validateJwt(jwt) {
  try {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
      throw new Error('Invalid JWT: Must have three parts');
    }
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    if (!payload.sub || !payload.aud || !payload.iss) {
      throw new Error('Invalid JWT: Missing required claims (sub, aud, iss)');
    }
    return payload;
  } catch (error) {
    throw new Error(`JWT validation failed: ${error.message}`);
  }
}

// Helper: convert buffer to BN254 field element
function bufferToBn254Field(buffer) {
  const hex = buffer.toString('hex');
  const num = BigInt(`0x${hex}`);
  return num % BN254_MODULUS;
}

// Helper: create mock proof for testing
function createMockProof() {
  return {
    proof_points: {
      a: ['0', '0'],
      b: [['0', '0'], ['0', '0']],
      c: ['0', '0']
    }
  };
}

// Initialize Sui client
const suiClient = new SuiClient({ url: 'https://fullnode.mainnet.sui.io:443' });

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

    console.log('Request body:', {
      jwt: jwt ? jwt.substring(0, 20) + '...' : 'undefined',
      extendedEphemeralPublicKey,
      maxEpoch,
      randomness,
      salt,
      keyClaimName,
      audience
    });

    // Validate required fields
    if (!jwt || !extendedEphemeralPublicKey || !maxEpoch || !randomness || !salt || !keyClaimName || !audience) {
      throw new Error('Missing required fields in request body');
    }

    // Extract sub claim from JWT
    const sub = extractSubFromJwt(jwt);
    console.log('Extracted sub claim:', sub);

    // Create inputs with the exact shape zkLogin expects
    const inputs = {
      jwt,
      maxEpoch: BigInt(maxEpoch),
      ephemeralPublicKey: b64ToBytes(extendedEphemeralPublicKey, 'ephemeralPublicKey'),
      randomness: b64ToBytes(randomness, 'randomness'),
      salt: b64ToBytes(salt, 'salt'),
      keyClaimName,
      claims: { sub: BigInt(sub) },
      audience
    };

    console.log('Inputs for getZkLoginSignature:', {
      jwt: inputs.jwt ? inputs.jwt.substring(0, 20) + '...' : 'undefined',
      maxEpoch: inputs.maxEpoch.toString(),
      ephemeralPublicKey: {
        type: inputs.ephemeralPublicKey.constructor.name,
        length: inputs.ephemeralPublicKey.length,
        value: inputs.ephemeralPublicKey.toString('base64')
      },
      randomness: {
        type: inputs.randomness.constructor.name,
        length: inputs.randomness.length,
        value: inputs.randomness.toString('base64')
      },
      salt: {
        type: inputs.salt.constructor.name,
        length: inputs.salt.length,
        value: inputs.salt.toString('base64')
      },
      keyClaimName: inputs.keyClaimName,
      claims: inputs.claims,
      audience: inputs.audience
    });

    // Generate signature
    try {
      const { signature, address } = await getZkLoginSignature({ inputs });
      console.log('Generated signature:', signature, 'address:', address);
      res.json({
        signature,
        address
      });
    } catch (error) {
      console.error('Detailed error in getZkLoginSignature:', error);
      throw error;
    }
  } catch (error) {
    console.error('Error generating proof:', error);
    res.status(400).json({
      error: error.message,
      stack: error.stack
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

app.listen(port, () => {
  console.log(`Prover service listening at http://localhost:${port}`);
}); 