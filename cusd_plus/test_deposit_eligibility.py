"""A chain-observed deposit is a receipt; a conversion row is a completed fact.

Before 2026-08-01 the deposit watcher opened a `to_savings` row at
DEST_ARRIVED for every arrival, then the relay decided whether the mint was
allowed. The two disagreed: the watcher runs in Celery and can only see the
holder's phone country, while the real gate also checks the request's IP
country. A phone-eligible holder connecting from a blocked country therefore
got a row the relay refused forever — "pendiente" with no way out.

The row is now written by the relay AFTER a mint it allowed, so its existence
means "this happened" rather than "this is promised".
"""
from types import SimpleNamespace
from unittest import mock
from decimal import Decimal
from django.test import SimpleTestCase
from cusd_plus import tasks


def _account(country, kind='personal'):
    return SimpleNamespace(
        id=1, account_type=kind, display_name='X',
        user=SimpleNamespace(phone_country=country, phone_number='1'),
        business=None)


class DepositOpensNoConversionTests(SimpleTestCase):
    """No arrival opens a conversion — not even an eligible holder's."""

    def _run(self, account):
        created = []
        with mock.patch('users.models.Account.objects') as accts, \
             mock.patch('conversion.models.Conversion.objects') as convs, \
             mock.patch('cusd_plus.tasks._record_deposit_receipt') as receipt:
            accts.filter.return_value.select_related.return_value.first.return_value = account
            convs.filter.return_value.exists.return_value = False
            convs.create.side_effect = lambda **kw: created.append(kw) or SimpleNamespace(
                internal_id='c1', **kw)
            tasks._record_inbound_deposit(
                account_id=1, to_addr='0xabc', amount_usd=Decimal('1.00'),
                tx_ref='0xhash:0', tx_hash='0xhash',
                source='external_deposit', now=None, from_addr='0xdef')
        return created, receipt.call_args

    def test_eligible_holder_gets_no_conversion(self):
        created, receipt = self._run(_account('VE'))
        self.assertEqual(created, [], 'the relay opens the row, not the watcher')
        self.assertIsNone(receipt.kwargs['conv'])

    def test_ineligible_holder_gets_no_conversion(self):
        created, receipt = self._run(_account('US'))
        self.assertEqual(created, [])
        self.assertIsNone(receipt.kwargs['conv'])

    def test_business_account_gets_no_conversion(self):
        # Used to keep one, which stranded a blocked sole owner.
        created, _ = self._run(_account('US', kind='business'))
        self.assertEqual(created, [])

    def test_receipt_is_always_recorded(self):
        _, receipt = self._run(_account('US'))
        self.assertEqual(receipt.kwargs['to_addr'], '0xabc')
        self.assertEqual(receipt.kwargs['amount_usd'], Decimal('1.00'))


class RecordSavingsMintTests(SimpleTestCase):
    """The row the relay writes once a mint is allowed AND broadcast."""

    def _record(self, tx_hash='0xmint', exists=False):
        created = []
        with mock.patch('conversion.models.Conversion.objects') as convs:
            convs.filter.return_value.exists.return_value = exists
            convs.create.side_effect = lambda **kw: created.append(kw) or SimpleNamespace(
                internal_id='c9', **kw)
            out = tasks.record_savings_mint(
                user=SimpleNamespace(id=1), business=None, actor_type='user',
                display_name='X', amount_wei=2 * 10 ** 18, tx_hash=tx_hash,
                bsc_address='0xabc')
        return created, out

    def test_writes_a_completed_row_from_the_decoded_amount(self):
        created, out = self._record()
        self.assertEqual(len(created), 1)
        row = created[0]
        self.assertEqual(row['conversion_type'], 'to_savings')
        self.assertEqual(row['status'], 'COMPLETED')
        self.assertEqual(row['from_amount'], Decimal('2.000000'))
        self.assertEqual(row['to_transaction_hash'], '0xmint')
        self.assertIsNotNone(out)

    def test_is_idempotent_on_the_mint_hash(self):
        created, out = self._record(exists=True)
        self.assertEqual(created, [])
        self.assertIsNone(out)

    def test_history_failure_never_breaks_the_relay(self):
        with mock.patch('conversion.models.Conversion.objects') as convs:
            convs.filter.return_value.exists.return_value = False
            convs.create.side_effect = RuntimeError('db down')
            self.assertIsNone(tasks.record_savings_mint(
                user=SimpleNamespace(id=1), business=None, actor_type='user',
                display_name='X', amount_wei=10 ** 18, tx_hash='0xz',
                bsc_address='0xabc'))


class DepositReceiptTests(SimpleTestCase):
    """The receipt mirror, which is the ONLY record a deposit now gets."""

    def _run(self, existing_row):
        made = []
        notified = []
        with mock.patch('send.models.SendTransaction.all_objects') as sends, \
             mock.patch('notifications.utils.create_notification') as notify:
            sends.filter.return_value.exists.return_value = existing_row
            sends.create.side_effect = lambda **kw: made.append(kw) or SimpleNamespace(
                internal_id='r1')
            notify.side_effect = lambda **kw: notified.append(kw)
            tasks._record_deposit_receipt(
                account=_account('US'), is_business=False, to_addr='0xabc',
                from_addr='0xdef', amount_usd=Decimal('1.00'), tx_ref='0xhash:0',
                tx_hash='0xhash', source='external_deposit', conv=None)
        return made, notified

    def test_internal_send_row_suppresses_duplicate(self):
        # transaction_hash is UNIQUE — creating would raise IntegrityError, and
        # the send flow already notified the recipient.
        made, notified = self._run(existing_row=True)
        self.assertEqual(made, [])
        self.assertEqual(notified, [], 'no duplicate deposit notification')

    def test_external_deposit_records_and_notifies_once(self):
        made, notified = self._run(existing_row=False)
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]['token_type'], 'USDT')
        self.assertEqual(len(notified), 1)
        # ineligible copy: no promise that it joins savings
        self.assertIn('Confío Dollar', notified[0]['message'])
        self.assertFalse(notified[0]['data']['pending_auto_mint'])
