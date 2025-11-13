"""
Services for interacting with the CONFIO referral rewards vault on Algorand.

This module encapsulates the logic required to mark a referred user as eligible
for an on-chain reward by calling the deployed rewards application.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Sequence

import base64
from algosdk import mnemonic, transaction, encoding
from algosdk.logic import get_application_address
from algosdk.error import AlgodHTTPError
from algosdk.v2client import algod
from django.conf import settings

from blockchain.algorand_client import get_algod_client

logger = logging.getLogger(__name__)


BOX_MBR_FUNDING = 100_000  # microAlgos; safe buffer above theoretical MBR


@dataclass(frozen=True)
class RewardSyncResult:
    """Return payload after syncing eligibility on-chain."""

    tx_id: str
    confirmed_round: int
    referee_confio_micro: int
    referrer_confio_micro: int
    box_name: str


class ConfioRewardsService:
    """
    High-level helper for calling the rewards vault application.

    The service signs an atomic group containing:
      1. Payment from sponsor to cover box minimum-balance charges.
      2. Application call from the rewards admin account.
    """

    def __init__(self, client: Optional[algod.AlgodClient] = None) -> None:
        self.algod: algod.AlgodClient = client or get_algod_client()
        self.app_id: int = getattr(settings, "ALGORAND_REWARD_APP_ID", 0)
        if not self.app_id:
            raise RuntimeError("ALGORAND_REWARD_APP_ID is not configured")

        sponsor_mnemonic: Optional[str] = getattr(
            settings, "ALGORAND_SPONSOR_MNEMONIC", None
        )
        reward_sponsor_addr: Optional[str] = getattr(
            settings, "ALGORAND_REWARD_SPONSOR_ADDRESS", None
        )

        if not sponsor_mnemonic:
            raise RuntimeError("ALGORAND_SPONSOR_MNEMONIC is required for rewards sync")

        self.sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
        sponsor_address = reward_sponsor_addr or getattr(
            settings, "ALGORAND_REWARD_SPONSOR_ADDRESS", None
        )
        if sponsor_address:
            self.sponsor_address = sponsor_address
        else:
            from algosdk import account

            self.sponsor_address = account.address_from_private_key(
                self.sponsor_private_key
            )

        admin_mnemonic: Optional[str] = getattr(
            settings, "ALGORAND_REWARD_ADMIN_MNEMONIC", None
        ) or getattr(settings, "ALGORAND_ADMIN_MNEMONIC", None)
        if not admin_mnemonic:
            raise RuntimeError(
                "ALGORAND_REWARD_ADMIN_MNEMONIC or ALGORAND_ADMIN_MNEMONIC is required"
            )

        self.admin_private_key = mnemonic.to_private_key(admin_mnemonic)
        from algosdk import account as _account

        self.admin_address = _account.address_from_private_key(
            self.admin_private_key
        )

        self.confio_asset_id: int = getattr(settings, "ALGORAND_CONFIO_ASSET_ID", 0)
        if not self.confio_asset_id:
            raise RuntimeError("ALGORAND_CONFIO_ASSET_ID must be configured")

        self.manual_price_micro_cusd: Optional[int] = None
        self.manual_price_active: bool = False
        self.price_micro_cusd: Optional[int] = None

        self._sync_global_state_config()

        if not self.price_micro_cusd:
            self.price_micro_cusd = getattr(
                settings, "ALGORAND_CONFIO_PRICE_MICRO_CUSD", 250_000
            )

        self.app_address = get_application_address(self.app_id)

    def _sync_global_state_config(self) -> None:
        """Ensure we use the asset/app IDs stored on-chain if they differ from settings."""
        try:
            info = self.algod.application_info(self.app_id)
            global_state = info.get("params", {}).get("global-state", [])
            state_dict = {}
            for entry in global_state:
                key = base64.b64decode(entry.get("key", ""))
                key_str = key.decode("utf-8", errors="ignore")
                value = entry.get("value", {})
                if value.get("type") == 2:
                    state_dict[key_str] = value.get("uint")
            confio_id = state_dict.get("confio_id")
            if confio_id:
                if confio_id != self.confio_asset_id:
                    logger.warning(
                        "Confio asset mismatch: settings=%s rewards_global=%s; using on-chain value",
                        self.confio_asset_id,
                        confio_id,
                    )
                self.confio_asset_id = confio_id
            manual_price = state_dict.get("manual_price")
            if manual_price:
                self.manual_price_micro_cusd = int(manual_price)
            manual_active = state_dict.get("manual_active")
            if manual_active is not None:
                self.manual_price_active = bool(manual_active)
            if "price" in state_dict:
                self.price_micro_cusd = int(state_dict["price"])
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to sync rewards global state: %s", exc)

    def mark_eligibility(
        self,
        *,
        user_address: str,
        reward_cusd_micro: int,
        referee_confio_micro: int,
        referrer_confio_micro: int = 0,
        referrer_address: Optional[str] = None,
        extra_foreign_apps: Optional[Sequence[int]] = None,
    ) -> RewardSyncResult:
        """
        Mark a referral as eligible in the rewards vault.

        Idempotency:
            If the user's box already exists with a non-zero amount, the vault
            will reject duplicate writes. In that case we treat the call as a
            success and return the stored values so the caller can mark the
            reward as eligible.

        Args:
            user_address: Algorand address of the referred user.
            reward_cusd_micro: Reward size denominated in micro cUSD.
            referee_confio_micro: Expected CONFIO allocation (for logging).
            referrer_confio_micro: Optional referrer allocation in micro CONFIO.
            referrer_address: Algorand address for the referrer (required if
                `referrer_confio_micro` > 0).
            extra_foreign_apps: Optional additional foreign app IDs.
        """
        if reward_cusd_micro <= 0:
            raise ValueError("reward_cusd_micro must be positive")

        user_addr_bytes = encoding.decode_address(user_address)

        existing = self._read_user_box(user_addr_bytes)
        if existing and existing["eligible_amount"] > 0:
            logger.info(
                "Rewards entry already exists for %s (eligible=%s ref=%s); skipping rewrite",
                user_address,
                existing["eligible_amount"],
                existing["ref_amount"],
            )
            return RewardSyncResult(
                tx_id="already-recorded",
                confirmed_round=existing.get("round", 0),
                referee_confio_micro=existing["eligible_amount"],
                referrer_confio_micro=existing["ref_amount"],
                box_name=user_addr_bytes.hex(),
            )

        if referrer_confio_micro and not referrer_address:
            raise ValueError(
                "referrer_address required when referrer_confio_micro > 0"
            )

        params_payment = self.algod.suggested_params()
        payment_txn = transaction.PaymentTxn(
            sender=self.sponsor_address,
            receiver=self.app_address,
            amt=BOX_MBR_FUNDING,
            sp=params_payment,
        )

        params_call = self.algod.suggested_params()
        app_args = [
            b"mark_eligible",
            reward_cusd_micro.to_bytes(8, "big"),
            user_addr_bytes,
        ]

        accounts = [user_address]
        if referrer_confio_micro > 0 and referrer_address:
            app_args.append(referrer_confio_micro.to_bytes(8, "big"))
            accounts.append(referrer_address)

        foreign_apps = list(extra_foreign_apps or [])

        box_references = [transaction.BoxReference(0, user_addr_bytes)]

        app_call = transaction.ApplicationNoOpTxn(
            sender=self.admin_address,
            index=self.app_id,
            sp=params_call,
            app_args=app_args,
            accounts=accounts,
            foreign_assets=[self.confio_asset_id],
            foreign_apps=foreign_apps,
            boxes=box_references,
        )

        logger.info(
            "Rewards service building group: confio_asset_id=%s reward_cusd_micro=%s ref_confio_micro=%s user=%s referrer=%s",
            self.confio_asset_id,
            reward_cusd_micro,
            referrer_confio_micro,
            user_address,
            referrer_address,
        )

        transaction.assign_group_id([payment_txn, app_call])

        signed_payment = payment_txn.sign(self.sponsor_private_key)
        signed_call = app_call.sign(self.admin_private_key)

        try:
            tx_id = self.algod.send_transactions([signed_payment, signed_call])
        except AlgodHTTPError as exc:
            message = str(exc)
            if (
                "pc=1135" in message
                or "load 8" in message
                or "box" in message.lower()
            ):
                logger.warning(
                    "Rewards app reports existing eligibility for %s (error=%s); treating as success",
                    user_address,
                    message,
                )
                existing = self._read_user_box(user_addr_bytes)
                if existing and existing["eligible_amount"] > 0:
                    return RewardSyncResult(
                        tx_id="already-recorded",
                        confirmed_round=existing.get("round", 0),
                        referee_confio_micro=existing["eligible_amount"],
                        referrer_confio_micro=existing["ref_amount"],
                        box_name=user_addr_bytes.hex(),
                    )
                logger.warning(
                    "Rewards vault indicates duplicate for %s but box lookup failed; "
                    "returning synthetic success (reason=%s)",
                    user_address,
                    message,
                )
                return RewardSyncResult(
                    tx_id="already-recorded",
                    confirmed_round=0,
                    referee_confio_micro=referee_confio_micro,
                    referrer_confio_micro=referrer_confio_micro,
                    box_name=user_addr_bytes.hex(),
                )
            raise
        logger.info(
            "Submitted rewards eligibility group tx %s for user %s (cUSD=%s, ref_confio=%s)",
            tx_id,
            user_address,
            reward_cusd_micro,
            referrer_confio_micro,
        )

        confirmation = transaction.wait_for_confirmation(self.algod, tx_id, 6)
        confirmed_round = confirmation.get("confirmed-round", 0)
        logger.info(
            "Rewards eligibility confirmed in round %s for user %s",
            confirmed_round,
            user_address,
        )

        return RewardSyncResult(
            tx_id=tx_id,
            confirmed_round=confirmed_round,
            referee_confio_micro=referee_confio_micro,
            referrer_confio_micro=referrer_confio_micro,
            box_name=user_addr_bytes.hex(),
        )

    def _read_user_box(self, user_addr_bytes: bytes) -> Optional[dict]:
        """Fetch an existing eligibility box, if any."""
        try:
            box = self.algod.application_box_by_name(self.app_id, user_addr_bytes)
            value = base64.b64decode(box.get("value", ""))
        except AlgodHTTPError as exc:
            if getattr(exc, "code", None) == 404:
                return None
            raise
        except Exception:
            return None

        if len(value) < 72:
            return None

        def read_uint(offset: int) -> int:
            return int.from_bytes(value[offset : offset + 8], "big")

        return {
            "eligible_amount": read_uint(0),
            "claimed_flag": read_uint(8),
            "ref_amount": read_uint(16),
            "ref_claimed_flag": read_uint(56),
            "round": read_uint(64),
        }

    def get_claimable_amount(self, user_address: str) -> Optional[Decimal]:
        """Return current CONFIO amount available for the user box (Decimal tokens)."""
        try:
            addr_bytes = encoding.decode_address(user_address)
        except Exception:
            return None

        box = self._read_user_box(addr_bytes)
        if not box:
            return None
        return Decimal(box["eligible_amount"]) / Decimal(1_000_000)

    def get_confio_price_micro_cusd(self) -> int:
        """Return the current CONFIO price in micro cUSD (falls back to settings)."""
        if self.manual_price_active and self.manual_price_micro_cusd:
            return int(self.manual_price_micro_cusd)
        if self.price_micro_cusd:
            return int(self.price_micro_cusd)
        return int(getattr(settings, "ALGORAND_CONFIO_PRICE_MICRO_CUSD", 250_000))

    def convert_cusd_to_confio(self, cusd_amount: Decimal) -> Decimal:
        """Convert a cUSD amount into CONFIO tokens using the vault price."""
        if not cusd_amount or cusd_amount <= Decimal("0"):
            return Decimal("0")
        price_micro = self.get_confio_price_micro_cusd()
        micro_amount = (cusd_amount * Decimal(1_000_000)).to_integral_value()
        tokens = Decimal(micro_amount) / Decimal(price_micro)
        return tokens

    def build_claim_group(
        self,
        *,
        user_address: str,
        referrer_address: Optional[str] = None,
    ) -> dict:
        """
        Prepare a sponsored claim group so the user can withdraw their CONFIO reward.

        Group layout:
          [0] Sponsor self-payment (covers all fees)
          [1] User ApplicationCall (claim)
        """
        params = self.algod.suggested_params()
        min_fee = getattr(params, "min_fee", 1000) or 1000

        user_sp = transaction.SuggestedParams(
            fee=0,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )

        boxes = [transaction.BoxReference(0, encoding.decode_address(user_address))]
        accounts: list[str] = [user_address]
        if referrer_address:
            accounts.append(referrer_address)

        user_app_call = transaction.ApplicationNoOpTxn(
            sender=user_address,
            index=self.app_id,
            sp=user_sp,
            app_args=[b"claim"],
            accounts=accounts,
            boxes=boxes,
        )

        sponsor_sp = transaction.SuggestedParams(
            fee=min_fee * 3,
            first=params.first,
            last=params.last,
            gh=params.gh,
            flat_fee=True,
        )
        sponsor_fee = transaction.PaymentTxn(
            sender=self.sponsor_address,
            receiver=self.sponsor_address,
            amt=0,
            sp=sponsor_sp,
        )

        gid = transaction.calculate_group_id([user_app_call, sponsor_fee])
        user_app_call.group = gid
        sponsor_fee.group = gid

        try:
            sponsor_signed = sponsor_fee.sign(self.sponsor_private_key)
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError("Unable to sign sponsor transaction") from exc

        return {
            "success": True,
            "group_id": base64.b64encode(gid).decode(),
            "sponsor_signed": encoding.msgpack_encode(sponsor_signed),
            "user_unsigned": encoding.msgpack_encode(user_app_call),
        }
