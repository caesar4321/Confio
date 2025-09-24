from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Max
from users.models import User, Account
from p2p_exchange.models import P2PTrade, P2PMessage
from send.models import SendTransaction
from payments.models import PaymentTransaction
from conversion.models import Conversion
from achievements.models import UserAchievement


class Command(BaseCommand):
    help = "Backfill users.last_activity_at from recent activity across the platform"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="How many days back to scan for activity (default: 365)",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timezone.timedelta(days=days)
        self.stdout.write(self.style.NOTICE(f"Backfilling last_activity_at using last {days} days (cutoff={cutoff:%Y-%m-%d %H:%M:%S %Z})"))

        latest = {}  # user_id -> datetime

        def merge(rows, key, ts):
            for r in rows:
                uid = r.get(key)
                when = r.get(ts)
                if uid and when:
                    prev = latest.get(uid)
                    if not prev or when > prev:
                        latest[uid] = when

        # Account login activity
        merge(
            Account.objects.filter(last_login_at__gte=cutoff)
            .values("user_id")
            .annotate(max_ts=Max("last_login_at")),
            "user_id",
            "max_ts",
        )

        # Auth logins
        merge(
            User.objects.filter(last_login__gte=cutoff).values("id").annotate(max_ts=Max("last_login")),
            "id",
            "max_ts",
        )

        # P2P trades (new + legacy)
        qs = P2PTrade.objects.filter(created_at__gte=cutoff)
        merge(qs.exclude(buyer_user__isnull=True).values("buyer_user_id").annotate(max_ts=Max("created_at")), "buyer_user_id", "max_ts")
        merge(qs.exclude(seller_user__isnull=True).values("seller_user_id").annotate(max_ts=Max("created_at")), "seller_user_id", "max_ts")
        merge(qs.exclude(buyer__isnull=True).values("buyer_id").annotate(max_ts=Max("created_at")), "buyer_id", "max_ts")
        merge(qs.exclude(seller__isnull=True).values("seller_id").annotate(max_ts=Max("created_at")), "seller_id", "max_ts")

        # P2P messages
        merge(
            P2PMessage.objects.filter(created_at__gte=cutoff)
            .exclude(sender_user__isnull=True)
            .values("sender_user_id")
            .annotate(max_ts=Max("created_at")),
            "sender_user_id",
            "max_ts",
        )
        merge(
            P2PMessage.objects.filter(created_at__gte=cutoff)
            .exclude(sender__isnull=True)
            .values("sender_id")
            .annotate(max_ts=Max("created_at")),
            "sender_id",
            "max_ts",
        )

        # Sends
        qs = SendTransaction.objects.filter(created_at__gte=cutoff)
        merge(qs.exclude(sender_user__isnull=True).values("sender_user_id").annotate(max_ts=Max("created_at")), "sender_user_id", "max_ts")
        merge(qs.exclude(recipient_user__isnull=True).values("recipient_user_id").annotate(max_ts=Max("created_at")), "recipient_user_id", "max_ts")

        # Payments
        qs = PaymentTransaction.objects.filter(created_at__gte=cutoff)
        merge(qs.values("payer_user_id").annotate(max_ts=Max("created_at")), "payer_user_id", "max_ts")
        merge(qs.exclude(merchant_account_user__isnull=True).values("merchant_account_user_id").annotate(max_ts=Max("created_at")), "merchant_account_user_id", "max_ts")

        # Conversions
        merge(
            Conversion.objects.filter(created_at__gte=cutoff)
            .exclude(actor_user__isnull=True)
            .values("actor_user_id")
            .annotate(max_ts=Max("created_at")),
            "actor_user_id",
            "max_ts",
        )

        # Achievements
        merge(
            UserAchievement.objects.filter(earned_at__gte=cutoff)
            .values("user_id")
            .annotate(max_ts=Max("earned_at")),
            "user_id",
            "max_ts",
        )

        # Persist updates in batches
        if not latest:
            self.stdout.write("No recent activity found to backfill.")
            return

        self.stdout.write(self.style.NOTICE(f"Updating {len(latest)} users..."))
        to_update = []
        for uid, when in latest.items():
            try:
                user = User(id=uid, last_activity_at=when)
                to_update.append(user)
            except Exception:
                continue

        # Bulk update
        BATCH = 500
        from itertools import islice

        def chunks(seq, size):
            it = iter(seq)
            while True:
                chunk = list(islice(it, size))
                if not chunk:
                    break
                yield chunk

        total = 0
        for chunk in chunks(to_update, BATCH):
            User.objects.bulk_update(chunk, ["last_activity_at"], batch_size=BATCH)
            total += len(chunk)

        self.stdout.write(self.style.SUCCESS(f"Backfill complete. Users updated: {total}"))

