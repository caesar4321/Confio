# CONFIO Token Specification

## Token Type
Algorand Standard Asset (ASA)

## Token Parameters
```python
# These are the FIXED parameters for CONFIO token
# Used by deployment scripts but defined here as the source of truth

CONFIO_PARAMS = {
    "asset_name": "Confío",
    "unit_name": "CONFIO",
    "total": 1_000_000_000_000_000,  # 1 billion tokens with 6 decimals
    "decimals": 6,
    "default_frozen": False,
    "url": "https://confio.lat",
    "metadata_hash": "Utility and governance coin for Confío platform",
    
    # Authorities (set during creation, cannot be changed)
    "manager": "<creator_address>",  # Can update metadata only
    "reserve": "",  # Empty - all tokens go to creator immediately
    "freeze": "",   # Empty - tokens cannot be frozen
    "clawback": "", # Empty - tokens cannot be clawed back
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

### No Control Mechanisms
- **No Freeze Authority**: Tokens cannot be frozen in any account
- **No Clawback Authority**: Tokens cannot be forcibly retrieved
- **Manager Authority**: Only for updating metadata (name, URL, etc.)

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
- Parameters are set once during creation and some cannot be changed
- Reserve, freeze, and clawback are intentionally disabled for true ownership

## Deployment
Use `/contracts/deploy/create_confio_token_algorand.py` to create this token with these exact specifications.