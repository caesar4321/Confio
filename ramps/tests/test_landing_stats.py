from django.core.cache import cache
from django.test import SimpleTestCase
from unittest.mock import patch
from decimal import Decimal

from ramps.schema import Query


class LandingStatsTests(SimpleTestCase):
    def tearDown(self):
        cache.delete('landing_stats_v3')
        cache.delete('fund_flow_stats_v2')
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
        from datetime import datetime, timezone as tz
        cache.delete('fund_flow_stats_v2')
        flow = {
            'deposited_usd': Decimal('100.5'), 'deposit_count': 3,
            'withdrawn_usd': Decimal('40'), 'withdrawal_count': 2,
            'median_withdrawal_minutes': 9.5, 'withdrawal_timing_samples': 12,
            'countries': [('BR', 4), ('PE', 1)],
            'since': datetime(2026, 3, 22, tzinfo=tz.utc),
        }
        with patch('ramps.metrics.fund_flow_breakdown', return_value=flow):
            # No request context at all: the endpoint is unauthenticated.
            result = Query().resolve_fund_flow_stats(None)
        self.assertEqual(result.total_usd, 140.5)
        self.assertEqual(result.operation_count, 5)
        self.assertEqual((result.deposit_count, result.withdrawal_count), (3, 2))
        self.assertEqual(result.median_withdrawal_minutes, 9.5)
        self.assertEqual([(c.country_iso, c.country_name, c.operation_count) for c in result.countries],
                         [('BR', 'Brasil', 4), ('PE', 'Perú', 1)])
        self.assertEqual(result.since.year, 2026)
        with patch('ramps.metrics.fund_flow_breakdown', side_effect=AssertionError('cache miss')):
            cached = Query().resolve_fund_flow_stats(None)
        self.assertEqual(cached.total_usd, 140.5)
        self.assertEqual(cached.countries[0].country_name, 'Brasil')
        self.assertEqual(cached.since, result.since)

    def test_fund_flow_stats_executes_through_the_schema_anonymously(self):
        from types import SimpleNamespace
        from config.schema import schema
        cache.set('fund_flow_stats_v2', {
            'deposited_usd': 1.0, 'withdrawn_usd': 2.0, 'total_usd': 3.0,
            'deposit_count': 1, 'withdrawal_count': 1, 'operation_count': 2,
            'median_withdrawal_minutes': None, 'withdrawal_timing_samples': 1,
            'since': None, 'countries': [{'country_iso': 'MX', 'country_name': 'México', 'operation_count': 2}],
        }, 60)
        anonymous = SimpleNamespace(user=SimpleNamespace(is_authenticated=False), META={})
        result = schema.execute(
            '{ fundFlowStats { totalUsd medianWithdrawalMinutes countries { countryIso operationCount } } }',
            context_value=anonymous)
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['fundFlowStats']['totalUsd'], 3.0)
        self.assertIsNone(result.data['fundFlowStats']['medianWithdrawalMinutes'])
        self.assertEqual(result.data['fundFlowStats']['countries'], [{'countryIso': 'MX', 'operationCount': 2}])
