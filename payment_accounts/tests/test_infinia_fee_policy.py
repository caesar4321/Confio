from types import SimpleNamespace
from unittest import mock
from decimal import Decimal
from django.test import SimpleTestCase, override_settings

from payment_accounts.infinia_fee_policy import price
from payment_accounts.infinia_fees import FeePricingError


@override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='CO,AR', INFINIA_PROCESSING_FEE_TIER=0)
class FeePolicyTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch('payment_accounts.infinia_fee_debt.quoted', return_value=([], Decimal(0)))
        patcher.start()
        self.addCleanup(patcher.stop)
        maintenance = mock.patch('payment_accounts.infinia_maintenance.quoted_charges', return_value=([], Decimal(0)))
        maintenance.start()
        self.addCleanup(maintenance.stop)
        self.local = SimpleNamespace(provider_profile=SimpleNamespace(confio_account=None), provider='infinia', country='COL', asset='COP',
                                     internal_id='local', payin_rail='BREB')

    def test_breb_and_ach_use_the_destination_not_just_country(self):
        for kind, total in (('BREB_KEY', '1.250000'), ('ACCOUNT_COLOMBIA','2.750000')):
            self.assertEqual(price(self.local, 'to_bank', destination=SimpleNamespace(
                details={'type':kind}))['total_usd'], total)

    def test_deposit_uses_verified_receiving_rail(self):
        self.assertEqual(price(self.local,'to_wallet')['total_usd'], '1.250000')
        self.local.payin_rail = 'ACH'
        self.assertEqual(price(self.local,'to_wallet')['total_usd'], '2.750000')
        self.local.payin_rail = ''
        with self.assertRaises(FeePricingError):
            price(self.local,'to_wallet')

    def test_argentina_charges_only_separately_invoiced_processing(self):
        self.local.country, self.local.asset = 'ARG', 'ARS'
        for direction in ('to_wallet', 'to_bank'):
            fee = price(self.local, direction)
            self.assertEqual(fee['units'], str(5 * 10**17))
            self.assertEqual(fee['itf_collection'], 'provider_automatic')

    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='')
    def test_disabled_rollout_does_not_reprice_legacy_routes(self):
        self.local.country = 'XXX'
        self.assertIsNone(price(self.local,'to_wallet'))

    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES=[' co ', 'eu'])
    def test_list_configuration_uses_same_normalization_as_startup_checks(self):
        from payment_accounts.infinia_fee_policy import enabled
        self.assertTrue(enabled('COL'))
        self.assertTrue(enabled(' eu '))
        self.assertFalse(enabled('BR'))
