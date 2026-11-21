from decimal import Decimal
from unittest import mock

from django.test import TestCase

from .models import ExchangeRate, RateFetchLog
from .services import ExchangeRateService, RATE_SOURCE_PRIORITY


def _response(payload):
    response = mock.Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class YadioRateTests(TestCase):
    def setUp(self):
        self.service = ExchangeRateService()

    def test_stores_full_precision_ves_per_usd(self):
        payload = {'request': {'amount': 1, 'from': 'USD', 'to': 'VES'},
                   'result': 1080.06, 'rate': 1080.057525, 'timestamp': 1}
        with mock.patch.object(self.service.session, 'get', return_value=_response(payload)) as get:
            self.assertTrue(self.service.fetch_yadio_rates())

        self.assertIn('/convert/1/USD/VES', get.call_args.args[0])
        row = ExchangeRate.objects.get(source='yadio')
        self.assertEqual(row.rate, Decimal('1080.057525'))
        self.assertEqual((row.source_currency, row.target_currency, row.rate_type),
                         ('VES', 'USD', 'parallel'))
        self.assertEqual(RateFetchLog.objects.get(source='yadio').status, 'success')

    def test_response_without_a_rate_is_logged_as_a_failure(self):
        # The old VES -> USD query came back as "result": 0 and was logged as success.
        payload = {'request': {'amount': 1, 'from': 'USD', 'to': 'VES'}, 'result': 0, 'rate': 0}
        with mock.patch.object(self.service.session, 'get', return_value=_response(payload)):
            self.assertFalse(self.service.fetch_yadio_rates())

        self.assertFalse(ExchangeRate.objects.filter(source='yadio').exists())
        log = RateFetchLog.objects.get(source='yadio')
        self.assertEqual((log.status, log.rates_fetched), ('failed', 0))
        self.assertIn('no usable rate', log.error_message)

    def test_malformed_rate_is_logged_as_a_failure(self):
        for payload in ({'result': 1080.06}, {'rate': 'abc'}):
            with self.subTest(payload=payload):
                RateFetchLog.objects.all().delete()
                with mock.patch.object(self.service.session, 'get', return_value=_response(payload)):
                    self.assertFalse(self.service.fetch_yadio_rates())
                self.assertFalse(ExchangeRate.objects.filter(source='yadio').exists())
                self.assertEqual(RateFetchLog.objects.get(source='yadio').status, 'failed')


class RetiredSourceTests(TestCase):
    def test_currencylayer_is_no_longer_fetched_or_preferred(self):
        service = ExchangeRateService()
        self.assertFalse(hasattr(service, 'fetch_currencylayer_rates'))
        self.assertNotIn('currencylayer', RATE_SOURCE_PRIORITY['official'])

        fetchers = [name for name in dir(service)
                    if name.startswith('fetch_') and name.endswith('_rates') and name != 'fetch_all_rates']
        with mock.patch.multiple(service, **{name: mock.Mock(return_value=True) for name in fetchers}):
            results = service.fetch_all_rates()
        self.assertNotIn('currencylayer', results)
