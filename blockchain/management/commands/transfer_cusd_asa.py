"""
Transfer cUSD ASA directly from sponsor/admin to a recipient.

Usage:
  python manage.py transfer_cusd_asa --amount 4000 --recipient <ALGOWALLET>

Notes:
- This performs a plain ASA transfer (bypasses app method checks).
- Requires ALGORAND_SPONSOR_MNEMONIC and cUSD ASA to be configured in settings.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from algosdk import mnemonic, account
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation


class Command(BaseCommand):
    help = 'Transfer cUSD ASA directly from sponsor/admin to recipient.'

    def add_arguments(self, parser):
        parser.add_argument('--amount', type=Decimal, required=True, help='Amount of cUSD to transfer')
        parser.add_argument('--recipient', type=str, required=True, help='Recipient Algorand address')

    def handle(self, *args, **options):
        amount: Decimal = options['amount']
        recipient: str = options['recipient']

        asa_id = getattr(settings, 'ALGORAND_CUSD_ASSET_ID', None)
        algod_addr = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', None)
        algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')
        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        if not (asa_id and algod_addr and sponsor_mn):
            self.stdout.write(self.style.ERROR('Missing settings: ensure ALGORAND_CUSD_ASSET_ID, ALGORAND_ALGOD_ADDRESS, ALGORAND_SPONSOR_MNEMONIC are set'))
            return

        sk = mnemonic.to_private_key(sponsor_mn)
        sender = account.address_from_private_key(sk)
        client = algod.AlgodClient(algod_token, algod_addr)

        sp = client.suggested_params()
        # Convert to micro (6 decimals)
        amt_units = int(amount * Decimal('1000000'))

        self.stdout.write(self.style.SUCCESS('\n=== cUSD ASA Transfer ==='))
        self.stdout.write(f'Sender: {sender[:12]}...')
        self.stdout.write(f'Recipient: {recipient[:12]}...')
        self.stdout.write(f'Amount: {amount} cUSD ({amt_units} micro)')

        try:
            txn = AssetTransferTxn(sender=sender, sp=sp, receiver=recipient, amt=amt_units, index=int(asa_id))
            signed = txn.sign(sk)
            txid = client.send_transaction(signed)
            wait_for_confirmation(client, txid, 10)
            self.stdout.write(self.style.SUCCESS(f'✅ Transfer submitted. TxID: {txid}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Transfer failed: {e}'))
            return

