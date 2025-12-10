#!/usr/bin/env python3
"""
CONFIO Vesting Pool Contract (Multi-Member)

Features:
- Single Admin, Single Vault (Pool).
- Multiple Beneficiaries managed via Boxes.
- Box Key: Beneficiary Address (32 bytes).
- Box Value: [TotalAllocated (uint64), TotalClaimed (uint64)] = 16 bytes.
- Linear Vesting based on Global Timer.
"""

from pyteal import *

def confio_vesting_pool():
    # Global State Keys
    admin_address = Bytes("admin")
    confio_asset_id = Bytes("confio_id")
    vesting_start_time = Bytes("start_time")
    vesting_duration = Bytes("duration")
    total_pool_locked = Bytes("total_pool_locked")
    
    # Constants
    BOX_SIZE = Int(16) # 8 bytes allocated + 8 bytes claimed
    
    # Helper: Get Box Value (Inlined logic)
    # box_value = App.box_get(addr)
    # allocated = Btoi(Substring(box_value, 0, 8))
    # claimed = Btoi(Substring(box_value, 8, 16))

    # Initialize
    @Subroutine(TealType.uint64)
    def initialize():
        confio_id_arg = Btoi(Txn.application_args[0])
        duration_arg = Btoi(Txn.application_args[1])
        
        return Seq([
            Assert(confio_id_arg > Int(0)),
            Assert(duration_arg > Int(0)),
            
            App.globalPut(admin_address, Txn.sender()),
            App.globalPut(confio_asset_id, confio_id_arg),
            App.globalPut(vesting_duration, duration_arg),
            App.globalPut(vesting_start_time, Int(0)),
            App.globalPut(total_pool_locked, Int(0)),
            
            Int(1)
        ])

    # Add Member (Admin Only)
    # Args: [address, allocation_amount]
    # Note: Caller must provide MBR payment for the box (min balance increase)
    # Box MBR: 2500 + (400 * (32 + 16)) = 2500 + 19200 = 21700 microAlgos approx per member.
    @Subroutine(TealType.uint64)
    def add_member():
        member_addr = Txn.application_args[1]
        allocation = Btoi(Txn.application_args[2])
        
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            Assert(Len(member_addr) == Int(32)),
            Assert(allocation > Int(0)),
            
            # Ensure box doesn't exist yet (prevent overwrite)
            (box_len := App.box_length(member_addr)),
            Assert(box_len.hasValue() == Int(0)),
            
            # Create Box: [Allocation (8 bytes) | Claimed (0) (8 bytes)]
            App.box_put(member_addr, Concat(Itob(allocation), Itob(Int(0)))),
            
            Log(Concat(
                Bytes("ADMIN|ADD_MEMBER|"),
                member_addr,
                Bytes("|"),
                Itob(allocation)
            )),
            
            Int(1)
        ])

    # Change Member (Admin Only)
    # Move allocation from Old Address to New Address
    # Args: [old_address, new_address]
    @Subroutine(TealType.uint64)
    def change_member():
        old_addr = Txn.application_args[1]
        new_addr = Txn.application_args[2]
        
        allocated = ScratchVar(TealType.uint64)
        claimed = ScratchVar(TealType.uint64)
        
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            
            # Read old box
            (maybe_box := App.box_get(old_addr)),
            Assert(maybe_box.hasValue()),
            allocated.store(Btoi(Substring(maybe_box.value(), Int(0), Int(8)))),
            claimed.store(Btoi(Substring(maybe_box.value(), Int(8), Int(16)))),
            
            # Create new box with same data
            (new_box_len := App.box_length(new_addr)),
            Assert(new_box_len.hasValue() == Int(0)),
            
            App.box_put(new_addr, Concat(Itob(allocated.load()), Itob(claimed.load()))),
            
            # Delete old box (Admin gets refund of MBR if they are the sender/closer? 
            # Actually box delete frees up the MBR requirements for the app account)
            Assert(App.box_delete(old_addr)),
            
            Log(Concat(
                Bytes("ADMIN|MOVE_MEMBER|"),
                old_addr,
                Bytes("|"),
                new_addr
            )),
            
            Int(1)
        ])

    # Claim (Member Only)
    @Subroutine(TealType.uint64)
    def claim():
        allocated = ScratchVar(TealType.uint64)
        claimed = ScratchVar(TealType.uint64)
        vested = ScratchVar(TealType.uint64)
        claimable = ScratchVar(TealType.uint64)
        
        start = ScratchVar(TealType.uint64)
        now = ScratchVar(TealType.uint64)
        elapsed = ScratchVar(TealType.uint64)
        duration = ScratchVar(TealType.uint64)
        
        return Seq([
            # Get Box for Sender
            (maybe_box := App.box_get(Txn.sender())),
            Assert(maybe_box.hasValue()),
            allocated.store(Btoi(Substring(maybe_box.value(), Int(0), Int(8)))),
            claimed.store(Btoi(Substring(maybe_box.value(), Int(8), Int(16)))),
            
            # Check Start Time
            start.store(App.globalGet(vesting_start_time)),
            Assert(start.load() > Int(0)),
            
            now.store(Global.latest_timestamp()),
            duration.store(App.globalGet(vesting_duration)),
            
            # Calculate Elapsed
            If(now.load() < start.load(),
               elapsed.store(Int(0)),
               elapsed.store(now.load() - start.load())
            ),
            
            # Calculate Vested
            If(elapsed.load() >= duration.load(),
               vested.store(allocated.load()),
               vested.store(WideRatio([allocated.load(), elapsed.load()], [duration.load()]))
            ),
            
            # Calculate Claimable
            If(vested.load() > claimed.load(),
               claimable.store(vested.load() - claimed.load()),
               claimable.store(Int(0))
            ),
            
            Assert(claimable.load() > Int(0)),
            
            # Update Box: [Allocated | New Claimed]
            App.box_put(Txn.sender(), Concat(Itob(allocated.load()), Itob(claimed.load() + claimable.load()))),
            
            # Send Tokens
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: claimable.load(),
                TxnField.fee: Int(0) # Inner txn fee sponsored
            }),
            InnerTxnBuilder.Submit(),
            
            Log(Concat(
                Bytes("CLAIM|"),
                Itob(claimable.load())
            )),
            
            Int(1)
        ])

    # Fund Pool (Admin Only)
    @Subroutine(TealType.uint64)
    def fund_pool():
        amount = ScratchVar(TealType.uint64)
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            Assert(Global.group_size() >= Int(2)),
            amount.store(Gtxn[Txn.group_index() - Int(1)].asset_amount()),
            Assert(amount.load() > Int(0)),
            
            App.globalPut(total_pool_locked, App.globalGet(total_pool_locked) + amount.load()),
            
            Log(Concat(Bytes("ADMIN|FUND|"), Itob(amount.load()))),
            Int(1)
        ])

    @Subroutine(TealType.uint64)
    def start_timer():
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            Assert(App.globalGet(total_pool_locked) > Int(0)),
            Assert(App.globalGet(vesting_start_time) == Int(0)),
            
            App.globalPut(vesting_start_time, Global.latest_timestamp()),
            Log(Concat(Bytes("ADMIN|START|"), Itob(Global.latest_timestamp()))),
            Int(1)
        ])

    @Subroutine(TealType.uint64)
    def withdraw_pool_pre_start():
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            Assert(App.globalGet(vesting_start_time) == Int(0)),
            Assert(App.globalGet(total_pool_locked) > Int(0)),
            
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: App.globalGet(admin_address),
                TxnField.asset_amount: App.globalGet(total_pool_locked),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            App.globalPut(total_pool_locked, Int(0)),
            Log(Bytes("ADMIN|WITHDRAW_ALL")),
            Int(1)
        ])
    
    @Subroutine(TealType.uint64)
    def update_admin():
        new_admin = Txn.application_args[1]
        return Seq([
            Assert(Txn.sender() == App.globalGet(admin_address)),
            Assert(Len(new_admin) == Int(32)),
            App.globalPut(admin_address, new_admin),
            Log(Concat(Bytes("ADMIN|UPDATE_ADMIN|"), new_admin)),
            Int(1)
        ])

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

    program = Cond(
        [Txn.application_id() == Int(0), initialize()],
        [Txn.on_completion() == OnComplete.DeleteApplication, Int(0)],
        [Txn.on_completion() == OnComplete.UpdateApplication, Int(0)],
        [Txn.on_completion() == OnComplete.OptIn, Int(1)],
        [Txn.on_completion() == OnComplete.CloseOut, Int(1)],
        
        [Txn.on_completion() == OnComplete.NoOp, Cond(
            [Txn.application_args[0] == Bytes("add_member"), add_member()],
            [Txn.application_args[0] == Bytes("change_member"), change_member()],
            [Txn.application_args[0] == Bytes("claim"), claim()],
            [Txn.application_args[0] == Bytes("fund"), fund_pool()],
            [Txn.application_args[0] == Bytes("start"), start_timer()],
            [Txn.application_args[0] == Bytes("withdraw_pre_start"), withdraw_pool_pre_start()],
            [Txn.application_args[0] == Bytes("opt_in_asset"), opt_in_asset()],
            [Txn.application_args[0] == Bytes("update_admin"), update_admin()],
        )]
    )
    
    return program

def compile_vesting_pool():
    return compileTeal(confio_vesting_pool(), Mode.Application, version=8)

if __name__ == "__main__":
    print(compile_vesting_pool())
