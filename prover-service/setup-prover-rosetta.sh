#!/bin/bash

echo "🚀 Setting up zkLogin prover with Rosetta 2 emulation for M4 Mac..."

# Create directory for prover resources
mkdir -p zklogin-prover-resources
cd zklogin-prover-resources

# Download Docker images with platform emulation
echo "📥 Pulling Docker images with x86_64 emulation..."
docker pull --platform linux/amd64 mysten/zklogin:prover-a66971815c15ba10c699203c5e3826a18eabc4ee
docker pull --platform linux/amd64 mysten/zklogin:prover-fe-a66971815c15ba10c699203c5e3826a18eabc4ee

# Check if zkey already exists (from previous attempt)
if [ -f "../zk-login-prover/zklogin-ceremony-contributions/zkLogin-test.zkey" ]; then
    echo "✅ Found existing zkLogin-test.zkey, copying it..."
    cp ../zk-login-prover/zklogin-ceremony-contributions/zkLogin-test.zkey ./zkLogin.zkey
else
    echo "📥 Downloading zkey file (~3GB, this will take a while)..."
    curl -L https://github.com/sui-foundation/zklogin-ceremony-contributions/raw/main/zkLogin-test.zkey -o zkLogin.zkey
fi

# Create docker-compose.yml with Rosetta platform specification
cat <<EOF > docker-compose.yml
services:
  prover:
    image: mysten/zklogin:prover-a66971815c15ba10c699203c5e3826a18eabc4ee
    platform: linux/amd64  # Force Rosetta 2 emulation
    container_name: zklogin-prover
    ports:
      - "8000:8080"
    volumes:
      - ./zkLogin.zkey:/app/binaries/zkLogin.zkey
    environment:
      - ZKEY=/app/binaries/zkLogin.zkey
      - WITNESS_BINARIES=/app/binaries
      - RUST_LOG=info
    restart: unless-stopped

  prover-fe:
    image: mysten/zklogin:prover-fe-a66971815c15ba10c699203c5e3826a18eabc4ee
    platform: linux/amd64  # Force Rosetta 2 emulation
    container_name: zklogin-prover-fe
    ports:
      - "8001:8080"
    environment:
      - PROVER_URI=http://prover:8080/input
      - NODE_ENV=production
      - DEBUG=zkLogin:info,jwks
    depends_on:
      - prover
    restart: unless-stopped
EOF

# Start containers
echo "🐳 Starting Docker containers with Rosetta 2 emulation..."
docker-compose up -d

echo ""
echo "✅ zkLogin prover setup complete!"
echo "   - API endpoint: http://localhost:8001/v1"
echo "   - Test with: curl http://localhost:8001/ping"
echo ""
echo "⚠️  Note: Rosetta 2 emulation adds ~20-30% overhead"
echo "   Proofs will take ~1.5-2.5s instead of 1-2s"
echo "   For production, use native x86_64 instance on AWS"