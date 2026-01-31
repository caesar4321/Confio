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
import msgpack
from algosdk.logic import get_application_address
from algosdk.transaction import PaymentTxn, AssetTransferTxn, ApplicationNoOpTxn, SuggestedParams

from .algorand_account_manager import AlgorandAccountManager
from .kms_manager import get_kms_signer_from_settings

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
            sponsor_mnemonic=getattr(AlgorandAccountManager, 'SPONSOR_MNEMONIC', None),
        )

        # Resolve KMS signer if available
        self.sponsor_signer = None
        try:
            self.sponsor_signer = get_kms_signer_from_settings()
            # Align sponsor address if mismatched
            if self.sponsor_signer.address and self.config.sponsor_address and self.sponsor_signer.address != self.config.sponsor_address:
                logger.warning(
                    "KMS sponsor address %s differs from configured %s; using KMS address",
                    self.sponsor_signer.address,
                    self.config.sponsor_address,
                )
                self.config.sponsor_address = self.sponsor_signer.address
        except Exception:
            self.sponsor_signer = None

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

    def _sign_sponsor(self, txn):
        """Sign a sponsor transaction using KMS if available, else mnemonic."""
        if self.sponsor_signer:
            try:
                return self.sponsor_signer.sign_transaction(txn)
            except Exception as e:
                logger.warning(f"Failed to sign sponsor txn via KMS: {e}")
        if self.config.sponsor_mnemonic:
            try:
                sk = mnemonic.to_private_key(self.config.sponsor_mnemonic)
                return txn.sign(sk)
            except Exception as e:
                logger.warning(f"Failed to sign sponsor txn via mnemonic: {e}")
        return None

    def _check_user_opted_in_app(self, user_address: str) -> bool:
        try:
            info = self.algod.account_info(user_address)
            for ls in info.get('apps-local-state', []) or []:
                if int(ls.get('id') or 0) == int(self.config.app_id):
                    return True
        except Exception as e:
            logger.warning(f"Failed to check app opt-in for {user_address}: {e}")
        return False

    def _app_has_assets(self) -> bool:
        try:
            app_addr = get_application_address(int(self.config.app_id))
            info = self.algod.account_info(app_addr)
            have_confio = any(int(a.get('asset-id')) == int(AlgorandAccountManager.CONFIO_ASSET_ID) for a in (info.get('assets') or []))
            have_cusd = any(int(a.get('asset-id')) == int(self.config.cusd_asset_id) for a in (info.get('assets') or []))
            return have_confio and have_cusd
        except Exception as e:
            logger.warning(f"Failed to check app assets: {e}")
            return False

    def _ensure_app_opted_in_assets(self) -> None:
        """Ensure the app account is opted into CONFIO and cUSD (sponsor-funded)."""
        try:
            if not self.config.app_id:
                return
            if self._app_has_assets():
                return
            from django.conf import settings as _dj
            admin_mn = getattr(_dj, 'ALGORAND_ADMIN_MNEMONIC', None) or AlgorandAccountManager.SPONSOR_MNEMONIC
            sponsor_addr = AlgorandAccountManager.SPONSOR_ADDRESS
            if not admin_mn or not sponsor_addr:
                logger.warning("Cannot opt-in app assets: missing admin mnemonic or sponsor address")
                return
            from algosdk import mnemonic as _mn, account as _acct
            admin_sk = _mn.to_private_key(" ".join(str(admin_mn).strip().split()))
            admin_addr = _acct.address_from_private_key(admin_sk)
            params = self.algod.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            sp_s = self.algod.suggested_params(); sp_s.flat_fee = True; sp_s.fee = min_fee * 2
            bump = PaymentTxn(sender=sponsor_addr, sp=sp_s, receiver=sponsor_addr, amt=0)
            sp_a = self.algod.suggested_params(); sp_a.flat_fee = True; sp_a.fee = min_fee * 3
            # Include foreign assets so inner txns can reference IDs
            foreign_assets_boot: List[int] = []
            try:
                if int(getattr(AlgorandAccountManager, 'CONFIO_ASSET_ID', 0) or 0):
                    foreign_assets_boot.append(int(AlgorandAccountManager.CONFIO_ASSET_ID))
            except Exception:
                pass
            try:
                if int(self.config.cusd_asset_id or 0):
                    foreign_assets_boot.append(int(self.config.cusd_asset_id))
            except Exception:
                pass
            call = ApplicationNoOpTxn(
                sender=admin_addr,
                sp=sp_a,
                index=int(self.config.app_id),
                app_args=[b"opt_in_assets"],
                foreign_assets=foreign_assets_boot,
            )
            gid = transaction.calculate_group_id([bump, call])
            bump.group = gid; call.group = gid
            stx0 = self._sign_sponsor(bump)
            if not stx0:
                logger.warning("Cannot sign sponsor bump: missing sponsor signer/credentials")
                return
            stx1 = call.sign(admin_sk)
            self.algod.send_transactions([stx0, stx1])
            try:
                from algosdk.transaction import wait_for_confirmation as _wfc
                _wfc(self.algod, stx1.get_txid(), 4)
            except Exception:
                pass
            logger.info("[PRESALE] Auto-opted app into CONFIO and cUSD via opt_in_assets")
        except Exception as e:
            logger.warning(f"Failed to auto opt-in app assets: {e}")

    def _check_address_opted_in_app(self, address: str) -> bool:
        """Generic checker for whether an address has opted into the presale app."""
        try:
            info = self.algod.account_info(address)
            for ls in info.get('apps-local-state', []) or []:
                if int(ls.get('id') or 0) == int(self.config.app_id):
                    return True
        except Exception as e:
            logger.warning(f"Failed to check app opt-in for {address}: {e}")
        return False

    def _ensure_sponsor_opted_in_app(self) -> None:
        """
        Ensure the sponsor address is opted into the presale application.
        The presale approval program asserts app_opted_in(Txn.Sender, CurrentApplicationID) for the app call,
        so the sponsor (as sender) must be opted in. Perform a one-time opt-in if needed.
        """
        # Must have app id and sponsor credentials
        if not self.config.app_id or not self.config.sponsor_address:
            return
        if self._check_address_opted_in_app(self.config.sponsor_address):
            return
        if not (self.sponsor_signer or self.config.sponsor_mnemonic):
            logger.error(
                "Presale sponsor is not opted into app %s and SPONSOR_MNEMONIC is not configured; cannot auto opt-in",
                self.config.app_id,
            )
            return
        try:
            # Build and submit a plain ApplicationOptIn from the sponsor
            sp = self.algod.suggested_params()
            sp.flat_fee = True
            sp.fee = getattr(sp, 'min_fee', 1000) or 1000
            app_opt_in = transaction.ApplicationOptInTxn(
                sender=self.config.sponsor_address,
                sp=sp,
                index=int(self.config.app_id),
            )
            stx = self._sign_sponsor(app_opt_in)
            if not stx:
                logger.error("Failed to sign sponsor opt-in txn; no signer available")
                return
            txid = self.algod.send_transaction(stx)
            try:
                from algosdk.transaction import wait_for_confirmation
                wait_for_confirmation(self.algod, txid, 4)
            except Exception:
                pass
            logger.info(
                "[PRESALE] Auto-opted sponsor into app %s (txid=%s)",
                self.config.app_id,
                txid,
            )
        except Exception as e:
            logger.error("Failed to auto opt-in sponsor to app %s: %s", self.config.app_id, e)

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

        # Ensure app account has required assets
        self._ensure_app_opted_in_assets()

        # Ensure user is opted into the presale app
        if not self._check_user_opted_in_app(user_address):
            return {
                "success": False,
                "error": "requires_presale_app_optin",
                "app_id": self.config.app_id,
            }

        # Ensure sponsor (app call sender) is opted in as required by the approval program
        # This is a one-time server-side action and is safe to perform here.
        self._ensure_sponsor_opted_in_app()

        params = self.algod.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        # Addresses
        app_address = get_application_address(self.config.app_id)

        # Check user balance vs min-balance; fund shortfall if needed
        try:
            acct = self.algod.account_info(user_address)
            current_balance = int(acct.get('amount') or 0)
            min_balance = int(acct.get('min-balance') or 0)
            # Ensure the account stays above MBR even if an extra local state/box nudges it.
            # Use a robust 250k headroom to avoid race-y underfunding.
            SAFETY_BUFFER = 250_000
            target = max(min_balance + SAFETY_BUFFER, 0)
            funding_needed = max(target - current_balance, 0)
            # Ensure meaningful top-up if any shortfall is detected
            if funding_needed > 0 and funding_needed < 200_000:
                funding_needed = 200_000
            logger.info(
                f"[PRESALE] MBR check user={user_address} bal={current_balance} min={min_balance} "
                f"buffer={SAFETY_BUFFER} target={target} fund={funding_needed}"
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

        # [1] User -> app cUSD transfer is fully sponsored; allow fee=0
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
        # Include foreign assets for contract reads (CONFIO balance) and inner txns if any
        foreign_assets: List[int] = []
        try:
            if int(getattr(AlgorandAccountManager, 'CONFIO_ASSET_ID', 0) or 0):
                foreign_assets.append(int(AlgorandAccountManager.CONFIO_ASSET_ID))
        except Exception:
            pass
        try:
            if int(self.config.cusd_asset_id or 0):
                foreign_assets.append(int(self.config.cusd_asset_id))
        except Exception:
            pass

        app_call = ApplicationNoOpTxn(
            sender=self.config.sponsor_address,
            sp=sp2,
            index=int(self.config.app_id),
            app_args=[b"buy"],
            accounts=[user_address],  # passed so contract can attribute purchase to user
            foreign_assets=foreign_assets,
        )

        # Group and (optionally) sign sponsor txns
        gid = transaction.calculate_group_id([sponsor_bump, cusd_axfer, app_call])
        sponsor_bump.group = gid
        cusd_axfer.group = gid
        app_call.group = gid

        sponsor_signed_0 = None
        sponsor_signed_2 = None
        stx0 = self._sign_sponsor(sponsor_bump)
        stx2 = self._sign_sponsor(app_call)
        if stx0:
            sponsor_signed_0 = algo_encoding.msgpack_encode(stx0)
        if stx2:
            sponsor_signed_2 = algo_encoding.msgpack_encode(stx2)

        pack = {
            "success": True,
            "sponsor_transactions": [
                {"index": 0, "txn": algo_encoding.msgpack_encode(sponsor_bump), "signed": sponsor_signed_0},
                {"index": 2, "txn": algo_encoding.msgpack_encode(app_call), "signed": sponsor_signed_2},
            ],
            "transactions_to_sign": [
                # Use raw msgpack of dictify() for unsigned txns so JS algosdk can decode
                {"index": 1, "txn": base64.b64encode(msgpack.packb(cusd_axfer.dictify(), use_bin_type=True)).decode(), "message": "User cUSD payment"}
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

        # [1] User ApplicationOptInTx (fee=0)
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

        # Check user balance vs min-balance + opt-in cost; fund shortfall if needed
        funding_needed = 0
        try:
            acct = self.algod.account_info(user_address)
            current_balance = int(acct.get('amount') or 0)
            min_balance = int(acct.get('min-balance') or 0)
            
            # Calculate opt-in cost for this specific app
            # Schema: 5 ints, 0 bytes (per user) -> 28500 microAlgos increase
            # Plus 100,000 basic min balance increase for a new entry
            # Total increase: 128,500
            OPTIN_COST = 100_000 + (28_500 * 1) # 1 schema chunk
            
            # Use a robust safety buffer
            SAFETY_BUFFER = 200_000
            
            # Target is current MBR + Cost + Buffer
            target = min_balance + OPTIN_COST + SAFETY_BUFFER
            funding_needed = max(target - current_balance, 0)
            
            # Ensure meaningful top-up if any shortfall is detected
            if funding_needed > 0 and funding_needed < 250_000:
                funding_needed = 250_000
                
            if funding_needed > 0:
                logger.info(
                    f"[PRESALE] Opt-in MBR check user={user_address} bal={current_balance} min={min_balance} "
                    f"funding={funding_needed}"
                )
        except Exception as e:
            # Conservative fallback top-up if account query fails
            funding_needed = 350_000
            logger.warning(f"[PRESALE] account_info failed during opt-in build; default funding={funding_needed} err={e}")

        # [0] Sponsor payment (MBR funding if needed, otherwise self-payment)
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
            # If funding needed, send to user; else send 0 to self (fee bump)
            receiver=user_address if funding_needed > 0 else self.config.sponsor_address,
            amt=int(funding_needed),
            note=b"Presale app opt-in fee bump",
        )

        gid = transaction.calculate_group_id([sponsor_bump, app_opt_in])
        sponsor_bump.group = gid
        app_opt_in.group = gid

        sponsor_signed_0 = None
        stx0 = self._sign_sponsor(sponsor_bump)
        if stx0:
            sponsor_signed_0 = algo_encoding.msgpack_encode(stx0)

        return {
            "success": True,
            "sponsor_transactions": [
                {"index": 0, "txn": algo_encoding.msgpack_encode(sponsor_bump), "signed": sponsor_signed_0},
            ],
            "transactions_to_sign": [
                # Use raw msgpack of dictify() for unsigned txns so JS algosdk can decode
                {"index": 1, "txn": base64.b64encode(msgpack.packb(app_opt_in.dictify(), use_bin_type=True)).decode(), "message": "User app opt-in"}
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

        # [0] User witness 0-ALGO payment must be fee=0 (contract asserts Gtxn[0].fee()==0)
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
        # App call must cover: its own base fee + inner xfer fee + pooled min for user witness
        # Use 3× min to safely cover (2 outer txns + 1 inner)
        sp1 = SuggestedParams(
            fee=min_fee * 3,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        # Include foreign assets for claim path (CONFIO; include cUSD for consistency)
        foreign_assets_claim: List[int] = []
        try:
            if int(getattr(AlgorandAccountManager, 'CONFIO_ASSET_ID', 0) or 0):
                foreign_assets_claim.append(int(AlgorandAccountManager.CONFIO_ASSET_ID))
        except Exception:
            pass
        try:
            if int(self.config.cusd_asset_id or 0):
                foreign_assets_claim.append(int(self.config.cusd_asset_id))
        except Exception:
            pass

        app_call = ApplicationNoOpTxn(
            sender=self.config.sponsor_address,
            sp=sp1,
            index=int(self.config.app_id),
            app_args=[b"claim"],
            accounts=[user_address],
            foreign_assets=foreign_assets_claim,
        )

        # Group
        gid = transaction.calculate_group_id([user_witness, app_call])
        user_witness.group = gid
        app_call.group = gid

        sponsor_signed_1 = None
        stx1 = self._sign_sponsor(app_call)
        if stx1:
            sponsor_signed_1 = algo_encoding.msgpack_encode(stx1)

        return {
            "success": True,
            "sponsor_transactions": [
                {"index": 1, "txn": algo_encoding.msgpack_encode(app_call), "signed": sponsor_signed_1},
            ],
            "transactions_to_sign": [
                # Use raw msgpack of dictify() for unsigned txns so JS algosdk can decode
                {"index": 0, "txn": base64.b64encode(msgpack.packb(user_witness.dictify(), use_bin_type=True)).decode(), "message": "User claim witness"}
            ],
            "group_id": base64.b64encode(gid).decode(),
        }
