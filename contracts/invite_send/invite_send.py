"""
Invite & Send Contract for Confío - Algorand Implementation
Escrow-based invitation system with 7-day reclaim period
Website: https://confio.lat

Usage and group structures:
- Create: [Payment(sponsor→app, amount=box MBR), AXFER(inviter→app), AppCall(sponsor)]
  The app calculates MBR dynamically from key/value sizes and requires the payment to cover it.
- Claim: AppCall(claim_invitation) standalone, or grouped with a 0-amount pay-yourself Payment to add fee budget.
  Fee-bump format: [Payment(sender→sender, amount=0), AppCall(claim_invitation)]
- Reclaim: AppCall(reclaim_invitation) standalone, or grouped with a 0-amount pay-yourself Payment to add fee budget.
  Fee-bump format: [Payment(sender→sender, amount=0), AppCall(reclaim_invitation)]

Notes:
- On claim/reclaim the original invite box is deleted, a compact receipt box is created, and the original MBR minus the receipt’s MBR is refunded to the inviter.
- Receipts enable on-chain auditability without additional funding.
"""

from pyteal import *
from beaker import *
from typing import Final

# Constants
RECLAIM_PERIOD_SECONDS = Int(604800)  # 7 days in seconds
MAX_INVITE_ID_LEN = Int(64)          # cap box key size to control MBR
MAX_MESSAGE_LEN = Int(256)           # cap message to control MBR
RECEIPT_PREFIX = Bytes("r:")        # receipt box key prefix
ASA_OPT_IN_MBR = Int(100000)         # ~0.1 ALGO per ASA opt-in
MIN_ASSET_AMOUNT = Int(1000)         # Min amount to prevent dust invites (6 decimals)

# Box MBR = 2500 + 400 * (key_len + value_len)
@Subroutine(TealType.uint64)
def box_mbr_cost(key_len: Expr, value_len: Expr) -> Expr:
    return Int(2500) + Int(400) * (key_len + value_len)

# Security helper: No rekey/close for payment transactions
@Subroutine(TealType.uint64)
def no_rekey_close_pay(idx: Expr) -> Expr:
    return And(
        Gtxn[idx].rekey_to() == Global.zero_address(),
        Gtxn[idx].close_remainder_to() == Global.zero_address()
    )

# Security helper: No rekey/close/clawback for asset transfers
@Subroutine(TealType.uint64)
def no_rekey_close_axfer(idx: Expr) -> Expr:
    return And(
        Gtxn[idx].rekey_to() == Global.zero_address(),
        Gtxn[idx].asset_close_to() == Global.zero_address(),
        # forbid clawback-mode transfers
        Gtxn[idx].asset_sender() == Global.zero_address()
    )

class InviteSendState:
    """Global state for invite & send system"""
    
    admin: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Admin address"
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
    need = ScratchVar(TealType.uint64)
    over = ScratchVar(TealType.uint64)
    
    return Seq(
        # Require funding in the same group: [Payment(admin→app), AppCall(setup_assets)]
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].sender() == Txn.sender()),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        # Need min-balance for 2 ASA opt-ins
        Assert(Gtxn[0].amount() >= ASA_OPT_IN_MBR * Int(2)),
        # No rekey/close on payment
        Assert(no_rekey_close_pay(Int(0))),
        
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.cusd_asset_id == Int(0),
                app.state.confio_asset_id == Int(0)
            )
        ),
        app.state.cusd_asset_id.set(cusd_id.get()),
        app.state.confio_asset_id.set(confio_id.get()),
        
        # Opt-in to both assets (fee = 0)
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
        
        # (Optional) auto-refund overpay so no ALGO is accidentally trapped
        need.store(ASA_OPT_IN_MBR * Int(2)),
        over.store(Gtxn[0].amount() - need.load()),
        If(over.load() > Int(0)).Then(Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: Txn.sender(),
                TxnField.amount: over.load(),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit()
        )),
        
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
    msg_len = ScratchVar(TealType.uint64)
    key_len = ScratchVar(TealType.uint64)
    value_len = ScratchVar(TealType.uint64)
    mbr_cost = ScratchVar(TealType.uint64)
    over = ScratchVar(TealType.uint64)
    actual_inviter = ScratchVar(TealType.bytes)
    
    return Seq(
        # Determine actual inviter (could be sponsor calling on behalf of user)
        If(
            And(
                app.state.sponsor_address.get() != Bytes(""),
                Txn.sender() == app.state.sponsor_address.get(),
                Txn.accounts.length() > Int(0)
            ),
            actual_inviter.store(Txn.accounts[0]),  # User passed as account reference
            actual_inviter.store(Txn.sender())  # Direct call from user
        ),
        
        # Check system state and asset configuration
        Assert(app.state.is_paused == Int(0)),
        Assert(Or(app.state.cusd_asset_id != Int(0), app.state.confio_asset_id != Int(0))),
        
        # This AppCall must not have rekey
        Assert(Txn.rekey_to() == Global.zero_address()),

        # Enforce bounded sizes (protect MBR)
        key_len.store(Len(invitation_id.get())),
        msg_len.store(Len(message.get())),
        Assert(And(key_len.load() > Int(0), key_len.load() <= MAX_INVITE_ID_LEN)),
        Assert(msg_len.load() <= MAX_MESSAGE_LEN),
        
        # Disallow invitation IDs that collide with receipt prefix "r:"
        Assert(Or(
            key_len.load() < Int(2),
            Extract(invitation_id.get(), Int(0), Int(2)) != RECEIPT_PREFIX
        )),

        # ABI arg must reference a group AXFER that sends to the app FROM the inviter
        Assert(asset_transfer.get().asset_receiver() == Global.current_application_address()),
        Assert(asset_transfer.get().asset_amount() >= MIN_ASSET_AMOUNT),  # Min amount to prevent dust
        Assert(asset_transfer.get().sender() == actual_inviter.load()),
        Assert(Or(
            asset_transfer.get().xfer_asset() == app.state.cusd_asset_id,
            asset_transfer.get().xfer_asset() == app.state.confio_asset_id
        )),

        # Compute box value length first
        value_len.store(Int(32 + 8 + 8 + 8 + 8 + 1 + 1 + 2) + msg_len.load()),
        
        # Group shape & funding: Support both sponsored and non-sponsored
        # Non-sponsored: [Payment(inviter→app), AXFER, AppCall]
        # Sponsored: [Payment(sponsor→user/app), Payment(inviter→app), AXFER, AppCall]
        Assert(Or(
            Global.group_size() == Int(3),  # Non-sponsored
            Global.group_size() == Int(4)   # Sponsored
        )),
        
        # Determine indices based on group size
        If(Global.group_size() == Int(4),
            Seq(
                # Sponsored: verify sponsor payment at index 0
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].amount() >= Int(0)),  # Can be 0 if just covering fees
                Assert(Or(
                    Gtxn[0].receiver() == actual_inviter.load(),  # Payment to user
                    Gtxn[0].receiver() == Global.current_application_address()  # Payment to app
                )),
                Assert(no_rekey_close_pay(Int(0))),
                
                # MBR payment at index 1 from sponsor
                Assert(Gtxn[1].type_enum() == TxnType.Payment),
                Assert(Gtxn[1].sender() == app.state.sponsor_address.get()),  # Sponsor pays MBR
                Assert(Gtxn[1].receiver() == Global.current_application_address()),
                Assert(no_rekey_close_pay(Int(1))),
                
                # AXFER at index 2
                Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
                Assert(Gtxn[2].asset_receiver() == Global.current_application_address()),
                Assert(Gtxn[2].sender() == actual_inviter.load()),
                Assert(Gtxn[2].xfer_asset() == asset_transfer.get().xfer_asset()),
                Assert(Gtxn[2].asset_amount() == asset_transfer.get().asset_amount()),
                Assert(no_rekey_close_axfer(Int(2))),
                
                # App call at index 3
                Assert(Txn.group_index() == Int(3)),
                
                # Store MBR calculations
                mbr_cost.store(box_mbr_cost(key_len.load(), value_len.load())),
                Assert(Gtxn[1].amount() >= mbr_cost.load()),
                over.store(Gtxn[1].amount() - mbr_cost.load())
            ),
            Seq(
                # Non-sponsored: original structure
                # MBR payment at index 0
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].sender() == app.state.sponsor_address.get()),  # Sponsor pays MBR
                Assert(Gtxn[0].receiver() == Global.current_application_address()),
                Assert(no_rekey_close_pay(Int(0))),
                
                # AXFER at index 1
                Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
                Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
                Assert(Gtxn[1].sender() == actual_inviter.load()),
                Assert(Gtxn[1].xfer_asset() == asset_transfer.get().xfer_asset()),
                Assert(Gtxn[1].asset_amount() == asset_transfer.get().asset_amount()),
                Assert(no_rekey_close_axfer(Int(1))),
                
                # App call at index 2
                Assert(Txn.group_index() == Int(2)),
                
                # Store MBR calculations
                mbr_cost.store(box_mbr_cost(key_len.load(), value_len.load())),
                Assert(Gtxn[0].amount() >= mbr_cost.load()),
                over.store(Gtxn[0].amount() - mbr_cost.load())
            )
        ),

        # Invitation must be new
        (existing_box := App.box_get(invitation_id.get())),
        Assert(Not(existing_box.hasValue())),

        # Create and populate box
        Assert(App.box_create(invitation_id.get(), value_len.load())),
        
        # Immediately refund any overpay (prevents trapped ALGO)
        # Note: over.store() is already set in the group validation above
        If(over.load() > Int(0)).Then(Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: actual_inviter.load(),
                TxnField.amount: over.load(),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit()
        )),
        App.box_replace(invitation_id.get(), Int(0), actual_inviter.load()),
        App.box_replace(invitation_id.get(), Int(32), Itob(asset_transfer.get().asset_amount())),
        App.box_replace(invitation_id.get(), Int(40), Itob(asset_transfer.get().xfer_asset())),
        App.box_replace(invitation_id.get(), Int(48), Itob(Global.latest_timestamp())),
        App.box_replace(invitation_id.get(), Int(56), Itob(Global.latest_timestamp() + RECLAIM_PERIOD_SECONDS)),
        App.box_replace(invitation_id.get(), Int(64), Bytes("base16", "00")),
        App.box_replace(invitation_id.get(), Int(65), Bytes("base16", "00")),
        App.box_replace(invitation_id.get(), Int(66), Extract(Itob(msg_len.load()), Int(6), Int(2))),
        App.box_replace(invitation_id.get(), Int(68), message.get()),

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
    val_len = ScratchVar(TealType.uint64)
    key_len2 = ScratchVar(TealType.uint64)
    receipt_key = ScratchVar(TealType.bytes)
    receipt_key_len = ScratchVar(TealType.uint64)
    receipt_val_len = ScratchVar(TealType.uint64)
    orig_mbr = ScratchVar(TealType.uint64)
    receipt_mbr = ScratchVar(TealType.uint64)
    refund = ScratchVar(TealType.uint64)
    
    return Seq(
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
        
        # Load invitation data
        (invitation_data := App.box_get(invitation_id.get())),
        Assert(invitation_data.hasValue()),
        
        sender.store(Extract(invitation_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(invitation_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(invitation_data.value(), Int(40), Int(8)))),
        expires_at.store(Btoi(Extract(invitation_data.value(), Int(56), Int(8)))),
        is_claimed.store(Extract(invitation_data.value(), Int(64), Int(1))),
        is_reclaimed.store(Extract(invitation_data.value(), Int(65), Int(1))),
        
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
        
        # Ensure recipient is opted in to the asset and valid
        Assert(recipient.get() != Global.zero_address()),
        Assert(recipient.get() != Global.current_application_address()),  # Prevent sending to app itself
        Assert(recipient.get() != sender.load()),  # Prevent self-claiming (backend verification flow guard)
        (rec_hold := AssetHolding.balance(recipient.get(), asset_id.load())),
        Assert(rec_hold.hasValue()),
        
        # Defensive: re-assert asset_id is one of configured assets
        Assert(Or(
            asset_id.load() == app.state.cusd_asset_id,
            asset_id.load() == app.state.confio_asset_id
        )),
        
        # Assert the app actually has the funds before sending
        (app_hold := AssetHolding.balance(Global.current_application_address(), asset_id.load())),
        Assert(app_hold.hasValue()),
        Assert(app_hold.value() >= amount.load()),

        # Transfer funds to recipient
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_amount: amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),

        # Delete box, write compact receipt, and refund remaining MBR to inviter
        val_len.store(Len(invitation_data.value())),
        key_len2.store(Len(invitation_id.get())),
        Assert(App.box_delete(invitation_id.get())),

        # Create receipt box: key = "r:" + invitation_id, value = status(8) | asset_id(8) | amount(8) | ts(8)
        receipt_key.store(Concat(RECEIPT_PREFIX, invitation_id.get())),
        receipt_key_len.store(Len(receipt_key.load())),
        receipt_val_len.store(Int(8 + 8 + 8 + 8)),
        (existing_receipt := App.box_get(receipt_key.load())),
        Assert(Not(existing_receipt.hasValue())),
        Assert(App.box_create(receipt_key.load(), receipt_val_len.load())),
        App.box_replace(receipt_key.load(), Int(0), Itob(Int(1))),  # status = claimed (8 bytes)
        App.box_replace(receipt_key.load(), Int(8), Itob(asset_id.load())),
        App.box_replace(receipt_key.load(), Int(16), Itob(amount.load())),
        App.box_replace(receipt_key.load(), Int(24), Itob(Global.latest_timestamp())),

        # Refund original MBR minus receipt MBR
        orig_mbr.store(box_mbr_cost(key_len2.load(), val_len.load())),
        receipt_mbr.store(box_mbr_cost(receipt_key_len.load(), receipt_val_len.load())),
        # Safety margin check to prevent underflow
        Assert(orig_mbr.load() >= receipt_mbr.load()),
        refund.store(orig_mbr.load() - receipt_mbr.load()),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: sender.load(),
            TxnField.amount: refund.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
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
    val_len = ScratchVar(TealType.uint64)
    key_len2 = ScratchVar(TealType.uint64)
    receipt_key = ScratchVar(TealType.bytes)
    receipt_key_len = ScratchVar(TealType.uint64)
    receipt_val_len = ScratchVar(TealType.uint64)
    orig_mbr = ScratchVar(TealType.uint64)
    receipt_mbr = ScratchVar(TealType.uint64)
    refund = ScratchVar(TealType.uint64)
    
    return Seq(
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
        
        # Load invitation data
        (invitation_data := App.box_get(invitation_id.get())),
        Assert(invitation_data.hasValue()),
        
        sender.store(Extract(invitation_data.value(), Int(0), Int(32))),
        amount.store(Btoi(Extract(invitation_data.value(), Int(32), Int(8)))),
        asset_id.store(Btoi(Extract(invitation_data.value(), Int(40), Int(8)))),
        expires_at.store(Btoi(Extract(invitation_data.value(), Int(56), Int(8)))),
        is_claimed.store(Extract(invitation_data.value(), Int(64), Int(1))),
        is_reclaimed.store(Extract(invitation_data.value(), Int(65), Int(1))),
        
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
        
        # Defensive: re-assert asset_id is one of configured assets
        Assert(Or(
            asset_id.load() == app.state.cusd_asset_id,
            asset_id.load() == app.state.confio_asset_id
        )),
        
        # Assert the app actually has the funds before sending
        (app_hold := AssetHolding.balance(Global.current_application_address(), asset_id.load())),
        Assert(app_hold.hasValue()),
        Assert(app_hold.value() >= amount.load()),
        
        # Return funds to sender
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.load(),
            TxnField.asset_receiver: sender.load(),
            TxnField.asset_amount: amount.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),

        # Delete box, write compact receipt, and refund remaining MBR to inviter
        val_len.store(Len(invitation_data.value())),
        key_len2.store(Len(invitation_id.get())),
        Assert(App.box_delete(invitation_id.get())),

        # Create receipt box: key = "r:" + invitation_id, value = status(8) | asset_id(8) | amount(8) | ts(8)
        receipt_key.store(Concat(RECEIPT_PREFIX, invitation_id.get())),
        receipt_key_len.store(Len(receipt_key.load())),
        receipt_val_len.store(Int(8 + 8 + 8 + 8)),
        (existing_receipt := App.box_get(receipt_key.load())),
        Assert(Not(existing_receipt.hasValue())),
        Assert(App.box_create(receipt_key.load(), receipt_val_len.load())),
        App.box_replace(receipt_key.load(), Int(0), Itob(Int(2))),  # status = reclaimed
        App.box_replace(receipt_key.load(), Int(8), Itob(asset_id.load())),
        App.box_replace(receipt_key.load(), Int(16), Itob(amount.load())),
        App.box_replace(receipt_key.load(), Int(24), Itob(Global.latest_timestamp())),

        # Refund original MBR minus receipt MBR
        orig_mbr.store(box_mbr_cost(key_len2.load(), val_len.load())),
        receipt_mbr.store(box_mbr_cost(receipt_key_len.load(), receipt_val_len.load())),
        # Safety margin check to prevent underflow
        Assert(orig_mbr.load() >= receipt_mbr.load()),
        refund.store(orig_mbr.load() - receipt_mbr.load()),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: sender.load(),
            TxnField.amount: refund.load(),
            TxnField.fee: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
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

@app.external
def set_sponsor(sponsor: abi.Address):
    """Admin sets or updates the sponsor address for sponsored transactions"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        app.state.sponsor_address.set(sponsor.get()),
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
    
    receipt_key = ScratchVar(TealType.bytes)
    
    return Seq(
        (bx := App.box_get(invitation_id.get())),
        If(bx.hasValue()).Then(Seq(
            exists.set(True),
            is_claimed.set(Extract(bx.value(), Int(64), Int(1)) == Bytes("base16", "01")),
            is_expired.set(Global.latest_timestamp() > Btoi(Extract(bx.value(), Int(56), Int(8))))
        )).Else(Seq(
            # Fall back to receipt
            receipt_key.store(Concat(RECEIPT_PREFIX, invitation_id.get())),
            (rb := App.box_get(receipt_key.load())),
            If(rb.hasValue()).Then(Seq(
                exists.set(False),  # Original doesn't exist, but receipt does
                # status: 1=claimed, 2=reclaimed
                is_claimed.set(Btoi(Extract(rb.value(), Int(0), Int(8))) == Int(1)),
                is_expired.set(True)  # if a receipt exists, the invite is no longer active
            )).Else(Seq(
                exists.set(False),
                is_claimed.set(False),
                is_expired.set(False)
            ))
        )),
        output.set(exists, is_claimed, is_expired)
    )

@app.external(read_only=True)
def get_receipt(
    invitation_id: abi.String,
    *,
    output: abi.Tuple5[abi.Bool, abi.Uint64, abi.Uint64, abi.Uint64, abi.Uint64]
):
    """
    Read compact receipt for an invitation id.
    Returns: (exists, status_code, asset_id, amount, timestamp)
    status_code: 1 = claimed, 2 = reclaimed
    """
    exists = abi.Bool()
    status_code = abi.Uint64()
    asset_id = abi.Uint64()
    amount = abi.Uint64()
    ts = abi.Uint64()

    key = ScratchVar(TealType.bytes)
    
    return Seq(
        key.store(Concat(RECEIPT_PREFIX, invitation_id.get())),
        (bx := App.box_get(key.load())),
        If(bx.hasValue(),
           Seq(
               exists.set(True),
               status_code.set(Btoi(Extract(bx.value(), Int(0), Int(8)))),
               asset_id.set(Btoi(Extract(bx.value(), Int(8), Int(8)))),
               amount.set(Btoi(Extract(bx.value(), Int(16), Int(8)))),
               ts.set(Btoi(Extract(bx.value(), Int(24), Int(8))))
           ),
           Seq(
               exists.set(False),
               status_code.set(Int(0)),
               asset_id.set(Int(0)),
               amount.set(Int(0)),
               ts.set(Int(0))
           )
        ),
        output.set(exists, status_code, asset_id, amount, ts)
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

@app.external
def set_admin(new_admin: abi.Address):
    """Admin rotation for operational flexibility"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(new_admin.get() != Global.zero_address()),
        app.state.admin.set(new_admin.get()),
        Approve()
    )

@app.delete
def delete():
    """Only admin can delete - prevent destroying app while value is locked"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(app.state.total_cusd_locked == Int(0)),
        Assert(app.state.total_confio_locked == Int(0)),
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
