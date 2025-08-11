# P2P Trade Dispute Resolution Guide

## Overview
The P2P vault includes a comprehensive dispute resolution system that protects both buyers and sellers while ensuring trades can't get stuck indefinitely.

## Trade Flow with Dispute Protection

### Standard Flow (No Disputes)
```
1. Create Trade → Both fund → Mark complete → 5-min window → Finalize → Funds released
                                                     ↓
                                              (No dispute raised)
```

### Disputed Flow
```
1. Create Trade → Both fund → Mark complete → 5-min window → DISPUTE! → Arbitration → Resolution
                                                     ↓
                                              (Dispute raised)
```

## Dispute Mechanism Details

### 1. Completion Phase
```python
mark_complete(trade_id)
```
- Either party marks trade as "complete"
- Starts 5-minute dispute window
- Funds remain locked in escrow

### 2. Dispute Window (5 minutes)
During this window:
- **Either party can dispute** with reason code
- **No funds are released** yet
- Protects against premature completion

### 3. Dispute Resolution Options

#### Option A: Automatic Finalization (No Dispute)
```python
finalize_trade(trade_id)  # After 5 minutes
```
- If no dispute raised within 5 minutes
- Anyone can call finalize
- Funds automatically released to intended parties
- MBR recovered

#### Option B: Arbitration (Dispute Raised)
```python
arbitrate_dispute(trade_id, seller_%, buyer_%)
```
- Only authorized arbitrator can resolve
- Custom fund distribution:
  - Seller gets: `seller_%` of their original funds
  - Buyer gets: `buyer_%` of their original funds
  - Arbitrator gets: `(100 - seller_% - buyer_%)%` as fee
- Example: `arbitrate(trade_id, 50, 45)` = 50% to seller, 45% to buyer, 5% to arbitrator

#### Option C: Emergency Cancel (After 24 hours)
```python
emergency_cancel_dispute(trade_id)
```
- For stuck disputed trades
- Available 24 hours after dispute
- Returns all funds to original owners
- No fees taken

## Dispute Reason Codes

Suggested 8-byte codes for common disputes:

| Code | Meaning |
|------|---------|
| `0x0000000000000001` | Payment not received |
| `0x0000000000000002` | Incorrect payment amount |
| `0x0000000000000003` | Payment from wrong account |
| `0x0000000000000004` | Item not as described |
| `0x0000000000000005` | Fraud suspected |
| `0x0000000000000006` | Technical issue |
| `0x0000000000000007` | Mutual cancellation requested |
| `0x0000000000000008` | Other (details off-chain) |

## Arbitration Examples

### Example 1: Clear Seller Fault
- Seller didn't deliver fiat payment
- Arbitration: `arbitrate(trade_id, 0, 95)`
- Result: Buyer gets 95%, Arbitrator gets 5% fee

### Example 2: Clear Buyer Fault  
- Buyer falsely claims non-payment
- Arbitration: `arbitrate(trade_id, 95, 0)`
- Result: Seller gets 95%, Arbitrator gets 5% fee

### Example 3: Partial Fault
- Miscommunication between parties
- Arbitration: `arbitrate(trade_id, 45, 45)`
- Result: Each gets 45%, Arbitrator gets 10% fee

### Example 4: Mutual Agreement
- Both agree to cancel
- Arbitration: `arbitrate(trade_id, 50, 50)`
- Result: Each gets 50% back, no arbitrator fee

## Timeline Protection

```
T+0 min:   Trade marked complete
T+5 min:   Dispute window closes
           → If no dispute: Can finalize
           → If disputed: Awaiting arbitration
T+24 hrs:  Emergency cancel available (disputed trades only)
```

## MBR Considerations

- **Standard trade box**: 136 bytes = 0.0697 ALGO
- **With dispute fields**: 152 bytes = 0.0762 ALGO
- **Additional cost**: ~0.0065 ALGO per trade
- **Always recovered**: On finalization/resolution/cancel

## Security Features

1. **Time-locked releases**: 5-minute safety window
2. **Dual confirmation**: Both parties can trigger completion
3. **Arbitrator authority**: Trusted third party for disputes
4. **Emergency recovery**: Failsafe after 24 hours
5. **Transparent resolution**: All decisions on-chain

## Integration with Frontend

### Status Display
```javascript
switch(trade.state) {
  case FUNDED:
    return "Ready to complete";
  case COMPLETED:
    if (now < completionTime + 300) {
      return `Dispute window: ${timeLeft} remaining`;
    } else {
      return "Ready to finalize";
    }
  case DISPUTED:
    return "Under review by arbitrator";
  case RESOLVED:
    return "Trade completed";
}
```

### User Actions
```javascript
// Mark trade as complete
if (trade.state === FUNDED) {
  await markComplete(tradeId);
}

// Raise dispute
if (trade.state === COMPLETED && withinDisputeWindow) {
  await raiseDispute(tradeId, reasonCode);
}

// Finalize (after window)
if (trade.state === COMPLETED && !withinDisputeWindow) {
  await finalizeTrade(tradeId);
}
```

## Best Practices

### For Traders
1. Document all off-chain payments
2. Use clear communication
3. Raise disputes promptly if issues arise
4. Provide evidence to arbitrator

### For Arbitrators
1. Review evidence thoroughly
2. Apply consistent resolution patterns
3. Document decisions off-chain
4. Aim for fair, proportional resolutions

### For Platform
1. Select trusted arbitrators
2. Set reasonable dispute windows
3. Monitor dispute rates
4. Provide clear dispute guidelines

## Comparison to Simple Escrow

| Feature | Simple Escrow | With Disputes |
|---------|--------------|---------------|
| Completion | Immediate | 5-min window |
| Dispute handling | None | Full arbitration |
| Stuck trades | Possible | Emergency recovery |
| MBR cost | 0.0697 ALGO | 0.0762 ALGO |
| User protection | Basic | Comprehensive |

## Conclusion

The dispute system adds minimal overhead (0.0065 ALGO per trade) while providing:
- ✅ Protection against premature release
- ✅ Fair arbitration mechanism
- ✅ Emergency recovery options
- ✅ Full MBR recovery in all cases
- ✅ Transparent on-chain resolution