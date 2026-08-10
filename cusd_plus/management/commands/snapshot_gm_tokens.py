"""Refresh the deploy-time BSC token registry from Ondo's signed-in API."""

import json
import os
import re
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from cusd_plus import gm_api


ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
OUTPUT = Path(__file__).resolve().parents[2] / 'gm_tokens.json'


def build_bsc_registry(rows):
    registry = {}
    addresses = set()
    for row in rows:
        symbol = str(row.get('symbol') or '').strip()
        if not symbol:
            continue
        if symbol in registry:
            raise CommandError(f'duplicate GM symbol: {symbol}')
        for item in row.get('addresses') or []:
            address = str(item.get('address') or '')
            if item.get('networkChainId') != 'bsc-56' or not ADDRESS_RE.fullmatch(address):
                continue
            address_key = address.lower()
            if address_key in addresses:
                raise CommandError(f'duplicate BSC token address: {address}')
            decimals = int(item.get('decimals') or 18)
            if not 0 <= decimals <= 36:
                raise CommandError(f'invalid decimals for {symbol}: {decimals}')
            registry[symbol] = {'address': address, 'decimals': decimals}
            addresses.add(address_key)
            break
    return dict(sorted(registry.items()))


class Command(BaseCommand):
    help = 'Refresh cusd_plus/gm_tokens.json from Ondo BSC address metadata'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true', help='Validate without writing')
        parser.add_argument('--minimum-assets', type=int, default=100)

    def handle(self, *args, **options):
        registry = build_bsc_registry(gm_api.all_addresses())
        try:
            existing = json.loads(OUTPUT.read_text())
            existing_count = len(existing) if isinstance(existing, dict) else 0
        except (FileNotFoundError, ValueError):
            existing_count = 0
        minimum = max(options['minimum_assets'], (existing_count * 9 + 9) // 10)
        if len(registry) < minimum:
            raise CommandError(
                f'Ondo returned only {len(registry)} BSC assets; minimum safe count is {minimum}'
            )
        payload = json.dumps(registry, indent=2, sort_keys=True) + '\n'
        if options['check']:
            self.stdout.write(self.style.SUCCESS(f'Validated {len(registry)} BSC GM assets'))
            return
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=OUTPUT.parent,
                prefix='.gm_tokens.', suffix='.tmp', delete=False,
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_name = tmp.name
            os.replace(tmp_name, OUTPUT)
        finally:
            if tmp_name and os.path.exists(tmp_name):
                os.unlink(tmp_name)
        self.stdout.write(self.style.SUCCESS(f'Wrote {len(registry)} BSC GM assets to {OUTPUT}'))
