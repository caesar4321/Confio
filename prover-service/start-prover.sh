#!/bin/bash

# Start zkLogin Prover Service
# Automatically selects the right mode based on environment

echo "🚀 Starting zkLogin Prover Service..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found, using defaults"
fi

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Determine which prover to use
if [ "$USE_MOCK_PROVER" = "true" ]; then
    echo "📦 Starting in MOCK mode (development)"
    echo "⚠️  Proofs will not validate on-chain"
    node index.js
elif [ "$NODE_ENV" = "production" ] || [ "$USE_MOCK_PROVER" = "false" ]; then
    echo "🏭 Starting in PRODUCTION mode"
    echo "✅ Will generate real zkLogin proofs"
    echo "📍 Using Mysten Labs prover"
    node production-prover.js
else
    echo "🔧 Starting in DEVELOPMENT mode (mock)"
    echo "Set USE_MOCK_PROVER=false for production"
    node index.js
fi