"""
Confío Payroll Escrow - per-business vault and per-business allowlist

Key behaviors:
- Single app, but each business has its own vault balance and delegate allowlist.
- Boxes:
  * Allowlist: key = business_addr || delegate_addr -> uint64(1)
  * Vault: key = b"VAULT" || business_addr -> uint64(balance in base units)
  * Receipt: key = payroll_item_id (string) -> recipient|net|fee|gross|sender|timestamp
- Externals:
  * setup_asset(asset_id) [admin] - sets payroll_asset and opts the app into it.
  * set_fee_recipient(addr) [admin].
  * set_business_delegates(business_account, add[], remove[]) [admin or business].
  * fund_business(business_account, amount) - grouped with ASA transfer business->app; increments vault.
  * payout(recipient, net_amount, payroll_item_id):
      - expects business account in Txn.accounts[0]
      - allowlist check on business||sender
      - require vault >= gross; decrement vault; inner transfers net to recipient, fee to fee_recipient.
  * withdraw_vault(business_account, amount, recipient) [business only]:
      - business can withdraw (partial or full) from its own vault
      - decrements vault; sends funds to recipient
  * admin_withdraw_vault(business_account, amount, recipient) [admin only]:
      - admin emergency withdrawal from any business vault
      - use for migrations, emergencies, or recovering stuck funds
"""

from typing import Final
from pyteal import *
from beaker import *

FEE_BPS = Int(90)  # 0.9%
BASIS_POINTS = Int(10000)


class PayrollState:
    admin: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.bytes, default=Bytes(""), descr="Contract admin/owner")
    fee_recipient: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.bytes, default=Bytes(""), descr="Fee recipient")
    sponsor_address: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.bytes, default=Bytes(""), descr="Sponsor address for fee-bumping/app calls")
    cusd_fees_balance: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.uint64, default=Int(0), descr="Accumulated payroll fees (ASA units)")
    total_fees_collected: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.uint64, default=Int(0), descr="Total fees ever collected")
    payroll_asset: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.uint64, default=Int(0), descr="ASA used for payroll (e.g., cUSD)")
    is_paused: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.uint64, default=Int(0), descr="Pause switch")


app = Application("PayrollEscrow", state=PayrollState(), descr="Confio payroll escrow per-business vault")


@app.create
def create():
    return Seq(
        app.state.admin.set(Txn.sender()),
        app.state.fee_recipient.set(Txn.sender()),
        app.state.sponsor_address.set(Txn.sender()),
        Approve()
    )


@app.external
def setup_asset(asset_id: abi.Uint64):
    """Admin sets payroll asset and opts the app into it."""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(app.state.payroll_asset == Int(0)),
        Assert(asset_id.get() > Int(0)),
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        app.state.payroll_asset.set(asset_id.get()),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        Approve()
    )


@app.external
def set_fee_recipient(addr: abi.Address):
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        app.state.fee_recipient.set(addr.get()),
        Approve()
    )


@app.external
def set_admin(addr: abi.Address):
    """Rotate admin to a new address"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(addr.get() != Global.zero_address()),
        Assert(addr.get() != Global.current_application_address()),
        app.state.admin.set(addr.get()),
        Approve()
    )

@app.external
def set_sponsor_address(addr: abi.Address):
    """Admin sets/updates sponsor address for sponsored app calls."""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(addr.get() != Global.zero_address()),
        app.state.sponsor_address.set(addr.get()),
        Approve()
    )


@app.external
def set_business_delegates(business_account: abi.Address, add: abi.DynamicArray[abi.Address], remove: abi.DynamicArray[abi.Address]):
    """Manage delegates for a business. Admin or that business account."""
    i = ScratchVar(TealType.uint64)
    biz_bytes = ScratchVar(TealType.bytes)
    del_bytes = ScratchVar(TealType.bytes)
    result = ScratchVar(TealType.uint64)
    allow_val = Itob(Int(1))
    return Seq(
        biz_bytes.store(business_account.get()),
        Assert(Or(Txn.sender() == app.state.admin.get(), Txn.sender() == biz_bytes.load())),
        For(i.store(Int(0)), i.load() < add.length(), i.store(i.load() + Int(1))).Do(
            Seq(
                (tmp := abi.Address()).set(add[i.load()]),
                del_bytes.store(tmp.get()),
                App.box_put(Concat(biz_bytes.load(), del_bytes.load()), allow_val)
            )
        ),
        For(i.store(Int(0)), i.load() < remove.length(), i.store(i.load() + Int(1))).Do(
            Seq(
                (tmp := abi.Address()).set(remove[i.load()]),
                del_bytes.store(tmp.get()),
                result.store(App.box_delete(Concat(biz_bytes.load(), del_bytes.load())))
            )
        ),
        Approve()
    )


@app.external
def fund_business(business_account: abi.Address, amount: abi.Uint64):
    """
    Increase business vault by amount. Expected group: [axfer business->app, app call]
    """
    asset = app.state.payroll_asset
    vault_key = ScratchVar(TealType.bytes)
    has_val = ScratchVar(TealType.uint64)
    val = ScratchVar(TealType.uint64)
    existing_bytes = ScratchVar(TealType.bytes)
    return Seq(
        Assert(asset != Int(0)),
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(1)),
        Assert(Gtxn[0].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[0].xfer_asset() == asset),
        Assert(Gtxn[0].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[0].asset_amount() == amount.get()),
        Assert(Gtxn[0].sender() == business_account.get()),
        vault_key.store(Concat(Bytes("VAULT"), business_account.get())),
        (existing_tuple := App.box_get(vault_key.load())),
        has_val.store(existing_tuple.hasValue()),
        existing_bytes.store(existing_tuple.value()),
        val.store(If(has_val.load(), Btoi(existing_bytes.load()), Int(0))),
        val.store(val.load() + amount.get()),
        App.box_put(vault_key.load(), Itob(val.load())),
        Approve()
    )


def _ceil_gross(net: Expr) -> Expr:
    numerator = (net * BASIS_POINTS) + (BASIS_POINTS - FEE_BPS - Int(1))
    return numerator / (BASIS_POINTS - FEE_BPS)


@app.external
def payout(recipient: abi.Address, net_amount: abi.Uint64, payroll_item_id: abi.String):
    asset = app.state.payroll_asset
    gross = ScratchVar(TealType.uint64)
    fee = ScratchVar(TealType.uint64)
    ts = ScratchVar(TealType.uint64)
    biz_addr = ScratchVar(TealType.bytes)
    rcpt = ScratchVar(TealType.bytes)
    receipt_data = ScratchVar(TealType.bytes)
    vault_key = ScratchVar(TealType.bytes)
    vault_amt = ScratchVar(TealType.uint64)

    return Seq(
        Assert(asset != Int(0)),
        Assert(app.state.is_paused == Int(0)),
        Assert(Txn.accounts.length() >= Int(1)),
        biz_addr.store(Txn.accounts[1]),
        (delegate_check := App.box_get(Concat(biz_addr.load(), Txn.sender()))),
        Assert(
            Or(
                delegate_check.hasValue(),
                Txn.sender() == app.state.sponsor_address.get()
            )
        ),
        ts.store(Global.latest_timestamp()),
        gross.store(_ceil_gross(net_amount.get())),
        fee.store(gross.load() - net_amount.get()),
        # Check vault balance
        vault_key.store(Concat(Bytes("VAULT"), biz_addr.load())),
        (vault_tuple := App.box_get(vault_key.load())),
        Assert(vault_tuple.hasValue()),
        vault_amt.store(Btoi(vault_tuple.value())),
        Assert(vault_amt.load() >= gross.load()),
        # Decrement vault
        vault_amt.store(vault_amt.load() - gross.load()),
        App.box_put(vault_key.load(), Itob(vault_amt.load())),
        # Recipient bytes
        rcpt.store(recipient.get()),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset,
            TxnField.asset_receiver: rcpt.load(),
            TxnField.asset_amount: net_amount.get(),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        # Accumulate fee in contract (track balance + total)
        app.state.cusd_fees_balance.set(app.state.cusd_fees_balance.get() + fee.load()),
        app.state.total_fees_collected.set(app.state.total_fees_collected.get() + fee.load()),
        receipt_data.store(
            Concat(
                rcpt.load(),
                Itob(net_amount.get()),
                Itob(fee.load()),
                Itob(gross.load()),
                Txn.sender(),
                Itob(ts.load())
            )
        ),
        App.box_put(payroll_item_id.get(), receipt_data.load()),
        Approve()
    )


@app.external
def withdraw_vault(business_account: abi.Address, amount: abi.Uint64, recipient: abi.Address):
    """
    Withdraw funds from business vault. Only the business account can withdraw its own vault.
    Amount can be partial or full. Recipient typically the business account itself.
    """
    asset = app.state.payroll_asset
    vault_key = ScratchVar(TealType.bytes)
    vault_amt = ScratchVar(TealType.uint64)
    existing_bytes = ScratchVar(TealType.bytes)

    return Seq(
        Assert(asset != Int(0)),
        # Only the business account can withdraw from its own vault
        Assert(
            Or(
                Txn.sender() == business_account.get(),
                Txn.sender() == app.state.sponsor_address.get()
            )
        ),
        Assert(amount.get() > Int(0)),
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),  # Base + inner tx

        # Read vault balance
        vault_key.store(Concat(Bytes("VAULT"), business_account.get())),
        (vault_tuple := App.box_get(vault_key.load())),
        Assert(vault_tuple.hasValue()),
        existing_bytes.store(vault_tuple.value()),
        vault_amt.store(Btoi(existing_bytes.load())),

        # Ensure sufficient balance
        Assert(vault_amt.load() >= amount.get()),

        # Decrement vault
        vault_amt.store(vault_amt.load() - amount.get()),
        App.box_put(vault_key.load(), Itob(vault_amt.load())),

        # Send funds to recipient
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset,
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_amount: amount.get(),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        Approve()
    )


@app.external
def admin_withdraw_vault(business_account: abi.Address, amount: abi.Uint64, recipient: abi.Address):
    """
    Admin emergency withdrawal from any business vault.
    Use for migrations, emergencies, or recovering stuck funds.
    """
    asset = app.state.payroll_asset
    vault_key = ScratchVar(TealType.bytes)
    vault_amt = ScratchVar(TealType.uint64)
    existing_bytes = ScratchVar(TealType.bytes)

    return Seq(
        Assert(asset != Int(0)),
        # Only admin can use this function
        Assert(Txn.sender() == app.state.admin.get()),
        Assert(amount.get() > Int(0)),
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),

        # Read vault balance
        vault_key.store(Concat(Bytes("VAULT"), business_account.get())),
        (vault_tuple := App.box_get(vault_key.load())),
        Assert(vault_tuple.hasValue()),
        existing_bytes.store(vault_tuple.value()),
        vault_amt.store(Btoi(existing_bytes.load())),

        # Ensure sufficient balance
        Assert(vault_amt.load() >= amount.get()),

        # Decrement vault
        vault_amt.store(vault_amt.load() - amount.get()),
        App.box_put(vault_key.load(), Itob(vault_amt.load())),

        # Send funds to recipient
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset,
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_amount: amount.get(),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        Approve()
    )


@app.external
def withdraw_fees(recipient: abi.Address):
    """
    Admin withdraws accumulated payroll fees (single asset) to a recipient (default: fee_recipient).
    Sends current cusd_fees_balance and resets it to 0.
    """
    asset = app.state.payroll_asset
    fee_bal = ScratchVar(TealType.uint64)
    target = ScratchVar(TealType.bytes)

    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(asset != Int(0)),
        fee_bal.store(app.state.cusd_fees_balance.get()),
        Assert(fee_bal.load() > Int(0)),
        # Decide recipient
        target.store(recipient.get()),
        If(target.load() == Global.zero_address()).Then(target.store(app.state.fee_recipient.get())),
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),  # inner xfer
        # Reset balance then pay out
        app.state.cusd_fees_balance.set(Int(0)),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset,
            TxnField.asset_receiver: target.load(),
            TxnField.asset_amount: fee_bal.load(),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        Approve()
    )


if __name__ == "__main__":
    app.build().export("./artifacts")
