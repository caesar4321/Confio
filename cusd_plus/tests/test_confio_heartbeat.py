"""
ConfioHeartbeat keeper + monitor (cusd_plus/heartbeat.py), RPC and KMS mocked.

    AWS_PROFILE=Julian CONFIO_ENV=testnet myvenv/bin/python manage.py test \
        cusd_plus.tests.test_confio_heartbeat --keepdb
"""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from cusd_plus import heartbeat as hb

HEARTBEAT = '0x' + 'ab' * 20
BEATER = '0x' + 'cd' * 20
TX_HASH = '0x' + '12' * 32
NOW = 1_800_000_000
DAY = 86_400


def _word(value: int) -> str:
    return '0x' + format(value, 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return '0x' + addr[2:].rjust(64, '0')


class FakeSigner:
    address = '0x' + 'CD' * 20  # checksum-ish casing; compared lowercased

    def __init__(self):
        self.signed = []

    def sign_transaction(self, tx):
        self.signed.append(tx)
        return '0xraw', TX_HASH


class FakeChain:
    """Minimal JSON-RPC dispatcher for the calls heartbeat.py makes."""

    def __init__(self, *, last_beat=NOW - DAY, silence=14 * DAY, beater=BEATER,
                 balance=10**18, receipt=None, block_number=100):
        self.last_beat = last_beat
        self.silence = silence
        self.beater = beater
        self.balance = balance
        self.receipt = receipt
        self.block_number = block_number
        self.calls = []

    def __call__(self, method, params, timeout=15):
        self.calls.append(method)
        if method == 'eth_blockNumber':
            return hex(self.block_number)
        if method == 'eth_getBlockByNumber':
            return {'timestamp': hex(NOW)}
        if method == 'eth_call':
            data = params[0]['data']
            if data == hb.SEL_LAST_BEAT:
                return _word(self.last_beat)
            if data == hb.SEL_SILENCE_REQUIRED:
                return _word(self.silence)
            if data == hb.SEL_BEATER:
                return _addr_word(self.beater)
            if data == hb.SEL_BEAT:
                return '0x'
            raise AssertionError(f'unexpected eth_call {data}')
        if method == 'eth_getTransactionCount':
            return '0x7'
        if method == 'eth_gasPrice':
            return hex(100_000_000)
        if method == 'eth_getBalance':
            return hex(self.balance)
        if method == 'eth_sendRawTransaction':
            return TX_HASH
        if method == 'eth_getTransactionReceipt':
            return self.receipt
        raise AssertionError(f'unexpected rpc {method}')


def _beat_receipt(status='0x1', with_event=True, emitter=HEARTBEAT):
    logs = []
    if with_event:
        logs.append({'address': emitter, 'topics': [hb.BEAT_TOPIC], 'data': _word(NOW)})
    return {'status': status, 'blockNumber': '0x65', 'logs': logs}


@override_settings(CONFIO_HEARTBEAT_ADDRESS=HEARTBEAT, CONFIO_HEARTBEAT_KMS_KEY_ALIAS='',
                   BSC_CHAIN_ID=56, CONFIO_HEARTBEAT_RECEIPT_TIMEOUT_SECONDS=1)
class PostHeartbeatTests(SimpleTestCase):
    def setUp(self):
        self.signer = FakeSigner()
        patches = [
            mock.patch.object(hb, 'system_health', return_value=''),
            mock.patch.object(hb, '_beater_signer', return_value=(self.signer, True)),
            mock.patch('cusd_plus.sponsor_7702.acquire_sponsor_nonce_lock', return_value='tok'),
            mock.patch('cusd_plus.sponsor_7702.release_sponsor_nonce_lock'),
            mock.patch.object(hb.time, 'sleep'),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.health, self.signer_factory, self.lock, self.release, _ = self.mocks

    def _run(self, chain):
        with mock.patch.object(hb, '_rpc', chain):
            return hb.post_heartbeat()

    @override_settings(CONFIO_HEARTBEAT_ADDRESS='')
    def test_unset_address_is_noop(self):
        chain = FakeChain()
        self.assertEqual(self._run(chain), {'skipped': 'unconfigured'})
        self.assertEqual(chain.calls, [])
        self.health.assert_not_called()
        self.assertEqual(self.signer.signed, [])

    @override_settings(CONFIO_HEARTBEAT_ADDRESS='')
    def test_task_unset_address_is_noop(self):
        self.assertEqual(hb.post_confio_heartbeat.apply().get(), {'skipped': 'unconfigured'})

    def test_health_gate_failure_sends_nothing(self):
        self.health.return_value = 'database'
        chain = FakeChain(receipt=_beat_receipt())
        with self.assertRaises(hb.HeartbeatError):
            self._run(chain)
        self.assertNotIn('eth_sendRawTransaction', chain.calls)
        self.assertEqual(self.signer.signed, [])
        self.signer_factory.assert_not_called()

    def test_success_requires_beat_event(self):
        chain = FakeChain(receipt=_beat_receipt())
        result = self._run(chain)
        self.assertEqual(result['beat'], TX_HASH)
        self.assertEqual(len(self.signer.signed), 1)
        tx = self.signer.signed[0]
        self.assertEqual(tx['to'], HEARTBEAT)
        self.assertEqual(tx['data'], hb.SEL_BEAT)
        self.assertEqual(tx['nonce'], 7)
        self.lock.assert_called_once()
        self.release.assert_called_once_with('tok')

    def test_success_receipt_without_event_is_failure(self):
        chain = FakeChain(receipt=_beat_receipt(with_event=False))
        with self.assertRaisesRegex(hb.HeartbeatError, 'without a Beat event'):
            self._run(chain)

    def test_event_from_another_contract_is_failure(self):
        chain = FakeChain(receipt=_beat_receipt(emitter='0x' + 'ee' * 20))
        with self.assertRaises(hb.HeartbeatError):
            self._run(chain)

    def test_reverted_receipt_is_failure(self):
        chain = FakeChain(receipt=_beat_receipt(status='0x0'))
        with self.assertRaises(hb.HeartbeatError):
            self._run(chain)

    def test_missing_receipt_is_failure(self):
        chain = FakeChain(receipt=None)
        with self.assertRaisesRegex(hb.HeartbeatError, 'no receipt'):
            self._run(chain)

    def test_signer_not_contract_beater_sends_nothing(self):
        chain = FakeChain(beater='0x' + '99' * 20, receipt=_beat_receipt())
        with self.assertRaisesRegex(hb.HeartbeatError, 'not the contract beater'):
            self._run(chain)
        self.assertEqual(self.signer.signed, [])
        self.release.assert_called_once_with('tok')

    def test_recent_beat_skips(self):
        chain = FakeChain(last_beat=NOW - 3600, receipt=_beat_receipt())
        self.assertEqual(self._run(chain)['skipped'], 'recent')
        self.assertEqual(self.signer.signed, [])

    def test_task_retries_on_failure(self):
        self.health.return_value = 'bsc_rpc'
        with mock.patch.object(hb, '_rpc', FakeChain()), \
                mock.patch.object(hb.post_confio_heartbeat, 'retry',
                                  side_effect=RuntimeError('retry')) as retry:
            with self.assertRaisesRegex(RuntimeError, 'retry'):
                hb.post_confio_heartbeat.run()
        retry.assert_called_once()
        self.assertIsInstance(retry.call_args.kwargs['exc'], hb.HeartbeatError)

    def test_last_failed_retry_pages_the_team(self):
        self.health.return_value = 'bsc_rpc'
        with mock.patch.object(hb, '_rpc', FakeChain()), \
                mock.patch.object(hb, 'send_ops_alert') as alert, \
                mock.patch.object(hb.post_confio_heartbeat, 'retry', side_effect=RuntimeError('retry')):
            hb.post_confio_heartbeat.push_request(retries=0)
            try:
                with self.assertRaises(RuntimeError):
                    hb.post_confio_heartbeat.run()
            finally:
                hb.post_confio_heartbeat.pop_request()
            alert.assert_not_called()  # an early failure only retries
            hb.post_confio_heartbeat.push_request(retries=hb.BEAT_MAX_RETRIES)
            try:
                with self.assertRaises(RuntimeError):
                    hb.post_confio_heartbeat.run()
            finally:
                hb.post_confio_heartbeat.pop_request()
        alert.assert_called_once()
        self.assertIn('FALLÓ tras todos los reintentos', alert.call_args.args[0])


class SystemHealthTests(SimpleTestCase):
    def setUp(self):
        p = mock.patch.object(hb, 'close_old_connections')
        p.start()
        self.addCleanup(p.stop)

    def test_database_down(self):
        conn = mock.MagicMock()
        conn.cursor.side_effect = RuntimeError('db down')
        with mock.patch.object(hb, 'connection', conn), \
                mock.patch.object(hb, '_rpc', return_value='0x64') as rpc:
            self.assertEqual(hb.system_health(), 'database')
        rpc.assert_not_called()

    def test_rpc_pool_down(self):
        with mock.patch.object(hb, 'connection', mock.MagicMock()), \
                mock.patch.object(hb, '_rpc', side_effect=RuntimeError('all endpoints failed')):
            self.assertEqual(hb.system_health(), 'bsc_rpc')

    def test_healthy(self):
        with mock.patch.object(hb, 'connection', mock.MagicMock()), \
                mock.patch.object(hb, '_rpc', return_value='0x64'):
            self.assertEqual(hb.system_health(), '')


class FakeCache:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v, timeout=None):
        self.d[k] = v

    def delete(self, k):
        self.d.pop(k, None)


@override_settings(CONFIO_HEARTBEAT_ADDRESS=HEARTBEAT,
                   CONFIO_HEARTBEAT_STALE_ALERT_SECONDS=26 * 3600,
                   CONFIO_HEARTBEAT_BEATER_MIN_BALANCE_WEI=10**16)
class CheckHeartbeatTests(SimpleTestCase):
    def setUp(self):
        p = mock.patch.object(hb, 'send_ops_alert')
        self.alert = p.start()
        self.addCleanup(p.stop)
        c = mock.patch.object(hb, 'cache', FakeCache())
        self.cache = c.start()
        self.addCleanup(c.stop)

    def _run(self, chain):
        with mock.patch.object(hb, '_rpc', chain):
            return hb.check_heartbeat()

    @override_settings(CONFIO_HEARTBEAT_ADDRESS='')
    def test_unset_address_is_noop(self):
        chain = FakeChain()
        self.assertEqual(self._run(chain), {'skipped': 'unconfigured'})
        self.assertEqual(chain.calls, [])

    def test_fresh_beat_and_funded_beater_ok(self):
        with self.assertNoLogs(hb.logger, level='ERROR'):
            result = self._run(FakeChain(last_beat=NOW - 20 * 3600, balance=10**17))
        self.assertFalse(result['stale'])
        self.assertFalse(result['low_balance'])
        self.alert.assert_not_called()

    def test_stale_detected_from_chain_time(self):
        with self.assertLogs(hb.logger, level='CRITICAL') as logs:
            result = self._run(FakeChain(last_beat=NOW - 27 * 3600))
        self.assertTrue(result['stale'])
        self.assertEqual(result['age_seconds'], 27 * 3600)
        self.assertIn('STALE', logs.output[0])
        # Pages the team on Telegram, not only the log.
        self.alert.assert_called_once()
        self.assertIn('ATRASADO', self.alert.call_args.args[0])
        self.assertEqual(self.alert.call_args.kwargs['dedupe_key'], 'heartbeat_stale')

    def test_recovery_is_announced_once_after_a_stale_alert(self):
        with self.assertLogs(hb.logger, level='CRITICAL'):
            self._run(FakeChain(last_beat=NOW - 27 * 3600))
        self.alert.reset_mock()
        self._run(FakeChain(last_beat=NOW - 3600, balance=10**17))
        self.alert.assert_called_once()
        self.assertIn('recuperado', self.alert.call_args.args[0])
        self.alert.reset_mock()
        self._run(FakeChain(last_beat=NOW - 3600, balance=10**17))
        self.alert.assert_not_called()

    def test_uninitialized_contract_is_stale(self):
        with self.assertLogs(hb.logger, level='CRITICAL'):
            result = self._run(FakeChain(last_beat=0, silence=0))
        self.assertTrue(result['stale'])

    def test_low_beater_balance_detected(self):
        with self.assertLogs(hb.logger, level='ERROR') as logs:
            result = self._run(FakeChain(last_beat=NOW - 3600, balance=10**15))
        self.assertTrue(result['low_balance'])
        self.assertFalse(result['stale'])
        self.assertIn('low on BNB', logs.output[0])
        self.alert.assert_called_once()
        self.assertEqual(self.alert.call_args.kwargs['dedupe_key'], 'heartbeat_low_balance')

    def test_read_failure_alerts(self):
        with self.assertLogs(hb.logger, level='ERROR'):
            with mock.patch.object(hb, '_rpc', side_effect=RuntimeError('rpc down')):
                self.assertEqual(hb.check_heartbeat(), {'skipped': 'read_failed'})
        self.alert.assert_called_once()
        self.assertEqual(self.alert.call_args.kwargs['dedupe_key'], 'heartbeat_read_failed')


class OpsAlertTests(SimpleTestCase):
    def setUp(self):
        from config import ops_alerts
        self.ops = ops_alerts

    def test_missing_secret_is_log_only_and_never_raises(self):
        with mock.patch.object(self.ops, 'get_secret', side_effect=RuntimeError('not found')), \
                mock.patch.object(self.ops.requests, 'post') as post:
            self.assertFalse(self.ops.send_ops_alert('x'))
        post.assert_not_called()

    def test_posts_to_the_configured_chat(self):
        resp = mock.MagicMock(ok=True)
        resp.json.return_value = {'ok': True}
        with mock.patch.object(self.ops, 'get_secret', return_value={'bot_token': 'T', 'chat_id': '-100'}), \
                mock.patch.object(self.ops.requests, 'post', return_value=resp) as post:
            self.assertTrue(self.ops.send_ops_alert('hello'))
        self.assertEqual(post.call_args.args[0], 'https://api.telegram.org/botT/sendMessage')
        self.assertEqual(post.call_args.kwargs['json']['chat_id'], '-100')
        self.assertEqual(post.call_args.kwargs['json']['text'], 'hello')

    def test_telegram_failure_never_raises(self):
        with mock.patch.object(self.ops, 'get_secret', return_value={'bot_token': 'T', 'chat_id': '-100'}), \
                mock.patch.object(self.ops.requests, 'post', side_effect=RuntimeError('down')):
            self.assertFalse(self.ops.send_ops_alert('hello'))

    def test_dedupe_sends_once_per_window(self):
        resp = mock.MagicMock(ok=True)
        resp.json.return_value = {'ok': True}
        added = set()
        fake_cache = mock.MagicMock()
        fake_cache.add.side_effect = lambda k, v, timeout=None: (k not in added, added.add(k))[0]
        with mock.patch.object(self.ops, 'cache', fake_cache), \
                mock.patch.object(self.ops, 'get_secret', return_value={'bot_token': 'T', 'chat_id': '-100'}), \
                mock.patch.object(self.ops.requests, 'post', return_value=resp) as post:
            self.assertTrue(self.ops.send_ops_alert('a', dedupe_key='k', dedupe_seconds=60))
            self.assertFalse(self.ops.send_ops_alert('a', dedupe_key='k', dedupe_seconds=60))
        self.assertEqual(post.call_count, 1)


class WatchdogScriptTests(SimpleTestCase):
    def test_pinned_selectors_match_keccak(self):
        import importlib.util
        from pathlib import Path

        from eth_utils import keccak
        path = Path(__file__).resolve().parents[2] / 'scripts' / 'ops' / 'heartbeat_watchdog.py'
        spec = importlib.util.spec_from_file_location('heartbeat_watchdog', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for sig, sel in mod.SELECTORS.items():
            self.assertEqual(sel, '0x' + keccak(text=sig)[:4].hex(), sig)


class OpsAlertHardeningTests(SimpleTestCase):
    def setUp(self):
        from config import ops_alerts
        self.ops = ops_alerts

    def test_network_errors_never_log_the_token(self):
        import requests as real_requests
        err = real_requests.ConnectionError(
            "Max retries exceeded with url: /bot123456:SECRETTOKEN/sendMessage")
        with mock.patch.object(self.ops, 'get_secret',
                               return_value={'bot_token': '123456:SECRETTOKEN', 'chat_id': '-100'}), \
                mock.patch.object(self.ops.requests, 'post', side_effect=err), \
                self.assertLogs(self.ops.logger, level='ERROR') as logs:
            self.assertFalse(self.ops.send_ops_alert('x'))
        self.assertNotIn('SECRETTOKEN', '\n'.join(logs.output))

    def test_failed_send_frees_the_dedupe_window(self):
        fake_cache = mock.MagicMock()
        fake_cache.add.return_value = True
        with mock.patch.object(self.ops, 'cache', fake_cache), \
                mock.patch.object(self.ops, 'get_secret', side_effect=RuntimeError('no secret')):
            self.assertFalse(self.ops.send_ops_alert('x', dedupe_key='k', dedupe_seconds=60))
        fake_cache.delete.assert_called_once_with('ops_alert:k')


class ChatSafeTests(SimpleTestCase):
    def test_rpc_urls_lose_their_path_and_key(self):
        exc = RuntimeError('all endpoints failed: 403 for url: https://bsc.paid.example/v1/SECRETKEY123 and http://x.io/k')
        out = hb._chat_safe(exc)
        self.assertNotIn('SECRETKEY123', out)
        self.assertIn('bsc.paid.example', out)
        self.assertNotIn('/k', out)

    def test_requests_connection_error_path_is_redacted(self):
        import requests as real_requests
        try:
            real_requests.get('http://127.0.0.1:9/v1/SECRETKEY', timeout=2)
        except real_requests.RequestException as exc:
            err = RuntimeError(f'all 3 BSC RPC endpoints failed: {exc}')
        self.assertIn('SECRETKEY', str(err))  # the real format carries it
        self.assertNotIn('SECRETKEY', hb._chat_safe(err))

    @override_settings(CONFIO_HEARTBEAT_ADDRESS=HEARTBEAT)
    def test_read_failure_alert_strips_urls(self):
        with mock.patch.object(hb, 'send_ops_alert') as alert, \
                mock.patch.object(hb, '_rpc', side_effect=RuntimeError('boom https://rpc.example/key/SECRET')):
            hb.check_heartbeat()
        self.assertNotIn('SECRET', alert.call_args.args[0])


@override_settings(CONFIO_HEARTBEAT_ADDRESS=HEARTBEAT)
class DailyReportTests(SimpleTestCase):
    def test_success_posts_spanish_daily_status(self):
        with mock.patch.object(hb, '_rpc', FakeChain(last_beat=NOW - 60, balance=48 * 10**15)), \
                mock.patch.object(hb, 'send_ops_alert', return_value=True) as alert:
            self.assertTrue(hb.daily_report({'beat': '0x' + 'ab' * 32}))
        text = alert.call_args.args[0]
        self.assertIn('todo normal', text)
        self.assertIn('https://bscscan.com/tx/0x' + 'ab' * 32, text)
        self.assertIn('Salida de emergencia: cerrada', text)
        self.assertIn(hb._fecha_utc(NOW - 60 + 14 * 86400), text)
        self.assertIn('0.0480 BNB', text)
        self.assertEqual(alert.call_args.kwargs['dedupe_key'], f'heartbeat_daily:{NOW // 86400}')

    def test_spanish_date(self):
        self.assertEqual(hb._fecha_utc(1792453731), '19 oct 2026, 23:48 UTC')

    def test_task_reports_after_a_beat_and_after_a_recent_skip_only(self):
        for result, expected in (({'beat': '0x1'}, True), ({'skipped': 'recent'}, True),
                                 ({'skipped': 'unconfigured'}, False)):
            with mock.patch.object(hb, 'post_heartbeat', return_value=result), \
                    mock.patch.object(hb, 'daily_report') as report:
                self.assertEqual(hb.post_confio_heartbeat.run(), result)
            self.assertEqual(report.called, expected, result)

    def test_failed_beat_never_reports_normal(self):
        with mock.patch.object(hb, 'post_heartbeat', side_effect=hb.HeartbeatError('x')), \
                mock.patch.object(hb, 'daily_report') as report, \
                mock.patch.object(hb, 'send_ops_alert'), \
                mock.patch.object(hb.post_confio_heartbeat, 'retry', side_effect=RuntimeError('retry')):
            with self.assertRaises(RuntimeError):
                hb.post_confio_heartbeat.run()
        report.assert_not_called()


@override_settings(CONFIO_HEARTBEAT_ADDRESS=HEARTBEAT,
                   CONFIO_HEARTBEAT_BEATER_MIN_BALANCE_WEI=10**16)
class DailyReportEdgeTests(SimpleTestCase):
    def test_low_beater_balance_is_never_reported_as_normal(self):
        with mock.patch.object(hb, '_rpc', FakeChain(last_beat=NOW - 60, balance=10**15)), \
                mock.patch.object(hb, 'send_ops_alert', return_value=True) as alert:
            hb.daily_report({'beat': '0x1'})
        text = alert.call_args.args[0]
        self.assertNotIn('todo normal', text)
        self.assertIn('poco BNB', text)

    def test_report_failures_never_fail_the_beat_task(self):
        with mock.patch.object(hb, 'post_heartbeat', return_value={'beat': '0x1'}), \
                mock.patch.object(hb, 'daily_report', side_effect=OverflowError('bad date')):
            self.assertEqual(hb.post_confio_heartbeat.run(), {'beat': '0x1'})

    def test_unreadable_chain_skips_the_report(self):
        with mock.patch.object(hb, '_rpc', side_effect=RuntimeError('rpc down')), \
                mock.patch.object(hb, 'send_ops_alert') as alert:
            self.assertFalse(hb.daily_report({'beat': '0x1'}))
        alert.assert_not_called()
