"""
Transfer CONFIO ASA directly from sponsor/admin to a recipient.

Usage:
  python manage.py transfer_confio_asa --amount 5000 --recipient <ALGOWALLET>

Notes:
- Performs a plain ASA transfer (no app involvement).
- Requires ALGORAND_SPONSOR_MNEMONIC and ALGORAND_CONFIO_ASSET_ID in settings.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from algosdk import mnemonic, account
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation


class Command(BaseCommand):
    help = 'Transfer CONFIO ASA directly from sponsor/admin to recipient.'

    def add_arguments(self, parser):
        parser.add_argument('--amount', type=Decimal, required=True, help='Amount of CONFIO to transfer')
        parser.add_argument('--recipient', type=str, required=True, help='Recipient Algorand address')
        parser.add_argument('--note', type=str, required=False, default='', help='Optional note')

    def handle(self, *args, **options):
        amount: Decimal = options['amount']
        recipient: str = options['recipient']
        note: str = options['note']

        asa_id = int(getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0) or 0)
        algod_addr = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', None)
        algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '') or ''
        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        if not (asa_id and algod_addr and sponsor_mn):
            self.stdout.write(self.style.ERROR('Missing settings: ensure ALGORAND_CONFIO_ASSET_ID, ALGORAND_ALGOD_ADDRESS, ALGORAND_SPONSOR_MNEMONIC are set'))
            return

        sk = mnemonic.to_private_key(sponsor_mn)
        sender = account.address_from_private_key(sk)
        client = algod.AlgodClient(algod_token, algod_addr)

        # Fetch decimals for conversion
        try:
            info = client.asset_info(asa_id)
            decimals = int((info.get('params') or {}).get('decimals', 6))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to fetch CONFIO asset info: {e}'))
            return

        sp = client.suggested_params()
        amt_units = int(amount * (Decimal(10) ** decimals))

        self.stdout.write(self.style.SUCCESS('\n=== CONFIO ASA Transfer ==='))
        self.stdout.write(f'Sender:    {sender[:12]}...')
        self.stdout.write(f'Recipient: {recipient[:12]}...')
        self.stdout.write(f'Amount:    {amount} CONFIO ({amt_units} base units; decimals={decimals})')

        # Ensure recipient is opted in
        try:
            client.account_asset_info(recipient, asa_id)
        except Exception:
            self.stdout.write(self.style.ERROR('Recipient is not opted into CONFIO ASA'))
            return

        try:
            txn = AssetTransferTxn(sender=sender, sp=sp, receiver=recipient, amt=amt_units, index=asa_id, note=note.encode() if note else None)
            signed = txn.sign(sk)
            txid = client.send_transaction(signed)
            wait_for_confirmation(client, txid, 10)
            self.stdout.write(self.style.SUCCESS(f'✅ Transfer submitted. TxID: {txid}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Transfer failed: {e}'))
            return

