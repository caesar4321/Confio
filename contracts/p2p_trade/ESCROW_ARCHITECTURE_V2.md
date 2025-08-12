# Algorand Escrow Architecture V2 - Capital Efficient Design

## Executive Summary
Following ChatGPT's excellent analysis, this revised architecture uses pooled vaults with box storage to minimize ALGO lock-up while maintaining security and functionality. The key insight: use box storage (recoverable) instead of per-trade escrows (expensive).

## Cost Comparison

### Original Design (Per-Trade Escrows)
- **Per P2P Trade**: ~0.3 ALGO locked (0.1 base + 0.2 for assets)
- **5,000 concurrent trades**: ~1,500 ALGO locked
- **Recovery**: Only when trade completes

### New Design (Pooled Vault + Boxes)
- **One-time vault setup**: 0.3 ALGO (permanent) - dual asset support
- **Per P2P Trade**: 0.0701 ALGO (box storage, recoverable)
- **5,000 concurrent trades**: 350.5 ALGO temporarily + 0.3 permanent
- **Recovery**: Immediate on trade completion
- **Savings**: 76.7% less ALGO locked

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

**Box Storage (137 bytes per trade)**:
```
trade_id (max 56B key) → {
  seller: 32 bytes
  amount: 8 bytes
  asset_id: 8 bytes (cUSD or CONFIO)
  created_at: 8 bytes
  expires_at: 8 bytes
  status: 1 byte
  accepted_at: 8 bytes
  buyer: 32 bytes
  mbr_payer: 32 bytes
}
```

**MBR Cost**: 2500 + 400 × (key_len + 137) microAlgos
- With 32-byte key: 70,100 microAlgos = 0.0701 ALGO per trade
- With 56-byte key: 79,700 microAlgos = 0.0797 ALGO per trade (max)
- Trade ID must be ≤ 56 bytes to allow for suffixes (_paid, _dispute)

**_paid Box MBR** (value=41 bytes, key=trade_id+"_paid"):
- With 32-byte trade_id: key=37 → 33,700 microAlgos = 0.0337 ALGO
- With 56-byte trade_id: key=61 → 43,300 microAlgos = 0.0433 ALGO

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
claim_code (max 56B key) → {
  sender: 32 bytes
  cusd_amount: 8 bytes
  confio_amount: 8 bytes
  expiry: 8 bytes
  metadata: 8 bytes
}
```

**MBR Cost**: 2500 + 400 × (key_len + 64) microAlgos
- With 32-byte key: 40,900 microAlgos = 0.0409 ALGO per invite
- With 56-byte key: 50,500 microAlgos = 0.0505 ALGO per invite (max)

## Transaction Flows

**Box References Required**:
- `create_trade`: trade_id
- `accept_trade`: trade_id
- `mark_as_paid`: trade_id, trade_id_paid (create)
- `confirm_payment_received`: trade_id, trade_id_paid (if exists)
- `cancel_trade`: trade_id, trade_id_paid (if exists), trade_id_dispute (if exists)
- `open_dispute`: trade_id, trade_id_dispute (create)
- `resolve_dispute`: trade_id, trade_id_dispute, trade_id_paid (if exists)

**Important for Client Developers**: 
- Remember to include both the base trade_id and any suffixed box references (trade_id+"_paid", trade_id+"_dispute") in the AppCall's boxes array. The contract will fail if required box references are missing.
- When creating "_paid" or "_dispute" boxes, you must include the suffixed key in your boxes array (e.g., for mark_as_paid include both trade_id and trade_id+"_paid").
- When reading _paid/_dispute boxes in confirm/cancel/resolve operations, include those keys in the AppCall boxes array even if you think they won't exist; the contract handles the 'missing' case but still needs the reference.
- For operations with sponsor fee-bumps, the sponsor's Payment transaction fee pools for the entire group (Algorand fee pooling) - set it high enough to cover all outer + inner transactions.

### P2P Trade Flow (One-sided deposit + fiat off-chain)

**Client Fee Notes**: 
- Clients must pay the outer transaction fee (0.001 ALGO) for each operation
- Operations requiring sponsor fee-bumps (confirm_payment_received, resolve_dispute) need sponsor participation
- Cancel operations do NOT require sponsor - anyone can clean expired trades

```python
# 1. Create trade (MBR funded)
[Payment(mbr), AXFER(seller→vault asset), AppCall create_trade]
→ Creates box (0.0701 ALGO from creator/sponsor)
→ Seller deposits cUSD or CONFIO
→ Client pays: 0.003 ALGO tx fees (3 transactions)

# 2. Buyer accepts
[AppCall accept_trade]  # starts 15-min window
→ Client pays: 0.001 ALGO tx fee

# 3. (optional) Buyer marks as paid
[Payment(mbr for _paid box), AppCall mark_as_paid]
→ Creates paid box to signal fiat payment sent
→ Can extend window by 10 minutes once
→ Client pays: 0.002 ALGO tx fees + ≈0.034-0.043 ALGO for _paid box MBR (budget 0.045)

# 4. Seller confirms payment received
[Payment(sponsor fee-bump), AppCall confirm_payment_received]
→ Inner AXFER vault→buyer (full amount, no fee)
→ box_delete (frees MBR to app)
→ Inner payment refund MBR to payer
→ Fee budgeting: Group must cover 1 inner AXFER + up to 2 inner PAYs ≈ 3000 µALGO
→ Sponsor Payment: Set fee ≥ 0.003 ALGO (pools for entire group via Algorand fee pooling)
→ Seller AppCall: Keep at 0.001 ALGO (wallet default)

# 5. Cancel (no sponsor needed - anyone can clean expired)
[AppCall cancel_trade]
→ Return funds to seller
→ box_delete (frees MBR to app)
→ Inner payment refund MBR to payer
→ Client pays: 0.003-0.004 ALGO tx fee (covers inner AXFER + 1-2 inner refunds)

# 6. Resolve dispute (admin only)
[Payment(sponsor fee-bump), AppCall resolve_dispute(winner)]
→ Inner AXFER vault→winner
→ box_delete dispute and trade boxes
→ Inner payment refund MBRs to payers
→ Fee budgeting: Group must cover 1 inner AXFER + 2 inner PAYs ≈ 4000 µALGO
→ Sponsor Payment: Set fee ≥ 0.004 ALGO (pools for entire group)
→ Admin AppCall: Keep at 0.001 ALGO (wallet default)
```

### Send & Invite Flow
```python
# 1. Send to non-user
[AXFER sender→inbox(assets), AppCall send(claim_code)]
→ Creates box (0.0409 ALGO from sender)

# 2. Recipient claims (after opt-in)
[AppCall claim(claim_code)]
→ Inner AXFER inbox→recipient
→ box_delete (frees MBR to app)
→ Inner payment app→sender (0.0409 ALGO refund)

# 3. Or reclaim if expired
[AppCall reclaim(claim_code)]
→ Inner AXFER inbox→sender
→ box_delete (frees MBR to app)
→ Inner payment app→sender (0.0409 ALGO refund)
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
3. **Explicit MBR refunds**: box_delete frees MBR, contract sends refunds
4. **State isolation**: Each trade's state is independent

### DoS Protection
1. **MBR deposit**: Creator pays box MBR upfront
2. **Expiry enforcement**: 15 minutes for P2P, 7 days for invites
3. **Garbage collection**: Anyone can cancel expired trades after grace period

## Recovery Mechanisms

### Automatic Recovery
1. **Garbage Collection**:
   - Anyone can call `cancel_trade` after expiry + grace period
   - No reward in current implementation (keeps it simple)
   - Subject to per-transaction box reference limits (8 box refs max)

2. **Active Trade Monitoring**:
   - Track active_trades counter
   - Monitor completion/cancellation stats

### Recovery Example
```python
# 5,000 expired trades = 350.5 ALGO locked
# Anyone can call cancel_trade on expired trades:
# - Recovers: 350.5 ALGO refunded to MBR payers
# - No rewards in current implementation
# - Cost: Only transaction fees
```

### Comparison to Per-Trade Escrows

| Aspect | Per-Trade Escrows | Pooled Vault + Boxes |
|--------|------------------|---------------------|
| ALGO per trade | 0.3 locked | 0.0701 temporary |
| Setup complexity | Deploy per trade | One-time setup |
| Gas costs | Higher (new contract) | Lower (box ops) |
| Audit trail | Separate accounts | Box history |
| Upgrade path | Old trades stuck | New logic for new trades |
| State queries | Multiple accounts | Single app state |

## Setup Order (IMPORTANT)

To avoid setup confusion, follow this exact initialization sequence:

1. **Deploy app** - Create the smart contract
2. **set_sponsor** - Configure sponsor address for MBR funding
3. **setup_assets** - Sponsor funds 0.2 ALGO to app for ASA opt-ins
4. **Go live** - Start accepting trades

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
- P2P Trade: 0.0701 ALGO (recovered on completion)
- Send Invite: 0.0409 ALGO (recovered on claim)
- Payment: 0.002 ALGO (tx fees only)

### At Scale (10,000 users, 5,000 trades)
- **Old design**: ~1,500 ALGO locked
- **New design**: 350.5 ALGO temporary + 0.7 permanent
- **Savings**: 1,149 ALGO (~76.7% reduction)

## Key Takeaways

1. **Box storage is the key**: 5-8x cheaper than account MBR
2. **Pool assets once**: Don't opt-in per trade
3. **Atomic is best**: Payment router needs no escrow
4. **ARC-59 pattern**: Solves the invite problem elegantly
5. **Dual asset support**: Both cUSD and CONFIO in same contracts

This architecture achieves ChatGPT's goal of minimizing capital lock-up while maintaining security and supporting both cUSD and CONFIO throughout the system.