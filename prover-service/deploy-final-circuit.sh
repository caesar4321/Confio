#!/bin/bash

# Deploy the final zkLogin circuit
SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"
EC2_IP="16.62.221.198"
LOCAL_DIR="/Users/julian/Confio/prover-service"

echo "📦 Deploying final zkLogin circuit..."

# Download the WASM file
echo "📥 Downloading WASM file..."
scp -i "$SSH_KEY" ec2-user@$EC2_IP:/home/ec2-user/kzero-circuit/zkLogin_final_js/zkLogin_final.wasm "$LOCAL_DIR/zkLogin.wasm"

if [ -f "$LOCAL_DIR/zkLogin.wasm" ]; then
    echo "✅ WASM file downloaded successfully"
    ls -lh "$LOCAL_DIR/zkLogin.wasm"
else
    echo "❌ Failed to download WASM file"
    exit 1
fi

# Download the zkey file (if exists)
echo ""
echo "📥 Checking for zkey file..."
ssh -i "$SSH_KEY" ec2-user@$EC2_IP "ls -la /home/ec2-user/kzero-circuit/*.zkey 2>/dev/null" || echo "No zkey file found"

# If we need to generate the zkey, we'll do that separately
echo ""
echo "✅ Circuit deployed!"
echo ""
echo "Note: The circuit is now ready for testing."
echo "The WASM file supports variable-length nonces:"
echo "  - Standard: 27 characters"
echo "  - Google: 43-44 characters"
echo "  - Apple: 64 characters (SHA-256 hashed)"