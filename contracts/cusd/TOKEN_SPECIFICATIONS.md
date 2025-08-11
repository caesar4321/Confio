# Token Specifications for Confío Platform

## CONFIO Token (Governance/Utility Token)

**Purpose**: Platform governance and utility token

**Specifications**:
- **Total Supply**: 1,000,000,000 (1 billion) tokens
- **Decimals**: 6
- **Symbol**: CONFIO
- **Name**: Confío
- **Distribution**: All tokens instantly available to creator upon creation
- **Authorities**:
  - Manager: Creator address (can update metadata)
  - Reserve: None (all tokens go to creator)
  - Freeze: None (tokens cannot be frozen)
  - Clawback: None (tokens cannot be clawed back)

**Key Points**:
- Fixed supply of 1 billion tokens
- No reserve mechanism - all tokens immediately available
- No freeze or clawback authorities for true ownership
- Creator receives all 1B tokens upon asset creation

**Configuration File**: `contracts/confio/create_confio_token.py`

---

## cUSD Token (Stablecoin)

**Purpose**: USD-pegged stablecoin with dual backing mechanism

**Specifications**:
- **Total Supply**: 10,000,000 cUSD (10,000,000,000,000 micro-units)
- **Decimals**: 6
- **Symbol**: cUSD
- **Name**: Confío Dollar
- **Distribution**: Held in reserve, minted only when collateral is deposited
- **Authorities**:
  - Manager: Creator address (can update asset parameters)
  - Reserve: Creator address (holds all non-circulating supply)
  - Freeze: Application address (contract controls freezing)
  - Clawback: Application address (contract controls minting)

**Backing Mechanism**:
1. **USDC Collateral** (Automatic 1:1):
   - Users deposit USDC → receive cUSD automatically
   - Users burn cUSD → redeem USDC automatically
   - Fully on-chain and transparent

2. **T-Bills Backing** (Admin controlled):
   - Admin can mint cUSD backed by off-chain T-bills
   - Used for treasury management and liquidity

**Key Points**:
- Fixed total supply of 10 million cUSD
- All tokens start in reserve (not in circulation)
- Application has clawback and freeze authorities from creation
- Minting only occurs when:
  - USDC collateral is deposited (automatic)
  - T-bills backing is added (admin action)

**Configuration Files**: 
- `contracts/cusd/deploy_cusd.py` - Deployment and asset creation
- `contracts/cusd/cusd.py` - Smart contract logic

---

## Important Differences

| Aspect | CONFIO | cUSD |
|--------|---------|------|
| Supply | Fixed 1B | 10 million cUSD |
| Initial Distribution | All to creator | All in reserve |
| Minting | Never (fixed supply) | On-demand with collateral |
| Reserve | None | Required for minting |
| Clawback | None | Required for minting |
| Backing | None | USDC + T-bills |

## Deployment Order

1. **Deploy CONFIO Token** - Creates fixed supply token
2. **Deploy cUSD Contract** - Smart contract for managing minting/burning
3. **Create cUSD Asset** - Creates asset with app as clawback/freeze
4. **Setup Contract Assets** - Contract opts into both assets

This ensures proper token economics where CONFIO has a fixed supply for governance while cUSD can grow based on actual USD backing.

## ASA Mutability Note

**Immutable after creation:**
- Total supply
- Decimals
- Asset name
- Unit name
- URL
- Metadata hash
- Default frozen state

**Can be changed (until manager is set to zero address):**
- Manager address (controls config changes)
- Reserve address (holds non-circulating supply)
- Freeze address (controls freezing)
- Clawback address (controls forced transfers)

Once the manager is set to the zero address, all parameters become permanently immutable.