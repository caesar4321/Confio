"""Record on-chain proof for direct USDC transfers so they can count in the
public "Movido" metric. Read-only against Algorand; rerunnable.

    python manage.py verify_direct_transfers --dry-run
    python manage.py verify_direct_transfers
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Match direct USDC deposits/withdrawals to Algorand transfers and store proof'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report only; write nothing')

    def handle(self, *args, dry_run=False, **options):
        from django.core.cache import cache
        from blockchain.algorand_client import AlgorandClient
        from ramps.direct_transfers import verify_direct_transfers

        outcome = verify_direct_transfers(AlgorandClient().indexer, dry_run=dry_run)
        for reason, n in sorted(outcome.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f'{reason}: {n}')
        if not dry_run and (outcome.get('verified') or outcome.get('proofs_revoked')):
            # The public figure is cached for 10 minutes: show added AND
            # revoked proofs now, never serve volume that was just removed.
            cache.delete('fund_flow_stats_v4')
            self.stdout.write('fund_flow_stats cache cleared')
