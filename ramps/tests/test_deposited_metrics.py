from decimal import Decimal

from django.test import TestCase

from conversion.models import Conversion
from ramps.metrics import deposited_volume_by_provider
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
