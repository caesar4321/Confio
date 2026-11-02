"""The BSC RPC pool (cusd_plus/tasks._rpc): keyless endpoints lead, the
metered one only catches the call that failed over."""
from unittest import mock

import requests

from django.core.cache import cache
from django.test import SimpleTestCase

from cusd_plus import tasks

FREE = 'https://bsc-rpc.publicnode.com'
PAID = 'https://bsc-mainnet.nodereal.io/v1/' + 'a' * 32
SPARE = 'https://bsc-dataseed.bnbchain.org'


class RpcPoolTests(SimpleTestCase):
    def setUp(self):
        cache.delete('cusd_plus_bsc_rpc_preferred')
        cache.delete_many([tasks._down_key(u) for u in (FREE, PAID, SPARE)])

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

    def test_an_endpoint_that_timed_out_goes_last(self):
        # protects=a hung publicnode costs one user request, not every request for 5 minutes; fails_when=a transport failure leaves it leading; no_claim=demotion TTL
        calls = []

        def single(url, method, params, timeout=15):
            calls.append(url)
            if url == FREE:
                raise requests.ReadTimeout('Read timed out. (read timeout=4)')
            return '0x1'

        with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, PAID, SPARE]), \
                mock.patch.object(tasks, '_rpc_single', side_effect=single):
            tasks._rpc('eth_getTransactionCount', [])
            tasks._rpc('eth_getTransactionCount', [])
        # Second call: FREE is benched, and the keyless SPARE stands in for it
        # ahead of the metered PAID.
        self.assertEqual(calls, [FREE, PAID, SPARE])

    def test_a_json_rpc_error_does_not_demote(self):
        # protects=a request-specific error (range past head) does not bench a healthy node; fails_when=any exception demotes; no_claim=error classification beyond transport
        with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, SPARE]), \
                mock.patch.object(tasks, '_rpc_single', side_effect=[RuntimeError('bsc rpc: range'), '0x1']):
            tasks._rpc('eth_getLogs', [])
        self.assertFalse(tasks._demoted_urls([FREE]))

    def test_cheap_reads_fail_over_fast_but_the_last_endpoint_gets_the_full_timeout(self):
        # protects=a stalled endpoint holds a daphne thread ~4 s, not 15 s; fails_when=every attempt uses the caller timeout; no_claim=wall clock
        seen = []

        def single(url, method, params, timeout=15):
            seen.append((url, timeout))
            raise requests.ConnectionError('down')

        with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, SPARE]), \
                mock.patch.object(tasks, '_rpc_single', side_effect=single):
            with self.assertRaises(RuntimeError):
                tasks._rpc('eth_call', [])
        self.assertEqual(seen, [(FREE, tasks.RPC_FAILOVER_TIMEOUT), (SPARE, 15)])

    def test_getlogs_and_broadcasts_keep_the_caller_timeout(self):
        # protects=slow-but-valid getLogs and a raw tx that may have landed are not cut short; fails_when=the short timeout applies to them; no_claim=other methods
        for method in ('eth_getLogs', 'eth_sendRawTransaction'):
            seen = []

            def single(url, m, params, timeout=15):
                seen.append(timeout)
                if len(seen) == 1:
                    raise RuntimeError('bsc rpc: x')
                return '0x1'

            with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, SPARE]), \
                    mock.patch.object(tasks, '_rpc_single', side_effect=single):
                tasks._rpc(method, [])
            self.assertEqual(seen, [15, 15], method)

    def test_preferred_only_skips_a_demoted_endpoint(self):
        # protects=the optimistic post-broadcast peek does not walk into a known-bad node; fails_when=preferred_only ignores demotion; no_claim=rotation
        tasks._demote(FREE)
        with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, PAID, SPARE]), \
                mock.patch.object(tasks, '_rpc_single', return_value='0x1') as single:
            tasks._rpc_preferred_only('eth_getTransactionReceipt', [], 1.5)
        self.assertEqual(single.call_args.args[0], SPARE)

    def test_preferred_only_uses_the_metered_endpoint_before_a_demoted_one(self):
        # protects=the receipt peek reaches a healthy node when every keyless one is benched; fails_when=it falls back to a demoted endpoint; no_claim=cost
        tasks._demote(FREE)
        with mock.patch.object(tasks, 'BSC_RPC_URLS', [FREE, PAID]), \
                mock.patch.object(tasks, '_rpc_single', return_value='0x1') as single:
            tasks._rpc_preferred_only('eth_getTransactionReceipt', [], 1.5)
        self.assertEqual(single.call_args.args[0], PAID)
