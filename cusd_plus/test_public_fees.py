from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from config.schema import schema

QUERY = '{ publicFees { conversionFeeBps payFeeBps } }'
VAULT = '0x3c29417eb4314155e63d4c7d4507852b87763ed1'
KEY = f'public_conversion_fee_bps_v2:{VAULT}'


@override_settings(CUSD_VAULT_ADDRESS=VAULT)
class PublicFeesTests(SimpleTestCase):
    def setUp(self):
        cache.delete_many([KEY, f'{KEY}:lease'])

    def fees(self):
        result = schema.execute(QUERY, context_value=mock.Mock(user=None))
        self.assertIsNone(result.errors)
        return result.data['publicFees']

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=False)
    def test_fee_switched_off_is_zero(self):
        self.assertEqual(self.fees(), {'conversionFeeBps': 0, 'payFeeBps': 90})

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_reads_the_vault_fee_and_caches_it(self):
        with mock.patch('cusd_plus.cusd_vault.current_fee_bps', return_value=75) as read:
            self.assertEqual(self.fees()['conversionFeeBps'], 75)
            self.assertEqual(self.fees()['conversionFeeBps'], 75)
        read.assert_called_once()

    def test_switching_the_fee_on_never_serves_a_cached_zero(self):
        with override_settings(CUSD_CONVERSION_FEE_ENABLED=False):
            self.assertEqual(self.fees()['conversionFeeBps'], 0)
        with override_settings(CUSD_CONVERSION_FEE_ENABLED=True), \
                mock.patch('cusd_plus.cusd_vault.current_fee_bps', return_value=90) as read:
            self.assertEqual(self.fees()['conversionFeeBps'], 90)
        read.assert_called_once()

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_unreadable_chain_is_null_and_not_retried_every_request(self):
        with mock.patch('cusd_plus.cusd_vault.current_fee_bps', side_effect=RuntimeError('rpc down')) as read:
            self.assertEqual(self.fees(), {'conversionFeeBps': None, 'payFeeBps': 90})
            self.assertEqual(self.fees(), {'conversionFeeBps': None, 'payFeeBps': 90})
        read.assert_called_once()

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_failure_sentinel_expiring_inside_the_lease_does_not_reread(self):
        with mock.patch('cusd_plus.cusd_vault.current_fee_bps', side_effect=RuntimeError('rpc down')) as read:
            self.fees()
            cache.delete(KEY)  # sentinel expired, lease still held
            self.assertIsNone(self.fees()['conversionFeeBps'])
        read.assert_called_once()

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_concurrent_refresh_returns_null_without_a_second_read(self):
        cache.add(f'{KEY}:lease', 1, 300)
        with mock.patch('cusd_plus.cusd_vault.current_fee_bps', return_value=90) as read:
            self.assertIsNone(self.fees()['conversionFeeBps'])
        read.assert_not_called()


class PublicFeesEndpointTests(SimpleTestCase):
    databases = '__all__'

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=False)
    def test_anonymous_post_to_graphql_endpoint(self):
        response = self.client.post(
            '/graphql/', data={'query': QUERY}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['publicFees'], {'conversionFeeBps': 0, 'payFeeBps': 90})
