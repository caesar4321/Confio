from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from blockchain.models import SponsoredBatch
from conversion.models import Conversion
from cusd_plus.management.commands.backfill_prefee_savings_conversions import TRANSFER, crossing
from users.models import Account

VAULT = '0x' + 'a' * 40
USDT = '0x' + 'b' * 40
WALLET = '0x' + 'c' * 40
RECIPIENT = '0x' + 'd' * 40
ZERO = '0x' + '0' * 40
HASH = '0x' + '1' * 64


def _log(token, frm, to, amount, index):
    word = lambda a: '0x' + '0' * 24 + a[2:]
    return {'address': token, 'topics': [TRANSFER, word(frm), word(to)],
            'data': hex(int(Decimal(amount) * 10 ** 18)), 'logIndex': hex(index)}


def _receipt(*logs, status='0x1'):
    return {'status': status, 'logs': list(logs)}


class CrossingTests(TestCase):
    def _batch(self, kind='send_redeem'):
        return SimpleNamespace(kind=kind, user_bsc_address=WALLET)

    def test_exit_uses_usdt_leaving_the_vault(self):
        receipt = _receipt(_log(VAULT, WALLET, ZERO, '9.95', 3), _log(USDT, VAULT, RECIPIENT, '10', 4))
        self.assertEqual(crossing(self._batch(), receipt, vault=VAULT, usdt=USDT), ('exit', Decimal('10'), 3))

    def test_entry_uses_usdt_entering_the_vault(self):
        receipt = _receipt(_log(USDT, WALLET, VAULT, '2.66', 1), _log(VAULT, ZERO, WALLET, '2.65', 2))
        self.assertEqual(crossing(self._batch('subscribe'), receipt, vault=VAULT, usdt=USDT), ('entry', Decimal('2.66'), 2))

    def test_amount_far_from_shares_is_not_trusted(self):
        receipt = _receipt(_log(VAULT, WALLET, ZERO, '10', 3), _log(USDT, VAULT, RECIPIENT, '5', 4))
        self.assertEqual(crossing(self._batch(), receipt, vault=VAULT, usdt=USDT)[:2], (None, 'amount_unverified'))

    def test_fee_era_receipts_belong_to_the_live_reconciler(self):
        receipt = _receipt(_log(VAULT, WALLET, ZERO, '10', 3), _log(USDT, VAULT, RECIPIENT, '10', 4))
        with mock.patch('cusd_plus.tasks._cusd_fee_events', return_value=[{}]):
            self.assertEqual(crossing(self._batch(), receipt, vault=VAULT, usdt=USDT)[:2], (None, 'has_fee_event'))

    def test_failed_receipt_and_ambiguous_burns_are_skipped(self):
        self.assertEqual(crossing(self._batch(), _receipt(status='0x0'), vault=VAULT, usdt=USDT)[:2], (None, 'receipt_failed'))
        two = _receipt(_log(VAULT, WALLET, ZERO, '5', 1), _log(VAULT, WALLET, ZERO, '5', 2), _log(USDT, VAULT, RECIPIENT, '10', 3))
        self.assertEqual(crossing(self._batch(), two, vault=VAULT, usdt=USDT)[:2], (None, 'share_moves_2'))


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, CUSD_PLUS_USDT_BSC=USDT)
class BackfillCommandTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='prefee', password='x')
        Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address=WALLET)
        self.batch = SponsoredBatch.objects.create(
            user=user, user_bsc_address=WALLET, kind='send_redeem', num_calls=1, calls_json='[]',
            tx_hash=HASH, status='confirmed', gas_limit=1, max_fee_wei=1)
        self.receipt = _receipt(_log(VAULT, WALLET, ZERO, '19.9', 3), _log(USDT, VAULT, RECIPIENT, '20', 4))

    def _run(self, *args):
        with mock.patch('cusd_plus.tasks._rpc', return_value=self.receipt):
            call_command('backfill_prefee_savings_conversions', *args, stdout=StringIO())

    def test_dry_run_writes_nothing_and_apply_is_idempotent(self):
        self._run()
        self.assertFalse(Conversion.objects.exists())
        self._run('--apply')
        self._run('--apply')
        row = Conversion.objects.get()
        self.assertEqual((row.conversion_type, row.perimeter_direction, row.status), ('from_savings', 'exit', 'COMPLETED'))
        self.assertEqual((row.to_amount, row.contract_event_index), (Decimal('20.000000'), 3))
        self.assertEqual(row.created_at, self.batch.created_at)

    def test_failed_row_on_a_confirmed_batch_is_reported_not_hidden(self):
        user = get_user_model().objects.get(username='prefee')
        Conversion.objects.create(
            actor_user=user, actor_type='user', conversion_type='from_savings',
            from_amount=Decimal('20'), to_amount=Decimal('20'), exchange_rate=Decimal('1'),
            fee_amount=Decimal('0'), status='FAILED', to_transaction_hash=HASH)
        out = StringIO()
        with mock.patch('cusd_plus.tasks._rpc', return_value=self.receipt):
            call_command('backfill_prefee_savings_conversions', '--apply', stdout=out)
        self.assertIn('row_failed', out.getvalue())
        self.assertEqual(Conversion.objects.count(), 1)
