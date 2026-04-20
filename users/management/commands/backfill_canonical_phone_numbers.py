from django.core.management.base import BaseCommand

from users.models import User
from users.phone_utils import canonicalize_phone_digits, normalize_phone


class Command(BaseCommand):
    help = "Backfill canonical phone_number and phone_key values for users in a given country."

    def add_arguments(self, parser):
        parser.add_argument(
            "--country",
            default="AR",
            help="ISO alpha-2 country to backfill (default: AR).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without saving them.",
        )

    def handle(self, *args, **options):
        country = (options.get("country") or "").upper()
        dry_run = bool(options.get("dry_run"))

        users = list(
            User.all_objects.filter(
                deleted_at__isnull=True,
                phone_country=country,
            ).exclude(phone_number__isnull=True).exclude(phone_number="")
        )

        changed = 0
        for user in users:
            canonical_phone = canonicalize_phone_digits(user.phone_number or "", user.phone_country or "")
            canonical_key = normalize_phone(canonical_phone, user.phone_country or "")

            if canonical_phone == (user.phone_number or "") and canonical_key == (user.phone_key or ""):
                continue

            changed += 1
            self.stdout.write(
                f"user={user.id} @{user.username} "
                f"{user.phone_number}/{user.phone_key} -> {canonical_phone}/{canonical_key}"
            )

            if dry_run:
                continue

            user.phone_number = canonical_phone
            user.phone_key = canonical_key
            user.save(update_fields=["phone_number", "phone_key", "updated_at"])

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: {changed} users would be updated."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated {changed} users."))
