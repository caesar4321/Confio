"""A rule create is never signed twice: the prepare refuses an identical
create that is active or still confirming (24 h), the submit refuses the
second of two identical creates prepared before either was signed, and a
re-opened Confío IA+ proposal leaves out the steps already signed."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from smart_account import abi, relay_policy, services
from smart_account.models import SmartAccountPreparedAction, SmartAccountRule

from .base import VAULT, WAD, SmartAccountTestCase

TOKEN = '0x' + '6a' * 20


class _BuyRules(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.fund(VAULT, self.account.contract_address, 500 * WAD)
        from cusd_plus import stock_fees
        for p in (mock.patch('smart_account.assets.resolve_asset_key',
                             return_value=('stock', 'AAPLon', TOKEN, 18)),
                  mock.patch('smart_account.services._stock_buy_allowed', return_value=True),
                  mock.patch('cusd_plus.complex_products.factor_for_symbol', return_value=None),
                  mock.patch('security.geo.review_cap_exceeded', return_value=False),
                  mock.patch('smart_account.quotes._stock_fee', return_value=(30, stock_fees.MODE_PERIMETER)),
                  mock.patch('cusd_plus.stock_fees.exit_buffer_bps', return_value=5)):
            p.start()
            self.addCleanup(p.stop)

    def prepare(self, amount='30.00', frequency='monthly', rule_id=None, proposal=None):
        return services.prepare_buy_rule(self.viewer(self.owner), rule_id, 'stock:AAPLon', amount, frequency,
                                         proposal=proposal)

    def sign(self, batch, status='sent'):
        from blockchain.models import SponsoredBatch
        sponsored = SponsoredBatch.objects.create(
            user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_rule', num_calls=1,
            calls_json='[]', tx_hash='0x' + batch.request_id[3:].ljust(64, '0')[:64], gas_limit=1,
            max_fee_wei='1', status=status, client_request_id=batch.request_id + '_a0')
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        relay_policy.consume(action, sponsored)
        return sponsored

    def assertDuplicate(self, pending=False, **kw):
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare(**kw)
        if pending:
            self.assertEqual(raised.exception.code, 'rule_duplicate_pending')
            self.assertEqual(raised.exception.message, 'Esta regla se está confirmando. No la repitas.')
        else:
            self.assertEqual(raised.exception.code, 'rule_duplicate')
            self.assertEqual(raised.exception.message, 'Ya tienes esta regla. No la repitas.')


class DuplicateCreateTests(_BuyRules):
    def test_an_identical_create_is_refused_while_the_first_is_confirming(self):
        self.prepare()   # prepared, never signed: nothing to protect yet
        self.sign(self.prepare())
        drafts = SmartAccountRule.objects.count()
        self.assertDuplicate(pending=True)
        self.assertEqual(SmartAccountRule.objects.count(), drafts)   # no draft written
        # Another amount, or another frequency, is another rule.
        self.prepare(amount='31.00')
        self.prepare(frequency='weekly')

    def test_a_create_whose_batch_did_nothing_may_be_signed_again(self):
        sponsored = self.sign(self.prepare())
        type(sponsored).objects.filter(pk=sponsored.pk).update(status='dropped')
        self.prepare()

    def test_an_identical_active_rule_made_today_is_refused_and_updates_are_not(self):
        rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=3, state='onchain', kind='buy', token_in=VAULT,
            token_out=TOKEN.upper().replace('0X', '0x'), asset_key='stock:AAPLon', amount=Decimal('30.00'),
            frequency='monthly', active=True, next_run_at=timezone.now() + timedelta(days=20))
        self.chain.rules[(self.account.contract_address.lower(), 3)] = {
            'kind': 'buy', 'frequency': 'monthly', 'active': True, 'token_in': VAULT, 'token_out': TOKEN,
            'payee': abi.ZERO_ADDRESS, 'payout_ref': '0x' + '00' * 32, 'amount_usd_wei': 30 * WAD,
            'next_run_at': int(rule.next_run_at.timestamp())}
        self.assertDuplicate()
        self.prepare(amount='45.00')
        # Editing that very rule (same terms) is an update, never refused.
        batch = self.prepare(rule_id=str(rule.internal_id))
        self.assertEqual(abi.decode_call(batch.calls[0]['data'])[0], 'updateRule')
        # A rule made more than a day ago: the owner may want a second one.
        SmartAccountRule.objects.filter(pk=rule.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.prepare()
        # A stopped one is no duplicate either.
        SmartAccountRule.objects.filter(pk=rule.pk).update(created_at=timezone.now(), active=False,
                                                           state='cancelled')
        self.prepare()

    def test_the_submit_refuses_the_second_of_two_creates_prepared_before_signing(self):
        first, second = self.prepare(), self.prepare()
        self.sign(first)
        action = SmartAccountPreparedAction.objects.get(request_id=second.request_id)
        self.assertEqual(relay_policy.duplicate_create_refusal(action), 'rule_duplicate_pending')
        with self.assertRaises(Exception) as raised:
            relay_policy.validate_batch(second.calls, self.owner, self.owner.wallet,
                                        request_id=second.request_id + '_a0')
        self.assertEqual(str(raised.exception), 'rule_duplicate_pending')
        # The first one's exact replay is untouched by the check.
        self.assertFalse(relay_policy.duplicate_create_refusal(
            SmartAccountPreparedAction.objects.get(request_id=first.request_id)))

    def test_the_submit_names_an_active_duplicate_apart_from_a_confirming_one(self):
        batch = self.prepare()
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        self.assertEqual(relay_policy.duplicate_create_refusal(action), '')
        SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=4, state='onchain', kind='buy', token_in=VAULT,
            token_out=TOKEN, asset_key='stock:AAPLon', amount=Decimal('30.00'), frequency='monthly',
            active=True, next_run_at=timezone.now() + timedelta(days=20))
        self.assertEqual(relay_policy.duplicate_create_refusal(action), 'rule_duplicate')
        with self.assertRaises(Exception) as raised:
            relay_policy.validate_batch(batch.calls, self.owner, self.owner.wallet,
                                        request_id=batch.request_id + '_a0')
        self.assertEqual(str(raised.exception), 'rule_duplicate')

    def test_two_creates_that_both_passed_validation_consume_one_at_a_time(self):
        # Concurrent submits: both validate before either is consumed. The
        # sponsor nonce lock serializes the consumes (each commits before the
        # lock is released); consume re-checks on a fresh read, so the second
        # is refused before broadcast. No account row lock is taken: the
        # reconciler may hold that row through slow RPC.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from smart_account.models import SmartAccount
        first, second = self.prepare(), self.prepare()
        for batch in (first, second):
            relay_policy.validate_batch(batch.calls, self.owner, self.owner.wallet,
                                        request_id=batch.request_id + '_a0')
        with CaptureQueriesContext(connection) as queries:
            self.sign(first)
        table = SmartAccount._meta.db_table
        self.assertFalse(any('FOR UPDATE' in q['sql'] and table in q['sql'] for q in queries.captured_queries),
                         'consume must not lock the account row')
        with self.assertRaises(Exception) as raised:
            self.sign(second)
        self.assertEqual(str(raised.exception), 'rule_duplicate_pending')
        self.assertFalse(SmartAccountPreparedAction.objects.get(request_id=second.request_id).consumed)
        self.assertTrue(SmartAccountPreparedAction.objects.get(request_id=first.request_id).consumed)

class ProposalProgressTests(_BuyRules):
    def setUp(self):
        super().setUp()
        from inbox.models import SupportMessage
        from inbox.schema import get_or_create_support_conversation
        from smart_account import context
        conv = get_or_create_support_conversation(self.owner, context.personal_account(self.owner), None)
        self.message = SupportMessage.objects.create(
            conversation=conv, sender_type='AGENT', message_type='TEXT', body='x',
            metadata={'ai': True, 'rule_proposal': {
                'created_at': (timezone.now() - timedelta(minutes=5)).isoformat(), 'steps': [
                    {'action': 'create', 'kind': 'buy', 'asset_key': 'stock:AAPLon', 'amount_usd': '30.00',
                     'frequency': 'monthly', 'sentence': 'uno'},
                    {'action': 'create', 'kind': 'buy', 'asset_key': 'stock:AAPLon', 'amount_usd': '40.00',
                     'frequency': 'weekly', 'sentence': 'dos'}]}})

    def resolve(self):
        from assistant.schema import Query
        return Query.resolve_assistant_rule_proposal.__wrapped__(None, self.info(self.owner), str(self.message.pk))

    def test_reopening_starts_at_the_first_step_not_signed(self):
        fresh = self.resolve()
        self.assertEqual([s.step_index for s in fresh.steps], [0, 1])
        self.assertFalse(fresh.done)
        # Prepared but never signed: still offered.
        self.prepare()
        self.assertEqual([s.step_index for s in self.resolve().steps], [0, 1])
        # Signed by a build that does not send the step: matched by what it does.
        self.sign(self.prepare())
        reopened = self.resolve()
        self.assertEqual([(s.step_index, s.amount_usd) for s in reopened.steps], [(1, '40.00')])
        self.assertEqual(reopened.signed_steps, 1)
        self.assertFalse(reopened.done)
        self.assertIsNone(reopened.message)

    def test_every_step_signed_is_the_done_state(self):
        for index, (amount, frequency) in enumerate((('30.00', 'monthly'), ('40.00', 'weekly'))):
            batch = self.prepare(amount=amount, frequency=frequency, proposal=(str(self.message.pk), index))
            action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
            self.assertEqual(action.payload['proposal'], {'message_id': str(self.message.pk), 'step': index})
            self.sign(batch, status='confirmed' if index == 0 else 'sent')
        done = self.resolve()
        self.assertEqual(done.steps, [])
        self.assertTrue(done.done)
        self.assertEqual(done.signed_steps, 2)
        self.assertTrue(done.message.startswith('Ya firmaste este plan.'))

    def test_a_tag_for_another_proposal_does_not_consume_this_one(self):
        self.sign(self.prepare(proposal=(str(self.message.pk + 1000), 0)))
        self.assertEqual([s.step_index for s in self.resolve().steps], [0, 1])

    def test_garbage_tags_are_dropped(self):
        for proposal in (('abc', 0), (str(self.message.pk), 99), (str(self.message.pk), -1), ('x',)):
            self.assertEqual(services._proposal_payload(proposal), {})
