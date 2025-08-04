#!/bin/bash

# Script to launch on-demand EC2 instance for zkLogin prover
# On-demand allows stop/start without losing the instance

# Configuration
INSTANCE_TYPE="t3.medium"  # 2 vCPUs, 4GB RAM - good balance for cost/performance
AMI_ID="ami-006b3a0f02bfbc190"  # Amazon Linux 2023 in eu-central-2 (Zurich)
KEY_NAME="Sui custom prover"  # Your key pair name
SECURITY_GROUP="sg-05c61dc980a18f39d"  # Your security group ID
REGION="eu-central-2"            # Zurich region

echo "🚀 Launching on-demand EC2 instance for zkLogin prover..."

# Launch on-demand instance (no spot pricing)
INSTANCE_ID=$(aws ec2 run-instances \
    --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SECURITY_GROUP" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=zkLogin-Prover-OnDemand},{Key=Environment,Value=production}]" \
    --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=30,VolumeType=gp3,DeleteOnTermination=true}" \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "✅ Instance launched: $INSTANCE_ID"

# Wait for instance to be running
echo "⏳ Waiting for instance to start..."
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "
✅ EC2 On-Demand Instance Launched Successfully!

Instance ID: $INSTANCE_ID
Public IP: $PUBLIC_IP
Instance Type: $INSTANCE_TYPE

📋 Next Steps:
1. SSH to instance: ssh -i \"$KEY_NAME.pem\" ec2-user@$PUBLIC_IP
2. Install dependencies and compile zkLogin circuit
3. Stop instance when not in use: aws ec2 stop-instances --region $REGION --instance-ids $INSTANCE_ID
4. Start instance when needed: aws ec2 start-instances --region $REGION --instance-ids $INSTANCE_ID

💡 Cost Management:
- Instance: ~\$0.0832/hour when running (t3.medium)
- Storage: ~\$2.40/month (30GB gp3)
- Stop the instance when not in use to save costs
- Data persists when stopped (unlike spot instances)

⚠️ Important:
- This is an on-demand instance - you can stop/start it anytime
- All data persists when stopped
- You're only charged for compute when running
- Storage is charged even when stopped (~\$0.08/day)
"

# Save instance ID for easy reference
echo "$INSTANCE_ID" > .current-instance-id
echo "Instance ID saved to .current-instance-id for easy reference"