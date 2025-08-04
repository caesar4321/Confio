#!/bin/bash

# Launch EC2 instance for Confio main website and app

# Configuration
INSTANCE_NAME="confio"
INSTANCE_TYPE="t3.micro"  # Smallest t3 instance type (2 vCPU, 1 GB RAM)
KEY_NAME="confio-key"  # Key pair name
SECURITY_GROUP_NAME="confio-sg"
REGION="eu-central-2"  # Zurich

# Get latest Amazon Linux 2023 AMI for the region
AMI_ID=$(aws ec2 describe-images \
    --owners amazon \
    --filters "Name=name,Values=al2023-ami-*-x86_64" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
    --output text \
    --region $REGION)

# Check if key pair exists, create if it doesn't
echo "Checking for SSH key pair..."
if ! aws ec2 describe-key-pairs --key-names $KEY_NAME --region $REGION &>/dev/null; then
    echo "Creating new key pair: $KEY_NAME"
    aws ec2 create-key-pair \
        --key-name $KEY_NAME \
        --region $REGION \
        --query 'KeyMaterial' \
        --output text > ~/.ssh/$KEY_NAME.pem
    chmod 400 ~/.ssh/$KEY_NAME.pem
    echo "Key pair created and saved to ~/.ssh/$KEY_NAME.pem"
else
    echo "Key pair $KEY_NAME already exists"
fi

echo "Creating security group for Confio..."
SECURITY_GROUP_ID=$(aws ec2 create-security-group \
    --group-name $SECURITY_GROUP_NAME \
    --description "Security group for Confio instance" \
    --region $REGION \
    --query 'GroupId' \
    --output text 2>/dev/null || \
    aws ec2 describe-security-groups \
    --group-names $SECURITY_GROUP_NAME \
    --region $REGION \
    --query 'SecurityGroups[0].GroupId' \
    --output text)

echo "Security Group ID: $SECURITY_GROUP_ID"

# Add SSH access rule
aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 22 \
    --cidr 0.0.0.0/0 \
    --region $REGION 2>/dev/null || echo "SSH rule already exists"

# Add HTTP rule (port 80)
aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 80 \
    --cidr 0.0.0.0/0 \
    --region $REGION 2>/dev/null || echo "HTTP rule already exists"

# Add HTTPS rule (port 443)
aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 443 \
    --cidr 0.0.0.0/0 \
    --region $REGION 2>/dev/null || echo "HTTPS rule already exists"

# Add custom port 3000 (for Node.js apps)
aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 3000 \
    --cidr 0.0.0.0/0 \
    --region $REGION 2>/dev/null || echo "Port 3000 rule already exists"

echo "Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id $AMI_ID \
    --instance-type $INSTANCE_TYPE \
    --key-name $KEY_NAME \
    --security-group-ids $SECURITY_GROUP_ID \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
    --region $REGION \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "Instance ID: $INSTANCE_ID"
echo "Waiting for instance to be running..."

aws ec2 wait instance-running --instance-ids $INSTANCE_ID --region $REGION

echo "Instance is running!"

# Allocate Elastic IP
echo "Allocating Elastic IP..."
ALLOCATION_ID=$(aws ec2 allocate-address \
    --domain vpc \
    --region $REGION \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$INSTANCE_NAME-eip}]" \
    --query 'AllocationId' \
    --output text)

echo "Elastic IP Allocation ID: $ALLOCATION_ID"

# Associate Elastic IP with instance
echo "Associating Elastic IP with instance..."
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
echo "✅ Confio EC2 instance successfully created!"
echo "========================================="
echo "Instance ID: $INSTANCE_ID"
echo "Instance Type: $INSTANCE_TYPE"
echo "Elastic IP: $ELASTIC_IP"
echo "Instance Name: $INSTANCE_NAME"
echo ""
echo "To connect via SSH:"
echo "ssh -i ~/.ssh/$KEY_NAME.pem ec2-user@$ELASTIC_IP"
echo ""
echo "To stop the instance (Elastic IP will remain):"
echo "aws ec2 stop-instances --instance-ids $INSTANCE_ID --region $REGION"
echo ""
echo "To start the instance:"
echo "aws ec2 start-instances --instance-ids $INSTANCE_ID --region $REGION"
echo ""
echo "To terminate and release Elastic IP (when no longer needed):"
echo "aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION"
echo "aws ec2 release-address --allocation-id $ALLOCATION_ID --region $REGION"
echo ""

# Save instance details to file
cat > confio-instance-details.txt <<EOF
INSTANCE_ID=$INSTANCE_ID
ELASTIC_IP=$ELASTIC_IP
ALLOCATION_ID=$ALLOCATION_ID
SECURITY_GROUP_ID=$SECURITY_GROUP_ID
INSTANCE_NAME=$INSTANCE_NAME
REGION=$REGION
EOF

echo "Instance details saved to confio-instance-details.txt"