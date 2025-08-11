# Sponsorship Strategy for Confío Contracts

## Executive Summary

Based on cost analysis and ChatGPT's recommendations, we implement **selective sponsorship** for specific app flows, NOT universal sponsorship for all cUSD/CONFIO transactions.

## Strategy Overview

### ✅ What We Sponsor (Within Confío App)

| Contract | Sponsored Operations | Cost Model |
|----------|---------------------|------------|
| **Presale** | • Buy CONFIO<br>• Claim tokens<br>• User opt-in | ~0.003 ALGO per buy<br>~0.022 ALGO MBR per new user |
| **P2P Vault** | • Create trade<br>• Complete trade<br>• Cancel/GC | ~0.07 ALGO MBR per trade<br>(recovered on completion) |
| **Inbox Router** | • Send invites<br>• Claim invites | ~0.037 ALGO MBR per invite<br>(recovered on claim) |
| **Payment Router** | • Simple payments<br>• Batch payments | ~0.001 ALGO per payment<br>(no MBR, atomic) |

### ❌ What We DON'T Sponsor

- **cUSD transfers** outside Confío app
- **CONFIO transfers** outside Confío app  
- **DEX trades** (Tinyman, Pact, etc.)
- **Other apps** using our tokens

## Why This Strategy?

### Cost Analysis at Scale

**Universal Sponsorship (BAD):**
```
Daily external txns: 10,000
Cost: 10 ALGO/day = 300 ALGO/month (~$50-100)
Abuse risk: HIGH (bots, wash trading)
```

**Selective Sponsorship (GOOD):**
```
Daily app txns: 1,000
Cost: 1 ALGO/day = 30 ALGO/month (~$5-15)
Abuse risk: LOW (controlled flows)
```

### MBR Float Considerations

```
Presale:
- 1k users = 21.7 ALGO locked
- 100k users = 2,170 ALGO locked
- 1M users = 21,700 ALGO locked (!)

P2P Trading:
- 1k active trades = 70 ALGO locked
- 10k active trades = 700 ALGO locked

All MBR is recoverable, but requires capital float
```

## Anti-Abuse Guardrails

### 1. Presale Contract (`confio_presale.py`)
```python
# Implemented guardrails:
min_buy_amount = 1 cUSD        # Prevent micro-spam
max_per_address = 100k CONFIO   # Per-round cap
daily_sponsor_budget = 100 ALGO # Daily limit
sponsor_enabled = toggle        # Can turn off
```

### 2. First-Time vs Repeat Users
- **First buy**: Sponsor pays MBR for box creation (0.022 ALGO)
- **Repeat buys**: No MBR needed, minimal sponsorship
- **Claims**: Delete box, recover MBR to sponsor

### 3. Daily Budget Management
```python
# Reset daily budget every 24 hours
if (timestamp > last_reset + 86400):
    daily_used = 0
    last_reset = timestamp

# Check budget before sponsoring
if (daily_used + tx_cost > daily_budget):
    require_user_payment()  # Fallback to user pays
```

## Implementation Architecture

### 1. Contract Level
Production contracts include sponsor support:
- `p2p_vault.py` ✅
- `inbox_router.py` ✅
- `payment_router.py` ✅
- `confio_presale.py` ✅ (with anti-abuse)

### 2. App Level (Backend)
```python
# Relayer service builds sponsored groups
def build_sponsored_group(user_txn):
    if should_sponsor(user_txn):
        sponsor_payment = create_sponsor_payment()
        return [sponsor_payment, user_txn]
    else:
        return [user_txn]  # User pays

def should_sponsor(txn):
    # Check daily budget
    if daily_used >= daily_budget:
        return False
    
    # Check minimum amounts
    if txn.amount < min_amount:
        return False
    
    # Check user limits
    if user_daily_txns >= max_per_user:
        return False
    
    return True
```

### 3. Frontend Integration
```javascript
// User only signs their transaction
const userTxn = await buildUserTransaction();
const signedTxn = await wallet.signTransaction(userTxn);

// Backend adds sponsor payment
const response = await api.submitSponsoredTransaction(signedTxn);
```

## Cost Projections

### Conservative (1k daily active users)
```
Presale: 10 ALGO/day (new users + buys)
P2P: 5 ALGO/day (trades)
Payments: 2 ALGO/day
Total: ~17 ALGO/day = 510 ALGO/month (~$75)
```

### Growth Phase (10k daily active users)
```
Presale: 50 ALGO/day
P2P: 30 ALGO/day
Payments: 20 ALGO/day
Total: ~100 ALGO/day = 3,000 ALGO/month (~$450)
```

### Scale Phase (100k daily active users)
```
Implement stricter guardrails:
- Sponsor only first transaction per day
- Higher minimum amounts
- Partner with wallet providers
Target: <500 ALGO/day = 15,000 ALGO/month (~$2,250)
```

## Future Considerations

### Phase 1: Current Implementation ✅
- Sponsor core app flows
- Monitor costs closely
- Gather usage data

### Phase 2: Optimization (3 months)
- Analyze abuse patterns
- Tune guardrails
- Consider tiered sponsorship (VIP users)

### Phase 3: Partnerships (6 months)
- Whitelist partner apps for sponsorship
- Revenue sharing with DEXs
- Corporate sponsors for specific flows

## Key Decisions

### ✅ DO:
- Sponsor presale buy/claim
- Sponsor P2P trades
- Sponsor payment routing
- Implement daily budgets
- Add minimum amounts
- Track per-user limits

### ❌ DON'T:
- Universal sponsorship for cUSD/CONFIO
- Sponsor DEX trades
- Sponsor without guardrails
- Allow unlimited usage

## Monitoring & Alerts

Set up monitoring for:
```
- Daily sponsor spend > 80% of budget
- Unusual spike in transactions
- Repeated failed sponsorships
- MBR float > threshold
- Per-user abuse patterns
```

## Emergency Controls

All production contracts include:
1. **Toggle sponsorship on/off**
2. **Update sponsor address**
3. **Emergency pause**
4. **Adjust guardrails without redeployment**

## Conclusion

By sponsoring only specific flows within our app with proper guardrails, we can provide a seamless user experience while maintaining sustainable costs and preventing abuse. Users never need ALGO within the Confío app, but standard blockchain fees apply for external usage of cUSD and CONFIO tokens.