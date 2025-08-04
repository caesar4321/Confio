# Immediate Solution for Apple Sign-In

## The Problem Summary
The zkLogin circuit is hardcoded to expect 27-byte nonces, but Apple SHA-256 hashes them to 33 bytes. Modifying and recompiling the circuit would take 2+ hours and requires deep Circom knowledge.

## Recommended Immediate Solution

### Use a Hybrid Approach

```typescript
// In React Native app (authService.ts)

async function handleSignIn(provider: 'google' | 'apple') {
  if (provider === 'google') {
    // Use zkLogin - it works perfectly
    return await zkLoginFlow();
  } else {
    // Use server-managed wallet for Apple users
    return await serverManagedWalletFlow();
  }
}
```

### Server-Managed Wallet Implementation

1. **Backend creates wallet on behalf of Apple users:**

```python
# In Django (prover/schema.py)

class CreateAppleWallet(graphene.Mutation):
    class Arguments:
        appleToken = graphene.String(required=True)
        deviceFingerprint = graphene.JSONString()
    
    success = graphene.Boolean()
    address = graphene.String()
    
    def mutate(self, info, appleToken, deviceFingerprint=None):
        # Verify Apple token
        apple_user = verify_apple_token(appleToken)
        
        # Create deterministic wallet from user ID
        # This ensures same wallet across devices
        seed = generate_deterministic_seed(apple_user.id, settings.WALLET_SECRET)
        keypair = Ed25519Keypair.from_seed(seed)
        
        # Store encrypted private key
        account = Account.objects.create(
            user=apple_user,
            address=keypair.get_public_key().to_sui_address(),
            wallet_type='managed',
            encrypted_key=encrypt(keypair.export_private_key())
        )
        
        return CreateAppleWallet(
            success=True,
            address=account.address
        )
```

2. **Backend signs transactions for Apple users:**

```python
class SignAppleTransaction(graphene.Mutation):
    class Arguments:
        transaction = graphene.String(required=True)
        accountId = graphene.ID(required=True)
    
    signature = graphene.String()
    
    def mutate(self, info, transaction, accountId):
        account = Account.objects.get(id=accountId)
        
        # Verify user owns this account
        if account.user != info.context.user:
            raise PermissionError()
        
        # Decrypt and sign
        private_key = decrypt(account.encrypted_key)
        keypair = Ed25519Keypair.from_private_key(private_key)
        signature = keypair.sign(transaction)
        
        return SignAppleTransaction(signature=signature)
```

### Security Considerations

1. **Private keys are encrypted at rest** using Django's encryption
2. **Deterministic generation** ensures wallet recovery
3. **Future migration path** to zkLogin when Apple is supported
4. **User can export** their private key if needed

### Frontend Implementation

```typescript
// In React Native

class AppleWalletService {
  async createWallet(appleToken: string): Promise<string> {
    const { data } = await apolloClient.mutate({
      mutation: CREATE_APPLE_WALLET,
      variables: { appleToken }
    });
    return data.createAppleWallet.address;
  }
  
  async signTransaction(tx: Transaction): Promise<string> {
    const { data } = await apolloClient.mutate({
      mutation: SIGN_APPLE_TRANSACTION,
      variables: { 
        transaction: tx.serialize(),
        accountId: this.accountId
      }
    });
    return data.signAppleTransaction.signature;
  }
}
```

### User Experience

1. **Apple users**: Seamless experience, server manages keys
2. **Google users**: Full zkLogin privacy
3. **Both**: Can send/receive transactions normally
4. **Migration**: When zkLogin supports Apple, migrate transparently

## Implementation Timeline

- **2 hours**: Implement server-managed wallets
- **1 hour**: Update React Native to use hybrid approach
- **1 hour**: Testing

Total: **4 hours** vs 2+ days for circuit modification

## Testing Checklist

- [ ] Apple Sign-In creates wallet
- [ ] Apple users can send transactions
- [ ] Apple users can receive transactions
- [ ] Google Sign-In still uses zkLogin
- [ ] Wallet recovery works for Apple users
- [ ] Export private key works

## Future Migration

When Mysten releases Apple-compatible zkLogin:

1. Deploy new prover with updated circuit
2. Migrate Apple users to zkLogin wallets
3. Allow users to claim their zkLogin address
4. Phase out server-managed wallets

## Conclusion

This hybrid approach ships today, passes App Store review, and provides a migration path to full zkLogin when available. It's the pragmatic solution that balances security, timeline, and user experience.