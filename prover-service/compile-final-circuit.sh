#!/bin/bash

# Compile the final zkLogin circuit
SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"
EC2_IP="16.62.221.198"

echo "🔨 Compiling FINAL zkLogin circuit..."
echo "⏱️ This will take approximately 10 minutes"

ssh -i "$SSH_KEY" ec2-user@$EC2_IP << 'REMOTE_SCRIPT'
set -e

cd /home/ec2-user/kzero-circuit

echo "🧹 Cleaning old files..."
rm -rf zkLogin_final_js zkLogin_final.r1cs zkLogin_final.sym

echo ""
echo "⚙️ Starting compilation..."
echo "Started at: $(date)"

/home/ec2-user/circom/target/release/circom circuits/zkLogin_final.circom \
    --r1cs --wasm --sym \
    -o . \
    -l node_modules

echo "Finished at: $(date)"

echo ""
echo "📊 Checking output files..."
if [ -f zkLogin_final_js/zkLogin_final.wasm ]; then
    echo "✅ WASM file created"
    ls -lh zkLogin_final_js/zkLogin_final.wasm
else
    echo "❌ WASM file not found"
fi

if [ -f zkLogin_final.r1cs ]; then
    echo "✅ R1CS file created"
    ls -lh zkLogin_final.r1cs
else
    echo "❌ R1CS file not found"
fi

REMOTE_SCRIPT

echo ""
echo "✅ Compilation complete!"