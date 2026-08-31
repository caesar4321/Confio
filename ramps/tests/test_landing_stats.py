from django.core.cache import cache
from django.test import SimpleTestCase

from ramps.schema import Query


class LandingStatsTests(SimpleTestCase):
    def tearDown(self):
        cache.delete('landing_stats_v2')

    def test_cached_public_stats_include_registered_users(self):
        cache.set(
            'landing_stats_v2',
            {
                'deposited_volume_usd': 125430.0,
                'presale_raised_usd': 3597.0,
                'registered_users': 8164,
            },
            60,
        )

        result = Query().resolve_landing_stats(None)

        self.assertEqual(result.registered_users, 8164)
