# CONFIO Presale Deployment Checklist

## Pre-Deployment Planning

### 1. Token Allocation Decision
**How much CONFIO to allocate for presale?**

Typical allocation strategies:
- **Conservative**: 10-20% of total supply (100-200M CONFIO)
- **Standard**: 20-30% of total supply (200-300M CONFIO)
- **Aggressive**: 30-40% of total supply (300-400M CONFIO)

### 2. Round Planning
Example rounds with cUSD-based pricing:
```
Round 1: 0.25 cUSD per CONFIO - Raise 1M cUSD (4M CONFIO)
Round 2: 0.50 cUSD per CONFIO - Raise 10M cUSD (20M CONFIO)
Round 3: 1.00 cUSD per CONFIO - Raise 25M cUSD (25M CONFIO)
Total: 49M CONFIO allocated, 36M cUSD raised
```

Alternative aggressive strategy:
```
Round 1: 0.10 cUSD per CONFIO - Raise 5M cUSD (50M CONFIO)
Round 2: 0.25 cUSD per CONFIO - Raise 25M cUSD (100M CONFIO)
Round 3: 0.50 cUSD per CONFIO - Raise 50M cUSD (100M CONFIO)
Total: 250M CONFIO allocated, 80M cUSD raised
```

## Deployment Steps

### Step 1: Deploy Contracts
```bash
# 1. Create CONFIO token (1B total supply)
python confio/create_confio_token_algorand.py

# 2. Create cUSD contract
python cusd/deploy_cusd.py

# 3. Deploy presale contract
python presale/deploy_presale.py
```

### Step 2: Initial Setup
```python
# Get contract addresses
PRESALE_APP_ID = 123456
PRESALE_APP_ADDR = "ABC..."
CONFIO_ID = 789
CUSD_ID = 456
SPONSOR_ADDR = "XYZ..."
```

### Step 3: Opt Contract Into Assets
```python
# Contract must opt into both CONFIO and cUSD
# Requires sponsor payment of 0.3 ALGO for MBR
opt_in_assets(
    admin_address,
    admin_sk,
    confio_id,
    cusd_id
)
```

### Step 4: Fund Contract with CONFIO ⚠️ CRITICAL
```python
# Transfer presale allocation to contract
# Conservative example: 50M CONFIO for initial rounds
amount = 50_000_000 * 10**6  # 50M with 6 decimals

fund_contract_with_confio(
    treasury_address,  # Where CONFIO is held
    treasury_sk,
    CONFIO_ID,
    PRESALE_APP_ADDR,
    amount
)

# Can add more CONFIO later as needed
```

### Step 5: Configure Parameters
```python
# Set round parameters (these are set when starting each round)
# Min buy amount (prevents spam)
min_buy = 10 * 10**6  # 10 cUSD minimum

# Max per address (prevents whale accumulation)
max_per_address = 100_000 * 10**6  # 100k cUSD max per address per round

# These are configured in start_round() call
```

### Step 6: Start First Round
```python
# Round 1: 0.25 cUSD per CONFIO
start_round(
    admin_address,
    admin_sk,
    price=250_000,               # 0.25 cUSD per CONFIO (6 decimals)
    cusd_cap=1_000_000 * 10**6,  # 1M cUSD cap for this round
    max_per_addr=10_000 * 10**6  # 10k cUSD max per address
)

# After Round 1 completes, start Round 2:
# price=500_000 (0.50 cUSD/CONFIO)
# cusd_cap=10_000_000 * 10**6 (10M cUSD)
```

## Funding Calculation Examples

### Scenario 1: Small Presale (Test)
```
Round 1: 0.10 cUSD/CONFIO → Raise 100k cUSD = 1M CONFIO needed
Contract funding: 1,000,000 * 10**6 microCONFIO
Expected raise: 100,000 cUSD
```

### Scenario 2: Conservative Launch
```
Round 1: 0.25 cUSD/CONFIO → Raise 1M cUSD = 4M CONFIO
Round 2: 0.50 cUSD/CONFIO → Raise 5M cUSD = 10M CONFIO
Round 3: 1.00 cUSD/CONFIO → Raise 10M cUSD = 10M CONFIO
Total: 24M CONFIO needed, 16M cUSD raised
```

### Scenario 3: Aggressive Launch
```
Round 1: 0.10 cUSD/CONFIO → Raise 5M cUSD = 50M CONFIO
Round 2: 0.25 cUSD/CONFIO → Raise 25M cUSD = 100M CONFIO
Round 3: 0.50 cUSD/CONFIO → Raise 50M cUSD = 100M CONFIO
Total: 250M CONFIO needed, 80M cUSD raised
```

## Security Considerations

### ⚠️ IMPORTANT: Funding Best Practices

1. **Don't overfund**: Only send what's needed for planned rounds
2. **Staged funding**: Can fund incrementally per round instead of all at once
3. **Multi-sig treasury**: Use multi-sig for treasury that holds CONFIO
4. **Audit trail**: Document all funding transactions

### Example: Staged Funding Approach
```python
# Instead of funding all tokens at once, fund per round:

# Round 1: Fund 4M CONFIO for 0.25 cUSD price
fund_contract(4_000_000 * 10**6)
start_round(price=250_000, cusd_cap=1_000_000 * 10**6)
# ... round completes, withdraw cUSD ...

# Round 2: Fund 10M more CONFIO for 0.50 cUSD price
fund_contract(10_000_000 * 10**6)
start_round(price=500_000, cusd_cap=5_000_000 * 10**6)
```

## Monitoring During Presale

### Key Metrics to Track
```python
# Check contract balance
confio_balance = get_asset_balance(PRESALE_APP_ADDR, CONFIO_ID)
cusd_balance = get_asset_balance(PRESALE_APP_ADDR, CUSD_ID)

print(f"CONFIO in contract: {confio_balance / 10**6:,.0f}")
print(f"CONFIO sold: {total_sold / 10**6:,.0f}")
print(f"CONFIO remaining: {(confio_balance - total_sold) / 10**6:,.0f}")
print(f"cUSD raised: {cusd_balance / 10**6:,.2f}")
```

### Daily Operations
1. Monitor round progress
2. Check sponsor budget usage
3. Withdraw cUSD regularly
4. Watch for unusual patterns
5. Prepare next round parameters

## Post-Presale

### After Final Round
1. **Stop rounds**: Set round_active = 0
2. **Withdraw all cUSD**: Transfer to treasury
3. **Prepare unlock**: Notify users of unlock date
4. **Permanent unlock**: Execute when ready
5. **Recover unused CONFIO**: If any remains

### Unlock Strategy
```python
# Option 1: Immediate unlock after presale
permanent_unlock()  # Users can claim immediately

# Option 2: Vesting (requires contract modification)
# Add vesting schedule to contract
# Users claim portions over time
```

## Emergency Procedures

### If Something Goes Wrong
```python
# 1. Emergency pause
emergency_pause()  # Stops all operations

# 2. Assess situation
# - Check balances
# - Review transactions
# - Identify issue

# 3. If needed, cancel round
toggle_round()  # Pause current round

# 4. Fix issue and resume
emergency_pause()  # Unpause
toggle_round()  # Resume round
```

## Recommended Funding for Production

For production launch, consider:

### Conservative Approach ✅ (Recommended)
```
Initial funding: 25M CONFIO (2.5% of supply)
- Round 1: 4M CONFIO @ 0.25 cUSD (raise 1M cUSD)
- Round 2: 10M CONFIO @ 0.50 cUSD (raise 5M cUSD)
- Round 3: 10M CONFIO @ 1.00 cUSD (raise 10M cUSD)
Total: 24M CONFIO, 16M cUSD raised
Monitor and add more rounds if successful
```

### Benefits:
- Lower risk
- Can adjust strategy based on demand
- Easier to manage
- Can always add more rounds

## Summary

**YES, you should fund the presale contract with CONFIO**, but:
1. Start conservative (25-50M CONFIO, 2.5-5% of supply)
2. Use staged funding per round for better control
3. Monitor metrics closely (raised amounts, participant count)
4. Have emergency procedures ready
5. Keep remaining supply for:
   - Future presale rounds
   - DEX liquidity pools
   - Staking rewards
   - Team/advisor vesting
   - Community incentives

## Price Guidance

Remember that pricing is in **cUSD per CONFIO**:
- 0.10 cUSD/CONFIO = Very early/seed price
- 0.25 cUSD/CONFIO = Early bird price
- 0.50 cUSD/CONFIO = Private sale price
- 1.00 cUSD/CONFIO = Public sale price
- 2.00+ cUSD/CONFIO = Post-launch market price target