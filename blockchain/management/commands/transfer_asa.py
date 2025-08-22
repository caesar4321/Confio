"""
Transfer an Algorand ASA from the sponsor/admin account to one or more recipients.

Usage examples:
  python manage.py transfer_asa --asset-id 744150851 \
    --recipients P7...ZZU,MNYI...34EWQ,TIU6...JAHM \
    --amounts 12.34,56.78,90.12

Notes:
- Uses ALGORAND_ALGOD_ADDRESS and ALGORAND_SPONSOR_MNEMONIC from settings.
- Assumes recipients are opted-in to the ASA.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from algosdk.v2client import algod
from algosdk import mnemonic
from algosdk.transaction import AssetTransferTxn
from algosdk import encoding as algo_encoding
import base64


class Command(BaseCommand):
    help = 'Transfer an Algorand ASA from sponsor/admin to recipients (comma-separated).'

    def add_arguments(self, parser):
        parser.add_argument('--asset-id', type=int, required=True, help='ASA ID to transfer')
        parser.add_argument('--recipients', type=str, required=True, help='Comma-separated list of Algorand addresses')
        parser.add_argument('--amounts', type=str, required=True, help='Comma-separated list of decimal amounts (same order as recipients)')

    def handle(self, *args, **options):
        asset_id = int(options['asset_id'])
        recipients = [x.strip() for x in options['recipients'].split(',') if x.strip()]
        amounts = [Decimal(x.strip()) for x in options['amounts'].split(',') if x.strip()]

        if len(recipients) != len(amounts):
            self.stdout.write(self.style.ERROR('Recipients and amounts must have the same length'))
            return

        algod_addr = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', None)
        algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')
        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)

        if not algod_addr or not sponsor_mn:
            self.stdout.write(self.style.ERROR('Missing ALGORAND_ALGOD_ADDRESS or ALGORAND_SPONSOR_MNEMONIC in settings'))
            return

        try:
            sk = mnemonic.to_private_key(sponsor_mn)
            from algosdk import account
            sender = account.address_from_private_key(sk)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to derive sponsor key: {e}'))
            return

        client = algod.AlgodClient(algod_token, algod_addr)

        # Fetch decimals for the asset to convert human amount to base units
        try:
            info = client.asset_info(asset_id)
            decimals = info['params'].get('decimals', 0)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to fetch asset info for {asset_id}: {e}'))
            return

        self.stdout.write(self.style.SUCCESS('=== ASA Transfer ==='))
        self.stdout.write(f'Asset ID: {asset_id} (decimals={decimals})')
        self.stdout.write(f'Sender: {sender[:12]}...')

        for r, a in zip(recipients, amounts):
            try:
                sp = client.suggested_params()
                base = int(a * (Decimal(10) ** Decimal(decimals)))
                txn = AssetTransferTxn(sender=sender, sp=sp, receiver=r, amt=base, index=asset_id)
                stx = txn.sign(sk)
                txid = client.send_transaction(stx)
                self.stdout.write(self.style.SUCCESS(f'Submitted transfer {a} -> {r[:12]}... (txid={txid})'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed transfer to {r[:12]}...: {e}'))
