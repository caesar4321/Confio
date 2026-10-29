"""Seed User.country for accounts created before the column (idempotent).

Residence (90-day IP majority) when known, else the verified phone country.
Accounts that already have a country are left alone.

    myvenv/bin/python manage.py backfill_residence_country [--dry-run]
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from users.residence import backfill_country


class Command(BaseCommand):
    help = 'Seed User.country from IP residence, else the legacy phone country.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, dry_run=False, **options):
        from django.db import transaction
        from collections import Counter
        User = get_user_model()
        sources = Counter()
        qs = User.objects.filter(country__isnull=True)
        total = qs.count()
        with transaction.atomic():
            for user in qs.iterator(chunk_size=500):
                if backfill_country(user):
                    sources[user.country_source] += 1
                else:
                    sources['unknown'] += 1
            if dry_run:
                transaction.set_rollback(True)
        self.stdout.write(f'{"DRY RUN " if dry_run else ""}accounts without country: {total}; {dict(sources)}')
