#!/usr/bin/env python3
"""
REFERENCE IMPLEMENTATION - Use p2p_trade.py (Beaker) as canonical version

This is a reference PyTeal implementation showing sponsor pattern and MBR handling.
The canonical P2P vault is p2p_trade.py which includes:
- accept_trade / mark_as_paid flow
- Proper 137-byte box layout matching documentation
- Complete dispute resolution

This file is kept for reference on pure PyTeal patterns.
"""

from pyteal import *
from algosdk import encoding

# Trade states
TRADE_CREATED = Int(1)
TRADE_FUNDED = Int(2)
TRADE_COMPLETED = Int(3)
TRADE_CANCELLED = Int(4)
TRADE_DISPUTED = Int(5)

# MBR constants (in microAlgos)
TRADE_BOX_MBR = Int(70100)  # 32 key + 137 value = 2500 + 400*(32+137) = 70,100
INVITE_BOX_MBR = Int(40900)  # 32 key + 64 value
ASA_OPT_IN_MBR = Int(100000)  # Per ASA opt-in

def p2p_vault_production():
    """
    Production P2P vault with proper MBR handling and sponsor support.
    """
    
    # Global state schema: 11 ints, 3 bytes
    cusd_asset_id = Bytes("cusd_id")
    confio_asset_id = Bytes("confio_id")  # Support both assets
    sponsor_address = Bytes("sponsor")  # Sponsor who funds MBR
    arbitrator_address = Bytes("arbitrator")
    total_trades = Bytes("trades")
    active_trades = Bytes("active")
    disputed_trades = Bytes("disputed")
    total_volume = Bytes("volume")
    vault_opted_in = Bytes("opted")
    # fee_basis_points removed - P2P has zero fees
    gc_reward_bp = Bytes("gc_reward")
    
    # Box storage layout (total: 137 bytes to match Beaker contract)
    # We store sponsor info globally, not per-trade, to save space
    BOX_SIZE = Int(137)
    
    # Box field offsets
    SELLER_OFFSET = Int(0)
    BUYER_OFFSET = Int(32)
    ASSET_ID_OFFSET = Int(64)  # Stores which asset (cUSD or CONFIO)
    AMOUNT_OFFSET = Int(72)
    STATE_OFFSET = Int(80)
    CREATED_OFFSET = Int(88)
    EXPIRY_OFFSET = Int(96)
    SELLER_FUNDED_OFFSET = Int(104)
    BUYER_FUNDED_OFFSET = Int(112)
    DISPUTE_REASON_OFFSET = Int(120)
    # FEE_PAID_OFFSET removed - P2P has zero fees
    
    # Initialize vault
    @Subroutine(TealType.uint64)
    def initialize():
        return Seq([
            # cUSD, CONFIO asset IDs and sponsor passed as arguments
            Assert(Txn.application_args.length() == Int(4)),
            App.globalPut(cusd_asset_id, Btoi(Txn.application_args[0])),
            App.globalPut(confio_asset_id, Btoi(Txn.application_args[1])),
            App.globalPut(sponsor_address, Txn.application_args[2]),
            App.globalPut(arbitrator_address, Txn.application_args[3]),
            
            # Initialize counters
            App.globalPut(total_trades, Int(0)),
            App.globalPut(active_trades, Int(0)),
            App.globalPut(disputed_trades, Int(0)),
            App.globalPut(total_volume, Int(0)),
            App.globalPut(vault_opted_in, Int(0)),
            # P2P trades have zero fees - no fee_basis_points needed
            App.globalPut(gc_reward_bp, Int(100)),  # 1% of MBR as GC reward
            
            Int(1)
        ])
    
    # Opt vault into both cUSD and CONFIO (one-time, sponsor-funded)
    @Subroutine(TealType.uint64)
    def opt_in_asset():
        return Seq([
            # Only creator can trigger opt-in
            Assert(Txn.sender() == Global.creator_address()),
            
            # Must not be already opted in
            Assert(App.globalGet(vault_opted_in) == Int(0)),
            
            # Group structure for dual asset opt-in:
            # G0: Payment from sponsor to app (2 * ASA_OPT_IN_MBR)
            # G1: This app call
            # G2: Asset opt-in for cUSD (0 amount to self)
            # G3: Asset opt-in for CONFIO (0 amount to self)
            Assert(Global.group_size() == Int(4)),
            
            # Verify sponsor payment (covers both opt-ins)
            Assert(Gtxn[0].type_enum() == TxnType.Payment),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].receiver() == Global.current_application_address()),
            Assert(Gtxn[0].amount() >= ASA_OPT_IN_MBR * Int(2)),  # 0.2 ALGO for both
            
            # Verify cUSD opt-in transaction
            Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[2].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[2].asset_amount() == Int(0)),
            Assert(Gtxn[2].xfer_asset() == App.globalGet(cusd_asset_id)),
            
            # Verify CONFIO opt-in transaction
            Assert(Gtxn[3].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[3].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[3].asset_amount() == Int(0)),
            Assert(Gtxn[3].xfer_asset() == App.globalGet(confio_asset_id)),
            
            # Mark as opted in
            App.globalPut(vault_opted_in, Int(1)),
            
            Int(1)
        ])
    
    # Create new trade (sponsor-funded)
    @Subroutine(TealType.uint64)
    def create_trade():
        trade_id = Txn.application_args[1]  # 32-byte trade ID
        
        return Seq([
            # Vault must be opted in
            Assert(App.globalGet(vault_opted_in) == Int(1)),
            
            # Group structure:
            # G0: Payment from sponsor to app (box MBR + headroom)
            # G1: This app call with trade details
            Assert(Global.group_size() == Int(2)),
            
            # Verify sponsor payment for box MBR
            Assert(Gtxn[0].type_enum() == TxnType.Payment),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].receiver() == Global.current_application_address()),
            Assert(Gtxn[0].amount() >= TRADE_BOX_MBR + Int(10000)),  # +10k headroom for fees
            
            # Trade must not already exist
            Assert(Not(App.box_get(trade_id)[0])),
            
            # Create box (now we have ALGO from sponsor to cover MBR)
            Assert(App.box_create(trade_id, BOX_SIZE)),
            
            # Parse arguments
            Assert(Txn.application_args.length() == Int(6)),
            (seller := Txn.application_args[2]),
            (buyer := Txn.application_args[3]),
            (asset_id := Btoi(Txn.application_args[4])),
            (amount := Btoi(Txn.application_args[5])),
            
            # Verify asset is either cUSD or CONFIO
            Assert(Or(
                asset_id == App.globalGet(cusd_asset_id),
                asset_id == App.globalGet(confio_asset_id)
            )),
            
            # Store trade data in box
            App.box_replace(trade_id, SELLER_OFFSET, seller),
            App.box_replace(trade_id, BUYER_OFFSET, buyer),
            App.box_replace(trade_id, ASSET_ID_OFFSET, Itob(asset_id)),
            App.box_replace(trade_id, AMOUNT_OFFSET, Itob(amount)),
            App.box_replace(trade_id, STATE_OFFSET, Itob(TRADE_CREATED)),
            App.box_replace(trade_id, CREATED_OFFSET, Itob(Global.latest_timestamp())),
            App.box_replace(trade_id, EXPIRY_OFFSET, Itob(Global.latest_timestamp() + Int(900))),  # 15 min
            App.box_replace(trade_id, SELLER_FUNDED_OFFSET, Itob(Int(0))),
            App.box_replace(trade_id, BUYER_FUNDED_OFFSET, Itob(Int(0))),
            # No fee tracking needed - P2P has zero fees
            
            # Update counters
            App.globalPut(total_trades, App.globalGet(total_trades) + Int(1)),
            App.globalPut(active_trades, App.globalGet(active_trades) + Int(1)),
            
            Int(1)
        ])
    
    # Deposit funds (seller deposits cUSD)
    @Subroutine(TealType.uint64)
    def deposit_funds():
        trade_id = Txn.application_args[1]
        
        return Seq([
            # Trade must exist
            (box_data := App.box_get(trade_id)),
            Assert(box_data[0]),
            (trade_data := box_data[1]),
            
            # Parse trade data
            (seller := Extract(trade_data, SELLER_OFFSET, Int(32))),
            (asset_id := Btoi(Extract(trade_data, ASSET_ID_OFFSET, Int(8)))),
            (amount := Btoi(Extract(trade_data, AMOUNT_OFFSET, Int(8)))),
            (state := Btoi(Extract(trade_data, STATE_OFFSET, Int(8)))),
            (seller_funded := Btoi(Extract(trade_data, SELLER_FUNDED_OFFSET, Int(8)))),
            
            # Must be in created state
            Assert(state == TRADE_CREATED),
            
            # Only seller can deposit
            Assert(Txn.sender() == seller),
            Assert(seller_funded == Int(0)),  # Can't deposit twice
            
            # Group structure:
            # G0: AXFER from seller to app
            # G1: This app call
            Assert(Global.group_size() == Int(2)),
            
            # Verify asset transfer (must match stored asset)
            Assert(Gtxn[0].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[0].sender() == seller),
            Assert(Gtxn[0].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[0].xfer_asset() == asset_id),  # Must match trade asset
            Assert(Gtxn[0].asset_amount() == amount),
            
            # Mark as funded
            App.box_replace(trade_id, SELLER_FUNDED_OFFSET, Itob(Int(1))),
            App.box_replace(trade_id, STATE_OFFSET, Itob(TRADE_FUNDED)),
            
            Int(1)
        ])
    
    # Complete trade (buyer confirms, sponsor covers fees)
    @Subroutine(TealType.uint64)
    def complete_trade():
        trade_id = Txn.application_args[1]
        
        return Seq([
            # Trade must exist
            (box_data := App.box_get(trade_id)),
            Assert(box_data[0]),
            (trade_data := box_data[1]),
            
            # Parse trade data
            (seller := Extract(trade_data, SELLER_OFFSET, Int(32))),
            (buyer := Extract(trade_data, BUYER_OFFSET, Int(32))),
            (asset_id := Btoi(Extract(trade_data, ASSET_ID_OFFSET, Int(8)))),
            (amount := Btoi(Extract(trade_data, AMOUNT_OFFSET, Int(8)))),
            (state := Btoi(Extract(trade_data, STATE_OFFSET, Int(8)))),
            
            # Must be funded and not disputed
            Assert(state == TRADE_FUNDED),
            
            # Only buyer can complete
            Assert(Txn.sender() == buyer),
            
            # Check buyer is opted into the trade asset
            (buyer_balance := AssetHolding.balance(buyer, asset_id)),
            Assert(buyer_balance.hasValue()),  # Buyer must be opted in
            
            # Group structure:
            # G0: Payment from sponsor (fee bump, can be 0 amount)
            # G1: This app call
            Assert(Global.group_size() == Int(2)),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            
            # Transfer full amount to buyer (no fees for P2P)
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: asset_id,  # Use the asset from the trade
                TxnField.asset_receiver: buyer,
                TxnField.asset_amount: amount,  # Full amount, no fees
                TxnField.fee: Int(0)  # Fee covered by group
            }),
            InnerTxnBuilder.Submit(),
            
            # Delete box FIRST to free MBR
            Assert(App.box_delete(trade_id)),
            
            # Refund MBR to sponsor
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: App.globalGet(sponsor_address),
                TxnField.amount: TRADE_BOX_MBR,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Update counters
            App.globalPut(active_trades, App.globalGet(active_trades) - Int(1)),
            App.globalPut(total_volume, App.globalGet(total_volume) + amount),
            
            Int(1)
        ])
    
    # Cancel trade (return funds, refund MBR)
    @Subroutine(TealType.uint64)
    def cancel_trade():
        trade_id = Txn.application_args[1]
        
        return Seq([
            # Trade must exist
            (box_data := App.box_get(trade_id)),
            Assert(box_data[0]),
            (trade_data := box_data[1]),
            
            # Parse trade data
            (seller := Extract(trade_data, SELLER_OFFSET, Int(32))),
            (buyer := Extract(trade_data, BUYER_OFFSET, Int(32))),
            (asset_id := Btoi(Extract(trade_data, ASSET_ID_OFFSET, Int(8)))),
            (amount := Btoi(Extract(trade_data, AMOUNT_OFFSET, Int(8)))),
            (state := Btoi(Extract(trade_data, STATE_OFFSET, Int(8)))),
            (expiry := Btoi(Extract(trade_data, EXPIRY_OFFSET, Int(8)))),
            (seller_funded := Btoi(Extract(trade_data, SELLER_FUNDED_OFFSET, Int(8)))),
            
            # Can't cancel completed trades
            Assert(state != TRADE_COMPLETED),
            
            # Either party can cancel, or anyone after expiry
            Assert(Or(
                Txn.sender() == seller,
                Txn.sender() == buyer,
                Global.latest_timestamp() > expiry
            )),
            
            # Return seller's funds if deposited
            If(seller_funded == Int(1),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: asset_id,  # Use the trade's asset
                        TxnField.asset_receiver: seller,
                        TxnField.asset_amount: amount,
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Delete box FIRST to free MBR
            Assert(App.box_delete(trade_id)),
            
            # Refund MBR to sponsor
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: App.globalGet(sponsor_address),
                TxnField.amount: TRADE_BOX_MBR,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Update counters
            App.globalPut(active_trades, App.globalGet(active_trades) - Int(1)),
            If(state == TRADE_DISPUTED,
                App.globalPut(disputed_trades, App.globalGet(disputed_trades) - Int(1))
            ),
            
            Int(1)
        ])
    
    # Garbage collect expired trade (with proper order)
    @Subroutine(TealType.uint64)
    def gc_single():
        trade_id = Txn.application_args[1]
        
        return Seq([
            # Trade must exist
            (box_data := App.box_get(trade_id)),
            Assert(box_data[0]),
            (trade_data := box_data[1]),
            
            # Parse trade data
            (seller := Extract(trade_data, SELLER_OFFSET, Int(32))),
            (asset_id := Btoi(Extract(trade_data, ASSET_ID_OFFSET, Int(8)))),
            (amount := Btoi(Extract(trade_data, AMOUNT_OFFSET, Int(8)))),
            (state := Btoi(Extract(trade_data, STATE_OFFSET, Int(8)))),
            (expiry := Btoi(Extract(trade_data, EXPIRY_OFFSET, Int(8)))),
            (seller_funded := Btoi(Extract(trade_data, SELLER_FUNDED_OFFSET, Int(8)))),
            
            # Must be expired
            Assert(Global.latest_timestamp() > expiry),
            
            # Can't GC completed trades
            Assert(state != TRADE_COMPLETED),
            
            # Group structure:
            # G0: Payment from sponsor (fee bump)
            # G1: This app call
            Assert(Global.group_size() == Int(2)),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            
            # Return funds if any
            If(seller_funded == Int(1),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: asset_id,  # Use the trade's asset
                        TxnField.asset_receiver: seller,
                        TxnField.asset_amount: amount,
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Delete box FIRST to free MBR (CRITICAL ORDER!)
            Assert(App.box_delete(trade_id)),
            
            # Calculate GC reward
            (gc_reward := TRADE_BOX_MBR * App.globalGet(gc_reward_bp) / Int(10000)),
            (sponsor_refund := TRADE_BOX_MBR - gc_reward),
            
            # Pay GC reward to caller (now we have freed ALGO)
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: Txn.sender(),
                TxnField.amount: gc_reward,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Refund remainder to sponsor
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: App.globalGet(sponsor_address),
                TxnField.amount: sponsor_refund,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Update counters
            App.globalPut(active_trades, App.globalGet(active_trades) - Int(1)),
            
            Int(1)
        ])
    
    # Main router
    program = Cond(
        # Creation
        [Txn.application_id() == Int(0), initialize()],
        
        # NoOp calls
        [Txn.on_completion() == OnComplete.NoOp,
         Cond(
             [Txn.application_args[0] == Bytes("opt_in"), opt_in_asset()],
             [Txn.application_args[0] == Bytes("create"), create_trade()],
             [Txn.application_args[0] == Bytes("deposit"), deposit_funds()],
             [Txn.application_args[0] == Bytes("complete"), complete_trade()],
             [Txn.application_args[0] == Bytes("cancel"), cancel_trade()],
             [Txn.application_args[0] == Bytes("gc"), gc_single()],
         )],
        
        # Reject everything else
        [Int(1), Int(0)]
    )
    
    return program

def compile_p2p_vault_production():
    """Compile the production P2P vault"""
    program = p2p_vault_production()
    return compileTeal(program, Mode.Application, version=8)

if __name__ == "__main__":
    print(compile_p2p_vault_production())
    print("\n# Production P2P Vault with Sponsor Support")
    print("# Key improvements:")
    print("# 1. Sponsor funds all MBR increases")
    print("# 2. Explicit MBR refunds after box_delete")
    print("# 3. Correct order: delete box → then pay rewards")
    print("# 4. Recipient opt-in checks before transfers")
    print("# 5. Dual-asset support (cUSD and CONFIO)")
    print("# 6. All terminal paths delete boxes and refund MBR")
    print("\n# Group transaction structures:")
    print("# Create: [Payment(sponsor→app), AppCall(create)]")
    print("# Deposit: [AXFER(seller→app), AppCall(deposit)]")
    print("# Complete: [Payment(sponsor fee-bump), AppCall(complete)]")
    print("# GC: [Payment(sponsor fee-bump), AppCall(gc)]")