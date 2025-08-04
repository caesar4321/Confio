import express from 'express';
import cors from 'cors';
import * as snarkjs from 'snarkjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const app = express();
const port = 3004;
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Circuit file paths - adjusted for EC2
const CIRCUIT_WASM_PATH = '/home/ec2-user/kzero-circuit/zkLogin_js/zkLogin.wasm';
const CIRCUIT_ZKEY_PATH = '/home/ec2-user/zkLogin.zkey';

console.log('🔍 Checking for circuit files...');
console.log(`WASM: ${fs.existsSync(CIRCUIT_WASM_PATH) ? '✅ Found' : '❌ Not found'} at ${CIRCUIT_WASM_PATH}`);
console.log(`zkey: ${fs.existsSync(CIRCUIT_ZKEY_PATH) ? '✅ Found' : '❌ Not found'} at ${CIRCUIT_ZKEY_PATH}`);

function hashToField(value, targetLength = 32) {
    const hash = crypto.createHash('sha256').update(value).digest('hex');
    const bigIntHash = BigInt('0x' + hash);
    const fieldPrime = BigInt('21888242871839275222246405745257275088548364400416034343698204186575808495617');
    const fieldElement = bigIntHash % fieldPrime;
    const hexStr = fieldElement.toString(16);
    return hexStr.padStart(targetLength * 2, '0');
}

function parseJWT(jwt) {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
        throw new Error('Invalid JWT format');
    }
    
    const header = JSON.parse(Buffer.from(parts[0], 'base64url').toString());
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    
    return {
        header: parts[0],
        payload: parts[1], 
        signature: parts[2],
        headerObj: header,
        payloadObj: payload
    };
}

function prepareCircuitInputs(jwt, ephemeralPublicKey, maxEpoch, jwtRandomness, salt, keyClaimName) {
    const jwtParts = parseJWT(jwt);
    const claims = jwtParts.payloadObj;
    
    // Convert JWT parts to arrays of ASCII values
    const headerArray = Array.from(Buffer.from(jwtParts.header, 'base64url')).map(b => b.toString());
    const payloadArray = Array.from(Buffer.from(jwtParts.payload, 'base64url')).map(b => b.toString());
    
    // Pad arrays to expected length (adjust based on circuit requirements)
    const padArray = (arr, length) => {
        const padded = [...arr];
        while (padded.length < length) {
            padded.push('0');
        }
        return padded.slice(0, length);
    };
    
    // Typical zkLogin circuit inputs
    const inputs = {
        jwt_header: padArray(headerArray, 200),  // Adjust size based on circuit
        jwt_payload: padArray(payloadArray, 1000), // Adjust size based on circuit
        jwt_signature: jwtParts.signature,
        ephemeral_public_key: ephemeralPublicKey,
        max_epoch: maxEpoch,
        jwt_randomness: jwtRandomness,
        salt: salt,
        key_claim_name: keyClaimName,
        key_claim_value: claims[keyClaimName] || claims.sub,
        iss: claims.iss || '',
        aud: Array.isArray(claims.aud) ? claims.aud[0] : (claims.aud || ''),
        nonce: claims.nonce || ''
    };
    
    return inputs;
}

async function generateRealProof(inputs) {
    try {
        console.log('🔨 Generating real zkLogin proof with snarkjs...');
        console.log('Circuit inputs keys:', Object.keys(inputs));
        
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
            randomness,  // Note: might be called jwtRandomness
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

        // Prepare circuit inputs with correct format
        const inputs = prepareCircuitInputs(
            jwt,
            extendedEphemeralPublicKey,
            maxEpoch,
            jwtRand,
            salt,
            keyClaimName || 'sub'
        );
        
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
        }
    });
});

app.listen(port, '0.0.0.0', () => {
    console.log(`
🚀 Native zkLogin Prover running on port ${port}
📁 Circuit files:
   - WASM: ${fs.existsSync(CIRCUIT_WASM_PATH) ? '✅' : '❌'} ${CIRCUIT_WASM_PATH}
   - zkey: ${fs.existsSync(CIRCUIT_ZKEY_PATH) ? '✅' : '❌'} ${CIRCUIT_ZKEY_PATH}
🔗 Endpoints:
   - POST /v1 - Generate zkLogin proof
   - GET /health - Check prover status
    `);
});