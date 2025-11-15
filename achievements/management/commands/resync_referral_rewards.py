"""
Management command to re-sync referral rewards with the Algorand vault.

This is useful after deploying a new rewards application ID or if the on-chain
state was never written even though the referral appears as "eligible" in the
admin UI.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from algosdk import encoding as algo_encoding
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from achievements.models import ReferralRewardEvent, UserReferral
from achievements.services.referral_rewards import get_primary_algorand_address
from blockchain.rewards_service import ConfioRewardsService

MICRO = Decimal("1000000")


def to_micro(amount: Optional[Decimal]) -> int:
    """Convert Decimal token amount into integer micro-units."""
    if not amount or amount <= Decimal("0"):
        return 0
    return int((amount * MICRO).to_integral_value())


class Command(BaseCommand):
    help = "Re-sync referral reward eligibility to the Algorand rewards vault."

    def add_arguments(self, parser):
        parser.add_argument(
            "--referral-id",
            type=int,
            action="append",
            dest="referral_ids",
            help="Specific UserReferral.id values to resync (can be repeated).",
        )
        parser.add_argument(
            "--referred-user",
            action="append",
            dest="user_identifiers",
            help="Filter by referred user's username or numeric ID (can be repeated).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process every referral that matches the other criteria.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-sync even if the referral already has a reward_tx_id or is not marked eligible.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be resynced without submitting transactions.",
        )

    def handle(self, *args, **options):
        referral_ids: Iterable[int] = options.get("referral_ids") or []
        user_identifiers: Iterable[str] = options.get("user_identifiers") or []
        process_all: bool = bool(options.get("all"))
        force: bool = bool(options.get("force"))
        dry_run: bool = bool(options.get("dry_run"))

        qs = UserReferral.objects.filter(deleted_at__isnull=True)

        if referral_ids:
            qs = qs.filter(id__in=set(referral_ids))

        if user_identifiers:
            query = Q()
            for ident in user_identifiers:
                if not ident:
                    continue
                if ident.isdigit():
                    query |= Q(referred_user__id=int(ident))
                else:
                    query |= Q(referred_user__username__iexact=ident)
                    query |= Q(referred_user__email__iexact=ident)
            qs = qs.filter(query)

        if not process_all and not referral_ids and not user_identifiers:
            raise CommandError(
                "Provide --referral-id, --referred-user, or --all to select referrals."
            )

        referrals = list(qs.order_by("id"))
        if not referrals:
            self.stdout.write(self.style.WARNING("No referrals matched the filters."))
            return

        service = ConfioRewardsService()
        price_micro = service.get_confio_price_micro_cusd()
        now = timezone.now()

        for referral in referrals:
            referee = referral.referred_user
            self.stdout.write(
                f"\n↪ Referral #{referral.id} - referee={referee.username} "
                f"referrer={getattr(referral.referrer_user, 'username', 'unknown')} "
                f"reward_status={referral.reward_status}"
            )

            if referral.reward_status != "eligible" and not force:
                self.stdout.write(
                    self.style.WARNING(
                        "  • Skipping (reward_status != eligible). Use --force to override."
                    )
                )
                continue

            user_address = get_primary_algorand_address(referee)
            if not user_address:
                self.stdout.write(
                    self.style.ERROR("  • Referee has no Algorand address; skipping.")
                )
                continue

            try:
                box_key = algo_encoding.decode_address(user_address)
            except Exception as exc:  # pragma: no cover - defensive guard
                self.stdout.write(
                    self.style.ERROR(f"  • Failed to decode address: {exc}")
                )
                continue

            existing_box = None
            try:
                existing_box = service._read_user_box(box_key)
            except Exception as exc:  # pragma: no cover - network guard
                self.stdout.write(
                    self.style.ERROR(f"  • Unable to read current box: {exc}")
                )
                continue

            if existing_box and existing_box.get("eligible_amount", 0) > 0 and not force:
                self.stdout.write(
                    self.style.SUCCESS(
                        "  • On-chain box already exists on current app; skipping."
                    )
                )
                continue

            referee_confio_micro = to_micro(referral.reward_referee_confio)
            referrer_confio_micro = to_micro(referral.reward_referrer_confio)

            if referee_confio_micro <= 0 and not force:
                self.stdout.write(
                    self.style.WARNING(
                        "  • Referee amount is zero; nothing to sync (use --force to override)."
                    )
                )
                continue

            reward_metadata = referral.reward_metadata or {}
            reward_cusd_micro = int(reward_metadata.get("reward_cusd_micro") or 0)
            if reward_cusd_micro <= 0:
                reward_cusd_micro = (
                    referee_confio_micro * price_micro // int(MICRO)
                )

            referrer_address = None
            if referrer_confio_micro > 0 and referral.referrer_user:
                referrer_address = get_primary_algorand_address(referral.referrer_user)
                if not referrer_address:
                    self.stdout.write(
                        self.style.WARNING(
                            "  • Referrer lacks Algorand address; "
                            "referrer portion will be skipped."
                        )
                    )
                    referrer_confio_micro = 0

            self.stdout.write(
                f"  • Preparing resync (reward_cusd_micro={reward_cusd_micro}, "
                f"referee_confio_micro={referee_confio_micro}, "
                f"referrer_confio_micro={referrer_confio_micro})"
            )

            if dry_run:
                self.stdout.write(self.style.SUCCESS("  • Dry run complete."))
                continue

            try:
                result = service.mark_eligibility(
                    user_address=user_address,
                    reward_cusd_micro=reward_cusd_micro,
                    referee_confio_micro=referee_confio_micro,
                    referrer_confio_micro=referrer_confio_micro,
                    referrer_address=referrer_address,
                )
            except Exception as exc:
                referral.reward_error = str(exc)
                referral.reward_last_attempt_at = now
                referral.save(update_fields=["reward_error", "reward_last_attempt_at"])
                self.stdout.write(
                    self.style.ERROR(f"  • Failed to sync referral: {exc}")
                )
                continue

            self.stdout.write(
                self.style.SUCCESS(
                    f"  • Resynced successfully (tx_id={result.tx_id}, box={result.box_name})"
                )
            )

            referral.reward_tx_id = result.tx_id
            referral.reward_box_name = result.box_name
            referral.reward_error = ""
            referral.reward_last_attempt_at = now
            referral.reward_submitted_at = now
            reward_metadata["reward_cusd_micro"] = reward_cusd_micro
            reward_metadata["resynced_at"] = now.isoformat()
            referral.reward_metadata = reward_metadata
            referral.save(
                update_fields=[
                    "reward_tx_id",
                    "reward_box_name",
                    "reward_error",
                    "reward_last_attempt_at",
                    "reward_submitted_at",
                    "reward_metadata",
                ]
            )

            self._update_events(referral, result.tx_id)

    def _update_events(self, referral: UserReferral, tx_id: str) -> None:
        """Ensure referral events mirror the on-chain eligibility state."""
        events = ReferralRewardEvent.objects.filter(
            referral=referral,
            reward_status__in=["pending", "eligible"],
        )
        now = timezone.now()
        for event in events:
            actor_role = (event.actor_role or "").lower()
            updated_fields = []
            if event.reward_status != "eligible":
                event.reward_status = "eligible"
                updated_fields.append("reward_status")
            if actor_role == "referee":
                target_confio = referral.reward_referee_confio or event.referee_confio
                if target_confio and target_confio != event.referee_confio:
                    event.referee_confio = target_confio
                    updated_fields.append("referee_confio")
            elif actor_role == "referrer":
                target_confio = referral.reward_referrer_confio or event.referrer_confio
                if target_confio and target_confio != event.referrer_confio:
                    event.referrer_confio = target_confio
                    updated_fields.append("referrer_confio")

            event.reward_tx_id = tx_id
            event.error = ""
            event.updated_at = now
            updated_fields.extend(["reward_tx_id", "error", "updated_at"])
            event.save(update_fields=updated_fields)
