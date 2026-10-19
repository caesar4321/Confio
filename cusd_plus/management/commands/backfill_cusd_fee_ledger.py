"""Fill conversion.CusdFeeEvent with every finalized cUSD perimeter fee
emitted before the fee ledger existed.

The live scanner (monitor_cusd_fee_events) records new events from its
cursor onward; this replays the vault's logs from CUSD_VAULT_FEE_EVENTS_
START_BLOCK (or --from-block) up to that cursor. Idempotent on
(tx_hash, log_index): safe to re-run, and safe while the scanner runs.

    manage.py backfill_cusd_fee_ledger            # dry run: counts
    manage.py backfill_cusd_fee_ledger --apply

Public BSC endpoints cap eth_getLogs at ~50 blocks (and rate-limit), so a
months-long range is impractical. --from-conversions instead replays the
receipt of every transaction the scanner already reconciled into a
Conversion row (exact logs, block and time). It cannot recover a past
permissionless exit by a non-Confío address, which was never stored.
"""
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from eth_utils import keccak

TOPICS = [
    '0x' + keccak(text=sig).hex() for sig in (
        'MintedWithFee(address,address,uint256,uint256,uint256,uint256)',
        'RedeemedWithFee(address,address,uint256,uint256,uint256,uint256)',
        'SavingsEntrySettled(uint256,uint256,uint256,uint256)',
        'SavingsExitSettled(address,uint256,uint256,uint256,uint256)',
    )
]


class Command(BaseCommand):
    help = 'Backfill the cUSD fee ledger from finalized vault logs'

    def add_arguments(self, parser):
        parser.add_argument('--from-block', type=int, default=0)
        parser.add_argument('--to-block', type=int, default=0, help='default: the live scanner cursor')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--from-conversions', action='store_true',
                            help='replay receipts of reconciled Conversion rows instead of scanning logs')

    def handle(self, *args, **options):
        from conversion.models import CusdFeeScanState
        from cusd_plus.fee_ledger import block_time, record_fee_events
        from cusd_plus.tasks import (
            _cusd_fee_events, _finality_depth, _finalized_block_number, _get_logs_chunked, _rpc,
        )

        cusd = (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()
        if not cusd:
            raise CommandError('CUSD_VAULT_ADDRESS is not configured')
        if options['from_conversions']:
            return self._from_conversions(cusd, options['apply'])
        start = options['from_block'] or int(getattr(settings, 'CUSD_VAULT_FEE_EVENTS_START_BLOCK', 0) or 0)
        if start <= 0:
            raise CommandError('no start block: pass --from-block or set CUSD_VAULT_FEE_EVENTS_START_BLOCK')
        end = options['to_block']
        if not end:
            state = CusdFeeScanState.objects.filter(chain_id=int(getattr(settings, 'BSC_CHAIN_ID', 56))).first()
            end = state.last_finalized_block if state else 0
        finalized = _finalized_block_number()
        if finalized is None:
            finalized = max(0, int(_rpc('eth_blockNumber', []), 16) - _finality_depth())
        if end > finalized:
            # Never record events from blocks that could still reorg away:
            # nothing would ever remove them from the ledger.
            raise CommandError(f'--to-block {end} is past the finalized block {finalized}')
        if end < start:
            raise CommandError(f'nothing to backfill ({start}..{end})')

        found = stored = 0
        times: dict = {}
        for lo in range(start, end + 1, 2_000):
            hi = min(end, lo + 1_999)
            by_tx = defaultdict(list)
            for log in _get_logs_chunked(lo, hi, [TOPICS], address=cusd):
                if log.get('transactionHash'):
                    by_tx[log['transactionHash']].append(log)
            for tx_hash, logs in by_tx.items():
                found += len(_cusd_fee_events({'logs': logs}))
                if options['apply']:
                    for log in logs:
                        block_time(_rpc, int(log.get('blockNumber', '0x0'), 16), times)
                    stored += record_fee_events(tx_hash, logs, times)
        self.stdout.write(f'blocks {start}..{end}: {found} fee events on chain')
        if options['apply']:
            self.stdout.write(self.style.SUCCESS(f'stored {stored} new ledger rows'))
        else:
            self.stdout.write(self.style.WARNING('DRY RUN: re-run with --apply to store them'))

    def _from_conversions(self, cusd, apply):
        import time

        from conversion.models import Conversion
        from cusd_plus.fee_ledger import block_time, record_fee_events
        from cusd_plus.tasks import _cusd_fee_events, _rpc

        hashes = sorted({
            h.lower() for h in Conversion.objects.filter(contract_event_index__isnull=False)
            .exclude(to_transaction_hash='').values_list('to_transaction_hash', flat=True) if h
        })
        found = stored = missing = 0
        times: dict = {}
        for tx_hash in hashes:
            receipt = None
            for attempt in range(4):
                try:
                    receipt = _rpc('eth_getTransactionReceipt', [tx_hash])
                    break
                except Exception:  # noqa: BLE001 — rate limits: back off and retry
                    time.sleep(1.5 * (attempt + 1))
            if not receipt or receipt.get('status') != '0x1':
                missing += 1
                continue
            logs = [log for log in receipt.get('logs') or [] if (log.get('address') or '').lower() == cusd]
            found += len(_cusd_fee_events({'logs': logs}))
            if apply and logs:
                block_time(_rpc, int(receipt.get('blockNumber', '0x0'), 16), times)
                stored += record_fee_events(tx_hash, logs, times)
            time.sleep(0.2)
        self.stdout.write(f'{len(hashes)} reconciled transactions: {found} fee events, '
                          f'{missing} receipts unavailable')
        if apply:
            self.stdout.write(self.style.SUCCESS(f'stored {stored} new ledger rows'))
        else:
            self.stdout.write(self.style.WARNING('DRY RUN: re-run with --apply to store them'))
