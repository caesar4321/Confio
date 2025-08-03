#!/bin/bash

# SSH to zkLogin Prover EC2 Instance

# Load configuration from .env.production
if [ -f .env.production ]; then
    export $(cat .env.production | grep -v '^#' | xargs)
else
    echo "❌ .env.production not found!"
    exit 1
fi

# Check if EC2_PROVER_URL has been updated
if [[ "$EC2_PROVER_URL" == *"YOUR_EC2_PUBLIC_IP"* ]]; then
    echo "❌ Please update EC2_PROVER_URL in .env.production with your instance IP"
    exit 1
fi

# Extract IP from EC2_PROVER_URL
EC2_IP=$(echo $EC2_PROVER_URL | sed -E 's|http://([0-9.]+):.*|\1|')

# SSH to the instance
echo "🔌 Connecting to zkLogin Prover at $EC2_IP..."
ssh -i "$EC2_KEY_PATH" ec2-user@$EC2_IP