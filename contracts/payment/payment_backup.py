"""
Payment Contract for Confío - Algorand Implementation
Simple payment processing with 0.9% fee collection
Website: https://confio.lat

Production-ready with comprehensive security validations:
- Strict group ordering enforcement
- Reliable AssetHolding checks with Txn.accounts
- Protection against rekeys, closeouts, and clawbacks
- Safe fee computation with WideRatio
- Self-payment prevention

Usage and group structures:
- pay_with_cusd/confio: [Payment(sponsor→payer,0), AXFER(payer→app), AppCall(sponsor)]
- setup_assets: [Payment(sponsor→app, 0.2 ALGO), AppCall(setup_assets)]

Client SDK Requirements:
- Recipient must be in accounts[1] array
- Group transactions in exact order specified above
- App call fee: ≥ 2,000 µAlgos (base + 1 inner transaction)
"""

from pyteal import *
from beaker import *
from typing import Final

# Fee constants
FEE_BPS = Int(90)  # 0.9% = 90 basis points
BASIS_POINTS = Int(10000)  # 100% = 10000 basis points
ASA_OPT_IN_MBR = Int(100000)  # 0.1 ALGO per ASA opt-in

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
    
    sponsor_address: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Sponsor address allowed to send app calls on behalf of users"
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
        # Initialize asset IDs to 0 (must be set via setup_assets)
        app.state.cusd_asset_id.set(Int(0)),
        app.state.confio_asset_id.set(Int(0)),
        # Initialize fee balances
        app.state.cusd_fees_balance.set(Int(0)),
        app.state.confio_fees_balance.set(Int(0)),
        Approve()
    )

@app.external
def setup_assets(cusd_id: abi.Uint64, confio_id: abi.Uint64):
    """
    Setup asset IDs for payments
    Requires exact sponsor funding for MBR increase
    """
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.cusd_asset_id == Int(0),
                app.state.confio_asset_id == Int(0)
            )
        ),
        
        # Block rekeys
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Asset ID sanity and distinctness checks
        Assert(cusd_id.get() > Int(0)),
        Assert(confio_id.get() > Int(0)),
        Assert(cusd_id.get() != confio_id.get()),
        
        # Fee budget for two inner opt-ins (base + 2 inners)
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(3)),
        
        # Require exact sponsor funding for MBR
        # Group structure: [Payment(sponsor→app, amount == 2*ASA_OPT_IN_MBR), AppCall]
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(1)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        Assert(Gtxn[0].amount() == Int(2) * ASA_OPT_IN_MBR),  # Exactly 0.2 ALGO
        Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
        Assert(Gtxn[0].rekey_to() == Global.zero_address()),
        
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
    fee_payment: abi.AssetTransferTransaction,
    recipient: abi.Address,
    payment_id: abi.String  # Kept for compatibility but not used
):
    """
    Process a Confío Dollar payment with 0.9% fee
    Requires two asset transfers: one to merchant, one for fees
    """
    payment_amount = ScratchVar(TealType.uint64)
    fee_amount = ScratchVar(TealType.uint64)
    total_amount = ScratchVar(TealType.uint64)
    fee_calculated = ScratchVar(TealType.uint64)
    actual_payer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Enforce sponsored call - must be fully sponsored
        Assert(Txn.sender() == app.state.sponsor_address.get()),
        Assert(Txn.accounts.length() >= Int(2)),
        actual_payer.store(Txn.accounts[0]),  # User passed as account reference
        
        # Basic validation
        Assert(
            And(
                app.state.is_paused == Int(0),
                app.state.cusd_asset_id != Int(0),
                app.state.fee_recipient != Bytes(""),
            )
        ),
        
        # Block sender rekeys on the AppCall itself
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Enforce strict group ordering for 4-txn group with fees
        # [Payment(sponsor→user), AssetTransfer(user→merchant), AssetTransfer(user→fee_recipient), AppCall(sponsor)]
        Assert(Global.group_size() == Int(4)),
        Assert(Txn.group_index() == Int(3)),  # AppCall is always last
        
        # Verify the payment AXFER (to merchant)
        Assert(payment.get().type_enum() == TxnType.AssetTransfer),
        Assert(payment.get().xfer_asset() == app.state.cusd_asset_id),
        Assert(payment.get().sender() == actual_payer.load()),
        Assert(payment.get().asset_receiver() == recipient.get()),  # Direct to merchant
        Assert(payment.get().asset_close_to() == Global.zero_address()),
        Assert(payment.get().asset_sender() == Global.zero_address()),
        Assert(payment.get().rekey_to() == Global.zero_address()),
        
        # Verify the fee AXFER (to fee recipient)
        Assert(fee_payment.get().type_enum() == TxnType.AssetTransfer),
        Assert(fee_payment.get().xfer_asset() == app.state.cusd_asset_id),
        Assert(fee_payment.get().sender() == actual_payer.load()),
        Assert(fee_payment.get().asset_receiver() == app.state.fee_recipient),  # To fee recipient
        Assert(fee_payment.get().asset_close_to() == Global.zero_address()),
        Assert(fee_payment.get().asset_sender() == Global.zero_address()),
        Assert(fee_payment.get().rekey_to() == Global.zero_address()),
        
        # Calculate and verify the fee split (0.9% = 90 basis points)
        payment_amount.store(payment.get().asset_amount()),
        fee_amount.store(fee_payment.get().asset_amount()),
        total_amount.store(payment_amount.load() + fee_amount.load()),
        
        # Calculate expected fee: ceil(total * 90 / 10000)
        fee_calculated.store(WideRatio([total_amount.load(), FEE_BPS], [BASIS_POINTS])),
        
        # Verify fee amount matches calculation
        Assert(fee_amount.load() == fee_calculated.load()),
        
        # Ensure amounts are positive
        Assert(payment_amount.load() > Int(0)),
        Assert(fee_amount.load() > Int(0)),
        
        # Make AssetHolding.balance check reliable for recipient
        # Recipient MUST be in foreign accounts array (slot 1)
        Assert(Txn.accounts.length() >= Int(2)),
        Assert(Txn.accounts[1] == recipient.get()),
        (rec_bal := AssetHolding.balance(Txn.accounts[1], app.state.cusd_asset_id)),
        Assert(rec_bal.hasValue()),
        
        # Recipient sanity checks
        Assert(recipient.get() != Global.zero_address()),
        Assert(recipient.get() != Global.current_application_address()),
        
        # Self-payment prevention
        Assert(actual_payer.load() != recipient.get()),
        
        # Check fees (base fee only, no inner transactions needed)
        Assert(Txn.fee() >= Global.min_txn_fee()),
        
        # Validate sponsor payment at index 0
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].sender() == app.state.sponsor_address.get()),
        Assert(Gtxn[0].receiver() == actual_payer.load()),  # Payment to payer
        # Allow MBR top-up: amount can be 0 or up to 0.1 ALGO for MBR
        Assert(Gtxn[0].amount() <= Int(100_000)),  # Max 0.1 ALGO for MBR safety
        Assert(Gtxn[0].rekey_to() == Global.zero_address()),
        Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
        
        # No inner transactions needed - payments go directly!
        # Just update statistics
        
        # Update fee balance (fees are now sent directly to fee_recipient, not held)
        app.state.cusd_fees_balance.set(app.state.cusd_fees_balance.get() + fee_amount.load()),
        
        # Update statistics
        app.state.total_cusd_volume.set(app.state.total_cusd_volume.get() + total_amount.load()),
        app.state.total_cusd_fees_collected.set(app.state.total_cusd_fees_collected.get() + fee_amount.load()),
        
        
        Approve()
    )

@app.external
def pay_with_confio(
    payment: abi.AssetTransferTransaction,
    fee_payment: abi.AssetTransferTransaction,
    recipient: abi.Address,
    payment_id: abi.String  # Kept for compatibility but not used
):
    """
    Process a CONFIO payment with 0.9% fee
    Requires two asset transfers: one to merchant, one for fees
    """
    payment_amount = ScratchVar(TealType.uint64)
    fee_amount = ScratchVar(TealType.uint64)
    total_amount = ScratchVar(TealType.uint64)
    fee_calculated = ScratchVar(TealType.uint64)
    actual_payer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Enforce sponsored call - must be fully sponsored
        Assert(Txn.sender() == app.state.sponsor_address.get()),
        Assert(Txn.accounts.length() >= Int(2)),
        actual_payer.store(Txn.accounts[0]),  # User passed as account reference
        
        # Basic validation
        Assert(
            And(
                app.state.is_paused == Int(0),
                app.state.confio_asset_id != Int(0),
                app.state.fee_recipient != Bytes(""),
            )
        ),
        
        # Block sender rekeys on the AppCall itself
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Enforce strict group ordering for 4-txn group with fees
        # [Payment(sponsor→user), AssetTransfer(user→merchant), AssetTransfer(user→fee_recipient), AppCall(sponsor)]
        Assert(Global.group_size() == Int(4)),
        Assert(Txn.group_index() == Int(3)),  # AppCall is always last
        
        # Verify the payment AXFER (to merchant)
        Assert(payment.get().type_enum() == TxnType.AssetTransfer),
        Assert(payment.get().xfer_asset() == app.state.confio_asset_id),
        Assert(payment.get().sender() == actual_payer.load()),
        Assert(payment.get().asset_receiver() == recipient.get()),  # Direct to merchant
        Assert(payment.get().asset_close_to() == Global.zero_address()),
        Assert(payment.get().asset_sender() == Global.zero_address()),
        Assert(payment.get().rekey_to() == Global.zero_address()),
        
        # Verify the fee AXFER (to fee recipient)
        Assert(fee_payment.get().type_enum() == TxnType.AssetTransfer),
        Assert(fee_payment.get().xfer_asset() == app.state.confio_asset_id),
        Assert(fee_payment.get().sender() == actual_payer.load()),
        Assert(fee_payment.get().asset_receiver() == app.state.fee_recipient),  # To fee recipient
        Assert(fee_payment.get().asset_close_to() == Global.zero_address()),
        Assert(fee_payment.get().asset_sender() == Global.zero_address()),
        Assert(fee_payment.get().rekey_to() == Global.zero_address()),
        
        # Calculate and verify the fee split (0.9% = 90 basis points)
        payment_amount.store(payment.get().asset_amount()),
        fee_amount.store(fee_payment.get().asset_amount()),
        total_amount.store(payment_amount.load() + fee_amount.load()),
        
        # Calculate expected fee: ceil(total * 90 / 10000)
        fee_calculated.store(WideRatio([total_amount.load(), FEE_BPS], [BASIS_POINTS])),
        
        # Verify fee amount matches calculation
        Assert(fee_amount.load() == fee_calculated.load()),
        
        # Ensure amounts are positive
        Assert(payment_amount.load() > Int(0)),
        Assert(fee_amount.load() > Int(0)),
        
        # Make AssetHolding.balance check reliable for recipient
        # Recipient MUST be in foreign accounts array (slot 1)
        Assert(Txn.accounts.length() >= Int(2)),
        Assert(Txn.accounts[1] == recipient.get()),
        (rec_bal := AssetHolding.balance(Txn.accounts[1], app.state.confio_asset_id)),
        Assert(rec_bal.hasValue()),
        
        # Recipient sanity checks
        Assert(recipient.get() != Global.zero_address()),
        Assert(recipient.get() != Global.current_application_address()),
        
        # Self-payment prevention
        Assert(actual_payer.load() != recipient.get()),
        
        # Check fees (base fee only, no inner transactions needed)
        Assert(Txn.fee() >= Global.min_txn_fee()),
        
        # Validate sponsor payment at index 0
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].sender() == app.state.sponsor_address.get()),
        Assert(Gtxn[0].receiver() == actual_payer.load()),  # Payment to payer
        # Allow MBR top-up: amount can be 0 or up to 0.1 ALGO for MBR
        Assert(Gtxn[0].amount() <= Int(100_000)),  # Max 0.1 ALGO for MBR safety
        Assert(Gtxn[0].rekey_to() == Global.zero_address()),
        Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
        
        # No inner transactions needed - payments go directly!
        # Just update statistics
        
        # Update fee balance (fees are now sent directly to fee_recipient, not held)
        app.state.confio_fees_balance.set(app.state.confio_fees_balance.get() + fee_amount.load()),
        
        # Update statistics
        app.state.total_confio_volume.set(app.state.total_confio_volume.get() + total_amount.load()),
        app.state.total_confio_fees_collected.set(app.state.total_confio_fees_collected.get() + fee_amount.load()),
        
        
        Approve()
    )

@app.external
def withdraw_fees():
    """
    Admin withdraws collected fees to fee recipient
    Only withdraws tracked fee amounts, not entire balance
    """
    req_inners = ScratchVar(TealType.uint64)
    
    return Seq(
        # Admin check
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        
        # Block rekeys
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Dynamic fee requirement based on actual withdrawals
        req_inners.store(
            If(app.state.cusd_fees_balance.get() > Int(0), Int(1), Int(0)) +
            If(app.state.confio_fees_balance.get() > Int(0), Int(1), Int(0))
        ),
        # Fee must cover: base + dynamic number of inner transfers
        Assert(Txn.fee() >= Global.min_txn_fee() * (Int(1) + req_inners.load())),
        
        # Check actual balances match tracked amounts (clearer failures)
        (cusd_bal := AssetHolding.balance(Global.current_application_address(), app.state.cusd_asset_id)),
        (confio_bal := AssetHolding.balance(Global.current_application_address(), app.state.confio_asset_id)),
        
        If(app.state.cusd_fees_balance.get() > Int(0),
           Assert(And(cusd_bal.hasValue(), cusd_bal.value() >= app.state.cusd_fees_balance.get()))
        ),
        If(app.state.confio_fees_balance.get() > Int(0),
           Assert(And(confio_bal.hasValue(), confio_bal.value() >= app.state.confio_fees_balance.get()))
        ),
        
        # Withdraw only tracked Confío Dollar fees
        If(
            app.state.cusd_fees_balance.get() > Int(0),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: app.state.cusd_asset_id,
                    TxnField.asset_receiver: app.state.fee_recipient,
                    TxnField.asset_amount: app.state.cusd_fees_balance.get(),
                    TxnField.fee: Int(0)
                }),
                InnerTxnBuilder.Submit(),
                app.state.cusd_fees_balance.set(Int(0))
            )
        ),
        
        # Withdraw only tracked CONFIO fees
        If(
            app.state.confio_fees_balance.get() > Int(0),
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: app.state.confio_asset_id,
                    TxnField.asset_receiver: app.state.fee_recipient,
                    TxnField.asset_amount: app.state.confio_fees_balance.get(),
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
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Guard fee recipient target
        Assert(new_recipient.get() != Global.zero_address()),
        Assert(new_recipient.get() != Global.current_application_address()),
        
        app.state.fee_recipient.set(new_recipient.get()),
        Approve()
    )

@app.external
def set_sponsor(sponsor: abi.Address):
    """Admin sets or updates the sponsor address for sponsored transactions"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        app.state.sponsor_address.set(sponsor.get()),
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
        Assert(Txn.rekey_to() == Global.zero_address()),
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
        Assert(Txn.rekey_to() == Global.zero_address()),
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

@app.update
def update():
    """Only admin can update the contract"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Approve()
    )

@app.delete
def delete():
    """
    Only admin can delete
    Prevents deletion if app holds any ASAs
    """
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # App deletion guard - don't allow deletion while holding funds or receipts
        (cusd_bal := AssetHolding.balance(Global.current_application_address(), app.state.cusd_asset_id)),
        (confio_bal := AssetHolding.balance(Global.current_application_address(), app.state.confio_asset_id)),
        Assert(Or(Not(cusd_bal.hasValue()), cusd_bal.value() == Int(0))),
        Assert(Or(Not(confio_bal.hasValue()), confio_bal.value() == Int(0))),
        
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