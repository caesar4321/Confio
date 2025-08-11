# Algorand Escrow Architecture V2 - Capital Efficient Design

## Executive Summary
Following ChatGPT's excellent analysis, this revised architecture uses pooled vaults with box storage to minimize ALGO lock-up while maintaining security and functionality. The key insight: use box storage (recoverable) instead of per-trade escrows (expensive).

## Cost Comparison

### Original Design (Per-Trade Escrows)
- **Per P2P Trade**: ~0.3 ALGO locked (0.1 base + 0.2 for assets)
- **5,000 concurrent trades**: ~1,500 ALGO locked
- **Recovery**: Only when trade completes

### New Design (Pooled Vault + Boxes)
- **One-time vault setup**: 0.3 ALGO (permanent)
- **Per P2P Trade**: ~0.0672 ALGO (box storage, recoverable)
- **5,000 concurrent trades**: ~336 ALGO temporarily + 0.3 permanent
- **Recovery**: Immediate on trade completion
- **Savings**: ~78% less ALGO locked

## Architecture Overview

### 1. Payment Router (Pay) - NO CHANGE
```
User → [Atomic Group] → 99.1% Merchant
                     → 0.9% Fee Vault
```
- **No escrow needed** - atomic transactions
- **No opt-ins** for router (doesn't hold funds)
- **Cost**: 0.1 ALGO one-time deployment

### 2. P2P Vault (Trading) - MAJOR IMPROVEMENT
```
[Single P2P Vault App]
  ├── Opted into cUSD (once)
  ├── Opted into CONFIO (once)
  ├── Boxes per trade (recoverable)
  └── 15-minute expiry for active trades
```

**Box Storage (136 bytes per trade)**:
```
trade_id (32B key) → {
  seller: 32 bytes
  buyer: 32 bytes
  seller_asset: 8 bytes (cUSD or CONFIO)
  buyer_asset: 8 bytes (cUSD or CONFIO)
  seller_amount: 8 bytes
  buyer_amount: 8 bytes
  state: 8 bytes
  created_time: 8 bytes
  expiry_time: 8 bytes
  seller_funded: 8 bytes
  buyer_funded: 8 bytes
}
```

**MBR Cost**: 2500 + 400 × (32 + 136) = 69,700 microAlgos = 0.0697 ALGO per trade

### 3. Inbox Router (Send & Invite) - ARC-59 PATTERN
```
[Single Inbox Router App]
  ├── Opted into cUSD (once)
  ├── Opted into CONFIO (once)
  ├── Boxes per invite (recoverable)
  └── 7-day expiry for invites
```

**Box Storage (64 bytes per invite)**:
```
claim_code (32B key) → {
  sender: 32 bytes
  cusd_amount: 8 bytes
  confio_amount: 8 bytes
  expiry: 8 bytes
  metadata: 8 bytes
}
```

**MBR Cost**: 2500 + 400 × (32 + 64) = 40,900 microAlgos = 0.0409 ALGO per invite

## Transaction Flows

### P2P Trade Flow
```python
# 1. Create trade
[AppCall create_trade(trade_id, seller, buyer, amounts)]
→ Creates box (0.0697 ALGO from creator)

# 2. Seller deposits
[AXFER seller→vault(cUSD), AppCall deposit(trade_id)]

# 3. Buyer deposits  
[AXFER buyer→vault(CONFIO), AppCall deposit(trade_id)]

# 4. Complete trade
[AppCall complete(trade_id)]
→ Inner AXFER vault→buyer (cUSD - fee)
→ Inner AXFER vault→seller (CONFIO - fee)
→ box_delete (recovers 0.0697 ALGO)
```

### Send & Invite Flow
```python
# 1. Send to non-user
[AXFER sender→inbox(assets), AppCall send(claim_code)]
→ Creates box (0.0409 ALGO from sender)

# 2. Recipient claims (after opt-in)
[AppCall claim(claim_code)]
→ Inner AXFER inbox→recipient
→ box_delete (recovers 0.0409 ALGO)

# 3. Or reclaim if expired
[AppCall reclaim(claim_code)]
→ Inner AXFER inbox→sender
→ box_delete (recovers 0.0409 ALGO)
```

## Dual Asset Support

Both P2P Vault and Inbox Router support cUSD and CONFIO:

1. **Single opt-in**: Each vault opts into both assets once
2. **Flexible trades**: Can trade cUSD↔CONFIO, cUSD↔cUSD, CONFIO↔CONFIO
3. **Combined sends**: Can send both assets in one invite
4. **Fee efficiency**: 0.2 ALGO permanent per vault vs 0.2 per trade

## Security & Safety

### Box Storage Benefits
1. **Atomic operations**: Box create/update/delete are atomic
2. **No replay**: Each trade_id is unique
3. **Automatic cleanup**: box_delete recovers MBR
4. **State isolation**: Each trade's state is independent

### DoS Protection
1. **MBR deposit**: Creator pays box MBR upfront
2. **Expiry enforcement**: 15 minutes for P2P, 7 days for invites
3. **Rate limiting**: Max trades per address
4. **Garbage collection**: Anyone can cancel expired trades

## Recovery Mechanisms

### Automatic Recovery
1. **Garbage Collection (GC)**:
   - Anyone can call `gc_single` to clean expired trades
   - Receives 1% of recovered MBR as incentive (~0.0007 ALGO per trade)
   - Batch GC can clean up to 5 trades in one transaction

2. **Emergency Recovery**:
   - Admin-only function for trades expired >24 hours
   - Failsafe for stuck funds

3. **Recovery Stats**:
   - Track total recovered ALGO
   - Monitor active trades
   - Last GC timestamp

### Recovery Example
```python
# 5,000 expired trades = ~348.5 ALGO locked
# Anyone calls gc_batch repeatedly:
# - Recovers: 348.5 ALGO to vault
# - Earns: ~3.5 ALGO in rewards
# - Cost: Only transaction fees
```

### Comparison to Per-Trade Escrows

| Aspect | Per-Trade Escrows | Pooled Vault + Boxes |
|--------|------------------|---------------------|
| ALGO per trade | 0.3 locked | 0.0697 temporary |
| Setup complexity | Deploy per trade | One-time setup |
| Gas costs | Higher (new contract) | Lower (box ops) |
| Audit trail | Separate accounts | Box history |
| Upgrade path | Old trades stuck | New logic for new trades |
| State queries | Multiple accounts | Single app state |

## Implementation Priority

### Phase 1: Core Infrastructure
1. ✅ Payment Router (already good)
2. ✅ P2P Vault with box storage
3. ✅ Inbox Router (ARC-59 style)

### Phase 2: Optimizations
1. Batch operations (multiple trades in one tx)
2. Fee distribution contract (CONFIO rewards)
3. Analytics dashboard (read box states)

### Phase 3: Advanced Features
1. Multi-sig trades (requires both parties to complete)
2. Partial fills (for large trades)
3. Time-locked releases

## Migration Path

For existing per-trade escrows:
1. Complete all active trades
2. Deploy new pooled vault
3. Route new trades to pooled system
4. Recover ALGO from old escrows

## Cost Summary

### One-Time Costs (Permanent)
- Payment Router: 0.1 ALGO
- P2P Vault: 0.3 ALGO (0.1 base + 0.2 assets)
- Inbox Router: 0.3 ALGO (0.1 base + 0.2 assets)
- **Total**: 0.7 ALGO permanent

### Per-Operation Costs (Recoverable)
- P2P Trade: 0.0697 ALGO (recovered on completion)
- Send Invite: 0.0409 ALGO (recovered on claim)
- Payment: 0.002 ALGO (tx fees only)

### At Scale (10,000 users, 5,000 trades)
- **Old design**: ~1,500 ALGO locked
- **New design**: ~336 ALGO temporary + 0.7 permanent
- **Savings**: 1,163 ALGO (~78% reduction)

## Key Takeaways

1. **Box storage is the key**: 5-8x cheaper than account MBR
2. **Pool assets once**: Don't opt-in per trade
3. **Atomic is best**: Payment router needs no escrow
4. **ARC-59 pattern**: Solves the invite problem elegantly
5. **Dual asset support**: Both cUSD and CONFIO in same contracts

This architecture achieves ChatGPT's goal of minimizing capital lock-up while maintaining security and supporting both cUSD and CONFIO throughout the system.