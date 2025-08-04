#!/bin/bash

# Add Elastic IP to existing prover instance

# Configuration
REGION="eu-central-2"  # Zurich - all Confio infrastructure
INSTANCE_NAME_TAG="zklogin-prover"  # Adjust if your instance has a different name

echo "Finding prover instance..."
# Find instance by Name tag
INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$INSTANCE_NAME_TAG" "Name=instance-state-name,Values=running,stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text \
    --region $REGION)

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
    echo "No instance found with name tag: $INSTANCE_NAME_TAG"
    echo "Listing all instances in $REGION:"
    aws ec2 describe-instances \
        --query 'Reservations[*].Instances[*].[InstanceId,State.Name,Tags[?Key==`Name`].Value|[0],InstanceType]' \
        --output table \
        --region $REGION
    echo ""
    echo "Please enter the Instance ID of your prover:"
    read INSTANCE_ID
fi

echo "Instance ID: $INSTANCE_ID"

# Get instance details
INSTANCE_TYPE=$(aws ec2 describe-instances \
    --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].InstanceType' \
    --output text \
    --region $REGION)

echo "Instance Type: $INSTANCE_TYPE"

# Check if instance already has an Elastic IP
EXISTING_EIP=$(aws ec2 describe-addresses \
    --filters "Name=instance-id,Values=$INSTANCE_ID" \
    --query 'Addresses[0].PublicIp' \
    --output text \
    --region $REGION)

if [ "$EXISTING_EIP" != "None" ] && [ ! -z "$EXISTING_EIP" ]; then
    echo "Instance already has an Elastic IP: $EXISTING_EIP"
    echo "No action needed."
    exit 0
fi

# Allocate Elastic IP
echo "Allocating Elastic IP for prover..."
ALLOCATION_ID=$(aws ec2 allocate-address \
    --domain vpc \
    --region $REGION \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=prover-eip}]" \
    --query 'AllocationId' \
    --output text)

echo "Elastic IP Allocation ID: $ALLOCATION_ID"

# Associate Elastic IP with instance
echo "Associating Elastic IP with prover instance..."
ASSOCIATION_ID=$(aws ec2 associate-address \
    --instance-id $INSTANCE_ID \
    --allocation-id $ALLOCATION_ID \
    --region $REGION \
    --query 'AssociationId' \
    --output text)

echo "Association ID: $ASSOCIATION_ID"

# Get the Elastic IP address
ELASTIC_IP=$(aws ec2 describe-addresses \
    --allocation-ids $ALLOCATION_ID \
    --region $REGION \
    --query 'Addresses[0].PublicIp' \
    --output text)

echo ""
echo "========================================="
echo "✅ Elastic IP successfully added to prover!"
echo "========================================="
echo "Instance ID: $INSTANCE_ID"
echo "Instance Type: $INSTANCE_TYPE"
echo "Elastic IP: $ELASTIC_IP"
echo ""
echo "This IP will remain constant even when you stop/start the instance."
echo ""
echo "To connect via SSH:"
echo "ssh -i ~/.ssh/your-key.pem ubuntu@$ELASTIC_IP"
echo ""

# Update the download script with the new IP
if [ -f "download-from-ec2.sh" ]; then
    echo "Would you like to update download-from-ec2.sh with the new Elastic IP? (y/n)"
    read UPDATE_SCRIPT
    if [ "$UPDATE_SCRIPT" == "y" ]; then
        # Backup original
        cp download-from-ec2.sh download-from-ec2.sh.backup
        # Update IP in script
        sed -i.bak "s/EC2_IP=.*/EC2_IP=\"$ELASTIC_IP\"/" download-from-ec2.sh
        echo "Updated download-from-ec2.sh with new Elastic IP"
    fi
fi

# Save prover details to file
cat > prover-elastic-ip-details.txt <<EOF
INSTANCE_ID=$INSTANCE_ID
ELASTIC_IP=$ELASTIC_IP
ALLOCATION_ID=$ALLOCATION_ID
INSTANCE_TYPE=$INSTANCE_TYPE
REGION=$REGION
EOF

echo "Prover details saved to prover-elastic-ip-details.txt"