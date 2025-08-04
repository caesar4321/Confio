#!/bin/bash

# Script to modify zkLogin circuit for Apple Sign-In support
# This creates a new circuit that accepts 33-byte (44-char base64) nonces

EC2_IP=${1:-16.62.221.198}
SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"

echo "🔧 Modifying zkLogin circuit for Apple Sign-In support..."
echo "📍 Target EC2: $EC2_IP"
echo ""

ssh -i "$SSH_KEY" ec2-user@$EC2_IP << 'EOF'
    set -e
    
    echo "📂 Creating backup of original circuit..."
    cd /home/ec2-user/kzero-circuit/circuits
    cp zkLoginMain.circom zkLoginMain.circom.backup
    cp zkLogin.circom zkLogin.circom.backup
    
    echo "🔨 Modifying circuit for 33-byte nonce support..."
    
    # Create a modified version that supports Apple's 33-byte nonce
    cat > zkLoginMain_apple.circom << 'CIRCUIT'
pragma circom 2.1.3;

include "./helpers/misc.circom";
include "./helpers/strings.circom";
include "./helpers/sha256.circom";
include "./helpers/rsa/rsa.circom";
include "./helpers/hasher.circom";
include "./helpers/base64.circom";
include "./helpers/jwtchecks.circom";
include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/bitify.circom";

template zkLogin(
    n, k, inCount, inCountSquared, inCountCubed, inCountQuartic, maxKeyIndexLen, maxISSLen, 
    maxAudLen, maxSubLen, maxEVNameLen, maxEVValueLen, maxWhiteSpaceLen, maxNonceLen
) {
    // MODIFIED FOR APPLE: Support 33-byte nonces (44 chars base64)
    // Original was 27 bytes (36 chars base64)
    var nonce_name_length = 7;  // "nonce"
    var nonce_value_length = 46; // 44 for Base64 encoding of 33 bytes, 2 for quotes
    var maxExtNonceLength = nonce_name_length + nonce_value_length + 2 + maxWhiteSpaceLen;
    
    // All other parameters remain the same
    signal input all_inputs_hash;
    signal input padded_unsigned_jwt[inCount];
    signal input payload_start_index;
    signal input payload_len;
    signal input num_sha2_blocks;
    signal input signature[k];
    signal input modulus[k];
    signal input max_epoch;
    signal input eph_public_key[2];
    signal input salt;
    signal input jwt_randomness;
    
    // Extended fields with updated nonce length
    signal input ext_aud[maxAudLen];
    signal input ext_aud_length;
    signal input ext_sub[maxSubLen];
    signal input ext_sub_length;
    signal input ext_iss[maxISSLen];
    signal input ext_iss_length;
    signal input ext_kc[maxSubLen];
    signal input ext_kc_length;
    signal input ext_nonce[maxExtNonceLength];
    signal input ext_nonce_length;
    signal input ext_ev[maxEVValueLen];
    signal input ext_ev_length;
    
    // Field indices
    signal input aud_index_b64;
    signal input aud_length_b64;
    signal input aud_colon_index;
    signal input aud_value_index;
    signal input aud_value_length;
    
    signal input sub_index_b64;
    signal input sub_length_b64;
    signal input sub_colon_index;
    signal input sub_value_index;
    signal input sub_value_length;
    
    signal input iss_index_b64;
    signal input iss_length_b64;
    
    signal input kc_index_b64;
    signal input kc_length_b64;
    signal input kc_name_length;
    signal input kc_colon_index;
    signal input kc_value_index;
    signal input kc_value_length;
    
    signal input nonce_index_b64;
    signal input nonce_length_b64;
    signal input nonce_colon_index;
    signal input nonce_value_index;
    
    signal input ev_index_b64;
    signal input ev_length_b64;
    signal input ev_name_length;
    signal input ev_colon_index;
    signal input ev_value_index;
    signal input ev_value_length;
    
    // Rest of the circuit logic remains the same
    // (We're just updating the nonce array size and length constants)
    
    // TODO: Include the rest of the zkLoginMain template here
    // For now, this shows the key changes needed
}
CIRCUIT
    
    echo "✅ Circuit modification complete"
    echo ""
    echo "📋 Key changes made:"
    echo "  - nonce_value_length: 29 → 46 (supports 44-char base64)"
    echo "  - maxExtNonceLength: adjusted for larger nonce"
    echo "  - ext_nonce array: expanded to handle 33-byte nonces"
    
    echo ""
    echo "⚠️ Next steps:"
    echo "1. Complete the circuit modification (merge with original logic)"
    echo "2. Recompile: circom zkLogin_apple.circom --r1cs --wasm --sym"
    echo "3. Generate new keys: snarkjs groth16 setup ..."
    echo "4. Test with Apple Sign-In JWTs"
EOF

echo ""
echo "✅ Circuit modification script complete!"
echo ""
echo "🔍 To compile the modified circuit:"
echo "  ssh -i '$SSH_KEY' ec2-user@$EC2_IP"
echo "  cd /home/ec2-user/kzero-circuit/circuits"
echo "  circom zkLogin_apple.circom --r1cs --wasm --sym --O2"
echo ""
echo "⚠️ Note: Full compilation will take 1-2 hours on t3.2xlarge"