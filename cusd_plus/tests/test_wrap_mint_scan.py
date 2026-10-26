"""A wrap of the member's own cUSD into cUSD+ is not a deposit (Comprar
payouts showed twice on prod: the sale and an "Ahorro acreditado" push).
It is skipped only when every cUSD arrival since the previous wrap is
already in history; anything else keeps the mint's row as its record."""
import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from cusd_plus import tasks

VAULT = '0x' + '11' * 20
CUSD = '0x' + '22' * 20
ESCROW = '0x' + 'e5' * 20
HOLDER = '0x' + 'a1' * 20
ZERO = '0x' + '0' * 40
PREVIOUS = '0x' + '01' * 32


def _topic(address):
    return '0x' + address[2:].rjust(64, '0')


def _transfer(sender, tx_hash, block=150):
    return {'topics': [tasks.TRANSFER_TOPIC, _topic(sender), _topic(HOLDER)], 'data': hex(2 * 10 ** 18),
            'transactionHash': tx_hash, 'logIndex': '0x1', 'blockNumber': hex(block)}


def _out(receiver, tx_hash, usd):
    return {'topics': [tasks.TRANSFER_TOPIC, _topic(HOLDER), _topic(receiver)], 'data': hex(usd * 10 ** 18),
            'transactionHash': tx_hash, 'logIndex': '0x2', 'blockNumber': hex(150)}


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, CUSD_VAULT_ADDRESS=CUSD, MARKETPLACE_ESCROW_ADDRESS=ESCROW)
class WrapMintScanTests(TestCase):
    def setUp(self):
        from users.models import Account, User

        self.user = User.objects.create(username='wrapper', firebase_uid='wrapper')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                              bsc_address=HOLDER)
        self.arrivals = []
        self.departures = []

    def _batch(self, tx_hash, holder=HOLDER, ago=0):
        from blockchain.models import SponsoredBatch

        batch = SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=holder, kind='wrap_cusd', calls_json='[]', num_calls=1,
            gas_limit=1, max_fee_wei=1, tx_hash=tx_hash, status='confirmed',
            client_request_id=str(uuid.uuid4()))
        SponsoredBatch.objects.filter(pk=batch.pk).update(created_at=timezone.now() - timedelta(hours=ago))
        return batch

    def _scan(self, tx):
        def logs(from_block, to_block, topics, address=None):
            if address == VAULT:
                return [_transfer(ZERO, tx, block=200)]
            self.assertEqual((address, from_block, to_block), (CUSD, 101, 200))
            if topics[1] is None:
                return list(self.arrivals)
            # The wrap itself pulls the cUSD it converts ($2).
            return [_out(VAULT, tx, 2)] + list(self.departures)

        with mock.patch.object(tasks, '_get_logs_chunked', side_effect=logs), \
                mock.patch.object(tasks, '_rpc', return_value={'status': '0x1', 'blockNumber': hex(100)}), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=10 ** 18), \
                mock.patch('cusd_plus.vault.invalidate_position'), \
                mock.patch('notifications.fcm_service.send_push_notification'):
            tasks._scan_cusd_plus_arrivals({HOLDER: self.account.id}, 1, 2, 1)

    def _recorded(self, tx):
        from send.models import SendTransaction
        return SendTransaction.all_objects.filter(transaction_hash=tx).exists()

    def test_wrap_of_an_escrow_payout_writes_no_deposit(self):
        from notifications.models import Notification

        tx = '0x' + 'fe' * 32
        self._batch(PREVIOUS, ago=5)
        self._batch('0x' + tx[2:].upper())
        self.arrivals = [_transfer(ESCROW, '0x' + 'c1' * 32)]
        self._scan(tx)
        self.assertFalse(self._recorded(tx))
        self.assertFalse(Notification.objects.filter(data__tx_hash=tx).exists())

    def test_an_unrecorded_arrival_keeps_the_record(self):
        tx = '0x' + 'ab' * 32
        self._batch(PREVIOUS, ago=5)
        self._batch(tx)
        # A recorded payout and a stranger's plain cUSD transfer: the second
        # has no row of its own, so the mint stays its record.
        self.arrivals = [_transfer(ESCROW, '0x' + 'c1' * 32), _transfer('0x' + 'c3' * 20, '0x' + 'c2' * 32)]
        self._scan(tx)
        self.assertTrue(self._recorded(tx))

    def test_first_wrap_keeps_the_record(self):
        tx = '0x' + 'cd' * 32
        self._batch(tx)
        self._scan(tx)
        self.assertTrue(self._recorded(tx))

    def test_someone_elses_wrap_is_not_ours(self):
        tx = '0x' + 'ef' * 32
        self._batch(PREVIOUS, ago=5)
        self._batch(tx, holder='0x' + 'b2' * 20)
        self._scan(tx)
        self.assertTrue(self._recorded(tx))

    def test_a_wrap_larger_than_recorded_arrivals_keeps_the_record(self):
        # The previous wrap left older cUSD behind: the $2 payout was spent,
        # so the $2 wrapped now is that older money and keeps its record.
        tx = '0x' + 'aa' * 32
        self._batch(PREVIOUS, ago=5)
        self._batch(tx)
        self.arrivals = [_transfer(ESCROW, '0x' + 'c1' * 32)]
        self.departures = [_out('0x' + 'c3' * 20, '0x' + 'c4' * 32, 2)]
        self._scan(tx)
        self.assertTrue(self._recorded(tx))
