# Non-Custodial Aptos Keyless Implementation

## Overview

This implementation ensures that the Aptos Keyless system is truly non-custodial by:
1. Generating ephemeral keys on the client side
2. Using deterministic pepper generation based on user identity

## Key Components

### 1. Client-Side Ephemeral Key Generation

```typescript
// In authService.ts
// Generate ephemeral key pair on client side for non-custodial approach
this.ephemeralKeyPair = await this.generateEphemeralKeyPair();
```

The ephemeral private key never leaves the user's device, ensuring the server cannot sign transactions on behalf of the user.

### 2. Deterministic Pepper Generation

Following the same formula as zkLogin salt generation:

```
pepper = SHA256(issuer | subject | audience | account_type | business_id | account_index)
```

Where:
- **issuer**: JWT issuer (e.g., "https://accounts.google.com")
- **subject**: JWT subject (user's unique ID)
- **audience**: OAuth client ID
- **account_type**: Either "personal" or "business"
- **business_id**: Business ID (empty for personal accounts)
- **account_index**: Numeric index (0, 1, 2, etc.)

### 3. Multi-Account Support

The deterministic pepper formula supports multiple accounts per user:
- Personal accounts: Different indices (0, 1, 2...)
- Business accounts: Different business IDs and indices

Each combination produces a unique, deterministic address.

## Implementation Flow

1. **Client generates ephemeral key pair** with nonce
2. **Client sends ephemeral public key** to server with OAuth request
3. **Server initiates OAuth** with the client's nonce
4. **OAuth provider returns JWT** with matching nonce
5. **Server generates deterministic pepper** using JWT claims
6. **Server derives Keyless account** with pepper
7. **Same address every time** for same user+account combination

## Security Benefits

1. **Private keys never leave device**: Server cannot access ephemeral private keys
2. **Deterministic addresses**: Users can recover addresses by logging in again
3. **No key storage needed**: Keys are derived, not stored
4. **Account recovery**: Lost device? Just log in again with same OAuth account
5. **Multi-account privacy**: Different addresses for different contexts

## Code Changes

### Client Side (React Native)
- Generate ephemeral keys locally
- Pass ephemeral key data to OAuth flow
- Calculate deterministic pepper for account derivation

### Server Side (Django)
- Accept client-generated ephemeral keys
- Generate deterministic pepper using formula
- Pass pepper to Aptos SDK for address derivation

## Example Usage

```typescript
// Generate ephemeral key on client
const ephemeralKeyPair = await generateEphemeralKeyPair();

// Pass to OAuth flow
const result = await webOAuth.signInWithProvider('google', ephemeralKeyPair);

// Server generates pepper deterministically
const pepper = generateKeylessPepper(iss, sub, aud, 'personal', '', 0);

// Same user, same account = same address every time
const keylessAccount = await deriveKeylessAccount(jwt, ephemeralKeyPair, pepper);
```

## Migration Note

The system still supports server-side ephemeral key generation for backward compatibility, but logs a warning encouraging client-side generation for true non-custodial operation.