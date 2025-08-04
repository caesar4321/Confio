#!/bin/bash

# Recompile the modified zkLogin circuit
SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"
EC2_IP="16.62.221.198"

echo "🔨 Recompiling zkLogin circuit with variable nonce support..."
echo "⏱️ This will take approximately 10 minutes on t3.2xlarge"
echo ""

ssh -i "$SSH_KEY" ec2-user@$EC2_IP << 'REMOTE_SCRIPT'
set -e

cd /home/ec2-user/kzero-circuit

echo "📦 Installing dependencies if needed..."
npm install

echo ""
echo "🧹 Cleaning old build artifacts..."
rm -f circuits/zkLogin.r1cs circuits/zkLogin.sym zkLogin_js/zkLogin.wasm zkLogin.zkey

echo ""
echo "⚙️ Compiling circuit with circom..."
echo "Started at: $(date)"

# Compile with optimization level 2 for faster compilation
npx circom circuits/zkLogin.circom --r1cs --wasm --sym --c -o . -l node_modules

echo "Compilation finished at: $(date)"

echo ""
echo "📊 Checking compilation output..."
ls -lh zkLogin.r1cs zkLogin_js/zkLogin.wasm zkLogin.sym 2>/dev/null || echo "Some files missing, checking..."

echo ""
echo "🔑 Setting up proving key (using existing powers of tau)..."
# Using the existing ceremony files
if [ -f "/home/ec2-user/zkLogin.zkey" ]; then
    echo "Using existing zkLogin.zkey"
    cp /home/ec2-user/zkLogin.zkey .
else
    echo "⚠️ No existing zkey found, would need to generate (takes 1+ hour)"
fi

echo ""
echo "✅ Circuit compilation complete!"
echo ""
echo "📁 Output files:"
ls -lh zkLogin.r1cs zkLogin_js/zkLogin.wasm zkLogin.zkey 2>/dev/null

REMOTE_SCRIPT

echo ""
echo "✅ Recompilation complete!"
echo "Next step: Deploy the new circuit files to the prover"