# CONFIO Token Module

## Overview
CONFIO is the utility and governance token for the Confío platform, implemented as an Algorand Standard Asset (ASA).

## Token Specifications
- **Name**: Confío
- **Symbol**: CONFIO
- **Decimals**: 6
- **Total Supply**: 1,000,000,000 (1 billion) - Fixed forever
- **Type**: Algorand Standard Asset (ASA)
- **Purpose**: Utility and governance token
- **Backing**: None (utility token, not backed by any assets)
- **Website**: https://confio.lat

## Important Notes
- CONFIO is **NOT** a smart contract. It's a pure ASA where all parameters are defined during asset creation and cannot be changed afterward.
- CONFIO is **NOT** collateral for cUSD. They are separate tokens with different purposes.
- CONFIO has a fixed supply that can never be increased.
 - Never commit private keys or mnemonics. Scripts now redact sensitive values by default; set `ALLOW_PRINT_PRIVATE_KEYS=1` or `ALLOW_PRINT_MNEMONIC=1` only in isolated dev environments.

## Files

### Core Files
- `create_confio_token_algorand.py` - Creates CONFIO ASA on Algorand mainnet/testnet
- `deploy_confio_localnet.py` - Deploy CONFIO to LocalNet for testing
- `confio_token_config.py` - Token configuration parameters

### Integration Files
- `deploy_cusd_with_confio.py` - Deploy cUSD contract with CONFIO collateral support
- `test_confio_collateral.py` - Test CONFIO as collateral for cUSD minting

## Usage

### Create CONFIO Token
```bash
ALGOD_ADDRESS=https://testnet-api.algonode.cloud \
ALGOD_TOKEN= \
python confio/create_confio_token_algorand.py
```

### Deploy to LocalNet
```bash
python confio/deploy_confio_localnet.py

# To print keys in dev (not recommended):
export ALLOW_PRINT_PRIVATE_KEYS=1
```

### Verify Asset Parameters
Use the sanity checker to confirm on-chain params (unit name, supply, authorities):
```bash
# Option A: pass asset id explicitly
python contracts/confio/check_confio_asset.py 123456

# Option B: use env var
export ALGORAND_CONFIO_ASSET_ID=123456
python contracts/confio/check_confio_asset.py

# Optionally override expectations
EXPECT_ASSET_NAME="Confío" EXPECT_UNIT_NAME=CONFIO EXPECT_TOTAL=1000000000000000 \
  python contracts/confio/check_confio_asset.py
```

## Token Distribution
Initial distribution is handled separately through the distribution scripts in `/contracts/scripts/`.

Security Recommendations
- Use environment variables or a secure key store for private keys and mnemonics.
- Do not write private keys to repo-tracked files; deployment scripts avoid persisting secrets by default.
- Verify asset params on-chain after creation (unit name, decimals, total, authorities).

## Environment Setup
See `.env.example` for Algorand-related variables:
- ALGOD_ADDRESS, ALGOD_TOKEN: Algod connection.
- ALGORAND_CONFIO_CREATOR_MNEMONIC: optional creator mnemonic for token creation.
- CONFIO_CREATOR_PRIVATE_KEY: required for creator-signed transfers in LocalNet.
- ALLOW_PRINT_PRIVATE_KEYS, ALLOW_PRINT_MNEMONIC, ALLOW_WRITE_KEYS: dev-only toggles.

LocalNet integration notes
- deploy_cusd_with_confio.py requires `CONFIO_CREATOR_PRIVATE_KEY` in the environment to transfer from the creator account.
- cusd_deployment_config.py will not include the test user private key unless `ALLOW_WRITE_KEYS=1` is set.
