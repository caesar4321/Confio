"""
P2P Trading Contract for Confío - Algorand Implementation
Escrow-based peer-to-peer trading with dispute resolution
Website: https://confio.lat

Usage and group structures:
- Create trade (non-sponsored): [Payment(seller→app, amount=box MBR), AXFER(seller→app, asset=cUSD/CONFIO), AppCall(create_trade)]
- Create trade (sponsored): [Payment(sponsor→user, fees), Payment(seller→app, MBR), AXFER(seller→app, asset=cUSD/CONFIO), AppCall(create_trade)]
- Accept: [AppCall(accept_trade)] - sets 15-minute window
- Confirm received: [AppCall(confirm_payment_received)] - deletes box and refunds MBR via inner payment
- Cancel: [AppCall(cancel_trade)] - deletes box and refunds MBR via inner payment
- Dispute: [Payment(sponsor|opener→app, amount=dispute MBR), AppCall(open_dispute)]
- Resolve: [AppCall(resolve_dispute)] - deletes both boxes and refunds MBR via inner payments

Note: Box deletion (App.box_delete) does NOT automatically return MBR to creator.
The contract explicitly sends MBR refunds via inner payment transactions to the original payers.
"""

from pyteal import *
from beaker import *
from typing import Final

# MBR helpers and limits
MAX_TRADE_ID_LEN = Int(56)  # Max 56 bytes: 56 + len("_dispute") = 64 (Algorand's box key limit)
# Trade box layout (optimized - moved paid data to separate box):
# seller(32) + amount(8) + asset_id(8) + created_at(8) + expires_at(8) +
# status(1) + accepted_at(8) + buyer(32) + mbr_payer(32) = 137 bytes
TRADE_VALUE_FIXED_LEN = Int(137)  # 32+8+8+8+8+1+8+32+32 = 137 bytes
# MBR = 2500 + 400*(32+137) = 70,100 µALGO = 0.0701 ALGO
# Paid box layout (only created when needed):
# paid_at(8) + ref_hash(32) + extended(1) = 41 bytes  
PAID_VALUE_LEN = Int(8 + 32 + 1)
DISPUTE_VALUE_LEN = Int(32 + 8 + 32 + 32)  # 104 bytes (opened_by + opened_at + reason_hash + payer)

# Box MBR = 2500 + 400 * (key_len + value_len)
@Subroutine(TealType.uint64)
def box_mbr_cost(key_len: Expr, value_len: Expr) -> Expr:
    return Int(2500) + Int(400) * (key_len + value_len)

# Delete box and explicitly refund MBR to payer via inner payment
# Note: App.box_delete() does NOT automatically return MBR - we must send it manually
@Subroutine(TealType.none)
def refund_box_mbr(box_key: Expr, value_len: Expr, payer: Expr):
    mbr = ScratchVar(TealType.uint64)
    return Seq(
        mbr.store(box_mbr_cost(Len(box_key), value_len)),
        Assert(App.box_delete(box_key)),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: payer,
            TxnField.amount: mbr.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit()
    )

# Helper to refund _paid box if it exists
@Subroutine(TealType.none)
def maybe_refund_paid_box(trade_id: Expr, buyer: Expr):
    paid_key = ScratchVar(TealType.bytes)
    return Seq(
        paid_key.store(Concat(trade_id, Bytes("_paid"))),
        (mv := App.box_get(paid_key.load())),
        If(mv.hasValue(), 
           refund_box_mbr(paid_key.load(), PAID_VALUE_LEN, buyer)
        )
    )

# Check for no rekey/close on transaction
@Subroutine(TealType.uint64)
def no_rekey_close(txn_index: Expr) -> Expr:
    return And(
        Gtxn[txn_index].rekey_to() == Global.zero_address(),
        Gtxn[txn_index].close_remainder_to() == Global.zero_address(),
        Or(
            Gtxn[txn_index].type_enum() != TxnType.AssetTransfer,
            Gtxn[txn_index].asset_close_to() == Global.zero_address()
        )
    )

# Trade status constants
TRADE_STATUS_PENDING = Int(0)
TRADE_STATUS_ACTIVE = Int(1) 
TRADE_STATUS_COMPLETED = Int(2)
TRADE_STATUS_CANCELLED = Int(3)
TRADE_STATUS_DISPUTED = Int(4)

# Trade window settings
TRADE_WINDOW_SECONDS = Int(900)  # 15 minutes default
EXTENSION_SECONDS = Int(600)  # 10 minutes extension when marked as paid
GRACE_PERIOD_SECONDS = Int(120)  # 2 minutes grace after expiry before third-party can cancel

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
    
    active_trades: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Number of active trades (for safe deletion)"
    )
    
    active_disputes: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Number of currently disputed trades"
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
        # Require sponsor deposit that also covers fees
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(And(app.state.sponsor_address != Bytes(""), Gtxn[0].sender() == app.state.sponsor_address)),
        # Deposit must go to the app so its balance can grow by 0.2 ALGO MBR
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        # 0.2 ALGO for two ASA opt-ins + a little headroom for fees
        Assert(Gtxn[0].amount() >= Int(200_000)),
        
        # Verify rekey/close protection on AppCall
        Assert(no_rekey_close(Int(1))),
        
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
    asset_transfer: abi.AssetTransferTransaction
):
    """
    Create a new P2P trade offer (seller deposits crypto)
    Trade data stored in box storage with payer tracking
    Note: fiat_amount and currency stored off-chain with trade_id
    BOX REFS REQUIRED: trade_id
    """
    key_len = ScratchVar(TealType.uint64)
    mbr_cost = ScratchVar(TealType.uint64)
    mbr_payer = ScratchVar(TealType.bytes)
    delta = ScratchVar(TealType.uint64)
    actual_seller = ScratchVar(TealType.bytes)

    return Seq(
        # Check system state and asset configuration
        Assert(app.state.is_paused == Int(0)),
        Assert(Or(app.state.cusd_asset_id != Int(0), app.state.confio_asset_id != Int(0))),

        # Determine actual seller (could be sponsor calling on behalf of user)
        If(
            And(
                app.state.sponsor_address.get() != Bytes(""),
                Txn.sender() == app.state.sponsor_address.get(),
                Txn.accounts.length() > Int(0)
            ),
            actual_seller.store(Txn.accounts[0]),  # User passed as account reference
            actual_seller.store(Txn.sender())  # Direct call from user
        ),

        # Bind the AXFER to the app call and verify
        Assert(asset_transfer.get().asset_receiver() == Global.current_application_address()),
        Assert(asset_transfer.get().asset_amount() > Int(0)),
        Assert(asset_transfer.get().sender() == actual_seller.load()),
        Assert(Or(
            asset_transfer.get().xfer_asset() == app.state.cusd_asset_id,
            asset_transfer.get().xfer_asset() == app.state.confio_asset_id
        )),

        # Bound trade_id length and compute MBR
        key_len.store(Len(trade_id.get())),
        Assert(And(key_len.load() > Int(0), key_len.load() <= MAX_TRADE_ID_LEN)),
        mbr_cost.store(box_mbr_cost(key_len.load(), TRADE_VALUE_FIXED_LEN)),

        # Support both sponsored and non-sponsored groups
        # Non-sponsored: [Payment(seller→app), AXFER(seller→app), AppCall]
        # Sponsored: [Payment(sponsor→user), Payment(seller→app), AXFER(seller→app), AppCall]
        Assert(Or(
            Global.group_size() == Int(3),  # Non-sponsored
            Global.group_size() == Int(4)   # Sponsored
        )),

        # Determine indices and validate based on group size
        If(Global.group_size() == Int(4),
            Seq(
                # Sponsored: verify sponsor payment at index 0
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].amount() >= Int(0)),  # Can be 0 if just covering fees
                Assert(Or(
                    Gtxn[0].receiver() == Txn.sender(),  # Payment to user
                    Gtxn[0].receiver() == Global.current_application_address()  # Payment to app
                )),
                Assert(no_rekey_close(Int(0))),
                
                # MBR payment at index 1
                Assert(Gtxn[1].type_enum() == TxnType.Payment),
                Assert(Gtxn[1].sender() == actual_seller.load()),
                Assert(Gtxn[1].receiver() == Global.current_application_address()),
                Assert(no_rekey_close(Int(1))),
                Assert(Gtxn[1].amount() >= mbr_cost.load()),
                
                # AXFER at index 2
                Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
                Assert(Gtxn[2].asset_receiver() == Global.current_application_address()),
                Assert(Gtxn[2].sender() == actual_seller.load()),
                Assert(Gtxn[2].xfer_asset() == asset_transfer.get().xfer_asset()),
                Assert(Gtxn[2].asset_amount() == asset_transfer.get().asset_amount()),
                Assert(no_rekey_close(Int(2))),
                
                # App call at index 3
                Assert(Txn.group_index() == Int(3)),
                Assert(no_rekey_close(Int(3))),
                
                # Store MBR payer and refund amount
                mbr_payer.store(Gtxn[1].sender()),
                delta.store(Gtxn[1].amount() - mbr_cost.load())
            ),
            Seq(
                # Non-sponsored: original structure
                # MBR payment at index 0
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].receiver() == Global.current_application_address()),
                Assert(no_rekey_close(Int(0))),
                Assert(Gtxn[0].amount() >= mbr_cost.load()),
                
                # AXFER at index 1
                Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
                Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
                Assert(Gtxn[1].sender() == actual_seller.load()),
                Assert(Gtxn[1].xfer_asset() == asset_transfer.get().xfer_asset()),
                Assert(Gtxn[1].asset_amount() == asset_transfer.get().asset_amount()),
                Assert(no_rekey_close(Int(1))),
                
                # App call at index 2
                Assert(Txn.group_index() == Int(2)),
                Assert(no_rekey_close(Int(2))),
                
                # Record the real payer and restrict who it can be
                Assert(Or(
                    Gtxn[0].sender() == app.state.sponsor_address,
                    Gtxn[0].sender() == actual_seller.load()
                )),
                mbr_payer.store(Gtxn[0].sender()),
                delta.store(Gtxn[0].amount() - mbr_cost.load())
            )
        ),
        If(delta.load() > Int(0),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Gtxn[0].sender(),
                    TxnField.amount: delta.load(),
                    TxnField.fee: Int(0)
                }),
                InnerTxnBuilder.Submit()
            )
        ),

        # Verify vault is opted into the asset being traded
        (app_hold := AssetHolding.balance(Global.current_application_address(), asset_transfer.get().xfer_asset())),
        Assert(app_hold.hasValue()),
        
        # Ensure new trade
        (box_exists := App.box_get(trade_id.get())),
        Assert(Not(box_exists.hasValue())),
        Assert(App.box_create(trade_id.get(), TRADE_VALUE_FIXED_LEN)),

        # Populate fixed-size trade record with zero bytes for buyer
        App.box_replace(trade_id.get(), Int(0), actual_seller.load()),                 # seller (32)
        App.box_replace(trade_id.get(), Int(32), Itob(asset_transfer.get().asset_amount())),  # amount (8)
        App.box_replace(trade_id.get(), Int(40), Itob(asset_transfer.get().xfer_asset())),    # asset_id (8)
        App.box_replace(trade_id.get(), Int(48), Itob(Global.latest_timestamp())),      # created_at (8)
        App.box_replace(trade_id.get(), Int(56), Itob(Int(0))),                        # expires_at (8) - set on accept
        App.box_replace(trade_id.get(), Int(64), Bytes("base16", "00")),               # status (1)
        App.box_replace(trade_id.get(), Int(65), Itob(Int(0))),                        # accepted_at (8)
        App.box_replace(trade_id.get(), Int(73), Bytes("base16", "00" * 32)),          # buyer (32) - zero bytes
        App.box_replace(trade_id.get(), Int(105), mbr_payer.load()),                   # mbr_payer (32)

        # Update statistics
        app.state.total_trades_created.set(app.state.total_trades_created + Int(1)),
        app.state.active_trades.set(app.state.active_trades + Int(1)),
        
        # Event log for indexers
        Log(Concat(Bytes("ev:create:"), trade_id.get())),

        Approve()
    )

@app.external  
def accept_trade(trade_id: abi.String):
    """
    Buyer accepts the trade - starts 15-minute window
    BOX REFS REQUIRED: trade_id
    """
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    actual_buyer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Determine actual buyer (could be sponsor calling on behalf of user)
        If(
            And(
                app.state.sponsor_address.get() != Bytes(""),
                Txn.sender() == app.state.sponsor_address.get(),
                Txn.accounts.length() > Int(0)
            ),
            actual_buyer.store(Txn.accounts[0]),  # User passed as account reference
            actual_buyer.store(Txn.sender())  # Direct call from user
        ),
        
        # Verify rekey/close protection
        Assert(no_rekey_close(Int(0))),
        
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        status.store(Extract(trade_data.value(), Int(64), Int(1))),
        
        # Verify conditions
        Assert(
            And(
                app.state.is_paused == Int(0),
                status.load() == Bytes("base16", "00"),  # PENDING
                seller.load() != actual_buyer.load(),  # Can't self-trade
                Extract(trade_data.value(), Int(65), Int(8)) == Itob(Int(0))  # Not previously accepted
            )
        ),
        
        # Ensure buyer is opted into the asset
        (bal := AssetHolding.balance(actual_buyer.load(), asset_id.load())),
        Assert(bal.hasValue()),
        
        # Update trade to ACTIVE and set expiry window NOW
        App.box_replace(trade_id.get(), Int(56), Itob(Global.latest_timestamp() + TRADE_WINDOW_SECONDS)),  # expires_at
        App.box_replace(trade_id.get(), Int(64), Bytes("base16", "01")),  # status = ACTIVE
        App.box_replace(trade_id.get(), Int(65), Itob(Global.latest_timestamp())),  # accepted_at
        App.box_replace(trade_id.get(), Int(73), actual_buyer.load()),  # buyer
        
        # Event log for indexers
        Log(Concat(Bytes("ev:accept:"), trade_id.get())),
        
        Approve()
    )

@app.external
def mark_as_paid(trade_id: abi.String, payment_ref: abi.String):
    """
    Buyer marks trade as paid and can get one-time 10-minute extension
    BOX REFS REQUIRED: trade_id, trade_id+"_paid" (will be created)
    """
    buyer = ScratchVar(TealType.bytes)
    status = ScratchVar(TealType.bytes)
    expires_at = ScratchVar(TealType.uint64)
    paid_box_key = ScratchVar(TealType.bytes)
    paid_mbr = ScratchVar(TealType.uint64)
    delta = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify rekey/close protection
        Assert(no_rekey_close(Int(0))),
        Assert(no_rekey_close(Int(1))),  # Payment for paid box MBR
        
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        buyer.store(Extract(trade_data.value(), Int(73), Int(32))),
        status.store(Extract(trade_data.value(), Int(64), Int(1))),
        expires_at.store(Btoi(Extract(trade_data.value(), Int(56), Int(8)))),
        
        # Verify conditions
        Assert(
            And(
                app.state.is_paused == Int(0),
                status.load() == Bytes("base16", "01"),  # ACTIVE
                Txn.sender() == buyer.load()  # Only buyer can mark as paid
            )
        ),
        
        # Check if paid box already exists
        paid_box_key.store(Concat(trade_id.get(), Bytes("_paid"))),
        Assert(Len(paid_box_key.load()) <= Int(64)),  # Algorand box key limit
        (paid_exists := App.box_get(paid_box_key.load())),
        Assert(Not(paid_exists.hasValue())),  # Can only mark as paid once
        
        # Group must be [Payment, AppCall] for paid box MBR
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        paid_mbr.store(box_mbr_cost(Len(paid_box_key.load()), PAID_VALUE_LEN)),
        Assert(Gtxn[0].amount() >= paid_mbr.load()),
        Assert(Gtxn[0].sender() == Txn.sender()),  # Buyer pays for paid box
        
        # Refund overpayment
        delta.store(Gtxn[0].amount() - paid_mbr.load()),
        If(delta.load() > Int(0),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Gtxn[0].sender(),
                    TxnField.amount: delta.load(),
                    TxnField.fee: Int(0)
                }),
                InnerTxnBuilder.Submit()
            )
        ),
        
        # Create and populate paid box
        Assert(App.box_create(paid_box_key.load(), PAID_VALUE_LEN)),
        App.box_replace(paid_box_key.load(), Int(0), Itob(Global.latest_timestamp())),  # paid_at
        App.box_replace(paid_box_key.load(), Int(8), Sha256(payment_ref.get())),  # ref_hash
        App.box_replace(paid_box_key.load(), Int(40), Bytes("base16", "00")),  # extended = false
        
        # Apply one-time extension if within original window
        If(
            Global.latest_timestamp() <= expires_at.load(),
            Seq(
                App.box_replace(trade_id.get(), Int(56), Itob(expires_at.load() + EXTENSION_SECONDS)),
                App.box_replace(paid_box_key.load(), Int(40), Bytes("base16", "01"))  # mark as extended
            )
        ),
        
        # Event log for indexers
        Log(Concat(Bytes("ev:paid:"), trade_id.get())),
        
        Approve()
    )

@app.external
def confirm_payment_received(trade_id: abi.String):
    """
    Seller confirms fiat payment received, releases crypto to buyer
    BOX REFS REQUIRED: trade_id, trade_id+"_paid" (if exists)
    """
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    buyer = ScratchVar(TealType.bytes)
    mbr_payer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Verify rekey/close protection
        Assert(no_rekey_close(Int(0))),  # Payment
        Assert(no_rekey_close(Int(1))),  # AppCall
        
        # Verify Payment type for fee-bump
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        status.store(Extract(trade_data.value(), Int(64), Int(1))),
        buyer.store(Extract(trade_data.value(), Int(73), Int(32))),
        mbr_payer.store(Extract(trade_data.value(), Int(105), Int(32))),
        
        # Verify authorization
        Assert(
            And(
                app.state.is_paused == Int(0),
                Txn.sender() == seller.load(),
                status.load() == Bytes("base16", "01"),  # ACTIVE
                buyer.load() != Bytes("base16", "00" * 32)  # Buyer has been set
            )
        ),
        
        # Require sponsor fee bump for inner txns
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(And(app.state.sponsor_address != Bytes(""), Gtxn[0].sender() == app.state.sponsor_address)),
        Assert(Gtxn[0].fee() >= Int(3000)),  # Covers 1 inner AXFER + up to 2 inner payments
        
        # Ensure buyer is opted-in to asset
        (buyer_hold := AssetHolding.balance(buyer.load(), asset_id.load())),
        Assert(buyer_hold.hasValue()),

        # Transfer full amount to buyer (no fees in P2P)
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: buyer.load(),
            TxnField.asset_amount: amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Update statistics
        app.state.total_trades_completed.set(app.state.total_trades_completed + Int(1)),
        app.state.active_trades.set(app.state.active_trades - Int(1)),
        If(
            asset_id.load() == app.state.cusd_asset_id,
            app.state.total_cusd_volume.set(app.state.total_cusd_volume + amount.load()),
            app.state.total_confio_volume.set(app.state.total_confio_volume + amount.load())
        ),
        
        # First, refund _paid box (if any) to buyer
        maybe_refund_paid_box(trade_id.get(), buyer.load()),
        # Then delete trade box and refund MBR to payer
        refund_box_mbr(trade_id.get(), TRADE_VALUE_FIXED_LEN, mbr_payer.load()),
        
        # Event log for indexers
        Log(Concat(Bytes("ev:confirm:"), trade_id.get())),
        
        Approve()
    )

@app.external
def cancel_trade(trade_id: abi.String):
    """
    Cancel trade (by seller if pending, or anyone if expired with grace period)
    BOX REFS REQUIRED: trade_id, trade_id+"_paid" (if exists)
    """
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    expires_at = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    mbr_payer = ScratchVar(TealType.bytes)
    paid_at = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify rekey/close protection
        Assert(no_rekey_close(Int(0))),
        
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        expires_at.store(Btoi(Extract(trade_data.value(), Int(56), Int(8)))),
        status.store(Extract(trade_data.value(), Int(64), Int(1))),
        mbr_payer.store(Extract(trade_data.value(), Int(105), Int(32))),
        # Check if paid box exists
        (paid_box := App.box_get(Concat(trade_id.get(), Bytes("_paid")))),
        paid_at.store(If(paid_box.hasValue(), Btoi(Extract(paid_box.value(), Int(0), Int(8))), Int(0))),
        
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
                    # Anyone can cancel stale pending trade after 24h
                    And(
                        status.load() == Bytes("base16", "00"),  # PENDING
                        Global.latest_timestamp() > Btoi(Extract(trade_data.value(), Int(48), Int(8))) + Int(86400)  # 24h since creation
                    ),
                    # Anyone can cancel expired active trade (with grace period)
                    And(
                        status.load() == Bytes("base16", "01"),  # ACTIVE
                        expires_at.load() > Int(0),  # Expiry has been set
                        paid_at.load() == Int(0),  # Not marked as paid
                        Global.latest_timestamp() > expires_at.load() + GRACE_PERIOD_SECONDS
                    )
                    # Disputed trades must go through resolve_dispute, not cancel
                )
            )
        ),
        
        # No fee-bump needed: caller pays outer fee; refunds use freed MBR
        
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
        
        # Update statistics
        app.state.total_trades_cancelled.set(app.state.total_trades_cancelled + Int(1)),
        app.state.active_trades.set(app.state.active_trades - Int(1)),
        
        # Note: Disputed trades cannot be cancelled (enforced by assertion above)
        # They must go through resolve_dispute instead
        
        # Refund _paid box (if any) to buyer, then trade box to payer
        maybe_refund_paid_box(trade_id.get(), Extract(trade_data.value(), Int(73), Int(32))),  # buyer
        refund_box_mbr(trade_id.get(), TRADE_VALUE_FIXED_LEN, mbr_payer.load()),
        
        # Event log for indexers
        Log(Concat(Bytes("ev:cancel:"), trade_id.get())),
        
        Approve()
    )

@app.external
def open_dispute(trade_id: abi.String, reason: abi.String):
    """
    Open dispute (by buyer or seller) - tracks payer for MBR refund
    BOX REFS REQUIRED: trade_id, trade_id+"_dispute" (will be created)
    """
    seller = ScratchVar(TealType.bytes)
    status = ScratchVar(TealType.bytes)
    buyer = ScratchVar(TealType.bytes)
    dispute_payer = ScratchVar(TealType.bytes)
    dispute_key = ScratchVar(TealType.bytes)
    dispute_key_len = ScratchVar(TealType.uint64)
    dispute_mbr = ScratchVar(TealType.uint64)
    delta = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify rekey/close protection
        Assert(no_rekey_close(Int(0))),  # Payment
        Assert(no_rekey_close(Int(1))),  # AppCall
        
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        status.store(Extract(trade_data.value(), Int(64), Int(1))),
        buyer.store(Extract(trade_data.value(), Int(73), Int(32))),
        
        # Verify authorization
        Assert(
            And(
                app.state.is_paused == Int(0),
                status.load() == Bytes("base16", "01"),  # ACTIVE
                buyer.load() != Bytes("base16", "00" * 32),  # Buyer has been set
                Or(
                    Txn.sender() == seller.load(),
                    Txn.sender() == buyer.load()
                )
            )
        ),
        
        # Store dispute info with payer tracking
        # Key: trade_id + "_dispute"; Value: opened_by(32) | opened_at(8) | reason_hash(32) | payer(32) = 104
        dispute_key.store(Concat(trade_id.get(), Bytes("_dispute"))),
        dispute_key_len.store(Len(dispute_key.load())),
        Assert(dispute_key_len.load() <= Int(64)),  # Algorand box key limit
        
        # Group must be [Payment, AppCall], funded by sponsor if set, else by opener
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        
        # Track who pays for dispute box
        If(
            And(
                app.state.sponsor_address != Bytes(""),
                Gtxn[0].sender() == app.state.sponsor_address
            ),
            dispute_payer.store(app.state.sponsor_address),
            dispute_payer.store(Txn.sender())
        ),
        
        dispute_mbr.store(box_mbr_cost(dispute_key_len.load(), DISPUTE_VALUE_LEN)),
        Assert(Gtxn[0].amount() >= dispute_mbr.load()),
        
        # Refund overpayment
        delta.store(Gtxn[0].amount() - dispute_mbr.load()),
        If(delta.load() > Int(0),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Gtxn[0].sender(),
                    TxnField.amount: delta.load(),
                    TxnField.fee: Int(0)
                }),
                InnerTxnBuilder.Submit()
            )
        ),
        
        # Create and populate dispute box with payer
        (dispute_exists := App.box_get(dispute_key.load())),
        Assert(Not(dispute_exists.hasValue())),
        Assert(App.box_create(dispute_key.load(), DISPUTE_VALUE_LEN)),
        App.box_replace(dispute_key.load(), Int(0), Txn.sender()),                    # opened_by
        App.box_replace(dispute_key.load(), Int(32), Itob(Global.latest_timestamp())), # opened_at
        App.box_replace(dispute_key.load(), Int(40), Sha256(reason.get())),           # reason_hash
        App.box_replace(dispute_key.load(), Int(72), dispute_payer.load()),           # payer for MBR refund
        
        # Update status to DISPUTED after all validations succeed
        App.box_replace(trade_id.get(), Int(64), Bytes("base16", "04")),
        
        # Update statistics
        app.state.total_trades_disputed.set(app.state.total_trades_disputed + Int(1)),
        app.state.active_disputes.set(app.state.active_disputes + Int(1)),
        
        # Event log for indexers
        Log(Concat(Bytes("ev:dispute:"), trade_id.get())),
        
        Approve()
    )

@app.external
def resolve_dispute(trade_id: abi.String, winner: abi.Address):
    """
    Admin resolves dispute - refunds both boxes
    BOX REFS REQUIRED: trade_id, trade_id+"_dispute", trade_id+"_paid" (if exists)
    """
    seller = ScratchVar(TealType.bytes)
    amount = ScratchVar(TealType.uint64)
    asset_id = ScratchVar(TealType.uint64)
    status = ScratchVar(TealType.bytes)
    buyer = ScratchVar(TealType.bytes)
    mbr_payer = ScratchVar(TealType.bytes)
    dispute_payer = ScratchVar(TealType.bytes)
    dispute_key = ScratchVar(TealType.bytes)
    
    return Seq(
        # Verify rekey/close protection
        Assert(no_rekey_close(Int(0))),  # Payment
        Assert(no_rekey_close(Int(1))),  # AppCall
        
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        seller.store(Extract(trade_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        status.store(Extract(trade_data.value(), Int(64), Int(1))),
        buyer.store(Extract(trade_data.value(), Int(73), Int(32))),
        mbr_payer.store(Extract(trade_data.value(), Int(105), Int(32))),
        
        # Load dispute data
        dispute_key.store(Concat(trade_id.get(), Bytes("_dispute"))),
        (dispute_data := App.box_get(dispute_key.load())),
        Assert(dispute_data.hasValue()),
        dispute_payer.store(Extract(dispute_data.value(), Int(72), Int(32))),
        
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
        
        # Require sponsor fee bump for inner txns
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(And(app.state.sponsor_address != Bytes(""), Gtxn[0].sender() == app.state.sponsor_address)),
        Assert(Gtxn[0].fee() >= Int(4000)),  # Covers 1 inner AXFER + 2 inner refunds
        
        # Ensure winner is opted-in
        (win_hold := AssetHolding.balance(winner.get(), asset_id.load())),
        Assert(win_hold.hasValue()),

        # Transfer full amount to winner (no fees in P2P)
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: winner.get(),
            TxnField.asset_amount: amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Update statistics
        app.state.total_trades_completed.set(app.state.total_trades_completed + Int(1)),
        app.state.active_trades.set(app.state.active_trades - Int(1)),
        app.state.active_disputes.set(app.state.active_disputes - Int(1)),
        If(
            asset_id.load() == app.state.cusd_asset_id,
            app.state.total_cusd_volume.set(app.state.total_cusd_volume + amount.load()),
            app.state.total_confio_volume.set(app.state.total_confio_volume + amount.load())
        ),
        
        # Refund _paid box (if any) to buyer
        maybe_refund_paid_box(trade_id.get(), buyer.load()),
        
        # Delete dispute box and refund MBR to payer
        refund_box_mbr(dispute_key.load(), DISPUTE_VALUE_LEN, dispute_payer.load()),
        
        # Delete trade box and refund MBR
        refund_box_mbr(trade_id.get(), TRADE_VALUE_FIXED_LEN, mbr_payer.load()),
        
        # Event log for indexers
        Log(Concat(Bytes("ev:resolve:"), trade_id.get())),
        
        Approve()
    )

# Removed set_fee_receiver since P2P trades have no fees

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
def get_trade(
    trade_id: abi.String,
    *,
    output: abi.String
):
    """Get trade details: (seller, amount, asset_id, created_at, expires_at, status, accepted_at, buyer, mbr_payer)"""
    seller = abi.Address()
    amount = abi.Uint64()
    asset_id = abi.Uint64()
    created_at = abi.Uint64()
    expires_at = abi.Uint64()
    status = abi.Uint8()
    accepted_at = abi.Uint64()
    buyer = abi.Address()
    mbr_payer = abi.Address()
    
    return Seq(
        # Load trade data
        (trade_data := App.box_get(trade_id.get())),
        Assert(trade_data.hasValue()),
        
        # Extract and return all fields
        seller.set(Extract(trade_data.value(), Int(0), Int(32))),
        amount.set(Btoi(Extract(trade_data.value(), Int(32), Int(8)))),
        asset_id.set(Btoi(Extract(trade_data.value(), Int(40), Int(8)))),
        created_at.set(Btoi(Extract(trade_data.value(), Int(48), Int(8)))),
        expires_at.set(Btoi(Extract(trade_data.value(), Int(56), Int(8)))),
        status.set(Btoi(Extract(trade_data.value(), Int(64), Int(1)))),
        accepted_at.set(Btoi(Extract(trade_data.value(), Int(65), Int(8)))),
        buyer.set(Extract(trade_data.value(), Int(73), Int(32))),
        mbr_payer.set(Extract(trade_data.value(), Int(105), Int(32))),
        
        output.set(Concat(Bytes("trade_data:"), Itob(amount.get())))
    )

@app.external(read_only=True)
def get_stats(*, output: abi.Tuple4[abi.Uint64, abi.Uint64, abi.Uint64, abi.Uint64]):
    """Get comprehensive trading statistics"""
    created = abi.Uint64()
    completed = abi.Uint64()
    cancelled = abi.Uint64()
    disputed = abi.Uint64()
    return Seq(
        created.set(app.state.total_trades_created),
        completed.set(app.state.total_trades_completed),
        cancelled.set(app.state.total_trades_cancelled),
        disputed.set(app.state.total_trades_disputed),
        output.set(created, completed, cancelled, disputed)
    )

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
    """Only admin can delete - must have no active trades"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(app.state.active_trades == Int(0)),  # No active trades
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