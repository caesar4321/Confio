# Custom zkLogin Prover Implementation Guide

## Overview

This custom zkLogin prover implementation maintains compatibility with your 32-byte salt while supporting various proof generation backends.

## Key Features

1. **32-byte Salt Support**: Maintains wallet address compatibility
2. **Multiple Backends**: Mock, EC2 Docker, or future local implementation
3. **Deterministic Addresses**: Same salt = same wallet address
4. **Apple Sign In Support**: Handles Apple's special JWT requirements

## Architecture

```
Client (React Native)
    ↓ (32-byte salt)
Django Backend
    ↓ (HTTP request)
Custom Prover Service (localhost:3001)
    ↓ (adapts if needed)
Backend Options:
  - Mock Prover (development)
  - EC2 Docker Prover (production)
  - Local snarkjs (future)
```

## Current Implementation Status

### ✅ Completed
- Custom prover service with 32-byte salt support
- Mock proof generation for development
- EC2 Docker prover adapter (with salt adaptation)
- Integration with Django backend

### 🚧 In Progress
- EC2 prover testing with real proofs
- Production deployment configuration

### 📋 Future Work
- Local snarkjs implementation with zkLogin circuit files
- Full 32-byte native support without adaptation

## Configuration

### Development Mode (Mock Proofs)

```bash
# In prover-service/.env
USE_MOCK_PROVER=true
PORT=3001
```

### Production Mode (EC2 Docker Prover)

```bash
# In prover-service/.env
USE_MOCK_PROVER=false
EC2_PROVER_URL=http://YOUR_EC2_IP:8080/v1
PORT=3001
```

## Running the Service

### Start the Custom Prover

```bash
cd prover-service
npm install  # First time only
node index.js
```

### Verify It's Working

```bash
# Health check
curl http://localhost:3001/health

# Should return:
{
  "status": "ok",
  "mode": "mock",  # or "external"
  "proverUrl": "none",  # or EC2 URL
  "timestamp": "...",
  "saltSupport": "32-byte",
  "customProver": true
}
```

## Salt Adaptation Strategy

When using external provers (EC2 Docker) that expect 16-byte values:

1. **Address Generation**: Always uses full 32-byte salt
2. **Proof Generation**: Adapts salt/randomness using SHA256 hash truncation
3. **Result**: Maintains correct wallet addresses while generating valid proofs

```javascript
// Adaptation method (in custom-zklogin-prover.js)
adaptToProverRequirements(bytes32) {
  const hash = crypto.createHash('sha256').update(bytes32).digest();
  return Buffer.from(hash.slice(0, 16)).toString('base64');
}
```

## Integration with Django

The Django backend automatically uses the custom prover:

```python
# In config/settings.py
PROVER_SERVICE_URL = 'http://localhost:3001'

# In prover/schema.py
response = requests.post(
    f"{settings.PROVER_SERVICE_URL}/generate-proof",
    json=prover_payload,
    timeout=30
)
```

## Testing the Full Flow

### 1. Start All Services

```bash
# Terminal 1: Django backend
make runserver

# Terminal 2: Custom prover
cd prover-service && node index.js

# Terminal 3: BCS microservice
cd bcs-zklogin-service && npm start
```

### 2. Test Login Flow

- Open React Native app
- Sign in with Google/Apple
- Check logs for 32-byte salt generation
- Verify consistent Sui address

### 3. Test Transaction Signing

With mock proofs, transactions won't validate on-chain, but you can test:
- Transaction construction
- Signature generation
- UI flow completion

## Production Deployment

### Option 1: EC2 with Docker Prover

1. Launch EC2 instance with Docker prover
2. Update `EC2_PROVER_URL` in `.env`
3. Set `USE_MOCK_PROVER=false`
4. Deploy custom prover service

### Option 2: Integrated Deployment

Deploy custom prover alongside Django:

```nginx
# nginx.conf
location /prover/ {
    proxy_pass http://localhost:3001/;
    proxy_set_header Host $host;
}
```

## Troubleshooting

### "Salt must be 32 bytes" Error
- Ensure client is sending base64-encoded 32-byte values
- Check `generateZkLoginSalt` function in React Native

### "External prover failed" Error
- Verify EC2 instance is running
- Check network connectivity
- Review prover logs for specific errors

### Address Mismatch Issues
- Ensure salt generation is deterministic
- Verify same account context (type, index) is used
- Check that salt isn't being truncated prematurely

## Security Considerations

1. **Mock Mode**: Only for development - clearly warn users
2. **Salt Handling**: Never log full salt values
3. **JWT Validation**: Always validate JWT structure and claims
4. **Error Messages**: Don't expose internal details in production

## Future Enhancements

### Local Proof Generation

To implement local proof generation:

1. Obtain zkLogin circuit files from Sui
2. Implement circuit input preparation
3. Use snarkjs for proof generation
4. Remove external prover dependency

### Performance Optimization

- Cache proof generation for same inputs
- Implement proof pre-generation
- Use worker threads for CPU-intensive operations

## Conclusion

This custom prover implementation provides a bridge between your 32-byte salt requirement and various zkLogin proof backends. It maintains wallet compatibility while allowing flexibility in proof generation methods.