"""
Invite & Send Contract for Confío - Algorand Implementation
Escrow-based invitation system with 7-day reclaim period
Website: https://confio.lat
"""

from pyteal import *
from beaker import *
from typing import Final

# Constants
RECLAIM_PERIOD_SECONDS = Int(604800)  # 7 days in seconds

class InviteSendState:
    """Global state for invite & send system"""
    
    admin: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Admin address"
    )
    
    is_paused: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="System pause state"
    )
    
    cusd_asset_id: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Confío Dollar asset ID"
    )
    
    confio_asset_id: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="CONFIO token asset ID"
    )
    
    # Statistics
    total_invitations_created: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total invitations created"
    )
    
    total_invitations_claimed: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total invitations claimed"
    )
    
    total_invitations_reclaimed: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total invitations reclaimed"
    )
    
    total_cusd_locked: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total Confío Dollar currently locked"
    )
    
    total_confio_locked: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total CONFIO currently locked"
    )

app = Application("InviteSend", state=InviteSendState())

@app.create
def create():
    """Initialize the invite & send contract"""
    return Seq(
        app.state.admin.set(Txn.sender()),
        app.state.is_paused.set(Int(0)),
        Approve()
    )

@app.external
def setup_assets(cusd_id: abi.Uint64, confio_id: abi.Uint64):
    """Setup asset IDs for invitations"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.cusd_asset_id == Int(0),
                app.state.confio_asset_id == Int(0)
            )
        ),
        app.state.cusd_asset_id.set(cusd_id.get()),
        app.state.confio_asset_id.set(confio_id.get()),
        
        # Opt-in to both assets
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: cusd_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: confio_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        Approve()
    )

@app.external
def create_invitation(
    invitation_id: abi.String,
    asset_transfer: abi.AssetTransferTransaction,
    message: abi.String
):
    """
    Create an invitation with escrowed funds
    Invitation data stored in box storage
    """
    return Seq(
        # Check system state and transaction
        Assert(
            And(
                app.state.is_paused == Int(0),
                asset_transfer.get().asset_receiver() == Global.current_application_address(),
                asset_transfer.get().asset_amount() > Int(0),
                Or(
                    asset_transfer.get().xfer_asset() == app.state.cusd_asset_id,
                    asset_transfer.get().xfer_asset() == app.state.confio_asset_id
                )
            )
        ),
        # Box will be created, will fail if already exists
        
        # Create box with invitation data
        # Box format: sender(32) | amount(8) | asset_id(8) | created_at(8) | expires_at(8) | 
        #            is_claimed(1) | is_reclaimed(1) | message_length(2) | message(variable)
        App.box_put(
            invitation_id.get(),
            Concat(
                Txn.sender(),  # sender (32 bytes)
                Itob(asset_transfer.get().asset_amount()),  # amount (8 bytes)
                Itob(asset_transfer.get().xfer_asset()),  # asset_id (8 bytes)
                Itob(Global.latest_timestamp()),  # created_at (8 bytes)
                Itob(Global.latest_timestamp() + RECLAIM_PERIOD_SECONDS),  # expires_at (8 bytes)
                Bytes("base16", "00"),  # is_claimed (1 byte)
                Bytes("base16", "00"),  # is_reclaimed (1 byte)
                Extract(Itob(Len(message.get())), Int(6), Int(2)),  # message length (2 bytes)
                message.get()  # message (variable length)
            )
        ),
        
        # Update statistics
        app.state.total_invitations_created.set(app.state.total_invitations_created + Int(1)),
        If(
            asset_transfer.get().xfer_asset() == app.state.cusd_asset_id,
            app.state.total_cusd_locked.set(app.state.total_cusd_locked + asset_transfer.get().asset_amount()),
            app.state.total_confio_locked.set(app.state.total_confio_locked + asset_transfer.get().asset_amount())
        ),
        
        Approve()
    )

@app.external
def claim_invitation(
    invitation_id: abi.String,
    recipient: abi.Address
):
    """
    Admin claims invitation on behalf of verified user
    Called after user verification through Django backend
    """
    sender = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    expires_at = ScratchVar(TealType.uint64)
    is_claimed = ScratchVar(TealType.bytes)
    is_reclaimed = ScratchVar(TealType.bytes)
    
    return Seq(
        # Load invitation data
        (invitation_data := App.box_get(invitation_id.get())),
        Assert(invitation_data.hasValue()),
        
        sender.store(BoxExtract(invitation_data.value(), Int(0), Int(32))),
        amount.store(Btoi(BoxExtract(invitation_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(BoxExtract(invitation_data.value(), Int(40), Int(8)))),
        expires_at.store(Btoi(BoxExtract(invitation_data.value(), Int(56), Int(8)))),
        is_claimed.store(BoxExtract(invitation_data.value(), Int(64), Int(1))),
        is_reclaimed.store(BoxExtract(invitation_data.value(), Int(65), Int(1))),
        
        # Verify conditions
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0),
                is_claimed.load() == Bytes("base16", "00"),  # Not claimed
                is_reclaimed.load() == Bytes("base16", "00"),  # Not reclaimed
                Global.latest_timestamp() <= expires_at.load()  # Not expired
            )
        ),
        
        # Transfer funds to recipient
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_amount: amount.load()
        }),
        InnerTxnBuilder.Submit(),
        
        # Mark as claimed
        App.box_replace(invitation_id.get(), Int(64), Bytes("base16", "01")),
        
        # Update statistics
        app.state.total_invitations_claimed.set(app.state.total_invitations_claimed + Int(1)),
        If(
            asset_id.load() == app.state.cusd_asset_id,
            app.state.total_cusd_locked.set(app.state.total_cusd_locked - amount.load()),
            app.state.total_confio_locked.set(app.state.total_confio_locked - amount.load())
        ),
        
        Approve()
    )

@app.external
def reclaim_invitation(invitation_id: abi.String):
    """
    Sender reclaims expired invitation
    Can only be called after 7-day expiry period
    """
    sender = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    expires_at = ScratchVar(TealType.uint64)
    is_claimed = ScratchVar(TealType.bytes)
    is_reclaimed = ScratchVar(TealType.bytes)
    
    return Seq(
        # Load invitation data
        (invitation_data := App.box_get(invitation_id.get())),
        Assert(invitation_data.hasValue()),
        
        sender.store(BoxExtract(invitation_data.value(), Int(0), Int(32))),
        amount.store(Btoi(BoxExtract(invitation_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(BoxExtract(invitation_data.value(), Int(40), Int(8)))),
        expires_at.store(Btoi(BoxExtract(invitation_data.value(), Int(56), Int(8)))),
        is_claimed.store(BoxExtract(invitation_data.value(), Int(64), Int(1))),
        is_reclaimed.store(BoxExtract(invitation_data.value(), Int(65), Int(1))),
        
        # Verify conditions
        Assert(
            And(
                app.state.is_paused == Int(0),
                Txn.sender() == sender.load(),
                is_claimed.load() == Bytes("base16", "00"),  # Not claimed
                is_reclaimed.load() == Bytes("base16", "00"),  # Not reclaimed
                Global.latest_timestamp() > expires_at.load()  # Expired
            )
        ),
        
        # Return funds to sender
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: sender.load(),
            TxnField.asset_amount: amount.load()
        }),
        InnerTxnBuilder.Submit(),
        
        # Mark as reclaimed
        App.box_replace(invitation_id.get(), Int(65), Bytes("base16", "01")),
        
        # Update statistics
        app.state.total_invitations_reclaimed.set(app.state.total_invitations_reclaimed + Int(1)),
        If(
            asset_id.load() == app.state.cusd_asset_id,
            app.state.total_cusd_locked.set(app.state.total_cusd_locked - amount.load()),
            app.state.total_confio_locked.set(app.state.total_confio_locked - amount.load())
        ),
        
        Approve()
    )

@app.external
def pause():
    """Pause invitation system"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        app.state.is_paused.set(Int(1)),
        Approve()
    )

@app.external
def unpause():
    """Unpause invitation system"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(1)
            )
        ),
        app.state.is_paused.set(Int(0)),
        Approve()
    )

@app.external(read_only=True)
def get_invitation_status(
    invitation_id: abi.String, 
    *, 
    output: abi.Tuple3[abi.Bool, abi.Bool, abi.Bool]
):
    """
    Get invitation status
    Returns: (exists, is_claimed, is_expired)
    """
    exists = abi.Bool()
    is_claimed = abi.Bool()
    is_expired = abi.Bool()
    
    return Seq(
        (invitation_data := App.box_get(invitation_id.get())),
        If(
            invitation_data.hasValue(),
            Seq(
                exists.set(True),
                is_claimed.set(
                    BoxExtract(invitation_data.value(), Int(64), Int(1)) == Bytes("base16", "01")
                ),
                is_expired.set(
                    Global.latest_timestamp() > Btoi(BoxExtract(invitation_data.value(), Int(56), Int(8)))
                )
            ),
            Seq(
                exists.set(False),
                is_claimed.set(False),
                is_expired.set(False)
            )
        ),
        output.set(exists, is_claimed, is_expired)
    )

@app.external(read_only=True)
def get_stats(*, output: abi.Tuple5[abi.Uint64, abi.Uint64, abi.Uint64, abi.Uint64, abi.Uint64]):
    """Get invitation statistics"""
    created = abi.Uint64()
    claimed = abi.Uint64()
    reclaimed = abi.Uint64()
    cusd_locked = abi.Uint64()
    confio_locked = abi.Uint64()
    
    return Seq(
        created.set(app.state.total_invitations_created),
        claimed.set(app.state.total_invitations_claimed),
        reclaimed.set(app.state.total_invitations_reclaimed),
        cusd_locked.set(app.state.total_cusd_locked),
        confio_locked.set(app.state.total_confio_locked),
        output.set(created, claimed, reclaimed, cusd_locked, confio_locked)
    )

@app.delete
def delete():
    """Only admin can delete"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Approve()
    )

if __name__ == "__main__":
    import json
    
    spec = app.build()
    
    with open("invite_send_approval.teal", "w") as f:
        f.write(spec.approval_program)
    
    with open("invite_send_clear.teal", "w") as f:
        f.write(spec.clear_program)
    
    with open("invite_send.json", "w") as f:
        f.write(json.dumps(spec.export(), indent=2))
    
    print("Invite & Send contract compiled successfully!")
    print("Website: https://confio.lat")