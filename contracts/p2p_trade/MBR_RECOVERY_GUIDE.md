# MBR Recovery Guide - Complete Scenarios

## Overview
Every box creation locks MBR (Minimum Balance Requirement) that must be **explicitly refunded** when the box is deleted. The contract handles this by sending inner payment transactions to return MBR to the original payers. This happens in ALL scenarios where a trade/invite ends.

## P2P Trades (0.0701 ALGO per trade)

### ✅ Successful Trade Completion
```python
def complete_trade():
    # ... transfer asset to buyer (one-sided, fiat paid off-chain) ...
    Assert(App.box_delete(trade_id))  # ← Frees MBR in app account
    # Inner payment sends 0.0701 ALGO back to creator
    InnerTxn.payment(creator, mbr_amount)
```
**Result**: Trade creator receives 0.0701 ALGO back via inner payment

### ✅ Trade Cancellation (by either party)
```python
def cancel_trade():
    # ... return funds to original owners ...
    Assert(App.box_delete(trade_id))  # ← Frees MBR in app account
    # Inner payment sends 0.0701 ALGO back to creator
    InnerTxn.payment(creator, mbr_amount)
```
**Result**: Trade creator receives 0.0701 ALGO back via inner payment

### ✅ Expired Trade Cleanup (after 15 minutes + grace period)
```python
def cancel_expired_trade():
    # ... anyone can call cancel_trade after expiry + grace ...
    # ... returns funds to original owners ...
    Assert(App.box_delete(trade_id))  # ← Frees MBR in app account
    # Inner payment sends full MBR back to creator
    InnerTxn.payment(creator, mbr_amount)
```
**Result**: 
- Trade creator receives full 0.0701 ALGO back
- No reward in current implementation

## Send & Invite (0.0409 ALGO per invite)

### ✅ Successful Claim (recipient joins and claims)
```python
def claim_funds():
    # ... transfer assets to recipient ...
    Assert(App.box_delete(claim_code))  # ← Frees MBR in app account
    # Inner payment sends 0.0409 ALGO back to sender
    InnerTxn.payment(sender, mbr_amount)
```
**Result**: Original sender receives 0.0409 ALGO back via inner payment

### ✅ Reclaim by Sender (before expiry)
```python
def reclaim_expired():
    # ... if sender reclaims their own invite ...
    Assert(App.box_delete(claim_code))  # ← Frees MBR in app account
    # Inner payment sends 0.0409 ALGO back to sender
    InnerTxn.payment(sender, mbr_amount)
```
**Result**: Sender receives 0.0409 ALGO back via inner payment

### ✅ Expired Invite Cleanup (after 7 days)
```python
def reclaim_expired():
    # ... anyone can call this after expiry ...
    # ... returns funds to original sender ...
    Assert(App.box_delete(claim_code))  # ← Frees MBR in app account
    # Inner payment sends 0.0409 ALGO back to sender
    InnerTxn.payment(sender, mbr_amount)
```
**Result**: Original sender receives 0.0409 ALGO back via inner payment

## MBR Recovery Summary

| Scenario | Who Pays MBR | Who Gets MBR Back | When | Amount |
|----------|--------------|-------------------|------|--------|
| **P2P Trade** | | | | |
| Trade completed | Trade creator | Trade creator | On completion | 0.0701 ALGO |
| Trade cancelled | Trade creator | Trade creator | On cancellation | 0.0701 ALGO |
| Trade expired | Trade creator | Trade creator | After 15 min + grace | 0.0701 ALGO |
| **Send & Invite** | | | | |
| Invite claimed | Sender | Sender | When claimed | 0.0409 ALGO |
| Invite reclaimed | Sender | Sender | Before expiry | 0.0409 ALGO |
| Invite expired | Sender | Sender | After 7 days | 0.0409 ALGO |

## Key Points

1. **MBR is ALWAYS refunded** - The contract explicitly sends MBR back via inner payments
2. **Explicit refund required** - `box_delete` only frees MBR to app account, contract must send it back
3. **Contract handles refunds** - All refunds are automated within the contract logic
4. **Simple cleanup** - Anyone can cancel expired trades (no complex reward logic)

## Capital Efficiency at Scale

### Example: 5,000 Active P2P Trades
- **Temporary lock**: 5,000 × 0.0701 = 350.5 ALGO
- **After completion**: ALL 350.5 ALGO recovered
- **If 10% expire**: 
  - 4,500 complete normally → 315.45 ALGO recovered
  - 500 expire → 35.05 ALGO recovered (full refund)
  - No rewards, just tx fees for cleanup

### Example: 1,000 Pending Invites
- **Temporary lock**: 1,000 × 0.0409 = 40.9 ALGO
- **After 7 days**: ALL 40.9 ALGO recovered
- **If 80% claimed, 20% expire**:
  - 800 claimed → 32.72 ALGO recovered
  - 200 expire → 8.18 ALGO recovered

## Permanent Costs (Never Recovered)

The only permanent costs are the one-time opt-ins:

1. **P2P Vault**: 0.3 ALGO (app account + 2 assets)
2. **Inbox Router**: 0.3 ALGO (app account + 2 assets)
3. **Payment Router**: 0.1 ALGO (app account only)

**Total permanent**: 0.7 ALGO for entire system

## Comparison to Per-Trade Escrows

| Design | Active Trades | Permanent Lock | Temporary Lock | Recovery |
|--------|--------------|----------------|----------------|----------|
| Per-trade escrows | 5,000 | 0 ALGO | 1,500 ALGO | Complex close-out |
| Pooled + boxes | 5,000 | 0.7 ALGO | 350.5 ALGO | Automatic on completion |

## Conclusion

The pooled vault + box storage design ensures:
- ✅ **100% MBR refunds** via explicit inner payments
- ✅ **Contract-managed refunds** after each `box_delete`
- ✅ **No locked capital** except minimal one-time opt-ins
- ✅ **Self-cleaning** via garbage collection incentives
- ✅ **76.7% less capital** required vs per-trade escrows