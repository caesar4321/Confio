# Aptos Keyless Implementation Approach

## Current Implementation (Server-Assisted, Similar to zkLogin)

### Overview
The implementation follows the same pattern as zkLogin - temporarily server-assisted during authentication but ultimately non-custodial.

### Key Features

1. **Deterministic Pepper Generation**
   - Formula: `SHA256(iss_sub_aud_account_type_[business_id_]account_index)`
   - Components joined with underscores
   - Empty business_id is omitted for personal accounts
   - Ensures same user + same account = same address

2. **Server-Assisted Flow**
   - Server generates ephemeral keys during OAuth
   - Server derives Keyless account with deterministic pepper
   - Server returns everything to client
   - Server NEVER stores private keys

3. **Client-Side Control**
   - Client receives and stores keys locally
   - Client signs all transactions
   - Client has full control after authentication

### Why This Approach?

1. **Proven Pattern**: Same as zkLogin which worked successfully
2. **Practical Non-Custodial**: Server can't access funds after auth completes
3. **Simpler Implementation**: No need for Aptos SDK in React Native
4. **Compatibility**: Avoids potential React Native compatibility issues

### Security Properties

- **No Key Storage**: Server never persists private keys
- **Session-Limited**: Server only has keys during OAuth flow
- **User Sovereignty**: Only user can sign transactions after auth
- **Deterministic Recovery**: User can always regenerate same address

### Trade-offs

✅ **Pros**:
- Simple client implementation
- Already working and tested
- Matches zkLogin pattern
- No React Native compatibility issues

⚠️ **Considerations**:
- Temporarily custodial during auth (like zkLogin)
- Requires trust in server during OAuth flow
- Not "pure" non-custodial

### Future Enhancement

If needed, we can move to full client-side implementation by:
1. Adding Aptos SDK to React Native
2. Generating keys client-side
3. Deriving accounts client-side
4. Only using server for OAuth facilitation

But current approach is sufficient and matches the accepted zkLogin pattern.