"""
Payroll Transaction Builder

Builds unsigned Algorand transactions for the payroll escrow contract:
- Computes gross/fee for a target net amount (0.9% skim) so recipients get full net.
- Prepares single-recipient payout app calls (delegate-signed).
"""

from typing import Dict, Optional
import base64
from algosdk import transaction, encoding, logic
from algosdk.transaction import SuggestedParams
from algosdk.abi import Method, AddressType, UintType, StringType, ArrayDynamicType
from algosdk.v2client import algod
from django.conf import settings
try:
    from algosdk.transaction import BoxReference  # available in newer SDK versions
except Exception:  # pragma: no cover
    BoxReference = None


class PayrollTransactionBuilder:
    """Builds payout transaction groups for the payroll escrow contract."""

    def __init__(self, network: str = "testnet"):
        self.network = network
        self.algod_address = settings.ALGORAND_ALGOD_ADDRESS
        self.algod_token = settings.ALGORAND_ALGOD_TOKEN
        self.algod_client = algod.AlgodClient(self.algod_token, self.algod_address)

        config = settings.BLOCKCHAIN_CONFIG
        self.payroll_app_id = config["ALGORAND_PAYROLL_APP_ID"]
        self.payroll_asset_id = config["ALGORAND_PAYROLL_ASSET_ID"]
        self.sponsor_address = config.get("ALGORAND_SPONSOR_ADDRESS")
        self._fee_recipient: Optional[str] = None

        # ABI method definitions
        self.payout_method = Method.from_signature("payout(address,uint64,string)void")
        self._addr_type = AddressType()
        self._u64_type = UintType(64)
        self._str_type = StringType()
        self._set_delegates_method = Method.from_signature("set_business_delegates(address,address[],address[])void")

    def calculate_amounts_for_net(self, net_amount: int) -> Dict[str, int]:
        """Return gross and fee needed to deliver `net_amount` (base units)."""
        fee_bps = 90
        basis_points = 10000
        numerator = net_amount * basis_points + (basis_points - fee_bps - 1)
        gross = numerator // (basis_points - fee_bps)
        fee = gross - net_amount
        return {"gross_amount": gross, "fee_amount": fee, "net_amount": net_amount}

    def build_payout_app_call(
        self,
        delegate_address: str,
        business_address: str,
        recipient_address: str,
        net_amount: int,
        payroll_item_id: str,
        suggested_params: Optional[SuggestedParams] = None,
        note: Optional[bytes] = None,
    ) -> transaction.ApplicationNoOpTxn:
        """
        Build the single AppCall needed for a payroll payout.
        Caller (delegate) signs and pays fees; contract disburses from escrow.
        """
        sp = suggested_params or self.algod_client.suggested_params()
        # Two inner transactions => require at least 3x min fee
        sp.flat_fee = True
        sp.fee = max(sp.min_fee * 3, sp.fee)

        # Fetch fee recipient from app global state (cached)
        if not self._fee_recipient:
            try:
                info = self.algod_client.application_info(self.payroll_app_id)
                for kv in info.get("params", {}).get("global-state", []):
                    key = kv.get("key")
                    if key and base64.b64decode(key).decode(errors="ignore") == "fee_recipient":
                        val = kv.get("value", {})
                        if val.get("bytes"):
                            self._fee_recipient = encoding.encode_address(
                                base64.b64decode(val["bytes"])
                            )
                            break
            except Exception:
                self._fee_recipient = None

        business_bytes = encoding.decode_address(business_address)
        delegate_bytes = encoding.decode_address(delegate_address)
        allow_key = business_bytes + delegate_bytes
        sender_key = delegate_bytes + delegate_bytes

        app_args = [
            self.payout_method.get_selector(),
            self._addr_type.encode(recipient_address),
            self._u64_type.encode(net_amount),
            self._str_type.encode(payroll_item_id),
        ]

        vault_key = b"VAULT" + encoding.decode_address(business_address)
        # Use current app (index=0) for boxes to keep mobile decoding happy; foreign_apps left empty
        if BoxReference:
            boxes = [
                BoxReference(0, allow_key),
                BoxReference(0, sender_key),
                BoxReference(0, payroll_item_id.encode("utf-8")),
                BoxReference(0, vault_key),
            ]
        else:
            boxes = [
                (0, allow_key),
                (0, sender_key),
                (0, payroll_item_id.encode("utf-8")),
                (0, vault_key),
            ]

        # Only include business (for vault/allowlist) and recipient (inner tx) + optional fee recipient
        accounts = [business_address, recipient_address]
        if self._fee_recipient and self._fee_recipient not in accounts:
            accounts.append(self._fee_recipient)

        txn = transaction.ApplicationNoOpTxn(
            sender=delegate_address,
            sp=sp,
            index=self.payroll_app_id,
            app_args=app_args,
            boxes=boxes,
            accounts=accounts,
            foreign_assets=[self.payroll_asset_id],
            foreign_apps=[],
            note=note,
        )
        return txn

    def build_fund_business_group(
        self,
        business_account: str,
        amount_base: int,
        suggested_params: Optional[SuggestedParams] = None,
        note: Optional[bytes] = None,
    ) -> list[transaction.Transaction]:
        """
        Build group [axfer business->app, app call fund_business].
        amount_base is in base units of payroll asset (1e6).
        """
        sp = suggested_params or self.algod_client.suggested_params()
        sp.flat_fee = True
        sp.fee = max(sp.min_fee, sp.fee)

        app_addr = encoding.decode_address(logic.get_application_address(self.payroll_app_id))

        axfer = transaction.AssetTransferTxn(
            sender=business_account,
            sp=sp,
            receiver=logic.get_application_address(self.payroll_app_id),
            amt=amount_base,
            index=self.payroll_asset_id,
            note=note,
        )

        app_args = [
            Method.from_signature("fund_business(address,uint64)void").get_selector(),
            self._addr_type.encode(business_account),
            self._u64_type.encode(amount_base),
        ]
        app_call = transaction.ApplicationNoOpTxn(
            sender=business_account,
            sp=sp,
            index=self.payroll_app_id,
            app_args=app_args,
            accounts=[business_account],
            foreign_assets=[self.payroll_asset_id],
            note=note,
        )

        gid = transaction.calculate_group_id([axfer, app_call])
        axfer.group = gid
        app_call.group = gid
        return [axfer, app_call]

    def build_withdrawal_app_call(
        self,
        business_account: str,
        amount_base: int,
        recipient_address: Optional[str] = None,
        suggested_params: Optional[SuggestedParams] = None,
        note: Optional[bytes] = None,
    ) -> transaction.ApplicationNoOpTxn:
        """
        Build a single app call for the on-chain withdraw_vault method.

        The business signs and pays fees (no sponsor). Amount is in base units of the
        payroll asset (1e6). Recipient defaults to the business address.
        """
        sp = suggested_params or self.algod_client.suggested_params()
        sp.flat_fee = True
        # Contract requires fee >= 2x min fee because of inner asset xfer
        sp.fee = max(sp.min_fee * 2, sp.fee)

        recipient = recipient_address or business_account

        method = Method.from_signature("withdraw_vault(address,uint64,address)void")
        app_args = [
            method.get_selector(),
            self._addr_type.encode(business_account),
            self._u64_type.encode(amount_base),
            self._addr_type.encode(recipient),
        ]

        vault_key = b"VAULT" + encoding.decode_address(business_account)
        boxes = [(0, vault_key)] if not BoxReference else [BoxReference(0, vault_key)]

        txn = transaction.ApplicationNoOpTxn(
            sender=business_account,
            sp=sp,
            index=self.payroll_app_id,
            app_args=app_args,
            accounts=[recipient] if recipient != business_account else [],
            foreign_assets=[self.payroll_asset_id],
            boxes=boxes,
            note=note,
        )
        return txn

    def build_set_business_delegates(
        self,
        business_account: str,
        add: list[str],
        remove: list[str],
        suggested_params: Optional[SuggestedParams] = None,
        note: Optional[bytes] = None,
    ) -> transaction.ApplicationNoOpTxn:
        """
        Build the AppCall to set_business_delegates. Sender must be the business account (or admin).
        Boxes: one per add/remove using key business||delegate.
        """
        sp = suggested_params or self.algod_client.suggested_params()
        sp.flat_fee = True
        sp.fee = max(sp.min_fee * 2, sp.fee)

        biz_bytes = encoding.decode_address(business_account)
        add_boxes = [(self.payroll_app_id, biz_bytes + encoding.decode_address(a)) for a in add]
        remove_boxes = [(self.payroll_app_id, biz_bytes + encoding.decode_address(r)) for r in remove]

        app_args = [
          self._set_delegates_method.get_selector(),
          self._addr_type.encode(business_account),
          ArrayDynamicType(self._addr_type).encode([encoding.decode_address(a) for a in add]),
          ArrayDynamicType(self._addr_type).encode([encoding.decode_address(r) for r in remove]),
        ]

        txn = transaction.ApplicationNoOpTxn(
            sender=business_account,
            sp=sp,
            index=self.payroll_app_id,
            app_args=app_args,
            boxes=add_boxes + remove_boxes,
            note=note,
        )
        return txn

    def build_fund_business(
        self,
        business_account: str,
        amount: int,
        suggested_params: Optional[SuggestedParams] = None,
    ) -> list[transaction.Transaction]:
        """
        Build the group [axfer business->app, appcall fund_business].
        Amount in base units.
        """
        sp = suggested_params or self.algod_client.suggested_params()
        sp.flat_fee = True
        sp.fee = max(sp.min_fee * 2, sp.fee)

        asset_id = self.payroll_asset_id
        app_addr = transaction.logic.get_application_address(self.payroll_app_id)

        axfer = transaction.AssetTransferTxn(
            sender=business_account,
            sp=sp,
            receiver=app_addr,
            amt=amount,
            index=asset_id,
        )

        appcall = transaction.ApplicationNoOpTxn(
            sender=business_account,
            sp=sp,
            index=self.payroll_app_id,
            app_args=[
                Method.from_signature("fund_business(address,uint64)void").get_selector(),
                encoding.decode_address(business_account),
                UintType(64).encode(amount),
            ],
            accounts=[business_account],
            foreign_assets=[asset_id],
        )

        return [axfer, appcall]

    def build_fund_group(
        self,
        business_account: str,
        amount_base: int,
        suggested_params: Optional[SuggestedParams] = None,
        algo_amount: int = 1_000_000,  # Default 1 ALGO for MBR
    ) -> list[transaction.Transaction]:
        """
        Build the atomic group for fund_business:
        [0] ALGO payment business -> app (for vault MBR)
        [1] ASA transfer business -> app
        [2] App call fund_business(business_account, amount)
        """
        sp = suggested_params or self.algod_client.suggested_params()
        sp.flat_fee = True
        sp.fee = max(sp.min_fee, sp.fee)

        app_addr = transaction.logic.get_application_address(self.payroll_app_id)
        
        # ALGO payment for vault MBR
        algo_payment = transaction.PaymentTxn(
            sender=business_account,
            sp=sp,
            receiver=app_addr,
            amt=algo_amount,
            note=b"Payroll vault MBR funding"
        )
        
        # cUSD asset transfer
        axfer = transaction.AssetTransferTxn(
            sender=business_account,
            sp=sp,
            receiver=app_addr,
            amt=amount_base,
            index=self.payroll_asset_id,
        )

        sp_app = self.algod_client.suggested_params()
        sp_app.flat_fee = True
        sp_app.fee = max(sp_app.min_fee * 2, sp_app.fee)

        method = Method.from_signature("fund_business(address,uint64)void")
        app_args = [
            method.get_selector(),
            self._addr_type.encode(business_account),
            self._u64_type.encode(amount_base),
        ]
        vault_key = b"VAULT" + encoding.decode_address(business_account)

        app_call = transaction.ApplicationNoOpTxn(
            sender=business_account,
            sp=sp_app,
            index=self.payroll_app_id,
            app_args=app_args,
            boxes=[(self.payroll_app_id, vault_key)],
        )

        transaction.assign_group_id([algo_payment, axfer, app_call])
        return [algo_payment, axfer, app_call]
