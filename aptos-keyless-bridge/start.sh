#!/bin/bash

# Simple start script for the Aptos Keyless Bridge

echo "Starting Aptos Keyless Bridge..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
fi

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Check if dist directory exists
if [ ! -d "dist" ]; then
    echo "Building TypeScript..."
    npm run build
fi

# Start the server
echo "Starting server on port ${PORT:-3333}..."
npm start