import crypto from 'crypto';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { toB64 } from '@mysten/sui/utils';
import fetch from 'node-fetch';

/**
 * Custom zkLogin Prover Implementation
 * 
 * This implementation creates a hybrid approach:
 * 1. Uses 32-byte salt for address generation (maintains wallet compatibility)
 * 2. Communicates with external provers when needed
 * 3. Falls back to mock proofs for development
 */

export class CustomZkLoginProver {
  constructor() {
    this.mockMode = process.env.USE_MOCK_PROVER === 'true';
    this.externalProverUrl = process.env.EC2_PROVER_URL;
  }

  /**
   * Generate zkLogin proof with 32-byte salt support
   */
  async generateProof(params) {
    const {
      jwt: jwtToken,
      extendedEphemeralPublicKey,
      maxEpoch,
      randomness,
      salt,
      keyClaimName = 'sub',
      audience
    } = params;

    // Validate inputs
    this.validateInputs(params);

    // Parse JWT to extract claims
    const jwtPayload = this.parseJWT(jwtToken);
    
    // Generate the proof
    if (this.mockMode) {
      console.log('🔧 Using mock proof generation (development mode)');
      return this.generateMockProof(params, jwtPayload);
    } else if (this.externalProverUrl) {
      console.log('🌐 Using external prover with 32-byte salt adaptation');
      return this.generateExternalProof(params, jwtPayload);
    } else {
      console.log('🔨 Using local proof generation');
      return this.generateLocalProof(params, jwtPayload);
    }
  }

  /**
   * Validate all required inputs
   */
  validateInputs(params) {
    const { jwt, extendedEphemeralPublicKey, maxEpoch, randomness, salt } = params;

    if (!jwt) throw new Error('JWT is required');
    if (!extendedEphemeralPublicKey) throw new Error('Extended ephemeral public key is required');
    if (!maxEpoch) throw new Error('Max epoch is required');
    if (!randomness) throw new Error('Randomness is required');
    if (!salt) throw new Error('Salt is required');

    // Validate 32-byte values
    const saltBytes = Buffer.from(salt, 'base64');
    const randomnessBytes = Buffer.from(randomness, 'base64');

    if (saltBytes.length !== 32) {
      throw new Error(`Salt must be 32 bytes, got ${saltBytes.length}`);
    }
    if (randomnessBytes.length !== 32) {
      throw new Error(`Randomness must be 32 bytes, got ${randomnessBytes.length}`);
    }
  }

  /**
   * Parse JWT and extract required claims
   */
  parseJWT(jwtToken) {
    const parts = jwtToken.split('.');
    if (parts.length !== 3) {
      throw new Error('Invalid JWT format');
    }

    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    
    if (!payload.sub || !payload.iss || !payload.aud) {
      throw new Error('JWT missing required claims (sub, iss, aud)');
    }

    // Handle Apple's hashed nonce
    if (payload.aud === 'apple' && payload.nonce) {
      console.log('⚠️  Apple JWT detected with hashed nonce');
      // Apple provides SHA256(nonce) instead of raw nonce
      // This is a known limitation that requires special handling
    }

    return payload;
  }

  /**
   * Generate mock proof for development
   */
  async generateMockProof(params, jwtPayload) {
    const { extendedEphemeralPublicKey, salt } = params;

    // Calculate deterministic Sui address from salt and public key
    const ephemeralKeypair = this.deriveEphemeralKeypair(salt, jwtPayload.sub, jwtPayload.aud);
    const suiAddress = ephemeralKeypair.getPublicKey().toSuiAddress();

    // Generate mock proof structure
    const mockProof = {
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

    return {
      proof: mockProof,
      suiAddress: suiAddress,
      warning: 'Mock proof - will not work on-chain'
    };
  }

  /**
   * Generate proof using external prover (EC2/Docker)
   * Adapts 32-byte values to work with provers expecting 16-byte values
   */
  async generateExternalProof(params, jwtPayload) {
    const { jwt, extendedEphemeralPublicKey, maxEpoch, randomness, salt } = params;

    // Important: We need to maintain the same address derivation
    // So we use 32-byte salt for address, but may need to adapt for prover
    const ephemeralKeypair = this.deriveEphemeralKeypair(salt, jwtPayload.sub, jwtPayload.aud);
    const suiAddress = ephemeralKeypair.getPublicKey().toSuiAddress();

    // Create a modified salt/randomness for the prover
    // Option 1: Use first 16 bytes (truncation)
    // Option 2: Hash to 16 bytes
    // Option 3: Use the prover as-is and handle errors
    
    const saltBytes = Buffer.from(salt, 'base64');
    const randomnessBytes = Buffer.from(randomness, 'base64');
    
    // Strategy: Try with full 32 bytes first, fall back if needed
    try {
      const response = await fetch(this.externalProverUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jwt,
          extendedEphemeralPublicKey,
          maxEpoch: maxEpoch.toString(),
          jwtRandomness: randomness,  // Try 32-byte first
          salt: salt,                 // Try 32-byte first
          keyClaimName: keyClaimName || 'sub'
        }),
        timeout: 120000
      });

      if (response.ok) {
        const proofData = await response.json();
        return {
          proof: proofData,
          suiAddress: suiAddress
        };
      }

      // If it fails, try with adapted values
      const adaptedSalt = this.adaptToProverRequirements(saltBytes);
      const adaptedRandomness = this.adaptToProverRequirements(randomnessBytes);

      const retryResponse = await fetch(this.externalProverUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jwt,
          extendedEphemeralPublicKey,
          maxEpoch: maxEpoch.toString(),
          jwtRandomness: adaptedRandomness,
          salt: adaptedSalt,
          keyClaimName: keyClaimName || 'sub'
        }),
        timeout: 120000
      });

      if (!retryResponse.ok) {
        throw new Error(`External prover failed: ${await retryResponse.text()}`);
      }

      const proofData = await retryResponse.json();
      return {
        proof: proofData,
        suiAddress: suiAddress,
        note: 'Generated with adapted parameters for external prover'
      };

    } catch (error) {
      console.error('External prover error:', error);
      throw new Error(`Failed to generate proof: ${error.message}`);
    }
  }

  /**
   * Generate proof locally using snarkjs
   * This is the ideal solution but requires circuit files
   */
  async generateLocalProof(params, jwtPayload) {
    // This would require:
    // 1. zkLogin.wasm and zkLogin.zkey files
    // 2. Proper circuit input preparation
    // 3. snarkjs proof generation
    
    throw new Error(
      'Local proof generation not yet implemented. ' +
      'Requires zkLogin circuit files (wasm/zkey) from Sui. ' +
      'Use mock mode or external prover for now.'
    );
  }

  /**
   * Derive ephemeral keypair from 32-byte salt
   * This must match the client-side derivation exactly
   */
  deriveEphemeralKeypair(salt, sub, aud) {
    // Ensure we're using the same derivation as the client
    const message = `${salt}${sub}${aud}`;
    const hash = crypto.createHash('sha256').update(message).digest();
    
    // Use first 32 bytes as seed
    const seed = new Uint8Array(hash);
    return Ed25519Keypair.fromSecretKey(seed);
  }

  /**
   * Adapt 32-byte values to 16-byte for external provers
   * Uses deterministic method to ensure consistency
   */
  adaptToProverRequirements(bytes32) {
    // Option 1: Truncate (simple but loses entropy)
    // return Buffer.from(bytes32.slice(0, 16)).toString('base64');
    
    // Option 2: Hash to 16 bytes (maintains more entropy)
    const hash = crypto.createHash('sha256').update(bytes32).digest();
    return Buffer.from(hash.slice(0, 16)).toString('base64');
  }
}

// Export singleton instance
export const zkLoginProver = new CustomZkLoginProver();