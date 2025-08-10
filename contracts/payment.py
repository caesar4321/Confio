"""
Payment Contract for Confío - Algorand Implementation
Simple payment processing with 0.9% fee collection
Website: https://confio.lat
"""

from pyteal import *
from beaker import *
from typing import Final

# Fee constants
FEE_PERCENTAGE = Int(90)  # 0.9% = 90 basis points
BASIS_POINTS = Int(10000)  # 100% = 10000 basis points

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
                payment.get().xfer_asset() == app.state.cusd_asset_id,
                payment.get().asset_receiver() == Global.current_application_address(),
                payment.get().asset_amount() > Int(0)
            )
        ),
        
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
            TxnField.asset_amount: net_amount.load()
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
            App.box_put(
                Concat(Bytes("payment_"), payment_id.get()),
                Concat(
                    Txn.sender(),  # payer (32 bytes)
                    recipient.get(),  # recipient (32 bytes)
                    Itob(payment_amount.load()),  # amount (8 bytes)
                    Itob(fee_amount.load()),  # fee (8 bytes)
                    Itob(Global.latest_timestamp()),  # timestamp (8 bytes)
                    Bytes("CUSD")  # token type (4 bytes)
                )
            )
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
                payment.get().xfer_asset() == app.state.confio_asset_id,
                payment.get().asset_receiver() == Global.current_application_address(),
                payment.get().asset_amount() > Int(0)
            )
        ),
        
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
            TxnField.asset_amount: net_amount.load()
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
            App.box_put(
                Concat(Bytes("payment_"), payment_id.get()),
                Concat(
                    Txn.sender(),  # payer (32 bytes)
                    recipient.get(),  # recipient (32 bytes)
                    Itob(payment_amount.load()),  # amount (8 bytes)
                    Itob(fee_amount.load()),  # fee (8 bytes)
                    Itob(Global.latest_timestamp()),  # timestamp (8 bytes)
                    Bytes("CONF")  # token type (4 bytes)
                )
            )
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
                    TxnField.asset_amount: cusd_balance.value()
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
                    TxnField.asset_amount: confio_balance.value()
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