#!/bin/bash

# Compile the comprehensive zkLogin circuit
SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"
EC2_IP="16.62.221.198"

echo "🔨 Compiling comprehensive zkLogin circuit..."
echo "⏱️ This will take approximately 10 minutes on t3.2xlarge"

ssh -i "$SSH_KEY" ec2-user@$EC2_IP << 'REMOTE_SCRIPT'
set -e

cd /home/ec2-user/kzero-circuit

echo "🧹 Cleaning old comprehensive circuit files..."
rm -rf zkLogin_comprehensive_js zkLogin_comprehensive.r1cs zkLogin_comprehensive.sym

echo ""
echo "⚙️ Compiling circuit..."
echo "Started at: $(date)"

/home/ec2-user/circom/target/release/circom circuits/zkLogin_comprehensive.circom \
    --r1cs --wasm --sym \
    -o zkLogin_comprehensive_js \
    -l node_modules

echo "Finished at: $(date)"

echo ""
echo "📊 Compilation results:"
ls -lh zkLogin_comprehensive_js/zkLogin_comprehensive.r1cs 2>/dev/null || echo "R1CS not found"
ls -lh zkLogin_comprehensive_js/zkLogin_comprehensive_js/zkLogin_comprehensive.wasm 2>/dev/null || echo "WASM not found"
ls -lh zkLogin_comprehensive_js/zkLogin_comprehensive.sym 2>/dev/null || echo "SYM not found"

# Copy WASM to correct location
if [ -f zkLogin_comprehensive_js/zkLogin_comprehensive_js/zkLogin_comprehensive.wasm ]; then
    cp zkLogin_comprehensive_js/zkLogin_comprehensive_js/zkLogin_comprehensive.wasm zkLogin_comprehensive_js/
    echo "✅ WASM file copied to zkLogin_comprehensive_js/"
fi

REMOTE_SCRIPT

echo ""
echo "✅ Compilation complete!"
echo "Next: Deploy the comprehensive circuit"