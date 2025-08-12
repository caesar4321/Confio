#!/usr/bin/env python3
"""
Invite Pool Contract for Algorand
Handles send_and_invite functionality with a shared pool to minimize ALGO lock.

Usage:
- Send invite: [AXFER(sender→pool), AppCall(send_invite)]
- Claim: AppCall(claim_invite) standalone, or grouped with 0-amount pay-yourself Payment for fee budget
  Fee-bump format: [Payment(sender→sender, amount=0, no rekey/close), AppCall(claim_invite)]
- Reclaim: AppCall(reclaim_expired) standalone, or grouped with 0-amount pay-yourself Payment for fee budget
  Fee-bump format: [Payment(sender→sender, amount=0, no rekey/close), AppCall(reclaim_expired)]
"""

from pyteal import *
from algosdk import encoding

def invite_pool_contract():
    """
    Pooled invite contract that holds funds for non-users.
    Uses box storage to track individual invites.
    """
    
    # Global state schema: 5 ints, 2 bytes
    cusd_asset_id = Bytes("cusd_id")
    confio_asset_id = Bytes("confio_id")
    total_pending = Bytes("pending")     # Total value pending
    invite_count = Bytes("count")        # Number of active invites
    expiry_days = Bytes("expiry")        # Days until invite expires
    pool_opted_in = Bytes("opted")       # Whether pool has opted into assets
    
    # Box storage for invites
    # Key: recipient_address (32 bytes)
    # Value: sender(32) + cusd_amount(8) + confio_amount(8) + expiry(8) = 56 bytes
    
    # Initialize pool
    @Subroutine(TealType.uint64)
    def initialize():
        return Seq([
            # Asset IDs passed as arguments
            Assert(Txn.application_args.length() == Int(2)),
            App.globalPut(cusd_asset_id, Btoi(Txn.application_args[0])),
            App.globalPut(confio_asset_id, Btoi(Txn.application_args[1])),
            
            # Set defaults
            App.globalPut(expiry_days, Int(30)),  # 30 day expiry
            App.globalPut(total_pending, Int(0)),
            App.globalPut(invite_count, Int(0)),
            App.globalPut(pool_opted_in, Int(0)),
            
            Int(1)
        ])
    
    # Opt pool into assets (one-time)
    @Subroutine(TealType.uint64)
    def opt_in_assets():
        return Seq([
            # Only creator can opt-in
            Assert(Txn.sender() == Global.creator_address()),
            
            # Must not be already opted in
            Assert(App.globalGet(pool_opted_in) == Int(0)),
            
            # Must be in group with opt-in transactions
            Assert(Global.group_size() == Int(3)),
            
            # Verify opt-in to cUSD
            Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[1].asset_amount() == Int(0)),
            Assert(Gtxn[1].xfer_asset() == App.globalGet(cusd_asset_id)),
            
            # Verify opt-in to CONFIO
            Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[2].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[2].asset_amount() == Int(0)),
            Assert(Gtxn[2].xfer_asset() == App.globalGet(confio_asset_id)),
            
            # Mark as opted in
            App.globalPut(pool_opted_in, Int(1)),
            
            Int(1)
        ])
    
    # Send invite (deposit funds for non-user)
    @Subroutine(TealType.uint64)
    def send_invite():
        recipient = Txn.application_args[1]
        box_name = recipient
        
        # Box value structure
        sender_start = Int(0)
        cusd_start = Int(32)
        confio_start = Int(40)
        expiry_start = Int(48)
        box_size = Int(56)
        
        return Seq([
            # Pool must be opted in
            Assert(App.globalGet(pool_opted_in) == Int(1)),
            
            # Must be in group with asset transfers
            Assert(Global.group_size() >= Int(2)),
            
            # Check if invite already exists
            (existing_box := App.box_get(box_name)),
            Assert(Not(existing_box.hasValue())),
            
            # Create box for this invite
            Assert(App.box_create(box_name, box_size)),
            
            # Calculate amounts from transfers
            # Could be cUSD only, CONFIO only, or both
            (cusd_amount := ScratchVar()).store(Int(0)),
            (confio_amount := ScratchVar()).store(Int(0)),
            
            # Check for cUSD transfer
            If(And(
                Global.group_size() >= Int(2),
                Gtxn[1].type_enum() == TxnType.AssetTransfer,
                Gtxn[1].xfer_asset() == App.globalGet(cusd_asset_id),
                Gtxn[1].asset_receiver() == Global.current_application_address()
            ),
                cusd_amount.store(Gtxn[1].asset_amount())
            ),
            
            # Check for CONFIO transfer
            If(And(
                Global.group_size() >= Int(3),
                Gtxn[2].type_enum() == TxnType.AssetTransfer,
                Gtxn[2].xfer_asset() == App.globalGet(confio_asset_id),
                Gtxn[2].asset_receiver() == Global.current_application_address()
            ),
                confio_amount.store(Gtxn[2].asset_amount())
            ),
            
            # Store invite data in box
            App.box_replace(box_name, sender_start, Txn.sender()),
            App.box_replace(box_name, cusd_start, Itob(cusd_amount.load())),
            App.box_replace(box_name, confio_start, Itob(confio_amount.load())),
            App.box_replace(box_name, expiry_start, 
                Itob(Global.latest_timestamp() + App.globalGet(expiry_days) * Int(86400))
            ),
            
            # Update statistics
            App.globalPut(
                total_pending,
                App.globalGet(total_pending) + cusd_amount.load() + confio_amount.load()
            ),
            App.globalPut(
                invite_count,
                App.globalGet(invite_count) + Int(1)
            ),
            
            Int(1)
        ])
    
    # Security helper: No rekey/close for payment transactions
    @Subroutine(TealType.uint64)
    def no_rekey_close_pay(idx):
        return And(
            Gtxn[idx].rekey_to() == Global.zero_address(),
            Gtxn[idx].close_remainder_to() == Global.zero_address()
        )
    
    # Claim invite (recipient claims their funds)
    @Subroutine(TealType.uint64)
    def claim_invite():
        box_name = Txn.sender()
        
        return Seq([
            # This AppCall must not have rekey
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Allow optional fee-bump (fee-only, no deposit)
            Assert(Or(
                Global.group_size() == Int(1),
                And(
                    Global.group_size() == Int(2),
                    Gtxn[0].type_enum() == TxnType.Payment,
                    Gtxn[0].amount() == Int(0),  # pure fee, no deposit
                    Gtxn[0].receiver() == Gtxn[0].sender(),  # pay-yourself convention
                    no_rekey_close_pay(Int(0))
                )
            )),
            # Box must exist (invite must exist)
            (box_data := App.box_get(box_name)),
            Assert(box_data.hasValue()),
            
            # Parse box data
            (stored_data := box_data.value()),
            (cusd_amount := Btoi(Extract(stored_data, Int(32), Int(8)))),
            (confio_amount := Btoi(Extract(stored_data, Int(40), Int(8)))),
            (expiry := Btoi(Extract(stored_data, Int(48), Int(8)))),
            
            # Check not expired
            Assert(Global.latest_timestamp() <= expiry),
            
            # Transfer cUSD if any
            If(cusd_amount > Int(0),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(cusd_asset_id),
                        TxnField.asset_receiver: Txn.sender(),
                        TxnField.asset_amount: cusd_amount,
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Transfer CONFIO if any
            If(confio_amount > Int(0),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(confio_asset_id),
                        TxnField.asset_receiver: Txn.sender(),
                        TxnField.asset_amount: confio_amount,
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Update statistics
            App.globalPut(
                total_pending,
                App.globalGet(total_pending) - cusd_amount - confio_amount
            ),
            App.globalPut(
                invite_count,
                App.globalGet(invite_count) - Int(1)
            ),
            
            # Delete box
            Assert(App.box_delete(box_name)),
            
            Int(1)
        ])
    
    # Reclaim expired invite (sender reclaims expired funds)
    @Subroutine(TealType.uint64)
    def reclaim_expired():
        recipient = Txn.application_args[1]
        box_name = recipient
        
        return Seq([
            # This AppCall must not have rekey
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Allow optional fee-bump (fee-only, no deposit)
            Assert(Or(
                Global.group_size() == Int(1),
                And(
                    Global.group_size() == Int(2),
                    Gtxn[0].type_enum() == TxnType.Payment,
                    Gtxn[0].amount() == Int(0),  # pure fee, no deposit
                    Gtxn[0].receiver() == Gtxn[0].sender(),  # pay-yourself convention
                    no_rekey_close_pay(Int(0))
                )
            )),
            # Box must exist
            (box_data := App.box_get(box_name)),
            Assert(box_data.hasValue()),
            
            # Parse box data
            (stored_data := box_data.value()),
            (sender := Extract(stored_data, Int(0), Int(32))),
            (cusd_amount := Btoi(Extract(stored_data, Int(32), Int(8)))),
            (confio_amount := Btoi(Extract(stored_data, Int(40), Int(8)))),
            (expiry := Btoi(Extract(stored_data, Int(48), Int(8)))),
            
            # Must be sender or expired
            Assert(Or(
                Txn.sender() == sender,
                Global.latest_timestamp() > expiry
            )),
            
            # Return cUSD if any
            If(cusd_amount > Int(0),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(cusd_asset_id),
                        TxnField.asset_receiver: sender,
                        TxnField.asset_amount: cusd_amount,
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Return CONFIO if any
            If(confio_amount > Int(0),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(confio_asset_id),
                        TxnField.asset_receiver: sender,
                        TxnField.asset_amount: confio_amount,
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Update statistics
            App.globalPut(
                total_pending,
                App.globalGet(total_pending) - cusd_amount - confio_amount
            ),
            App.globalPut(
                invite_count,
                App.globalGet(invite_count) - Int(1)
            ),
            
            # Delete box
            Assert(App.box_delete(box_name)),
            
            Int(1)
        ])
    
    # Main router
    program = Cond(
        # Creation
        [Txn.application_id() == Int(0), initialize()],
        
        # NoOp calls
        [Txn.on_completion() == OnComplete.NoOp,
         Cond(
             [Txn.application_args[0] == Bytes("opt_in"), opt_in_assets()],
             [Txn.application_args[0] == Bytes("send"), send_invite()],
             [Txn.application_args[0] == Bytes("claim"), claim_invite()],
             [Txn.application_args[0] == Bytes("reclaim"), reclaim_expired()],
         )],
        
        # Reject everything else
        [Int(1), Int(0)]
    )
    
    return program

def compile_invite_pool():
    """Compile the invite pool contract"""
    program = invite_pool_contract()
    return compileTeal(program, Mode.Application, version=8)

if __name__ == "__main__":
    print(compile_invite_pool())