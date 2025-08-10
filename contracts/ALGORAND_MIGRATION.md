# Algorand Migration Documentation

## Overview

The Confío smart contracts have been migrated from Sui Move to Algorand PyTeal. This document outlines the migration status and key architectural changes.

## Migration Status

### ✅ Completed Contracts

1. **cusd.py** - Confío Dollar stablecoin contract
2. **p2p_trade.py** - P2P trading with escrow
3. **invite_send.py** - Invitation system with escrow
4. **payment.py** - Payment processing with fees

### 🔧 Technical Notes

The contracts are syntactically complete but require minor adjustments for full compilation:

1. **State Access**: Some state value accesses need proper getter methods
2. **Box Storage**: Box operations need proper type handling
3. **Tuple Types**: Custom tuple types for complex return values

## Key Architectural Changes

### From Sui Move to Algorand

| Sui Move | Algorand PyTeal |
|----------|-----------------|
| Object Model | Global/Local State + Box Storage |
| Coin<T> | Algorand Standard Assets (ASA) |
| Transfer::share_object | App.box_put for shared data |
| Table/VecSet | Box storage with key prefixes |
| Millisecond timestamps | Second timestamps |
| Capability pattern | Direct admin checks |

## Contract Features

### Confío Dollar (cUSD)
- Admin-controlled minting and burning
- Account freezing for compliance
- Vault management
- Pause functionality

### P2P Trading
- Escrow-based trading
- 15-minute trade windows
- Dispute resolution
- Support for cUSD and CONFIO tokens

### Invite & Send
- Send tokens to non-users
- 7-day reclaim period
- Admin-controlled claiming

### Payment Processing
- 0.9% fee collection
- Fee accumulation
- Payment tracking

## Next Steps

1. **Complete Compilation**: Fix remaining PyTeal syntax issues
2. **Create Test Suite**: Implement comprehensive tests
3. **Deploy to Testnet**: Test on Algorand testnet
4. **Security Audit**: Review security implications
5. **Production Deployment**: Deploy to mainnet

## Building Instructions

```bash
# Install dependencies
pip install pyteal beaker-pyteal

# Build contracts (after compilation fixes)
python build_contracts.py
```

## Security Considerations

- All admin functions protected by address checks
- Pause mechanisms for emergency situations
- Box storage for efficient data management
- Inner transactions for secure asset transfers

## Website
https://confio.lat