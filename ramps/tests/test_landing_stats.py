from django.core.cache import cache
from django.test import SimpleTestCase
from unittest.mock import patch
from decimal import Decimal

from ramps.schema import Query


class LandingStatsTests(SimpleTestCase):
    def tearDown(self):
        cache.delete('landing_stats_v3')
        cache.delete('fund_flow_stats_v1')
        cache.delete('stats_summary_v13')

    def test_cached_public_stats_include_registered_users(self):
        cache.set(
            'landing_stats_v3',
            {
                'deposited_volume_usd': 125430.0,
                'presale_raised_usd': 3597.0,
                'registered_users': 8164,
            },
            60,
        )

        result = Query().resolve_landing_stats(None)

        self.assertEqual(result.registered_users, 8164)

    def test_uncached_stats_use_combined_provider_metric(self):
        cache.delete('landing_stats_v3')
        cache.set('stats_summary_v13', {'total_users': 123}, 60)
        with patch('ramps.metrics.deposited_volume_by_provider', return_value={
            'koywe': Decimal('10'), 'infinia': Decimal('1.982'), 'cobre': Decimal('2')}), \
                patch('presale.models.PresalePhase.objects.all', return_value=[]):
            result = Query().resolve_landing_stats(None)
        self.assertEqual(result.deposited_volume_usd, 13.982)
        self.assertEqual(result.registered_users, 123)

    def test_fund_flow_stats_is_public_and_cached(self):
        cache.delete('fund_flow_stats_v1')
        with patch('ramps.metrics.deposit_volume_and_count', return_value=(Decimal('100.5'), 3)), \
                patch('ramps.metrics.withdrawn_volume_and_count', return_value=(Decimal('40'), 2)):
            # No request context at all: the endpoint is unauthenticated.
            result = Query().resolve_fund_flow_stats(None)
        self.assertEqual(result.deposited_usd, 100.5)
        self.assertEqual(result.withdrawn_usd, 40.0)
        self.assertEqual(result.total_usd, 140.5)
        self.assertEqual(result.operation_count, 5)
        with patch('ramps.metrics.deposit_volume_and_count', side_effect=AssertionError('cache miss')):
            self.assertEqual(Query().resolve_fund_flow_stats(None).total_usd, 140.5)
