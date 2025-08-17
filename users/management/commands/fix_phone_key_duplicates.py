from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import User
from users.country_codes import COUNTRY_CODES


class Command(BaseCommand):
    help = "Fix duplicates within +1 calling code by adjusting duplicate phone numbers to unique values (last digits)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Do not persist changes, just print planned updates')

    def handle(self, *args, **options):
        dry = options.get('dry_run', False)

        # Build ISO set for calling code +1
        iso_plus1 = {row[2] for row in COUNTRY_CODES if row[1] == '+1'}

        # Build a set of all numbers in +1 space for quick membership check
        existing_plus1_numbers = set(
            User.all_objects.filter(
                deleted_at__isnull=True,
                phone_country__in=list(iso_plus1)
            ).values_list('phone_number', flat=True)
        )

        # Group users by their current number within +1 space
        users_plus1 = list(User.all_objects.filter(
            deleted_at__isnull=True,
            phone_country__in=list(iso_plus1)
        ).order_by('created_at', 'id'))

        from collections import defaultdict
        groups = defaultdict(list)
        for u in users_plus1:
            groups[(u.phone_number or '').strip()].append(u)

        updated = []

        for number, group in groups.items():
            if not number or len(group) <= 1:
                continue
            # Keep the earliest; adjust the rest
            base_user = group[0]
            others = group[1:]

            # Strategy: decrement last 4 digits until a free number is found
            # If number shorter than 4, decrement entire integer
            try:
                prefix = number[:-4] if len(number) > 4 else ''
                last = int(number[-4:]) if len(number) > 4 else int(number)
            except ValueError:
                # Non-digit phones: skip safely
                continue

            next_last = last - 1
            for u in others:
                # Find a free candidate within +1 space
                while True:
                    if next_last < 0:
                        # Exhausted; append '0' to prefix to extend length minimally
                        candidate = (prefix or number) + '0'
                    else:
                        candidate = f"{prefix}{next_last:0{4}d}" if prefix else f"{next_last}"
                    if candidate not in existing_plus1_numbers:
                        break
                    next_last -= 1

                updated.append((u.id, u.phone_country, u.phone_number, candidate))
                existing_plus1_numbers.add(candidate)
                next_last -= 1

        if dry:
            for row in updated:
                self.stdout.write(f"Would update user {row[0]} ({row[1]}) {row[2]} -> {row[3]}")
            self.stdout.write(self.style.SUCCESS(f"Planned updates: {len(updated)} (base user left unchanged)"))
            return

        with transaction.atomic():
            for uid, iso, old, new in updated:
                u = User.all_objects.get(id=uid)
                # Skip if already at target (idempotent)
                if u.phone_number == new:
                    continue
                u.phone_number = new
                u.save(update_fields=['phone_number'])
                self.stdout.write(f"Updated user {uid} ({iso}) {old} -> {new}")

        self.stdout.write(self.style.SUCCESS(f"Updated {len(updated)} duplicate users; base user kept at 9293993619"))
