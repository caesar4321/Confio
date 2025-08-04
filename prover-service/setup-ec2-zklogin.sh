#!/bin/bash

# Setup zkLogin circuit files on EC2
EC2_IP="16.62.59.54"
KEY_PATH="/Users/julian/Confio/Sui custom prover.pem"

echo "🚀 Setting up zkLogin prover on EC2..."

# Wait for instance to be ready
echo "⏳ Waiting for EC2 to be ready..."
sleep 30

# SSH and setup
ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no ec2-user@$EC2_IP << 'EOF'
echo "📦 Setting up zkLogin circuit files..."

# Install git-lfs
sudo yum install -y git-lfs
git lfs install

# Create directory for circuit files
mkdir -p ~/zklogin-files
cd ~/zklogin-files

echo "⬇️ Downloading zkLogin zkey file (this will take 10-15 minutes)..."
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/sui-foundation/zklogin-ceremony-contributions.git
cd zklogin-ceremony-contributions

# Download the test zkey file
echo "📥 Pulling zkey file..."
git lfs pull --include "zkLogin-test.zkey"

# Check file size
ls -la zkLogin-test.zkey
echo "✅ zkey file downloaded successfully"

# Look for WASM file
echo "🔍 Looking for WASM file..."
find . -name "*.wasm" -type f 2>/dev/null || echo "No WASM file found in repository"

# Move files to accessible location
cp zkLogin-test.zkey ~/zkLogin.zkey
echo "📂 Files ready at ~/zkLogin.zkey"

# Check final files
cd ~
ls -la zkLogin.*

echo "✅ zkLogin circuit files setup complete!"
echo "📋 Available files:"
ls -la ~/zkLogin.*

# Verify file integrity
echo "🔐 Verifying file integrity..."
b2sum zkLogin.zkey 2>/dev/null || echo "b2sum not available, skipping verification"

EOF

echo "✅ EC2 zkLogin setup complete!"
echo "📍 EC2 IP: $EC2_IP"
echo "🔗 Prover URL: http://$EC2_IP:8080"
echo ""
echo "📋 Next steps:"
echo "1. Files are ready on EC2 at ~/zkLogin.zkey"
echo "2. We can now set up our native prover to use these files"
echo "3. Or use the EC2 Docker prover directly"