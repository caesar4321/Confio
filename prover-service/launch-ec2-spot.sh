#!/bin/bash

# Simple script to launch EC2 spot instance for zkLogin prover
# Prerequisites: AWS CLI configured with proper credentials

# Configuration
INSTANCE_TYPE="t3.small"
AMI_ID="ami-006b3a0f02bfbc190"  # Amazon Linux 2023 in eu-central-2 (Zurich)
KEY_NAME="Sui custom prover"  # Your key pair name
SECURITY_GROUP="sg-05c61dc980a18f39d"  # Your security group ID
VPC_ID="vpc-0cbdcac70bc0d4434"  # Your VPC ID
REGION="eu-central-2"            # Zurich region
MAX_PRICE="0.0104"              # Maximum spot price (t3.small on-demand is ~$0.0416/hr)

echo "🚀 Launching EC2 spot instance for zkLogin prover..."

# Create user data script
cat > /tmp/user-data.sh << 'EOF'
#!/bin/bash
# Log output
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "Starting zkLogin prover setup..."

# Install Docker
yum update -y
yum install -y docker git
systemctl start docker
systemctl enable docker
usermod -a -G docker ec2-user

# Install docker-compose
curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Setup zkLogin prover
cd /home/ec2-user
git clone https://github.com/yourusername/zklogin-prover-setup.git prover
cd prover

# Create docker-compose.yml
cat > docker-compose.yml << 'COMPOSE'
version: '3.8'
services:
  prover:
    image: mysten/zklogin:prover-a66971815c15c55e6c9e254e0f0712ef2ce26383f2787867fd39965fdf10e84f
    container_name: zklogin-prover
    ports:
      - "8080:8080"
    environment:
      - PROVER_PORT=8080
      - PROVER_HOST=0.0.0.0
    restart: unless-stopped
    volumes:
      - ./data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
COMPOSE

# Start the prover
mkdir -p data
docker-compose up -d

# Setup auto-restart on reboot
echo "@reboot cd /home/ec2-user/prover && /usr/local/bin/docker-compose up -d" | crontab -

echo "zkLogin prover setup complete!"
EOF

# Use AWS profile if set
AWS_PROFILE=${AWS_PROFILE:-default}
echo "Using AWS profile: $AWS_PROFILE"

# Request spot instance
INSTANCE_ID=$(aws ec2 run-instances \
    --profile "$AWS_PROFILE" \
    --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SECURITY_GROUP" \
    --instance-market-options "MarketType=spot,SpotOptions={MaxPrice=$MAX_PRICE,SpotInstanceType=persistent,InstanceInterruptionBehavior=stop}" \
    --user-data file:///tmp/user-data.sh \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=zkLogin-Prover-Spot},{Key=Environment,Value=production}]" \
    --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=30,VolumeType=gp3,DeleteOnTermination=true}" \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "✅ Spot instance requested: $INSTANCE_ID"

# Wait for instance to be running
echo "⏳ Waiting for instance to start..."
aws ec2 wait instance-running --profile "$AWS_PROFILE" --region "$REGION" --instance-ids "$INSTANCE_ID"

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --profile "$AWS_PROFILE" \
    --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "
✅ EC2 Spot Instance Launched Successfully!

Instance ID: $INSTANCE_ID
Public IP: $PUBLIC_IP
Prover URL: http://$PUBLIC_IP:8080

🔒 Security Group Configuration Required:
Please ensure your security group ($SECURITY_GROUP) allows:
- Inbound TCP port 8080 from your app servers
- Inbound TCP port 22 from your IP (for SSH)

📋 Next Steps:
1. Wait 2-3 minutes for Docker to start
2. Check health: curl http://$PUBLIC_IP:8080/health
3. Update your app's prover URL to: http://$PUBLIC_IP:8080/v1
4. SSH to instance: ssh -i your-key.pem ec2-user@$PUBLIC_IP

💡 Cost Savings:
- Spot price: ~\$0.0104/hour (74% savings)
- On-demand price: ~\$0.0416/hour
- Monthly savings: ~\$22.46 (if running 24/7)

⚠️  Important:
- Spot instances can be interrupted with 2-minute notice
- Consider using Elastic IP for production
- Set up CloudWatch alarms for monitoring
"

# Clean up
rm -f /tmp/user-data.sh