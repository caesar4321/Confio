# CLAUDE.md - Important Rules and Context for AI Assistant

## CRITICAL RULES - NEVER VIOLATE

### 1. NO MOCKS - EVER
**NEVER USE MOCK DATA OR MOCK RESPONSES**
- Always implement real functionality
- If something doesn't work, fix the actual issue
- Never return fake/mock success responses
- Never use placeholder data in production code
- If a real implementation is blocked (e.g., missing API keys), document the exact requirements needed

### 2. Code Quality Standards
- Always write production-ready code
- Handle all error cases properly
- Use proper typing in TypeScript
- Follow existing code patterns in the codebase

## Project Context

### Architecture
- Django backend with GraphQL API
- React Native mobile app
- TypeScript bridge service for Aptos blockchain
- All blockchain operations go through Django → TypeScript Bridge → Aptos

### Key Services
- **Django**: Main backend at http://localhost:8000
- **TypeScript Bridge**: Aptos integration at http://localhost:3333 (or 3456)
- **React Native**: Mobile app

### Current Issues That Need Real Solutions

#### Sponsored Transactions
- Status: INVALID_SIGNATURE errors  
- Root cause: Need real sponsor private key with funded account
- Required fix: Set APTOS_SPONSOR_PRIVATE_KEY environment variable in .env file (NEVER commit this)
- Sponsor Address: 0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c
- Module addresses: 0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio / ::cusd

## Testing Commands
- Run Django: `python manage.py runserver`
- Run TypeScript Bridge: `npm start` (in aptos-keyless-bridge/)
- Build TypeScript: `npm run build`
- Run React Native: `npm start` (in apps/)

## Common Issues and Real Solutions

### INVALID_SIGNATURE
- Check sponsor account has funds
- Verify module is deployed at correct address
- Ensure transaction is built with withFeePayer: true
- Verify both sender and sponsor signatures are included

### Transaction Flow (V2 Sponsored)
1. Prepare: Build transaction with fee payer
2. Sign: Client signs with keyless account
3. Submit: Send both signatures to blockchain

## Environment Variables Required
- APTOS_SPONSOR_PRIVATE_KEY: Real funded sponsor account private key
- TYPESCRIPT_BRIDGE_URL: Bridge service URL (default: http://localhost:3333)
- APTOS_NETWORK: Network to use (testnet/mainnet)