"""
Payment Contract for Confío - Algorand Implementation
Simple payment processing with 0.9% fee collection
Website: https://confio.lat

Usage and group structures:
- pay_with_cusd/confio (no receipt): [AXFER(payer→app), AppCall(pay_* )]
- pay_with_cusd/confio (with receipt): [Payment(payer→app, amount=MBR), AXFER(payer→app), AppCall(pay_* )]
  - If a payment_id is provided, the app requires an MBR payment to fund a fixed-size receipt box.
  - MBR is computed on-chain as 2500 + 400*(key_len + value_len).

Notes:
- Receipt boxes are permanent audit records funded by the payer's MBR payment.
- Inner transactions set fee to 0; callers must cover outer fees or include a fee-bump payment.
"""

from pyteal import *
from beaker import *
from typing import Final

# Fee constants
FEE_PERCENTAGE = Int(90)  # 0.9% = 90 basis points
BASIS_POINTS = Int(10000)  # 100% = 10000 basis points
MAX_PAYMENT_ID_LEN = Int(64)
RECEIPT_PREFIX = Bytes("p:")

# Box MBR = 2500 + 400 * (key_len + value_len)
@Subroutine(TealType.uint64)
def box_mbr_cost(key_len: Expr, value_len: Expr) -> Expr:
    return Int(2500) + Int(400) * (key_len + value_len)

class PaymentState:
    """Global state for payment processing"""
    
    admin: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Admin address"
    )
    
    fee_recipient: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Fee recipient address"
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
    
    # Collected fees (held in contract)
    cusd_fees_balance: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Accumulated Confío Dollar fees"
    )
    
    confio_fees_balance: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Accumulated CONFIO fees"
    )
    
    # Statistics
    total_cusd_volume: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total Confío Dollar payment volume"
    )
    
    total_confio_volume: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total CONFIO payment volume"
    )
    
    total_cusd_fees_collected: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total Confío Dollar fees collected"
    )
    
    total_confio_fees_collected: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total CONFIO fees collected"
    )

app = Application("Payment", state=PaymentState())

@app.create
def create():
    """Initialize the payment contract"""
    return Seq(
        app.state.admin.set(Txn.sender()),
        app.state.fee_recipient.set(Txn.sender()),  # Initially set to deployer
        app.state.is_paused.set(Int(0)),
        Approve()
    )

@app.external
def setup_assets(cusd_id: abi.Uint64, confio_id: abi.Uint64):
    """Setup asset IDs for payments"""
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
def pay_with_cusd(
    payment: abi.AssetTransferTransaction,
    recipient: abi.Address,
    payment_id: abi.String  # Optional payment ID from Django for tracking
):
    """
    Process a Confío Dollar payment with 0.9% fee
    The payment transaction must be to this application
    """
    payment_amount = ScratchVar(TealType.uint64)
    fee_amount = ScratchVar(TealType.uint64)
    net_amount = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify transaction
        Assert(
            And(
                app.state.is_paused == Int(0),
                app.state.cusd_asset_id != Int(0),
                payment.get().xfer_asset() == app.state.cusd_asset_id,
                payment.get().asset_receiver() == Global.current_application_address(),
                payment.get().asset_amount() > Int(0),
                payment.get().sender() == Txn.sender()  # bind payer to app call
            )
        ),
        # Ensure recipient is opted-in
        (rec_bal := AssetHolding.balance(recipient.get(), app.state.cusd_asset_id)),
        Assert(rec_bal.hasValue()),
        
        # Calculate fee (0.9%)
        payment_amount.store(payment.get().asset_amount()),
        fee_amount.store(payment_amount.load() * FEE_PERCENTAGE / BASIS_POINTS),
        net_amount.store(payment_amount.load() - fee_amount.load()),
        
        # Send net amount to recipient
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.cusd_asset_id,
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_amount: net_amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Update fee balance
        app.state.cusd_fees_balance.set(app.state.cusd_fees_balance.get() + fee_amount.load()),
        
        # Update statistics
        app.state.total_cusd_volume.set(app.state.total_cusd_volume.get() + payment_amount.load()),
        app.state.total_cusd_fees_collected.set(app.state.total_cusd_fees_collected.get() + fee_amount.load()),
        
        # Store payment info in box if payment_id provided
        If(
            Len(payment_id.get()) > Int(0),
            Seq(
                # Build receipt key and enforce size
                (key := Concat(RECEIPT_PREFIX, payment_id.get())),
                (key_len := Len(key)),
                Assert(key_len <= MAX_PAYMENT_ID_LEN),
                
                # Fixed-size value: payer(32)|recipient(32)|amount(8)|fee(8)|ts(8)|asset_id(8) = 96
                (val_len := Int(32 + 32 + 8 + 8 + 8 + 8)),
                
                # If writing a receipt, require group with MBR funding payment
                # Require exact group sizing with MBR funding
                Assert(Global.group_size() == Int(3)),
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].sender() == Txn.sender()),
                Assert(Gtxn[0].receiver() == Global.current_application_address()),
                (mbr := box_mbr_cost(key_len, val_len)),
                Assert(Gtxn[0].amount() >= mbr),
                
                # Create and populate box
                Assert(Not(App.box_get(key)[0])),
                Assert(App.box_create(key, val_len)),
                App.box_replace(key, Int(0), Txn.sender()),
                App.box_replace(key, Int(32), recipient.get()),
                App.box_replace(key, Int(64), Itob(payment_amount.load())),
                App.box_replace(key, Int(72), Itob(fee_amount.load())),
                App.box_replace(key, Int(80), Itob(Global.latest_timestamp())),
                App.box_replace(key, Int(88), Itob(app.state.cusd_asset_id))
            )
        ,
            # No receipt: exactly [AXFER, AppCall]
            Assert(Global.group_size() == Int(2))
        ),
        
        Approve()
    )

@app.external
def pay_with_confio(
    payment: abi.AssetTransferTransaction,
    recipient: abi.Address,
    payment_id: abi.String  # Optional payment ID from Django for tracking
):
    """
    Process a CONFIO payment with 0.9% fee
    The payment transaction must be to this application
    """
    payment_amount = ScratchVar(TealType.uint64)
    fee_amount = ScratchVar(TealType.uint64)
    net_amount = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify transaction
        Assert(
            And(
                app.state.is_paused == Int(0),
                app.state.confio_asset_id != Int(0),
                payment.get().xfer_asset() == app.state.confio_asset_id,
                payment.get().asset_receiver() == Global.current_application_address(),
                payment.get().asset_amount() > Int(0),
                payment.get().sender() == Txn.sender()
            )
        ),
        # Ensure recipient is opted-in
        (rec_bal := AssetHolding.balance(recipient.get(), app.state.confio_asset_id)),
        Assert(rec_bal.hasValue()),
        
        # Calculate fee (0.9%)
        payment_amount.store(payment.get().asset_amount()),
        fee_amount.store(payment_amount.load() * FEE_PERCENTAGE / BASIS_POINTS),
        net_amount.store(payment_amount.load() - fee_amount.load()),
        
        # Send net amount to recipient
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.confio_asset_id,
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_amount: net_amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Update fee balance
        app.state.confio_fees_balance.set(app.state.confio_fees_balance.get() + fee_amount.load()),
        
        # Update statistics
        app.state.total_confio_volume.set(app.state.total_confio_volume.get() + payment_amount.load()),
        app.state.total_confio_fees_collected.set(app.state.total_confio_fees_collected.get() + fee_amount.load()),
        
        # Store payment info in box if payment_id provided
        If(
            Len(payment_id.get()) > Int(0),
            Seq(
                (key := Concat(RECEIPT_PREFIX, payment_id.get())),
                (key_len := Len(key)),
                Assert(key_len <= MAX_PAYMENT_ID_LEN),
                (val_len := Int(32 + 32 + 8 + 8 + 8 + 8)),
                Assert(Global.group_size() == Int(3)),
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].sender() == Txn.sender()),
                Assert(Gtxn[0].receiver() == Global.current_application_address()),
                (mbr := box_mbr_cost(key_len, val_len)),
                Assert(Gtxn[0].amount() >= mbr),
                Assert(Not(App.box_get(key)[0])),
                Assert(App.box_create(key, val_len)),
                App.box_replace(key, Int(0), Txn.sender()),
                App.box_replace(key, Int(32), recipient.get()),
                App.box_replace(key, Int(64), Itob(payment_amount.load())),
                App.box_replace(key, Int(72), Itob(fee_amount.load())),
                App.box_replace(key, Int(80), Itob(Global.latest_timestamp())),
                App.box_replace(key, Int(88), Itob(app.state.confio_asset_id))
            )
        ,
            Assert(Global.group_size() == Int(2))
        ),
        
        Approve()
    )

@app.external
def withdraw_fees():
    """Admin withdraws collected fees to fee recipient"""
    return Seq(
        # Admin check
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        
        # Get current balances
        (cusd_balance := AssetHolding.balance(Global.current_application_address(), app.state.cusd_asset_id)),
        (confio_balance := AssetHolding.balance(Global.current_application_address(), app.state.confio_asset_id)),
        
        # Withdraw Confío Dollar fees if any
        If(
            And(cusd_balance.hasValue(), cusd_balance.value() > Int(0)),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: app.state.cusd_asset_id,
                    TxnField.asset_receiver: app.state.fee_recipient,
                    TxnField.asset_amount: cusd_balance.value(),
                    TxnField.fee: Int(0)
                }),
                InnerTxnBuilder.Submit(),
                app.state.cusd_fees_balance.set(Int(0))
            )
        ),
        
        # Withdraw CONFIO fees if any
        If(
            And(confio_balance.hasValue(), confio_balance.value() > Int(0)),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: app.state.confio_asset_id,
                    TxnField.asset_receiver: app.state.fee_recipient,
                    TxnField.asset_amount: confio_balance.value(),
                    TxnField.fee: Int(0)
                }),
                InnerTxnBuilder.Submit(),
                app.state.confio_fees_balance.set(Int(0))
            )
        ),
        
        Approve()
    )

@app.external
def update_fee_recipient(new_recipient: abi.Address):
    """Admin updates the fee recipient address"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        app.state.fee_recipient.set(new_recipient.get()),
        Approve()
    )

@app.external
def pause():
    """Pause payment processing"""
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
    """Unpause payment processing"""
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
def get_fee_balances(*, output: abi.Tuple2[abi.Uint64, abi.Uint64]):
    """Get current fee balances held in contract"""
    cusd_bal = abi.Uint64()
    confio_bal = abi.Uint64()
    return Seq(
        cusd_bal.set(app.state.cusd_fees_balance),
        confio_bal.set(app.state.confio_fees_balance),
        output.set(cusd_bal, confio_bal)
    )

@app.external(read_only=True)
def get_total_volume(*, output: abi.Tuple2[abi.Uint64, abi.Uint64]):
    """Get total payment volume"""
    cusd_vol = abi.Uint64()
    confio_vol = abi.Uint64()
    return Seq(
        cusd_vol.set(app.state.total_cusd_volume),
        confio_vol.set(app.state.total_confio_volume),
        output.set(cusd_vol, confio_vol)
    )

@app.external(read_only=True)
def get_total_fees_collected(*, output: abi.Tuple2[abi.Uint64, abi.Uint64]):
    """Get total fees collected"""
    cusd_fees = abi.Uint64()
    confio_fees = abi.Uint64()
    return Seq(
        cusd_fees.set(app.state.total_cusd_fees_collected),
        confio_fees.set(app.state.total_confio_fees_collected),
        output.set(cusd_fees, confio_fees)
    )

@app.external(read_only=True)
def get_fee_recipient(*, output: abi.Address):
    """Get current fee recipient address"""
    return output.set(app.state.fee_recipient)

@app.external(read_only=True)
def is_paused(*, output: abi.Bool):
    """Check if system is paused"""
    return output.set(app.state.is_paused == Int(1))

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
    
    with open("payment_approval.teal", "w") as f:
        f.write(spec.approval_program)
    
    with open("payment_clear.teal", "w") as f:
        f.write(spec.clear_program)
    
    with open("payment.json", "w") as f:
        f.write(json.dumps(spec.export(), indent=2))
    
    print("Payment contract compiled successfully!")
    print("Website: https://confio.lat")
