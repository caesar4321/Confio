# Aptos Keyless Deterministic Addresses

## Overview

Aptos Keyless **DOES** provide deterministic addresses for users. This document explains how it works and addresses any concerns about addresses changing.

## How Deterministic Addresses Work

### 1. Address Components
The Aptos Keyless address is a cryptographic commitment to:
- **User Identity (sub)**: The user's unique identifier from the OAuth provider (e.g., Google sub)
- **Application Identity (aud)**: The OAuth client ID of your application
- **Pepper**: A deterministic blinding factor for privacy

### 2. The Pepper Service
- The pepper service deterministically derives a pepper based on the user's JWT
- For the same user (same `sub`) and same app (same `aud`), the pepper service ALWAYS returns the same pepper
- The pepper service is "stateless" - it uses a VRF (Verifiable Random Function) secret key to derive peppers deterministically

### 3. Ephemeral Keys vs Address
- **Ephemeral keys can be random** - they are used for transaction signing, NOT address derivation
- The address is derived from: `hash(sub, aud, pepper)`
- Since sub, aud, and pepper are deterministic, the address is deterministic

## Implementation Details

### Current Implementation
```python
# In web_oauth_views.py
# Generate random ephemeral key - this is correct!
ephemeral_key = await keyless_service.generate_ephemeral_key(24)

# Derive keyless account - pepper fetched automatically
keyless_account = await keyless_service.derive_keyless_account(jwt_token, ephemeral_key)
```

### What Happens Behind the Scenes
1. User logs in with OAuth (Google/Apple)
2. We generate a random ephemeral key pair (with nonce)
3. OAuth provider returns JWT with the nonce
4. We call `deriveKeylessAccount` with the JWT
5. The SDK automatically:
   - Validates the JWT
   - Fetches the pepper from the pepper service using the JWT
   - Derives the deterministic address using (sub, aud, pepper)
   - Returns the KeylessAccount with the address

## Why Addresses Might Appear to Change

### 1. Different Environments
- Development vs Production use different OAuth client IDs
- Different client IDs = different addresses for the same user

### 2. Different OAuth Providers
- Google sign-in and Apple sign-in have different `sub` values
- Same user, different provider = different address

### 3. Database Updates
- The logs show addresses being updated, but this is normal
- The system updates the stored address to ensure it's current
- If properly implemented, the "new" address should be the same as the old

## Verification Steps

To verify deterministic addresses are working:

1. **Check OAuth Claims**:
   - Same user should have same `sub`
   - Same app should have same `aud`
   - Same issuer should have same `iss`

2. **Monitor Logs**:
   ```python
   logger.info(f"Deriving Keyless account for sub={sub}, aud={aud}, iss={iss}")
   logger.info(f"Derived Keyless address: {address}")
   ```

3. **Watch for Address Changes**:
   ```python
   if old_address and old_address != keyless_account['address']:
       logger.warning(f"ADDRESS CHANGED for user {user.email}!")
   ```

## Security Note

The pepper service is NOT trusted for security. A malicious pepper service cannot:
- Take over a user's account
- Access the ephemeral secret key
- Sign transactions on behalf of the user

It can only affect privacy by potentially linking addresses to identities.

## Conclusion

Aptos Keyless provides deterministic addresses through its pepper service. The same user logging into the same application will always get the same blockchain address, regardless of when they log in or which ephemeral keys are used.

If addresses are changing in your implementation, check:
1. OAuth client IDs are consistent
2. Users are using the same OAuth provider
3. The pepper service is functioning correctly
4. No code is generating custom peppers