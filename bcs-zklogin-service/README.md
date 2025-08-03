# BCS zkLogin Signature Service

A Node.js microservice that creates BCS (Binary Canonical Serialization) formatted zkLogin signatures for Sui blockchain transactions.

## Purpose

Sui blockchain requires zkLogin signatures to be in BCS format for transaction execution. This service uses the official `@mysten/sui` SDK to create properly formatted zkLogin signatures that the Sui RPC will accept.

## Features

- ✅ **Official Sui SDK**: Uses `@mysten/sui/zklogin` for guaranteed compatibility
- ✅ **BCS Serialization**: Outputs proper binary format for Sui RPC
- ✅ **Multiple Providers**: Supports Apple, Google, Twitch, Facebook
- ✅ **Health Checks**: Built-in monitoring endpoint
- ✅ **Error Handling**: Comprehensive error reporting

## API Endpoints

### Health Check
```
GET /health
```

Response:
```json
{
  "status": "healthy",
  "service": "bcs-zklogin-service", 
  "timestamp": "2025-08-03T03:15:00.000Z"
}
```

### Create BCS zkLogin Signature
```
POST /bcs-signature
```

Request Body:
```json
{
  "ephemeralSignature": "base64_ephemeral_signature",
  "ephemeralPublicKey": "base64_ephemeral_public_key",
  "zkProof": {
    "a": ["0x1a2b3c...", "0x2b3c4d..."],
    "b": [["0x3c4d5e...", "0x4d5e6f..."], ["0x5e6f7a...", "0x6f7a8b..."]],
    "c": ["0x7a8b9c...", "0x8b9c0d..."]
  },
  "maxEpoch": "122",
  "subject": "000705.4c035b5cd80a40c28a58cb233ce399d3.2311",
  "audience": "apple",
  "userSalt": "base64_user_salt",
  "issuer": "https://appleid.apple.com" // optional
}
```

Response:
```json
{
  "success": true,
  "zkLoginSignature": "bcs_serialized_signature_base64",
  "bcsFormat": true,
  "metadata": {
    "issuer": "https://appleid.apple.com",
    "maxEpoch": 122,
    "audience": "apple",
    "subject": "000705.4c0..."
  }
}
```

## Setup

1. **Install Dependencies**:
```bash
cd bcs-zklogin-service
npm install
```

2. **Development**:
```bash
npm run dev
```

3. **Production Build**:
```bash
npm run build
npm start
```

## Environment Variables

- `PORT`: Service port (default: 3002)

## Integration with Django

Update your Django sponsor service to call this microservice:

```python
async def _build_zklogin_signature(cls, ...):
    # Prepare payload for BCS service
    bcs_payload = {
        "ephemeralSignature": ephemeral_sig,
        "ephemeralPublicKey": ephemeral_pubkey,
        "zkProof": zkproof,
        "maxEpoch": max_epoch,
        "subject": subject,
        "audience": audience,
        "userSalt": user_salt
    }
    
    # Call BCS service
    response = requests.post(
        "http://localhost:3002/bcs-signature",
        json=bcs_payload,
        timeout=10
    )
    
    if response.status_code == 200:
        result = response.json()
        return result['zkLoginSignature']
    else:
        raise ValueError("BCS service failed")
```

## Deployment Options

- **Local Development**: `npm run dev`
- **Docker**: Create Dockerfile for containerization
- **Cloudflare Workers**: Modify for serverless deployment
- **PM2**: Process management for production

## Security Notes

- Service should run on internal network only
- No sensitive data is logged (subjects are truncated)
- Validates all input parameters before processing
- Uses official Sui SDK for maximum security