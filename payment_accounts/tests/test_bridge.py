from datetime import timedelta
from unittest import mock
import uuid

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from payment_accounts.allbridge_next import NextError
from payment_accounts.bridge import quote_provider_funding
from payment_accounts.models import AccountActivation, FinancialAccount, FundingInstruction, MoneyFlow, PaymentBridgeQuote, ProviderProfile
from payment_accounts.services import PaymentAccountError
from security.models import IdentityVerification
from users.models import User, Account
from .test_allbridge_next import SOURCE, DESTINATION, route as raw_route


def route(*args, **kwargs):
    return dict(raw_route(*args, **kwargs), messenger='near-intents')


@override_settings(PAYMENT_BRIDGE_QUOTES_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True)
class BridgeQuoteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bridge-user', firebase_uid='bridge-user')
        self.owner = Account.objects.create(user=self.user, account_type='personal', bsc_address=SOURCE)
        # Existing paid local account enables the shared crypto settlement account.
        AccountActivation.objects.create(confio_account=self.owner, country='PER', asset='PEN', status='legacy')
        identity = IdentityVerification.objects.create(
            user=self.user, status='verified', verified_date_of_birth='1990-01-01',
        )
        profile = ProviderProfile.objects.create(
            confio_account=self.owner, provider='infinia', owner_type='individual',
            status='active', identity_verification=identity,
        )
        account = FinancialAccount.objects.create(
            provider_profile=profile, country='XXX', asset='USDC_POL',
            ownership_structure='provider_named', status='active',
        )
        self.instruction = FundingInstruction.objects.create(
            financial_account=account, kind='crypto_address', status='active', display_value=DESTINATION,
        )
        self.config = self.settings(PAYMENT_BRIDGE_VERIFIED_INSTRUCTIONS={
            str(self.instruction.internal_id): {'address': DESTINATION, 'token_id': 'POL:USDC'},
        })
        self.config.enable()
        self.addCleanup(self.config.disable)
        self.eligibility = mock.patch('payment_accounts.bridge.enforce_and_record').start()
        self.addCleanup(mock.patch.stopall)
        self.net_funding = mock.patch('payment_accounts.bridge.net_funding_units',
                                      side_effect=lambda owner, units: str(units)).start()
        self.client = mock.Mock()
        self.client.quote.return_value = [route()]
        self.request_id = uuid.uuid4()

    def quote(self, **overrides):
        args = dict(confio_account=self.owner, funding_instruction_id=self.instruction.internal_id,
                    amount='10', request_id=self.request_id, client=self.client)
        args.update(overrides)
        return quote_provider_funding(**args)

    def test_durable_quote_is_not_money_submission(self):
        quoted = self.quote()
        self.assertEqual(quoted.destination_address, DESTINATION)
        self.assertEqual(quoted.source_address, SOURCE)
        self.assertEqual(quoted.money_flow.status, 'created')
        self.assertIsNone(quoted.money_flow.target_amount)
        self.assertFalse(quoted.money_flow.operations.exists())
        self.eligibility.assert_called_once()

    def test_retry_returns_same_quote_without_second_api_call(self):
        first = self.quote()
        self.assertEqual(self.quote().pk, first.pk)
        self.assertEqual(MoneyFlow.objects.count(), 1)
        self.client.quote.assert_called_once()

    def test_gross_spend_quotes_only_net_and_retry_does_not_reprice_the_fee(self):
        self.net_funding.side_effect = None
        self.net_funding.return_value = '49550000000000000000'
        first = self.quote(amount='50')
        self.assertEqual(first.amount_units, '49550000000000000000')
        self.assertEqual(first.money_flow.source_amount, 50)
        self.assertEqual(first.money_flow.metadata['gross_spend_units'], '50000000000000000000')
        self.client.quote.assert_called_once_with('BSC:USDT', 'POL:USDC', '49550000000000000000')
        self.net_funding.side_effect = AssertionError('retry must not reprice the fee')
        self.assertEqual(self.quote(amount='50').pk, first.pk)

    def test_pre_inclusive_quote_retry_preserves_its_original_amount(self):
        first = self.quote(amount='50')
        first.money_flow.metadata.pop('gross_spend_units')
        first.money_flow.save(update_fields=['metadata'])
        self.net_funding.side_effect = AssertionError('legacy retry must not reprice')
        self.assertEqual(self.quote(amount='50').pk, first.pk)

    def test_unexecutable_routes_cannot_be_the_default(self):
        self.client.quote.return_value = [raw_route(), route()]
        q = self.quote()
        self.assertEqual([r['messenger'] for r in q.routes], ['near-intents'])

    def test_only_unexecutable_routes_leave_no_orphan_flow(self):
        self.client.quote.return_value = [raw_route()]
        with self.assertRaisesRegex(NextError, 'No executable'):
            self.quote()
        self.assertFalse(MoneyFlow.objects.exists())

    def test_reusing_id_for_different_amount_fails(self):
        self.quote()
        with self.assertRaisesRegex(PaymentAccountError, 'different bridge details'):
            self.quote(amount='11')

    def test_expired_quote_cannot_be_repriced_under_same_request(self):
        quoted = self.quote()
        PaymentBridgeQuote.objects.filter(pk=quoted.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaisesRegex(PaymentAccountError, 'expired'):
            self.quote()
        self.client.quote.assert_called_once()

    def test_other_account_cannot_use_instruction(self):
        other = Account.objects.create(user=self.user, account_type='personal', account_index=1)
        with self.assertRaisesRegex(PaymentAccountError, 'not found'):
            self.quote(confio_account=other)
        self.client.quote.assert_not_called()

    @override_settings(PAYMENT_BRIDGE_VERIFIED_INSTRUCTIONS={})
    def test_unconfirmed_provider_address_fails_closed(self):
        with self.assertRaisesRegex(PaymentAccountError, 'not verified'):
            self.quote()
        self.client.quote.assert_not_called()

    def test_address_rotation_requires_reverification(self):
        self.instruction.display_value = SOURCE
        self.instruction.save()
        with self.assertRaisesRegex(PaymentAccountError, 'changed'):
            self.quote()

    @override_settings(PAYMENT_BRIDGE_MAX_USDT='100')  # no cap by default; this is the emergency brake
    def test_braked_oversize_quote_does_not_call_next(self):
        with self.assertRaisesRegex(PaymentAccountError, 'limit'):
            self.quote(amount='101')
        self.client.quote.assert_not_called()

    def test_api_failure_leaves_no_orphan_flow(self):
        self.client.quote.side_effect = NextError('unavailable')
        with self.assertRaises(NextError):
            self.quote()
        self.assertFalse(MoneyFlow.objects.exists())

    def test_revocation_during_pricing_is_checked_again(self):
        def price(*args):
            FundingInstruction.objects.filter(pk=self.instruction.pk).update(status='closed')
            return [route()]
        self.client.quote.side_effect = price
        with self.assertRaisesRegex(PaymentAccountError, 'active reusable'):
            self.quote()
        self.assertFalse(MoneyFlow.objects.exists())

    def test_eligibility_denial_prevents_pricing(self):
        self.eligibility.side_effect = PaymentAccountError('Eligibility blocked')
        with self.assertRaisesRegex(PaymentAccountError, 'Eligibility blocked'):
            self.quote()
        self.client.quote.assert_not_called()

    @override_settings(PAYMENT_BRIDGE_QUOTES_ENABLED=False)
    def test_disabled_by_default(self):
        with self.assertRaisesRegex(PaymentAccountError, 'not enabled'):
            self.quote()
        self.client.quote.assert_not_called()


@override_settings(PAYMENT_BRIDGE_QUOTES_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True)
class ConcurrentBridgeQuoteTests(TransactionTestCase):
    setUp = BridgeQuoteTests.setUp
    quote = BridgeQuoteTests.quote

    def test_concurrent_retry_creates_one_flow_and_quote(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections

        barrier = Barrier(2)

        def price(*args):
            barrier.wait(timeout=10)
            return [route()]

        self.client.quote.side_effect = price

        def run():
            try:
                return self.quote(confio_account=Account.objects.get(pk=self.owner.pk)).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(MoneyFlow.objects.count(), 1)
        self.assertEqual(PaymentBridgeQuote.objects.count(), 1)
