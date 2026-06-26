import base64
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import msgpack
from algosdk import encoding as algo_encoding, mnemonic, transaction
from algosdk.abi import Method, StringType
from algosdk.logic import get_application_address
from algosdk.transaction import ApplicationNoOpTxn, AssetTransferTxn, SuggestedParams
from django.conf import settings

from .algorand_account_manager import AlgorandAccountManager
from .kms_manager import get_kms_signer_from_settings

logger = logging.getLogger(__name__)


@dataclass
class HumanitarianConfig:
    app_id: int
    cusd_asset_id: int
    sponsor_address: str
    sponsor_mnemonic: Optional[str]


class HumanitarianTransactionBuilder:
    def __init__(self, app_id: int | None = None):
        configured_app_id = app_id or getattr(settings, 'ALGORAND_HUMANITARIAN_APP_ID', None)
        try:
            app_id_int = int(configured_app_id or 0)
        except Exception:
            app_id_int = 0

        self.config = HumanitarianConfig(
            app_id=app_id_int,
            cusd_asset_id=AlgorandAccountManager.CUSD_ASSET_ID,
            sponsor_address=AlgorandAccountManager.SPONSOR_ADDRESS,
            sponsor_mnemonic=getattr(AlgorandAccountManager, 'SPONSOR_MNEMONIC', None),
        )

        self.sponsor_signer = None
        try:
            self.sponsor_signer = get_kms_signer_from_settings()
            if (
                self.sponsor_signer.address
                and self.config.sponsor_address
                and self.sponsor_signer.address != self.config.sponsor_address
            ):
                logger.warning(
                    "KMS sponsor address %s differs from configured %s; using KMS address",
                    self.sponsor_signer.address,
                    self.config.sponsor_address,
                )
                self.config.sponsor_address = self.sponsor_signer.address
        except Exception:
            self.sponsor_signer = None

        from algosdk.v2client import algod
        self.algod = algod.AlgodClient(
            AlgorandAccountManager.ALGOD_TOKEN,
            AlgorandAccountManager.ALGOD_ADDRESS,
        )

    def _sign_sponsor(self, txn):
        if self.sponsor_signer:
            try:
                return self.sponsor_signer.sign_transaction(txn)
            except Exception as e:
                logger.warning("Failed to sign humanitarian sponsor txn via KMS: %s", e)
        if self.config.sponsor_mnemonic:
            try:
                sk = mnemonic.to_private_key(self.config.sponsor_mnemonic)
                return txn.sign(sk)
            except Exception as e:
                logger.warning("Failed to sign humanitarian sponsor txn via mnemonic: %s", e)
        return None

    def build_donation_group(self, user_address: str, cusd_amount_base: int, donation_ref: str) -> Dict[str, Any]:
        if not self.config.app_id or not self.config.cusd_asset_id:
            return {"success": False, "error": "humanitarian_not_configured"}
        if not self.config.sponsor_address:
            return {"success": False, "error": "sponsor_not_configured"}
        if cusd_amount_base <= 0:
            return {"success": False, "error": "invalid_amount"}

        params = self.algod.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000
        app_address = get_application_address(self.config.app_id)

        sp0 = SuggestedParams(
            fee=0,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        donation = AssetTransferTxn(
            sender=user_address,
            sp=sp0,
            receiver=app_address,
            amt=int(cusd_amount_base),
            index=int(self.config.cusd_asset_id),
        )

        sp1 = SuggestedParams(
            fee=min_fee * 2,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        donate_method = Method.from_signature("donate(axfer,string)void")
        app_call = ApplicationNoOpTxn(
            sender=self.config.sponsor_address,
            sp=sp1,
            index=int(self.config.app_id),
            app_args=[
                donate_method.get_selector(),
                StringType().encode(str(donation_ref or '')[:64]),
            ],
            foreign_assets=[int(self.config.cusd_asset_id)],
        )

        gid = transaction.calculate_group_id([donation, app_call])
        donation.group = gid
        app_call.group = gid

        sponsor_signed = self._sign_sponsor(app_call)
        sponsor_signed_b64 = algo_encoding.msgpack_encode(sponsor_signed) if sponsor_signed else None

        return {
            "success": True,
            "sponsor_transactions": [
                {"index": 1, "txn": algo_encoding.msgpack_encode(app_call), "signed": sponsor_signed_b64},
            ],
            "transactions_to_sign": [
                {
                    "index": 0,
                    "txn": base64.b64encode(msgpack.packb(donation.dictify(), use_bin_type=True)).decode(),
                    "message": "Humanitarian cUSD donation",
                }
            ],
            "group_id": base64.b64encode(gid).decode(),
            "app_address": app_address,
        }
