# Sponsor Pattern Guide for Algorand Smart Contracts

## Overview

The sponsor pattern solves a critical UX problem in Algorand: users shouldn't need to hold ALGO to use applications. A sponsor (the platform) funds all Minimum Balance Requirements (MBR) and transaction fees, creating a seamless experience for users who only hold stablecoins.

## Critical Production Fixes (from ChatGPT's Review)

### 1. ❌ Common Misconception: Box Delete Returns MBR
```python
# WRONG - Box delete does NOT automatically return MBR!
Assert(App.box_delete(trade_id))
# MBR is now freed but sitting in the app account
```

### 2. ✅ Correct: Explicit MBR Refund Required
```python
# RIGHT - Delete box, then explicitly refund
Assert(App.box_delete(trade_id))

# Refund MBR to sponsor
InnerTxnBuilder.Begin()
InnerTxnBuilder.SetFields({
    TxnField.type_enum: TxnType.Payment,
    TxnField.receiver: App.globalGet(sponsor_address),
    TxnField.amount: TRADE_BOX_MBR,
    TxnField.fee: Int(0)
})
InnerTxnBuilder.Submit()
```

## Sponsor Pattern Implementation

### Global State Setup
```python
# Store sponsor address in global state
sponsor_address = Bytes("sponsor")

def initialize():
    return Seq([
        App.globalPut(sponsor_address, Txn.application_args[1]),
        # ... other initialization
    ])
```

### Box Creation with Sponsor Funding

#### Group Transaction Structure
```
G0: Payment(sponsor → app, MBR amount)
G1: AppCall(create operation)
```

#### Smart Contract Code
```python
@Subroutine(TealType.uint64)
def create_trade():
    trade_id = Txn.application_args[1]
    
    return Seq([
        # Verify group structure
        Assert(Global.group_size() == Int(2)),
        
        # Verify sponsor payment
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        Assert(Gtxn[0].amount() >= TRADE_BOX_MBR + Int(10000)),  # +headroom
        
        # Now safe to create box
        Assert(App.box_create(trade_id, BOX_SIZE)),
        
        # ... rest of logic
    ])
```

### MBR Refund on Completion

#### Critical: Order of Operations
```python
@Subroutine(TealType.uint64)
def complete_trade():
    return Seq([
        # ... validate and process trade ...
        
        # 1. FIRST: Delete box to free MBR
        Assert(App.box_delete(trade_id)),
        
        # 2. THEN: Refund MBR to sponsor
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: App.globalGet(sponsor_address),
            TxnField.amount: TRADE_BOX_MBR,
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # 3. Update counters AFTER refund
        App.globalPut(active_trades, App.globalGet(active_trades) - Int(1))
    ])
```

### Expired Trade Cleanup

```python
@Subroutine(TealType.uint64)
def cancel_expired():
    return Seq([
        # ... validate expiry + grace period ...
        
        # Delete box FIRST
        Assert(App.box_delete(trade_id)),
        
        # Refund full MBR to sponsor (no reward)
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: App.globalGet(sponsor_address),
            TxnField.amount: TRADE_BOX_MBR,
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit()
    ])
```

## MBR Calculations

### Box Storage MBR
```python
def calculate_box_mbr(key_bytes: int, value_bytes: int) -> int:
    """Calculate MBR in microAlgos"""
    return 2500 + 400 * (key_bytes + value_bytes)
```

### Common Box Sizes
| Use Case | Key | Value | Total Bytes | MBR (ALGO) |
|----------|-----|-------|-------------|------------|
| Trade | 32* | 137 | 169 | 0.0701 |
| Invite | 32* | 64 | 96 | 0.0409 |
| Large Trade | 32* | 200 | 232 | 0.0953 |

*Note: Trade IDs must be ≤ 56 bytes to allow for suffixes like "_paid" (5 bytes) and "_dispute" (8 bytes) within Algorand's 64-byte box key limit.

### Asset Opt-in MBR
- Per asset opt-in: 0.1 ALGO (permanent until opt-out)
- App account opt-in: Same 0.1 ALGO per asset

## Client Integration

### JavaScript/TypeScript Example
```javascript
async function createTrade(tradeData) {
    const appId = CONFIG.P2P_VAULT_APP_ID;
    const sponsorAddr = CONFIG.SPONSOR_ADDRESS;
    const appAddr = getApplicationAddress(appId);
    
    // Calculate MBR needed
    const TRADE_BOX_MBR = 70100; // microAlgos for 32 + 137 bytes
    const HEADROOM = 2000; // Enough for a few inner txns
    
    // Build transactions
    const params = await algodClient.getTransactionParams().do();
    
    // 1. Sponsor payment
    const payTxn = makePaymentTxnWithSuggestedParams(
        sponsorAddr,
        appAddr,
        TRADE_BOX_MBR + HEADROOM,
        undefined,
        undefined,
        params
    );
    
    // 2. App call
    const appArgs = [
        new Uint8Array(Buffer.from("create")),
        tradeId,
        sellerAddr,
        buyerAddr,
        encodeUint64(amount)
    ];
    
    const appTxn = makeApplicationCallTxnFromObject({
        from: userAddr,
        appIndex: appId,
        appArgs,
        boxes: [{appIndex: appId, name: tradeId}],
        suggestedParams: params
    });
    
    // Group transactions
    const group = [payTxn, appTxn];
    assignGroupID(group);
    
    // Sign (sponsor signs offline/via API)
    const signedPay = await sponsorSign(group[0]);
    const signedApp = await userWallet.signTransaction(group[1]);
    
    // Submit
    await algodClient.sendRawTransaction([
        signedPay,
        signedApp
    ]).do();
}
```

## Design Principles

### 1. User Never Pays ALGO
- All MBR funded by sponsor
- All fees covered by sponsor or fee-bumps
- Users only need stablecoin balance

### 2. 100% MBR Recovery
- Every box creation has matching deletion
- All terminal paths refund MBR
- GC incentives ensure cleanup

### 3. Capital Efficiency
- Use boxes (temporary) vs account storage (permanent)
- Single asset (cUSD) to save opt-in MBR
- Pooled vaults over per-trade contracts

### 4. Safety Checks
- Recipient opt-in verification before transfers
- Sponsor payment validation before box creation
- Explicit refunds after box deletion

## Common Pitfalls

### ❌ DON'T: Assume MBR Auto-Returns
```python
# WRONG
App.box_delete(trade_id)
# MBR is freed but not returned!
```

### ❌ DON'T: Pay Before Deleting
```python
# WRONG - Will fail, not enough balance!
InnerTxnBuilder.SetField(TxnField.amount: gc_reward)
InnerTxnBuilder.Submit()
App.box_delete(trade_id)  # Too late!
```

### ❌ DON'T: Skip Opt-in Checks
```python
# WRONG - Transfer will fail if not opted in
InnerTxnBuilder.SetFields({
    TxnField.asset_receiver: recipient,
    TxnField.asset_amount: amount
})
```

### ✅ DO: Follow the Pattern
```python
# RIGHT
# 1. Check recipient opted in
Assert(AssetHolding.balance(recipient, asset_id).hasValue())

# 2. Delete box first
Assert(App.box_delete(trade_id))

# 3. Then pay refunds
InnerTxnBuilder.Begin()
InnerTxnBuilder.SetFields({
    TxnField.type_enum: TxnType.Payment,
    TxnField.receiver: sponsor,
    TxnField.amount: MBR_AMOUNT
})
InnerTxnBuilder.Submit()
```

## Testing Checklist

- [ ] Sponsor payment required for all box creation
- [ ] MBR explicitly refunded on all deletions
- [ ] Box deleted BEFORE payments in GC
- [ ] Recipient opt-in checked before transfers
- [ ] All terminal paths delete boxes
- [ ] GC incentives working correctly
- [ ] No ALGO required from end users
- [ ] Capital efficiency metrics tracked

## Production Deployment

1. **Fund Sponsor Account**
   ```bash
   # Calculate needs: boxes * MBR + buffer
   # 5000 trades * 0.07 ALGO = 350 ALGO
   # Add 20% buffer = 420 ALGO
   ```

2. **Monitor MBR Usage**
   ```python
   def get_mbr_stats(app_id):
       app_info = algod_client.application_info(app_id)
       boxes = algod_client.application_boxes(app_id)
       
       total_mbr = 0
       for box in boxes['boxes']:
           key_len = len(box['name'])
           # Get box info for value length
           box_data = algod_client.application_box_by_name(
               app_id, box['name']
           )
           value_len = len(box_data['value'])
           mbr = calculate_box_mbr(key_len, value_len)
           total_mbr += mbr
           
       return {
           'box_count': len(boxes['boxes']),
           'total_mbr_algo': total_mbr / 1_000_000,
           'recoverable': total_mbr  # All box MBR is recoverable
       }
   ```

3. **Automated GC Bot**
   ```python
   async def run_gc_bot():
       while True:
           expired = find_expired_boxes()
           for box in expired:
               try:
                   await garbage_collect(box)
                   # Collect 1% reward
               except:
                   continue
           await asyncio.sleep(300)  # Check every 5 min
   ```

## Conclusion

The sponsor pattern enables Web2-like UX on Algorand by abstracting away ALGO requirements. Combined with proper MBR management, it creates a sustainable, capital-efficient system where users only need stablecoins to interact with the platform.

Remember: **Always delete boxes first, then pay refunds!**