from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.db.models.functions import Coalesce

from achievements.referral_security import get_referral_reward_transactions
from blockchain.constants import REFERRAL_SINGLE_REVIEW_THRESHOLD
from blockchain.mutations import _record_referral_withdrawal
from send.models import SendTransaction


class Command(BaseCommand):
    help = (
        "Backfill missing ReferralWithdrawalLog rows for historical CONFIO sends "
        "funded by referral-earned rewards."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-id",
            type=int,
            help="Limit processing to a single sender user ID.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of send transactions to inspect.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print matches without writing any backfill rows.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        user_id = options.get("user_id")
        limit = options.get("limit")

        sends = (
            SendTransaction.objects.filter(
                token_type="CONFIO",
                sender_user__isnull=False,
                deleted_at__isnull=True,
                status__in=["SUBMITTED", "CONFIRMED", "AML_REVIEW"],
            )
            .select_related("sender_user")
            .order_by("created_at", "id")
        )
        if user_id:
            sends = sends.filter(sender_user_id=user_id)
        if limit:
            sends = sends[:limit]

        processed = 0
        created = 0
        skipped = 0

        for send in sends:
            processed += 1
            reference_id = str(send.id)

            if send.sender_user_id is None:
                skipped += 1
                continue

            existing = send.sender_user.referral_withdrawal_logs.filter(
                reference_type="send_transaction",
                reference_id=reference_id,
            ).first()
            if existing:
                skipped += 1
                self.stdout.write(
                    f"[skip] send={send.id} user={send.sender_user_id} existing_log={existing.id}"
                )
                continue

            earned_total = (
                get_referral_reward_transactions(user=send.sender_user)
                .filter(created_at__lte=send.created_at)
                .aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]
                or Decimal("0")
            )

            spent_total = (
                send.sender_user.referral_withdrawal_logs.filter(created_at__lt=send.created_at)
                .aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]
                or Decimal("0")
            )

            available = earned_total - spent_total
            if available <= Decimal("0"):
                skipped += 1
                self.stdout.write(
                    f"[skip] send={send.id} user={send.sender_user_id} referral_available=0"
                )
                continue

            referral_portion = min(send.amount, available)
            requires_review = referral_portion > REFERRAL_SINGLE_REVIEW_THRESHOLD

            self.stdout.write(
                f"[match] send={send.id} user={send.sender_user_id} created_at={send.created_at.isoformat()} "
                f"send_amount={send.amount} earned_before={earned_total} spent_before={spent_total} "
                f"referral_portion={referral_portion} dry_run={dry_run}"
            )

            if not dry_run:
                _record_referral_withdrawal(
                    send.sender_user,
                    referral_portion,
                    reference_id=reference_id,
                    requires_review=requires_review,
                )
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed={processed} created={created} skipped={skipped} dry_run={dry_run}"
            )
        )
