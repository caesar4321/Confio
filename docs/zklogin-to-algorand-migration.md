# zkLogin to Algorand Authentication Migration

## Current zkLogin Flow (TO BE REMOVED)

### Client Side (authService.ts)
1. **initializeZkLogin mutation**
   - Sends: firebaseToken, providerToken, provider, deviceFingerprint
   - Receives: authAccessToken, authRefreshToken, maxEpoch, randomness
   - Stores JWT tokens in Keychain

2. **finalizeZkLogin mutation**
   - Sends: jwt, maxEpoch, salt, ephemeralPublicKey, userSignature, deviceFingerprint
   - Receives: zkProof, subject, clientId
   - Stores zkLogin proof data

### Server Side
- Creates/updates User record
- Generates JWT tokens
- Tracks device fingerprint
- Awards achievements (Pionero Beta for first 10,000 users)
- Creates default personal account

## New Algorand Flow (ALREADY WORKING)

### Client Side (authService.ts)
1. **OAuth Login** (Google/Apple)
   - Get ID token with claims (iss, sub, aud)
   - Firebase authentication
   - Store OAuth claims in Keychain

2. **Web3AuthLoginMutation** (replaces initializeZkLogin)
   - Sends: provider, web3_auth_id, email, firstName, lastName, algorandAddress, deviceFingerprint
   - Receives: accessToken, refreshToken, user data
   - ✅ Handles device fingerprinting
   - ✅ Awards achievements
   - ✅ Creates/updates user
   - ✅ Generates JWT tokens

3. **Client-side Algorand Address Generation**
   - Uses OAuth claims (iss, sub, aud)
   - Generates deterministic address
   - No server involvement needed
   - Updates server with updateAccountAlgorandAddress

## Features Comparison

| Feature | zkLogin | Algorand | Status |
|---------|---------|----------|---------|
| Device Fingerprinting | ✅ initializeZkLogin, finalizeZkLogin | ✅ Web3AuthLoginMutation | Already migrated |
| Achievement Awards | ✅ After finalizeZkLogin | ✅ In Web3AuthLoginMutation | Already migrated |
| JWT Token Generation | ✅ initializeZkLogin | ✅ Web3AuthLoginMutation | Already migrated |
| Account Creation | ✅ After zkLogin | ✅ In Web3AuthLoginMutation | Already migrated |
| User Profile Update | ✅ From OAuth | ✅ From OAuth | Already migrated |
| Address Generation | Server-side (Sui) | Client-side (Algorand) | Different approach |
| Proof Storage | zkLogin proofs | Not needed | Simplified |

## Code to Remove

### Client (authService.ts)
- [ ] initializeZkLogin mutation call (lines 235-243)
- [ ] finalizeZkLogin mutation call (lines 334-349)
- [ ] zkLogin proof storage methods
- [ ] zkLogin keychain service constants
- [ ] Sui-related imports and dependencies
- [ ] zkLogin salt generation (different from Algorand salt)
- [ ] Ephemeral keypair for zkLogin
- [ ] zkLogin nonce generation
- [ ] refreshZkLoginProof method

### Server (if any zkLogin endpoints exist)
- [ ] InitializeZkLogin mutation
- [ ] FinalizeZkLogin mutation
- [ ] zkLogin proof generation logic
- [ ] Sui blockchain integration

## Migration Steps

1. **Phase 1: Verify Algorand Flow Has Everything**
   - ✅ Device fingerprinting is working
   - ✅ Achievements are awarded
   - ✅ JWT tokens are generated
   - ✅ Accounts are created
   - ✅ User profiles are updated

2. **Phase 2: Remove zkLogin Code**
   - Remove client-side zkLogin calls
   - Remove server-side zkLogin mutations (if any)
   - Clean up unused imports
   - Remove zkLogin-related constants

3. **Phase 3: Simplify Authentication Flow**
   - Use Web3AuthLoginMutation as the single authentication endpoint
   - Keep Algorand address generation client-side
   - Maintain all app-level features (fingerprinting, achievements)

## API Request Count Comparison

### zkLogin Flow (OLD)
1. initializeZkLogin
2. finalizeZkLogin  
3. loadUserAccounts
4. getServerPepper
5. updateAccountAddress
6. getUserProfile
**Total: 6 requests**

### Algorand Flow (NEW)
1. Web3AuthLoginMutation (combines init + finalize)
2. loadUserAccounts
3. getServerPepper
4. updateAccountAlgorandAddress
5. getUserProfile
**Total: 5 requests** (1 less request)

## Benefits of Migration

1. **Simpler Flow**: One authentication mutation instead of two
2. **Client-side Address Generation**: More secure, non-custodial
3. **No Proof Management**: No need to store/refresh zkLogin proofs
4. **Fewer Dependencies**: Remove Sui SDK dependencies
5. **Better Performance**: One less server request
6. **All Features Preserved**: Device tracking, achievements, JWT tokens all work