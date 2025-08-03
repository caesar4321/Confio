# EC2 zkLogin Prover Setup Guide

## Quick Start

### 1. Launch EC2 Spot Instance

```bash
# Make the script executable
chmod +x launch-ec2-spot.sh

# The script is pre-configured for eu-central-2 (Zurich) with:
# - KEY_NAME: Confio/Sui custom prover
# - SECURITY_GROUP: sg-05c61dc980a18f39d
# - VPC: vpc-0cbdcac70bc0d4434
# - AMI_ID: ami-0f673487d7e5f89ca (Amazon Linux 2023)

# Launch the instance
./launch-ec2-spot.sh
```

### 2. Configure Security Group

Add these inbound rules to your security group:
- **Port 8080**: TCP, Source: Your app servers (or 0.0.0.0/0 for testing)
- **Port 22**: TCP, Source: Your IP address (for SSH)

### 3. Update Your Application

After the instance launches, update your `.env` file:
```bash
EC2_PROVER_URL=http://YOUR_EC2_PUBLIC_IP:8080/v1
```

Then start the EC2 proxy service:
```bash
node index-ec2.js
```

## Manual Setup (Alternative)

### 1. Launch Instance via AWS Console

1. Go to EC2 Dashboard → Launch Instance
2. Choose:
   - **Name**: zkLogin-Prover
   - **AMI**: Amazon Linux 2023 (x86_64)
   - **Instance Type**: t3.small
   - **Key Pair**: Select your existing key pair
   - **Network**: Default VPC is fine
   - **Security Group**: Create new or use existing (must allow port 8080)
   - **Storage**: 20 GB gp3
   - **Advanced Details**:
     - **Purchasing option**: Spot instances
     - **Maximum price**: $0.0104 (or use "Use on-demand price as max")

3. Launch the instance

### 2. SSH to Instance and Run Setup

```bash
# SSH to your instance
ssh -i your-key.pem ec2-user@YOUR_EC2_PUBLIC_IP

# Download and run setup script
curl -O https://raw.githubusercontent.com/YOUR_REPO/ec2-setup.sh
chmod +x ec2-setup.sh
./ec2-setup.sh
```

### 3. Verify Installation

```bash
# Check if Docker is running
docker ps

# Check prover health
curl http://localhost:8080/health

# View logs
docker logs zklogin-prover
```

## Cost Optimization

### Spot Instance Savings
- **On-Demand**: ~$0.0416/hour ($30.36/month)
- **Spot**: ~$0.0104/hour ($7.59/month)
- **Savings**: 74% (~$22.77/month)

### Additional Cost Savings
1. **Use t3.micro** if load is light (1GB RAM): ~$0.0026/hour spot
2. **Schedule start/stop** for business hours only
3. **Use Reserved Instances** for long-term (1-3 year) commitment

## Production Considerations

### 1. High Availability
```bash
# Use Auto Scaling Group with spot instances
aws autoscaling create-auto-scaling-group \
  --auto-scaling-group-name zklogin-prover-asg \
  --min-size 1 --max-size 3 --desired-capacity 2 \
  --mixed-instances-policy file://mixed-instances-policy.json
```

### 2. Persistent Storage
```bash
# Create EBS volume for data persistence
aws ec2 create-volume --size 20 --volume-type gp3 \
  --availability-zone us-east-1a --tag-specifications \
  'ResourceType=volume,Tags=[{Key=Name,Value=zklogin-data}]'
```

### 3. Monitoring
- Set up CloudWatch alarms for:
  - Instance health checks
  - Spot instance interruption notices
  - High CPU/memory usage
  - API response times

### 4. Security
- Use Systems Manager Session Manager instead of SSH
- Enable VPC Flow Logs
- Use AWS Secrets Manager for any API keys
- Enable GuardDuty for threat detection

## Troubleshooting

### Docker won't start
```bash
sudo systemctl status docker
sudo systemctl restart docker
sudo usermod -a -G docker $USER
# Log out and back in
```

### Prover health check fails
```bash
# Check if container is running
docker ps -a

# View logs
docker logs zklogin-prover

# Restart container
docker restart zklogin-prover
```

### Out of memory errors
```bash
# Check memory usage
free -h
docker stats

# Increase swap space
sudo dd if=/dev/zero of=/swapfile bs=128M count=16
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Spot instance interrupted
- Check CloudWatch for interruption notice
- Instance will automatically restart if using persistent spot request
- Consider using Spot Fleet for automatic replacement

## Updating the Prover

```bash
# SSH to instance
ssh -i your-key.pem ec2-user@YOUR_EC2_IP

# Pull latest image
cd ~/zklogin-ceremony-contributions
docker-compose pull

# Restart with new image
docker-compose down
docker-compose up -d
```

## Backup and Recovery

### Backup zkLogin data
```bash
# Create backup
tar -czf zklogin-backup-$(date +%Y%m%d).tar.gz data/

# Upload to S3
aws s3 cp zklogin-backup-*.tar.gz s3://your-backup-bucket/
```

### Restore from backup
```bash
# Download from S3
aws s3 cp s3://your-backup-bucket/zklogin-backup-20240115.tar.gz .

# Extract
tar -xzf zklogin-backup-20240115.tar.gz

# Restart services
docker-compose restart
```