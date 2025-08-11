# CONFIO Token Presale Contract

## Overview

The CONFIO presale contract enables multiple rounds of token sales with flexible parameters, allowing users to purchase CONFIO tokens using cUSD at admin-defined exchange rates.

## Key Features

### 🎯 Core Functionality
- **Multiple Rounds**: Unlimited presale rounds with different parameters
- **Flexible Pricing**: Admin can set cUSD per CONFIO price per round
- **cUSD-Based Caps**: Configurable cUSD raise limits per round
- **Lock Mechanism**: Tokens locked until admin enables permanent unlock
- **Immediate cUSD Access**: Admin can withdraw cUSD anytime
- **Fully Sponsored Claims**: Sponsor pays ALL fees when users claim tokens

### 🔐 Admin Controls
- Start/pause presale rounds
- Adjust exchange rates dynamically
- Set cUSD cap per round (maximum to raise)
- Withdraw collected cUSD immediately
- Permanent unlock switch (irreversible)
- Emergency pause functionality

### 👤 User Features
- Buy CONFIO with cUSD at current rate
- Track purchase history
- Claim tokens after unlock
- View presale statistics

## Contract Architecture

### Global State (17 ints, 2 bytes)
```python
# Assets
confio_id         # CONFIO asset ID
cusd_id           # cUSD asset ID
admin_address     # Admin address

# Round parameters
current_round     # Current round number
round_active      # 0=paused, 1=active
price             # cUSD per CONFIO (6 decimals)
cusd_cap          # Max cUSD to raise this round (6 decimals)
cusd_raised       # cUSD raised this round (6 decimals)
min_buy           # Minimum cUSD per transaction
max_addr          # Max cUSD per address per round

# Lock mechanism
tokens_locked     # 0=unlocked, 1=locked
unlock_time       # Timestamp of unlock

# Statistics
total_rounds      # Total rounds completed
total_sold        # Total CONFIO sold
total_raised      # Total cUSD raised
total_participants # Unique buyers
```

### Local State (5 ints per user)
```python
user_confio      # Total CONFIO purchased
user_cusd        # Total cUSD spent
claimed          # CONFIO already claimed
round_cusd       # cUSD spent this round
user_round       # User's last active round
```

## Sponsor Support

The presale contract (`confio_presale.py`) implements full sponsor support:

### Transaction Structures with Sponsor

| Operation | Group Structure | Who Pays ALGO |
|-----------|----------------|---------------|
| **Opt-in** | [Payment(sponsor→self), OptIn(user)] | Sponsor |
| **Buy** | [Payment(sponsor→self), cUSD(user→app), AppCall(user)] | Sponsor |
| **Claim** | [Payment(user→self, 0 ALGO, 0 fee), AppCall(sponsor)] | Sponsor |

The sponsor covers ALL transaction fees! In a custom wallet where users never hold ALGO, the sponsor handles everything. Users only need cUSD.

## Usage Flow

### 1. Contract Deployment
```python
# Deploy contract with asset IDs and sponsor
deploy_presale(confio_id, cusd_id, admin_address, sponsor_address)
```

### 2. Initial Setup
```python
# Opt contract into assets
opt_in_assets()

# Fund contract with CONFIO tokens
transfer_confio_to_contract(amount)
```

### 3. Start Presale Round
```python
# Admin starts round with parameters
start_round(
    price=250_000,             # 0.25 cUSD per CONFIO (6 decimals)
    cusd_cap=1_000_000 * 10**6,  # 1M cUSD to raise
    max_per_addr=10_000 * 10**6  # 10k cUSD max per address
)
```

### 4. User Participation
```python
# User opts into contract
opt_in()

# User buys CONFIO with cUSD
buy_tokens(cusd_amount)
```

### 5. Admin Management
```python
# Pause/resume round
toggle_round()

# Update price
update_price(new_price_cusd_per_confio)

# Withdraw collected cUSD
withdraw_cusd()
```

### 6. Token Distribution
```python
# Admin permanently unlocks tokens
permanent_unlock()  # IRREVERSIBLE!

# Users claim their tokens
claim_tokens()
```

## Pricing Examples

Price is stored as cUSD per CONFIO with 6 decimals:

| Price (stored) | Meaning | 100 cUSD buys |
|---------------|---------|---------------|
| 250_000 | 0.25 cUSD/CONFIO | 400 CONFIO |
| 500_000 | 0.50 cUSD/CONFIO | 200 CONFIO |
| 1_000_000 | 1.00 cUSD/CONFIO | 100 CONFIO |
| 2_000_000 | 2.00 cUSD/CONFIO | 50 CONFIO |

## Security Features

### Access Control
- Only admin can start/modify rounds
- Only admin can unlock tokens permanently
- Only admin can withdraw cUSD
- Users can only buy during active rounds

### Safety Mechanisms
- Inventory tracking prevents overselling
- Outstanding obligations tracked across rounds
- Per-address caps prevent whale accumulation
- Minimum buy amounts prevent spam
- Lock prevents early token claims
- Permanent unlock is irreversible (protects users)
- Emergency pause for critical situations

### Fund Protection
- cUSD immediately available to admin
- CONFIO locked until explicit unlock
- Users can always claim after unlock
- Contract tracks all purchases

## Deployment Guide

### 1. Deploy Contract
```bash
cd presale
python deploy_presale.py
```

### 2. Configure First Round
```python
# Set price (e.g., 0.50 cUSD per CONFIO)
price = int(0.50 * 10**6)  # 500_000 (6 decimals)

# Set cUSD cap for the round
cusd_cap = 25_000 * 10**6  # 25,000 cUSD to raise
max_per_addr = 1_000 * 10**6  # 1,000 cUSD max per address

# Start round
start_round(price, cusd_cap, max_per_addr)
```

### 3. Monitor Progress
```python
# Check round status
presale.display_presale_info()

# Output:
# Round #1
# 🟢 PRESALE IS ACTIVE
# Price: 0.50 cUSD per CONFIO
# Progress: 12,500 / 25,000 cUSD (50.0%)
# [████████████████████░░░░░░░░░░░░░░░░░░░]
```

## Testing Checklist

- [ ] Deploy contract with correct asset IDs
- [ ] Opt contract into CONFIO and cUSD
- [ ] Fund contract with CONFIO tokens
- [ ] Start presale round with parameters
- [ ] Test user purchases at different amounts
- [ ] Verify exchange rate calculations
- [ ] Test pause/resume functionality
- [ ] Test rate updates mid-round
- [ ] Verify hard cap enforcement
- [ ] Test cUSD withdrawal by admin
- [ ] Test permanent unlock
- [ ] Verify user claims work after unlock
- [ ] Test multiple rounds sequentially

## Common Operations

### Check User Balance
```python
info = presale.get_user_info(user_address)
print(f"Purchased: {info['purchased'] / 10**6} CONFIO")
print(f"Claimable: {info['claimable'] / 10**6} CONFIO")
```

### Emergency Pause
```python
# Admin pauses all operations
emergency_pause()
```

### Complete Round Cycle
```python
# 1. Start round
start_round(price, cusd_cap, max_per_addr)

# 2. Users buy tokens
# ... purchases happen ...

# 3. Round ends (manually or at hard cap)
toggle_round()  # Pause

# 4. Withdraw cUSD
withdraw_cusd()

# 5. Start next round or unlock
# Either:
start_round(new_price, new_cusd_cap, new_max_per_addr)
# Or:
permanent_unlock()  # Allow claims
```

## Important Notes

⚠️ **Permanent Unlock is Irreversible**: Once tokens are unlocked, they cannot be locked again.

⚠️ **Asset Opt-in Required**: Contract must opt into both CONFIO and cUSD before operations.

⚠️ **Funding Required**: Contract must hold CONFIO tokens before starting rounds.

⚠️ **Exchange Rate Precision**: Price uses 6 decimals (1_000_000 = 1.0 cUSD per CONFIO).

## Error Handling

Common errors and solutions:

| Error | Cause | Solution |
|-------|-------|----------|
| "Round not active" | Trying to buy when paused | Wait for admin to start/resume |
| "Hard cap exceeded" | Round is full | Wait for next round |
| "Tokens still locked" | Trying to claim early | Wait for admin unlock |
| "No tokens to claim" | Already claimed all | Check claimed amount |
| "Insufficient CONFIO" | Contract underfunded | Admin must add CONFIO |

## Gas Optimization

- Batch operations when possible
- Use group transactions for buy operations
- Minimize storage reads in loops
- Cache frequently accessed values
