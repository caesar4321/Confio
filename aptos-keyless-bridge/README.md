# Aptos Keyless Bridge

A TypeScript bridge service that provides Aptos Keyless Account functionality for Python applications. This service wraps the Aptos TypeScript SDK to enable Keyless authentication features that aren't yet available in the Python SDK.

## Features

- Generate ephemeral key pairs for Keyless authentication
- Generate OAuth URLs with proper nonce handling
- Derive Keyless accounts from JWT tokens
- Sign and submit transactions using Keyless accounts
- Get account balances
- RESTful API for easy integration with any language

## Prerequisites

- Node.js 20+ 
- npm or yarn
- Docker (optional, for containerized deployment)

## Installation

### Local Development

1. Install dependencies:
```bash
npm install
```

2. Copy environment file:
```bash
cp .env.example .env
```

3. Configure your `.env` file with appropriate values

4. Run in development mode:
```bash
npm run dev
```

### Production Deployment

#### Using Docker

1. Build the Docker image:
```bash
docker build -t aptos-keyless-bridge .
```

2. Run with Docker Compose:
```bash
docker-compose up -d
```

#### Without Docker

1. Build the TypeScript code:
```bash
npm run build
```

2. Start the production server:
```bash
npm start
```

## API Endpoints

### Health Check
```
GET /api/keyless/health
```

### Generate Ephemeral Key Pair
```
POST /api/keyless/ephemeral-key
Body: {
  "expiryHours": 24  // optional, defaults to 24
}
```

### Generate OAuth URL
```
POST /api/keyless/oauth-url
Body: {
  "provider": "google",  // or "apple"
  "clientId": "your-oauth-client-id",
  "redirectUri": "http://localhost:3000/callback",
  "ephemeralPublicKey": "0x...",
  "expiryDate": "2024-08-05T18:00:00.000Z",
  "blinder": "optional-blinder-value"
}
```

### Derive Keyless Account
```
POST /api/keyless/derive-account
Body: {
  "jwt": "eyJ...",  // JWT from OAuth provider
  "ephemeralKeyPair": {
    "privateKey": "0x...",
    "publicKey": "0x...",
    "expiryDate": "2024-08-05T18:00:00.000Z",
    "nonce": "...",
    "blinder": "..."
  },
  "pepper": "optional-pepper-bytes"
}
```

### Sign and Submit Transaction
```
POST /api/keyless/sign-and-submit
Body: {
  "jwt": "eyJ...",
  "ephemeralKeyPair": { ... },
  "transaction": {
    // Aptos transaction payload
  },
  "pepper": "optional-pepper-bytes"
}
```

### Get Account Balance
```
GET /api/keyless/balance/:address
```

## Python Client Usage

A Python client wrapper is provided for easy integration:

```python
import asyncio
from aptos_keyless_client import AptosKeylessClient

async def main():
    async with AptosKeylessClient() as client:
        # Generate ephemeral key pair
        ephemeral_key = await client.generate_ephemeral_key_pair(expiry_hours=24)
        
        # Generate OAuth URL
        oauth_url = await client.generate_oauth_url(
            provider="google",
            client_id="your-client-id",
            redirect_uri="http://localhost:3000/callback",
            ephemeral_key_pair=ephemeral_key
        )
        
        # After OAuth callback, derive account
        # keyless_account = await client.derive_keyless_account(
        #     jwt=jwt_from_oauth,
        #     ephemeral_key_pair=ephemeral_key
        # )

asyncio.run(main())
```

## Environment Variables

- `PORT`: Server port (default: 3333)
- `NODE_ENV`: Environment (development/production)
- `APTOS_NETWORK`: Aptos network to use (devnet/testnet/mainnet)
- `LOG_LEVEL`: Logging level (debug/info/warn/error)
- `ALLOWED_ORIGINS`: CORS allowed origins (comma-separated)
- `JWT_SECRET`: Optional JWT secret for additional security
- `RATE_LIMIT_WINDOW_MS`: Rate limit window in milliseconds
- `RATE_LIMIT_MAX_REQUESTS`: Maximum requests per window

## Development

### Run Tests
```bash
npm test
```

### Lint Code
```bash
npm run lint
```

### Build
```bash
npm run build
```

## Migration from Sui zkLogin

This bridge service facilitates migration from Sui's zkLogin to Aptos's Keyless Accounts. Key differences:

1. **Privacy**: zkLogin uses "salt" while Keyless uses "pepper"
2. **Expiry**: zkLogin uses epoch-based expiry, Keyless uses time-based
3. **Address Derivation**: Different algorithms but similar concepts

The OAuth flow remains similar, making migration straightforward once users re-authenticate.

## Security Considerations

1. Always use HTTPS in production
2. Properly configure CORS origins
3. Consider implementing rate limiting
4. Store sensitive data (JWTs, private keys) securely
5. Use environment variables for configuration

## Troubleshooting

### Common Issues

1. **"Cannot find module '@aptos-labs/ts-sdk'"**
   - Run `npm install` to install dependencies

2. **"Network error"**
   - Check that you're using the correct Aptos network
   - Ensure your internet connection is stable

3. **"Invalid JWT"**
   - Ensure the JWT is from a supported OAuth provider
   - Check that the JWT hasn't expired

## License

MIT