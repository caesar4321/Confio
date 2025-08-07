# Web3Auth + Algorand Migration Guide

## Overview
This guide documents the migration from Firebase + Google/Apple authentication to Web3Auth with Algorand blockchain integration.

## What's Been Implemented

### 1. Frontend (React Native)
- **Web3Auth SDK Integration** (`@web3auth/react-native-sdk`)
- **Algorand SDK** (`algosdk`)
- **Services Created:**
  - `web3AuthService.ts` - Handles Web3Auth authentication
  - `algorandWalletService.ts` - Manages Algorand wallet operations
  - `authServiceWeb3.ts` - Unified authentication service
- **New Screens:**
  - `AuthScreenWeb3.tsx` - New authentication screen with Web3Auth

### 2. Backend (Django)
- **Database Updates:**
  - Added Algorand fields to Account model:
    - `algorand_address` - Stores user's Algorand address
    - `web3auth_id` - Web3Auth user identifier
    - `web3auth_provider` - Provider used (google/apple)
    - `algorand_verified` - Address ownership verification status
    - `algorand_verified_at` - Verification timestamp
- **GraphQL Schema:**
  - `web3auth_schema.py` - New mutations and queries for Web3Auth
  - Mutations: `web3AuthLogin`, `updateAlgorandAddress`, `verifyAlgorandOwnership`
  - Queries: `algorandBalance`, `algorandTransactions`

### 3. Configuration Files
- `apps/src/config/web3auth.ts` - Web3Auth configuration
- `apps/.env.web3auth` - Environment variables template

## Setup Instructions

### Step 1: Web3Auth Dashboard Setup
1. Go to https://dashboard.web3auth.io/
2. Create a new project
3. Configure OAuth providers:
   - Add Google OAuth
   - Add Apple OAuth (for iOS)
4. Copy your Client ID
5. Configure redirect URLs:
   - iOS: `com.confio://auth`
   - Android: `com.confio://auth`

### Step 2: Environment Configuration
1. Copy `.env.web3auth` to `.env`
2. Update with your credentials:
```bash
WEB3AUTH_CLIENT_ID=your_client_id_here
ALGORAND_NETWORK=testnet  # or mainnet for production
```

### Step 3: Backend Setup
```bash
# Apply database migrations
./myvenv/bin/python manage.py migrate

# Start Django server
./myvenv/bin/python manage.py runserver
```

### Step 4: Frontend Setup
```bash
# Install dependencies (already done)
cd apps
npm install

# For iOS, update Info.plist with URL scheme
# Add: com.confio as URL scheme

# Run the app
npm run ios  # or npm run android
```

## Authentication Flow

### User Journey
1. User opens app → `AuthScreenWeb3`
2. User chooses Google/Apple sign-in
3. Web3Auth handles OAuth flow
4. Algorand wallet is automatically created
5. User's Algorand address is stored in backend
6. User can now:
   - View their Algorand address
   - Check balance
   - Send/receive ALGO tokens
   - Create and manage Algorand assets

### Technical Flow
```
User → Web3Auth OAuth → Get Private Key → Derive Algorand Account → Store in Backend
```

## Key Features

### Algorand Wallet Features
- **Automatic Wallet Creation**: Users get an Algorand wallet upon sign-in
- **Self-Custody**: Users control their private keys via Web3Auth
- **Transaction Support**: Send/receive ALGO tokens
- **Asset Management**: Create and manage Algorand Standard Assets (ASA)
- **Balance Checking**: Real-time balance queries

### Security Features
- **Non-Custodial**: Private keys never touch your servers
- **MPC Security**: Web3Auth uses multi-party computation
- **Session Management**: Secure session storage in Keychain
- **Address Verification**: Optional ownership verification

## Migration Path for Existing Users

### Option 1: Gradual Migration
1. Keep both auth systems running
2. New users use Web3Auth
3. Existing users can migrate when ready
4. Use `migrateFromFirebase()` helper method

### Option 2: Forced Migration
1. Set a migration deadline
2. Notify users about the change
3. On next login, migrate to Web3Auth
4. Preserve user data and history

## Testing

### Test Credentials
- Use testnet for development
- Get test ALGO from: https://bank.testnet.algorand.network/

### Test Flows
1. **New User Registration**
   - Sign in with Google/Apple
   - Verify Algorand address is created
   - Check balance shows 0 ALGO

2. **Send Transaction**
   - Fund account with test ALGO
   - Send transaction using `algorandWalletService`
   - Verify transaction on AlgoExplorer

3. **Session Persistence**
   - Sign in
   - Close app
   - Reopen and verify still logged in

## Troubleshooting

### Common Issues

1. **"Web3Auth not initialized"**
   - Ensure `WEB3AUTH_CLIENT_ID` is set
   - Check network connectivity

2. **"Invalid Algorand address"**
   - Address should be 58 characters
   - Verify Web3Auth is returning ED25519 key

3. **Transaction Failures**
   - Check account has sufficient balance
   - Verify network (testnet vs mainnet)
   - Ensure proper fee calculation

### Debug Commands
```bash
# Check Django migrations
./myvenv/bin/python manage.py showmigrations users

# Test GraphQL mutations
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { web3AuthLogin(...) }"}'

# View Algorand transactions
https://testnet.algoexplorer.io/address/YOUR_ADDRESS
```

## Production Checklist

- [ ] Set up Web3Auth production project
- [ ] Configure mainnet Algorand network
- [ ] Update redirect URLs for production
- [ ] Set up monitoring for Algorand transactions
- [ ] Implement rate limiting for blockchain operations
- [ ] Add transaction fee management
- [ ] Set up Algorand node or reliable RPC provider
- [ ] Implement proper error handling and recovery
- [ ] Add analytics for Web3Auth conversions
- [ ] Document recovery procedures

## Resources

- **Web3Auth Docs**: https://web3auth.io/docs/
- **Algorand Developer Portal**: https://developer.algorand.org/
- **AlgoExplorer**: https://algoexplorer.io/
- **Algorand Testnet Faucet**: https://bank.testnet.algorand.network/

## Support

For issues or questions:
- Web3Auth Support: https://web3auth.io/community
- Algorand Forum: https://forum.algorand.org/
- Internal: Update this doc with solutions as you find them