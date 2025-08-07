# How Algorand Address Updates in the UI

## The Flow

1. **User signs in with Firebase** (Google/Apple)
2. **HomeScreenEnhanced renders** with `<AlgorandWalletSetup />` component
3. **AlgorandWalletSetup automatically**:
   - Checks if user has an address in `aptosAddress` field
   - If not, creates Algorand wallet via Web3Auth
   - Updates backend with new address
   - Refreshes Apollo cache
   - Calls `onWalletCreated` callback

4. **UI Updates**:
   - Apollo cache refresh triggers re-render
   - `refreshAccounts()` updates the account context
   - `refetchCUSD()` and `refetchConfio()` update balances
   - AccountDetailScreen gets new address from `activeAccount?.aptosAddress`

## Key Components

### AlgorandWalletSetup Component
```typescript
// Automatically creates wallet in background
<AlgorandWalletSetup 
  onWalletCreated={(address) => {
    // Refresh everything
    refetchCUSD();
    refetchConfio();
    refreshAccounts();
  }}
  showStatus={false}  // Silent mode
/>
```

### AlgorandExtension Service
- `setupAlgorandWallet()` - Creates wallet if needed
- `refreshApolloCache()` - Forces UI update
- Uses `apolloClient.resetStore()` to refresh all queries

### Backend
- Stores Algorand address in `aptos_address` field (temporary)
- `AddAlgorandWalletMutation` updates the address

## Testing

1. **Sign in with a new user** (or clear app data)
2. **Watch console logs**:
   ```
   AlgorandWalletSetup - Setting up Algorand wallet...
   AlgorandExtension - Algorand wallet created: [ADDRESS]
   HomeScreenEnhanced - Wallet created: [ADDRESS]
   ```

3. **Navigate to AccountDetailScreen**:
   - Should show the new Algorand address
   - Format: `ALGO12...ABC456`

## Troubleshooting

### Address Not Showing?

1. **Check Apollo Cache**:
   ```typescript
   // Force refresh
   await apolloClient.resetStore();
   ```

2. **Check Account Context**:
   ```typescript
   const { activeAccount, refreshAccounts } = useAccount();
   console.log('Current address:', activeAccount?.aptosAddress);
   await refreshAccounts();
   ```

3. **Check Backend**:
   - GraphQL: Query `me { accounts { aptosAddress } }`
   - Django Admin: Check Account model

### Manual Refresh

Pull down to refresh in HomeScreenEnhanced - this triggers:
- Balance refetch
- Account refresh
- Address update

## Important Files

- `components/AlgorandWalletSetup.tsx` - Auto-setup component
- `services/algorandExtension.ts` - Wallet creation logic
- `screens/HomeScreenEnhanced.tsx` - Integration point
- `screens/AccountDetailScreen.tsx` - Shows the address
- `users/web3auth_schema.py` - Backend mutations