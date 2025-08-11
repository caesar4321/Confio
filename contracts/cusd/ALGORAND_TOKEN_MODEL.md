# Understanding Algorand's Token Model

## Key Concept: ASAs vs Smart Contracts

In Algorand, tokens and smart contracts are **separate entities**:

### Algorand Standard Assets (ASAs)
- Built-in token standard (like ERC-20 but native to Algorand)
- Created with `AssetConfigTxn` in deployment scripts
- Parameters are **immutable** once set (supply, decimals, name)
- No smart contract needed for basic tokens

### Smart Contracts
- Control token **behavior** but don't define token **parameters**
- Can manage ASAs if given proper authorities (clawback, freeze)
- Written in PyTeal/TEAL
- Cannot change fundamental ASA parameters

## Where Token Parameters Are Defined

### ❌ NOT in Contract Files
```python
# cusd.py does NOT contain:
total_supply = 1000000  # Not here!
decimals = 6           # Not here!
token_name = "cUSD"    # Not here!
```

### ✅ In Deployment Scripts
```python
# deploy_cusd.py contains:
AssetConfigTxn(
    total=10_000_000_000_000,  # 10 million cUSD (with 6 decimals)
    decimals=6,                # Decimals defined HERE
    unit_name="cUSD",          # Name defined HERE
    asset_name="Confío Dollar",
    clawback=app_address,      # App controls minting
    freeze=app_address,        # App controls freezing
    ...
)
```

## Our Token Architecture

### CONFIO Token
```
contracts/confio/create_confio_token.py
    ↓
Creates ASA with 1B supply
    ↓
Done! (No smart contract needed)
```

### cUSD Token
```
contracts/cusd/deploy_cusd.py
    ↓
Deploys smart contract first
    ↓
Creates ASA with app as clawback/freeze
    ↓
Configures assets in contract
    ↓
Contract controls minting/burning
```

## Common Confusion Points

### From Other Blockchains

| Blockchain | Where Token Params Live | Example |
|------------|------------------------|---------|
| Ethereum | In smart contract code | `totalSupply = 1000000` in Solidity |
| Aptos/Move | In smart contract code | `const TOTAL_SUPPLY = 1000000` in Move |
| **Algorand** | **In deployment transaction** | `AssetConfigTxn(total=1000000)` |

### Why This Matters

1. **To change token supply**: Must modify deployment script, NOT contract
2. **To understand a token**: Look at AssetConfigTxn, NOT PyTeal code
3. **Contract compilation**: Doesn't affect token parameters
4. **Token parameters**: Set once during creation, mostly immutable

## Summary

- **ASA Creation** (deployment scripts) = Token Definition
- **Smart Contracts** (PyTeal files) = Token Behavior
- Never look for supply/decimals in `.py` contract files
- Always check `AssetConfigTxn` for actual token parameters

This is fundamentally different from Ethereum/Solidity where everything is in the contract!