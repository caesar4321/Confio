# MBR Recovery Guide - Complete Scenarios

## Overview
Every box creation locks MBR (Minimum Balance Requirement) that is **automatically recovered** when the box is deleted. This happens in ALL scenarios where a trade/invite ends.

## P2P Trades (0.0697 ALGO per trade)

### ✅ Successful Trade Completion
```python
def complete_trade():
    # ... swap assets between parties ...
    Assert(App.box_delete(trade_id))  # ← MBR RECOVERED HERE
    # Creator gets back 0.0697 ALGO
```
**Result**: Trade creator automatically receives 0.0697 ALGO back

### ✅ Trade Cancellation (by either party)
```python
def cancel_trade():
    # ... return funds to original owners ...
    Assert(App.box_delete(trade_id))  # ← MBR RECOVERED HERE
    # Creator gets back 0.0697 ALGO
```
**Result**: Trade creator automatically receives 0.0697 ALGO back

### ✅ Expired Trade Cleanup (after 15 minutes)
```python
def gc_single_trade():
    # ... anyone can call this after expiry ...
    # ... returns funds to original owners ...
    Assert(App.box_delete(trade_id))  # ← MBR RECOVERED HERE
    # Original creator gets back 0.0697 ALGO
    # Caller gets small reward (1% = 0.0007 ALGO)
```
**Result**: 
- Trade creator receives ~0.069 ALGO back
- Garbage collector receives ~0.0007 ALGO reward

## Send & Invite (0.0409 ALGO per invite)

### ✅ Successful Claim (recipient joins and claims)
```python
def claim_funds():
    # ... transfer assets to recipient ...
    Assert(App.box_delete(claim_code))  # ← MBR RECOVERED HERE
    # Sender gets back 0.0409 ALGO
```
**Result**: Original sender automatically receives 0.0409 ALGO back

### ✅ Reclaim by Sender (before expiry)
```python
def reclaim_expired():
    # ... if sender reclaims their own invite ...
    Assert(App.box_delete(claim_code))  # ← MBR RECOVERED HERE
    # Sender gets back 0.0409 ALGO
```
**Result**: Sender automatically receives 0.0409 ALGO back

### ✅ Expired Invite Cleanup (after 7 days)
```python
def reclaim_expired():
    # ... anyone can call this after expiry ...
    # ... returns funds to original sender ...
    Assert(App.box_delete(claim_code))  # ← MBR RECOVERED HERE
    # Original sender gets back 0.0409 ALGO
```
**Result**: Original sender automatically receives 0.0409 ALGO back

## MBR Recovery Summary

| Scenario | Who Pays MBR | Who Gets MBR Back | When | Amount |
|----------|--------------|-------------------|------|--------|
| **P2P Trade** | | | | |
| Trade completed | Trade creator | Trade creator | On completion | 0.0697 ALGO |
| Trade cancelled | Trade creator | Trade creator | On cancellation | 0.0697 ALGO |
| Trade expired (GC) | Trade creator | Trade creator (minus reward) | After 15 min | ~0.069 ALGO |
| **Send & Invite** | | | | |
| Invite claimed | Sender | Sender | When claimed | 0.0409 ALGO |
| Invite reclaimed | Sender | Sender | Before expiry | 0.0409 ALGO |
| Invite expired | Sender | Sender | After 7 days | 0.0409 ALGO |

## Key Points

1. **MBR is ALWAYS recovered** - There's no scenario where MBR is permanently lost
2. **Automatic recovery** - The `box_delete` operation automatically returns MBR to the original payer
3. **No manual intervention needed** - Recovery happens as part of normal operations
4. **Incentivized cleanup** - Even expired trades get cleaned up thanks to GC rewards

## Capital Efficiency at Scale

### Example: 5,000 Active P2P Trades
- **Temporary lock**: 5,000 × 0.0697 = 348.5 ALGO
- **After completion**: ALL 348.5 ALGO recovered
- **If 10% expire**: 
  - 4,500 complete normally → 313.65 ALGO recovered
  - 500 expire → ~34.5 ALGO recovered via GC
  - GC collectors earn → ~0.35 ALGO total rewards

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
| Pooled + boxes | 5,000 | 0.7 ALGO | 348.5 ALGO | Automatic on completion |

## Conclusion

The pooled vault + box storage design ensures:
- ✅ **100% MBR recovery** on all completed/cancelled/expired operations
- ✅ **Automatic recovery** via `box_delete`
- ✅ **No locked capital** except minimal one-time opt-ins
- ✅ **Self-cleaning** via garbage collection incentives
- ✅ **78% less capital** required vs per-trade escrows