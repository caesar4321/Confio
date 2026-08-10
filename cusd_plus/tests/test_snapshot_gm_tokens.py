import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from cusd_plus.management.commands import snapshot_gm_tokens


def _row(symbol, address, decimals=18):
    return {
        'symbol': symbol,
        'addresses': [{
            'networkChainId': 'bsc-56',
            'address': address,
            'decimals': decimals,
        }],
    }


class SnapshotGmTokensTests(SimpleTestCase):
    def test_builder_rejects_duplicate_symbol_address_and_invalid_decimals(self):
        address_a = '0x' + '11' * 20
        address_b = '0x' + '22' * 20
        with self.assertRaises(CommandError):
            snapshot_gm_tokens.build_bsc_registry([
                _row('Aon', address_a), _row('Aon', address_b),
            ])
        with self.assertRaises(CommandError):
            snapshot_gm_tokens.build_bsc_registry([
                _row('Aon', address_a), _row('Bon', address_a),
            ])
        with self.assertRaises(CommandError):
            snapshot_gm_tokens.build_bsc_registry([_row('Aon', address_a, 37)])

    def test_partial_response_cannot_replace_existing_snapshot(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'gm_tokens.json'
            existing = {f'S{i}on': {'address': f'0x{i:040x}', 'decimals': 18} for i in range(200)}
            output.write_text(json.dumps(existing))
            rows = [_row(f'N{i}on', f'0x{i + 1000:040x}') for i in range(100)]
            with mock.patch.object(snapshot_gm_tokens, 'OUTPUT', output), \
                 mock.patch.object(snapshot_gm_tokens.gm_api, 'all_addresses', return_value=rows):
                with self.assertRaises(CommandError):
                    snapshot_gm_tokens.Command().handle(check=False, minimum_assets=100)
            self.assertEqual(json.loads(output.read_text()), existing)

    def test_check_mode_validates_without_writing(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'gm_tokens.json'
            output.write_text('{}')
            rows = [_row(f'N{i}on', f'0x{i + 1000:040x}') for i in range(100)]
            with mock.patch.object(snapshot_gm_tokens, 'OUTPUT', output), \
                 mock.patch.object(snapshot_gm_tokens.gm_api, 'all_addresses', return_value=rows):
                snapshot_gm_tokens.Command().handle(check=True, minimum_assets=100)
            self.assertEqual(output.read_text(), '{}')

    def test_successful_refresh_replaces_with_complete_valid_json(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'gm_tokens.json'
            output.write_text('{}')
            rows = [_row(f'N{i}on', f'0x{i + 1000:040x}') for i in range(100)]
            with mock.patch.object(snapshot_gm_tokens, 'OUTPUT', output), \
                 mock.patch.object(snapshot_gm_tokens.gm_api, 'all_addresses', return_value=rows):
                snapshot_gm_tokens.Command().handle(check=False, minimum_assets=100)
            self.assertEqual(len(json.loads(output.read_text())), 100)
