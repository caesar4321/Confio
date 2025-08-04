#!/bin/bash

# Complete setup script for zkLogin compilation on fresh EC2 instance

EC2_IP="$1"
if [ -z "$EC2_IP" ]; then
    echo "Usage: ./setup-zklogin-compilation.sh <EC2_IP>"
    exit 1
fi

KEY_PATH="/Users/julian/Confio/Sui custom prover.pem"

echo "🚀 Setting up zkLogin compilation environment on EC2..."

ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no ec2-user@$EC2_IP << 'ENDSSH'
set -e

echo "📦 Installing system dependencies..."
sudo yum update -y
sudo yum groupinstall -y 'Development Tools'
sudo yum install -y nodejs npm git git-lfs docker

echo "🦀 Installing Rust..."
curl --proto '=https' --tlsv1.2 https://sh.rustup.rs -sSf | sh -s -- -y
source ~/.cargo/env

echo "⚙️ Installing Circom..."
git clone https://github.com/iden3/circom.git
cd circom
git checkout v2.1.9
cargo build --release
cargo install --path circom
cd ~

echo "📥 Installing snarkjs..."
sudo npm install -g snarkjs

echo "🔑 Downloading zkLogin ceremony files..."
git lfs install
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/sui-foundation/zklogin-ceremony-contributions.git
cd zklogin-ceremony-contributions
echo "⬇️ Downloading zkLogin-test.zkey (this will take 10-15 minutes)..."
git lfs pull --include "zkLogin-test.zkey"
cp zkLogin-test.zkey ~/zkLogin.zkey
cd ~

echo "📂 Cloning zkLogin circuit source..."
git clone https://github.com/kzero-xyz/kzero-circuit.git
cd kzero-circuit
npm install

echo "🔨 Compiling zkLogin circuit to WASM..."
echo "This will take 15-30 minutes on t3.medium..."
~/.cargo/bin/circom circuits/zkLogin.circom --r1cs --wasm --sym -l node_modules

echo "✅ Checking generated files..."
if [ -f zkLogin_js/zkLogin.wasm ]; then
    echo "✅ WASM file generated successfully!"
    ls -la zkLogin_js/zkLogin.wasm
else
    echo "❌ WASM generation failed"
    exit 1
fi

echo "📊 Summary of circuit files:"
ls -la ~/zkLogin.zkey 2>/dev/null || echo "No zkey file"
ls -la ~/kzero-circuit/zkLogin_js/zkLogin.wasm 2>/dev/null || echo "No WASM file"

echo "
✅ Setup complete! Circuit files ready:
- zkLogin.zkey: ~/zkLogin.zkey
- zkLogin.wasm: ~/kzero-circuit/zkLogin_js/zkLogin.wasm

You can now use these files with your native prover!
"
ENDSSH

echo "✅ Setup script completed!"