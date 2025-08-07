# Firebase + Web3Auth Hybrid Integration Guide

## Overview
This implementation maintains Firebase as the primary authentication system while adding Web3Auth Single Factor Auth (SFA) to provide Algorand wallet functionality. Users continue to sign in with Firebase, and Web3Auth seamlessly generates their Algorand wallet in the background.

## Architecture

```
User → Firebase Auth (Primary) → Backend User Management
           ↓
      Web3Auth SFA → Algorand Wallet (Secondary)
```

## Key Design Decisions

1. **Firebase Remains Primary**: 
   - Firebase UID is the primary user identifier
   - All existing Firebase functionality is preserved
   - User management stays in Firebase/Django

2. **Web3Auth as Wallet Provider**:
   - Web3Auth Single Factor Auth generates deterministic keys
   - Uses Firebase ID token as input
   - Provides Algorand wallet functionality
   - No separate Web3Auth login required

3. **Seamless Integration**:
   - Users sign in once with Google/Apple via Firebase
   - Algorand wallet is automatically created
   - No additional authentication steps

## Configuration

### Web3Auth Setup
- **Client ID**: `BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE`
- **Product**: Single Factor Auth (SFA)
- **Network**: Sapphire Mainnet

### Environment Variables
```bash
# Web3Auth (already configured in code)
WEB3AUTH_CLIENT_ID=BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE

# Algorand Network
ALGORAND_NETWORK=testnet  # Use mainnet for production
```

## Implementation Details

### Frontend Services

1. **authServiceHybrid.ts**
   - Main authentication service
   - Handles Firebase sign-in
   - Automatically initializes Web3Auth
   - Creates Algorand wallet

2. **web3AuthService.ts**
   - Web3Auth SDK wrapper
   - Single Factor Auth implementation
   - Key derivation for Algorand

3. **algorandWalletService.ts**
   - Algorand blockchain interactions
   - Wallet management
   - Transaction handling

### Backend Integration

1. **Firebase UID as Primary Key**
   - Users identified by Firebase UID
   - No changes to existing user model

2. **Algorand Fields Added to Account Model**
   - `algorand_address`: User's Algorand address
   - `web3auth_id`: Web3Auth identifier (optional)
   - `web3auth_provider`: Provider used
   - `algorand_verified`: Verification status

3. **New GraphQL Mutations**
   - `addAlgorandWallet`: Add wallet to existing user
   - `verifyAlgorandOwnership`: Verify wallet ownership
   - `createAlgorandTransaction`: Create transactions

## User Flow

### New User Registration
1. User signs in with Google/Apple (Firebase)
2. Firebase creates user account
3. Backend creates user record with Firebase UID
4. Web3Auth SFA generates Algorand wallet
5. Wallet address saved to user's account
6. User can immediately use Algorand features

### Existing User Migration
1. User signs in normally (Firebase)
2. System checks for Algorand wallet
3. If no wallet exists, creates one via Web3Auth
4. Wallet added to existing account
5. No disruption to user experience

## Code Usage

### Sign In with Algorand Wallet Creation
```typescript
import authServiceHybrid from './services/authServiceHybrid';

// Sign in with Google (Firebase + Algorand)
const userInfo = await authServiceHybrid.signInWithGoogle();
console.log('Firebase UID:', userInfo.firebaseUid);
console.log('Algorand Address:', userInfo.algorandAddress);

// Sign in with Apple (iOS only)
const userInfo = await authServiceHybrid.signInWithApple();
```

### Check/Create Algorand Wallet for Existing User
```typescript
// Ensure user has Algorand wallet (creates if needed)
const address = await authServiceHybrid.ensureAlgorandWallet();
if (address) {
  console.log('User Algorand address:', address);
}
```

### Algorand Operations
```typescript
// Get balance
const balance = await authServiceHybrid.getAlgorandBalance();

// Send transaction
const txId = await authServiceHybrid.sendAlgorandTransaction(
  'RECIPIENT_ADDRESS',
  1.5, // Amount in ALGO
  'Payment for services'
);
```

## Testing Instructions

### 1. Test Firebase Authentication
```bash
# Run the app
cd apps && npm run ios

# Sign in with Google/Apple
# Verify Firebase user is created
# Check Firebase UID in logs
```

### 2. Test Algorand Wallet Creation
```bash
# After sign in, check logs for:
"Algorand wallet initialized: [ADDRESS]"

# Verify address format (58 characters)
# Check address on Algorand testnet explorer
```

### 3. Test Wallet Operations
```javascript
// In app console or debug
const balance = await authServiceHybrid.getAlgorandBalance();
console.log('Balance:', balance);
```

## Migration Strategy

### Phase 1: Silent Rollout (Recommended)
1. Deploy hybrid authentication
2. New users automatically get Algorand wallets
3. Existing users get wallets on next login
4. No user action required

### Phase 2: Feature Activation
1. Enable Algorand features in UI
2. Show wallet address in profile
3. Add send/receive functionality
4. Introduce Algorand-based features

### Phase 3: Full Integration
1. Tokenization features
2. Smart contract interactions
3. DeFi integrations
4. Cross-chain capabilities

## Benefits of This Approach

1. **No Breaking Changes**: Existing Firebase auth continues working
2. **Seamless UX**: Users don't need to understand Web3Auth
3. **Progressive Enhancement**: Add blockchain features gradually
4. **Fallback Support**: App works even if Web3Auth fails
5. **Easy Rollback**: Can disable Algorand features if needed

## Security Considerations

1. **Key Management**
   - Private keys never stored on servers
   - Web3Auth handles key sharding
   - Keys derived deterministically from Firebase token

2. **Session Management**
   - Firebase session = primary authentication
   - Web3Auth session = wallet access only
   - Separate session lifecycles

3. **Recovery**
   - Users can recover wallets with same Firebase account
   - Deterministic key generation ensures consistency
   - No seed phrases to manage

## Common Issues & Solutions

### Issue: "Web3Auth not initialized"
**Solution**: Ensure Client ID is correct and network is accessible

### Issue: "No Algorand wallet created"
**Solution**: Check Web3Auth session is established after Firebase login

### Issue: "Invalid signature" on transactions
**Solution**: Verify Algorand network (testnet vs mainnet) matches

### Issue: "Firebase UID not found"
**Solution**: Ensure Firebase auth completes before Web3Auth init

## Production Checklist

- [ ] Set Algorand network to mainnet
- [ ] Configure Web3Auth production verifiers
- [ ] Add error tracking for wallet creation
- [ ] Implement transaction monitoring
- [ ] Set up Algorand node access
- [ ] Add rate limiting for blockchain calls
- [ ] Create wallet backup/export feature
- [ ] Document recovery procedures
- [ ] Test with real ALGO tokens
- [ ] Add analytics for wallet adoption

## Next Steps

1. **Immediate**: Test authentication flow end-to-end
2. **Short-term**: Add Algorand balance display in UI
3. **Medium-term**: Implement send/receive features
4. **Long-term**: Build Algorand-powered features (NFTs, tokens, etc.)

## Support Resources

- **Web3Auth Dashboard**: https://dashboard.web3auth.io/
- **Web3Auth SFA Docs**: https://web3auth.io/docs/sdk/pnp/web/sfa
- **Algorand Developer Portal**: https://developer.algorand.org/
- **Firebase Console**: https://console.firebase.google.com/