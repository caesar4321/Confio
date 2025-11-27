#!/usr/bin/env python3
"""
Production-Ready Inbox Router with Sponsor Support
Implements ARC-59 pattern with proper MBR handling.
"""

from pyteal import *
from algosdk import encoding
import hashlib

# MBR helpers (in microAlgos)
ASA_OPT_IN_MBR = Int(100000)  # Per ASA opt-in

@Subroutine(TealType.uint64)
def box_mbr_cost(key_len: Expr, value_len: Expr) -> Expr:
    # Algorand MBR for boxes: 2500 + 400*(key_len + value_len)
    return Int(2500) + Int(400) * (key_len + value_len)

def inbox_router_production():
    """
    Production inbox router with proper MBR handling.
    cUSD-only to save permanent MBR.
    """
    
    # Global state schema: 7 ints, 2 bytes
    cusd_asset_id = Bytes("cusd_id")
    sponsor_address = Bytes("sponsor")
    total_pending = Bytes("pending")
    pending_count = Bytes("count")
    total_claimed = Bytes("claimed")
    router_opted_in = Bytes("opted")
    expiry_days = Bytes("expiry")
    gc_reward_bp = Bytes("gc_reward")
    
    # Box storage layout (total: 88 bytes)
    # Key: claim_code (32 bytes secret)
    # Value structure:
    #   sender_address: 32 bytes
    #   cusd_amount: 8 bytes
    #   expiry_time: 8 bytes
    #   recipient_address: 32 bytes (intended recipient; zero-address if unknown)
    #   metadata_hash: 8 bytes
    BOX_SIZE = Int(88)
    
    # Box field offsets
    SENDER_OFFSET = Int(0)
    AMOUNT_OFFSET = Int(32)
    EXPIRY_OFFSET = Int(40)
    RECIPIENT_OFFSET = Int(48)
    METADATA_OFFSET = Int(80)
    
    # Initialize router
    @Subroutine(TealType.uint64)
    def initialize():
        return Seq([
            # cUSD asset ID and sponsor passed as arguments
            Assert(Txn.sender() == Global.creator_address()),
            Assert(Txn.application_args.length() == Int(2)),
            App.globalPut(cusd_asset_id, Btoi(Txn.application_args[0])),
            App.globalPut(sponsor_address, Txn.application_args[1]),
            
            # Set defaults
            App.globalPut(expiry_days, Int(7)),  # 7 day default
            App.globalPut(total_pending, Int(0)),
            App.globalPut(pending_count, Int(0)),
            App.globalPut(total_claimed, Int(0)),
            App.globalPut(router_opted_in, Int(0)),
            App.globalPut(gc_reward_bp, Int(50)),  # 0.5% of MBR as GC reward
            
            Int(1)
        ])
    
    # Opt router into cUSD (one-time, sponsor-funded)
    @Subroutine(TealType.uint64)
    def opt_in_asset():
        return Seq([
            # Only creator can trigger opt-in
            Assert(Txn.sender() == Global.creator_address()),
            
            # Must not be already opted in
            Assert(App.globalGet(router_opted_in) == Int(0)),
            
            # Group structure:
            # G0: Payment from sponsor to app (ASA_OPT_IN_MBR)
            # G1: This app call
            # G2: Asset opt-in (0 amount to self)
            Assert(Global.group_size() == Int(3)),
            
            # Verify sponsor payment
            Assert(Gtxn[0].type_enum() == TxnType.Payment),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].receiver() == Global.current_application_address()),
            Assert(Gtxn[0].amount() >= ASA_OPT_IN_MBR),
            
            # Verify opt-in transaction
            Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[2].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[2].asset_amount() == Int(0)),
            Assert(Gtxn[2].xfer_asset() == App.globalGet(cusd_asset_id)),
            
            # Mark as opted in
            App.globalPut(router_opted_in, Int(1)),
            
            Int(1)
        ])
    
    # Send invite (sponsor-funded)
    @Subroutine(TealType.uint64)
    def send_invite():
        claim_code = Txn.application_args[1]  # 32-byte secret
        metadata_hash = Txn.application_args[2]  # 8-byte hash
        intended_recipient = Txn.accounts[1] if Txn.accounts.length() > Int(1) else Global.zero_address()
        key_len = Len(claim_code)
        invite_box_mbr = box_mbr_cost(key_len, BOX_SIZE)
        
        return Seq([
            # Router must be opted in
            Assert(App.globalGet(router_opted_in) == Int(1)),
            
            # Group structure:
            # G0: Payment from sponsor to app (box MBR + headroom)
            # G1: AXFER from sender to app (cUSD)
            # G2: This app call
            Assert(Global.group_size() == Int(3)),
            
            # Verify sponsor payment for box MBR
            Assert(Gtxn[0].type_enum() == TxnType.Payment),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].receiver() == Global.current_application_address()),
            Assert(Gtxn[0].amount() >= invite_box_mbr + Int(10000)),  # +10k headroom
            
            # Verify cUSD transfer
            Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[1].xfer_asset() == App.globalGet(cusd_asset_id)),
            (amount := Gtxn[1].asset_amount()),
            Assert(amount > Int(0)),
            
            # Check invite doesn't already exist
            Assert(Not(App.box_get(claim_code)[0])),
            
            # Create box (now we have ALGO from sponsor to cover MBR)
            Assert(App.box_create(claim_code, BOX_SIZE)),
            
            # Store invite data
            App.box_replace(claim_code, SENDER_OFFSET, Gtxn[1].sender()),  # Original sender
            App.box_replace(claim_code, AMOUNT_OFFSET, Itob(amount)),
            App.box_replace(claim_code, EXPIRY_OFFSET,
                Itob(Global.latest_timestamp() + App.globalGet(expiry_days) * Int(86400))
            ),
            App.box_replace(claim_code, RECIPIENT_OFFSET, intended_recipient),
            App.box_replace(claim_code, METADATA_OFFSET, metadata_hash),
            
            # Update statistics
            App.globalPut(total_pending, App.globalGet(total_pending) + amount),
            App.globalPut(pending_count, App.globalGet(pending_count) + Int(1)),
            
            Int(1)
        ])
    
    # Claim invite (recipient claims)
    @Subroutine(TealType.uint64)
    def claim_invite():
        claim_code = Txn.application_args[1]
        key_len = Len(claim_code)
        invite_box_mbr = box_mbr_cost(key_len, BOX_SIZE)
        
        return Seq([
            # Prevent rekey/close hijack on the app call itself
            Assert(Txn.rekey_to() == Global.zero_address()),
            Assert(Txn.close_remainder_to() == Global.zero_address()),
            Assert(Txn.asset_close_to() == Global.zero_address()),

            # Box must exist
            (box_data := App.box_get(claim_code)),
            Assert(box_data[0]),
            
            # Parse box data
            (stored_data := box_data[1]),
            (sender := Extract(stored_data, SENDER_OFFSET, Int(32))),
            (amount := Btoi(Extract(stored_data, AMOUNT_OFFSET, Int(8)))),
            (expiry := Btoi(Extract(stored_data, EXPIRY_OFFSET, Int(8)))),
            (intended_recipient := Extract(stored_data, RECIPIENT_OFFSET, Int(32))),
            
            # Check not expired
            Assert(Global.latest_timestamp() <= expiry),

            # If an intended recipient was provided, enforce it
            Assert(Or(
                intended_recipient == Global.zero_address(),
                Txn.sender() == intended_recipient
            )),
            
            # Check recipient is opted into cUSD
            (recipient_balance := AssetHolding.balance(Txn.sender(), App.globalGet(cusd_asset_id))),
            Assert(recipient_balance.hasValue()),  # Must be opted in
            
            # Group structure:
            # G0: Payment from sponsor (fee bump)
            # G1: This app call
            Assert(Global.group_size() == Int(2)),
            (fee_payer := Gtxn[0].sender()),
            Assert(fee_payer == App.globalGet(sponsor_address)),
            
            # Transfer cUSD to recipient
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(cusd_asset_id),
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: amount,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Delete box FIRST to free MBR
            Assert(App.box_delete(claim_code)),
            
            # Refund MBR to sponsor
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: App.globalGet(sponsor_address),
                TxnField.amount: invite_box_mbr,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Update statistics
            App.globalPut(total_pending, App.globalGet(total_pending) - amount),
            App.globalPut(pending_count, App.globalGet(pending_count) - Int(1)),
            App.globalPut(total_claimed, App.globalGet(total_claimed) + amount),
            
            Int(1)
        ])
    
    # Reclaim expired invite
    @Subroutine(TealType.uint64)
    def reclaim_expired():
        claim_code = Txn.application_args[1]
        key_len = Len(claim_code)
        invite_box_mbr = box_mbr_cost(key_len, BOX_SIZE)
        
        return Seq([
            # Box must exist
            (box_data := App.box_get(claim_code)),
            Assert(box_data[0]),
            
            # Parse box data
            (stored_data := box_data[1]),
            (sender := Extract(stored_data, SENDER_OFFSET, Int(32))),
            (amount := Btoi(Extract(stored_data, AMOUNT_OFFSET, Int(8)))),
            (expiry := Btoi(Extract(stored_data, EXPIRY_OFFSET, Int(8)))),
            
            # Must be sender or expired
            Assert(Or(
                Txn.sender() == sender,
                Global.latest_timestamp() > expiry
            )),
            
            # Group structure:
            # G0: Payment from sponsor (fee bump)
            # G1: This app call
            Assert(Global.group_size() == Int(2)),
            (fee_payer := Gtxn[0].sender()),
            Assert(fee_payer == App.globalGet(sponsor_address)),
            
            # Return cUSD to original sender
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(cusd_asset_id),
                TxnField.asset_receiver: sender,
                TxnField.asset_amount: amount,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Delete box FIRST to free MBR
            Assert(App.box_delete(claim_code)),
            
            # Calculate GC reward if called by someone else
            If(Txn.sender() != sender,
                Seq([
                    (gc_reward := invite_box_mbr * App.globalGet(gc_reward_bp) / Int(10000)),
                    (sponsor_refund := invite_box_mbr - gc_reward),
                    
                    # Pay GC reward to caller
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
                    InnerTxnBuilder.Submit()
                ]),
                # If sender reclaims, full refund to sponsor
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.Payment,
                        TxnField.receiver: App.globalGet(sponsor_address),
                        TxnField.amount: invite_box_mbr,
                        TxnField.fee: Int(0)
                    }),
                InnerTxnBuilder.Submit()
            ])
            ),
            
            # Update statistics
            App.globalPut(total_pending, App.globalGet(total_pending) - amount),
            App.globalPut(pending_count, App.globalGet(pending_count) - Int(1)),
            
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
             [Txn.application_args[0] == Bytes("send"), send_invite()],
             [Txn.application_args[0] == Bytes("claim"), claim_invite()],
             [Txn.application_args[0] == Bytes("reclaim"), reclaim_expired()],
         )],
        
        # Reject everything else
        [Int(1), Int(0)]
    )
    
    return program

def compile_inbox_router_production():
    """Compile the production inbox router"""
    program = inbox_router_production()
    return compileTeal(program, Mode.Application, version=8)

def generate_claim_code(phone_or_email: str, salt: str = "") -> bytes:
    """
    Generate a 32-byte claim code.
    Uses cryptographically secure randomness to avoid predictable hashes of phone/email.
    """
    import secrets
    return secrets.token_bytes(32)

if __name__ == "__main__":
    print(compile_inbox_router_production())
    print("\n# Production Inbox Router with Sponsor Support")
    print("# Key improvements:")
    print("# 1. cUSD-only (saves 0.1 ALGO permanent MBR)")
    print("# 2. Sponsor funds all box creation")
    print("# 3. Explicit MBR refunds after box_delete")
    print("# 4. Recipient opt-in checks before transfers")
    print("# 5. GC rewards for expired invite cleanup")
    print("\n# Box MBR = 2500 + 400*(key_len + value_len). For 32+56 bytes → 37,700 µAlgos.")
    print("\n# Group transaction structures:")
    print("# Send: [Payment(sponsor→app), AXFER(sender→app), AppCall(send)]")
    print("# Claim: [Payment(sponsor fee-bump), AppCall(claim)]")
    print("# Reclaim: [Payment(sponsor fee-bump), AppCall(reclaim)]")
