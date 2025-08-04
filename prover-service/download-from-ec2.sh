#!/bin/bash

# Download zkLogin files from EC2 to local prover
EC2_IP="16.62.59.54"
KEY_PATH="/Users/julian/Confio/Sui custom prover.pem"

echo "⬇️ Downloading zkLogin files from EC2..."

# Download zkey file
scp -i "$KEY_PATH" ec2-user@$EC2_IP:~/zkLogin.zkey ./zkLogin.zkey

echo "✅ Files downloaded!"
ls -la zkLogin.*

# Restart native prover to detect files
echo "🔄 Restarting native prover..."
pkill -f "native-zklogin-prover"
node native-zklogin-prover.js &

sleep 2

# Check if it detects the files
echo "🔍 Checking prover status..."
curl -s http://localhost:3004/health | jq '.files'