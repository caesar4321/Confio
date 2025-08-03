# zkLogin Prover Service Setup Guide

This guide will help you set up a zkLogin prover service that supports custom audiences for Apple/Google Login.

## Problem Summary

The Mysten Labs zkLogin prover service doesn't support custom audiences, which is required for your Apple/Google Login implementation. You need a prover service that can generate real zkProofs with your specific audience configuration.

## Available Options

### Option 1: Shinami zkLogin Prover API (Recommended)

Shinami provides a production-ready zkLogin prover API that **supports custom audiences**.

**Pros:**
- No Docker required
- Supports custom audiences for Apple/Google Login
- Fast response times (~3 seconds)
- Production-ready with high availability
- Works on Testnet and Mainnet

**Cons:**
- Requires API key (free tier available)
- Rate limited to 2 proofs per address per minute
- External dependency

**Setup:**
1. Sign up for a Shinami account at https://app.shinami.com/
2. Create a new project and get your Wallet Access Key
3. Update your `.env` file:
   ```
   EXTERNAL_ZKLOGIN_PROVER_URL=https://api.us1.shinami.com/sui/zkprover/v1
   EXTERNAL_PROVER_API_KEY=your_shinami_wallet_access_key_here
   USE_MOCK_PROVER=false
   ```

### Option 2: Interest Protocol Docker Setup (Self-Hosted)

Run your own zkLogin prover using Docker containers.

**Pros:**
- Full control over the service
- No external dependencies
- No rate limits
- Supports custom audiences

**Cons:**
- Requires Docker (which you mentioned is "too heavy")
- Needs 16GB+ RAM for good performance
- More complex setup

**Setup:**
1. Clone Interest Protocol's zkLogin prover:
   ```bash
   git clone https://github.com/interest-protocol/zk-login-prover.git
   cd zk-login-prover
   ```

2. Download the zkey file:
   ```bash
   # For testnet
   wget -O - https://raw.githubusercontent.com/sui-foundation/zklogin-ceremony-contributions/main/download-test-zkey.sh | bash
   ```

3. Start the service:
   ```bash
   docker-compose up -d
   ```

4. Update your `.env` file:
   ```
   EXTERNAL_ZKLOGIN_PROVER_URL=http://localhost:8001/v1
   USE_MOCK_PROVER=false
   ```

### Option 3: Continue with Mock Proofs (Development Only)

Use mock proofs while developing the UI, then switch to a real prover for production.

**Setup:**
```
USE_MOCK_PROVER=true
```

## Quick Start with Shinami (Recommended)

Since you want a Node.js solution without Docker, Shinami is the best option:

1. **Get a Shinami API Key:**
   - Go to https://app.shinami.com/
   - Sign up for a free account
   - Create a new project
   - Copy your Wallet Access Key

2. **Configure the prover service:**
   ```bash
   cd /Users/julian/Confio/prover-service
   cp .env.example .env
   ```

3. **Edit `.env`:**
   ```
   EXTERNAL_ZKLOGIN_PROVER_URL=https://api.us1.shinami.com/sui/zkprover/v1
   EXTERNAL_PROVER_API_KEY=your_key_here
   USE_MOCK_PROVER=false
   PORT=3001
   ```

4. **Start the service:**
   ```bash
   npm start
   ```

## Testing the Setup

Once configured, test your zkLogin flow:

1. The iPhone app will send JWT + ephemeral key data to your prover service
2. Your prover service will forward the request to Shinami (or other configured service)
3. Shinami will generate a real zkProof that works with your custom audience
4. The proof will be returned to create a valid zkLogin signature

## Important Notes

- Shinami's free tier should be sufficient for development and testing
- The proof generation takes ~3 seconds, so implement appropriate loading states
- Each proof can be cached and reused for the session
- Make sure your JWT audience matches your OAuth app configuration

## Next Steps

1. Choose your preferred option (Shinami recommended for Node.js without Docker)
2. Configure the `.env` file
3. Restart the prover service
4. Test with your iPhone app to verify real zkProofs are being generated

The prover service is already configured to handle different external services automatically based on the URL pattern.