# Algorand Escrow Architecture for Confío

## Overview
Algorand requires accounts (including smart contracts) to opt-in to assets before receiving them. Each opt-in locks 0.1 ALGO minimum balance requirement (MBR). This creates design challenges for escrow contracts.

## Current Use Cases

### 1. Pay (Merchant Payments)
- **Flow**: User → Contract → Split (99.1% merchant, 0.9% vault)
- **Assets**: cUSD, CONFIO
- **Frequency**: High volume, multiple merchants

### 2. P2P Escrow (Trading)
- **Flow**: Seller → Escrow → Buyer (on confirmation)
- **Assets**: cUSD, CONFIO, potentially USDC
- **Frequency**: Medium volume, unique pairs

### 3. Send & Invite (Non-user transfers)
- **Flow**: Sender → Escrow → Recipient (when they join)
- **Assets**: cUSD, CONFIO
- **Frequency**: Low volume, long holding periods

## Architecture Options

### Option 1: Single Global Escrow (NOT RECOMMENDED)
```
[Global Escrow Contract]
  ├── Opted into cUSD
  ├── Opted into CONFIO
  └── Opted into USDC
```
**Pros:**
- Simple deployment
- Low ALGO lock (0.3 total)

**Cons:**
- Single point of failure
- Complex state management
- Difficult audit trail
- Security risk (all funds in one place)

### Option 2: Per-Trade Escrow (RECOMMENDED for P2P)
```
[P2P Trade #1 Escrow]
  ├── Opted into selling asset
  └── Opted into buying asset

[P2P Trade #2 Escrow]
  ├── Opted into selling asset
  └── Opted into buying asset
```
**Pros:**
- Clear separation of concerns
- Easy audit trail
- Isolated risk
- Can close and recover ALGO after trade

**Cons:**
- Higher ALGO requirement (0.2-0.3 per trade)
- More contracts to manage

### Option 3: Pool-Based Escrow (RECOMMENDED for Pay)
```
[Payment Router Contract]
  ├── Opted into cUSD
  ├── Opted into CONFIO
  └── Routes payments atomically (no holding)
```
**Pros:**
- No fund holding (atomic routing)
- Single opt-in set
- Efficient for high volume

**Cons:**
- Requires atomic transaction groups

### Option 4: User-Specific Escrow (RECOMMENDED for Send & Invite)
```
[Invite Escrow for User A]
  ├── Opted into assets
  └── Holds until claimed

[Invite Escrow for User B]
  ├── Opted into assets
  └── Holds until claimed
```
**Pros:**
- Clear ownership
- Can implement expiry/reclaim
- Isolated funds

**Cons:**
- ALGO lock per invite

## Recommended Architecture

### 1. Payment System (Pay)
Use **Atomic Transaction Groups** - no escrow needed:
```python
# Atomic group:
# 1. User sends to merchant (99.1%)
# 2. User sends to vault (0.9%)
```
No opt-in required for contract since it doesn't hold funds.

### 2. P2P Trading
Use **Per-Trade Escrow Contracts**:
```python
class P2PEscrow:
    def create_trade():
        # Deploy new escrow
        # Opt-in to both assets
        # Store trade details in box storage
    
    def complete_trade():
        # Transfer assets
        # Close escrow
        # Recover ALGO (0.2-0.3)
    
    def cancel_trade():
        # Return assets
        # Close escrow
        # Recover ALGO
```

### 3. Send & Invite
Use **Pooled Invite Contract** with expiry:
```python
class InvitePool:
    def __init__():
        # Opt-in to cUSD and CONFIO once
        # Total lock: 0.2 ALGO
    
    def send_invite():
        # Store in box: recipient -> amount
        # Set expiry (30 days)
    
    def claim():
        # Verify recipient
        # Transfer from pool
        # Delete box entry
    
    def reclaim_expired():
        # Check expiry
        # Return to sender
        # Delete box entry
```

## Cost Analysis

### Per-Trade Escrow (P2P)
- **Creation**: 0.1 (contract) + 0.1 * num_assets ALGO
- **Typical**: 0.3 ALGO per trade
- **Recovery**: Full amount on trade completion

### Payment Router
- **One-time**: 0.3 ALGO (permanent)
- **Per-payment**: Only transaction fees

### Invite Pool
- **One-time**: 0.3 ALGO (permanent)
- **Per-invite**: Box storage cost (~0.002 ALGO)

## Implementation Priority

1. **Phase 1**: Payment Router (atomic, no escrow)
2. **Phase 2**: P2P Per-Trade Escrow
3. **Phase 3**: Invite Pool Contract

## Security Considerations

### Per-Trade Escrow Benefits
1. **Isolation**: Each trade is isolated
2. **Auditability**: Clear on-chain history
3. **Recovery**: Can always close and recover ALGO
4. **Upgradability**: New trades use latest contract

### Opt-in Management
```python
def manage_opt_ins(asset_ids: List[int]):
    """Dynamically manage asset opt-ins"""
    current_assets = get_opted_assets()
    
    # Opt-in to new assets
    for asset in asset_ids:
        if asset not in current_assets:
            opt_in(asset)
    
    # Opt-out from unused assets (recover ALGO)
    for asset in current_assets:
        if asset not in asset_ids and balance(asset) == 0:
            opt_out(asset)
```

## Recommended Implementation

### P2P Escrow Factory Pattern
```python
class P2PEscrowFactory:
    """Factory to deploy per-trade escrows"""
    
    def create_escrow(
        seller_asset: int,
        buyer_asset: int,
        seller_amount: int,
        buyer_amount: int
    ) -> str:
        """Deploy new escrow for specific trade"""
        # Deploy contract
        # Opt-in to both assets
        # Return escrow address
        
    def get_trade_escrow(trade_id: str) -> str:
        """Get escrow address for trade"""
        # Look up in box storage
        
    def close_escrow(escrow_address: str):
        """Close completed trade escrow"""
        # Verify trade complete
        # Close out contract
        # Recover ALGO
```

## Conclusion

**Recommendations:**
1. **Pay**: Use atomic transactions, no escrow needed
2. **P2P**: Use per-trade escrows with automatic cleanup
3. **Invite**: Use single pool with box storage

**Benefits:**
- Clear separation of concerns
- Automatic ALGO recovery
- Better security isolation
- Easier debugging and auditing

**Trade-offs:**
- Slightly higher ALGO requirements during active trades
- More complex contract management
- But: Better security and recoverability