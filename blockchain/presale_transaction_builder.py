"""
Presale Transaction Builder
Builds sponsored transaction groups for CONFIO presale purchases via the
presale application (contracts/presale).

Group layout (fully sponsored):
  [0] Payment sponsor->sponsor amount=0 (fee bump for the whole group)
  [1] AXFER user->app cUSD amount
  [2] AppCall (sender = sponsor) app_args=['buy'], accounts=[user]

All user-facing transactions require zero fees; the sponsor covers group fees.
"""
import base64
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.conf import settings

from algosdk import encoding as algo_encoding, mnemonic, transaction
from algosdk.logic import get_application_address
from algosdk.transaction import PaymentTxn, AssetTransferTxn, ApplicationNoOpTxn, SuggestedParams

from .algorand_account_manager import AlgorandAccountManager

logger = logging.getLogger(__name__)


@dataclass
class PresaleConfig:
    app_id: int
    cusd_asset_id: int
    sponsor_address: str
    sponsor_mnemonic: Optional[str]


class PresaleTransactionBuilder:
    def __init__(self):
        # Resolve config from settings/env (no hard-coded values here)
        app_id = getattr(settings, 'ALGORAND_PRESALE_APP_ID', None)
        if not app_id:
            # Fallback to raw env var used in deploy scripts/checklist
            import os
            app_id = os.environ.get('PRESALE_APP_ID')
        try:
            app_id_int = int(app_id) if app_id is not None else 0
        except Exception:
            app_id_int = 0

        self.config = PresaleConfig(
            app_id=app_id_int,
            cusd_asset_id=AlgorandAccountManager.CUSD_ASSET_ID,
            sponsor_address=AlgorandAccountManager.SPONSOR_ADDRESS,
            sponsor_mnemonic=AlgorandAccountManager.SPONSOR_MNEMONIC,
        )

        # Basic validation logging (don’t crash here; let callers handle)
        if not self.config.app_id:
            logger.warning('Presale app id not configured (ALGORAND_PRESALE_APP_ID/PRESALE_APP_ID)')
        if not self.config.cusd_asset_id:
            logger.warning('cUSD asset id not configured (ALGORAND_CUSD_ASSET_ID)')

        from algosdk.v2client import algod
        self.algod = algod.AlgodClient(
            AlgorandAccountManager.ALGOD_TOKEN,
            AlgorandAccountManager.ALGOD_ADDRESS,
        )

    def _check_user_opted_in_app(self, user_address: str) -> bool:
        try:
            info = self.algod.account_info(user_address)
            for ls in info.get('apps-local-state', []) or []:
                if int(ls.get('id') or 0) == int(self.config.app_id):
                    return True
        except Exception as e:
            logger.warning(f"Failed to check app opt-in for {user_address}: {e}")
        return False

    def build_buy_group(self, user_address: str, cusd_amount_base: int) -> Dict[str, Any]:
        """
        Build the sponsored 3-txn group for buying CONFIO with cUSD.

        Args:
            user_address: buyer’s Algorand address (must be opted into app id)
            cusd_amount_base: amount in base units (6 decimals)

        Returns:
            Dict with success flag and transaction pack:
              - sponsor_transactions: list of {index, txn, signed}
              - transactions_to_sign: list with the user AXFER txn (base64)
              - group_id: base64 gid
        """
        if not self.config.app_id or not self.config.cusd_asset_id:
            return {"success": False, "error": "presale_not_configured"}

        # Ensure user is opted into the presale app
        if not self._check_user_opted_in_app(user_address):
            return {
                "success": False,
                "error": "requires_presale_app_optin",
                "app_id": self.config.app_id,
            }

        params = self.algod.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        # Addresses
        app_address = get_application_address(self.config.app_id)

        # Check user balance vs min-balance; fund shortfall if needed
        try:
            acct = self.algod.account_info(user_address)
            current_balance = int(acct.get('amount') or 0)
            min_balance = int(acct.get('min-balance') or 0)
            # User must at least meet current MBR; fees are fully sponsored elsewhere
            # Keep a small 50k buffer to reduce flapping if MBR nudges up
            target = max(min_balance, 0) + 50_000
            funding_needed = max(target - current_balance, 0)
            logger.info(
                f"[PRESALE] MBR check user={user_address} bal={current_balance} min={min_balance} "
                f"target={target} fund={funding_needed}"
            )
        except Exception:
            # Conservative fallback top-up if account query fails
            funding_needed = 200_000
            logger.warning(f"[PRESALE] account_info failed; default funding_needed={funding_needed}")

        # [0] Sponsor payment (MBR funding if needed, otherwise self-payment) and fee
        # Contract now expects each txn to cover its base fee; AppCall carries extra
        sp0 = SuggestedParams(
            fee=min_fee * 1,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        sponsor_bump = PaymentTxn(
            sender=self.config.sponsor_address,
            sp=sp0,
            receiver=user_address if funding_needed > 0 else self.config.sponsor_address,
            amt=int(funding_needed),
            note=b"CONFIO presale sponsor",
        )
        logger.info(
            f"[PRESALE] Sponsor bump fee={sp0.fee} recv={'user' if funding_needed>0 else 'sponsor'} amt={int(funding_needed)}"
        )

        # [1] User -> app cUSD transfer (fee 0; sponsored)
        sp1 = SuggestedParams(
            fee=0,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        cusd_axfer = AssetTransferTxn(
            sender=user_address,
            sp=sp1,
            receiver=app_address,
            amt=int(cusd_amount_base),
            index=int(self.config.cusd_asset_id),
        )

        # [2] Sponsor AppCall to buy – carries >=2× fee budget (sponsor covers)
        sp2 = SuggestedParams(
            fee=min_fee * 2,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        app_call = ApplicationNoOpTxn(
            sender=self.config.sponsor_address,
            sp=sp2,
            index=int(self.config.app_id),
            app_args=[b"buy"],
            accounts=[user_address],  # passed so contract can attribute purchase to user
        )

        # Group and (optionally) sign sponsor txns
        gid = transaction.calculate_group_id([sponsor_bump, cusd_axfer, app_call])
        sponsor_bump.group = gid
        cusd_axfer.group = gid
        app_call.group = gid

        sponsor_signed_0 = None
        sponsor_signed_2 = None
        if self.config.sponsor_mnemonic:
            try:
                sk = mnemonic.to_private_key(self.config.sponsor_mnemonic)
                sponsor_signed_0 = algo_encoding.msgpack_encode(sponsor_bump.sign(sk))
                sponsor_signed_2 = algo_encoding.msgpack_encode(app_call.sign(sk))
            except Exception as e:
                logger.warning(f"Failed to pre-sign sponsor txns: {e}")
                sponsor_signed_0 = None
                sponsor_signed_2 = None

        pack = {
            "success": True,
            "sponsor_transactions": [
                {"index": 0, "txn": algo_encoding.msgpack_encode(sponsor_bump), "signed": sponsor_signed_0},
                {"index": 2, "txn": algo_encoding.msgpack_encode(app_call), "signed": sponsor_signed_2},
            ],
            "transactions_to_sign": [
                {"index": 1, "txn": algo_encoding.msgpack_encode(cusd_axfer), "message": "User cUSD payment"}
            ],
            "group_id": base64.b64encode(gid).decode(),
        }
        return pack

    def build_app_opt_in(self, user_address: str) -> Dict[str, Any]:
        """
        Build SPONSORED opt-in for the presale application (local state opt-in).
        Group: [0] sponsor 0-ALGO self-pay with fee>=1*min, [1] ApplicationOptIn (user) fee>=1*min
        """
        if not self.config.app_id:
            return {"success": False, "error": "presale_not_configured"}

        # If already opted in, short-circuit
        if self._check_user_opted_in_app(user_address):
            return {"success": True, "already_opted_in": True, "transactions_to_sign": [], "sponsor_transactions": []}

        params = self.algod.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        # [0] Sponsor fee covers both txns (pooling) since user opt-in is fee=0
        sp0 = SuggestedParams(
            fee=min_fee * 2,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        sponsor_bump = PaymentTxn(
            sender=self.config.sponsor_address,
            sp=sp0,
            receiver=self.config.sponsor_address,
            amt=0,
            note=b"Presale app opt-in fee bump",
        )

        # [1] User ApplicationOptInTx with fee=0 (strictly sponsored)
        sp1 = SuggestedParams(
            fee=0,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        app_opt_in = transaction.ApplicationOptInTxn(
            sender=user_address,
            sp=sp1,
            index=int(self.config.app_id),
        )

        gid = transaction.calculate_group_id([sponsor_bump, app_opt_in])
        sponsor_bump.group = gid
        app_opt_in.group = gid

        sponsor_signed_0 = None
        if self.config.sponsor_mnemonic:
            try:
                sk = mnemonic.to_private_key(self.config.sponsor_mnemonic)
                sponsor_signed_0 = algo_encoding.msgpack_encode(sponsor_bump.sign(sk))
            except Exception as e:
                logger.warning(f"Failed to pre-sign sponsor opt-in bump: {e}")
                sponsor_signed_0 = None

        return {
            "success": True,
            "sponsor_transactions": [
                {"index": 0, "txn": algo_encoding.msgpack_encode(sponsor_bump), "signed": sponsor_signed_0},
            ],
            "transactions_to_sign": [
                {"index": 1, "txn": algo_encoding.msgpack_encode(app_opt_in), "message": "User app opt-in"}
            ],
            "group_id": base64.b64encode(gid).decode(),
        }

    def build_claim_group(self, user_address: str) -> Dict[str, Any]:
        """
        Build a fully sponsored claim group for unlocked presale tokens.

        Group layout:
          [0] Payment user->user amount=0 fee=0 (user signature witness)
          [1] AppCall (sender=sponsor) app_args=['claim'] accounts=[user] fee>=2*min
        """
        if not self.config.app_id:
            return {"success": False, "error": "presale_not_configured"}

        # Suggested params
        params = self.algod.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        # [0] User witness 0-ALGO payment (fee=0; sponsored)
        sp0 = SuggestedParams(
            fee=0,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        user_witness = PaymentTxn(
            sender=user_address,
            sp=sp0,
            receiver=user_address,
            amt=0,
            note=b"CONFIO presale claim witness",
        )

        # [1] Sponsor AppCall to claim – covers fees incl. inner xfer
        sp1 = SuggestedParams(
            fee=min_fee * 2,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        app_call = ApplicationNoOpTxn(
            sender=self.config.sponsor_address,
            sp=sp1,
            index=int(self.config.app_id),
            app_args=[b"claim"],
            accounts=[user_address],
        )

        # Group
        gid = transaction.calculate_group_id([user_witness, app_call])
        user_witness.group = gid
        app_call.group = gid

        sponsor_signed_1 = None
        if self.config.sponsor_mnemonic:
            try:
                sk = mnemonic.to_private_key(self.config.sponsor_mnemonic)
                sponsor_signed_1 = algo_encoding.msgpack_encode(app_call.sign(sk))
            except Exception as e:
                logger.warning(f"Failed to pre-sign sponsor claim app call: {e}")
                sponsor_signed_1 = None

        return {
            "success": True,
            "sponsor_transactions": [
                {"index": 1, "txn": algo_encoding.msgpack_encode(app_call), "signed": sponsor_signed_1},
            ],
            "transactions_to_sign": [
                {"index": 0, "txn": algo_encoding.msgpack_encode(user_witness), "message": "User claim witness"}
            ],
            "group_id": base64.b64encode(gid).decode(),
        }
