from unittest import mock
from decimal import Decimal

from django.test import TestCase

from conversion.models import Conversion
from ramps.metrics import (
    deposit_volume_and_count,
    fund_flow_breakdown,
    deposit_operation_count,
    deposited_volume_by_provider,
    withdrawn_volume_and_count,
)
from ramps.models import RampTransaction


class DepositedMetricsTests(TestCase):
    """Use bulk fixtures so provider/recovery signals do not create evidence."""

    def conversion(self, **overrides):
        values = dict(conversion_type='usdt_to_cusd', status='COMPLETED',
            from_amount=100, to_amount=99, net_amount_exact=99)
        values.update(overrides)
        return Conversion.objects.bulk_create([Conversion(**values)])[0]

    def ramp(self, **overrides):
        values = dict(provider='koywe', direction='on_ramp', status='COMPLETED',
            destination='cusd_plus', final_amount=99, final_currency='CUSD_BSC')
        values.update(overrides)
        return RampTransaction.objects.bulk_create([RampTransaction(**values)])[0]

    def test_provider_completion_alone_is_not_delivery(self):
        self.ramp()
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_verified_raw_usdt_receipt_counts_actual_not_provider_quote(self):
        self.ramp(final_currency='USDT BSC', metadata={
            'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 1, 'bsc_arrival_amount': '100'})
        self.assertEqual(deposited_volume_by_provider()['koywe'], 100)

    def test_completed_usdc_receipt_counts_without_mint(self):
        from usdc_transactions.models import USDCDeposit
        deposit = USDCDeposit.objects.bulk_create([USDCDeposit(amount=73,
            status='COMPLETED', actor_type='user')])[0]
        self.ramp(usdc_deposit=deposit, final_currency='CUSD', final_amount=999)
        self.assertEqual(deposited_volume_by_provider()['koywe'], 73)
        USDCDeposit.objects.filter(pk=deposit.pk).update(is_deleted=True)
        self.assertEqual(deposited_volume_by_provider()['koywe'], 0)

    def test_completed_conversion_takes_precedence_over_raw_receipt(self):
        self.ramp(conversion=self.conversion(), metadata={
            'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 0, 'bsc_arrival_amount': '100'})
        self.assertEqual(deposited_volume_by_provider()['koywe'], 99)

    def test_failed_or_pending_deposits_and_outgoing_receipts_are_excluded(self):
        from usdc_transactions.models import USDCDeposit
        for status in ('FAILED', 'PROCESSING', 'PENDING'):
            deposit = USDCDeposit.objects.bulk_create([USDCDeposit(amount=73,
                status=status, actor_type='user')])[0]
            self.ramp(usdc_deposit=deposit)
        self.ramp(direction='off_ramp', metadata={
            'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 0, 'bsc_arrival_amount': '100'})
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_malformed_or_incomplete_scanner_evidence_cannot_break_metric(self):
        valid = {'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 0, 'bsc_arrival_amount': '100'}
        for overrides in ({'bsc_arrival_amount': 'NaN'}, {'bsc_arrival_amount': '9' * 100},
                          {'bsc_arrival_amount': '-1'}, {'bsc_arrival_amount': None},
                          {'bsc_arrival_amount': {}}, {'bsc_arrival_tx_hash': 'provider-only'},
                          {'bsc_arrival_log_index': None}):
            self.ramp(metadata={**valid, **overrides})
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_failed_pending_deleted_or_wrong_direction_conversion_is_excluded(self):
        for overrides in ({'status': 'SUBMITTED'}, {'status': 'FAILED'},
                          {'is_deleted': True}, {'conversion_type': 'cusd_to_usdt'}):
            self.ramp(conversion=self.conversion(**overrides))
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_completed_batch_preserves_per_ramp_allocation(self):
        conversion = self.conversion()
        self.ramp(conversion=conversion, final_amount=Decimal('39.6'))
        self.ramp(conversion=conversion, final_amount=Decimal('59.4'))
        self.assertEqual(deposited_volume_by_provider()['koywe'], Decimal('99'))

    def test_all_product_types_and_providers_with_verified_delivery(self):
        for provider, kind, currency in (
            ('koywe', 'usdt_to_cusd', 'CUSD_BSC'),
            ('guardarian', 'usdc_to_cusd', 'CUSD'),
            ('transak', 'to_savings', 'CUSD+'),
        ):
            self.ramp(provider=provider, final_currency=currency,
                conversion=self.conversion(conversion_type=kind))
        totals = deposited_volume_by_provider()
        self.assertEqual([totals[p] for p in ('koywe', 'guardarian', 'transak')], [99, 99, 99])

    def test_quote_currency_outgoing_and_unfinished_ramp_are_excluded(self):
        conversion = self.conversion()
        for overrides in ({'final_currency': 'USDT BSC'}, {'direction': 'off_ramp'},
                          {'status': 'PROCESSING'}, {'final_amount': -1}):
            self.ramp(conversion=conversion, **overrides)
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_metrics_use_fixed_query_count(self):
        conversion = self.conversion()
        for _ in range(20):
            self.ramp(conversion=conversion, final_amount=1)
        with self.assertNumQueries(3):
            self.assertEqual(deposited_volume_by_provider()['koywe'], 20)

    def test_public_graphql_uses_verified_database_totals_and_cache(self):
        import graphene
        from django.core.cache import cache
        from unittest.mock import patch
        from ramps.schema import Query

        self.addCleanup(cache.delete, 'landing_stats_v3')
        cache.delete('landing_stats_v3')
        self.ramp(conversion=self.conversion(), final_amount=Decimal('12.34'))
        self.ramp(final_amount=999)
        schema = graphene.Schema(query=Query)
        result = schema.execute('{ landingStats { depositedVolumeUsd } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['landingStats']['depositedVolumeUsd'], 12.34)
        with patch('ramps.metrics.deposited_volume_by_provider', side_effect=AssertionError('cache miss')):
            cached = schema.execute('{ landingStats { depositedVolumeUsd } }')
        self.assertIsNone(cached.errors)
        self.assertEqual(cached.data, result.data)


class FundFlowMetricsTests(TestCase):
    """Withdrawals and the shared operation count."""

    ramp = DepositedMetricsTests.ramp

    def test_operation_count_matches_what_the_volume_counts(self):
        self.ramp()  # provider completion alone: not a deposit
        self.ramp(final_currency='USDT BSC', metadata={
            'bsc_arrival_tx_hash': '0x' + 'b' * 64,
            'bsc_arrival_log_index': 2, 'bsc_arrival_amount': '50'})
        self.assertEqual(deposited_volume_by_provider()['koywe'], 50)
        self.assertEqual(deposit_operation_count(), 1)

    def test_withdrawal_counts_actual_amount_once(self):
        self.ramp(direction='off_ramp', crypto_currency='USDC Algorand',
                  crypto_amount_estimated=120, crypto_amount_actual=100)
        self.ramp(direction='off_ramp', crypto_currency='USDT BSC', status='FAILED', crypto_amount_actual=500)
        self.ramp(direction='off_ramp', crypto_currency='USDT BSC',
                  crypto_amount_estimated=80, crypto_amount_actual=None)
        self.assertEqual(withdrawn_volume_and_count(), (Decimal('100'), 1))

    def test_non_dollar_withdrawal_is_not_counted_as_dollars(self):
        self.ramp(direction='off_ramp', provider='guardarian', crypto_currency='ALGO', crypto_amount_actual=1000)
        self.ramp(direction='off_ramp', provider='guardarian', crypto_currency='BTC', crypto_amount_actual=2)
        self.ramp(direction='off_ramp', crypto_currency='USDT BSC', crypto_amount_actual=10)
        self.assertEqual(withdrawn_volume_and_count(), (Decimal('10'), 1))


class PerimeterFlowTests(TestCase):
    """Movido = conversions across the Confío-dollar perimeter; cUSD <-> cUSD+ excluded."""

    def setUp(self):
        from users.models import User
        self.people = [User.objects.create(username=f'flow{i}', firebase_uid=f'flow-uid-{i}', phone_country='BR')
                       for i in range(5)]

    def conversion(self, conversion_type, amount_in, amount_out=None, *, direction='', user=None, **overrides):
        values = dict(conversion_type=conversion_type, status='COMPLETED', from_amount=Decimal(amount_in),
                      to_amount=Decimal(amount_out if amount_out is not None else amount_in),
                      perimeter_direction=direction, actor_user=user or self.people[0], actor_type='user')
        values.update(overrides)
        return Conversion.objects.bulk_create([Conversion(**values)])[0]

    def test_entries_and_exits_from_every_era(self):
        self.conversion('usdc_to_cusd', '10')                                   # Algorand, unlabeled
        self.conversion('usdt_to_cusd', '20', '19.8', direction='entry')        # BSC
        self.conversion('to_savings', '5', direction='entry')                   # straight into Dollar+
        self.conversion('cusd_to_usdc', '7')                                    # Algorand exit
        self.conversion('cusd_to_usdt', '12', '11.9', direction='exit')         # BSC exit, after fee
        self.conversion('from_savings', '3', direction='exit')
        flow = fund_flow_breakdown()
        # Entries at what came in; exits at what went out.
        self.assertEqual((flow['deposited_usd'], flow['deposit_count']), (Decimal('35'), 3))
        self.assertEqual((flow['withdrawn_usd'], flow['withdrawal_count']), (Decimal('21.9'), 3))

    def test_only_cusd_cusd_plus_moves_are_excluded(self):
        self.conversion('to_savings', '50', direction='internal')
        self.conversion('from_savings', '50', direction='internal')
        self.conversion('usdc_to_algo', '9')                                     # never crosses
        self.conversion('usdt_to_cusd', '99', status='FAILED', direction='entry')
        self.conversion('usdt_to_cusd', '99', is_deleted=True, direction='entry')
        flow = fund_flow_breakdown()
        self.assertEqual((flow['deposit_count'], flow['withdrawal_count']), (0, 0))

    def test_every_channel_counts_once(self):
        # A ramp's deposit is counted by its conversion, never on top of it.
        conv = self.conversion('usdt_to_cusd', '40', direction='entry')
        RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='on_ramp',
            status='COMPLETED', destination='cusd', final_amount=40, final_currency='CUSD_BSC', conversion=conv)])
        flow = fund_flow_breakdown()
        self.assertEqual((flow['deposited_usd'], flow['deposit_count']), (Decimal('40'), 1))

    def test_countries_need_five_people_and_show_counts_not_dollars(self):
        for person in self.people:
            self.conversion('usdt_to_cusd', '10', direction='entry', user=person)
        from users.models import User
        whale = User.objects.create(username='whale', firebase_uid='whale-uid', phone_country='CL')
        for _ in range(4):
            self.conversion('cusd_to_usdt', '5000', direction='exit', user=whale)
        flow = fund_flow_breakdown()
        self.assertEqual(flow['countries'], [('BR', 5)])
        self.assertEqual(flow['withdrawn_usd'], Decimal('20000'))
        self.assertIsNotNone(flow['since'])

    def test_withdrawal_median_still_comes_from_fiat_payouts(self):
        from datetime import timedelta
        self.conversion('cusd_to_usdt', '10', direction='exit')
        for minutes in range(1, 11):
            ramp = RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='off_ramp',
                status='COMPLETED', crypto_currency='USDT BSC', crypto_amount_actual=Decimal('10'))])[0]
            RampTransaction.objects.filter(pk=ramp.pk).update(completed_at=ramp.created_at + timedelta(minutes=minutes))
        flow = fund_flow_breakdown()
        self.assertEqual(flow['withdrawal_timing_samples'], 10)
        self.assertAlmostEqual(flow['median_withdrawal_minutes'], 5.5, places=3)
        self.assertEqual(flow['withdrawal_count'], 1)  # volume comes from conversions only
