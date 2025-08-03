# zkLogin Migration Guide: 32-byte to 16-byte Values

## Problem
The Confío app previously generated zkLogin sessions with 32-byte randomness and salt values. However, Shinami's zkLogin API requires exactly 16-byte values. This mismatch causes "Nonce does not match" errors.

## Solution
Users with existing 32-byte zkLogin sessions must logout and login again to generate new 16-byte sessions.

## How It Works

### Old System (32-byte)
- Server generated 32-byte randomness
- Client generated 32-byte salt from SHA-256 hash
- Self-hosted prover (Docker) supported 32-byte values
- But Docker prover doesn't work on ARM64 Macs

### New System (16-byte) 
- Server generates 16-byte randomness
- Client generates 16-byte salt (truncated SHA-256)
- Shinami API requires exactly 16-byte values
- Works on all platforms without Docker

### Client-Side Key Derivation
The client's `deriveEphemeralKeypair` function now handles both:
- 16-byte salts: Expands to 32 bytes using SHA-256(salt + sub + clientId)
- 32-byte salts: Uses first 32 bytes (backward compatibility)

## Migration Steps

1. **Detect Legacy Sessions**
   - Check if randomness or salt is 32 bytes
   - Show user-friendly error message
   - Direct user to logout and login again

2. **Clear Old Session**
   - User clicks logout
   - App clears all zkLogin data from Keychain
   - App clears account data

3. **Create New Session**  
   - User logs in again (Google/Apple)
   - Server generates 16-byte randomness
   - Client generates 16-byte salt
   - Shinami generates zkProof successfully

## Error Messages

### Legacy Format Detected
```
Your login session needs to be refreshed to enable new features.
Please logout and login again to continue.
```

### Technical Details (for logs)
```
Legacy zkLogin format detected
Current: 32-byte randomness/salt
Required: 16-byte randomness/salt
Action: logout and login again
```

## Testing

Use the migration check service to test format detection:
```bash
node migration-check.js
```

This will identify whether a zkLogin session needs migration before attempting to use Shinami.