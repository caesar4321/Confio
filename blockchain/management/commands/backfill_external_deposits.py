"""
Backfill SendTransaction rows for inbound external deposits (cUSD, CONFIO)
that were already processed by the indexer scanner but failed to persist
because of earlier issues (e.g., timestamp parsing).

Usage:
  python manage.py backfill_external_deposits --rounds 2000

Notes:
- Scans ProcessedIndexerTransaction for cUSD/CONFIO to tracked user addresses.
- Skips if a SendTransaction with the same transaction_hash already exists.
- Does NOT create notifications (assumed already sent at scan time).
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.cache import cache
from datetime import datetime, timezone as py_tz

from blockchain.algorand_client import AlgorandClient
from blockchain.models import ProcessedIndexerTransaction
from users.models import Account
from send.models import SendTransaction


class Command(BaseCommand):
    help = 'Backfill SendTransaction for inbound cUSD/CONFIO external deposits from processed indexer markers.'

    def add_arguments(self, parser):
        parser.add_argument('--rounds', type=int, default=2000, help='How many rounds to look back from latest indexer health')

    def handle(self, *args, **options):
        rounds = int(options['rounds'])

        client = AlgorandClient()
        indexer = client.indexer
        algod = client.algod

        CUSD_ID = settings.ALGORAND_CUSD_ASSET_ID
        CONFIO_ID = settings.ALGORAND_CONFIO_ASSET_ID
        asset_ids = [aid for aid in [CUSD_ID, CONFIO_ID] if aid]
        if not asset_ids:
            self.stdout.write(self.style.ERROR('Missing CUSD/CONFIO asset IDs in settings'))
            return

        # Build tracked address set
        addresses = set(
            Account.objects.filter(
                deleted_at__isnull=True,
                algorand_address__isnull=False
            ).values_list('algorand_address', flat=True)
        )
        if not addresses:
            self.stdout.write(self.style.WARNING('No user addresses to backfill'))
            return

        # Determine sponsor address (treated as external)
        sponsor_address = None
        try:
            from algosdk import mnemonic as _mn, account as _acct
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if sponsor_mn:
                sponsor_address = _acct.address_from_private_key(_mn.to_private_key(sponsor_mn))
        except Exception:
            sponsor_address = None

        # Determine current round and min_round
        try:
            current_round = indexer.health().get('round') or algod.status().get('last-round', 0)
        except Exception:
            current_round = algod.status().get('last-round', 0)
        min_round = max(0, int(current_round) - rounds)

        # Fetch decimals for assets
        decimals_map = {}
        for aid in asset_ids:
            try:
                info = algod.asset_info(aid)
                decimals_map[aid] = int((info.get('params') or {}).get('decimals', 6))
            except Exception:
                decimals_map[aid] = 6

        # Gather processed markers in range
        markers = ProcessedIndexerTransaction.objects.filter(
            asset_id__in=asset_ids,
            confirmed_round__gte=min_round,
            receiver__in=addresses,
        ).order_by('confirmed_round')

        created = 0
        skipped = 0
        errors = 0

        for m in markers:
            # Skip if sender is a Confío address (internal) and not sponsor
            if m.sender in addresses and (not sponsor_address or m.sender != sponsor_address):
                skipped += 1
                continue

            # If we already have a send row for this txid, skip
            if SendTransaction.all_objects.filter(transaction_hash=m.txid).exists():
                skipped += 1
                continue

            # Load tx from indexer for amount + round-time
            try:
                tx_resp = indexer.transaction(m.txid)
                itx = (tx_resp or {}).get('transaction') or {}
                inner = itx.get('asset-transfer-transaction') or {}
                amount_base = int(inner.get('amount', 0))
                xaid = int(inner.get('asset-id') or 0)
                dec = int(decimals_map.get(xaid, 6))
                amount = (Decimal(amount_base) / (Decimal(10) ** dec)).quantize(Decimal('0.000001'))
                rtime = itx.get('round-time') or 0
                created_at = datetime.fromtimestamp(int(rtime), tz=py_tz.utc) if rtime else datetime.now(tz=py_tz.utc)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to fetch tx {m.txid}: {e}'))
                errors += 1
                continue

            # Resolve account for receiver
            account = Account.objects.filter(algorand_address=m.receiver, deleted_at__isnull=True).select_related('user', 'business').first()
            if not account:
                skipped += 1
                continue

            token_type = 'CUSD' if xaid == CUSD_ID else 'CONFIO'
            idempotency_key = f'ALG:{m.txid}:{m.intra or 0}'

            # Build kwargs (mirror scanner)
            send_kwargs = {
                'sender_user': None,
                'recipient_user': account.user if account.account_type == 'personal' else None,
                'sender_business': None,
                'recipient_business': account.business if account.account_type == 'business' else None,
                'sender_type': 'external',
                'recipient_type': 'business' if account.account_type == 'business' else 'user',
                'sender_display_name': 'Billetera externa',
                'recipient_display_name': account.display_name,
                'sender_phone': '',
                'recipient_phone': getattr(account.user, 'phone_number', '') if account.account_type == 'personal' else '',
                'sender_address': m.sender or '',
                'recipient_address': m.receiver or '',
                'amount': amount,
                'token_type': token_type,
                'memo': f'Depósito {token_type} recibido',
                'status': 'CONFIRMED',
                'transaction_hash': m.txid,
                'idempotency_key': idempotency_key,
                'error_message': '',
                'created_at': created_at,
            }

            try:
                SendTransaction.all_objects.create(**send_kwargs)
                created += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to create send for {m.txid}: {e}'))
                errors += 1

        self.stdout.write(self.style.SUCCESS(f'Backfill complete: created={created}, skipped={skipped}, errors={errors}'))

