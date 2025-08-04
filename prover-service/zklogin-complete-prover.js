import express from 'express';
import cors from 'cors';
import * as snarkjs from 'snarkjs';
import fs from 'fs';
import fetch from 'node-fetch';
import { prepareZkLoginInputs } from './zklogin-input-parser.js';

const app = express();
const port = 3004;
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Circuit file paths - adjusted for EC2
const CIRCUIT_WASM_PATH = '/home/ec2-user/kzero-circuit/zkLogin_js/zkLogin.wasm';
const CIRCUIT_ZKEY_PATH = '/home/ec2-user/zkLogin.zkey';

// JWKS endpoints for getting RSA public keys
const JWKS_ENDPOINTS = {
    'https://appleid.apple.com': 'https://appleid.apple.com/auth/keys',
    'https://accounts.google.com': 'https://www.googleapis.com/oauth2/v3/certs'
};

console.log('🔍 Checking for circuit files...');
console.log(`WASM: ${fs.existsSync(CIRCUIT_WASM_PATH) ? '✅ Found' : '❌ Not found'} at ${CIRCUIT_WASM_PATH}`);
console.log(`zkey: ${fs.existsSync(CIRCUIT_ZKEY_PATH) ? '✅ Found' : '❌ Not found'} at ${CIRCUIT_ZKEY_PATH}`);

async function fetchJWKS(issuer) {
    const endpoint = JWKS_ENDPOINTS[issuer];
    if (!endpoint) {
        throw new Error(`Unknown issuer: ${issuer}`);
    }
    
    try {
        const response = await fetch(endpoint);
        const data = await response.json();
        return data.keys;
    } catch (error) {
        console.error(`Failed to fetch JWKS from ${endpoint}:`, error);
        throw error;
    }
}

function getModulusFromJWKS(keys, kid) {
    const key = keys.find(k => k.kid === kid);
    if (!key) {
        throw new Error(`Key with kid ${kid} not found in JWKS`);
    }
    
    // Convert base64url encoded modulus to byte array
    const modulusB64 = key.n;
    const modulusBytes = Buffer.from(modulusB64, 'base64url');
    
    // Convert to 32 chunks of 64-bit values (as strings for circuit)
    // The modulus is 2048 bits = 256 bytes = 32 * 64-bit chunks
    const modulusArray = [];
    
    // Process in 8-byte (64-bit) chunks
    for (let i = 0; i < 32; i++) {
        const start = i * 8;
        const end = start + 8;
        const chunk = modulusBytes.slice(start, end);
        
        if (chunk.length > 0) {
            // Convert chunk to BigInt (little-endian as per circuit)
            let value = BigInt(0);
            for (let j = 0; j < chunk.length; j++) {
                value = value | (BigInt(chunk[j]) << BigInt(j * 8));
            }
            modulusArray.push(value.toString());
        } else {
            modulusArray.push('0');
        }
    }
    
    return modulusArray;
}

function parseJWT(jwt) {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
        throw new Error('Invalid JWT format');
    }
    
    const header = JSON.parse(Buffer.from(parts[0], 'base64url').toString());
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    
    return { header, payload };
}

async function generateRealProof(inputs) {
    try {
        console.log('🔨 Generating real zkLogin proof with snarkjs...');
        console.log('Input fields count:', Object.keys(inputs).length);
        
        // Write inputs to file for debugging
        fs.writeFileSync('/tmp/zklogin-inputs.json', JSON.stringify(inputs, null, 2));
        console.log('📝 Inputs written to /tmp/zklogin-inputs.json');
        
        const { proof, publicSignals } = await snarkjs.groth16.fullProve(
            inputs,
            CIRCUIT_WASM_PATH,
            CIRCUIT_ZKEY_PATH
        );

        // Format proof for Sui
        const formattedProof = {
            a: proof.pi_a.slice(0, 2),
            b: [proof.pi_b[0].slice().reverse(), proof.pi_b[1].slice().reverse()],
            c: proof.pi_c.slice(0, 2)
        };

        return {
            proof: formattedProof,
            publicSignals
        };
    } catch (error) {
        console.error('❌ Proof generation failed:', error);
        throw error;
    }
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
            audience 
        } = req.body;
        
        // Use randomness or jwtRandomness
        const jwtRand = jwtRandomness || randomness;
        
        // Check if we have circuit files
        if (!fs.existsSync(CIRCUIT_WASM_PATH) || !fs.existsSync(CIRCUIT_ZKEY_PATH)) {
            console.log('⚠️ Circuit files not found - returning error');
            return res.status(500).json({
                error: 'Circuit files not available'
            });
        }

        // Parse JWT to get issuer and kid
        const { header, payload } = parseJWT(jwt);
        const issuer = payload.iss;
        const kid = header.kid;
        
        console.log(`📋 JWT Info - Issuer: ${issuer}, Kid: ${kid}`);
        
        // Fetch JWKS and get modulus
        console.log('🔑 Fetching JWKS...');
        const keys = await fetchJWKS(issuer);
        const modulus = getModulusFromJWKS(keys, kid);
        
        // Prepare circuit inputs with correct format
        console.log('🔧 Preparing circuit inputs...');
        const inputs = prepareZkLoginInputs(
            jwt,
            extendedEphemeralPublicKey,
            maxEpoch,
            jwtRand,
            salt,
            keyClaimName || 'sub'
        );
        
        // Add the real modulus
        inputs.modulus = modulus;
        
        console.log('📊 Circuit inputs prepared with', Object.keys(inputs).length, 'fields');
        
        // Generate real proof
        const result = await generateRealProof(inputs);
        
        console.log('✅ Proof generated successfully');
        
        res.json({
            success: true,
            proof: result.proof,
            publicSignals: result.publicSignals
        });
        
    } catch (error) {
        console.error('❌ Error generating proof:', error);
        res.status(500).json({
            error: 'Failed to generate proof',
            details: error.message
        });
    }
});

app.get('/health', (req, res) => {
    const hasWasm = fs.existsSync(CIRCUIT_WASM_PATH);
    const hasZkey = fs.existsSync(CIRCUIT_ZKEY_PATH);
    
    res.json({
        status: hasWasm && hasZkey ? 'ready' : 'missing_files',
        circuit_files: {
            wasm: hasWasm,
            zkey: hasZkey
        },
        endpoints: {
            prover: 'POST /v1',
            health: 'GET /health'
        }
    });
});

app.listen(port, '0.0.0.0', () => {
    console.log(`
🚀 Complete zkLogin Prover running on port ${port}
📁 Circuit files:
   - WASM: ${fs.existsSync(CIRCUIT_WASM_PATH) ? '✅' : '❌'} ${CIRCUIT_WASM_PATH}
   - zkey: ${fs.existsSync(CIRCUIT_ZKEY_PATH) ? '✅' : '❌'} ${CIRCUIT_ZKEY_PATH}
🔑 JWKS Support:
   - Apple: ✅
   - Google: ✅
🔗 Endpoints:
   - POST /v1 - Generate zkLogin proof
   - GET /health - Check prover status
    `);
});