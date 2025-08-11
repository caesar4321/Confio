"""
P2P Trading Contract for Confío - Algorand Implementation
Escrow-based peer-to-peer trading with dispute resolution
Website: https://confio.lat

Usage and group structures:
- Create trade: [Payment(sponsor|seller→app, amount=box MBR), AXFER(seller→app, asset=cUSD/CONFIO), AppCall(create_trade)]
  - The app computes MBR = 2500 + 400*(key_len + value_len) and requires the Payment to cover it. If a sponsor address is configured, the sponsor funds this Payment; otherwise the seller funds it.
- Accept: [AppCall(accept_trade)]
- Confirm received: [AppCall(confirm_payment_received)] with enough fee or fee-bump payment; buyer must be opted into the asset.
- Cancel: [AppCall(cancel_trade)] with enough fee; returns asset to seller and keeps a record in the box.
- Dispute: [Payment(sponsor|opener→app, amount=dispute MBR), AppCall(open_dispute)] writes a compact dispute record (hashed reason).
- Resolve: [AppCall(resolve_dispute)] with enough fee or fee-bump; winner must be opted into the asset.

- Notes:
- Boxes are funded at creation by the sponsor if configured (fallback to caller). Dispute boxes store a 32-byte hash of the reason to bound MBR.
- Inner transactions set fee to 0; callers should cover outer fees or include a fee-bump payment.
- Fiat currency code is not stored on-chain to minimize MBR; backends should track it off-chain alongside the trade ID.
"""

from pyteal import *
from beaker import *
from typing import Final

# MBR helpers and limits
MAX_TRADE_ID_LEN = Int(64)
TRADE_VALUE_FIXED_LEN = Int(32 + 8 + 8 + 8 + 8 + 8 + 1 + 8 + 32)  # 113 bytes

# Box MBR = 2500 + 400 * (key_len + value_len)
@Subroutine(TealType.uint64)
def box_mbr_cost(key_len: Expr, value_len: Expr) -> Expr:
    return Int(2500) + Int(400) * (key_len + value_len)

# Trade status constants
TRADE_STATUS_PENDING = Int(0)
TRADE_STATUS_ACTIVE = Int(1) 
TRADE_STATUS_COMPLETED = Int(2)
TRADE_STATUS_CANCELLED = Int(3)
TRADE_STATUS_DISPUTED = Int(4)
TRADE_STATUS_EXPIRED = Int(5)

# Trade window (15 minutes in seconds)
TRADE_WINDOW_SECONDS = Int(900)

class P2PTradeState:
    """Global state for P2P trading"""
    
    admin: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Admin address"
    )
    
    sponsor_address: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Optional sponsor address for MBR/fee funding"
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
    total_trades_created: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total trades created"
    )
    
    total_trades_completed: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total trades completed"
    )
    
    total_trades_cancelled: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total trades cancelled"
    )
    
    total_trades_disputed: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total trades disputed"
    )
    
    total_cusd_volume: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total Confío Dollar volume"
    )
    
    total_confio_volume: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total CONFIO volume"
    )

app = Application("P2PTrade", state=P2PTradeState())

@app.create
def create():
    """Initialize the P2P trading contract"""
    return Seq(
        app.state.admin.set(Txn.sender()),
        app.state.is_paused.set(Int(0)),
        Approve()
    )

@app.external
def setup_assets(cusd_id: abi.Uint64, confio_id: abi.Uint64):
    """Setup asset IDs for trading"""
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
            TxnField.asset_amount: Int(0),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: confio_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        Approve()
    )

@app.external
def create_trade(
    trade_id: abi.String,
    asset_transfer: abi.AssetTransferTransaction,
    fiat_amount: abi.Uint64,
    fiat_currency: abi.String
):
    """
    Create a new P2P trade offer (seller deposits crypto)
    Trade data stored in box storage
    """
    key_len = ScratchVar(TealType.uint64)
    mbr_cost = ScratchVar(TealType.uint64)

    return Seq(
        # Check system state and asset configuration
        Assert(app.state.is_paused == Int(0)),
        Assert(Or(app.state.cusd_asset_id != Int(0), app.state.confio_asset_id != Int(0))),

        # Bind the AXFER to the app call and verify
        Assert(asset_transfer.get().asset_receiver() == Global.current_application_address()),
        Assert(asset_transfer.get().asset_amount() > Int(0)),
        Assert(asset_transfer.get().sender() == Txn.sender()),
        Assert(Or(
            asset_transfer.get().xfer_asset() == app.state.cusd_asset_id,
            asset_transfer.get().xfer_asset() == app.state.confio_asset_id
        )),

        # Enforce group with MBR funding: [Payment, AXFER, AppCall]
        Assert(Global.group_size() == Int(3)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),

        # Bound trade_id length and compute MBR
        key_len.store(Len(trade_id.get())),
        Assert(And(key_len.load() > Int(0), key_len.load() <= MAX_TRADE_ID_LEN)),
        mbr_cost.store(box_mbr_cost(key_len.load(), TRADE_VALUE_FIXED_LEN)),
        # Allow sponsor to fund MBR if configured, otherwise seller funds it
        Assert(Or(
            And(
                app.state.sponsor_address != Bytes(""),
                Gtxn[0].sender() == app.state.sponsor_address,
                Gtxn[0].amount() >= mbr_cost.load()
            ),
            And(
                Gtxn[0].sender() == Txn.sender(),
                Gtxn[0].amount() >= mbr_cost.load()
            )
        )),

        # Ensure new trade
        Assert(Not(App.box_get(trade_id.get())[0])),
        Assert(App.box_create(trade_id.get(), TRADE_VALUE_FIXED_LEN)),

        # Populate fixed-size trade record
        App.box_replace(trade_id.get(), Int(0), Txn.sender()),                         # seller (32)
        App.box_replace(trade_id.get(), Int(32), Itob(asset_transfer.get().asset_amount())),  # amount (8)
        App.box_replace(trade_id.get(), Int(40), Itob(asset_transfer.get().xfer_asset())),    # asset_id (8)
        App.box_replace(trade_id.get(), Int(48), Itob(fiat_amount.get())),              # fiat_amount (8)
        App.box_replace(trade_id.get(), Int(56), Itob(Global.latest_timestamp())),      # created_at (8)
        App.box_replace(trade_id.get(), Int(64), Itob(Global.latest_timestamp() + TRADE_WINDOW_SECONDS)),  # expires_at (8)
        App.box_replace(trade_id.get(), Int(72), Bytes("base16", "00")),              # status (1)
        App.box_replace(trade_id.get(), Int(73), Itob(Int(0))),                        # accepted_at (8)
        App.box_replace(trade_id.get(), Int(81), Bytes("base32", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")), # buyer (32)

        # Update statistics
        app.state.total_trades_created.set(app.state.total_trades_created + Int(1)),

        Approve()
    )

@app.external  
def accept_trade(trade_id: abi.String):
    """Buyer accepts the trade"""
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    expires_at = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    
    return Seq(
        # Load trade data - BoxLen > 0 means box exists
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        expires_at.store(Btoi(Extract(trade_data.value(), Int(64), Int(8)))),
        status.store(Extract(trade_data.value(), Int(72), Int(1))),
        
        # Verify conditions
        Assert(
            And(
                app.state.is_paused == Int(0),
                status.load() == Bytes("base16", "00"),  # PENDING
                seller.load() != Txn.sender(),  # Can't self-trade
                Global.latest_timestamp() <= expires_at.load()
            )
        ),
        
        # Update trade to ACTIVE
        App.box_replace(trade_id.get(), Int(72), Bytes("base16", "01")),  # status = ACTIVE
        App.box_replace(trade_id.get(), Int(73), Itob(Global.latest_timestamp())),  # accepted_at
        App.box_replace(trade_id.get(), Int(81), Txn.sender()),  # buyer
        
        Approve()
    )

@app.external
def confirm_payment_received(trade_id: abi.String):
    """Seller confirms fiat payment received, releases crypto to buyer"""
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    buyer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        status.store(Extract(trade_data.value(), Int(72), Int(1))),
        buyer.store(Extract(trade_data.value(), Int(81), Int(32))),
        
        # Verify authorization
        Assert(
            And(
                app.state.is_paused == Int(0),
                Txn.sender() == seller.load(),
                status.load() == Bytes("base16", "01")  # ACTIVE
            )
        ),
        
        # Ensure buyer is opted-in to asset
        (buyer_hold := AssetHolding.balance(buyer.load(), asset_id.load())),
        Assert(buyer_hold.hasValue()),

        # Transfer funds to buyer
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: buyer.load(),
            TxnField.asset_amount: amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Update trade status
        App.box_replace(trade_id.get(), Int(72), Bytes("base16", "02")),  # COMPLETED
        
        # Update statistics
        app.state.total_trades_completed.set(app.state.total_trades_completed + Int(1)),
        If(
            asset_id.load() == app.state.cusd_asset_id,
            app.state.total_cusd_volume.set(app.state.total_cusd_volume + amount.load()),
            app.state.total_confio_volume.set(app.state.total_confio_volume + amount.load())
        ),
        
        Approve()
    )

@app.external
def cancel_trade(trade_id: abi.String):
    """Cancel trade (by seller if pending, or anyone if expired)"""
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    expires_at = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    
    return Seq(
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        expires_at.store(Btoi(Extract(trade_data.value(), Int(64), Int(8)))),
        status.store(Extract(trade_data.value(), Int(72), Int(1))),
        
        # Check authorization
        Assert(
            And(
                app.state.is_paused == Int(0),
                Or(
                    # Seller can cancel pending trade
                    And(
                        status.load() == Bytes("base16", "00"),  # PENDING
                        Txn.sender() == seller.load()
                    ),
                    # Anyone can cancel expired active trade
                    And(
                        status.load() == Bytes("base16", "01"),  # ACTIVE
                        Global.latest_timestamp() > expires_at.load()
                    )
                )
            )
        ),
        
        # Ensure seller is opted-in (should be, but enforce)
        (seller_hold := AssetHolding.balance(seller.load(), asset_id.load())),
        Assert(seller_hold.hasValue()),

        # Return funds to seller
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: seller.load(),
            TxnField.asset_amount: amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Update status
        App.box_replace(trade_id.get(), Int(72), Bytes("base16", "03")),  # CANCELLED
        
        # Update statistics
        app.state.total_trades_cancelled.set(app.state.total_trades_cancelled + Int(1)),
        
        Approve()
    )

@app.external
def open_dispute(trade_id: abi.String, reason: abi.String):
    """Open dispute (by buyer or seller)"""
    seller = ScratchVar(TealType.bytes)
    status = ScratchVar(TealType.bytes)
    buyer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        status.store(Extract(trade_data.value(), Int(72), Int(1))),
        buyer.store(Extract(trade_data.value(), Int(81), Int(32))),
        
        # Verify authorization
        Assert(
            And(
                app.state.is_paused == Int(0),
                status.load() == Bytes("base16", "01"),  # ACTIVE
                Or(
                    Txn.sender() == seller.load(),
                    Txn.sender() == buyer.load()
                )
            )
        ),
        
        # Update status to DISPUTED
        App.box_replace(trade_id.get(), Int(72), Bytes("base16", "04")),
        
        # Store dispute info in a compact fixed-size box (sponsor-funded if configured)
        # Key: trade_id + "_dispute"; Value: opened_by(32) | opened_at(8) | reason_hash(32) = 72
        (dispute_key := Concat(trade_id.get(), Bytes("_dispute"))),
        (dispute_key_len := Len(dispute_key)),
        (dispute_val_len := Int(32 + 8 + 32)),
        # Group must be [Payment, AppCall], funded by sponsor if set, else by opener
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        (dispute_mbr := box_mbr_cost(dispute_key_len, dispute_val_len)),
        Assert(Or(
            And(
                app.state.sponsor_address != Bytes(""),
                Gtxn[0].sender() == app.state.sponsor_address,
                Gtxn[0].amount() >= dispute_mbr
            ),
            And(
                Gtxn[0].sender() == Txn.sender(),
                Gtxn[0].amount() >= dispute_mbr
            )
        )),
        # Create and populate dispute box
        Assert(Not(App.box_get(dispute_key)[0])),
        Assert(App.box_create(dispute_key, dispute_val_len)),
        App.box_replace(dispute_key, Int(0), Txn.sender()),
        App.box_replace(dispute_key, Int(32), Itob(Global.latest_timestamp())),
        App.box_replace(dispute_key, Int(40), Sha256(reason.get())),
        
        # Update statistics
        app.state.total_trades_disputed.set(app.state.total_trades_disputed + Int(1)),
        
        Approve()
    )

@app.external
def resolve_dispute(trade_id: abi.String, winner: abi.Address):
    """Admin resolves dispute"""
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    buyer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        status.store(Extract(trade_data.value(), Int(72), Int(1))),
        buyer.store(Extract(trade_data.value(), Int(81), Int(32))),
        
        # Verify admin and status
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0),
                status.load() == Bytes("base16", "04"),  # DISPUTED
                Or(
                    winner.get() == seller.load(),
                    winner.get() == buyer.load()
                )
            )
        ),
        
        # Ensure winner is opted-in
        (win_hold := AssetHolding.balance(winner.get(), asset_id.load())),
        Assert(win_hold.hasValue()),

        # Transfer funds to winner
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: winner.get(),
            TxnField.asset_amount: amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Update status
        App.box_replace(trade_id.get(), Int(72), Bytes("base16", "02")),  # COMPLETED
        
        # Update volume if buyer won
        If(
            winner.get() == buyer.load(),
            If(
                asset_id.load() == app.state.cusd_asset_id,
                app.state.total_cusd_volume.set(app.state.total_cusd_volume + amount.load()),
                app.state.total_confio_volume.set(app.state.total_confio_volume + amount.load())
            )
        ),
        
        # Update completed count
        app.state.total_trades_completed.set(app.state.total_trades_completed + Int(1)),
        
        # Delete dispute box
        Pop(App.box_delete(Concat(trade_id.get(), Bytes("_dispute")))),
        
        Approve()
    )

@app.external
def pause():
    """Pause trading"""
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
    """Unpause trading"""
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

@app.external
def set_sponsor(sponsor: abi.Address):
    """Admin sets or updates the optional sponsor address for MBR/fee funding"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        app.state.sponsor_address.set(sponsor.get()),
        Approve()
    )

@app.external(read_only=True)
def get_created_count(*, output: abi.Uint64):
    """Get total trades created"""
    return output.set(app.state.total_trades_created)

@app.external(read_only=True)
def get_completed_count(*, output: abi.Uint64):
    """Get total trades completed"""
    return output.set(app.state.total_trades_completed)

@app.external(read_only=True)
def get_volume(*, output: abi.Tuple2[abi.Uint64, abi.Uint64]):
    """Get trading volume (cusd, confio)"""
    cusd_vol = abi.Uint64()
    confio_vol = abi.Uint64()
    return Seq(
        cusd_vol.set(app.state.total_cusd_volume),
        confio_vol.set(app.state.total_confio_volume),
        output.set(cusd_vol, confio_vol)
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
    
    with open("p2p_trade_approval.teal", "w") as f:
        f.write(spec.approval_program)
    
    with open("p2p_trade_clear.teal", "w") as f:
        f.write(spec.clear_program)
    
    with open("p2p_trade.json", "w") as f:
        f.write(json.dumps(spec.export(), indent=2))
    
    print("P2P Trade contract compiled successfully!")
    print("Website: https://confio.lat")
