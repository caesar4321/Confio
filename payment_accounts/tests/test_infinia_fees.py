from unittest import TestCase
from payment_accounts.infinia_fees import FeePricingError, transaction_cost, virtual_account_cost, route_cost


class InvoicePricingTests(TestCase):
    def test_colombian_one_blockchain_leg_and_breb_is_125(self):
        for country in ('CO', 'COL'):
            result = transaction_cost(country=country, rail='BREB', blockchain_transfers=1)
            self.assertEqual(result['total_usd'], '1.250000')
            self.assertEqual(result['processing_usd'], '0.5')
            self.assertEqual(result['blockchain_usd'], '0.75')
            self.assertNotIn('fx_fee', result)

    def test_colombian_processing_is_separate_from_blockchain_cost(self):
        for rail, processing in (('BREB', '0.5'), ('ACH', '2')):
            result = transaction_cost(country='CO', rail=rail, blockchain_transfers=1)
            self.assertEqual(result['processing_usd'], processing)
            self.assertEqual(result['blockchain_usd'], '0.75')

    def test_each_actual_provider_blockchain_leg_is_counted(self):
        self.assertEqual(transaction_cost(country='CO', rail='ACH', blockchain_transfers=2)['total_usd'], '3.500000')

    def test_tiers_and_fractional_cents_are_preserved(self):
        self.assertEqual(transaction_cost(country='BR', rail='PIX', tier=1, blockchain_transfers=1)['total_usd'], '0.075000')
        self.assertEqual(transaction_cost(country='CO', rail='BREB', tier=5, blockchain_transfers=1)['total_usd'], '1.000000')

    def test_unknown_costs_are_not_free(self):
        for kwargs in ({'country': 'CO', 'rail': 'UNKNOWN'},
                       {'country': 'ZZ', 'rail': 'PIX'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FeePricingError):
                transaction_cost(**kwargs, blockchain_transfers=1)

    def test_bolivia_always_uses_immediate_conversion_tariff(self):
        result = route_cost(country='BO', rail='QR',
                            assets=['BSC:USDT', 'POL:USDC', 'BOB'])
        self.assertEqual(result['total_usd'], '3.200000')
        with self.assertRaises(FeePricingError):
            route_cost(country='BO', rail='QR',
                       assets=['BSC:USDT', 'POL:USDC', 'BOB'],
                       bolivia_mode='holding')

    def test_rejects_invalid_numeric_inputs(self):
        for tier in (-1, 6, True, '0'):
            with self.subTest(tier=tier), self.assertRaises(FeePricingError):
                transaction_cost(country='CO', rail='BREB', tier=tier, blockchain_transfers=1)
        for count in (0, -1, True, '1', 1.0, None):
            with self.subTest(count=count), self.assertRaises(FeePricingError):
                transaction_cost(country='CO', rail='BREB', blockchain_transfers=count)
        for amount in ('NaN', 'Infinity', '-1', True):
            with self.subTest(amount=amount), self.assertRaises(FeePricingError):
                transaction_cost(country='AR', rail='CBU', blockchain_transfers=1,
                                 argentina_itf_usd=amount)

    def test_account_costs_are_per_account_not_per_customer(self):
        self.assertEqual(virtual_account_cost(account_count=4,new_accounts=2,enabled_account_months=2),
                         {'creation_usd':'2','maintenance_usd':'0.20'})
        with self.assertRaises(FeePricingError):virtual_account_cost(account_count=100000)


class RoutePricingTests(TestCase):
    def test_normal_colombian_withdrawal_cannot_omit_blockchain_charge(self):
        result = route_cost(country='COL', rail='BREB',
                            assets=['BSC:USDT', 'POL:USDC', 'COP'])
        self.assertEqual(result['total_usd'], '1.250000')
        self.assertEqual(result['blockchain_transfers'], 1)
        self.assertEqual(result['direction'], 'to_bank')

    def test_colombian_deposit_has_the_same_provider_blockchain_charge(self):
        result = route_cost(country='CO', rail='Bre-B',
                            assets=['COP', 'POL:USDC', 'BSC:USDT'])
        self.assertEqual(result['total_usd'], '1.250000')
        self.assertEqual(result['direction'], 'to_wallet')

    def test_fiat_only_routes_are_not_supported(self):
        from payment_accounts.infinia_fees import FIAT_ASSETS
        for country, fiat in FIAT_ASSETS.items():
            with self.subTest(country=country), self.assertRaises(FeePricingError):
                route_cost(country=country, rail='BREB', assets=[fiat, fiat])

    def test_partial_or_mismatched_routes_do_not_become_fiat_payouts(self):
        for assets in (None, 'COP', ['COP'], ['POL:USDC','COP'],
                       ['MXN','MXN'], ['BSC:USDT','COP'], [{}]):
            with self.subTest(assets=assets), self.assertRaises(FeePricingError):
                route_cost(country='CO',rail='BREB',assets=assets)

    def test_caller_cannot_override_route_leg_count(self):
        with self.assertRaises(FeePricingError):
            route_cost(country='CO',rail='BREB',assets=['BSC:USDT','POL:USDC','COP'],
                       blockchain_transfers=0)

    def test_low_level_tariff_requires_explicit_leg_count(self):
        with self.assertRaises(FeePricingError):
            transaction_cost(country='CO',rail='BREB')

    def test_normal_ach_route_uses_both_fees(self):
        self.assertEqual(route_cost(country='CO',rail='ACH',
                         assets=['BSC:USDT','POL:USDC','COP'])['total_usd'], '2.750000')

    def test_country_alias_normalization(self):
        self.assertEqual(route_cost(country=' eu ',rail='SEPA',
                         assets=['EUR','POL:USDC','BSC:USDT'])['total_usd'], '0.800000')

    def test_every_supported_country_and_direction_has_a_blockchain_leg(self):
        from payment_accounts.infinia_fees import FIAT_ASSETS
        for country, fiat in FIAT_ASSETS.items():
            for assets in ([fiat, 'POL:USDC', 'BSC:USDT'],
                           ['BSC:USDT', 'POL:USDC', fiat]):
                with self.subTest(country=country, assets=assets):
                    result = route_cost(country=country, rail='BREB', assets=assets)
                    self.assertEqual(result['blockchain_transfers'], 1)
                    self.assertEqual(result['blockchain_usd'],
                                     '0.75' if country == 'CO' else '0')

    def test_argentina_automatic_itf_is_not_collected_in_either_direction(self):
        for assets in (['ARS', 'POL:USDC', 'BSC:USDT'],
                       ['BSC:USDT', 'POL:USDC', 'ARS']):
            result = route_cost(country='AR', rail='CBU', assets=assets)
            self.assertEqual(result['total_usd'], '0.500000')
            self.assertEqual(result['processing_usd'], '0.5')
            self.assertEqual(result['itf_usd'], '0')
            self.assertEqual(result['itf_collection'], 'provider_automatic')
            self.assertEqual(result['blockchain_usd'], '0')

    def test_already_included_gas_cannot_be_added_again(self):
        with self.assertRaises(FeePricingError):
            route_cost(country='BR', rail='PIX',
                       assets=['BSC:USDT', 'POL:USDC', 'BRL'],
                       other_blockchain_cost_usd='0.01')

    def test_fee_configuration_cannot_silently_apply_to_the_wrong_country(self):
        for options in ({'argentina_itf_usd': '0.12'}, {'bolivia_mode': 'holding'}):
            with self.subTest(options=options), self.assertRaises(FeePricingError):
                route_cost(country='CO', rail='BREB',
                           assets=['BSC:USDT', 'POL:USDC', 'COP'], **options)

    def test_oversized_itf_is_a_pricing_error(self):
        with self.assertRaises(FeePricingError):
            route_cost(country='AR', rail='CBU',
                       assets=['ARS', 'POL:USDC', 'BSC:USDT'], argentina_itf_usd='1e1000')

    def test_even_zero_manual_itf_is_rejected_to_keep_provider_tax_separate(self):
        for amount in ('0', '0.0000011', '1.20'):
            with self.subTest(amount=amount), self.assertRaisesRegex(FeePricingError, 'automatically'):
                route_cost(country='AR', rail='CBU',
                           assets=['ARS', 'POL:USDC', 'BSC:USDT'], argentina_itf_usd=amount)

    def test_argentina_processing_tiers_exclude_automatic_tax(self):
        for tier, total in enumerate(('0.500000','0.400000','0.300000','0.200000','0.100000','0.050000')):
            self.assertEqual(transaction_cost(country='AR', rail='CBU',
                blockchain_transfers=1, tier=tier)['total_usd'], total)
