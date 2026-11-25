"""
Rebuild the Cuenta inteligente trade rows (inbox.SmartAccountTrade) indexed before 2026-11-25's fix.

relayTrade logs Traded and RelayTraded with the same amounts. The indexer counted RelayTraded as the trade
(reading names it does not store: 0 units) and left the Traded unpriced once the node pruned its block
("missing trie node"), so hands-off sells never indexed and buys had no units. Now Traded is the trade (priced
from the receipt's logged share price when the state is gone) and RelayTraded a marker.

This turns stored RelayTraded rows into markers and indexes every trade event still unindexed. Idempotent.

  myvenv/bin/python manage.py reindex_account_trades            # dry run
  myvenv/bin/python manage.py reindex_account_trades --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Re-index Cuenta inteligente trades (RelayTraded as marker, Traded priced from its receipt)"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the changes (default: dry run)')

    def handle(self, *args, **options):
        from smart_account.models import SmartAccountEvent

        from inbox.account_trades import TRADE_EVENTS, decode, index_event
        from inbox.models import SmartAccountTrade

        apply = options['apply']
        wrong = SmartAccountTrade.objects.filter(event__name='RelayTraded').exclude(kind='')
        self.stdout.write(f'RelayTraded rows counted as trades: {wrong.count()}')
        for row in wrong:
            self.stdout.write(f'  {row.event.tx_hash} {row.kind} {row.symbol} units={row.units} usd={row.usd}')
        missing = list(SmartAccountEvent.objects.filter(name__in=TRADE_EVENTS, portfolio_trade__isnull=True)
                       .order_by('block_number', 'log_index'))
        self.stdout.write(f'Trade events not indexed: {len(missing)}')
        for event in missing:
            try:
                fields = decode(event, allow_rpc=True)
                said = f"{fields['kind'] or 'no trade'} {fields['symbol']} units={fields['units']} usd={fields['usd']}"
            except Exception as exc:  # noqa: BLE001 - reported, left pending
                said = f'still unpriced: {type(exc).__name__}: {str(exc)[:120]}'
            self.stdout.write(f'  {event.name} {event.tx_hash}#{event.log_index}: {said}')
        if not apply:
            self.stdout.write(self.style.WARNING('DRY RUN: nothing written. Re-run with --apply.'))
            return
        with transaction.atomic():
            changed = wrong.update(symbol='', kind='', units=Decimal('0'), usd=None)
        indexed = sum(1 for event in missing if index_event(event, allow_rpc=True) is not None)
        self.stdout.write(self.style.SUCCESS(f'markers: {changed}, newly indexed: {indexed}'))
