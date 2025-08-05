# Aptos Keyless Account - Quick Start Guide

This guide shows how to use Aptos Keyless Accounts in your Python application using a TypeScript bridge service.

## Why a TypeScript Bridge?

The Aptos Python SDK doesn't support Keyless Accounts yet, so we use a lightweight TypeScript service that exposes REST APIs for Python to consume.

## Setup

### 1. Start the TypeScript Bridge Service

```bash
cd aptos-keyless-bridge
npm install
npm run build
npm start
```

The service will run on `http://localhost:3333`

### 2. Use the Python Client

```python
import asyncio
from aptos_keyless_client import AptosKeylessClient

async def main():
    async with AptosKeylessClient() as client:
        # Generate ephemeral key pair
        ephemeral_key = await client.generate_ephemeral_key_pair()
        print(f"Generated key: {ephemeral_key.public_key[:32]}...")
        
        # Generate OAuth URL for user login
        oauth_url = await client.generate_oauth_url(
            provider="google",
            client_id="your-client-id",
            redirect_uri="http://localhost:3000/callback",
            ephemeral_key_pair=ephemeral_key
        )
        print(f"Login URL: {oauth_url}")
        
        # After user logs in and you get the JWT...
        # keyless_account = await client.derive_keyless_account(
        #     jwt=jwt_from_oauth,
        #     ephemeral_key_pair=ephemeral_key
        # )

asyncio.run(main())
```

## Key Differences from zkLogin

| Feature | zkLogin (Sui) | Keyless (Aptos) |
|---------|---------------|-----------------|
| Python SDK | ✅ Native support | ❌ TypeScript bridge needed |
| Privacy | Salt-based | Pepper-based |
| Key Expiry | Epoch-based | Time-based |
| Address Format | Sui format | Aptos format |

## OAuth Setup

1. **Google OAuth**:
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Create OAuth 2.0 credentials
   - Add redirect URI: `http://localhost:3000/callback`

2. **Apple Sign In**:
   - Configure in Apple Developer portal
   - Enable "Sign in with Apple" capability

## Running the Integration Test

```bash
# Make sure TypeScript service is NOT already running
python test_aptos_integration.py
```

## Production Considerations

1. **Security**: 
   - Use HTTPS in production
   - Secure the TypeScript service behind authentication
   - Store ephemeral keys securely

2. **Performance**:
   - Consider caching derived accounts
   - Use connection pooling in Python client

3. **Error Handling**:
   - Implement retry logic
   - Handle network failures gracefully

## Next Steps

1. Set up OAuth providers (Google/Apple)
2. Implement the OAuth callback handler
3. Integrate with your existing authentication flow
4. Test with real transactions on devnet

## Troubleshooting

- **Port 3333 already in use**: Kill the existing process or change the port
- **TypeScript build errors**: Make sure you have Node.js 20+
- **Python import errors**: Install the client with dependencies