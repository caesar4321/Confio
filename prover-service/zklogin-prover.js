import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import * as snarkjs from 'snarkjs';
import { execSync } from 'child_process';
import crypto from 'crypto';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Configuration
const ZKEY_PATH = path.join(__dirname, 'zkLogin.zkey');
const CIRCUIT_WASM_PATH = path.join(__dirname, 'zkLogin.wasm');
const EXPECTED_ZKEY_HASH = '060beb961802568ac9ac7f14de0fbcd55e373e8f5ec7cc32189e26fb65700aa4e36f5604f868022c765e634d14ea1cd58bd4d79cef8f3cf9693510696bcbcbce';

/**
 * Download zkLogin zkey file if not present
 */
async function downloadZkeyIfNeeded() {
  if (fs.existsSync(ZKEY_PATH)) {
    console.log('✅ zkLogin.zkey already exists');
    return verifyZkeyHash();
  }

  console.log('📥 Downloading zkLogin.zkey for testnet...');
  try {
    // Use the testnet zkey download script
    execSync(
      'wget -O - https://raw.githubusercontent.com/sui-foundation/zklogin-ceremony-contributions/main/download-test-zkey.sh | bash',
      { stdio: 'inherit', cwd: __dirname }
    );
    
    // Move the downloaded file to our directory
    const downloadPath = path.join(process.env.HOME, 'data', 'zklogin-ceremony-contributions', 'zkLogin.zkey');
    if (fs.existsSync(downloadPath)) {
      fs.renameSync(downloadPath, ZKEY_PATH);
      console.log('✅ zkLogin.zkey downloaded successfully');
      return verifyZkeyHash();
    } else {
      throw new Error('zkey file not found after download');
    }
  } catch (error) {
    console.error('❌ Failed to download zkLogin.zkey:', error.message);
    throw error;
  }
}

/**
 * Verify the zkey file hash
 */
function verifyZkeyHash() {
  if (!fs.existsSync(ZKEY_PATH)) {
    throw new Error('zkLogin.zkey not found');
  }

  const fileBuffer = fs.readFileSync(ZKEY_PATH);
  const hash = crypto.createHash('blake2b512').update(fileBuffer).digest('hex');
  
  if (hash === EXPECTED_ZKEY_HASH) {
    console.log('✅ zkLogin.zkey hash verified');
    return true;
  } else {
    console.error('❌ zkLogin.zkey hash mismatch!');
    console.error('Expected:', EXPECTED_ZKEY_HASH);
    console.error('Got:', hash);
    throw new Error('Invalid zkey file hash');
  }
}

/**
 * Convert JWT and zkLogin inputs to circuit inputs
 */
function prepareCircuitInputs(params) {
  const { jwt, extendedEphemeralPublicKey, maxEpoch, randomness, salt, keyClaimName, audience } = params;
  
  // Parse JWT
  const [headerB64, payloadB64, signatureB64] = jwt.split('.');
  const payload = JSON.parse(Buffer.from(payloadB64, 'base64url').toString());
  
  // Extract required claims
  const sub = payload.sub;
  const iss = payload.iss;
  const aud = payload.aud;
  
  // TODO: This is where we'd need to implement the actual zkLogin circuit input preparation
  // For now, return a placeholder that matches the circuit's expected inputs
  console.warn('⚠️  Circuit input preparation not fully implemented');
  
  // The actual zkLogin circuit requires specific formatted inputs including:
  // - JWT header and payload in specific format
  // - Ephemeral public key coordinates
  // - Salt and randomness
  // - Various hashes and commitments
  
  return {
    // Placeholder inputs - these would need to match the actual zkLogin circuit
    jwt_header: headerB64,
    jwt_payload: payloadB64,
    ephemeral_pubkey: extendedEphemeralPublicKey,
    max_epoch: maxEpoch,
    randomness: randomness,
    salt: salt,
    key_claim_name: keyClaimName,
    audience: audience
  };
}

/**
 * Generate zkLogin proof
 * 
 * Since we don't have the zkLogin circuit WASM file (which requires the original
 * circom circuit from Sui), we'll need to use one of these approaches:
 * 1. Use an external prover service
 * 2. Use mock proofs for development
 * 3. Obtain the compiled circuit from Sui team
 */
export async function generateZkLoginProof(params) {
  // Check if we should use an external prover service
  const EXTERNAL_PROVER_URL = process.env.EXTERNAL_ZKLOGIN_PROVER_URL;
  const EXTERNAL_PROVER_API_KEY = process.env.EXTERNAL_PROVER_API_KEY;
  
  if (EXTERNAL_PROVER_URL) {
    // Option 1: Use an external prover service (e.g., Shinami, or a custom one)
    console.log(`Using external prover at ${EXTERNAL_PROVER_URL}`);
    
    try {
      // Prepare headers
      const headers = { 'Content-Type': 'application/json' };
      
      // Add API key if provided (for Shinami)
      if (EXTERNAL_PROVER_API_KEY) {
        headers['X-API-Key'] = EXTERNAL_PROVER_API_KEY;
      }
      
      // Prepare request body based on service type
      let requestBody;
      
      if (EXTERNAL_PROVER_URL.includes('shinami.com')) {
        // Shinami uses JSON-RPC format
        requestBody = {
          jsonrpc: "2.0",
          method: "shinami_zkp_createZkLoginProof",
          params: [
            params.jwt,
            params.maxEpoch,
            params.extendedEphemeralPublicKey,
            params.randomness,
            params.salt
          ],
          id: 1
        };
      } else {
        // Default format for other services
        requestBody = params;
      }
      
      const response = await fetch(EXTERNAL_PROVER_URL, {
        method: 'POST',
        headers,
        body: JSON.stringify(requestBody),
        timeout: 30000
      });
      
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`External prover error: ${response.status} - ${errorText}`);
      }
      
      const result = await response.json();
      
      // Extract proof based on service response format
      let proof;
      if (result.result && result.result.proof) {
        // Shinami JSON-RPC format
        proof = result.result.proof;
      } else if (result.proof) {
        // Direct proof format
        proof = result.proof;
      } else {
        throw new Error('Invalid response format from external prover');
      }
      
      return { proof };
      
    } catch (error) {
      console.error('External prover failed:', error);
      throw error;
    }
  }
  
  // Option 2: Try to use local snarkjs if we have the circuit files
  const hasCircuitFiles = fs.existsSync(CIRCUIT_WASM_PATH) && fs.existsSync(ZKEY_PATH);
  
  if (hasCircuitFiles) {
    try {
      // Ensure we have the zkey file
      await downloadZkeyIfNeeded();
      
      // Prepare circuit inputs
      const circuitInputs = prepareCircuitInputs(params);
      
      console.log('🔐 Generating zkLogin proof with snarkjs...');
      
      // Generate the proof
      const { proof, publicSignals } = await snarkjs.groth16.fullProve(
        circuitInputs,
        CIRCUIT_WASM_PATH,
        ZKEY_PATH
      );
      
      console.log('✅ Proof generated successfully');
      
      // Format the proof for Sui zkLogin
      const formattedProof = {
        a: [
          '0x' + BigInt(proof.pi_a[0]).toString(16).padStart(64, '0'),
          '0x' + BigInt(proof.pi_a[1]).toString(16).padStart(64, '0')
        ],
        b: [
          [
            '0x' + BigInt(proof.pi_b[0][0]).toString(16).padStart(64, '0'),
            '0x' + BigInt(proof.pi_b[0][1]).toString(16).padStart(64, '0')
          ],
          [
            '0x' + BigInt(proof.pi_b[1][0]).toString(16).padStart(64, '0'),
            '0x' + BigInt(proof.pi_b[1][1]).toString(16).padStart(64, '0')
          ]
        ],
        c: [
          '0x' + BigInt(proof.pi_c[0]).toString(16).padStart(64, '0'),
          '0x' + BigInt(proof.pi_c[1]).toString(16).padStart(64, '0')
        ]
      };
      
      return {
        proof: formattedProof,
        publicSignals
      };
      
    } catch (error) {
      console.error('❌ Local proof generation failed:', error);
      throw error;
    }
  }
  
  // If we reach here, we can't generate real proofs
  throw new Error(
    'Cannot generate zkLogin proofs. Options:\n' +
    '1. Set EXTERNAL_ZKLOGIN_PROVER_URL to use an external service\n' +
    '2. Obtain zkLogin.wasm from Sui (requires circuit compilation)\n' +
    '3. Use USE_MOCK_PROVER=true for development'
  );
}

/**
 * Initialize the prover (download resources if needed)
 */
export async function initializeProver() {
  try {
    console.log('🚀 Initializing zkLogin prover...');
    
    // Skip zkey download if using external prover
    if (process.env.EXTERNAL_ZKLOGIN_PROVER_URL) {
      console.log('✅ Using external prover, skipping zkey download');
      return;
    }
    
    await downloadZkeyIfNeeded();
    console.log('✅ zkLogin prover initialized');
  } catch (error) {
    console.error('❌ Failed to initialize prover:', error);
    throw error;
  }
}