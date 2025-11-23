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
"""

from typing import Final
from pyteal import *
from beaker import *

FEE_BPS = Int(90)  # 0.9%
BASIS_POINTS = Int(10000)


class PayrollState:
    admin: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.bytes, default=Bytes(""), descr="Contract admin/owner")
    fee_recipient: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.bytes, default=Bytes(""), descr="Fee recipient")
    payroll_asset: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.uint64, default=Int(0), descr="ASA used for payroll (e.g., cUSD)")
    is_paused: Final[GlobalStateValue] = GlobalStateValue(stack_type=TealType.uint64, default=Int(0), descr="Pause switch")


app = Application("PayrollEscrow", state=PayrollState(), descr="Confio payroll escrow per-business vault")


@app.create
def create():
    return Seq(
        app.state.admin.set(Txn.sender()),
        app.state.fee_recipient.set(Txn.sender()),
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
        biz_addr.store(Txn.accounts[0]),
        (delegate_check := App.box_get(Concat(biz_addr.load(), Txn.sender()))),
        Assert(delegate_check.hasValue()),
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
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset,
            TxnField.asset_receiver: app.state.fee_recipient.get(),
            TxnField.asset_amount: fee.load(),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
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


if __name__ == "__main__":
    app.build().export("./artifacts")
