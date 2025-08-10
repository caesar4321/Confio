# Confío Smart Contracts - Deployment Guide

## Network Configuration

The smart contracts support automatic network detection for USDC asset IDs:

- **Mainnet USDC**: 31566704 (Circle's official USDC)
- **Testnet USDC**: 10458941 (Test USDC)

## Configuration Methods

### Method 1: Environment Variables

```bash
# For testnet (default)
export ALGORAND_NETWORK=testnet
python3 cusd.py

# For mainnet
export ALGORAND_NETWORK=mainnet
python3 cusd.py

# Custom USDC asset ID
export USDC_ASSET_ID=12345
python3 cusd.py
```

### Method 2: Inline Configuration

```bash
# Testnet compilation
ALGORAND_NETWORK=testnet python3 cusd.py

# Mainnet compilation
ALGORAND_NETWORK=mainnet python3 cusd.py

# Custom asset
USDC_ASSET_ID=12345 python3 cusd.py
```

### Method 3: Using Deploy Script

```bash
# Deploy for testnet (default)
./deploy.sh

# Deploy for mainnet
./deploy.sh mainnet

# Deploy for testnet explicitly
./deploy.sh testnet
```

## Deployment Steps

1. **Compile Contracts**
   ```bash
   # Choose your network
   ./deploy.sh testnet  # or mainnet
   ```

2. **Deploy to Algorand**
   ```bash
   # Using goal CLI
   goal app create --creator <ACCOUNT> \
     --approval-prog cusd_approval.teal \
     --clear-prog cusd_clear.teal \
     --global-byteslices 2 --global-ints 8 \
     --local-byteslices 0 --local-ints 2

   # Note the application ID returned
   ```

3. **Initialize Assets**
   ```bash
   # Call setup_assets with cUSD and USDC IDs
   goal app call --app-id <APP_ID> \
     --from <ADMIN_ACCOUNT> \
     --app-arg "str:setup_assets" \
     --app-arg "int:<CUSD_ASSET_ID>" \
     --app-arg "int:<USDC_ASSET_ID>"
   ```

4. **Configure cUSD Reserve**
   - Create or rekey the cUSD reserve account to the application address
   - This allows the contract to mint cUSD when users deposit USDC

## Contract Features

### cUSD (Confío Dollar)
- **Collateralized Minting**: Deposit USDC to mint cUSD (1:1 ratio)
- **Collateralized Burning**: Burn cUSD to redeem USDC
- **Freeze/Unfreeze**: Admin can freeze accounts
- **Adjustable Collateral Ratio**: 100% to 200% range
- **Reserve Verification**: Check if reserves match supply

### Payment Processing
- 0.9% transaction fee
- Payment tracking and statistics

### P2P Trading
- Escrow-based trading with dispute resolution
- 15-minute claim window for trades
- Admin dispute resolution capabilities

### Invite & Send
- Send funds to non-users via invitation codes
- 7-day reclaim period for unclaimed funds
- Support for both cUSD and Confío tokens

## Security Notes

1. **Admin Keys**: Secure the admin private key used for deployment
2. **Reserve Account**: The cUSD reserve must be rekeyed to the app
3. **Asset IDs**: Verify USDC asset IDs before mainnet deployment
4. **Collateral Ratio**: Monitor and adjust based on market conditions

## Testing

For testnet testing:
1. Get test ALGO from the faucet
2. Use testnet USDC (ID: 10458941)
3. Test all functions before mainnet deployment

## Support

Website: https://confio.lat