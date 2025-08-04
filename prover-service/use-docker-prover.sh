#!/bin/bash

# Alternative: Use Mysten's Docker image as the prover (no WASM needed)

echo "🐳 Setting up Mysten's zkLogin Docker prover..."

# Run the Docker prover locally
docker run -d \
    --name zklogin-prover \
    -p 8080:8080 \
    --restart unless-stopped \
    mysten/zklogin:prover-a66971815c15c55e6c9e254e0f0712ef2ce26383f2787867fd39965fdf10e84f

echo "
✅ Docker prover running!

Prover URL: http://localhost:8080/v1

This prover includes the compiled circuit internally.
No need to compile zkLogin.wasm separately.

Test with:
curl -X POST http://localhost:8080/v1 \
    -H 'Content-Type: application/json' \
    -d '{\"jwt\":\"your-jwt-token\",\"extendedEphemeralPublicKey\":\"your-key\",\"maxEpoch\":\"10\",\"jwtRandomness\":\"100681567828351849884072155819400689117\",\"salt\":\"248191903847969014646285995941615069143\",\"keyClaimName\":\"sub\"}'
"