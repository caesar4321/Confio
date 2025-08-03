# zkLogin Prover Service

This service provides zkLogin proof generation for the Confío wallet application.

## Overview

The zkLogin prover generates zero-knowledge proofs for Sui blockchain authentication using OAuth providers (Google, Apple). This allows users to control blockchain addresses using their existing OAuth accounts.

## Setup Options

### Option 1: Mock Prover (Development Only)
```bash
# Start mock prover
node index-mock.js
```
⚠️ Mock proofs won't work on mainnet!

### Option 2: EC2 Docker Prover (Production)
```bash
# 1. Launch EC2 instance
./launch-ec2-spot.sh

# 2. Configure security group
./configure-security-group.sh

# 3. Update .env.production with your EC2 IP
# EC2_PROVER_URL=http://YOUR_EC2_IP:8080/v1

# 4. Start local proxy
node index-ec2.js
```

### Option 3: External Prover (Mysten)
```bash
# Uses Mysten's public prover (limited to standard OAuth)
node index-mysten.js
```

## Configuration

### Environment Variables (.env.production)
```bash
# EC2 Configuration
EC2_REGION=eu-central-2
EC2_KEY_NAME=Confio/Sui custom prover
EC2_SECURITY_GROUP=sg-05c61dc980a18f39d
EC2_VPC_ID=vpc-0cbdcac70bc0d4434
EC2_KEY_PATH=/Users/julian/Confio/Sui custom prover.pem

# Prover URL (update after launching EC2)
EC2_PROVER_URL=http://YOUR_EC2_IP:8080/v1

# Service port
PORT=3001
```

### Security
- `.env.production` is encrypted with git-crypt
- EC2 key pair should be stored securely
- Security group restricts access to authorized IPs only

## API Endpoints

### POST /generate-proof
Generate a zkLogin proof.

Request:
```json
{
  "jwt": "eyJ...",
  "extendedEphemeralPublicKey": "base64...",
  "maxEpoch": "235",
  "randomness": "base64...",
  "salt": "base64...",
  "keyClaimName": "sub",
  "audience": "apple"
}
```

Response:
```json
{
  "proof": {
    "a": ["0x...", "0x..."],
    "b": [["0x...", "0x..."], ["0x...", "0x..."]],
    "c": ["0x...", "0x..."]
  },
  "suiAddress": "0x...",
  "mode": "ec2-docker",
  "duration_ms": 1234
}
```

### GET /health
Health check endpoint.

## Troubleshooting

### "Invalid prover service response"
- Ensure the prover returns both `proof` and `suiAddress`
- Check that all required fields are present in the request

### "Nonce does not match"
- This occurs with Shinami when using Firebase OAuth
- Use EC2 Docker prover or Mysten's external prover instead

### EC2 Connection Issues
```bash
# Check instance status
aws ec2 describe-instances --region eu-central-2 \
  --filters "Name=tag:Name,Values=zkLogin-Prover-Spot" \
  --query 'Reservations[*].Instances[*].[InstanceId,State.Name,PublicIpAddress]'

# SSH to instance
./ssh-to-prover.sh

# Check Docker logs
docker logs zklogin-prover
```

## Cost Optimization

- **Spot Instances**: ~74% savings vs on-demand
- **t3.small**: $0.0104/hour spot vs $0.0416/hour on-demand
- **Auto-stop**: Configure CloudWatch to stop during off-hours
- **Reserved Instances**: Consider for long-term usage

## Security Best Practices

1. **Network Security**
   - Use VPC peering for internal communication
   - Restrict security group to specific IPs
   - Enable VPC Flow Logs

2. **Access Control**
   - Use IAM roles, not access keys
   - Enable CloudTrail for audit logs
   - Use Systems Manager Session Manager

3. **Data Protection**
   - Encrypt EBS volumes
   - Use git-crypt for sensitive configs
   - Rotate credentials regularly

## Monitoring

### CloudWatch Metrics
- CPU utilization
- Memory usage
- Network throughput
- API response times

### Alarms
- Spot instance interruption
- High CPU/memory usage
- Health check failures
- API errors

## Support

For issues or questions:
- Check logs: `docker logs zklogin-prover`
- Review CloudWatch metrics
- Contact the development team