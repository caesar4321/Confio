# Web3Auth Single Factor Auth (SFA) Setup Guide

## Problem
The Algorand wallet isn't being created because Web3Auth SFA requires proper configuration in the Web3Auth dashboard.

## Current Status
- Client ID: `BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE`
- Product: Single Factor Auth (SFA)
- Integration: Firebase Authentication (existing) + Web3Auth for Algorand

## Required Web3Auth Dashboard Configuration

### 1. Single Factor Auth Configuration
In your Web3Auth dashboard:

1. Go to your project with the above Client ID
2. Ensure Single Factor Auth (SFA) is enabled
3. Configure OAuth providers:
   - **Google**: Enable Google as a login provider
   - **Apple**: Enable Apple as a login provider

### 2. No Custom Verifier Needed
Since you're using native Google and Apple OAuth (not Firebase JWT), Web3Auth will use its built-in verifiers for these providers. You don't need to create custom verifiers.

### 3. Provider Configuration
- **Google**: Web3Auth uses Google's OAuth directly
- **Apple**: Web3Auth uses Apple's OAuth directly
- The SDK will generate deterministic keys based on the OAuth provider's user ID

## Testing the Integration

### Debug Steps
1. **Check Console Logs** when signing in:
   ```
   AlgorandWalletSetup - Found Aptos address, migrating to Algorand...
   AlgorandExtension - Getting Firebase ID token...
   AlgorandExtension - Got ID token (length: XXX)
   Web3Auth - Using JWT login with Firebase ID token...
   ```

2. **Common Errors**:
   - "verifier not configured" → Need to set up firebase-jwt verifier in Web3Auth dashboard
   - "Invalid JWT" → Check Firebase project ID in verifier config
   - "Network error" → Check network configuration (sapphire_mainnet)

### Expected Flow
1. User signs in with Google/Apple via Firebase
2. App detects old Aptos address (0x...)
3. AlgorandWalletSetup triggers migration
4. Gets Firebase ID token
5. Uses Web3Auth SFA to generate deterministic Algorand keys
6. Creates Algorand wallet from those keys
7. Updates backend with new Algorand address
8. UI refreshes to show new Algorand address

## Required: Configure Web3Auth Verifier
The Web3Auth integration will NOT work without proper verifier configuration. You must:

1. Configure the firebase-jwt verifier in Web3Auth dashboard
2. Get your Firebase project ID from Firebase Console
3. Update the verifier configuration with correct issuer/audience

## Code Files
- `/apps/src/components/AlgorandWalletSetup.tsx` - Auto-setup component
- `/apps/src/services/algorandExtension.ts` - Main service
- `/apps/src/services/web3AuthService.ts` - Web3Auth integration
- `/apps/src/config/web3auth.ts` - Configuration

## Next Steps
1. Configure the firebase-jwt verifier in Web3Auth dashboard
2. Get your Firebase project ID from Firebase Console
3. Update the verifier configuration with correct issuer/audience
4. Test with a user that has an old Aptos address