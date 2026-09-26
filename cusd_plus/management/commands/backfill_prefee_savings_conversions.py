"""Write the missing conversion rows for pre-fee cUSD+ perimeter crossings.

Before the vault emitted SavingsEntrySettled/SavingsExitSettled (early
September 2026), cUSD+ sends that redeem to USDT (send_redeem), direct
redemptions (redeem), USDT merchant payments funded from cUSD+ (pay_usdt)
and some subscriptions left no Conversion row, so Movido missed them
(reconciled 2026-09-25: 28 exits, US$722.67; 1 entry, US$2.65).

A batch qualifies only when: it is confirmed, no live conversion carries its
hash, the receipt succeeded with NO fee event (the live reconciler owns those),
it holds exactly one cUSD+ burn (exit) or mint (entry) for the batch wallet,
and the USDT the vault moved is within 3% of the shares moved. The row mirrors
what _reconcile_cusd_fee_event writes today, at the batch's own time.
Dry run by default; --apply writes.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
ZERO = '0x' + '0' * 40
WAD = Decimal(10 ** 18)
TOLERANCE = Decimal('0.03')
EXIT_KINDS = ('send_redeem', 'redeem', 'pay_usdt')
ENTRY_KINDS = ('subscribe',)


def _transfers(receipt, token):
    for log in receipt.get('logs') or []:
        topics = log.get('topics') or []
        if ((log.get('address') or '').lower() != token or len(topics) < 3
                or topics[0].lower() != TRANSFER):
            continue
        yield ('0x' + topics[1][-40:].lower(), '0x' + topics[2][-40:].lower(),
               Decimal(int(log.get('data') or '0x0', 16)) / WAD, int(log.get('logIndex') or '0x0', 16))


def crossing(batch, receipt, *, vault, usdt):
    """(direction, dollars, share log index) or (None, reason, None)."""
    from cusd_plus.tasks import _cusd_fee_events

    if not receipt or receipt.get('status') != '0x1':
        return None, 'receipt_failed', None
    if _cusd_fee_events(receipt):
        return None, 'has_fee_event', None
    wallet = (batch.user_bsc_address or '').lower()
    entry = batch.kind in ENTRY_KINDS
    shares = [(amount, index) for frm, to, amount, index in _transfers(receipt, vault)
              if (frm, to) == ((ZERO, wallet) if entry else (wallet, ZERO))]
    if len(shares) != 1:
        return None, 'share_moves_%d' % len(shares), None
    usdt_moved = sum((amount for frm, to, amount, _ in _transfers(receipt, usdt)
                      if (to if entry else frm) == vault), Decimal(0))
    share_amount, index = shares[0]
    if usdt_moved <= 0 or abs(usdt_moved - share_amount) > share_amount * TOLERANCE:
        return None, 'amount_unverified', None
    return ('entry' if entry else 'exit'), usdt_moved, index


class Command(BaseCommand):
    help = 'Backfill conversion rows for pre-fee cUSD+ entries/exits (dry run unless --apply)'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        from blockchain.models import SponsoredBatch
        from conversion.models import Conversion
        from cusd_plus import vault as cusd_plus_vault
        from cusd_plus.tasks import _rpc
        from users.models import Account

        vault = (cusd_plus_vault.vault_address() or '').lower()
        usdt = cusd_plus_vault.usdt_address().lower()
        apply = options['apply']
        totals, skipped = {'entry': Decimal(0), 'exit': Decimal(0)}, {}
        counts = {'entry': 0, 'exit': 0}
        batches = SponsoredBatch.objects.filter(
            status='confirmed', kind__in=EXIT_KINDS + ENTRY_KINDS,
        ).exclude(tx_hash='').order_by('created_at')
        for batch in batches:
            if Conversion.objects.filter(to_transaction_hash__iexact=batch.tx_hash, is_deleted=False).exists():
                continue
            direction, amount, index = crossing(
                batch, _rpc('eth_getTransactionReceipt', [batch.tx_hash]), vault=vault, usdt=usdt)
            account = Account.objects.filter(
                bsc_address__iexact=batch.user_bsc_address, deleted_at__isnull=True,
            ).select_related('user', 'business').first()
            if direction is None or account is None:
                reason = amount if direction is None else 'no_account'
                skipped[reason] = skipped.get(reason, 0) + 1
                self.stdout.write(f'skip {batch.kind} {batch.tx_hash} ({reason})')
                continue
            counts[direction] += 1
            totals[direction] += amount
            self.stdout.write(f'{direction} {batch.kind} {batch.created_at:%Y-%m-%d} {amount:.6f} {batch.tx_hash}')
            if not apply:
                continue
            is_business = account.account_type == 'business'
            savings = 'CUSD_PLUS_BSC'
            display = amount.quantize(Decimal('0.000001'))
            with transaction.atomic():
                Conversion.objects.create(
                    actor_user=None if is_business else account.user,
                    actor_business=account.business if is_business else None,
                    actor_type='business' if is_business else 'user',
                    actor_display_name=account.display_name or '',
                    actor_address=batch.user_bsc_address,
                    user_bsc_address=batch.user_bsc_address,
                    conversion_type='to_savings' if direction == 'entry' else 'from_savings',
                    source='external_deposit' if direction == 'entry' else 'convert',
                    from_asset_id='USDT_BSC' if direction == 'entry' else savings,
                    to_asset_id=savings if direction == 'entry' else 'USDT_BSC',
                    perimeter_direction=direction,
                    from_amount=display, to_amount=display,
                    exchange_rate=Decimal('1'), fee_amount=Decimal('0'),
                    gross_amount_exact=amount, fee_amount_exact=Decimal(0), net_amount_exact=amount,
                    conversion_fee_bps=0, quoted_cost_pct=Decimal('0'),
                    contract_event_index=index,
                    from_transaction_hash=batch.tx_hash, to_transaction_hash=batch.tx_hash,
                    status='COMPLETED', created_at=batch.created_at, completed_at=batch.created_at,
                )
        self.stdout.write(
            f"{'APPLIED' if apply else 'DRY RUN'}: exits {counts['exit']} US${totals['exit']:.2f}, "
            f"entries {counts['entry']} US${totals['entry']:.2f}, skipped {skipped}")
        if apply and (counts['exit'] or counts['entry']):
            from django.core.cache import cache
            cache.delete_many(['fund_flow_stats_v4', 'landing_stats_v3'])
