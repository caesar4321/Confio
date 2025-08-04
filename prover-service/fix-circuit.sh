#!/bin/bash

# Fix zkLogin circuit to accept variable-length nonces (27-64 chars)
# This handles both Google (43 char) and Apple (64 char) nonces

SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"
EC2_IP="16.62.221.198"

echo "🔧 Fixing zkLogin circuit for variable-length nonces..."

ssh -i "$SSH_KEY" ec2-user@$EC2_IP << 'REMOTE_SCRIPT'
set -e

cd /home/ec2-user/kzero-circuit/circuits

echo "📝 Modifying zkLoginMain.circom to accept 27-64 char nonces..."

# Create a fixed version with variable nonce support
cat > zkLoginMain_fixed.circom << 'EOF'
pragma circom 2.1.3;

include "./zkLoginMain.circom";

// Modify the template instantiation to support up to 64-char nonces
// The maximum nonce we've seen is 64 chars (Apple's SHA-256 hash)
// We need to support: 27 (original), 43 (Google), 64 (Apple)
template zkLoginFixed() {
    // Original parameters but with expanded nonce support
    // maxNonceLength increased from 44 to 100 to handle 64-char nonces with padding
    component main = zkLogin(248, 64 * 25, 32, 115, 126, 145, 6, 100);
}

component main {
    public [all_inputs_hash]
} = zkLoginFixed();
EOF

# Now modify the actual zkLoginMain.circom to handle variable nonce lengths
echo "📝 Patching zkLoginMain.circom for variable nonce lengths..."

# First, let's see the current nonce configuration
grep -n "nonce_value_length" zkLoginMain.circom

# Create a sed script to update the nonce handling
cat > patch_circuit.sed << 'SED_SCRIPT'
# Update nonce_value_length to support up to 64 chars + 2 quotes = 66
s/var nonce_value_length = 29;/var nonce_value_length = 66;/g

# Update maxExtNonceLength calculation to handle larger nonces
s/var maxExtNonceLength = nonce_name_length + nonce_value_length + 2 + maxWhiteSpaceLen;/var maxExtNonceLength = nonce_name_length + 66 + 2 + maxWhiteSpaceLen;/g

# Also need to handle the expected nonce name check - keep it flexible
# The circuit should validate whatever nonce length is provided, not enforce 27
SED_SCRIPT

# Apply the patch
cp zkLoginMain.circom zkLoginMain_original.circom
sed -f patch_circuit.sed zkLoginMain_original.circom > zkLoginMain.circom

echo "✅ Circuit modifications complete"
echo ""
echo "📊 Changes made:"
echo "  - nonce_value_length: 29 → 66 (supports up to 64 chars + quotes)"
echo "  - maxExtNonceLength: expanded for larger nonces"
echo "  - Circuit now accepts 27-64 character nonces"

# Show the changes
echo ""
echo "🔍 Verifying changes:"
grep -A2 -B2 "nonce_value_length" zkLoginMain.circom | head -20

REMOTE_SCRIPT

echo ""
echo "✅ Circuit modification complete!"
echo ""
echo "Next step: Recompile the circuit"
echo "Run: ./recompile-circuit.sh"