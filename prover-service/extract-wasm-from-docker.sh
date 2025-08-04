#!/bin/bash

# Script to extract zkLogin.wasm from Mysten's Docker image

echo "🔍 Searching for pre-compiled zkLogin.wasm in Mysten's Docker image..."

# Pull the zkLogin prover image
echo "📥 Pulling zkLogin prover Docker image..."
docker pull mysten/zklogin:prover-a66971815c15c55e6c9e254e0f0712ef2ce26383f2787867fd39965fdf10e84f

# Create a temporary container
echo "🔧 Creating temporary container..."
CONTAINER_ID=$(docker create mysten/zklogin:prover-a66971815c15c55e6c9e254e0f0712ef2ce26383f2787867fd39965fdf10e84f)

# Search for WASM files in the container
echo "🔍 Looking for WASM files..."
docker export $CONTAINER_ID | tar -t | grep -i "\.wasm$" | head -20

# Try common locations
echo "📂 Checking common locations..."
for path in /app /opt /usr/local /home /zklogin /prover; do
    echo "Checking $path..."
    docker run --rm mysten/zklogin:prover-a66971815c15c55e6c9e254e0f0712ef2ce26383f2787867fd39965fdf10e84f ls -la $path 2>/dev/null | grep -i wasm || true
done

# Clean up
docker rm $CONTAINER_ID

echo "✅ Done searching for WASM files"