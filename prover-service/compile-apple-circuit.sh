#!/bin/bash

# Compile the Apple-compatible zkLogin circuit
SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"
EC2_IP="16.62.221.198"

echo "🔨 Compiling Apple-compatible zkLogin circuit..."
echo "⏱️ This will take approximately 10 minutes on t3.2xlarge"

ssh -i "$SSH_KEY" ec2-user@$EC2_IP << 'REMOTE_SCRIPT'
set -e

cd /home/ec2-user/kzero-circuit

echo "🧹 Cleaning old Apple circuit files..."
rm -rf zkLogin_apple_js zkLogin_apple.r1cs zkLogin_apple.sym

echo ""
echo "⚙️ Compiling circuit..."
echo "Started at: $(date)"

/home/ec2-user/circom/target/release/circom circuits/zkLogin_apple.circom \
    --r1cs --wasm --sym \
    -o zkLogin_apple_js \
    -l node_modules

echo "Finished at: $(date)"

echo ""
echo "📊 Compilation results:"
ls -lh zkLogin_apple_js/zkLogin_apple.r1cs 2>/dev/null || echo "R1CS not found"
ls -lh zkLogin_apple_js/zkLogin_apple_js/zkLogin_apple.wasm 2>/dev/null || echo "WASM not found"
ls -lh zkLogin_apple_js/zkLogin_apple.sym 2>/dev/null || echo "SYM not found"

# Copy WASM to correct location
if [ -f zkLogin_apple_js/zkLogin_apple_js/zkLogin_apple.wasm ]; then
    cp zkLogin_apple_js/zkLogin_apple_js/zkLogin_apple.wasm zkLogin_apple_js/
    echo "✅ WASM file copied to zkLogin_apple_js/"
fi

REMOTE_SCRIPT

echo ""
echo "✅ Compilation complete!"
echo "Next: Update prover to use the Apple circuit"