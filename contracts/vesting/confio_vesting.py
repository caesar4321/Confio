#!/usr/bin/env python3
"""
CONFIO Token Vesting Contract

Features:
- Admin deposits CONFIO and locks it.
- Linear vesting over a configurable duration (e.g. 24 or 36 months).
- Timer starts when Admin triggers it.
- Beneficiary can claim vested tokens.
- Admin can change the beneficiary address (revocability/reassignment).
- Admin can update the admin address.
"""

from pyteal import *

def confio_vesting():
    """
    CONFIO Vesting Contract
    """
    
    # Global state schema
    # admin: Address (Manager)
    # beneficiary: Address (Recipient)
    # confio_id: Uint64 (Asset ID)
    # start_time: Uint64 (Timestamp when vesting starts, 0 if inactive)
    # duration: Uint64 (Vesting duration in seconds)
    # total_locked: Uint64 (Total CONFIO deposited and locked)
    # total_claimed: Uint64 (Total CONFIO claimed)
    
    admin_address = Bytes("admin")
    beneficiary_address = Bytes("beneficiary")
    confio_asset_id = Bytes("confio_id")
    vesting_start_time = Bytes("start_time")
    vesting_duration = Bytes("duration")
    total_locked_amount = Bytes("total_locked")
    total_claimed_amount = Bytes("total_claimed")
    
    # Initialize contract
    @Subroutine(TealType.uint64)
    def initialize():
        confio_id_arg = Btoi(Txn.application_args[0])
        beneficiary_arg = Txn.application_args[1]
        duration_arg = Btoi(Txn.application_args[2])
        
        return Seq([
            # Verify arguments
            Assert(Txn.application_args.length() == Int(3)),
            # Validate asset ID
            Assert(confio_id_arg > Int(0)),
            # Validate beneficiary address
            Assert(Len(beneficiary_arg) == Int(32)),
            # Validate duration (must be positive)
            Assert(duration_arg > Int(0)),
            
            # Set global state
            App.globalPut(admin_address, Txn.sender()),
            App.globalPut(beneficiary_address, beneficiary_arg),
            App.globalPut(confio_asset_id, confio_id_arg),
            App.globalPut(vesting_duration, duration_arg),
            App.globalPut(vesting_start_time, Int(0)), # Not started yet
            App.globalPut(total_locked_amount, Int(0)),
            App.globalPut(total_claimed_amount, Int(0)),
            
            Int(1)
        ])

    # Fund vault (Admin deposits CONFIO)
    @Subroutine(TealType.uint64)
    def fund_vault():
        # Determines how much is being deposited
        amount = ScratchVar(TealType.uint64)
        
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # No rekeying
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Group: [Payment (gas), AssetTransfer (fund), AppCall (this)]
            # Or just [AssetTransfer, AppCall] if admin pays gas in AssetTransfer
            # Let's assume strict structure:
            # Gtxn[-1]: Asset Transfer to this contract
            
            Assert(Global.group_size() >= Int(2)),
            Assert(Gtxn[Txn.group_index() - Int(1)].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[Txn.group_index() - Int(1)].xfer_asset() == App.globalGet(confio_asset_id)),
            Assert(Gtxn[Txn.group_index() - Int(1)].asset_receiver() == Global.current_application_address()),
            
            # Store amount
            amount.store(Gtxn[Txn.group_index() - Int(1)].asset_amount()),
            Assert(amount.load() > Int(0)),
            
            # Update total locked
            App.globalPut(total_locked_amount, App.globalGet(total_locked_amount) + amount.load()),
            
            Log(Concat(
                Bytes("ADMIN|FUND|"),
                Itob(amount.load())
            )),
            
            Int(1)
        ])

    # Start Timer (Admin only)
    @Subroutine(TealType.uint64)
    def start_timer():
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            
            # Must have locked tokens
            Assert(App.globalGet(total_locked_amount) > Int(0)),
            
            # Must not be already started
            Assert(App.globalGet(vesting_start_time) == Int(0)),
            
            # Set start time to now
            App.globalPut(vesting_start_time, Global.latest_timestamp()),
            
            Log(Concat(
                Bytes("ADMIN|START|"),
                Itob(Global.latest_timestamp())
            )),
            
            Int(1)
        ])

    # Claim Vested Tokens (Beneficiary only)
    @Subroutine(TealType.uint64)
    def claim():
        # Math vars
        now = ScratchVar(TealType.uint64)
        start = ScratchVar(TealType.uint64)
        duration = ScratchVar(TealType.uint64)
        total = ScratchVar(TealType.uint64)
        claimed = ScratchVar(TealType.uint64)
        elapsed = ScratchVar(TealType.uint64)
        vested = ScratchVar(TealType.uint64)
        claimable = ScratchVar(TealType.uint64)
        
        return Seq([
            # Beneficiary only
            Assert(Txn.sender() == App.globalGet(beneficiary_address)),
            # Must be opted in to app? Not strictly necessary for this logic, but good practice.
            # We skip app opt-in check to allow beneficiary to just close-out if needed or call without opt-in.
            
            # Must be started
            start.store(App.globalGet(vesting_start_time)),
            Assert(start.load() > Int(0)),
            
            # Calculate vesting
            now.store(Global.latest_timestamp()),
            duration.store(App.globalGet(vesting_duration)),
            total.store(App.globalGet(total_locked_amount)),
            claimed.store(App.globalGet(total_claimed_amount)),
            
            # If Before start (should be caught by start > 0 check unless time is weird), claimable is 0
            # If now < start, elapsed = 0
            If(now.load() < start.load(),
               elapsed.store(Int(0)),
               elapsed.store(now.load() - start.load())
            ),
            
            # If elapsed >= duration, fully vested
            If(elapsed.load() >= duration.load(),
               vested.store(total.load()),
               # Linear vesting: vested = total * elapsed / duration
               vested.store(WideRatio([total.load(), elapsed.load()], [duration.load()]))
            ),
            
            # Calculate claimable
            If(vested.load() > claimed.load(),
               claimable.store(vested.load() - claimed.load()),
               claimable.store(Int(0))
            ),
            
            # Assert there is something to claim
            Assert(claimable.load() > Int(0)),
            
            # Ensure contract has enough balance
            (confio_balance := AssetHolding.balance(
                Global.current_application_address(),
                App.globalGet(confio_asset_id)
            )),
            Assert(confio_balance.hasValue()),
            Assert(confio_balance.value() >= claimable.load()),
            
            # Send tokens
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: Txn.sender(), # Beneficiary
                TxnField.asset_amount: claimable.load(),
                TxnField.fee: Int(0) # Inner txn fee must be covered by caller
            }),
            InnerTxnBuilder.Submit(),
            
            # Update state
            App.globalPut(total_claimed_amount, claimed.load() + claimable.load()),
            
            Log(Concat(
                Bytes("CLAIM|"),
                Itob(claimable.load())
            )),
            
            Int(1)
        ])

    # Change Beneficiary (Admin only)
    @Subroutine(TealType.uint64)
    def change_beneficiary():
        new_beneficiary = Txn.application_args[1]
        
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            Assert(Len(new_beneficiary) == Int(32)),
            
            App.globalPut(beneficiary_address, new_beneficiary),
            
            Log(Concat(
                Bytes("ADMIN|CHANGE_BENEFICIARY|"),
                new_beneficiary
            )),
            
            Int(1)
        ])

    # Update Admin (Admin only)
    @Subroutine(TealType.uint64)
    def update_admin():
        new_admin = Txn.application_args[1]
        
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            Assert(Len(new_admin) == Int(32)),
            
            App.globalPut(admin_address, new_admin),
            
            Log(Concat(
                Bytes("ADMIN|UPDATE_ADMIN|"),
                new_admin
            )),
            
            Int(1)
        ])
    
    # Opt-In to Asset (Admin only - required to receive funding)
    @Subroutine(TealType.uint64)
    def opt_in_asset():
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            Int(1)
        ])

    # Withdraw Before Start (Admin only)
    # Allows recovering funds if timer hasn't started yet
    @Subroutine(TealType.uint64)
    def withdraw_before_start():
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            
            # Must NOT be started (start_time == 0)
            Assert(App.globalGet(vesting_start_time) == Int(0)),
            
            # Must have locked tokens
            Assert(App.globalGet(total_locked_amount) > Int(0)),
            
            # Send all CONFIO back to admin
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: App.globalGet(admin_address),
                TxnField.asset_amount: App.globalGet(total_locked_amount),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Log
            Log(Concat(
                Bytes("ADMIN|WITHDRAW_PRE_START|"),
                Itob(App.globalGet(total_locked_amount))
            )),
            
            # Reset total locked
            App.globalPut(total_locked_amount, Int(0)),
            
            Int(1)
        ])

    program = Cond(
        [Txn.application_id() == Int(0), initialize()],
        
        [Txn.on_completion() == OnComplete.DeleteApplication, Int(0)],
        [Txn.on_completion() == OnComplete.UpdateApplication, Int(0)],
        [Txn.on_completion() == OnComplete.OptIn, Int(1)], # Allow opt-in
        [Txn.on_completion() == OnComplete.CloseOut, Int(1)], # Allow close-out
        
        [Txn.on_completion() == OnComplete.NoOp, Cond(
            [Txn.application_args[0] == Bytes("fund"), fund_vault()],
            [Txn.application_args[0] == Bytes("start"), start_timer()],
            [Txn.application_args[0] == Bytes("claim"), claim()],
            [Txn.application_args[0] == Bytes("change_beneficiary"), change_beneficiary()],
            [Txn.application_args[0] == Bytes("update_admin"), update_admin()],
            [Txn.application_args[0] == Bytes("opt_in_asset"), opt_in_asset()],
            [Txn.application_args[0] == Bytes("withdraw_before_start"), withdraw_before_start()],
        )]
    )
    
    return program

def compile_vesting():
    return compileTeal(confio_vesting(), Mode.Application, version=8)

if __name__ == "__main__":
    print(compile_vesting())
