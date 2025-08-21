from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from algosdk.v2client import algod


class Command(BaseCommand):
    help = "Check if an Algorand address is opted-in to configured cUSD and CONFIO ASAs (and show balances)."

    def add_arguments(self, parser):
        parser.add_argument('address', type=str, help='Algorand address to check')
        parser.add_argument('--asset', type=int, default=0, help='Optional specific ASA id to check')

    def handle(self, *args, **options):
        address = options['address']
        specific_asset = int(options.get('asset') or 0)

        algod_address = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', None)
        algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', None)
        if not algod_address:
            raise CommandError('ALGORAND_ALGOD_ADDRESS is not configured')

        client = algod.AlgodClient(algod_token, algod_address)

        # Resolve assets to check
        assets = []
        if specific_asset:
            assets.append(('SPECIFIED', specific_asset))
        else:
            cusd = getattr(settings, 'ALGORAND_CUSD_ASSET_ID', None)
            confio = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', None)
            if cusd:
                assets.append(('cUSD', int(cusd)))
            if confio:
                assets.append(('CONFIO', int(confio)))
        if not assets:
            raise CommandError('No assets to check. Configure ALGORAND_CUSD_ASSET_ID and/or ALGORAND_CONFIO_ASSET_ID.')

        self.stdout.write(self.style.NOTICE(f'Checking address: {address}'))
        for name, asa in assets:
            try:
                info = client.account_asset_info(address, asa)
                holding = info.get('asset-holding') or {}
                amount = int(holding.get('amount', 0))
                self.stdout.write(self.style.SUCCESS(f'✅ {name} ({asa}): OPTED-IN, balance={amount}'))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'❌ {name} ({asa}): NOT opted-in or unavailable ({e})'))

