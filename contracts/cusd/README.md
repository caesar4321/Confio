# Confío Dollar (cUSD) - Algorand Smart Contract

## Overview

Confío Dollar (cUSD) is a stablecoin implementation on the Algorand blockchain, designed to maintain a 1:1 peg with the US Dollar through a dual-backing mechanism using USDC collateral and Treasury Bills reserves.

**Website**: [confio.lat](https://confio.lat)

## Architecture

### Dual-Backing System

cUSD maintains stability through two backing mechanisms:

1. **USDC Collateral**: Users can mint cUSD by depositing USDC at a 1:1 ratio
2. **Treasury Bills**: Admin can mint cUSD backed by real-world T-bills and reserves

### Key Components

- **Smart Contract** (`cusd.py`): PyTeal/Beaker contract managing all cUSD operations
- **ASA Token**: Algorand Standard Asset with 6 decimals
- **Clawback Control**: Contract has clawback authority for minting
- **Freeze Control**: Contract can freeze/unfreeze addresses

## Features

### Core Functionality
- ✅ Mint cUSD with USDC collateral (1:1 ratio)
- ✅ Burn cUSD to redeem USDC
- ✅ Admin minting backed by T-bills
- ✅ Real ASA freeze/unfreeze enforcement
- ✅ Pause mechanism for emergency stops
- ✅ Collateral ratio management (100-200%)
- ✅ On-chain backing verification

### Security Features
- Reserve address validation
- Underflow protection for all operations
- Caller verification for mint/burn operations
- Asset parameter validation (decimals, clawback, freeze)
- Update/delete lifecycle guards

## Token Specifications

| Parameter | Value |
|-----------|-------|
| Name | Confío Dollar |
| Unit | cUSD |
| Decimals | 6 |
| Total Supply | 10,000,000 cUSD |
| Initial Supply | 0 (minted on demand) |
| Backing | USDC + Treasury Bills |

For complete token specifications, see [TOKEN_SPECIFICATIONS.md](TOKEN_SPECIFICATIONS.md)

## Smart Contract Details

### Global State
- `admin`: Admin address for governance
- `cusd_asset_id`: ASA ID of cUSD token
- `usdc_asset_id`: ASA ID of USDC collateral
- `collateral_ratio`: Collateralization ratio (1e6 = 100%)
- `reserve_address`: ASA reserve holding non-circulating supply
- `total_usdc_locked`: Total USDC locked as collateral
- `cusd_circulating_supply`: Collateral-backed cUSD in circulation
- `tbills_backed_supply`: T-bills backed cUSD supply
- `is_paused`: System pause state

### Local State
- `is_frozen`: Account freeze status
- `is_vault`: Vault designation

## Quick Start

### Prerequisites
```bash
pip install pyteal py-algorand-sdk beaker-pyteal
```

### Compile Contract
```bash
cd contracts/cusd
python cusd.py
```

This generates:
- `cusd_approval.teal` - Approval program
- `cusd_clear.teal` - Clear state program
- `cusd.json` - ABI specification

### Deploy to Testnet
```bash
python deploy_cusd.py
```

The deployment script will:
1. Deploy the smart contract
2. Create cUSD ASA with app as clawback/freeze
3. Configure assets in the contract
4. Save deployment info to `deployment_info.json`

For detailed deployment instructions, see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

## Network Configuration

### Testnet
- USDC Asset ID: `10458941`
- Network: `https://testnet-api.algonode.cloud`
- Faucet: [Algorand Testnet Dispenser](https://bank.testnet.algorand.network/)

### Mainnet
- USDC Asset ID: `31566704`
- Network: `https://mainnet-api.algonode.cloud`

## Treasury Management

### USDC Reserve Rebalancing

The contract supports rebalancing USDC reserves to tokenized T-bills (e.g., mTBILL on Algorand):

1. **Withdraw USDC**: `withdraw_usdc(amount, recipient)` - Send USDC to treasury wallet
2. **Purchase mTBILL**: Use withdrawn USDC to buy tokenized T-bills on Algorand
3. **Track backing**: T-bills backing is tracked via `tbills_backed_supply`

**Backing Model**: The stablecoin maintains 1:1 backing (1 cUSD = 1 USD value) through a combination of:
- USDC collateral (liquid reserves)
- mTBILL holdings (tokenized T-bills)

**Treasury Management**: Up to 70% of USDC reserves can be withdrawn for mTBILL purchases, while maintaining 30% as liquid USDC to ensure immediate user redemptions are always possible.

This allows the treasury to earn yield on reserves while maintaining full backing. The system remains fully operational during rebalancing - users can continue minting and burning cUSD 24/7.

### Multi-sig Security

For production deployment, transfer admin control to a multi-sig wallet:

```python
# Create Algorand multi-sig account
multisig_addr = "..."  # Your multi-sig address

# Transfer admin rights
update_admin(multisig_addr)

# After admin transfer, also consider:
# - Rotating ASA manager to multi-sig or zero address
# - Setting up approval thresholds for treasury operations
```

## Recent Security Improvements

Based on comprehensive security audit, the following fixes have been implemented:

1. **Reserve Address Management**: Uses ASA reserve address instead of admin for clawback operations
2. **Real Freeze Enforcement**: Implements actual ASA freeze transactions, not just local flags
3. **Burn Returns to Reserve**: Burned cUSD properly returned to reserve address
4. **Caller Verification**: Ties app caller to asset depositor/redeemer
5. **Underflow Protection**: All decrement operations check for underflows
6. **On-chain Verification**: `verify_backing` checks actual on-chain balances
7. **Lifecycle Guards**: Update/delete operations properly restricted

## Testing

### Manual Testing
```python
# Test minting with USDC collateral
python test_mint_collateral.py

# Test admin minting
python test_admin_mint.py

# Test freeze functionality
python test_freeze.py
```

## Documentation

- [Token Specifications](TOKEN_SPECIFICATIONS.md) - Complete token parameters
- [Deployment Guide](DEPLOYMENT_GUIDE.md) - Step-by-step deployment instructions
- [Algorand Migration](ALGORAND_MIGRATION.md) - Historical migration from Move
- [Algorand Token Model](ALGORAND_TOKEN_MODEL.md) - Understanding ASAs

## Contract Methods

### User Methods
- `mint_with_collateral()` - Mint cUSD with USDC deposit (requires opt-in to cUSD first)
- `burn_for_collateral()` - Burn cUSD to redeem USDC
- `transfer_cusd()` - Optional checked transfer (regular ASA transfers work when not frozen)

**Important**: Users must opt-in to the cUSD asset before receiving any mints

**Freeze/Unfreeze Note**: Freezing an account requires the account to opt in to the application (not just the ASA) for local state management

### Admin Methods
- `mint_admin()` - Mint backed by T-bills (requires recipient opt-in to cUSD)
- `burn_admin()` - Burn T-bills backed supply
- `withdraw_usdc()` - Withdraw USDC for treasury rebalancing (e.g., mTBILL purchases)
- `freeze_address()` - Freeze an account (requires app opt-in, not just ASA)
- `unfreeze_address()` - Unfreeze an account (requires app opt-in, not just ASA)
- `update_collateral_ratio()` - Adjust collateral requirements (100%-200%)
- `update_admin()` - Transfer admin to new address (e.g., multi-sig)
- `refresh_reserve()` - Update stored reserve if ASA reserve was intentionally rotated
- `pause()` / `unpause()` - Emergency controls

### Read Methods
- `get_stats()` - Minting/burning statistics
- `get_reserves()` - Reserve and supply information
- `verify_backing()` - Check if properly backed
- `is_frozen()` - Check freeze status
- `is_vault()` - Check vault status

## Support

For questions or issues, please visit [confio.lat](https://confio.lat)