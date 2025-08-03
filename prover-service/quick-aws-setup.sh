#!/bin/bash

# Quick AWS Setup for Confio Project

echo "🚀 Quick AWS Setup for Confio"
echo "============================"
echo ""
echo "This script will help you set up AWS credentials quickly and securely."
echo ""

# Check if credentials already exist
if [ -f ~/.aws/credentials ]; then
    echo "⚠️  AWS credentials file already exists."
    read -p "Do you want to overwrite it? (y/N): " overwrite
    if [ "$overwrite" != "y" ]; then
        echo "Using existing credentials."
        aws sts get-caller-identity
        exit 0
    fi
fi

echo "Choose setup method:"
echo "1) Temporary credentials (paste from AWS Console) - Recommended"
echo "2) Access keys (less secure, but simpler)"
echo "3) AWS SSO (if your organization uses it)"

read -p "Enter choice (1-3): " choice

case $choice in
    1)
        echo ""
        echo "📋 To get temporary credentials:"
        echo "1. Log into AWS Console"
        echo "2. Click your username (top right) → 'Security credentials'"
        echo "3. Under 'Access keys', create a new access key"
        echo "4. In AWS Console, go to your account dropdown → 'Switch Role'"
        echo "   OR use CloudShell and run: aws sts get-session-token --duration-seconds 43200"
        echo ""
        echo "Enter the credentials:"
        read -p "AWS Access Key ID: " AWS_ACCESS_KEY_ID
        read -s -p "AWS Secret Access Key: " AWS_SECRET_ACCESS_KEY
        echo ""
        read -p "AWS Session Token (if any, press Enter to skip): " AWS_SESSION_TOKEN
        
        # Configure AWS CLI
        aws configure set aws_access_key_id "$AWS_ACCESS_KEY_ID"
        aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY"
        aws configure set region eu-central-2
        
        if [ ! -z "$AWS_SESSION_TOKEN" ]; then
            aws configure set aws_session_token "$AWS_SESSION_TOKEN"
        fi
        ;;
        
    2)
        echo ""
        echo "⚠️  Using long-term access keys (less secure)"
        echo ""
        read -p "AWS Access Key ID: " AWS_ACCESS_KEY_ID
        read -s -p "AWS Secret Access Key: " AWS_SECRET_ACCESS_KEY
        echo ""
        
        aws configure set aws_access_key_id "$AWS_ACCESS_KEY_ID"
        aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY"
        aws configure set region eu-central-2
        aws configure set output json
        ;;
        
    3)
        echo ""
        echo "Setting up AWS SSO..."
        aws configure sso
        ;;
esac

# Test the credentials
echo ""
echo "🧪 Testing AWS credentials..."
if aws sts get-caller-identity; then
    echo "✅ AWS credentials configured successfully!"
    
    # Set default region for this session
    export AWS_DEFAULT_REGION=eu-central-2
    
    echo ""
    echo "📋 Next steps:"
    echo "1. Create IAM role: ./setup-ec2-iam-role.sh"
    echo "2. Launch EC2: ./launch-ec2-spot.sh"
else
    echo "❌ Failed to verify credentials. Please check and try again."
    exit 1
fi

# Create a temporary script to set environment variables
cat > set-aws-env.sh << 'EOF'
#!/bin/bash
# Source this file to set AWS environment variables
export AWS_DEFAULT_REGION=eu-central-2
echo "✅ AWS environment set for region: eu-central-2"
EOF

chmod +x set-aws-env.sh

echo ""
echo "💡 Tip: Run 'source set-aws-env.sh' to set AWS region for this session"