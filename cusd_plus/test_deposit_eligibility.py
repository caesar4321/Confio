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
             mock.patch('cusd_plus.models.CusdPlusConversion.objects') as convs, \
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
        self.assertEqual(created[0]['direction'], 'to_savings')
        self.assertIsNotNone(receipt.kwargs['conv'])

    def test_business_account_keeps_conversion(self):
        created, _ = self._run(_account('US', kind='business'))
        self.assertEqual(len(created), 1, 'business mint is gated on the requesting user')
