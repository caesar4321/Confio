#!/bin/bash

# Configure AWS CLI for Confio project

echo "🔧 Configuring AWS CLI..."

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found! Please install it first."
    exit 1
fi

echo "✅ AWS CLI version: $(aws --version)"

# Configure AWS profile
echo "
📝 Setting up AWS profile for Confio...

Please have ready:
1. AWS Access Key ID
2. AWS Secret Access Key
3. Default region: eu-central-2
4. Output format: json
"

# Create AWS config directory if it doesn't exist
mkdir -p ~/.aws

# Option 1: Interactive configuration
echo "Choose configuration method:"
echo "1) Interactive (aws configure)"
echo "2) Manual (edit files directly)"
read -p "Enter choice (1-2): " choice

if [ "$choice" == "1" ]; then
    echo "Running aws configure..."
    aws configure --profile confio
    
elif [ "$choice" == "2" ]; then
    echo "
Add these to ~/.aws/credentials:

[confio]
aws_access_key_id = YOUR_ACCESS_KEY_ID
aws_secret_access_key = YOUR_SECRET_ACCESS_KEY

Add these to ~/.aws/config:

[profile confio]
region = eu-central-2
output = json
"
    
    read -p "Press enter when you've added the credentials..."
fi

# Test the configuration
echo "
🧪 Testing AWS configuration..."
aws sts get-caller-identity --profile confio

if [ $? -eq 0 ]; then
    echo "✅ AWS CLI configured successfully!"
    
    # Set default profile for this project
    echo "
export AWS_PROFILE=confio
export AWS_DEFAULT_REGION=eu-central-2" >> ~/.bashrc
    
    echo "
💡 Added to ~/.bashrc:
   export AWS_PROFILE=confio
   export AWS_DEFAULT_REGION=eu-central-2
   
   Run 'source ~/.bashrc' or restart your terminal.
"
else
    echo "❌ AWS configuration test failed. Please check your credentials."
fi

# Clean up installer
rm -f ../AWSCLIV2.pkg 2>/dev/null

echo "
📋 Next steps:
1. source ~/.bashrc
2. ./launch-ec2-spot.sh
"