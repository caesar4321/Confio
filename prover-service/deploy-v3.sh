#!/bin/bash

# Deploy script for zkLogin prover V3
# Usage: ./deploy-v3.sh <EC2_IP> <SSH_KEY_PATH>

EC2_IP=${1:-16.62.221.198}
SSH_KEY=${2:-/Users/julian/Confio/Sui\ custom\ prover.pem}

echo "🚀 Deploying zkLogin prover V3 to EC2 instance: $EC2_IP"

# Check if SSH key exists
if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found at $SSH_KEY"
    echo "Please provide the correct SSH key path as second argument"
    exit 1
fi

echo "📦 Uploading files..."

# Upload the new prover files
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    zklogin-complete-prover-v3.js \
    zklogin-input-parser-v3.js \
    ec2-user@$EC2_IP:/home/ec2-user/

if [ $? -ne 0 ]; then
    echo "❌ Failed to upload files. Please check SSH key and EC2 IP"
    exit 1
fi

echo "🔄 Restarting prover service..."

# SSH into EC2 and restart the prover
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@$EC2_IP << 'EOF'
    # Stop existing prover
    echo "Stopping existing prover..."
    pkill -f "node.*zklogin" || true
    sleep 2
    
    # Backup old versions
    echo "Backing up old versions..."
    mv zklogin-complete-prover.js zklogin-complete-prover-v2.js 2>/dev/null || true
    mv zklogin-input-parser.js zklogin-input-parser-v2.js 2>/dev/null || true
    
    # Rename new versions
    echo "Installing new versions..."
    mv zklogin-complete-prover-v3.js zklogin-complete-prover.js
    mv zklogin-input-parser-v3.js zklogin-input-parser.js
    
    # Start new prover
    echo "Starting new prover..."
    nohup node zklogin-complete-prover.js > prover.log 2>&1 &
    
    sleep 3
    
    # Check if running
    if pgrep -f "node.*zklogin" > /dev/null; then
        echo "✅ Prover started successfully"
        echo "📝 Last 20 lines of log:"
        tail -20 prover.log
    else
        echo "❌ Prover failed to start"
        echo "📝 Error log:"
        tail -50 prover.log
    fi
EOF

echo ""
echo "🔍 Testing prover health..."
curl -s http://$EC2_IP:3004/health | python3 -m json.tool

echo ""
echo "✅ Deployment complete!"
echo "📡 Prover endpoint: http://$EC2_IP:3004/v1"
echo "📊 Health check: http://$EC2_IP:3004/health"
echo ""
echo "🔑 Critical Update: Prover V3 now requires originalNonce for Apple Sign-In"
echo "   - Apple: Pass the original 27-char nonce"
echo "   - Google: Works without originalNonce"
echo ""
echo "To view logs on EC2:"
echo "  ssh -i '$SSH_KEY' ec2-user@$EC2_IP 'tail -f prover.log'"