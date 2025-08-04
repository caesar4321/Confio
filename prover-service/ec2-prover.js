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

function generateNonce(ephemeralPublicKey, maxEpoch, jwtRandomness) {
    const publicKeyStr = Array.isArray(ephemeralPublicKey) 
        ? ephemeralPublicKey.join('')
        : ephemeralPublicKey.toString();
    const input = `${publicKeyStr}${maxEpoch}${jwtRandomness}`;
    return hashToField(input);
}

async function generateRealProof(inputs) {
    try {
        console.log('🔨 Generating real zkLogin proof with snarkjs...');
        
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
        const { jwt, extendedEphemeralPublicKey, maxEpoch, jwtRandomness, salt, keyClaimName } = req.body;
        
        // Check if we have circuit files
        if (!fs.existsSync(CIRCUIT_WASM_PATH) || !fs.existsSync(CIRCUIT_ZKEY_PATH)) {
            console.log('⚠️ Circuit files not found - returning error');
            return res.status(500).json({
                error: 'Circuit files not available'
            });
        }

        // Parse JWT to get claims
        const [header, payload, signature] = jwt.split('.');
        const claims = JSON.parse(Buffer.from(payload, 'base64url').toString());
        
        // Generate nonce
        const nonce = generateNonce(extendedEphemeralPublicKey, maxEpoch, jwtRandomness);
        console.log('📝 Generated nonce:', nonce);
        
        // Prepare circuit inputs
        const inputs = {
            jwt: jwt,
            ephemeralPublicKey: extendedEphemeralPublicKey,
            maxEpoch: maxEpoch,
            jwtRandomness: jwtRandomness,
            salt: salt,
            nonce: nonce,
            iss: claims.iss || '',
            aud: claims.aud || '',
            keyClaimValue: claims[keyClaimName] || claims.sub
        };
        
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