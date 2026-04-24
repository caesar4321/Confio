from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Backfill signup_completed and referral_attached funnel events from durable referral tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Lookback window in days. Defaults to 90.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print counts without writing FunnelEvent rows.",
        )
        parser.add_argument(
            "--reroll",
            action="store_true",
            help="Rebuild FunnelDailyRollup rows for dates touched by the backfill.",
        )
        parser.add_argument(
            "--include-historical-referrals",
            action="store_true",
            help=(
                "Also synthesize referral_link signup/attach rows from UserReferral. "
                "Do not use for click-to-signup funnels unless historical clicks were "
                "also tracked for the same window."
            ),
        )

    def handle(self, *args, **options):
        from send.models import PhoneInvite
        from users.models_analytics import FunnelEvent
        from users.tasks import rollup_funnel_events

        days = int(options["days"])
        dry_run = bool(options["dry_run"])
        reroll = bool(options["reroll"])
        include_historical_referrals = bool(options["include_historical_referrals"])
        cutoff = timezone.now() - timedelta(days=days)
        touched_dates = set()

        def event_exists(event_name, user_id, source_type, dedupe_key):
            return FunnelEvent.objects.filter(
                event_name=event_name,
                user_id=user_id,
                source_type=source_type,
                properties__dedupe_key=dedupe_key,
            ).exists()

        def create_event(event_name, *, user, source_type, channel, properties, event_time):
            dedupe_key = properties["dedupe_key"]
            if event_exists(event_name, user.id, source_type, dedupe_key):
                return False
            if dry_run:
                touched_dates.add(event_time.date())
                return True

            event = FunnelEvent.objects.create(
                event_name=event_name,
                user=user,
                country=(getattr(user, "phone_country", "") or "")[:2].upper(),
                platform="",
                source_type=source_type,
                channel=channel,
                properties=properties,
            )
            FunnelEvent.objects.filter(pk=event.pk).update(created_at=event_time)
            touched_dates.add(event_time.date())
            return True

        referral_signup_created = 0
        referral_attached_created = 0
        send_invite_signup_created = 0
        send_invite_attached_created = 0

        with transaction.atomic():
            if include_historical_referrals:
                from achievements.models import UserReferral

                referrals = (
                    UserReferral.objects
                    .select_related("referred_user")
                    .filter(created_at__gte=cutoff, referred_user__isnull=False)
                    .exclude(status="inactive")
                    .order_by("created_at", "id")
                )
                for referral in referrals.iterator(chunk_size=500):
                    user = referral.referred_user
                    identifier = (referral.referrer_identifier or "").lstrip("@").strip().upper()
                    if not identifier:
                        continue
                    base_props = {
                        "referral_code": identifier,
                        "referral_type": "friend",
                        "attach_method": "backfill_user_referral",
                        "referral_id": referral.id,
                    }
                    if create_event(
                        "signup_completed",
                        user=user,
                        source_type="referral_link",
                        channel="backfill",
                        properties={
                            **base_props,
                            "dedupe_key": f"signup_completed:referral_link:{identifier}",
                        },
                        event_time=referral.created_at,
                    ):
                        referral_signup_created += 1
                    if create_event(
                        "referral_attached",
                        user=user,
                        source_type="referral_link",
                        channel="backfill",
                        properties={
                            **base_props,
                            "dedupe_key": f"referral_attached:referral_link:{identifier}",
                        },
                        event_time=referral.created_at,
                    ):
                        referral_attached_created += 1

            phone_invites = (
                PhoneInvite.objects
                .select_related("claimed_by", "inviter_user")
                .filter(claimed_by__isnull=False, claimed_at__gte=cutoff)
                .order_by("claimed_at", "id")
            )
            for invite in phone_invites.iterator(chunk_size=500):
                user = invite.claimed_by
                if user is None:
                    continue

                # Only count a send-invite signup if the claimant account was
                # created after this phone invite. Existing users can claim, but
                # they are not signup conversions for this funnel step.
                user_created_at = getattr(user, "created_at", None)
                if user_created_at and user_created_at >= invite.created_at and user_created_at >= cutoff:
                    if create_event(
                        "signup_completed",
                        user=user,
                        source_type="send_invite",
                        channel="backfill",
                        properties={
                            "invitation_id": invite.invitation_id,
                            "inviter_user_id": invite.inviter_user_id,
                            "dedupe_key": f"signup_completed:send_invite:{invite.invitation_id}",
                        },
                        event_time=user_created_at,
                    ):
                        send_invite_signup_created += 1

                if create_event(
                    "referral_attached",
                    user=user,
                    source_type="send_invite",
                    channel="backfill",
                    properties={
                        "invitation_id": invite.invitation_id,
                        "inviter_user_id": invite.inviter_user_id,
                        "dedupe_key": f"referral_attached:send_invite:{invite.invitation_id}",
                    },
                    event_time=invite.claimed_at or invite.updated_at,
                ):
                    send_invite_attached_created += 1

            if dry_run:
                transaction.set_rollback(True)

        if reroll and not dry_run:
            for date in sorted(touched_dates):
                rollup_funnel_events(str(date))

        self.stdout.write(self.style.SUCCESS(
            "Backfill complete: "
            f"referral signup={referral_signup_created}, "
            f"referral attached={referral_attached_created}, "
            f"send_invite signup={send_invite_signup_created}, "
            f"send_invite attached={send_invite_attached_created}, "
            f"dates={len(touched_dates)}, dry_run={dry_run}, reroll={reroll}, "
            f"include_historical_referrals={include_historical_referrals}"
        ))
