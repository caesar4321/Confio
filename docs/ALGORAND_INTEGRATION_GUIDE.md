# Algorand Integration Guide - Simple & Non-Invasive

## Overview
This integration adds Algorand wallet functionality to your existing Firebase authentication WITHOUT changing your current auth flow. Users continue to sign in with Firebase, and Algorand wallets are created automatically in the background.

## How It Works

1. **User signs in normally with Firebase** (Google/Apple)
2. **Your existing auth flow remains unchanged**
3. **Algorand wallet is created automatically** (using Web3Auth Single Factor Auth)
4. **Wallet is optional** - if it fails, the app continues working

## Quick Integration (3 Steps)

### Step 1: Import the Algorand Extension
No changes to your existing authentication code needed!

```typescript
// In your existing authenticated screen
import { AlgorandWalletCard } from '../components/AlgorandWalletCard';

// Just add the component anywhere in your authenticated screens
<AlgorandWalletCard />
```

### Step 2: Use the Hook (Optional)
For custom integration:

```typescript
import { useAlgorandWallet } from '../hooks/useAlgorandWallet';

function MyScreen() {
  const { walletInfo, hasWallet, sendTransaction } = useAlgorandWallet();
  
  // Wallet is automatically created after Firebase auth
  if (hasWallet) {
    console.log('User Algorand address:', walletInfo?.address);
  }
}
```

### Step 3: That's It!
No changes to:
- Your authentication flow ✓
- Your backend auth ✓
- Your user model (Firebase UID remains primary) ✓
- Your existing screens ✓

## Backend Integration

The backend automatically tracks Algorand addresses for users:

```python
# User still identified by Firebase UID
user = User.objects.get(firebase_uid=firebase_uid)

# Algorand address is stored in Account model
account = user.accounts.first()
algorand_address = account.algorand_address  # Optional field
```

## Example Usage

### In Profile Screen
```typescript
// ProfileScreen.tsx
import { AlgorandWalletCard } from '../components/AlgorandWalletCard';

export function ProfileScreen() {
  // Your existing profile code...
  
  return (
    <ScrollView>
      {/* Your existing profile UI */}
      <UserInfo />
      <Settings />
      
      {/* Just add this - it handles everything */}
      <AlgorandWalletCard />
    </ScrollView>
  );
}
```

### Custom Integration
```typescript
// Any authenticated component
import { algorandExtension } from '../services/algorandExtension';

async function handlePayment() {
  // Ensure wallet exists (creates if needed)
  const wallet = await algorandExtension.setupAlgorandWallet();
  
  if (wallet) {
    // Send payment
    const txId = await algorandExtension.sendTransaction(
      'RECIPIENT_ADDRESS',
      1.5, // Amount in ALGO
      'Payment note'
    );
  }
}
```

## How Web3Auth Single Factor Auth Works

1. **User signs in with Firebase** → Gets ID token
2. **Web3Auth uses the ID token** → Generates deterministic key
3. **Same login = Same wallet** → User always gets the same Algorand address
4. **No separate Web3Auth login** → It's automatic

## What Gets Added to Your App

### Services (Drop-in, no changes needed)
- `algorandExtension.ts` - Manages Algorand functionality
- `web3AuthService.ts` - Handles Web3Auth SDK
- `algorandWalletService.ts` - Blockchain operations

### Optional UI Components
- `AlgorandWalletCard.tsx` - Ready-to-use wallet UI
- `useAlgorandWallet.ts` - React hook for custom UI

### Backend
- `algorand_address` field added to Account model
- GraphQL mutations for wallet operations
- All optional - app works without them

## Testing

1. **Run your app normally**:
```bash
cd apps
npm run ios  # No rebuild needed!
```

2. **Sign in with Firebase** (as usual)

3. **Check logs for**:
```
AlgorandExtension - Algorand wallet created: [ADDRESS]
```

4. **Verify in UI**:
- If using `AlgorandWalletCard`, it appears automatically
- Shows address and balance

## Configuration

Already configured with your Web3Auth Client ID:
```typescript
// config/web3auth.ts
clientId: 'BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE'
```

Network: Algorand Testnet (switch to mainnet for production)

## FAQ

**Q: What if Web3Auth fails?**
A: The app continues working normally. Algorand is optional.

**Q: Do users need to know about Web3Auth?**
A: No, it's completely transparent to users.

**Q: Can users export their wallet?**
A: The wallet is deterministic - same Firebase login always generates the same wallet.

**Q: What about existing users?**
A: They get an Algorand wallet on their next login automatically.

**Q: Do I need to change my auth flow?**
A: No changes needed. Keep using Firebase as you always have.

## Common Issues

### "Web3Auth not initialized"
- Check internet connection
- Verify Client ID is correct

### "No Algorand wallet created"
- Ensure user is authenticated with Firebase first
- Check Web3Auth logs in console

### Balance shows 0
- Normal for new wallets
- Get test ALGO from: https://bank.testnet.algorand.network/

## Production Checklist

- [ ] Change Algorand network to mainnet
- [ ] Test with real ALGO (small amounts first)
- [ ] Add error tracking for wallet creation
- [ ] Consider adding wallet backup/export feature
- [ ] Monitor Web3Auth usage/limits

## Summary

This integration:
- ✅ Keeps Firebase as primary auth
- ✅ Adds Algorand wallets automatically
- ✅ Requires NO changes to existing code
- ✅ Is completely optional/non-breaking
- ✅ Works with Single Factor Auth (your choice was correct!)

Just drop in the `AlgorandWalletCard` component where you want it, and you're done!