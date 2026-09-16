from types import SimpleNamespace
from django.test import SimpleTestCase
from payment_accounts.receiving_rails import CANDIDATES, detect_receiving_rail


class ReceivingRailTests(SimpleTestCase):
    def detect(self, country, asset, instructions):
        return detect_receiving_rail(SimpleNamespace(country=country, asset=asset,
            provider_data={'latest': {'funding_instructions': instructions}}))

    def test_every_configured_fiat_pair_has_candidates(self):
        from payment_accounts.services import PROVIDER_ACCOUNT_SHAPES
        from payment_accounts.providers.common import iso_alpha2
        for country, asset in PROVIDER_ACCOUNT_SHAPES['infinia'][1]:
            if country == 'XXX':
                continue
            with self.subTest(country=country, asset=asset):
                self.assertIn((iso_alpha2(country), asset), CANDIDATES)

    def test_generic_country_bank_details_never_authorize(self):
        for country, asset in CANDIDATES:
            with self.subTest(country=country, asset=asset):
                result = self.detect(country, asset, {'type': 'fiat', 'account_number': '12345678',
                    'bank_code': '021000021', 'iban': 'GB82WEST12345698765432'})
                self.assertEqual(result['verified_rail'], '')
                self.assertTrue(result['candidates'])
                self.assertEqual(result['status'], 'inferred')

    def test_ted_and_fps_explicit_shapes(self):
        for country, asset, shape, rail in [
            ('BRA', 'BRL', {'ted_brl': {'bank_code': '001', 'branch_number': '1234',
                'account_number': '123456', 'account_type': 'CHECKING'}}, 'TED'),
            ('GBR', 'GBP', {'fps_gbp': {'account_number': '12345678', 'sort_code': '12-34-56'}}, 'FPS'),
        ]:
            with self.subTest(rail=rail):
                result = self.detect(country, asset, shape)
                self.assertEqual(result['status'], 'verified')
                self.assertEqual(result['verified_rail'], rail)
                self.assertNotIn('123456', str(result))  # diagnostics contain no banking PII

    def test_multiple_rails_are_not_arbitrarily_selected(self):
        result = self.detect('BR', 'BRL', {'pix_key_brl': {'pix_key': 'private@example.com'},
            'ted_brl': {'bank_code': '001', 'branch_number': '1234',
                        'account_number': '123456', 'account_type': 'CHECKING'}})
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual(result['candidates'], ['PIX', 'TED'])
        self.assertEqual(result['verified_rail'], '')

    def test_partial_unknown_and_malformed_data_fail_closed(self):
        for instructions in [None, 'bad', 1, [None], [{'pix_key': 'valid'}, 'bad'],
                             {'pix_key': 123}, {'pix_key': {'value': 'bad'}},
                             {'type': 'crypto', 'pix_key': 'not-fiat'}]:
            with self.subTest(instructions=instructions):
                self.assertEqual(self.detect('BR', 'BRL', instructions)['verified_rail'], '')
        self.assertEqual(self.detect('GB', 'GBP', {'fps_gbp': {
            'account_number': '12345678', 'sort_code': '１２３４５６'}})['verified_rail'], '')

    def test_unknown_extra_instruction_prevents_single_rail_assumption(self):
        for instructions in [[{'pix_key': 'valid'}, {'new_rail': 'unknown'}],
                             {'pix_key': 'valid', 'new_rail': 'unknown'},
                             {'pix_key': 'valid', 'ted_brl': {'account_number': 'partial'}},
                             {'breb_key': '@key', 'account_number': '123456'}]:
            country, asset = ('CO', 'COP') if isinstance(instructions, dict) and 'breb_key' in instructions else ('BR', 'BRL')
            result = self.detect(country, asset, instructions)
            self.assertEqual(result['status'], 'ambiguous')
            self.assertEqual(result['verified_rail'], '')

    def test_wrong_currency_or_country_never_verifies(self):
        for country, asset in [('US', 'BRL'), ('BR', 'USD'), ('XX', 'USDC_POL'), ('bad', 'BRL')]:
            self.assertEqual(self.detect(country, asset, {'pix_key': 'valid'})['verified_rail'], '')

    def test_populated_foreign_rail_conflicts_but_null_placeholders_do_not(self):
        for extra in ['ted_brl', 'breb_key', 'pix_key']:
            shape = {'fps_gbp': {'account_number': '12345678', 'sort_code': '123456'}, extra: 'foreign'}
            self.assertEqual(self.detect('GB', 'GBP', shape)['status'], 'ambiguous')
            shape[extra] = None
            self.assertEqual(self.detect('GB', 'GBP', shape)['verified_rail'], 'FPS')

    def test_empty_snapshot_retains_candidates_not_verification(self):
        result = self.detect('US', 'USD', [])
        self.assertEqual(result['candidates'], ['ACH', 'FEDWIRE'])
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['verified_rail'], '')
