"""The inbound scanners move a cursor only past work that is committed.

Found 2026-11-22: the cursor was saved right after the fetch, so a worker
killed while processing lost every deposit older than the rewind.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from cusd_plus import tasks

VAULT = '0x' + '11' * 20
CUSD = '0x' + '22' * 20
HOLDER = '0x' + 'a1' * 20
FRIEND = '0x' + 'b2' * 20
STRANGER = '0x' + 'c9' * 20
REWIND = 100
START = 100_000
OLD = START + 10  # far older than the rewind behind HEAD
HEAD = START + 1_000
BEAT = 50


class WorkerKilled(BaseException):
    """Like WorkerLostError's cause: nothing in the task can catch it."""


def _transfer(n, block, to=HOLDER, usd=5, token=None, index=1, sender=STRANGER):
    return {
        'address': token or tasks.USDT_BSC,
        'topics': [tasks.TRANSFER_TOPIC, tasks._address_topic(sender), tasks._address_topic(to)],
        'data': hex(usd * 10 ** 18),
        'transactionHash': '0x' + f'{n:02x}' * 32,  # idempotency keys use a hash prefix
        'logIndex': hex(index),
        'blockNumber': hex(block),
    }


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                        'LOCATION': 'inbound-scan-cursor'}},
    CUSD_PLUS_VAULT_ADDRESS=VAULT, CUSD_VAULT_ADDRESS=CUSD, MARKETPLACE_ESCROW_ADDRESS='',
    CUSD_PLUS_BSC_SCAN_REWIND_BLOCKS=REWIND, CUSD_PLUS_MIN_EXTERNAL_DEPOSIT_USD=1)
class InboundScanCursorTests(TestCase):
    def setUp(self):
        from users.models import Account, User

        cache.clear()
        self.addCleanup(cache.clear)
        for name, address in (('holder', HOLDER), ('friend', FRIEND)):
            user = User.objects.create(username=f'scan-{name}', firebase_uid=f'scan-{name}')
            Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address=address)
            if name == 'holder':
                self.user = user
        cache.set('cusd_plus_bsc_scan_cursor', START, None)
        cache.set('cusd_plus_cusd_scan_cursor', START, None)
        cache.set('cusd_plus_cusd_epoch', {'id': 'test', 'from': START}, None)
        self.head = HEAD
        self.chain = []
        self.down = set()  # token addresses whose getLogs fails
        self.ranges = []
        self.mined_at_head = timezone.now().timestamp()  # HEAD's block time
        for target, kwargs in (
                ('cusd_plus.tasks._rpc', {'side_effect': self._rpc}),
                ('cusd_plus.tasks._get_logs_chunked', {'side_effect': self._get_logs}),
                ('cusd_plus.tasks._mark_receipt_balances_stale', {}),
                ('cusd_plus.vault.p_plus_wad', {'return_value': 10 ** 18}),
                ('cusd_plus.vault.invalidate_position', {}),
                ('notifications.utils.send_push_notification', {'return_value': {'success': True, 'sent': 1, 'failed': 0}})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _rpc(self, method, params, timeout=15):
        if method == 'eth_blockNumber':
            return hex(self.head + tasks.SCAN_HEAD_MARGIN_BLOCKS)
        if method == 'eth_getBlockByNumber':
            return {'timestamp': hex(int(self.mined_at_head - (HEAD - int(params[0], 16)) * 0.45))}
        raise AssertionError(method)

    def _get_logs(self, start, end, topics, address=tasks.USDT_BSC):
        if address in self.down:
            raise RuntimeError('rpc down')
        self.ranges.append((address, start, end))
        return [log for log in self.chain
                if log['address'] == address and start <= int(log['blockNumber'], 16) <= end
                and log['topics'][2] in topics[2]]

    def _scan(self):
        tasks.monitor_bridge_arrivals()

    def _later(self, beats=1):
        for _ in range(beats):
            self.head += BEAT
            self._scan()

    def _rows(self, log):
        from send.models import SendTransaction
        return SendTransaction.all_objects.filter(transaction_hash=log['transactionHash']).count()

    def _notices(self, log):
        from notifications.models import Notification
        return Notification.objects.filter(data__tx_hash=log['transactionHash']).count()

    def _ramp(self):
        from ramps.models import RampTransaction
        return RampTransaction.objects.create(
            provider='koywe', direction='on_ramp', status='PENDING', destination='cusd_plus',
            actor_user=self.user, actor_address=HOLDER, crypto_amount_estimated=Decimal('5'))

    def _saga(self, committed_at=None):
        from conversion.models import Conversion
        return Conversion.objects.create(
            actor_user=self.user, actor_type='user', actor_address=HOLDER, conversion_type='to_savings',
            from_amount=Decimal('5'), to_amount=Decimal('5'), user_bsc_address=HOLDER,
            status='SRC_COMMITTED',
            src_committed_at=committed_at or timezone.now() - timedelta(minutes=20))

    def _fail_once_for(self, name, log, error):
        """`name` raises the first time it is called for this log."""
        real, failed = getattr(tasks, name), []

        def call(*args, **kwargs):
            seen = kwargs.get('tx_hash') or args[0]
            if seen == log['transactionHash'] and not failed:
                failed.append(True)
                raise error
            return real(*args, **kwargs)

        return mock.patch.object(tasks, name, side_effect=call)

    # ── killed mid-run ──────────────────────────────────────────────────

    def test_a_kill_after_the_fetch_loses_no_usdt_deposit(self):
        first, second = _transfer(1, OLD), _transfer(2, OLD + 1)
        self.chain = [first, second]
        with self._fail_once_for('_record_inbound_deposit', second, WorkerKilled()):
            with self.assertRaises(WorkerKilled):
                self._scan()
        self._later()
        for log in (first, second):
            self.assertEqual((self._rows(log), self._notices(log)), (1, 1))

    def test_a_kill_after_the_fetch_still_lets_a_conversion_complete(self):
        saga = self._saga()
        self.chain = [_transfer(1, OLD)]
        with mock.patch.object(tasks, '_mark_bridge_arrived', side_effect=WorkerKilled):
            with self.assertRaises(WorkerKilled):
                self._scan()
        self._later()
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'DEST_ARRIVED')

    def test_a_kill_in_the_share_pass_loses_no_share_deposit(self):
        log = _transfer(1, OLD, token=VAULT)
        self.chain = [log]
        with mock.patch('cusd_plus.vault.p_plus_wad', side_effect=WorkerKilled):
            with self.assertRaises(WorkerKilled):
                self._scan()
        self._later()
        self.assertEqual((self._rows(log), self._notices(log)), (1, 1))

    # ── a pass or a write that fails ────────────────────────────────────

    def test_a_failed_share_pass_rescans_its_own_window(self):
        log = _transfer(1, OLD, token=VAULT)
        self.chain = [log]
        self.down = {VAULT}
        self._scan()
        self._later(3)
        self.down = set()
        self._later()
        self.assertEqual(self._rows(log), 1)

    def test_a_failed_receipt_write_is_retried_past_the_rewind(self):
        from send.models import SendTransaction

        log = _transfer(1, OLD)
        self.chain = [log]
        with mock.patch.object(SendTransaction.all_objects, 'create', side_effect=RuntimeError('db')):
            self._scan()
        self._later()
        self.assertEqual((self._rows(log), self._notices(log)), (1, 1))

    def test_a_failed_bridge_mark_is_retried_and_never_called_stuck(self):
        saga = self._saga(timezone.now() - timedelta(hours=2))
        self.chain = [_transfer(1, OLD)]
        with mock.patch.object(tasks, '_mark_bridge_arrived', side_effect=RuntimeError('db')):
            self._scan()
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'SRC_COMMITTED')
        self._later()
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'DEST_ARRIVED')

    # ── poison logs ─────────────────────────────────────────────────────

    def test_a_poison_usdt_log_stalls_nothing_and_is_retried(self):
        poison, good = _transfer(1, OLD), _transfer(2, OLD + 1)
        self.chain = [poison, good]
        real = tasks._record_inbound_deposit

        def record(**kwargs):
            if kwargs['tx_hash'] == poison['transactionHash']:
                raise ValueError('poison')
            return real(**kwargs)

        with mock.patch.object(tasks, '_record_inbound_deposit', side_effect=record):
            self._scan()
            self._later(3)
            self.assertEqual((self._rows(poison), self._rows(good)), (0, 1))
            self.assertEqual(cache.get('cusd_plus_bsc_scan_cursor'), self.head)
        self._later()
        self.assertEqual((self._rows(poison), self._notices(poison)), (1, 1))

    def test_a_malformed_log_stalls_nothing(self):
        bad, good = dict(_transfer(1, OLD), data='0x'), _transfer(2, OLD + 1)
        self.chain = [bad, good]
        self._scan()
        self.assertEqual(self._rows(good), 1)

    def test_a_poison_share_log_stalls_nothing_and_is_retried(self):
        poison, good = _transfer(1, OLD, token=VAULT), _transfer(2, OLD + 1, token=VAULT)
        poison['topics'][1] = tasks._address_topic(FRIEND)  # an internal sender asks who owns it
        self.chain = [poison, good]
        with mock.patch.object(tasks, '_source_row_covers', side_effect=RuntimeError('poison')):
            self._scan()
            self._later(3)
            self.assertEqual((self._rows(poison), self._rows(good)), (0, 1))
        self._later()
        self.assertEqual(self._rows(poison), 1)

    def test_one_transaction_paying_two_holders_does_not_poison_the_share_pass(self):
        first = _transfer(1, OLD, token=VAULT)
        shared = _transfer(1, OLD, to=FRIEND, token=VAULT, index=2)
        after = _transfer(2, OLD + 1, token=VAULT)
        self.chain = [first, shared, after]
        self._scan()
        self.assertEqual((self._rows(first), self._rows(after)), (1, 1))
        self.assertFalse(cache.get('cusd_plus_bsc_share_scan_retry'))  # known limit: nothing to retry

    def test_a_poison_cusd_group_stalls_nothing_and_is_retried_whole(self):
        from send.models import SendTransaction

        poison = [_transfer(1, OLD, token=CUSD), _transfer(1, OLD, token=CUSD, usd=3, index=2)]
        good = _transfer(2, OLD + 1, token=CUSD)
        self.chain = poison + [good]
        with self._fail_once_for('_source_row_covers', good, RuntimeError('poison')):
            self._scan()
        self.assertEqual((self._rows(poison[0]), self._rows(good)), (1, 0))
        self._later()
        self.assertEqual(self._rows(good), 1)

        group = [_transfer(3, self.head + 1, token=CUSD), _transfer(3, self.head + 1, token=CUSD, usd=3, index=2)]
        self.chain += group
        with self._fail_once_for('_source_row_covers', group[0], RuntimeError('poison')):
            self._later()
        self.head += REWIND * 3
        self._scan()
        self.assertEqual(SendTransaction.all_objects.get(transaction_hash=group[0]['transactionHash']).amount, 8)

    def test_the_cursor_stays_when_a_failed_log_cannot_be_saved(self):
        self.chain = [_transfer(1, OLD)]
        real_set = cache.set

        def save(key, *args, **kwargs):
            if key.endswith('_retry'):
                raise ConnectionError('cache down')
            return real_set(key, *args, **kwargs)

        with mock.patch.object(tasks, '_record_inbound_deposit', side_effect=RuntimeError('db')), \
                mock.patch.object(cache, 'set', side_effect=save):
            with self.assertRaises(ConnectionError):
                self._scan()
        self.assertEqual(cache.get('cusd_plus_bsc_scan_cursor'), START)

    # ── backlogs ────────────────────────────────────────────────────────

    def test_a_backlog_is_read_in_bounded_windows_without_a_gap(self):
        logs = [_transfer(1, OLD), _transfer(2, OLD, token=VAULT), _transfer(3, OLD, token=CUSD),
                _transfer(4, START + 11_900)]
        self.chain = logs
        self.head = START + 12_000
        self._scan()
        self.assertLessEqual(max(end - start for _, start, end in self.ranges), 5_000 + REWIND)
        self.assertLess(cache.get('cusd_plus_bsc_scan_cursor'), self.head)
        self._later(3)
        self.assertEqual([self._rows(log) for log in logs], [1, 1, 1, 1])
        self.assertEqual(cache.get('cusd_plus_bsc_scan_cursor'), self.head)

    def test_no_saga_is_stuck_before_the_scan_reaches_the_head(self):
        saga = self._saga(timezone.now() - timedelta(hours=2))
        self.head = START + 12_000
        self._scan()
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'SRC_COMMITTED')
        self._later(3)
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'STUCK')

    # ── replays stay idempotent ─────────────────────────────────────────

    def test_replaying_a_whole_window_writes_nothing_twice(self):
        self.chain = [_transfer(1, OLD), _transfer(2, OLD, token=VAULT), _transfer(3, OLD, token=CUSD)]
        self._scan()
        for key in ('cusd_plus_bsc_scan_cursor', 'cusd_plus_bsc_share_scan_cursor', 'cusd_plus_cusd_scan_cursor'):
            cache.set(key, START, None)
        self._scan()
        for log in self.chain:
            self.assertEqual((self._rows(log), self._notices(log)), (1, 1))

    def test_a_second_arrival_at_a_saga_address_is_still_recorded(self):
        saga = self._saga()
        other, bridge = _transfer(1, OLD, usd=9), _transfer(2, OLD + 1)
        self.chain = [other, bridge]
        self._scan()
        self._later()
        saga.refresh_from_db()
        self.assertEqual(saga.bridge_arrival_tx, bridge['transactionHash'])
        self.assertEqual((self._rows(other), self._rows(bridge)), (1, 0))

    def test_a_replayed_arrival_never_completes_the_next_saga(self):
        self._saga()
        self.chain = [_transfer(1, OLD)]
        self._scan()
        following = self._saga()
        cache.set('cusd_plus_bsc_scan_cursor', START, None)
        self._scan()
        following.refresh_from_db()
        self.assertEqual(following.status, 'SRC_COMMITTED')

    def test_a_replay_of_a_linked_ramps_transfer_is_no_deposit(self):
        from ramps.models import RampTransaction

        log = _transfer(1, OLD)
        self.chain = [log]
        ramp = mock.MagicMock()
        ramp.exists.return_value = True
        real = RampTransaction.objects.filter

        def claimed(*args, **kwargs):
            if kwargs.get('metadata__bsc_arrival_tx_hash') == log['transactionHash']:
                return ramp  # claimed and linked: no longer in the ramp watch set
            return real(*args, **kwargs)

        with mock.patch.object(RampTransaction.objects, 'filter', side_effect=claimed):
            self._scan()
        self.assertEqual((self._rows(log), self._notices(log)), (0, 0))

    def test_a_killed_cold_run_restarts_from_the_same_block(self):
        cache.clear()
        log = _transfer(1, HEAD - 1_150)
        self.chain = [log]
        with mock.patch.object(tasks, '_record_inbound_deposit', side_effect=WorkerKilled):
            with self.assertRaises(WorkerKilled):
                self._scan()
        self.head += REWIND * 3
        self._scan()
        self.assertEqual(self._rows(log), 1)

    def test_a_retried_deposit_never_completes_a_saga_committed_after_it(self):
        log = _transfer(1, OLD)
        self.chain = [log]
        with self._fail_once_for('_record_inbound_deposit', log, RuntimeError('db')):
            self._scan()
        saga = self._saga(timezone.now())
        self._later()
        saga.refresh_from_db()
        self.assertEqual((saga.status, self._rows(log)), ('SRC_COMMITTED', 1))

    # ── judged the same on a replay as on time ──────────────────────────

    def test_the_delivery_not_the_newest_transfer_completes_the_saga(self):
        saga = self._saga()
        bridge, later = _transfer(1, OLD), _transfer(2, OLD + 1, usd=500)
        self.chain = [bridge, later]
        self._scan()
        self._later()
        saga.refresh_from_db()
        self.assertEqual((saga.bridge_arrival_tx, saga.to_amount), (bridge['transactionHash'], Decimal('5')))
        self.assertEqual((self._rows(bridge), self._rows(later)), (0, 1))

    def test_an_old_delivery_goes_to_the_saga_that_was_waiting_then(self):
        late = self._saga(timezone.now())  # created first, committed after the block
        waiting = self._saga()
        self.chain = [_transfer(1, OLD)]
        self._scan()
        late.refresh_from_db()
        waiting.refresh_from_db()
        self.assertEqual((late.status, waiting.status), ('SRC_COMMITTED', 'DEST_ARRIVED'))

    @override_settings(KOYWE_BSC_SETTLEMENT_ADDRESSES=[STRANGER])
    def test_a_replayed_deposit_is_not_given_to_a_newer_ramp(self):
        log = _transfer(1, OLD)
        self.chain = [log]
        self._scan()
        ramp = self._ramp()
        cache.set('cusd_plus_bsc_scan_cursor', START, None)
        self._scan()
        ramp.refresh_from_db()
        self.assertFalse((ramp.metadata or {}).get('bsc_arrival_tx_hash'))

    @override_settings(KOYWE_BSC_SETTLEMENT_ADDRESSES=[STRANGER])
    def test_a_late_delivery_goes_to_the_order_open_when_it_was_mined(self):
        from ramps.models import RampTransaction

        waiting, newer = self._ramp(), self._ramp()
        RampTransaction.objects.filter(pk=waiting.pk).update(created_at=timezone.now() - timedelta(minutes=30))
        log = _transfer(1, OLD)
        self.chain = [log]
        self._scan()
        waiting.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(waiting.metadata['bsc_arrival_tx_hash'], log['transactionHash'])
        self.assertFalse((newer.metadata or {}).get('bsc_arrival_tx_hash'))
        self.assertEqual(self._rows(log), 0)

    def test_a_failed_ramp_attribution_is_retried_not_filed_as_a_deposit(self):
        self._ramp()
        log = _transfer(1, OLD)
        self.chain = [log]
        with mock.patch('ramps.signals.attribute_bsc_ramp_arrival', side_effect=RuntimeError('lock')):
            self._scan()
        self.assertEqual(self._rows(log), 0)
        self.assertTrue(cache.get(tasks.USDT_RETRY_KEY))

    def test_a_retry_survives_the_wallet_re_enrolling(self):
        from users.models import Account

        log = _transfer(1, OLD)
        self.chain = [log]
        with self._fail_once_for('_record_inbound_deposit', log, RuntimeError('db')):
            self._scan()
        Account.objects.filter(bsc_address=HOLDER).update(bsc_address='0x' + 'd4' * 20)
        cache.delete('cusd_plus_bsc_registered_v1')
        self._later()
        self.assertEqual(self._rows(log), 1)

    def test_a_cusd_group_with_an_unreadable_log_is_not_recorded_short(self):
        good = _transfer(1, OLD, token=CUSD)
        self.chain = [good, dict(_transfer(1, OLD, token=CUSD, usd=3, index=2), data='0x')]
        self._scan()
        self.assertEqual(self._rows(good), 0)

    def test_a_wrap_waits_for_the_cusd_it_may_have_converted(self):
        self.assertTrue(tasks._wrap_must_wait(HOLDER, OLD + 5, OLD))  # the cUSD pass is behind it
        self.assertFalse(tasks._wrap_must_wait(HOLDER, OLD + 5, HEAD))
        arrival = _transfer(1, OLD, token=CUSD)
        entry = {'log': arrival, 'attempts': 1, 'replay': True}  # failed only on a rescan
        cache.set(tasks.CUSD_RETRY_KEY, {'a': entry}, None)
        self.assertFalse(tasks._wrap_must_wait(HOLDER, OLD + 5, HEAD))
        cache.set(tasks.CUSD_RETRY_KEY, {'a': {**entry, 'replay': False}}, None)
        self.assertTrue(tasks._wrap_must_wait(HOLDER, OLD + 5, HEAD))
        self.assertFalse(tasks._wrap_must_wait(HOLDER, OLD - 1, HEAD))

    def test_a_failed_cusd_replay_leaves_the_clean_span_open(self):
        log = _transfer(1, OLD, token=CUSD)
        self.chain = [log]
        self._scan()
        mark = {'epoch': 'test', 'spans': [[START, None]]}
        cache.set(tasks.CUSD_CLEAN_KEY.format(HOLDER), mark, None)
        cache.set(tasks.CUSD_CURSOR_KEY, OLD + 20, None)
        with self._fail_once_for('_source_row_covers', log, RuntimeError('db')):
            self._scan()
        self.assertEqual(cache.get(tasks.CUSD_CLEAN_KEY.format(HOLDER)), mark)
        self.assertTrue(all(e['replay'] for e in cache.get(tasks.CUSD_RETRY_KEY).values()))

    def test_after_a_rollback_no_share_backlog_is_jumped(self):
        self.down = {VAULT}
        log = _transfer(1, OLD, token=VAULT)
        self.chain = [log]
        self._scan()
        moved = self.head + 2_000  # the previous release moved only this key
        cache.set('cusd_plus_bsc_scan_cursor', moved, None)
        self.head = moved + BEAT
        self.down = set()
        self._scan()
        self.assertEqual(self._rows(log), 1)

    def test_a_node_behind_the_cursor_proves_no_silence(self):
        saga = self._saga(timezone.now() - timedelta(hours=2))
        for head in (START - 10, -tasks.SCAN_HEAD_MARGIN_BLOCKS):
            self.head = head
            self._scan()
            self.assertEqual(cache.get('cusd_plus_bsc_scan_cursor'), START)
            self.assertEqual(cache.get(tasks.CUSD_CURSOR_KEY), START)
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'SRC_COMMITTED')

    def test_only_one_scan_runs_at_a_time(self):
        from django.db import connection

        other = connection.copy()
        try:
            with other.cursor() as db:
                db.execute('SELECT pg_advisory_lock(%s)', [tasks.SCAN_LOCK_ID])
            self._scan()
            self.assertEqual(self.ranges, [])
        finally:
            other.close()
        self._scan()
        self.assertTrue(self.ranges)

    def test_a_saga_waits_while_one_of_its_transfers_is_unread(self):
        saga = self._saga()
        bridge, later = _transfer(1, OLD), _transfer(2, OLD + 1, usd=500)
        self.chain = [bridge, later]
        def owned(tx, _wallet):
            if tx == bridge['transactionHash']:
                raise RuntimeError('db')
            return False

        with mock.patch('payment_accounts.activity.arrival_owned', side_effect=owned):
            self._scan()
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'SRC_COMMITTED')
        self._later()
        saga.refresh_from_db()
        self.assertEqual(saga.bridge_arrival_tx, bridge['transactionHash'])

    def test_an_unreadable_saga_address_does_not_stop_the_scan(self):
        from conversion.models import Conversion

        saga = self._saga()
        Conversion.objects.filter(pk=saga.pk).update(user_bsc_address='not-an-address')
        self.chain = [_transfer(1, OLD)]
        self._scan()
        self.assertEqual(self._rows(self.chain[0]), 1)
