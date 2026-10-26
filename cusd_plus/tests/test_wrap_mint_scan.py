"""cUSD from outside Confío gets its own row, so a wrap of the member's own
cUSD into cUSD+ is never a second deposit (Comprar payouts showed twice on
prod: the sale and an "Ahorro acreditado" push)."""
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from cusd_plus import tasks

VAULT = '0x' + '11' * 20
CUSD = '0x' + '22' * 20
ESCROW = '0x' + 'e5' * 20
HOLDER = '0x' + 'a1' * 20
ZERO = '0x' + '0' * 40


def _topic(address):
    return '0x' + address[2:].rjust(64, '0')


def _transfer(sender, tx_hash, usd=2):
    return {'topics': [tasks.TRANSFER_TOPIC, _topic(sender), _topic(HOLDER)], 'data': hex(usd * 10 ** 18),
            'transactionHash': tx_hash, 'logIndex': '0x1', 'blockNumber': hex(150)}


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, CUSD_VAULT_ADDRESS=CUSD, MARKETPLACE_ESCROW_ADDRESS=ESCROW)
class WrapMintScanTests(TestCase):
    def setUp(self):
        from users.models import Account, User

        for key in (tasks.CUSD_EPOCH_KEY, tasks.CUSD_CURSOR_KEY, tasks.CUSD_CLEAN_KEY.format(HOLDER)):
            cache.delete(key)
            self.addCleanup(cache.delete, key)
        self.user = User.objects.create(username='wrapper', firebase_uid='wrapper')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                              bsc_address=HOLDER)
        self.head = 1_000
        self.balance = 0  # the holder's cUSD after a wrap (the app wraps it all)

    def _rpc(self, method, params, timeout=15):
        if method == 'eth_blockNumber':
            return hex(self.head)
        if method == 'eth_call':
            self.assertEqual(params[0]['to'], CUSD)
            return hex(self.balance)
        raise AssertionError(method)

    def _batch(self, tx_hash, holder=HOLDER):
        from blockchain.models import SponsoredBatch

        SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=holder, kind='wrap_cusd', calls_json='[]', num_calls=1,
            gas_limit=1, max_fee_wei=1, tx_hash=tx_hash, status='confirmed',
            client_request_id=str(uuid.uuid4()))

    def _scan_cusd(self, logs=()):
        def get_logs(from_block, to_block, topics, address=None):
            self.assertEqual((address, to_block), (CUSD, self.head))
            return list(logs)

        with mock.patch.object(tasks, '_get_logs_chunked', side_effect=get_logs), \
                mock.patch('notifications.fcm_service.send_push_notification'):
            tasks._scan_cusd_arrivals({HOLDER: self.account.id}, self.head, 1, 100)

    def _wrap(self, tx, block):
        """A wrap mined at `block`, seen by the cUSD+ pass."""
        self._batch(tx)
        mint = dict(_transfer(ZERO, tx), blockNumber=hex(block))
        with mock.patch.object(tasks, '_get_logs_chunked', return_value=[mint]), \
                mock.patch.object(tasks, '_rpc', side_effect=self._rpc), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=10 ** 18), \
                mock.patch('cusd_plus.vault.invalidate_position'), \
                mock.patch('notifications.fcm_service.send_push_notification'):
            tasks._scan_cusd_plus_arrivals({HOLDER: self.account.id}, 1, 2, 1)

    def _recorded(self, tx):
        from send.models import SendTransaction
        return SendTransaction.all_objects.filter(transaction_hash=tx).exists()

    def test_the_wrap_after_a_clean_one_is_no_deposit(self):
        from notifications.models import Notification

        self._scan_cusd()
        first, second = '0x' + 'fd' * 32, '0x' + 'fe' * 32
        self._wrap(first, 990)  # the first since: its row stays, and it leaves the balance at zero
        self.assertTrue(self._recorded(first))
        self.head = 1_050
        self._scan_cusd()  # the pass runs on past the next wrap
        self._wrap('0x' + second[2:].upper(), 1_040)
        self.assertFalse(self._recorded(second))
        self.assertFalse(Notification.objects.filter(data__tx_hash=second).exists())

    def test_a_wrap_leaving_cusd_behind_is_not_clean(self):
        self._scan_cusd()
        self.balance = 5 * 10 ** 18  # cUSD older than the pass may be in there
        self._wrap('0x' + 'fd' * 32, 990)
        self.head = 1_050
        self._scan_cusd()
        tx = '0x' + 'fe' * 32
        self._wrap(tx, 1_040)
        self.assertTrue(self._recorded(tx))

    def test_a_wrap_the_pass_has_not_reached_keeps_its_row(self):
        self._scan_cusd()
        self._wrap('0x' + 'fd' * 32, 990)
        tx = '0x' + 'fe' * 32
        self._wrap(tx, 1_040)  # pass cursor still at 1000
        self.assertTrue(self._recorded(tx))

    def test_a_new_epoch_voids_clean_marks(self):
        self._scan_cusd()
        self._wrap('0x' + 'fd' * 32, 990)
        self.head = 1_000 + tasks.CUSD_MAX_LAG_BLOCKS + 10  # fell behind: a gap
        self._scan_cusd()
        tx = '0x' + 'fe' * 32
        self._wrap(tx, self.head - 5)
        self.assertTrue(self._recorded(tx))

    def test_someone_elses_wrap_is_not_ours(self):
        from blockchain.models import SponsoredBatch

        self._scan_cusd()
        self._wrap('0x' + 'fd' * 32, 990)
        self.head = 1_050
        self._scan_cusd()
        tx = '0x' + 'ef' * 32
        SponsoredBatch.objects.create(
            user=self.user, user_bsc_address='0x' + 'b2' * 20, kind='wrap_cusd', calls_json='[]',
            num_calls=1, gas_limit=1, max_fee_wei=1, tx_hash=tx, status='confirmed',
            client_request_id=str(uuid.uuid4()))
        mint = dict(_transfer(ZERO, tx), blockNumber=hex(1_040))
        with mock.patch.object(tasks, '_get_logs_chunked', return_value=[mint]), \
                mock.patch.object(tasks, '_rpc', side_effect=self._rpc), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=10 ** 18), \
                mock.patch('cusd_plus.vault.invalidate_position'), \
                mock.patch('notifications.fcm_service.send_push_notification'):
            tasks._scan_cusd_plus_arrivals({HOLDER: self.account.id}, 1, 2, 1)
        self.assertTrue(self._recorded(tx))

    def test_outside_cusd_is_a_deposit_and_confio_flows_are_not(self):
        from notifications.models import Notification
        from send.models import SendTransaction

        stranger, payout, mint, vault_leg = ('0x' + c * 32 for c in ('c1', 'c2', 'c3', 'c4'))
        self._scan_cusd([
            _transfer('0x' + 'c9' * 20, stranger),
            _transfer(ESCROW, payout),  # Comprar: its order row is the record
            _transfer(ZERO, mint),  # a conversion's mint
            _transfer(VAULT, vault_leg),  # a vault leg
        ])
        row = SendTransaction.all_objects.get(transaction_hash=stranger)
        self.assertEqual((row.token_type, row.sender_type, row.amount), ('CUSD_BSC', 'external', 2))
        notice = Notification.objects.get(data__tx_hash=stranger)
        self.assertIn('Confío Dollar.', notice.message)
        for tx in (payout, mint, vault_leg):
            self.assertFalse(self._recorded(tx), tx)
        self._scan_cusd([_transfer('0x' + 'c9' * 20, stranger)])  # rescan: nothing twice
        self.assertEqual(SendTransaction.all_objects.filter(transaction_hash=stranger).count(), 1)

    def test_two_transfers_in_one_transaction_are_summed(self):
        from send.models import SendTransaction

        tx = '0x' + 'c5' * 32
        second = dict(_transfer('0x' + 'c9' * 20, tx, usd=3), logIndex='0x2')
        self._scan_cusd([_transfer('0x' + 'c9' * 20, tx), second])
        self.assertEqual(SendTransaction.all_objects.get(transaction_hash=tx).amount, 5)

    def test_a_recorded_send_is_not_recorded_again(self):
        from send.models import SendTransaction

        tx = '0x' + 'c6' * 32
        SendTransaction.all_objects.create(
            sender_type='user', recipient_type='user', recipient_user=self.user, sender_display_name='Ana',
            recipient_display_name='Yo', sender_address='0x' + 'c7' * 20, recipient_address=HOLDER,
            amount='2', token_type='CUSD_BSC', status='CONFIRMED', transaction_hash=tx,
            idempotency_key='send-c6', error_message='')
        self._scan_cusd([_transfer('0x' + 'c7' * 20, tx)])
        self.assertEqual(SendTransaction.all_objects.filter(transaction_hash=tx).count(), 1)

    def test_a_failed_pass_does_not_advance(self):
        self._scan_cusd()
        self.head = 1_050
        with mock.patch.object(tasks, '_get_logs_chunked', side_effect=RuntimeError('rpc down')):
            with self.assertRaises(RuntimeError):
                tasks._scan_cusd_arrivals({HOLDER: self.account.id}, self.head, 1, 100)
        self.assertEqual(cache.get(tasks.CUSD_CURSOR_KEY), 1_000)

    def _clean_then(self, logs):
        """Clean at 990, then a window with these arrivals, then a wrap at 1040."""
        self._scan_cusd()
        self._wrap('0x' + 'fd' * 32, 990)
        self.head = 1_050
        self._scan_cusd(logs)
        tx = '0x' + 'fe' * 32
        self._wrap(tx, 1_040)
        return tx

    def test_dust_keeps_the_next_wrap_on_record(self):
        tx = self._clean_then([dict(_transfer('0x' + 'c9' * 20, '0x' + 'd1' * 32, usd=0), blockNumber=hex(1_020))])
        self.assertTrue(self._recorded(tx))

    def test_an_arrival_sharing_a_recorded_hash_keeps_the_next_wrap_on_record(self):
        from send.models import SendTransaction

        shared = '0x' + 'd2' * 32
        SendTransaction.all_objects.create(
            sender_type='external', recipient_type='user', sender_display_name='', recipient_display_name='B',
            sender_address='0x' + 'c9' * 20, recipient_address='0x' + 'b2' * 20, amount='2',
            token_type='CUSD_BSC', status='CONFIRMED', transaction_hash=shared, idempotency_key='cu:other',
            error_message='')
        tx = self._clean_then([dict(_transfer('0x' + 'c9' * 20, shared), blockNumber=hex(1_020))])
        self.assertTrue(self._recorded(tx))

    def test_a_rescan_keeps_a_skipped_wrap_skipped(self):
        tx = self._clean_then([])
        self.assertFalse(self._recorded(tx))
        self.head = 1_100
        self._scan_cusd()
        mint = dict(_transfer(ZERO, tx), blockNumber=hex(1_040))
        with mock.patch.object(tasks, '_get_logs_chunked', return_value=[mint]), \
                mock.patch.object(tasks, '_rpc', side_effect=self._rpc), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=10 ** 18), \
                mock.patch('cusd_plus.vault.invalidate_position'), \
                mock.patch('notifications.fcm_service.send_push_notification'):
            tasks._scan_cusd_plus_arrivals({HOLDER: self.account.id}, 1, 2, 1)
        self.assertFalse(self._recorded(tx))

    def test_dust_after_a_skipped_wrap_does_not_resurrect_it(self):
        tx = self._clean_then([])
        self.assertFalse(self._recorded(tx))
        self.head = 1_100
        self._scan_cusd([dict(_transfer('0x' + 'c9' * 20, '0x' + 'd3' * 32, usd=0), blockNumber=hex(1_060))])
        mint = dict(_transfer(ZERO, tx), blockNumber=hex(1_040))
        with mock.patch.object(tasks, '_get_logs_chunked', return_value=[mint]), \
                mock.patch.object(tasks, '_rpc', side_effect=self._rpc), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=10 ** 18), \
                mock.patch('cusd_plus.vault.invalidate_position'), \
                mock.patch('notifications.fcm_service.send_push_notification'):
            tasks._scan_cusd_plus_arrivals({HOLDER: self.account.id}, 1, 2, 1)
        self.assertFalse(self._recorded(tx))
        later = '0x' + 'f1' * 32
        self.head = 1_120
        self._scan_cusd()
        self._wrap(later, 1_080)  # after the dust: keeps its row
        self.assertTrue(self._recorded(later))

    def test_a_members_send_is_never_an_outside_deposit(self):
        # Mined before the send's row has its hash: still the send's.
        from blockchain.models import SponsoredBatch
        from users.models import Account, User

        friend = User.objects.create(username='friend', firebase_uid='friend')
        friend_addr = '0x' + 'f2' * 20
        friend_account = Account.objects.create(user=friend, account_type='personal', account_index=0,
                                                bsc_address=friend_addr)
        send, batched = '0x' + 'e1' * 32, '0x' + 'e2' * 32
        SponsoredBatch.objects.create(
            user=friend, user_bsc_address='0x' + 'f3' * 20, kind='send_cusd', calls_json='[]', num_calls=1,
            gas_limit=1, max_fee_wei=1, tx_hash=batched, status='sent', client_request_id=str(uuid.uuid4()))

        def get_logs(from_block, to_block, topics, address=None):
            return [_transfer(friend_addr, send), _transfer('0x' + 'f3' * 20, batched)]

        with mock.patch.object(tasks, '_get_logs_chunked', side_effect=get_logs):
            tasks._scan_cusd_arrivals({HOLDER: self.account.id, friend_addr: friend_account.id}, self.head, 1, 100)
        self.assertFalse(self._recorded(send))
        self.assertFalse(self._recorded(batched))
