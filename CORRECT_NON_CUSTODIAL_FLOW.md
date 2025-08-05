# Correct Non-Custodial Flow for Aptos Keyless

## The Problem with Current Implementation

The current implementation sends ephemeral keys to the server and derives the Keyless account server-side. This is NOT non-custodial because:
- Server has access to ephemeral private keys
- Server could sign transactions on behalf of users
- Users must trust the server

## Correct Non-Custodial Flow

### 1. Client-Side Only Operations
- Generate ephemeral key pair
- Derive Keyless account
- Sign transactions

### 2. Server-Side Only Operations  
- Facilitate OAuth flow
- Store user profile data
- Relay signed transactions to blockchain

## Detailed Flow

### Step 1: Client Generates Ephemeral Key
```typescript
// Client-side only!
const ephemeralKeyPair = EphemeralKeyPair.generate();
const nonce = ephemeralKeyPair.nonce;
```

### Step 2: Client Initiates OAuth
```typescript
// Only send PUBLIC info to server
const oauthUrl = await getOAuthUrl({
  provider: 'google',
  nonce: ephemeralKeyPair.nonce,  // Only the nonce!
  publicKey: ephemeralKeyPair.publicKey  // Optional, for logging
});
```

### Step 3: OAuth Callback Returns JWT
The server facilitates OAuth and returns the JWT to the client.

### Step 4: Client Derives Keyless Account Locally
```typescript
// Client-side only!
const pepper = generateDeterministicPepper(jwt.iss, jwt.sub, jwt.aud, ...);
const keylessAccount = await aptos.deriveKeylessAccount({
  jwt,
  ephemeralKeyPair,  // Private key stays on client!
  pepper
});
```

### Step 5: Client Signs Transactions Locally
```typescript
// Client-side only!
const signedTxn = await keylessAccount.signTransaction(transaction);
// Send only the signed transaction to server
await submitSignedTransaction(signedTxn);
```

## What the Server Should Store

The server should only store:
- User profile (email, name, etc.)
- Aptos address (public)
- JWT claims (for account recovery)
- NOT the ephemeral private key
- NOT the ability to derive accounts

## Benefits

1. **True Non-Custodial**: Server never has signing capability
2. **User Sovereignty**: Only user can sign transactions
3. **Account Recovery**: User can regenerate same address by logging in again
4. **No Trust Required**: Server compromise doesn't risk user funds

## Implementation Requirements

### Client (React Native)
1. Install `@aptos-labs/ts-sdk`
2. Generate ephemeral keys locally
3. Derive Keyless accounts locally
4. Sign transactions locally

### Server (Django)
1. Remove keyless account derivation
2. Only facilitate OAuth flow
3. Store public user data only
4. Accept pre-signed transactions

## Migration Path

1. Keep current server-side implementation for backward compatibility
2. Add client-side implementation as preferred method
3. Deprecate server-side key handling
4. Eventually remove server-side key operations

## Security Note

The deterministic pepper ensures that:
- Same user + same account type/index = same address
- User can always recover their address
- No need to backup private keys
- True self-custody with OAuth convenience