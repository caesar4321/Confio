#!/bin/bash

# Test EC2 zkLogin Prover
# Run this after updating EC2_PROVER_URL in .env.production

echo "🧪 Testing EC2 zkLogin Prover..."

# Load configuration
if [ -f .env.production ]; then
    export $(cat .env.production | grep -v '^#' | xargs)
else
    echo "❌ .env.production not found!"
    echo "Please create it with: EC2_PROVER_URL=http://YOUR_EC2_IP:8080/v1"
    exit 1
fi

# Check if EC2_PROVER_URL is set
if [[ "$EC2_PROVER_URL" == *"YOUR_EC2_PUBLIC_IP"* ]]; then
    echo "❌ Please update EC2_PROVER_URL in .env.production"
    exit 1
fi

# Extract base URL
BASE_URL=$(echo $EC2_PROVER_URL | sed 's|/v1$||')

echo "📍 Testing prover at: $BASE_URL"

# Test health endpoint
echo -e "\n1️⃣ Testing health endpoint..."
HEALTH=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$BASE_URL/health")
HTTP_CODE=$(echo "$HEALTH" | grep HTTP_CODE | cut -d: -f2)
RESPONSE=$(echo "$HEALTH" | grep -v HTTP_CODE)

if [ "$HTTP_CODE" == "200" ]; then
    echo "✅ Health check passed!"
    echo "Response: $RESPONSE"
else
    echo "❌ Health check failed! HTTP $HTTP_CODE"
    echo "Response: $RESPONSE"
    exit 1
fi

# Test proof generation with mock data
echo -e "\n2️⃣ Testing proof generation..."
PROOF_RESPONSE=$(curl -s -X POST "$EC2_PROVER_URL" \
  -H "Content-Type: application/json" \
  -w "\nHTTP_CODE:%{http_code}" \
  -d '{
    "jwt": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InRlc3QifQ.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhdWQiOiJ0ZXN0LWNsaWVudC1pZCIsInN1YiI6IjEyMzQ1Njc4OTAiLCJpYXQiOjE3MDAwMDAwMDAsImV4cCI6MTcwMDAwMzYwMCwibm9uY2UiOiJ0ZXN0LW5vbmNlIn0.test-signature",
    "extendedEphemeralPublicKey": "dGVzdC1lcGhlbWVyYWwtcHVibGljLWtleS10aGlzLWlzLTMyLWJ5dGVz",
    "maxEpoch": "235",
    "randomness": "dGVzdC1yYW5kb21uZXNzLXRoaXMtaXMtdGhpcnR5LXR3by1ieXRlcw==",
    "salt": "dGVzdC1zYWx0LXRoaXMtaXMtdGhpcnR5LXR3by1ieXRlcy1sb25nLQ==",
    "keyClaimName": "sub"
  }')

HTTP_CODE=$(echo "$PROOF_RESPONSE" | grep HTTP_CODE | cut -d: -f2)
RESPONSE=$(echo "$PROOF_RESPONSE" | grep -v HTTP_CODE)

if [ "$HTTP_CODE" == "200" ]; then
    echo "✅ Proof generation endpoint accessible!"
    echo "Note: This was a test with invalid JWT - actual proof will fail"
    echo "Response preview: $(echo "$RESPONSE" | head -c 200)..."
else
    echo "⚠️  Proof generation returned HTTP $HTTP_CODE"
    echo "This is expected with test data"
    echo "Response: $(echo "$RESPONSE" | head -c 500)..."
fi

# Test local proxy
echo -e "\n3️⃣ Testing local proxy..."
LOCAL_HEALTH=$(curl -s -w "\nHTTP_CODE:%{http_code}" "http://localhost:3001/health" 2>/dev/null)
LOCAL_HTTP_CODE=$(echo "$LOCAL_HEALTH" | grep HTTP_CODE | cut -d: -f2)

if [ "$LOCAL_HTTP_CODE" == "200" ]; then
    echo "✅ Local proxy is running!"
else
    echo "⚠️  Local proxy not running. Start it with: node index-ec2.js"
fi

echo -e "\n✅ EC2 zkLogin Prover is ready for use!"
echo "📋 Configuration:"
echo "   - EC2 Prover: $EC2_PROVER_URL"
echo "   - Local Proxy: http://localhost:3001"
echo "   - Mode: EC2 Docker zkLogin"