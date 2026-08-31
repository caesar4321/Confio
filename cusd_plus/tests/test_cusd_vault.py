from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from cusd_plus import cusd_vault


VAULT = '0x' + '12' * 20


def _words(*values):
    return '0x' + ''.join(f'{value:064x}' for value in values)


@override_settings(CUSD_VAULT_ADDRESS=VAULT)
class CusdVaultPreviewTests(SimpleTestCase):
    @patch('cusd_plus.cusd_vault._rpc')
    def test_preview_is_decoded_from_contract(self, rpc):
        gross = 100 * 10 ** 18
        fee = 9 * 10 ** 17
        net = gross - fee
        rpc.side_effect = [_words(fee, net), _words(90)]

        preview = cusd_vault.preview_mint_wei(gross)

        self.assertEqual(preview.gross_wei, gross)
        self.assertEqual(preview.fee_wei, fee)
        self.assertEqual(preview.net_wei, net)
        self.assertEqual(preview.fee_bps, 90)
        self.assertEqual(preview.fee, cusd_vault.Decimal('0.9'))

    @patch('cusd_plus.cusd_vault._rpc')
    def test_inconsistent_contract_response_fails_closed(self, rpc):
        rpc.return_value = _words(10, 89)
        with self.assertRaisesRegex(RuntimeError, 'invalid_preview'):
            cusd_vault.preview_redeem_wei(100)

    @override_settings(CUSD_VAULT_ADDRESS='')
    def test_missing_contract_address_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'not_configured'):
            cusd_vault.fee_for_wei(100)
