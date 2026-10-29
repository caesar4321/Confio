"""The BSC RPC pool (cusd_plus/tasks._rpc): keyless endpoints lead, the
metered one only catches the call that failed over."""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from cusd_plus import tasks

FREE = 'https://bsc-rpc.publicnode.com'
PAID = 'https://bsc-mainnet.nodereal.io/v1/' + 'a' * 32
SPARE = 'https://bsc-dataseed.bnbchain.org'


class RpcPoolTests(SimpleTestCase):
    def setUp(self):
        cache.delete('cusd_plus_bsc_rpc_preferred')

    def test_a_failover_to_the_metered_endpoint_does_not_stick(self):
        # protects=one publicnode refusal costs one NodeReal call, not 5 minutes of them; fails_when=the paid URL becomes the preferred one; no_claim=endpoint health
        calls = []

        def single(url, method, params, timeout=15):
            calls.append(url)
            if url == FREE and len(calls) == 1:
                raise RuntimeError("bsc rpc: {'code': -32602, 'message': 'block range extends beyond current head block'}")
            return '0x1'

        with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, PAID, SPARE]), \
                mock.patch.object(tasks, '_rpc_single', side_effect=single):
            self.assertEqual(tasks._rpc('eth_getLogs', []), '0x1')
            self.assertEqual(tasks._rpc('eth_getLogs', []), '0x1')
        self.assertEqual(calls, [FREE, PAID, FREE])
        self.assertNotEqual(cache.get('cusd_plus_bsc_rpc_preferred'), PAID)

    def test_a_keyless_endpoint_that_answers_leads(self):
        # protects=a dead publicnode does not send every call through a failing first try; fails_when=keyless failover is forgotten; no_claim=TTL length
        with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, SPARE]), \
                mock.patch.object(tasks, '_rpc_single', side_effect=[RuntimeError('down'), '0x1']):
            tasks._rpc('eth_blockNumber', [])
        self.assertEqual(cache.get('cusd_plus_bsc_rpc_preferred'), SPARE)

    def test_logs_and_errors_never_carry_the_key(self):
        # protects=the NodeReal key stays out of logs; fails_when=an HTTP error repeats the keyed URL; no_claim=other loggers
        self.assertTrue(tasks._is_metered(PAID))
        self.assertFalse(tasks._is_metered(FREE))
        self.assertNotIn('a' * 32, tasks._redact(f'429 Client Error for url: {PAID}'))
