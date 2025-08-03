#!/bin/bash

# zkLogin Prover Setup Script
# This script helps download and set up the Sui zkLogin prover

set -e

echo "🔧 zkLogin Prover Setup Script"
echo "==============================="

# Create a directory for prover resources
PROVER_DIR="./zklogin-prover-resources"
mkdir -p "$PROVER_DIR"
cd "$PROVER_DIR"

# Download the zkey file
echo "📥 Downloading zkLogin proving key (zkey file)..."
if [ ! -f "zklogin.zkey" ]; then
    # Note: Update this URL with the actual Sui zkLogin zkey file URL
    echo "⚠️  Please download the zklogin.zkey file from Sui's official resources"
    echo "   Check: https://github.com/MystenLabs/sui"
    echo "   Place it in: $PROVER_DIR/zklogin.zkey"
else
    echo "✅ zklogin.zkey already exists"
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

echo ""
echo "📦 Pulling zkLogin prover Docker images..."
docker pull mysten/zklogin-prover:latest || echo "⚠️  Could not pull prover image"
docker pull mysten/zklogin-prover-fe:latest || echo "⚠️  Could not pull prover-fe image"

# Create docker-compose.yml
echo ""
echo "📝 Creating docker-compose.yml..."
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  zklogin-prover:
    image: mysten/zklogin-prover:latest
    container_name: zklogin-prover
    ports:
      - "8080:8080"
    volumes:
      - ./zklogin.zkey:/app/zklogin.zkey:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/ping"]
      interval: 30s
      timeout: 10s
      retries: 3

  zklogin-prover-fe:
    image: mysten/zklogin-prover-fe:latest
    container_name: zklogin-prover-fe
    ports:
      - "8081:8081"
    environment:
      - PROVER_URI=http://zklogin-prover:8080
    depends_on:
      - zklogin-prover
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8081/ping"]
      interval: 30s
      timeout: 10s
      retries: 3
EOF

echo "✅ docker-compose.yml created"

echo ""
echo "🚀 To start the prover services, run:"
echo "   cd $PROVER_DIR"
echo "   docker-compose up -d"
echo ""
echo "📍 The prover will be available at:"
echo "   - Backend: http://localhost:8080"
echo "   - Frontend: http://localhost:8081"
echo ""
echo "⚠️  Remember to:"
echo "   1. Download the zklogin.zkey file if not already present"
echo "   2. Update prover-service/index.js to use http://localhost:8081/v1"
echo "   3. Test with your JWT tokens before production use"