# Need Help: Keyless Accounts with Sponsored Transactions - INVALID_SIGNATURE Issues

## Problem Summary
We're implementing a two-phase sponsored transaction flow where:
1. **Prepare Phase**: Backend builds transaction and sponsor signs as fee payer
2. **Submit Phase**: Frontend (keyless account) signs, backend submits with both signatures

However, we consistently get `INVALID_SIGNATURE` errors despite extensive debugging.

## Our Architecture

### Flow Overview
```
React Native (Keyless Account) → Django GraphQL → TypeScript Bridge → Aptos Network
```

1. **React Native**: Only handles keyless account signing using `signWithAuthenticator()`
2. **Django**: GraphQL layer for transaction coordination  
3. **TypeScript Bridge**: Aptos SDK integration, transaction building, and submission
4. **All blockchain interactions** route through the backend (no direct RN → Aptos calls)

### Current Implementation

#### Phase 1: Prepare Transaction
```typescript
// TypeScript Bridge - keylessServiceV2.ts
async buildSponsoredTransaction(request: SimpleFeePayerRequest) {
  // Build transaction with fee payer
  const transaction = await this.aptos.transaction.build.simple({
    sender: AccountAddress.from(request.senderAddress),
    withFeePayer: true,
    data: {
      function: this.getTransferFunction(request.tokenType),
      functionArguments: [request.recipientAddress, request.amount]
    }
  });

  // Sign as sponsor (fee payer)
  const sponsorAuthenticator = this.aptos.transaction.signAsFeePayer({
    signer: this.sponsorAccount,
    transaction
  });

  // Cache transaction and sponsor signature
  this.pendingTransactions.set(transactionId, {
    transaction,
    sponsorAuthenticator,
    timestamp: Date.now()
  });

  // Return raw transaction bytes for sender to sign
  const rawTxnBytes = transaction.rawTransaction.bcsToBytes();
  const rawTransactionBase64 = Buffer.from(rawTxnBytes).toString('base64');

  return {
    success: true,
    transactionId,
    rawTransaction: rawTransactionBase64,
    sponsorAddress: this.sponsorAccount.accountAddress.toString()
  };
}
```

#### Phase 2: Client Signing
```typescript
// React Native - authService.ts
public async signSponsoredTransaction(rawTransaction: string): Promise<string | null> {
  if (!this.currentAccount || !this.ephemeralKeyPair) {
    return null;
  }

  const { AptosKeylessService } = await import('./aptosKeylessService');
  const aptosKeylessService = new AptosKeylessService();

  // Generate authenticator for the sponsored transaction
  const authenticatorResponse = await aptosKeylessService.generateAuthenticator({
    jwt: this.currentAccount.jwt,
    ephemeralKeyPair: this.ephemeralKeyPair,
    signingMessage: rawTransaction, // Base64 encoded raw transaction
    pepper: pepperBytes,
  });

  // Return the base64 encoded authenticator
  return authenticatorResponse.senderAuthenticatorBcsBase64;
}
```

```typescript
// aptosKeylessService.ts - generateAuthenticator method
async generateAuthenticator(params: GenerateAuthenticatorParams) {
  const { jwt, ephemeralKeyPair, signingMessage, pepper } = params;
  
  const ephKeyPair = this.getEphemeralKeyPairForSDK(ephemeralKeyPair);
  
  // Derive the keyless account
  const keylessAccount = await this.aptos.deriveKeylessAccount({
    jwt,
    ephemeralKeyPair: ephKeyPair,
    pepper,
  });

  await keylessAccount.waitForProofFetch();
  
  // Decode the signing message from base64
  const signingMessageBytes = this.b64ToBytes(signingMessage);
  
  // Sign the message to get the authenticator
  const authenticator = keylessAccount.signWithAuthenticator(signingMessageBytes);
  
  // Serialize the authenticator to BCS
  const serializer = new Serializer();
  authenticator.serialize(serializer);
  const authenticatorBytes = serializer.toUint8Array();
  const senderAuthenticatorBcsBase64 = this.bytesToB64(authenticatorBytes);
  
  return { senderAuthenticatorBcsBase64, /* ... other fields */ };
}
```

#### Phase 3: Submit Transaction
```typescript
// TypeScript Bridge - submitCachedTransaction
async submitCachedTransaction(transactionId: string, senderAuthenticatorBase64: string) {
  const cached = this.pendingTransactions.get(transactionId);
  const { transaction, sponsorAuthenticator } = cached;
  
  // Deserialize sender authenticator
  const senderAuthBytes = Buffer.from(senderAuthenticatorBase64, 'base64');
  const deserializer = new Deserializer(new Uint8Array(senderAuthBytes));
  const senderAuthenticator = AccountAuthenticator.deserialize(deserializer);

  // Submit with both authenticators
  const pendingTxn = await this.aptos.transaction.submit.simple({
    transaction,  // Cached transaction from prepare phase
    senderAuthenticator,
    feePayerAuthenticator: sponsorAuthenticator
  });
}
```

## Problems Encountered

### 1. INVALID_SIGNATURE Errors
Every transaction submission fails with:
```
"Invalid transaction: Type: Validation Code: INVALID_SIGNATURE"
```

### 2. BCS Deserialization Issues
Manual submission attempts fail with:
```
"Failed to deserialize input into SignedTransaction: ULEB128-encoded integer did not fit in the target size"
```

### 3. Transaction Format Questions
- Should sender sign `transaction.rawTransaction.bcsToBytes()` (includes fee payer) or something else?
- Is the two-phase caching approach correct?
- Are we using the right SDK methods for keyless + sponsored transactions?

## What We've Tried

1. **Different RPC Endpoints**: Switched from Aptos Labs to Nodit API
2. **Manual BCS Construction**: Attempted to build SignedTransaction with FeePayer variant
3. **SDK Method Variations**: Tried different transaction building approaches
4. **Extensive Logging**: Added detailed debugging for all transaction states
5. **Cache Validation**: Verified transaction and authenticator caching works correctly

## Key Questions

1. **Signing Message**: For sponsored transactions with keyless accounts, what exactly should the sender sign?
   - Raw transaction bytes with fee payer? 
   - Raw transaction bytes without fee payer?
   - Something else entirely?

2. **SDK Pattern**: Is there a recommended pattern for keyless + sponsored transactions?
   - Should we use `buildSponsoredTransaction()` differently?
   - Is two-phase approach (prepare/sign/submit) supported?

3. **Transaction Structure**: How should the final transaction be constructed?
   - Are we correctly using `signAsFeePayer()` for the sponsor?
   - Is `submit.simple()` the right method for this flow?

## Environment
- **Network**: Aptos Testnet
- **SDK Version**: `@aptos-labs/ts-sdk` latest
- **Keyless Setup**: Google OAuth, working proof fetching
- **Sponsor Account**: Ed25519, sufficient APT balance

## Sample Transaction Data
```
Sender Address: 0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c
Sponsor Address: 0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c
Function: 0x75f38ae0...::confio::transfer_confio
Amount: 111000000
Raw Transaction Length: 165 bytes
Sender Authenticator Length: ~755 bytes
```

## Request for Help

We'd greatly appreciate:

1. **Working Example**: A complete example of keyless accounts with sponsored transactions
2. **Signing Guidance**: Clarification on what the sender should sign in sponsored transactions
3. **SDK Best Practices**: Recommended patterns for this use case
4. **Debugging Tips**: How to better diagnose signature validation issues

Any insights or sample code would be incredibly helpful! We've been stuck on this for quite some time and are running out of ideas.

## Repository
Our implementation is available at: [https://github.com/caesar4321/Confio]

Thank you for any assistance! 🙏