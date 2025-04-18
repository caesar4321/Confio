import express from 'express';
import cors from 'cors';
import { randomBytes } from 'crypto';
import { SuiClient } from '@mysten/sui/client';
import { getZkLoginSignature } from '@mysten/zklogin';

const app = express();
const port = 3001;

// Enable CORS for all routes
app.use(cors());
app.use(express.json());

// Helper: decode base64 → Buffer
function b64ToBuf(s) {
  return Buffer.from(s, 'base64');
}

// Helper function to extract sub claim from JWT
function extractSubFromJwt(jwt) {
  const payload = jwt.split('.')[1];
  return JSON.parse(Buffer.from(payload, 'base64url')).sub;
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

    // extract the "sub" claim (string)
    const sub = extractSubFromJwt(jwt);

    // Create the inputs object with exact structure expected by @mysten/zklogin
    const inputs = {
      // JWT string
      jwt,

      // u64 fields as BigInt
      maxEpoch: BigInt(maxEpoch),

      // claims as a plain object map with BigInt values
      claims: {
        [keyClaimName]: BigInt(sub)
      },

      // byte arrays as Buffers (all must be exactly 32 bytes)
      ephemeralPublicKey: b64ToBuf(extendedEphemeralPublicKey),
      randomness: b64ToBuf(randomness),
      salt: b64ToBuf(salt),

      // string fields
      keyClaimName,
      audience
    };

    // Verify buffer lengths
    if (inputs.randomness.length !== 32) {
      throw new Error(`randomness must be exactly 32 bytes, got ${inputs.randomness.length}`);
    }
    if (inputs.salt.length !== 32) {
      throw new Error(`salt must be exactly 32 bytes, got ${inputs.salt.length}`);
    }
    if (inputs.ephemeralPublicKey.length !== 32) {
      throw new Error(`ephemeralPublicKey must be exactly 32 bytes, got ${inputs.ephemeralPublicKey.length}`);
    }

    // Log the exact structure being passed to getZkLoginSignature
    console.log('Inputs structure:', JSON.stringify({
      jwt: typeof inputs.jwt,
      maxEpoch: {
        type: typeof inputs.maxEpoch,
        value: inputs.maxEpoch.toString()
      },
      claims: Object.fromEntries(
        Object.entries(inputs.claims).map(([key, value]) => [
          key,
          {
            type: typeof value,
            value: value.toString()
          }
        ])
      ),
      ephemeralPublicKey: {
        type: inputs.ephemeralPublicKey.constructor.name,
        length: inputs.ephemeralPublicKey.length,
        firstBytes: inputs.ephemeralPublicKey.slice(0, 4).toString('hex')
      },
      randomness: {
        type: inputs.randomness.constructor.name,
        length: inputs.randomness.length,
        firstBytes: inputs.randomness.slice(0, 4).toString('hex')
      },
      salt: {
        type: inputs.salt.constructor.name,
        length: inputs.salt.length,
        firstBytes: inputs.salt.slice(0, 4).toString('hex')
      },
      keyClaimName: typeof inputs.keyClaimName,
      audience: typeof inputs.audience
    }, null, 2));

    try {
      const { signature, address } = await getZkLoginSignature({ inputs });
      console.log('Generated signature:', signature);
      console.log('Sui address:', address);
      return res.json({ signature, address });
    } catch (innerErr) {
      console.error('Detailed error in getZkLoginSignature:', {
        message: innerErr.message,
        stack: innerErr.stack,
        inputs: {
          maxEpoch: inputs.maxEpoch.toString(),
          claims: Object.fromEntries(
            Object.entries(inputs.claims).map(([key, value]) => [
              key,
              value.toString()
            ])
          ),
          ephemeralPublicKey: inputs.ephemeralPublicKey.toString('hex'),
          randomness: inputs.randomness.toString('hex'),
          salt: inputs.salt.toString('hex')
        }
      });
      throw innerErr;
    }

  } catch (err) {
    console.error('Error generating proof:', err);
    return res.status(500).json({ error: err.message });
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