# zkLogin Prover Setup Guide

This guide explains how to set up a real zkLogin prover service to generate valid Groth16 proofs for Sui zkLogin authentication.

## Current Status

The prover service currently returns mock proof data. To enable real zkLogin transactions, you need to set up an actual zkLogin prover.

## Options for zkLogin Proof Generation

### Option 1: Sui's Official Docker Prover (Recommended)

1. **Download Required Resources**:
   ```bash
   # Download prover Docker images
   docker pull mysten/zklogin-prover:latest
   docker pull mysten/zklogin-prover-fe:latest
   
   # Download the zkey file (Groth16 proving key)
   wget https://github.com/MystenLabs/sui/raw/main/zklogin/zklogin.zkey
   
   # Verify the zkey file hash
   # Expected Blake2b hash: [insert correct hash from Sui docs]
   ```

2. **Run the Prover Service**:
   ```bash
   # Run the prover backend
   docker run -d \
     --name zklogin-prover \
     -p 8080:8080 \
     -v $(pwd)/zklogin.zkey:/app/zklogin.zkey \
     mysten/zklogin-prover:latest
   
   # Run the prover frontend
   docker run -d \
     --name zklogin-prover-fe \
     -p 8081:8081 \
     -e PROVER_URI=http://localhost:8080 \
     mysten/zklogin-prover-fe:latest
   ```

3. **Update the Prover Service Code**:
   ```javascript
   // In prover-service/index.js, replace the mock proof generation with:
   const proverResponse = await fetch('http://localhost:8081/v1', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({
       jwt,
       extendedEphemeralPublicKey,
       maxEpoch: maxEpoch.toString(),
       randomness,
       salt,
       keyClaimName
     })
   });
   
   if (!proverResponse.ok) {
     throw new Error(`Prover error: ${await proverResponse.text()}`);
   }
   
   const proverResult = await proverResponse.json();
   const proof = proverResult.proof;
   ```

### Option 2: Shinami's Managed Prover Service

**Note**: Shinami may not support custom audiences like your Apple/Google setup.

1. Sign up for a Shinami account and get an API key
2. Use their prover endpoint (check their docs for the latest URL)

### Option 3: Build from Source

For maximum control and performance:

1. Clone Sui's rapidsnark implementation:
   ```bash
   git clone https://github.com/MystenLabs/rapidsnark
   cd rapidsnark
   npm install
   npm run build
   ```

2. Set up the prover with the zkLogin circuit

## Important Considerations

### Custom Audience Support

The zkLogin circuit has restrictions:
- `aud` (audience) field: Maximum 120 characters
- Custom audiences like yours should work as long as they're within limits
- The prover doesn't validate the audience - it just generates proofs

### Performance Requirements

- Recommended: 16 vCPU / 64GB RAM for production
- Proof generation typically takes 2-5 seconds
- Consider using a queue system for high traffic

### Security

- Keep the prover service internal (not exposed to the internet)
- Only your backend should call the prover
- The zkey file is public (from the trusted setup ceremony)

## Testing the Prover

Once set up, test with:

```bash
curl -X POST http://localhost:8081/v1 \
  -H "Content-Type: application/json" \
  -d '{
    "jwt": "your.jwt.token",
    "extendedEphemeralPublicKey": "base64_pubkey",
    "maxEpoch": "227",
    "randomness": "base64_randomness",
    "salt": "base64_salt",
    "keyClaimName": "sub"
  }'
```

Expected response:
```json
{
  "proof": {
    "a": ["0x...", "0x..."],
    "b": [["0x...", "0x..."], ["0x...", "0x..."]],
    "c": ["0x...", "0x..."]
  }
}
```

## Troubleshooting

1. **"Circuit size mismatch"**: Ensure you're using the correct zkey file
2. **"Invalid JWT"**: Check JWT format and required claims (sub, aud, iss)
3. **Performance issues**: Increase Docker container resources
4. **Custom audience rejected**: Verify audience length < 120 characters

## Next Steps

After setting up the prover:
1. Update `prover-service/index.js` to call the real prover
2. Test with your iPhone app
3. Monitor performance and scale as needed