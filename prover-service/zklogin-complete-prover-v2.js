import express from 'express';
import cors from 'cors';
import * as snarkjs from 'snarkjs';
import fs from 'fs';
import { prepareZkLoginInputs } from './zklogin-input-parser.js';
import fetch from 'node-fetch';

const app = express();
const port = 3004;

app.use(cors());
app.use(express.json({ limit: '50mb' }));

// Circuit file paths
const CIRCUIT_WASM_PATH = '/home/ec2-user/kzero-circuit/zkLogin_js/zkLogin.wasm';
const CIRCUIT_ZKEY_PATH = '/home/ec2-user/zkLogin.zkey';

// JWKS endpoints for different providers
const JWKS_ENDPOINTS = {
    'https://accounts.google.com': 'https://www.googleapis.com/oauth2/v3/certs',
    'https://appleid.apple.com': 'https://appleid.apple.com/auth/keys'
};

async function fetchJWKS(issuer) {
    const endpoint = JWKS_ENDPOINTS[issuer];
    if (!endpoint) {
        throw new Error(`Unknown issuer: ${issuer}`);
    }
    
    const response = await fetch(endpoint);
    const data = await response.json();
    return data.keys;
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
    
    // Process in 8-byte (64-bit) chunks - BIG ENDIAN for RSA
    for (let i = 0; i < 32; i++) {
        const start = i * 8;
        const end = start + 8;
        const chunk = modulusBytes.slice(start, end);
        
        if (chunk.length > 0) {
            // Convert chunk to BigInt (big-endian for RSA modulus)
            let value = BigInt(0);
            for (let j = 0; j < chunk.length; j++) {
                // Big-endian: most significant byte first
                value = (value << BigInt(8)) | BigInt(chunk[j]);
            }
            modulusArray.push(value.toString());
        } else {
            modulusArray.push('0');
        }
    }
    
    console.log(`📐 Modulus formatted: ${modulusArray.length} chunks`);
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
        
        // Validate critical inputs
        console.log('🔍 Validating inputs:');
        console.log('  - all_inputs_hash length:', inputs.all_inputs_hash?.length);
        console.log('  - jwt_randomness length:', inputs.jwt_randomness?.length);
        console.log('  - salt length:', inputs.salt?.length);
        console.log('  - signature chunks:', inputs.signature?.length);
        console.log('  - modulus chunks:', inputs.modulus?.length);
        console.log('  - eph_public_key parts:', inputs.eph_public_key?.length);
        
        // Write inputs to file for debugging
        fs.writeFileSync('/tmp/zklogin-inputs-v2.json', JSON.stringify(inputs, null, 2));
        console.log('📝 Inputs written to /tmp/zklogin-inputs-v2.json');
        
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
        
        // Use jwtRandomness or randomness (backward compatibility)
        const jwtRand = jwtRandomness || randomness;
        
        console.log(`🎯 Processing ${audience || 'unknown'} JWT`);
        
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
🚀 Complete zkLogin Prover V2 running on port ${port}
📁 Circuit files:
   - WASM: ${fs.existsSync(CIRCUIT_WASM_PATH) ? '✅' : '❌'} ${CIRCUIT_WASM_PATH}
   - zkey: ${fs.existsSync(CIRCUIT_ZKEY_PATH) ? '✅' : '❌'} ${CIRCUIT_ZKEY_PATH}
🔑 JWKS Support:
   - Apple: ✅
   - Google: ✅
🔗 Endpoints:
   - POST /v1 - Generate zkLogin proof
   - GET /health - Check prover status
📝 Updates:
   - Improved base64 field index calculation
   - Fixed ephemeral key 128-bit split
   - Corrected RSA modulus big-endian format
   - Better field length calculations
    `);
});