#!/bin/bash

# Script to stop current instance and launch t3.2xlarge for faster compilation

INSTANCE_ID="i-08a3605c990ad715d"
REGION="eu-central-2"
KEY_PATH="/Users/julian/Confio/Sui custom prover.pem"

echo "🔄 Upgrading EC2 instance to t3.2xlarge for faster compilation..."

# Stop current instance
echo "⏹️ Stopping current t3.medium instance..."
aws ec2 stop-instances --region $REGION --instance-ids $INSTANCE_ID
aws ec2 wait instance-stopped --region $REGION --instance-ids $INSTANCE_ID

# Modify instance type
echo "🔧 Changing instance type to t3.2xlarge..."
aws ec2 modify-instance-attribute --region $REGION --instance-id $INSTANCE_ID --instance-type "{\"Value\": \"t3.2xlarge\"}"

# Start instance with new type
echo "▶️ Starting instance with t3.2xlarge..."
aws ec2 start-instances --region $REGION --instance-ids $INSTANCE_ID
aws ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID

# Get new IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --region $REGION \
    --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "
✅ Instance upgraded to t3.2xlarge!

Instance ID: $INSTANCE_ID
New Public IP: $PUBLIC_IP
Instance Type: t3.2xlarge (8 vCPUs, 32GB RAM)

📊 Performance Improvement:
- CPU: 2 vCPUs → 8 vCPUs (4x faster)
- RAM: 4GB → 32GB (8x more)
- Estimated compilation time: 15-30 minutes

💰 Cost:
- t3.2xlarge: $0.3336/hour
- Estimated total cost for compilation: ~$0.17

🚀 Resume compilation:
ssh -i \"$KEY_PATH\" ec2-user@$PUBLIC_IP
cd ~/kzero-circuit
~/.cargo/bin/circom circuits/zkLogin.circom --r1cs --wasm --sym -l node_modules

💡 After compilation completes:
1. Download the WASM file locally
2. Downgrade back to t3.medium to save costs
"