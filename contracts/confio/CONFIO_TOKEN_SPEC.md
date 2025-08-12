# CONFIO Token Specification

## Token Type
Algorand Standard Asset (ASA)

## Token Parameters
```python
# These are the FIXED parameters for CONFIO token
# Used by deployment scripts but defined here as the source of truth

# NOTE: During creation, manager = creator_address (for one transaction).
# Immediately after creation, we finalize → all authorities become ZERO_ADDR forever.
# The values below show the FINAL STATE after finalization.

CONFIO_PARAMS = {
    "asset_name": "Confío",
    "unit_name": "CONFIO",
    "total": 1_000_000_000_000_000,  # 1 billion tokens with 6 decimals
    "decimals": 6,
    "default_frozen": False,
    "url": "https://confio.lat",
    "metadata_hash": None,  # Omitted for simplicity (would be 32-byte hash if needed)
    
    # Authorities - Initially creator, then IMMEDIATELY finalized to ZERO_ADDR
    "manager": None,  # After finalization: ZERO_ADDR (immutable forever)
    "reserve": None,  # ZERO_ADDR - all tokens go to creator immediately
    "freeze": None,   # ZERO_ADDR - tokens cannot be frozen
    "clawback": None, # ZERO_ADDR - tokens cannot be clawed back
}
```

## Key Design Decisions

### Fixed Supply
- Total supply is fixed at 1,000,000,000 (1 billion) CONFIO tokens
- No minting or burning possible after creation
- All tokens are created at once

### Instant Availability
- No reserve mechanism - all 1B tokens go directly to creator
- Creator receives full supply upon asset creation
- No vesting or time-locked distribution

### Complete Immutability (After Finalization)
- **No Freeze Authority**: Tokens cannot be frozen in any account (freeze = ZERO_ADDR)
- **No Clawback Authority**: Tokens cannot be forcibly retrieved (clawback = ZERO_ADDR)
- **No Manager Authority**: After finalization, no one can modify ANY parameters (manager = ZERO_ADDR)
- **True Decentralization**: Token is completely immutable and ungovernable after finalization

## Distribution Strategy
1. Creator receives all 1B tokens at creation
2. Creator distributes tokens according to tokenomics plan
3. Users must opt-in to CONFIO asset before receiving tokens

## Use Cases
- Platform governance voting
- Fee discounts
- Staking rewards
- Ecosystem incentives

## Important Notes
- This is NOT a smart contract - it's an ASA (Algorand Standard Asset)
- Token MUST be finalized immediately after creation (sets all authorities to ZERO_ADDR)
- After finalization, the token is completely immutable - no parameters can ever be changed
- Reserve, freeze, clawback, and manager are all set to ZERO_ADDR for true decentralization

## Deployment Process
1. Create token: `python contracts/confio/create_confio_token_algorand.py`
2. **IMMEDIATELY finalize**: `python contracts/confio/finalize_confio_asset.py`
3. Verify immutability: `python contracts/confio/check_confio_asset.py`

⚠️ **CRITICAL**: Always run finalization immediately after creation to prevent any future modifications.