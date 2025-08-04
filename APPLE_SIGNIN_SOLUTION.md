# Apple Sign-In Solution for zkLogin

## The Problem
Apple Sign-In SHA-256 hashes the nonce before including it in the JWT, making it incompatible with the standard zkLogin circuit which expects the original nonce to appear in the JWT.

## Current Status
- **Google Sign-In**: ✅ Works (uses original nonce)
- **Apple Sign-In**: ❌ Fails (uses hashed nonce)

## Technical Details
- zkLogin generates a 27-character nonce
- Apple hashes it to 64 characters (SHA-256 base64)
- The circuit verifies the nonce appears in the JWT
- Since 27 ≠ 64, verification always fails

## Solutions

### Option 1: Use Alternative Authentication for Apple Users
**Recommended for immediate production**
```typescript
if (provider === 'apple') {
  // Use traditional wallet creation with seed phrase
  // Store encrypted seed in secure storage
  return createTraditionalWallet();
} else {
  // Use zkLogin for Google
  return createZkLoginWallet();
}
```

### Option 2: Hybrid Approach
**Best UX while maintaining security**
```typescript
if (provider === 'apple') {
  // Create custodial wallet managed by your backend
  // User can export/import later
  return createManagedWallet();
} else {
  // Non-custodial zkLogin for Google
  return createZkLoginWallet();
}
```

### Option 3: Custom zkLogin Circuit
**Most complex but unified solution**
1. Modify circuit to accept 33-byte (decoded) nonces
2. Recompile circuit (1+ hour on t3.2xlarge)
3. Generate new proving/verification keys
4. Deploy custom prover

### Option 4: Wait for Mysten Updates
Mysten is aware of this issue and may release an updated circuit or alternative solution.

## Recommended Approach for Confío

Given the production timeline and App Store requirements:

1. **Immediate**: Implement Option 1 or 2 for Apple users
2. **Future**: Migrate to zkLogin when Mysten supports Apple
3. **Communication**: Inform Apple users about the different security model

## Implementation Steps

### For Option 1 (Traditional Wallet):
```typescript
// In authService.ts
async function handleAppleSignIn(appleCredential) {
  // Generate seed phrase
  const mnemonic = generateMnemonic();
  
  // Derive keypair
  const keypair = Ed25519Keypair.deriveKeypair(mnemonic);
  
  // Encrypt and store securely
  await Keychain.setInternetCredentials(
    'confio-wallet',
    appleCredential.user,
    encryptSeed(mnemonic, appleCredential.identityToken)
  );
  
  return {
    address: keypair.getPublicKey().toSuiAddress(),
    type: 'traditional'
  };
}
```

### For Option 2 (Managed Wallet):
```typescript
// Backend creates and manages wallet
async function createManagedWallet(appleUser) {
  // Backend generates wallet
  const wallet = await backend.createWallet({
    userId: appleUser.id,
    provider: 'apple'
  });
  
  // Frontend stores reference
  return {
    address: wallet.address,
    type: 'managed',
    exportable: true
  };
}
```

## Security Considerations

- **Option 1**: User has full control but must manage seed phrase
- **Option 2**: Convenient but requires trust in backend
- **Both**: Can migrate to zkLogin when available

## Testing Requirements

- Test wallet creation with Apple Sign-In
- Test transaction signing
- Test wallet recovery
- Test migration path to zkLogin

## App Store Compliance

Apple Sign-In is required for App Store approval. Using Option 1 or 2 ensures compliance while maintaining functionality.

## Conclusion

The zkLogin circuit incompatibility with Apple's nonce hashing is a fundamental limitation. Until Mysten provides a solution, using an alternative authentication method for Apple users is the most practical approach.