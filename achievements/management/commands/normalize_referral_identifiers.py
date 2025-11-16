import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from achievements.models import InfluencerReferral


def normalize_identifier(value: str) -> str:
    """Lowercase and strip non-alphanumeric characters so variants collapse."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


class Command(BaseCommand):
    help = (
        "Normalize historical influencer referral identifiers so legacy aliases "
        "map to a single canonical username."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--canonical",
            default="julianmoonluna",
            help="Canonical username that legacy aliases should map to.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report affected referrals without modifying the database.",
        )

    def handle(self, *args, **options):
        canonical_username: str = options["canonical"].strip()
        dry_run: bool = options["dry_run"]

        if not canonical_username:
            raise CommandError("Canonical username cannot be blank.")

        User = get_user_model()
        canonical_user = User.objects.filter(username=canonical_username).first()
        if not canonical_user:
            raise CommandError(
                f"Canonical user '{canonical_username}' does not exist in the database."
            )

        target_fingerprint = normalize_identifier(canonical_username)
        updated = 0
        skipped = 0

        self.stdout.write(
            f"Normalizing influencer referrals matching '{canonical_username}' "
            f"(dry_run={dry_run})"
        )

        queryset = InfluencerReferral.objects.all().only(
            "id", "referrer_identifier", "attribution_data"
        )

        for referral in queryset.iterator():
            legacy_identifier = (referral.referrer_identifier or "").strip()
            if not legacy_identifier:
                skipped += 1
                continue

            if normalize_identifier(legacy_identifier) != target_fingerprint:
                skipped += 1
                continue

            if (
                legacy_identifier == canonical_username
                and referral.referrer_user_id == canonical_user.id
            ):
                skipped += 1
                continue

            updated += 1
            self.stdout.write(
                f" - Referral #{referral.id}: '{legacy_identifier}' -> '{canonical_username}'"
            )

            if dry_run:
                continue

            attribution = dict(referral.attribution_data or {})
            attribution.setdefault("legacy_identifier", legacy_identifier)

            referral.referrer_identifier = canonical_username
            referral.referrer_user = canonical_user
            referral.attribution_data = attribution
            referral.save(
                update_fields=[
                    "referrer_identifier",
                    "referrer_user",
                    "attribution_data",
                    "updated_at",
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed. Updated {updated} referral(s); skipped {skipped}."
            )
        )
