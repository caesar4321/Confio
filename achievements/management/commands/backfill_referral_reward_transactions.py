"""
Backfill UnifiedTransactionTable entries for already-claimed referral rewards.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from achievements.models import ReferralRewardEvent
from achievements.services.referral_rewards import get_primary_algorand_address
from users.models_unified import UnifiedTransactionTable


class Command(BaseCommand):
    help = "Create unified transaction rows for referral rewards that were already claimed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-id",
            type=int,
            help="Limit backfill to rewards belonging to this user ID.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of events to process (newest first).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        user_id = options.get("user_id")
        limit = options.get("limit")
        dry_run = options.get("dry_run", False)

        events = (
            ReferralRewardEvent.objects.filter(reward_status__iexact="claimed")
            .select_related("user", "referral")
            .order_by("-updated_at")
        )
        if user_id:
            events = events.filter(user_id=user_id)
        if limit:
            events = events[:limit]

        processed = 0
        skipped = 0
        created = 0

        for event in events:
            identifier = f"referral_claim:{event.id}:{event.user_id}"
            claim_amount = Command._event_claim_amount(event)
            if claim_amount <= Decimal("0"):
                skipped += 1
                continue

            referral = event.referral
            timestamp = (
                referral.reward_claimed_at
                if referral and referral.reward_claimed_at
                else event.updated_at
            ) or timezone.now()
            user_address = get_primary_algorand_address(event.user)
            amount_str = Command._decimal_to_string(claim_amount)

            defaults = {
                "amount": amount_str,
                "token_type": "CONFIO",
                "status": "CONFIRMED",
                "transaction_hash": event.reward_tx_id or "",
                "sender_user": None,
                "sender_business": None,
                "sender_type": "external",
                "sender_display_name": "Confío Rewards",
                "sender_phone": "",
                "sender_address": "ConfioRewardsVault",
                "counterparty_user": event.user,
                "counterparty_business": None,
                "counterparty_type": "user",
                "counterparty_display_name": Command._user_display(event.user),
                "counterparty_phone": "",
                "counterparty_address": user_address or "",
                "description": "Recompensa por referidos",
                "invoice_id": None,
                "payment_reference_id": identifier,
                "payment_transaction_id": None,
                "from_address": "ConfioRewardsVault",
                "to_address": user_address or "",
                "is_invitation": False,
                "invitation_claimed": False,
                "invitation_reverted": False,
                "invitation_expires_at": None,
                "transaction_date": timestamp,
                "referral_reward_event": event,
            }

            self.stdout.write(
                f"[event {event.id}] amount={amount_str} user={event.user_id} "
                f"txid={event.reward_tx_id or 'n/a'} dry_run={dry_run}"
            )

            if not dry_run:
                with transaction.atomic():
                    UnifiedTransactionTable.objects.update_or_create(
                        transaction_type="reward",
                        payment_reference_id=identifier,
                        defaults=defaults,
                    )
                created += 1
            processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed={processed} created={created} skipped={skipped} dry_run={dry_run}"
            )
        )

    @staticmethod
    def _event_claim_amount(event: ReferralRewardEvent) -> Decimal:
        """
        Determine the claimed amount for the event (referee vs referrer).
        """
        role = (event.actor_role or "").lower()
        amount = event.referee_confio if role == "referee" else event.referrer_confio
        if amount and amount > Decimal("0"):
            return amount

        referral = event.referral
        if referral:
            if role == "referee" and referral.reward_referee_confio:
                return referral.reward_referee_confio
            if role == "referrer" and referral.reward_referrer_confio:
                return referral.reward_referrer_confio
        return Decimal("0")

    @staticmethod
    def _decimal_to_string(value: Decimal) -> str:
        normalized = format(value.normalize(), "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return normalized or "0"

    @staticmethod
    def _user_display(user) -> str:
        full_name = f"{user.first_name} {user.last_name}".strip()
        if full_name:
            return full_name
        if user.username:
            return user.username
        if user.email:
            return user.email
        return "Tú"
