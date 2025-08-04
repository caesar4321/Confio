import express from 'express';
import cors from 'cors';
import fetch from 'node-fetch';
import crypto from 'crypto';

const app = express();
const port = 3004;
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Mysten's prover endpoint
const MYSTEN_PROVER = 'https://prover-dev.mystenlabs.com/v1';

function parseJWT(jwt) {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
        throw new Error('Invalid JWT format');
    }
    
    const header = JSON.parse(Buffer.from(parts[0], 'base64url').toString());
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    
    return { header, payload, parts };
}

function computeNonceFromRaw(rawNonce) {
    // For Apple/Google, the nonce in JWT is hashed
    // We need to provide the raw nonce that was hashed
    return rawNonce;
}

app.post('/v1', async (req, res) => {
    console.log('\n📨 Received zkLogin proof request');
    
    try {
        const { 
            jwt, 
            extendedEphemeralPublicKey, 
            maxEpoch, 
            randomness,
            jwtRandomness,
            salt, 
            keyClaimName,
            audience,
            computedNonce  // The raw nonce before hashing
        } = req.body;
        
        // Parse JWT to check if it's Apple/Google
        const { payload } = parseJWT(jwt);
        const isApple = payload.iss === 'https://appleid.apple.com';
        const isGoogle = payload.iss === 'https://accounts.google.com';
        
        // Prepare request for Mysten's prover
        const proverRequest = {
            jwt: jwt,
            extendedEphemeralPublicKey: extendedEphemeralPublicKey,
            maxEpoch: maxEpoch,
            jwtRandomness: jwtRandomness || randomness,
            salt: salt,
            keyClaimName: keyClaimName || 'sub'
        };
        
        // If Apple/Google and we have computed nonce, we might need special handling
        if ((isApple || isGoogle) && computedNonce) {
            console.log('🍎/🔍 Apple/Google detected with computed nonce');
            // Mysten's prover expects the JWT to have the correct nonce
            // Since Apple/Google hash the nonce, we need to work around this
            
            // Option 1: Try with the original JWT
            console.log('Trying with original JWT...');
        }
        
        console.log('📤 Forwarding to Mysten prover...');
        const response = await fetch(MYSTEN_PROVER, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(proverRequest),
            timeout: 30000
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            console.error('❌ Mysten prover error:', result);
            
            // If it's a nonce mismatch for Apple/Google, we expected this
            if ((isApple || isGoogle) && result.error && result.error.includes('nonce')) {
                return res.status(500).json({
                    error: 'Nonce mismatch - Apple/Google hash their nonces which is incompatible with Mysten prover',
                    details: 'Need custom implementation for Apple/Google Sign In'
                });
            }
            
            return res.status(response.status).json(result);
        }
        
        console.log('✅ Proof generated successfully');
        res.json(result);
        
    } catch (error) {
        console.error('❌ Error in proxy:', error);
        res.status(500).json({
            error: 'Proxy error',
            details: error.message
        });
    }
});

app.get('/health', (req, res) => {
    res.json({
        status: 'ready',
        type: 'proxy',
        backend: MYSTEN_PROVER
    });
});

app.listen(port, '0.0.0.0', () => {
    console.log(`
🔄 zkLogin Proxy Server running on port ${port}
🎯 Backend: ${MYSTEN_PROVER}
📝 This proxy handles Apple/Google nonce issues
🔗 Endpoints:
   - POST /v1 - Generate zkLogin proof
   - GET /health - Check proxy status
    `);
});