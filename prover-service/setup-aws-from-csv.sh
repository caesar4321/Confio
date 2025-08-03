#!/bin/bash

# Setup AWS CLI from downloaded CSV file

echo "🔧 Setting up AWS CLI from CSV file..."

# Check if CSV file exists
CSV_FILE="/Users/julian/Confio/Julian_accessKeys.csv"
if [ ! -f "$CSV_FILE" ]; then
    echo "❌ CSV file not found at: $CSV_FILE"
    echo "Please make sure you downloaded Julian_accessKeys.csv to the Confio directory"
    exit 1
fi

# Read the CSV file (skip header)
echo "📄 Reading credentials from CSV..."
CREDENTIALS=$(tail -n 1 "$CSV_FILE")
ACCESS_KEY=$(echo "$CREDENTIALS" | cut -d',' -f1)
SECRET_KEY=$(echo "$CREDENTIALS" | cut -d',' -f2)

if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
    echo "❌ Could not extract credentials from CSV"
    echo "CSV content:"
    cat "$CSV_FILE"
    exit 1
fi

# Configure AWS CLI
echo "⚙️  Configuring AWS CLI with profile 'confio'..."
aws configure set aws_access_key_id "$ACCESS_KEY" --profile confio
aws configure set aws_secret_access_key "$SECRET_KEY" --profile confio
aws configure set region eu-central-2 --profile confio
aws configure set output json --profile confio

# Test the configuration
echo "🧪 Testing AWS credentials..."
export AWS_PROFILE=confio
if aws sts get-caller-identity; then
    echo "✅ AWS CLI configured successfully!"
    
    # Create environment file
    cat > aws-env.sh << EOF
#!/bin/bash
# Source this file to use AWS profile
export AWS_PROFILE=confio
export AWS_DEFAULT_REGION=eu-central-2
echo "✅ AWS environment configured for profile: confio"
EOF
    chmod +x aws-env.sh
    
    echo ""
    echo "📋 Next steps:"
    echo "1. source ./aws-env.sh"
    echo "2. ./launch-ec2-spot.sh"
    echo ""
    echo "🔒 Security reminder:"
    echo "- Move CSV files to a secure location"
    echo "- Never commit CSV files to git"
    echo "- Consider deleting access keys after EC2 setup"
else
    echo "❌ Failed to verify AWS credentials"
    exit 1
fi

# Secure the CSV files
echo ""
echo "🔐 Securing credential files..."
chmod 600 "$CSV_FILE"
chmod 600 "/Users/julian/Confio/Julian_credentials.csv" 2>/dev/null || true

echo "⚠️  IMPORTANT: Move these files to a secure location:"
echo "- $CSV_FILE"
echo "- /Users/julian/Confio/Julian_credentials.csv"