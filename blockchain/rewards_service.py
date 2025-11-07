"""
Services for interacting with the CONFIO referral rewards vault on Algorand.

This module encapsulates the logic required to mark a referred user as eligible
for an on-chain reward by calling the deployed rewards application.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from algosdk import encoding, mnemonic, transaction
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
        self.sponsor_address = (
            reward_sponsor_addr
            or getattr(settings, "ALGORAND_REWARD_SPONSOR_ADDRESS", None)
            or mnemonic.to_public_key(sponsor_mnemonic)
        )

        admin_mnemonic: Optional[str] = getattr(
            settings, "ALGORAND_REWARD_ADMIN_MNEMONIC", None
        ) or getattr(settings, "ALGORAND_ADMIN_MNEMONIC", None)
        if not admin_mnemonic:
            raise RuntimeError(
                "ALGORAND_REWARD_ADMIN_MNEMONIC or ALGORAND_ADMIN_MNEMONIC is required"
            )

        self.admin_private_key = mnemonic.to_private_key(admin_mnemonic)
        self.admin_address = mnemonic.to_public_key(admin_mnemonic)

        self.confio_asset_id: int = getattr(settings, "ALGORAND_CONFIO_ASSET_ID", 0)
        if not self.confio_asset_id:
            raise RuntimeError("ALGORAND_CONFIO_ASSET_ID must be configured")

        self.presale_app_id: int = getattr(settings, "ALGORAND_PRESALE_APP_ID", 0)

        self.app_address = encoding.get_application_address(self.app_id)

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
        if self.presale_app_id:
            foreign_apps.append(self.presale_app_id)

        app_call = transaction.ApplicationNoOpTxn(
            sender=self.admin_address,
            index=self.app_id,
            sp=params_call,
            app_args=app_args,
            accounts=accounts,
            foreign_assets=[self.confio_asset_id],
            foreign_apps=foreign_apps,
            boxes=[transaction.BoxReference(self.app_id, user_addr_bytes)],
        )

        transaction.assign_group_id([payment_txn, app_call])

        signed_payment = payment_txn.sign(self.sponsor_private_key)
        signed_call = app_call.sign(self.admin_private_key)

        tx_id = self.algod.send_transactions([signed_payment, signed_call])
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
