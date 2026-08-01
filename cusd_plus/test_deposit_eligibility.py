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


class DepositEligibilityTests(SimpleTestCase):
    def _run(self, account):
        created = []
        with mock.patch('users.models.Account.objects') as accts, \
             mock.patch('conversion.models.Conversion.objects') as convs, \
             mock.patch('cusd_plus.tasks._record_deposit_receipt') as receipt:
            accts.filter.return_value.select_related.return_value.first.return_value = account
            convs.filter.return_value.exists.return_value = False
            convs.create.side_effect = lambda **kw: created.append(kw) or SimpleNamespace(
                internal_id='c1', **kw)
            with mock.patch('cusd_plus.unified.sync_unified_from_cusd_plus_conversion'):
                tasks._record_inbound_deposit(
                    account_id=1, to_addr='0xabc', amount_usd=Decimal('1.00'),
                    tx_ref='0xhash:0', tx_hash='0xhash',
                    source='external_deposit', now=None, from_addr='0xdef')
        return created, receipt.call_args

    def test_us_holder_gets_no_conversion(self):
        created, receipt = self._run(_account('US'))
        self.assertEqual(created, [], 'US holder must not get a to_savings row')
        self.assertIsNone(receipt.kwargs['conv'], 'receipt still recorded, without a conversion')

    def test_eligible_holder_still_converts(self):
        created, receipt = self._run(_account('CO'))
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]['conversion_type'], 'to_savings')
        self.assertIsNotNone(receipt.kwargs['conv'])

    def test_business_account_keeps_conversion(self):
        created, _ = self._run(_account('US', kind='business'))
        self.assertEqual(len(created), 1, 'business mint is gated on the requesting user')


class DepositReceiptTests(SimpleTestCase):
    """The receipt mirror, which is the ONLY record for an ineligible holder."""

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
