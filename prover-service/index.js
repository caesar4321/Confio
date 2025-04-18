import express from 'express';
import cors from 'cors';

const app = express();
const port = 3001;

// Enable CORS for all routes
app.use(cors());
app.use(express.json());

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

    // Convert base64 fields to Uint8Array with validation
    let ephemeralPublicKey, randBytes, saltBytes;
    try {
      ephemeralPublicKey = b64ToBuf(extendedEphemeralPublicKey, 'ephemeralPublicKey');
      randBytes = b64ToBuf(randomness, 'randomness');
      saltBytes = b64ToBuf(salt, 'salt');
    } catch (error) {
      throw new Error(`Invalid base64 format for ${error.message}`);
    }

    // Generate a mock Groth16 proof
    // In a real implementation, this would call your actual prover
    const proof = {
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

    // Return the proof and Sui address
    res.json({
      proof,
      suiAddress: "0x" + Buffer.from(ephemeralPublicKey).toString('hex')
    });
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

app.listen(port, () => {
  console.log(`Prover service listening at http://localhost:${port}`);
}); 