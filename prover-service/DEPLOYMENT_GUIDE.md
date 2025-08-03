# zkLogin Prover Deployment Guide

This guide covers both Shinami (recommended for quick start) and self-hosted Docker options.

## Option 1: Shinami Integration (Recommended)

### Why Shinami?
- ✅ Supports custom audiences (Apple/Google OAuth)
- ✅ No 3GB zkey download required
- ✅ Production-ready with 99.9% uptime
- ✅ Free tier available
- ⚠️ 2-3 second latency per proof
- ⚠️ Rate limit: 2 proofs per address per minute

### Quick Start

1. **Sign up for Shinami**
   ```
   https://app.shinami.com/
   - Create free account
   - Create new project
   - Go to API Keys > Wallet Services
   - Copy your Wallet Access Key
   ```

2. **Configure Environment**
   ```bash
   cd /Users/julian/Confio/prover-service
   cp .env.example .env
   
   # Edit .env:
   USE_MOCK_PROVER=false
   SHINAMI_WALLET_ACCESS_KEY=your_key_here
   PORT=3001
   ```

3. **Run Locally**
   ```bash
   # Use the Shinami implementation
   node index-shinami.js
   ```

4. **Test**
   ```bash
   node test-prover.js
   ```

## Option 2: Docker Deployment (For Production)

### Local Docker Testing

1. **Build and Run**
   ```bash
   # Build Shinami-based prover
   docker build -f Dockerfile.shinami -t zklogin-prover:shinami .
   
   # Run with your API key
   docker run -d \
     --name zklogin-prover \
     -p 3001:3001 \
     -e SHINAMI_WALLET_ACCESS_KEY=your_key_here \
     -e USE_MOCK_PROVER=false \
     zklogin-prover:shinami
   ```

2. **Using Docker Compose**
   ```bash
   # Start all services
   docker-compose up -d zklogin-prover-shinami bcs-zklogin-service
   
   # Check logs
   docker-compose logs -f zklogin-prover-shinami
   ```

### AWS EC2 Deployment

#### Architecture
```
┌─────────────────┐      ┌─────────────────┐
│   App Server    │      │  Prover Server  │
│   (t3.small)    │─────▶│   (t3.medium)   │
│  Django + API   │ HTTP │ Docker + Prover │
└─────────────────┘      └─────────────────┘
         │                        │
         └────────VPC─────────────┘
```

#### Step 1: Launch EC2 Instance

```bash
# AWS CLI command
aws ec2 run-instances \
  --image-id ami-0c02fb55956c7d316 \  # Amazon Linux 2
  --instance-type t3.medium \
  --key-name your-key \
  --security-group-ids sg-xxxxx \
  --subnet-id subnet-xxxxx \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=zklogin-prover}]' \
  --user-data file://userdata.sh
```

#### Step 2: User Data Script
Create `userdata.sh`:
```bash
#!/bin/bash
# Update system
yum update -y

# Install Docker
amazon-linux-extras install docker -y
service docker start
usermod -a -G docker ec2-user

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Clone your repo (or copy files)
cd /home/ec2-user
git clone https://github.com/yourusername/confio.git
cd confio/prover-service

# Create .env file
cat > .env << EOF
USE_MOCK_PROVER=false
SHINAMI_WALLET_ACCESS_KEY=${SHINAMI_KEY}
PORT=3001
EOF

# Start services
docker-compose up -d zklogin-prover-shinami bcs-zklogin-service

# Setup CloudWatch logs
yum install -y awslogs
systemctl start awslogsd
```

#### Step 3: Security Group
```
Inbound Rules:
- Port 3001: From App Server SG only
- Port 3002: From App Server SG only (BCS service)
- Port 22: From your IP (SSH)

Outbound Rules:
- All traffic allowed
```

#### Step 4: Update App Server
```python
# In Django settings.py
PROVER_SERVICE_URL = config('PROVER_SERVICE_URL', default='http://10.0.1.123:3001')  # Private IP
```

## Option 3: Self-Hosted with Sui Docker (Heavy)

Only use this if you need:
- Sub-second latency
- No external dependencies
- Full control

### Setup
```bash
# Download 3GB zkey
./setup-prover.sh

# Uncomment Sui services in docker-compose.yml
# Edit docker-compose.yml to use Sui prover services

# Start
docker-compose up -d zklogin-prover-backend zklogin-prover-frontend
```

⚠️ **Note**: Sui's official prover doesn't support custom audiences for Apple/Google OAuth.

## Cost Comparison

| Solution | Setup Time | Latency | Monthly Cost | Custom Audiences |
|----------|------------|---------|--------------|------------------|
| Shinami | 5 min | 2-3s | Free-$50 | ✅ Yes |
| EC2 + Shinami | 30 min | 2-3s | $15 (t3.medium) | ✅ Yes |
| EC2 + Sui Docker | 2 hours | <1s | $50 (c5.large) | ❌ No |

## Monitoring

### CloudWatch Metrics
```bash
# CPU usage alarm
aws cloudwatch put-metric-alarm \
  --alarm-name zklogin-prover-cpu \
  --alarm-description "Alert when CPU exceeds 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold
```

### Application Logs
```javascript
// Add to index-shinami.js
import winston from 'winston';

const logger = winston.createLogger({
  format: winston.format.json(),
  transports: [
    new winston.transports.File({ filename: 'prover.log' }),
    new winston.transports.Console()
  ]
});
```

## Scaling Strategy

1. **Start**: Single t3.medium with Shinami
2. **Growth**: Add CloudFront caching for repeated proofs
3. **Scale**: Multiple instances + ALB
4. **Optimize**: Move to self-hosted if >1000 proofs/day

## Troubleshooting

### "Rate limit exceeded"
- Shinami limits: 2 proofs per address per minute
- Solution: Implement client-side queueing

### "Invalid JWT"
- Check JWT hasn't expired
- Verify 'aud' matches your OAuth client ID

### High latency
- Check EC2 instance type
- Verify same AZ as app server
- Consider upgrading to c5 instance

## Best Practices

1. **Environment Variables**: Never commit API keys
2. **Health Checks**: Monitor /health endpoint
3. **Backup**: Keep mock mode as fallback
4. **Security**: Use IAM roles, not keys in production
5. **Logs**: Ship to CloudWatch or ELK stack

## Next Steps

1. Test locally with Shinami
2. Deploy to staging EC2
3. Load test with expected traffic
4. Setup monitoring/alerts
5. Deploy to production

For support, check:
- Shinami docs: https://docs.shinami.com/
- Sui zkLogin: https://docs.sui.io/concepts/cryptography/zklogin
- AWS EC2: https://docs.aws.amazon.com/ec2/