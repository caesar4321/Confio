#!/bin/bash

# Configure Security Group for zkLogin Prover
# Run this after creating your EC2 instance

SECURITY_GROUP="sg-05c61dc980a18f39d"
REGION="eu-central-2"

echo "🔒 Configuring Security Group for zkLogin Prover..."

# Get your current IP address
MY_IP=$(curl -s https://api.ipify.org)
echo "📍 Your current IP: $MY_IP"

# Add SSH access from your IP
echo "➕ Adding SSH access from your IP..."
aws ec2 authorize-security-group-ingress \
    --region "$REGION" \
    --group-id "$SECURITY_GROUP" \
    --protocol tcp \
    --port 22 \
    --cidr "$MY_IP/32" \
    --group-rule-description "SSH access from developer" 2>/dev/null || echo "SSH rule may already exist"

# Add zkLogin prover port (8080) - initially from your IP for testing
echo "➕ Adding zkLogin prover access (port 8080) from your IP..."
aws ec2 authorize-security-group-ingress \
    --region "$REGION" \
    --group-id "$SECURITY_GROUP" \
    --protocol tcp \
    --port 8080 \
    --cidr "$MY_IP/32" \
    --group-rule-description "zkLogin prover access - testing" 2>/dev/null || echo "Port 8080 rule may already exist"

# For production, you'll want to add your Django server's IP
# Uncomment and modify this when ready:
# DJANGO_SERVER_IP="YOUR_DJANGO_SERVER_IP"
# aws ec2 authorize-security-group-ingress \
#     --region "$REGION" \
#     --group-id "$SECURITY_GROUP" \
#     --protocol tcp \
#     --port 8080 \
#     --cidr "$DJANGO_SERVER_IP/32" \
#     --group-rule-description "zkLogin prover access from Django server"

# List current rules
echo "
📋 Current Security Group Rules:"
aws ec2 describe-security-groups \
    --region "$REGION" \
    --group-ids "$SECURITY_GROUP" \
    --query 'SecurityGroups[0].IpPermissions[*].[IpProtocol,FromPort,ToPort,IpRanges[0].CidrIp,IpRanges[0].Description]' \
    --output table

echo "
✅ Security group configuration complete!

⚠️  Important Notes:
1. Currently allows access from your IP only ($MY_IP)
2. For production, add your Django server's IP
3. Never allow 0.0.0.0/0 on port 8080 in production
4. Consider using VPC peering or private IPs for better security
"