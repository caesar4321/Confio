"""Prove BSC arrivals for completed Koywe Dollar+ deposits from the hash
Koywe reports (see ramps/bsc_provider_hash.py). Dry run by default.

    python manage.py attach_koywe_bsc_arrivals
    python manage.py attach_koywe_bsc_arrivals --apply
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Attach verified BSC arrivals to Koywe Dollar+ deposits using Koywe's reported txHash"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the proof (default: dry run)')

    def handle(self, *args, apply=False, **options):
        from collections import Counter
        from django.core.cache import cache
        from cusd_plus.tasks import _rpc
        from ramps.bsc_provider_hash import attach_arrival, eligible_ramps
        from ramps.koywe_client import KoyweClient
        from ramps.signals import find_provider_tx_hash

        client = KoyweClient()
        outcome = Counter()
        seen = set()  # one transfer proves one ramp, in dry runs too
        for ramp in eligible_ramps().order_by('created_at'):
            tx_hash = find_provider_tx_hash(ramp.metadata or {})
            if not tx_hash and ramp.provider_order_id:
                try:  # not stored yet: ask Koywe for the order (read-only)
                    order = client.get_order(order_id=ramp.provider_order_id,
                                             email=(ramp.metadata or {}).get('auth_email'))
                    tx_hash = find_provider_tx_hash(order)
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f'ramp {ramp.pk}: Koywe lookup failed ({type(exc).__name__})')
            try:
                outcome[attach_arrival(ramp, _rpc, tx_hash=tx_hash, apply=apply, seen=seen)] += 1
            except Exception as exc:  # noqa: BLE001 — one RPC failure must not stop the run
                self.stderr.write(f'ramp {ramp.pk}: verification failed ({type(exc).__name__})')
                outcome['error'] += 1
        for key, value in outcome.most_common():
            self.stdout.write(f'{key}: {value}')
        if apply and outcome.get('verified'):
            # Arrival proof feeds the provider deposit metric (landing stats);
            # Movido is measured from conversions and is unaffected.
            cache.delete('landing_stats_v3')
            self.stdout.write('public stat caches cleared')
