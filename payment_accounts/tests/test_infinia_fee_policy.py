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

    def test_disclosure_splits_the_fee_the_person_pays(self):
        from payment_accounts.infinia_fee_policy import disclosure
        self.assertIsNone(disclosure(None))
        with mock.patch('payment_accounts.infinia_maintenance.quoted_charges', return_value=([7], Decimal('0.20'))), \
                mock.patch('payment_accounts.infinia_fee_debt.quoted', return_value=([3], Decimal('0.05'))):
            fee = disclosure(price(self.local, 'to_bank', destination=SimpleNamespace(details={'type': 'BREB_KEY'})))
        self.assertEqual({key: Decimal(value) for key, value in fee.items()}, {
            'processing_usd': Decimal('0.5'), 'network_usd': Decimal('0.75'), 'maintenance_usd': Decimal('0.20'),
            'debt_usd': Decimal('0.05'), 'total_usd': Decimal('1.50'), 'deferred_usd': Decimal(0)})

    def test_disclosure_reports_what_a_capped_deposit_collected(self):
        # A deposit smaller than its invoice pays what arrived; the rest is carried.
        from payment_accounts.infinia_fee_policy import disclosure
        snapshot = dict(price(self.local, 'to_wallet'), invoice_units=str(125 * 10**16), units=str(9 * 10**17),
                        maintenance_usd='0.20', debt_usd='0.05')
        fee = disclosure(snapshot)
        self.assertEqual((Decimal(fee['total_usd']), Decimal(fee['deferred_usd'])), (Decimal('0.9'), Decimal('0.35')))
        # Never "includes US$0.20" on a total that did not cover it.
        self.assertEqual((fee['maintenance_usd'], fee['debt_usd']), ('0', '0'))

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


    @override_settings(INFINIA_INCOMING_FEE_COLLECTION_ENABLED=False)
    def test_server_only_rollout_preserves_old_app_incoming_mint(self):
        self.assertIsNone(price(self.local, 'to_wallet'))
        self.assertEqual(price(self.local, 'to_bank', destination=SimpleNamespace(
            details={'type': 'BREB_KEY'}))['total_usd'], '1.250000')
