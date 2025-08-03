#!/bin/bash

# Configure AWS CLI with SSO (Best Practice)

echo "🔧 Configuring AWS CLI with SSO (Recommended)..."

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found! Please install it first."
    exit 1
fi

echo "✅ AWS CLI version: $(aws --version)"

echo "
📝 AWS SSO Configuration Options:

1) AWS SSO (Recommended) - Uses temporary credentials
2) IAM Identity Center - For organizations
3) Assume Role with MFA - For enhanced security
4) EC2 Instance Profile - For EC2-based development

Which method would you like to use?"

read -p "Enter choice (1-4): " choice

case $choice in
    1)
        echo "
🔐 Setting up AWS SSO...

You'll need:
- Your AWS SSO start URL (e.g., https://my-sso-portal.awsapps.com/start)
- SSO Region (e.g., us-east-1)
- Account ID
- Permission set/role name
"
        aws configure sso --profile confio-sso
        
        echo "
✅ SSO configured! To use it:
1. Login: aws sso login --profile confio-sso
2. Use: export AWS_PROFILE=confio-sso
"
        ;;
        
    2)
        echo "
🏢 Setting up IAM Identity Center...
"
        aws configure sso-session
        ;;
        
    3)
        echo "
🔑 Setting up Assume Role with MFA...

First, configure your base profile with minimal permissions:"
        
        aws configure set aws_access_key_id YOUR_ACCESS_KEY --profile confio-base
        aws configure set aws_secret_access_key YOUR_SECRET_KEY --profile confio-base
        aws configure set region eu-central-2 --profile confio-base
        
        echo "
Now configure the role to assume:"
        
        cat >> ~/.aws/config << EOF

[profile confio]
source_profile = confio-base
role_arn = arn:aws:iam::YOUR_ACCOUNT_ID:role/YOUR_ROLE_NAME
mfa_serial = arn:aws:iam::YOUR_ACCOUNT_ID:mfa/YOUR_MFA_DEVICE
region = eu-central-2
EOF
        
        echo "
✅ Configured! When you use this profile, you'll be prompted for MFA code.
"
        ;;
        
    4)
        echo "
☁️  EC2 Instance Profile Setup...

This is ideal if you're developing on an EC2 instance.
No credentials needed - the instance role provides them!

To use:
1. Launch an EC2 instance with an IAM role
2. AWS CLI will automatically use the instance credentials
3. No configuration needed on the instance
"
        ;;
esac

# Create a secure credentials script
cat > use-temp-credentials.sh << 'EOF'
#!/bin/bash
# Use temporary credentials from AWS STS

echo "🔐 Getting temporary credentials..."

# Option 1: Get session token with MFA
get_session_token_with_mfa() {
    read -p "Enter MFA code: " MFA_CODE
    
    CREDS=$(aws sts get-session-token \
        --serial-number arn:aws:iam::YOUR_ACCOUNT_ID:mfa/YOUR_MFA_DEVICE \
        --token-code $MFA_CODE \
        --duration-seconds 43200 \
        --output json)
    
    export AWS_ACCESS_KEY_ID=$(echo $CREDS | jq -r '.Credentials.AccessKeyId')
    export AWS_SECRET_ACCESS_KEY=$(echo $CREDS | jq -r '.Credentials.SecretAccessKey')
    export AWS_SESSION_TOKEN=$(echo $CREDS | jq -r '.Credentials.SessionToken')
    
    echo "✅ Temporary credentials set for 12 hours"
}

# Option 2: Assume role
assume_role() {
    ROLE_ARN="arn:aws:iam::YOUR_ACCOUNT_ID:role/YOUR_ROLE_NAME"
    SESSION_NAME="confio-session-$(date +%s)"
    
    CREDS=$(aws sts assume-role \
        --role-arn $ROLE_ARN \
        --role-session-name $SESSION_NAME \
        --output json)
    
    export AWS_ACCESS_KEY_ID=$(echo $CREDS | jq -r '.Credentials.AccessKeyId')
    export AWS_SECRET_ACCESS_KEY=$(echo $CREDS | jq -r '.Credentials.SecretAccessKey')
    export AWS_SESSION_TOKEN=$(echo $CREDS | jq -r '.Credentials.SessionToken')
    
    echo "✅ Assumed role: $ROLE_ARN"
}

# Choose method
echo "1) Get session token with MFA"
echo "2) Assume role"
read -p "Choose method: " METHOD

case $METHOD in
    1) get_session_token_with_mfa ;;
    2) assume_role ;;
esac
EOF

chmod +x use-temp-credentials.sh

echo "
📋 Best Practices Summary:

✅ DO:
- Use AWS SSO or temporary credentials
- Enable MFA on your AWS account  
- Use IAM roles for EC2 instances
- Rotate credentials regularly
- Use least privilege principle

❌ DON'T:
- Create long-term access keys
- Store credentials in code
- Share credentials
- Use root account for daily tasks

🚀 Next Steps:
1. Complete the SSO/role configuration
2. Test with: aws sts get-caller-identity --profile confio-sso
3. Launch EC2: AWS_PROFILE=confio-sso ./launch-ec2-spot.sh
"