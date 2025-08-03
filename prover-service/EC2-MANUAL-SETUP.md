# Manual EC2 Setup Instructions

Since AWS CLI is not installed, follow these steps in the AWS Console:

## 1. Launch EC2 Instance

1. **Open AWS Console**: https://eu-central-2.console.aws.amazon.com/ec2/
2. Click **"Launch Instance"**
3. Configure as follows:

### Name and tags
- **Name**: `zkLogin-Prover-Spot`

### Application and OS Images
- **AMI**: Amazon Linux 2023 (ami-0f673487d7e5f89ca)
- **Architecture**: 64-bit (x86)

### Instance type
- **Type**: `t3.small`

### Key pair
- **Key pair name**: `Confio/Sui custom prover`

### Network settings
- **VPC**: vpc-0cbdcac70bc0d4434
- **Security group**: sg-05c61dc980a18f39d
- **Auto-assign public IP**: Enable

### Storage
- **Size**: 20 GiB
- **Volume type**: gp3

### Advanced details
- **Purchasing option**: ✅ Request Spot Instances
- **Maximum price**: Per hour - Set your maximum price: `0.0104`
- **Persistent request**: ✅ Persistent request
- **Interruption behavior**: Stop

### User data
Copy and paste this script:

```bash
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
mkdir -p prover
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
```

4. Click **"Launch Instance"**

## 2. Configure Security Group

After the instance launches:

1. Go to **Security Groups** in EC2 console
2. Select `sg-05c61dc980a18f39d`
3. Click **"Edit inbound rules"**
4. Add these rules:

| Type | Protocol | Port | Source | Description |
|------|----------|------|--------|-------------|
| SSH | TCP | 22 | My IP | SSH access |
| Custom TCP | TCP | 8080 | My IP | zkLogin prover (testing) |
| Custom TCP | TCP | 8080 | Your Django Server IP/32 | zkLogin prover (production) |

## 3. Get Instance Details

1. Go to **Instances** in EC2 console
2. Find your instance (zkLogin-Prover-Spot)
3. Copy the **Public IPv4 address**

## 4. Update Configuration

Edit `/Users/julian/Confio/prover-service/.env.production`:

```bash
EC2_PROVER_URL=http://YOUR_PUBLIC_IP:8080/v1
```

## 5. SSH to Instance (after 3-5 minutes)

```bash
chmod 400 "/Users/julian/Confio/Sui custom prover.pem"
ssh -i "/Users/julian/Confio/Sui custom prover.pem" ec2-user@YOUR_PUBLIC_IP
```

## 6. Verify Installation

Once connected via SSH:

```bash
# Check Docker status
sudo docker ps

# Check prover logs
sudo docker logs zklogin-prover

# Test health endpoint
curl http://localhost:8080/health
```

## 7. Start Local Proxy

On your local machine:

```bash
cd /Users/julian/Confio/prover-service
node index-ec2.js
```

## Expected Output

When everything is working:
- Health check returns: `{"status":"ok"}`
- Docker shows zklogin-prover container running
- Local proxy connects successfully

## Troubleshooting

If the prover isn't running after 5 minutes:

```bash
# SSH to instance
ssh -i "/Users/julian/Confio/Sui custom prover.pem" ec2-user@YOUR_PUBLIC_IP

# Check user-data log
sudo cat /var/log/user-data.log

# Manually start Docker
sudo systemctl start docker
sudo usermod -a -G docker ec2-user

# Re-login to apply group changes
exit
# SSH back in

# Manually run docker-compose
cd /home/ec2-user/prover
sudo /usr/local/bin/docker-compose up -d
```