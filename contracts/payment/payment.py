"""
Payment Contract for Confío - Algorand Implementation
Simple payment processing with 0.9% fee collection
Website: https://confio.lat

Production-ready with comprehensive security validations:
- Strict group ordering enforcement
- Reliable AssetHolding checks with Txn.accounts
- Protection against rekeys, closeouts, and clawbacks
- Safe fee computation with WideRatio
- Exact ALGO MBR requirements
- Collision-proof receipt keys
- Self-payment prevention

Usage and group structures:
- pay_with_cusd/confio (no receipt): [AXFER(payer→app), AppCall(pay_*)]
- pay_with_cusd/confio (with receipt): [Payment(payer→app, amount=MBR), AXFER(payer→app), AppCall(pay_*)]
- setup_assets: [Payment(sponsor→app, 0.2 ALGO), AppCall(setup_assets)]

Client SDK Requirements:
- Recipient must be in accounts[1] array
- When writing receipt, box reference for key must be in boxes array
- Group transactions in exact order specified above
- App call fee requirements:
  * No receipt: ≥ 2,000 µAlgos (base + 1 inner)
  * With receipt: ≥ 4,500 µAlgos (base + 1 inner + box ref)

Receipt MBR Calculation:
- Key length: 2 ("p:") + 8 (asset_id) + 1 (":") + 32 (sha256) = 43 bytes
- Value length: 96 bytes (payer + recipient + amount + fee + timestamp + asset_id)
- MBR required: 2500 + 400*(43+96) = 58,100 µAlgos
- Payment amount in group[0] must be exactly 58,100 µAlgos
"""

from pyteal import *
from beaker import *
from typing import Final

# Fee constants
FEE_BPS = Int(90)  # 0.9% = 90 basis points
BASIS_POINTS = Int(10000)  # 100% = 10000 basis points
RECEIPT_PREFIX = Bytes("p:")
ASA_OPT_IN_MBR = Int(100000)  # 0.1 ALGO per ASA opt-in
BOX_REF_SURCHARGE = Int(2500)  # Box reference surcharge in µAlgos

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
    
    # Receipt counter for safe deletion
    receipt_count: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Number of receipts stored"
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
    prev_idx = ScratchVar(TealType.uint64)
    key = ScratchVar(TealType.bytes)
    key_len = ScratchVar(TealType.uint64)
    val_len = ScratchVar(TealType.uint64)
    mbr = ScratchVar(TealType.uint64)
    receipt_value = ScratchVar(TealType.bytes)
    actual_payer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Determine actual payer (could be sponsor calling on behalf of user)
        If(
            And(
                app.state.sponsor_address.get() != Bytes(""),
                Txn.sender() == app.state.sponsor_address.get(),
                Txn.accounts.length() > Int(0)
            ),
            actual_payer.store(Txn.accounts[0]),  # User passed as account reference
            actual_payer.store(Txn.sender())  # Direct call from user
        ),
        
        # Basic validation
        Assert(
            And(
                app.state.is_paused == Int(0),
                app.state.cusd_asset_id != Int(0),
            )
        ),
        
        # Block sender rekeys on the AppCall itself
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Prove the app is opted into the asset (fail fast if setup was skipped)
        (app_bal := AssetHolding.balance(
            Global.current_application_address(),
            app.state.cusd_asset_id
        )),
        Assert(app_bal.hasValue()),
        
        # Enforce strict group ordering
        # AppCall must be the last txn in the group
        # Support sponsored and non-sponsored patterns
        Assert(
            Or(
                # Non-sponsored patterns
                And(
                    Len(payment_id.get()) == Int(0),  # No receipt
                    Global.group_size() == Int(2),
                    Txn.group_index() == Int(1)
                ),
                And(
                    Len(payment_id.get()) > Int(0),   # With receipt
                    Global.group_size() == Int(3),
                    Txn.group_index() == Int(2)
                ),
                # Sponsored patterns
                And(
                    Len(payment_id.get()) == Int(0),  # No receipt, sponsored
                    Global.group_size() == Int(3),
                    Txn.group_index() == Int(2)
                ),
                And(
                    Len(payment_id.get()) > Int(0),   # With receipt, sponsored
                    Global.group_size() == Int(4),
                    Txn.group_index() == Int(3)
                )
            )
        ),
        
        # The AXFER must be immediately before the AppCall
        prev_idx.store(Txn.group_index() - Int(1)),
        Assert(Gtxn[prev_idx.load()].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[prev_idx.load()].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[prev_idx.load()].xfer_asset() == app.state.cusd_asset_id),
        Assert(Gtxn[prev_idx.load()].sender() == actual_payer.load()),  # Bind payer to app call
        
        # Require zeroed dangerous fields on AXFER
        Assert(Gtxn[prev_idx.load()].asset_close_to() == Global.zero_address()),
        Assert(Gtxn[prev_idx.load()].asset_sender() == Global.zero_address()),
        Assert(Gtxn[prev_idx.load()].rekey_to() == Global.zero_address()),
        
        # Bind the ABI payment object to the prev AXFER
        Assert(payment.get().sender() == actual_payer.load()),
        Assert(payment.get().xfer_asset() == Gtxn[prev_idx.load()].xfer_asset()),
        Assert(payment.get().asset_receiver() == Gtxn[prev_idx.load()].asset_receiver()),
        Assert(payment.get().asset_amount() == Gtxn[prev_idx.load()].asset_amount()),
        
        # Zero dangerous fields on the ABI-ref txn too
        Assert(payment.get().asset_close_to() == Global.zero_address()),
        Assert(payment.get().asset_sender() == Global.zero_address()),
        Assert(payment.get().rekey_to() == Global.zero_address()),
        
        # Additional payment validations
        Assert(payment.get().xfer_asset() == app.state.cusd_asset_id),
        Assert(payment.get().asset_receiver() == Global.current_application_address()),
        Assert(payment.get().asset_amount() > Int(0)),
        
        # Make AssetHolding.balance check reliable
        # Recipient MUST be in foreign accounts array (slot 1)
        Assert(Txn.accounts.length() >= Int(1)),
        Assert(Txn.accounts[1] == recipient.get()),
        (rec_bal := AssetHolding.balance(Txn.accounts[1], app.state.cusd_asset_id)),
        Assert(rec_bal.hasValue()),
        
        # Recipient sanity checks
        Assert(recipient.get() != Global.zero_address()),
        Assert(recipient.get() != Global.current_application_address()),
        
        # Self-payment prevention
        Assert(actual_payer.load() != recipient.get()),
        
        # Safe fee computation with WideRatio
        payment_amount.store(payment.get().asset_amount()),
        fee_amount.store(WideRatio([payment_amount.load(), FEE_BPS], [BASIS_POINTS])),
        net_amount.store(payment_amount.load() - fee_amount.load()),
        
        # Guarantee positive net amount
        Assert(net_amount.load() > Int(0)),
        
        # Check fees early (before any inner transactions)
        If(
            Len(payment_id.get()) > Int(0),
            # Receipt path: needs box reference fee
            Assert(Txn.fee() >= Global.min_txn_fee() * Int(2) + BOX_REF_SURCHARGE),
            # No-receipt path: just base + 1 inner
            Assert(Txn.fee() >= Global.min_txn_fee() * Int(2))
        ),
        
        # Validate sponsorship payment if present
        If(
            Or(
                And(Len(payment_id.get()) == Int(0), Global.group_size() == Int(3)),  # No receipt, sponsored
                And(Len(payment_id.get()) > Int(0), Global.group_size() == Int(4))    # With receipt, sponsored
            ),
            Seq(
                # Verify sponsor payment at index 0
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].amount() >= Int(0)),  # Can be 0 if just covering fees
                Assert(Or(
                    Gtxn[0].receiver() == actual_payer.load(),  # Payment to user
                    Gtxn[0].receiver() == Global.current_application_address()  # Payment to app
                )),
                Assert(Gtxn[0].rekey_to() == Global.zero_address()),
                Assert(Gtxn[0].close_remainder_to() == Global.zero_address())
            )
        ),
        
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
                # Cheaper, collision-proof receipt keys
                # key = b"p:" || Itob(asset_id) || b":" || Sha256(payment_id)
                key.store(Concat(
                    RECEIPT_PREFIX, 
                    Itob(app.state.cusd_asset_id), 
                    Bytes(":"), 
                    Sha256(payment_id.get())
                )),
                key_len.store(Len(key.load())),
                
                # Client must include the receipt box reference
                # Box references are validated implicitly by PyTeal when accessing boxes
                
                # Fixed-size value: payer(32)|recipient(32)|amount(8)|fee(8)|ts(8)|asset_id(8) = 96
                val_len.store(Int(96)),
                
                # If using a receipt, pin and validate the ALGO funding payment
                # Handle both sponsored and non-sponsored cases
                mbr.store(box_mbr_cost(key_len.load(), val_len.load())),
                If(
                    Global.group_size() == Int(3),
                    Seq(
                        # Non-sponsored: MBR payment at index 0
                        Assert(Gtxn[0].type_enum() == TxnType.Payment),
                        Assert(Gtxn[0].sender() == actual_payer.load()),
                        Assert(Gtxn[0].receiver() == Global.current_application_address()),
                        Assert(Gtxn[0].amount() == mbr.load()),  # Exact, not >=
                        Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
                        Assert(Gtxn[0].rekey_to() == Global.zero_address())
                    ),
                    Seq(
                        # Sponsored: MBR payment at index 1 (index 0 is sponsor payment)
                        Assert(Global.group_size() == Int(4)),
                        Assert(Gtxn[1].type_enum() == TxnType.Payment),
                        Assert(Gtxn[1].sender() == actual_payer.load()),
                        Assert(Gtxn[1].receiver() == Global.current_application_address()),
                        Assert(Gtxn[1].amount() == mbr.load()),  # Exact, not >=
                        Assert(Gtxn[1].close_remainder_to() == Global.zero_address()),
                        Assert(Gtxn[1].rekey_to() == Global.zero_address())
                    )
                ),
                
                # Box existence check using hasValue()
                (box_exists := App.box_get(key.load())),
                Assert(Not(box_exists.hasValue())),
                Assert(App.box_create(key.load(), val_len.load())),
                
                # Build and write receipt value in one operation
                receipt_value.store(Concat(
                    actual_payer.load(),                  # 32 bytes: payer
                    recipient.get(),                       # 32 bytes: recipient
                    Itob(payment_amount.load()),          # 8 bytes: amount
                    Itob(fee_amount.load()),              # 8 bytes: fee
                    Itob(Global.latest_timestamp()),      # 8 bytes: timestamp
                    Itob(app.state.cusd_asset_id)         # 8 bytes: asset_id
                )),
                Assert(Len(receipt_value.load()) == Int(96)),
                App.box_replace(key.load(), Int(0), receipt_value.load()),
                
                # Increment receipt counter
                app.state.receipt_count.set(app.state.receipt_count.get() + Int(1)),
                
                # Log event for off-chain indexing
                Log(Concat(Bytes("paid:cusd:"), Sha256(payment_id.get())))
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
    prev_idx = ScratchVar(TealType.uint64)
    key = ScratchVar(TealType.bytes)
    key_len = ScratchVar(TealType.uint64)
    val_len = ScratchVar(TealType.uint64)
    mbr = ScratchVar(TealType.uint64)
    receipt_value = ScratchVar(TealType.bytes)
    actual_payer = ScratchVar(TealType.bytes)
    
    return Seq(
        # Determine actual payer (could be sponsor calling on behalf of user)
        If(
            And(
                app.state.sponsor_address.get() != Bytes(""),
                Txn.sender() == app.state.sponsor_address.get(),
                Txn.accounts.length() > Int(0)
            ),
            actual_payer.store(Txn.accounts[0]),  # User passed as account reference
            actual_payer.store(Txn.sender())  # Direct call from user
        ),
        
        # Basic validation
        Assert(
            And(
                app.state.is_paused == Int(0),
                app.state.confio_asset_id != Int(0),
            )
        ),
        
        # Block sender rekeys on the AppCall itself
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Prove the app is opted into the asset (fail fast if setup was skipped)
        (app_bal := AssetHolding.balance(
            Global.current_application_address(),
            app.state.confio_asset_id
        )),
        Assert(app_bal.hasValue()),
        
        # Enforce strict group ordering
        # AppCall must be the last txn in the group
        # Support sponsored and non-sponsored patterns
        Assert(
            Or(
                # Non-sponsored patterns
                And(
                    Len(payment_id.get()) == Int(0),  # No receipt
                    Global.group_size() == Int(2),
                    Txn.group_index() == Int(1)
                ),
                And(
                    Len(payment_id.get()) > Int(0),   # With receipt
                    Global.group_size() == Int(3),
                    Txn.group_index() == Int(2)
                ),
                # Sponsored patterns
                And(
                    Len(payment_id.get()) == Int(0),  # No receipt, sponsored
                    Global.group_size() == Int(3),
                    Txn.group_index() == Int(2)
                ),
                And(
                    Len(payment_id.get()) > Int(0),   # With receipt, sponsored
                    Global.group_size() == Int(4),
                    Txn.group_index() == Int(3)
                )
            )
        ),
        
        # The AXFER must be immediately before the AppCall
        prev_idx.store(Txn.group_index() - Int(1)),
        Assert(Gtxn[prev_idx.load()].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[prev_idx.load()].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[prev_idx.load()].xfer_asset() == app.state.confio_asset_id),
        Assert(Gtxn[prev_idx.load()].sender() == actual_payer.load()),  # Bind payer to app call
        
        # Require zeroed dangerous fields on AXFER
        Assert(Gtxn[prev_idx.load()].asset_close_to() == Global.zero_address()),
        Assert(Gtxn[prev_idx.load()].asset_sender() == Global.zero_address()),
        Assert(Gtxn[prev_idx.load()].rekey_to() == Global.zero_address()),
        
        # Bind the ABI payment object to the prev AXFER
        Assert(payment.get().sender() == actual_payer.load()),
        Assert(payment.get().xfer_asset() == Gtxn[prev_idx.load()].xfer_asset()),
        Assert(payment.get().asset_receiver() == Gtxn[prev_idx.load()].asset_receiver()),
        Assert(payment.get().asset_amount() == Gtxn[prev_idx.load()].asset_amount()),
        
        # Zero dangerous fields on the ABI-ref txn too
        Assert(payment.get().asset_close_to() == Global.zero_address()),
        Assert(payment.get().asset_sender() == Global.zero_address()),
        Assert(payment.get().rekey_to() == Global.zero_address()),
        
        # Additional payment validations
        Assert(payment.get().xfer_asset() == app.state.confio_asset_id),
        Assert(payment.get().asset_receiver() == Global.current_application_address()),
        Assert(payment.get().asset_amount() > Int(0)),
        
        # Make AssetHolding.balance check reliable
        # Recipient MUST be in foreign accounts array (slot 1)
        Assert(Txn.accounts.length() >= Int(1)),
        Assert(Txn.accounts[1] == recipient.get()),
        (rec_bal := AssetHolding.balance(Txn.accounts[1], app.state.confio_asset_id)),
        Assert(rec_bal.hasValue()),
        
        # Recipient sanity checks
        Assert(recipient.get() != Global.zero_address()),
        Assert(recipient.get() != Global.current_application_address()),
        
        # Self-payment prevention
        Assert(actual_payer.load() != recipient.get()),
        
        # Safe fee computation with WideRatio
        payment_amount.store(payment.get().asset_amount()),
        fee_amount.store(WideRatio([payment_amount.load(), FEE_BPS], [BASIS_POINTS])),
        net_amount.store(payment_amount.load() - fee_amount.load()),
        
        # Guarantee positive net amount
        Assert(net_amount.load() > Int(0)),
        
        # Check fees early (before any inner transactions)
        If(
            Len(payment_id.get()) > Int(0),
            # Receipt path: needs box reference fee
            Assert(Txn.fee() >= Global.min_txn_fee() * Int(2) + BOX_REF_SURCHARGE),
            # No-receipt path: just base + 1 inner
            Assert(Txn.fee() >= Global.min_txn_fee() * Int(2))
        ),
        
        # Validate sponsorship payment if present
        If(
            Or(
                And(Len(payment_id.get()) == Int(0), Global.group_size() == Int(3)),  # No receipt, sponsored
                And(Len(payment_id.get()) > Int(0), Global.group_size() == Int(4))    # With receipt, sponsored
            ),
            Seq(
                # Verify sponsor payment at index 0
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].amount() >= Int(0)),  # Can be 0 if just covering fees
                Assert(Or(
                    Gtxn[0].receiver() == actual_payer.load(),  # Payment to user
                    Gtxn[0].receiver() == Global.current_application_address()  # Payment to app
                )),
                Assert(Gtxn[0].rekey_to() == Global.zero_address()),
                Assert(Gtxn[0].close_remainder_to() == Global.zero_address())
            )
        ),
        
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
                # Cheaper, collision-proof receipt keys
                # key = b"p:" || Itob(asset_id) || b":" || Sha256(payment_id)
                key.store(Concat(
                    RECEIPT_PREFIX,
                    Itob(app.state.confio_asset_id),
                    Bytes(":"),
                    Sha256(payment_id.get())
                )),
                key_len.store(Len(key.load())),
                
                # Client must include the receipt box reference
                # Box references are validated implicitly by PyTeal when accessing boxes
                
                # Fixed-size value: payer(32)|recipient(32)|amount(8)|fee(8)|ts(8)|asset_id(8) = 96
                val_len.store(Int(96)),
                
                # If using a receipt, pin and validate the ALGO funding payment
                # Handle both sponsored and non-sponsored cases
                mbr.store(box_mbr_cost(key_len.load(), val_len.load())),
                If(
                    Global.group_size() == Int(3),
                    Seq(
                        # Non-sponsored: MBR payment at index 0
                        Assert(Gtxn[0].type_enum() == TxnType.Payment),
                        Assert(Gtxn[0].sender() == actual_payer.load()),
                        Assert(Gtxn[0].receiver() == Global.current_application_address()),
                        Assert(Gtxn[0].amount() == mbr.load()),  # Exact, not >=
                        Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
                        Assert(Gtxn[0].rekey_to() == Global.zero_address())
                    ),
                    Seq(
                        # Sponsored: MBR payment at index 1 (index 0 is sponsor payment)
                        Assert(Global.group_size() == Int(4)),
                        Assert(Gtxn[1].type_enum() == TxnType.Payment),
                        Assert(Gtxn[1].sender() == actual_payer.load()),
                        Assert(Gtxn[1].receiver() == Global.current_application_address()),
                        Assert(Gtxn[1].amount() == mbr.load()),  # Exact, not >=
                        Assert(Gtxn[1].close_remainder_to() == Global.zero_address()),
                        Assert(Gtxn[1].rekey_to() == Global.zero_address())
                    )
                ),
                
                # Box existence check using hasValue()
                (box_exists := App.box_get(key.load())),
                Assert(Not(box_exists.hasValue())),
                Assert(App.box_create(key.load(), val_len.load())),
                
                # Build and write receipt value in one operation
                receipt_value.store(Concat(
                    actual_payer.load(),                  # 32 bytes: payer
                    recipient.get(),                       # 32 bytes: recipient
                    Itob(payment_amount.load()),          # 8 bytes: amount
                    Itob(fee_amount.load()),              # 8 bytes: fee
                    Itob(Global.latest_timestamp()),      # 8 bytes: timestamp
                    Itob(app.state.confio_asset_id)       # 8 bytes: asset_id
                )),
                Assert(Len(receipt_value.load()) == Int(96)),
                App.box_replace(key.load(), Int(0), receipt_value.load()),
                
                # Increment receipt counter
                app.state.receipt_count.set(app.state.receipt_count.get() + Int(1)),
                
                # Log event for off-chain indexing
                Log(Concat(Bytes("paid:confio:"), Sha256(payment_id.get())))
            )
        ,
            # No receipt: exactly [AXFER, AppCall]
            Assert(Global.group_size() == Int(2))
        ),
        
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
    """Contract is immutable - updates are not allowed"""
    return Reject()

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
        
        # Prevent deletion if receipts exist (would strand MBR)
        Assert(app.state.receipt_count == Int(0)),
        
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