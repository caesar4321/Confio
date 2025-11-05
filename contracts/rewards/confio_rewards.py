#!/usr/bin/env python3
"""
CONFIO Rewards Vault

Stateful application that escrows CONFIO (Algorand ASA) and allows eligible
users to self-claim rewards that were attested off-chain by the Django backend.

Key ideas:
    * Eligibility is stored in boxes keyed by the claimant's address so that
      users do not need to opt into the app ahead of time.
    * The reward amount is computed on-chain from the current presale price
      (read from the existing presale contract) at the moment eligibility is
      written, locking the USD-equivalent rate.
    * Optional referrer payouts are recorded alongside the referee and can be
      claimed exactly once after the referee completes their claim.
    * Backend sponsors every write that creates a new box by attaching a
      payment covering the box minimum balance requirement (MBR).
"""

from pyteal import *


# -----------------------------------------------------------------------------
# Constants & helpers
# -----------------------------------------------------------------------------

CONFIO_DECIMALS = Int(1_000_000)  # ASA has 6 decimal places
ASA_OPT_IN_MBR = Int(100_000)     # microAlgos required to opt-in to an ASA
BOX_KEY_LENGTH = Int(32)          # address length

# Box layout (72 bytes total):
#   0..7   : uint64 - eligible CONFIO amount (micro units)
#   8..15  : uint64 - claimed flag (0 = no, 1 = yes)
#   16..23 : uint64 - referrer CONFIO amount (micro units)
#   24..55 : bytes  - referrer address (32 bytes, zero if none)
#   56..63 : uint64 - referrer claimed flag (0 = no, 1 = yes)
#   64..71 : uint64 - presale round snapshot when eligibility was written
BOX_VALUE_SIZE = Int(72)

AMOUNT_OFFSET = Int(0)
CLAIMED_OFFSET = Int(8)
REF_AMOUNT_OFFSET = Int(16)
REF_ADDRESS_OFFSET = Int(24)
REF_CLAIMED_OFFSET = Int(56)
ROUND_OFFSET = Int(64)


@Subroutine(TealType.uint64)
def box_mbr_cost(key_len: Expr, value_len: Expr) -> Expr:
    """MicroAlgo cost to open a box with the given key/value lengths."""
    return Int(2500) + Int(400) * (key_len + value_len)


# -----------------------------------------------------------------------------
# Contract
# -----------------------------------------------------------------------------

def confio_rewards_app() -> Expr:
    """Build the PyTeal approval program for the CONFIO rewards vault."""

    # Global keys
    ADMIN = Bytes("admin")
    CONFIO_ASA = Bytes("confio_id")
    PRESALE_APP = Bytes("presale")
    SPONSOR = Bytes("sponsor")
    BOOTSTRAPPED = Bytes("boot")
    PAUSED = Bytes("paused")
    TOTAL_ELIGIBLE = Bytes("eligible_sum")
    TOTAL_CLAIMED = Bytes("claimed_sum")
    TOTAL_REF_ELIGIBLE = Bytes("ref_eligible_sum")
    TOTAL_REF_PAID = Bytes("ref_sum")
    ELIGIBLE_COUNT = Bytes("eligible_ct")
    CLAIM_COUNT = Bytes("claim_ct")
    REF_CLAIM_COUNT = Bytes("ref_ct")
    MANUAL_PRICE = Bytes("manual_price")
    MANUAL_ROUND = Bytes("manual_round")
    MANUAL_ACTIVE = Bytes("manual_active")

    @Subroutine(TealType.none)
    def assert_admin() -> Expr:
        return Assert(Txn.sender() == App.globalGet(ADMIN))

    @Subroutine(TealType.uint64)
    def initialize() -> Expr:
        """App creation."""
        confio_id = Btoi(Txn.application_args[0])
        presale_id = Btoi(Txn.application_args[1])
        admin_addr = Txn.application_args[2]
        sponsor_addr = Txn.application_args[3]

        return Seq(
            Assert(Txn.application_args.length() == Int(4)),
            Assert(confio_id > Int(0)),
            Assert(presale_id > Int(0)),
            Assert(Len(admin_addr) == Int(32)),
            Assert(Len(sponsor_addr) == Int(32)),

            App.globalPut(CONFIO_ASA, confio_id),
            App.globalPut(PRESALE_APP, presale_id),
            App.globalPut(ADMIN, admin_addr),
            App.globalPut(SPONSOR, sponsor_addr),
            App.globalPut(BOOTSTRAPPED, Int(0)),
            App.globalPut(PAUSED, Int(0)),
            App.globalPut(TOTAL_ELIGIBLE, Int(0)),
            App.globalPut(TOTAL_CLAIMED, Int(0)),
            App.globalPut(TOTAL_REF_ELIGIBLE, Int(0)),
            App.globalPut(TOTAL_REF_PAID, Int(0)),
            App.globalPut(ELIGIBLE_COUNT, Int(0)),
            App.globalPut(CLAIM_COUNT, Int(0)),
            App.globalPut(REF_CLAIM_COUNT, Int(0)),
            App.globalPut(MANUAL_PRICE, Int(0)),
            App.globalPut(MANUAL_ROUND, Int(0)),
            App.globalPut(MANUAL_ACTIVE, Int(0)),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def bootstrap_vault() -> Expr:
        """Opt the application into the CONFIO ASA (once)."""
        return Seq(
            assert_admin(),
            Assert(App.globalGet(BOOTSTRAPPED) == Int(0)),
            Assert(Global.group_size() >= Int(2)),
            Assert(Gtxn[0].type_enum() == TxnType.Payment),
            Assert(Gtxn[0].receiver() == Global.current_application_address()),
            Assert(Gtxn[0].amount() >= ASA_OPT_IN_MBR + Int(2000)),  # safety buffer
            Assert(Gtxn[0].sender() == App.globalGet(SPONSOR)),

            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(CONFIO_ASA),
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0),
                TxnField.fee: Int(0),
            }),
            InnerTxnBuilder.Submit(),

            App.globalPut(BOOTSTRAPPED, Int(1)),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def mark_eligible() -> Expr:
        """
        Admin-only attestation that records a user's reward allocation.

        Arguments:
            application_args[1]: reward amount denominated in micro cUSD (uint64)
                                 to convert into CONFIO at current presale price.
            application_args[2] (optional): referrer reward in micro CONFIO.
            accounts[0]: user to reward.
            accounts[1] (optional): referrer payout target.
            applications[0]: presale contract ID (must match stored global).
        """
        reward_cusd = ScratchVar(TealType.uint64)
        ref_amount = ScratchVar(TealType.uint64)
        price_value = ScratchVar(TealType.uint64)
        round_value = ScratchVar(TealType.uint64)
        outstanding = ScratchVar(TealType.uint64)
        outstanding_ref = ScratchVar(TealType.uint64)
        confio_reward = ScratchVar(TealType.uint64)
        existing_box_data = ScratchVar(TealType.bytes)
        user_addr = ScratchVar(TealType.bytes)
        ref_addr_for_log = ScratchVar(TealType.bytes)

        presale_id = App.globalGet(PRESALE_APP)
        price_box = App.globalGetEx(presale_id, Bytes("price"))
        round_box = App.globalGetEx(presale_id, Bytes("round"))
        vault_balance = AssetHolding.balance(
            Global.current_application_address(),
            App.globalGet(CONFIO_ASA),
        )
        user_box = App.box_get(user_addr.load())

        return Seq(
            assert_admin(),
            Assert(App.globalGet(PAUSED) == Int(0)),
            Assert(Txn.application_args.length() >= Int(3)),

            user_addr.store(Txn.application_args[2]),
            Assert(Len(user_addr.load()) == Int(32)),

            Assert(Txn.accounts.length() > Int(0)),
            Assert(user_addr.load() != Global.zero_address()),

            reward_cusd.store(Btoi(Txn.application_args[1])),
            Assert(reward_cusd.load() > Int(0)),

            Assert(App.globalGet(MANUAL_ACTIVE) == Int(1)),
            price_value.store(App.globalGet(MANUAL_PRICE)),
            Assert(price_value.load() > Int(0)),
            round_value.store(App.globalGet(MANUAL_ROUND)),

            confio_reward.store(
                WideRatio(
                    [reward_cusd.load(), CONFIO_DECIMALS],
                    [price_value.load()],
                )
            ),
            Assert(confio_reward.load() > Int(0)),

            ref_amount.store(Int(0)),
            If(Txn.application_args.length() >= Int(4)).Then(
                ref_amount.store(Btoi(Txn.application_args[3]))
            ),

            Assert(App.globalGet(BOOTSTRAPPED) == Int(1)),
            Assert(App.globalGet(TOTAL_ELIGIBLE) >= App.globalGet(TOTAL_CLAIMED)),
            Assert(App.globalGet(TOTAL_REF_ELIGIBLE) >= App.globalGet(TOTAL_REF_PAID)),
            outstanding.store(
                App.globalGet(TOTAL_ELIGIBLE) - App.globalGet(TOTAL_CLAIMED)
            ),
            outstanding_ref.store(
                App.globalGet(TOTAL_REF_ELIGIBLE) - App.globalGet(TOTAL_REF_PAID)
            ),

            vault_balance,
            Assert(vault_balance.hasValue()),
            Assert(
                vault_balance.value()
                >= outstanding.load()
                + outstanding_ref.load()
                + confio_reward.load()
                + ref_amount.load()
            ),

            user_box,
            If(user_box.hasValue()).Then(
                Seq(
                    existing_box_data.store(user_box.value()),
                    Assert(
                        Btoi(
                            Extract(
                                existing_box_data.load(),
                                CLAIMED_OFFSET,
                                Int(8),
                            )
                        )
                        == Int(0)
                    ),
                    Assert(
                        Btoi(
                            Extract(
                                existing_box_data.load(),
                                AMOUNT_OFFSET,
                                Int(8),
                            )
                        )
                        == Int(0)
                    ),
                    Assert(
                        Btoi(
                            Extract(
                                existing_box_data.load(),
                                REF_AMOUNT_OFFSET,
                                Int(8),
                            )
                        )
                        == Int(0)
                    ),
                )
            ).Else(
                Seq(
                    Assert(Global.group_size() >= Int(2)),
                    Assert(Gtxn[0].type_enum() == TxnType.Payment),
                    Assert(Gtxn[0].receiver() == Global.current_application_address()),
                    Assert(
                        Gtxn[0].amount()
                        >= box_mbr_cost(BOX_KEY_LENGTH, BOX_VALUE_SIZE)
                    ),
                    Assert(Gtxn[0].sender() == App.globalGet(SPONSOR)),
                    Assert(App.box_create(user_addr.load(), BOX_VALUE_SIZE)),
                    App.box_replace(
                        user_addr.load(), REF_ADDRESS_OFFSET, Global.zero_address()
                    ),
                    App.box_replace(
                        user_addr.load(), REF_AMOUNT_OFFSET, Itob(Int(0))
                    ),
                    App.box_replace(
                        user_addr.load(), REF_CLAIMED_OFFSET, Itob(Int(1))
                    ),
                    App.box_replace(
                        user_addr.load(), CLAIMED_OFFSET, Itob(Int(0))
                    ),
                    App.box_replace(
                        user_addr.load(), ROUND_OFFSET, Itob(Int(0))
                    ),
                )
            ),

            App.box_replace(
                user_addr.load(), AMOUNT_OFFSET, Itob(confio_reward.load())
            ),
            App.box_replace(
                user_addr.load(), CLAIMED_OFFSET, Itob(Int(0))
            ),
            App.box_replace(
                user_addr.load(), ROUND_OFFSET, Itob(round_value.load())
            ),

            ref_addr_for_log.store(Global.zero_address()),
            If(ref_amount.load() > Int(0)).Then(
                Seq(
                    Assert(Txn.accounts.length() > Int(1)),
                    Assert(Txn.accounts[1] != user_addr.load()),
                    Assert(Txn.accounts[1] != Global.zero_address()),
                    App.box_replace(
                        user_addr.load(), REF_ADDRESS_OFFSET, Txn.accounts[1]
                    ),
                    App.box_replace(
                        user_addr.load(),
                        REF_AMOUNT_OFFSET,
                        Itob(ref_amount.load()),
                    ),
                    App.box_replace(
                        user_addr.load(), REF_CLAIMED_OFFSET, Itob(Int(0))
                    ),
                    App.globalPut(
                        TOTAL_REF_ELIGIBLE,
                        App.globalGet(TOTAL_REF_ELIGIBLE) + ref_amount.load(),
                    ),
                    ref_addr_for_log.store(Txn.accounts[1]),
                )
            ).Else(
                Seq(
                    App.box_replace(
                        user_addr.load(),
                        REF_ADDRESS_OFFSET,
                        Global.zero_address(),
                    ),
                    App.box_replace(
                        user_addr.load(), REF_AMOUNT_OFFSET, Itob(Int(0))
                    ),
                    App.box_replace(
                        user_addr.load(), REF_CLAIMED_OFFSET, Itob(Int(1))
                    ),
                    ref_addr_for_log.store(Global.zero_address()),
                )
            ),

            App.globalPut(
                TOTAL_ELIGIBLE,
                App.globalGet(TOTAL_ELIGIBLE) + confio_reward.load(),
            ),
            App.globalPut(
                ELIGIBLE_COUNT,
                App.globalGet(ELIGIBLE_COUNT) + Int(1),
            ),
            Log(
                Concat(
                    Bytes("ELIGIBLE|"),
                    user_addr.load(),
                    Bytes("|"),
                    Itob(confio_reward.load()),
                    Bytes("|"),
                    Itob(round_value.load()),
                    Bytes("|"),
                    ref_addr_for_log.load(),
                    Bytes("|"),
                    Itob(ref_amount.load()),
                )
            ),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def claim_reward() -> Expr:
        """User self-claims their CONFIO allocation."""
        user_addr = Txn.sender()
        user_box = App.box_get(user_addr)
        ref_addr = ScratchVar(TealType.bytes)
        ref_amount = ScratchVar(TealType.uint64)
        ref_claim_flag = ScratchVar(TealType.uint64)
        user_asset = AssetHolding.balance(user_addr, App.globalGet(CONFIO_ASA))
        box_bytes = ScratchVar(TealType.bytes)
        eligible_amount = ScratchVar(TealType.uint64)
        claimed_flag = ScratchVar(TealType.uint64)

        return Seq(
            If(App.globalGet(PAUSED) == Int(1)).Then(
                Seq(Log(Bytes("ERR|PAUSED")), Reject())
            ),
            If(Global.group_size() == Int(1)).Then(
                Assert(Txn.fee() >= Global.min_txn_fee() * Int(2))
            ),
            Assert(App.globalGet(PAUSED) == Int(0)),
            user_box,
            Assert(user_box.hasValue()),
            box_bytes.store(user_box.value()),
            eligible_amount.store(Btoi(Extract(box_bytes.load(), AMOUNT_OFFSET, Int(8)))),
            claimed_flag.store(Btoi(Extract(box_bytes.load(), CLAIMED_OFFSET, Int(8)))),
            ref_amount.store(Btoi(Extract(box_bytes.load(), REF_AMOUNT_OFFSET, Int(8)))),
            ref_claim_flag.store(Btoi(Extract(box_bytes.load(), REF_CLAIMED_OFFSET, Int(8)))),
            ref_addr.store(Extract(box_bytes.load(), REF_ADDRESS_OFFSET, Int(32))),
            Assert(eligible_amount.load() > Int(0)),
            Assert(claimed_flag.load() == Int(0)),

            user_asset,
            If(Not(user_asset.hasValue())).Then(
                Seq(
                    Log(Concat(Bytes("ERR|OPTIN|"), user_addr)),
                    Reject(),
                )
            ),

            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(CONFIO_ASA),
                TxnField.asset_receiver: user_addr,
                TxnField.asset_amount: eligible_amount.load(),
                TxnField.fee: Int(0),
            }),
            InnerTxnBuilder.Submit(),

            App.box_replace(user_addr, AMOUNT_OFFSET, Itob(Int(0))),
            App.box_replace(user_addr, CLAIMED_OFFSET, Itob(Int(1))),
            App.globalPut(TOTAL_CLAIMED, App.globalGet(TOTAL_CLAIMED) + eligible_amount.load()),
            App.globalPut(CLAIM_COUNT, App.globalGet(CLAIM_COUNT) + Int(1)),
            Log(Concat(Bytes("CLAIM|"), user_addr, Bytes("|"), Itob(eligible_amount.load()))),
            If(And(ref_amount.load() > Int(0), ref_claim_flag.load() == Int(0))).Then(
                Seq(
                    If(Txn.accounts.length() > Int(1)).Then(
                        Seq(
                            If(Txn.accounts[1] == ref_addr.load()).Then(
                                Seq(
                                    (ref_balance := AssetHolding.balance(Txn.accounts[1], App.globalGet(CONFIO_ASA))),
                                    ref_balance,
                                    If(ref_balance.hasValue()).Then(
                                        Seq(
                                            InnerTxnBuilder.Begin(),
                                            InnerTxnBuilder.SetFields({
                                                TxnField.type_enum: TxnType.AssetTransfer,
                                                TxnField.xfer_asset: App.globalGet(CONFIO_ASA),
                                                TxnField.asset_receiver: Txn.accounts[1],
                                                TxnField.asset_amount: ref_amount.load(),
                                                TxnField.fee: Int(0),
                                            }),
                                            InnerTxnBuilder.Submit(),
                                            App.box_replace(user_addr, REF_AMOUNT_OFFSET, Itob(Int(0))),
                                            App.box_replace(user_addr, REF_CLAIMED_OFFSET, Itob(Int(1))),
                                            App.globalPut(
                                                TOTAL_REF_PAID,
                                                App.globalGet(TOTAL_REF_PAID) + ref_amount.load(),
                                            ),
                                            App.globalPut(
                                                REF_CLAIM_COUNT,
                                                App.globalGet(REF_CLAIM_COUNT) + Int(1),
                                            ),
                                            Log(
                                                Concat(
                                                    Bytes("REF|"),
                                                    Txn.accounts[1],
                                                    Bytes("|"),
                                                    user_addr,
                                                    Bytes("|"),
                                                    Itob(ref_amount.load()),
                                                )
                                            ),
                                        )
                                    ),
                                )
                            )
                        )
                    )
                )
            ),
            (post_claim_box := App.box_get(user_addr)),
            If(
                And(
                    post_claim_box.hasValue(),
                    Btoi(Extract(post_claim_box.value(), REF_AMOUNT_OFFSET, Int(8))) == Int(0),
                    Btoi(Extract(post_claim_box.value(), REF_CLAIMED_OFFSET, Int(8))) == Int(1),
                )
            ).Then(
                Pop(App.box_delete(user_addr))
            ),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def claim_referrer() -> Expr:
        """Referrer claims their bonus after the referee has claimed."""
        referee = Txn.accounts[0]
        ref_box = App.box_get(referee)
        box_bytes = ScratchVar(TealType.bytes)
        ref_amount = ScratchVar(TealType.uint64)
        ref_claimed = ScratchVar(TealType.uint64)
        stored_addr = ScratchVar(TealType.bytes)
        claimed_flag = ScratchVar(TealType.uint64)
        ref_asset = AssetHolding.balance(Txn.sender(), App.globalGet(CONFIO_ASA))

        return Seq(
            Assert(Txn.accounts.length() > Int(0)),
            If(App.globalGet(PAUSED) == Int(1)).Then(
                Seq(Log(Bytes("ERR|PAUSED")), Reject())
            ),
            If(Global.group_size() == Int(1)).Then(
                Assert(Txn.fee() >= Global.min_txn_fee() * Int(2))
            ),
            Assert(App.globalGet(PAUSED) == Int(0)),
            ref_box,
            Assert(ref_box.hasValue()),
            box_bytes.store(ref_box.value()),
            ref_amount.store(Btoi(Extract(box_bytes.load(), REF_AMOUNT_OFFSET, Int(8)))),
            ref_claimed.store(Btoi(Extract(box_bytes.load(), REF_CLAIMED_OFFSET, Int(8)))),
            claimed_flag.store(Btoi(Extract(box_bytes.load(), CLAIMED_OFFSET, Int(8)))),
            Assert(ref_amount.load() > Int(0)),
            Assert(ref_claimed.load() == Int(0)),
            Assert(claimed_flag.load() == Int(1)),

            stored_addr.store(Extract(box_bytes.load(), REF_ADDRESS_OFFSET, Int(32))),
            Assert(stored_addr.load() == Txn.sender()),

            ref_asset,
            If(Not(ref_asset.hasValue())).Then(
                Seq(
                    Log(Concat(Bytes("ERR|REF_OPTIN|"), Txn.sender())),
                    Reject(),
                )
            ),

            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(CONFIO_ASA),
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: ref_amount.load(),
                TxnField.fee: Int(0),
            }),
            InnerTxnBuilder.Submit(),

            App.box_replace(referee, REF_AMOUNT_OFFSET, Itob(Int(0))),
            App.box_replace(referee, REF_CLAIMED_OFFSET, Itob(Int(1))),
            App.globalPut(TOTAL_REF_PAID, App.globalGet(TOTAL_REF_PAID) + ref_amount.load()),
            App.globalPut(REF_CLAIM_COUNT, App.globalGet(REF_CLAIM_COUNT) + Int(1)),
            Log(Concat(Bytes("REF|"), Txn.sender(), Bytes("|"), referee, Bytes("|"), Itob(ref_amount.load()))),
            (post_ref_box := App.box_get(referee)),
            If(
                And(
                    post_ref_box.hasValue(),
                    Btoi(Extract(post_ref_box.value(), AMOUNT_OFFSET, Int(8))) == Int(0),
                    Btoi(Extract(post_ref_box.value(), CLAIMED_OFFSET, Int(8))) == Int(1),
                    Btoi(Extract(post_ref_box.value(), REF_AMOUNT_OFFSET, Int(8))) == Int(0),
                    Btoi(Extract(post_ref_box.value(), REF_CLAIMED_OFFSET, Int(8))) == Int(1),
                )
            ).Then(
                Pop(App.box_delete(referee))
            ),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def admin_withdraw() -> Expr:
        """Admin withdraws CONFIO from the vault."""
        amount = ScratchVar(TealType.uint64)
        destination = ScratchVar(TealType.bytes)

        return Seq(
            assert_admin(),
            Assert(Txn.application_args.length() >= Int(2)),
            amount.store(Btoi(Txn.application_args[1])),
            Assert(amount.load() > Int(0)),
            If(Txn.accounts.length() > Int(0)).Then(
                Seq(
                    Assert(Txn.accounts[0] != Global.zero_address()),
                    destination.store(Txn.accounts[0]),
                )
            ).Else(
                destination.store(Txn.sender())
            ),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(CONFIO_ASA),
                TxnField.asset_receiver: destination.load(),
                TxnField.asset_amount: amount.load(),
                TxnField.fee: Int(0),
            }),
            InnerTxnBuilder.Submit(),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def withdraw_algo() -> Expr:
        """Admin sweeps excess ALGO held by the app account."""
        available = ScratchVar(TealType.uint64)
        dest = ScratchVar(TealType.bytes)
        balance_val = ScratchVar(TealType.uint64)
        min_balance_val = ScratchVar(TealType.uint64)

        return Seq(
            assert_admin(),
            Assert(Txn.accounts.length() > Int(0)),
            Assert(Txn.accounts[0] == Global.current_application_address()),
            balance_val.store(Balance(Txn.accounts[0])),
            min_balance_val.store(MinBalance(Txn.accounts[0])),
            Assert(balance_val.load() >= min_balance_val.load()),
            available.store(balance_val.load() - min_balance_val.load()),
            If(Txn.accounts.length() > Int(1)).Then(
                Seq(
                    Assert(Txn.accounts[1] != Global.zero_address()),
                    dest.store(Txn.accounts[1]),
                )
            ).Else(
                dest.store(Txn.sender())
            ),
            If(available.load() > Int(0)).Then(
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.Payment,
                        TxnField.receiver: dest.load(),
                        TxnField.amount: available.load(),
                        TxnField.fee: Int(0),
                    }),
                    InnerTxnBuilder.Submit(),
                )
            ),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def update_presale() -> Expr:
        """Rotate the presale app ID (admin only)."""
        new_id = Btoi(Txn.application_args[1])
        return Seq(
            assert_admin(),
            Assert(new_id > Int(0)),
            App.globalPut(PRESALE_APP, new_id),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def update_sponsor() -> Expr:
        """Rotate the sponsor address (admin only)."""
        new_sponsor = Txn.application_args[1]
        return Seq(
            assert_admin(),
            Assert(Len(new_sponsor) == Int(32)),
            App.globalPut(SPONSOR, new_sponsor),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def set_price_override() -> Expr:
        price = ScratchVar(TealType.uint64)
        round_id = ScratchVar(TealType.uint64)
        return Seq(
            assert_admin(),
            Assert(Txn.application_args.length() >= Int(2)),
            price.store(Btoi(Txn.application_args[1])),
            Assert(price.load() > Int(0)),
            round_id.store(Int(0)),
            If(Txn.application_args.length() >= Int(3)).Then(
                round_id.store(Btoi(Txn.application_args[2]))
            ),
            App.globalPut(MANUAL_PRICE, price.load()),
            App.globalPut(MANUAL_ROUND, round_id.load()),
            App.globalPut(MANUAL_ACTIVE, Int(1)),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def clear_price_override() -> Expr:
        return Seq(
            assert_admin(),
            App.globalPut(MANUAL_ACTIVE, Int(0)),
            App.globalPut(MANUAL_PRICE, Int(0)),
            App.globalPut(MANUAL_ROUND, Int(0)),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def pause_program() -> Expr:
        return Seq(
            assert_admin(),
            App.globalPut(PAUSED, Int(1)),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def resume_program() -> Expr:
        return Seq(
            assert_admin(),
            App.globalPut(PAUSED, Int(0)),
            Int(1),
        )

    on_create = initialize()

    return Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.DeleteApplication, Int(0)],
        [Txn.on_completion() == OnComplete.UpdateApplication, Int(0)],
        [Txn.on_completion() == OnComplete.CloseOut, Int(1)],
        [Txn.on_completion() == OnComplete.OptIn, Int(1)],
        [Txn.application_args.length() == Int(0), Int(0)],
        [Txn.application_args[0] == Bytes("bootstrap"), bootstrap_vault()],
        [Txn.application_args[0] == Bytes("mark_eligible"), mark_eligible()],
        [Txn.application_args[0] == Bytes("claim"), claim_reward()],
        [Txn.application_args[0] == Bytes("claim_referrer"), claim_referrer()],
        [Txn.application_args[0] == Bytes("withdraw"), admin_withdraw()],
        [Txn.application_args[0] == Bytes("withdraw_algo"), withdraw_algo()],
        [Txn.application_args[0] == Bytes("set_presale"), update_presale()],
        [Txn.application_args[0] == Bytes("set_sponsor"), update_sponsor()],
        [Txn.application_args[0] == Bytes("set_price_override"), set_price_override()],
        [Txn.application_args[0] == Bytes("clear_price_override"), clear_price_override()],
        [Txn.application_args[0] == Bytes("pause"), pause_program()],
        [Txn.application_args[0] == Bytes("resume"), resume_program()],
        [Int(1), Int(0)],
    )


def compile_confio_rewards() -> str:
    """Helper to compile the approval program."""
    program = confio_rewards_app()
    return compileTeal(program, Mode.Application, version=8)


if __name__ == "__main__":
    print(compile_confio_rewards())
