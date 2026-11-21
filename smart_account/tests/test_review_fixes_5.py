"""Review round 5: a closed-market stock slot waits for the next open session
(spec 7.5), Confío Face from a smart context, and cancelling a rule under an
identity hold."""
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import graphene
from django.test import override_settings
from django.utils import timezone
from graphql import GraphQLError

from cusd_plus import sponsor_7702
from smart_account import abi, automation, context, quotes, relay_policy, services
from smart_account.models import SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun

from .base import VAULT, SmartAccountTestCase, WAD
from .test_tasks import RelayHarness

STOCK = '0x' + '73' * 20


class _StockRuleMixin:
    def make_rule(self, slot, frequency='weekly'):
        self.slot = slot
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=4, state='onchain', kind='buy', token_in=VAULT,
            token_out=STOCK, amount=Decimal('25.00'), frequency=frequency,
            next_run_at=slot, scheduled_for=slot, active=True)
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 0
        self.chain.rules[(self.address, 4)] = {
            'kind': 'buy', 'frequency': frequency, 'active': True, 'amount_usd_wei': 25 * WAD,
            'next_run_at': int(slot.timestamp())}
        self.fund(VAULT, self.address, 500 * WAD)

    def tick(self, *, market_open: bool):
        quote = ({'call': {'to': '0x' + '51' * 20, 'value': '0', 'data': '0x1234'}, 'min_out': 1}
                 if market_open else None)
        with ExitStack() as stack:
            for p in (mock.patch('cusd_plus.crypto_catalog.by_address', return_value=None),
                      mock.patch('smart_account.assets.stock_by_address', return_value=('AAPLon', {})),
                      override_settings(CUSD_PLUS_STOCK_TRADING_ENABLED=True),
                      mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True),
                      mock.patch('smart_account.quotes.stock_buy_notional', return_value=Decimal('24.50')),
                      mock.patch('smart_account.quotes.stock_buy_call', return_value=quote,
                                 side_effect=None if market_open
                                 else quotes.QuoteUnavailable('market_closed', retry_later=True))):
                stack.enter_context(p)
            return automation.run_rules()


class ClosedMarketSlotTests(_StockRuleMixin, RelayHarness):
    def setUp(self):
        super().setUp()
        SmartAccount = type(self.account)
        SmartAccount.objects.filter(pk=self.account.pk).update(paid_until=timezone.now() + timedelta(days=20))
        self.account.refresh_from_db()
        told = mock.patch('smart_account.notifications.rule_run')
        self.told = told.start()
        self.addCleanup(told.stop)

    def test_saturday_slot_still_pending_on_monday_is_sent_once(self):
        # Two days old: past the 24h cutoff that used to give it up.
        self.make_rule(timezone.now().replace(microsecond=0) - timedelta(days=2))
        for _ in range(3):
            self.assertEqual(self.tick(market_open=False)['waiting'], 1)
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual(run.status, 'pending')
        self.assertTrue(run.error.startswith('market_closed'))
        self.assertEqual(self.told.call_count, 0)          # waiting is not told
        self.assertEqual(self.tick(market_open=True)['sent'], 1)   # Monday's open session
        self.assertEqual(self.tick(market_open=True)['sent'], 0)   # never twice
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(abi.decode_call(self.signed[0]['data'])[0], 'executeRule')
        run.refresh_from_db()
        self.assertEqual((run.status, run.scheduled_for), ('sent', self.slot))
        self.assertEqual(SmartAccountRelayTx.objects.count(), 1)
        self.assertEqual(self.told.call_count, 0)

    def test_weekly_slot_that_never_reopens_is_skipped_once_and_the_next_slot_runs(self):
        self.make_rule(timezone.now().replace(microsecond=0) - timedelta(days=6))
        self.assertEqual(self.tick(market_open=False)['waiting'], 1)
        # Two days pass without an open session: the next slot is now due.
        old = self.slot - timedelta(days=2)
        SmartAccountRuleRun.objects.update(scheduled_for=old)
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(scheduled_for=old, next_run_at=old)
        self.chain.rules[(self.address, 4)]['next_run_at'] = int(old.timestamp())

        out = self.tick(market_open=False)
        self.assertEqual((out['skipped'], out['waiting'], out['sent']), (1, 0, 0))
        stale = SmartAccountRuleRun.objects.get(scheduled_for=old)
        self.assertEqual((stale.status, stale.message), ('skipped', 'El mercado estaba cerrado.'))
        self.assertEqual(self.told.call_count, 1)
        self.rule.refresh_from_db()
        current = automation.next_slot('weekly', old)
        self.assertEqual(self.rule.scheduled_for, current)      # the current slot, not lost
        self.assertLessEqual(current, timezone.now())

        # Later ticks: the old slot is never touched again nor told again;
        # the current slot waits for its own open session.
        for _ in range(2):
            out = self.tick(market_open=False)
            self.assertEqual((out['skipped'], out['waiting']), (0, 1))
        self.assertEqual(SmartAccountRuleRun.objects.count(), 2)
        self.assertEqual(SmartAccountRuleRun.objects.get(scheduled_for=current).status, 'pending')
        self.assertEqual(self.told.call_count, 1)
        self.assertEqual(self.tick(market_open=True)['sent'], 1)
        self.assertEqual(SmartAccountRuleRun.objects.get(scheduled_for=current).status, 'sent')
        stale.refresh_from_db()
        self.assertEqual(stale.status, 'skipped')
        self.assertEqual(len(self.sent), 1)

    def test_non_market_skips_keep_the_24h_cutoff(self):
        self.make_rule(timezone.now().replace(microsecond=0) - timedelta(days=2))
        self.fund(VAULT, self.address, WAD)
        self.assertEqual(self.tick(market_open=True)['skipped'], 1)
        self.rule.refresh_from_db()
        self.assertGreater(self.rule.scheduled_for, timezone.now())   # given up, moved on
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'skipped')

    def test_buy_rule_does_not_run_under_an_identity_hold(self):
        self.make_rule(timezone.now().replace(microsecond=0) - timedelta(minutes=3))
        self.holds[self.owner.pk] = 'En revisión'
        self.assertEqual(automation.buy_rule_refusal(self.rule).code, 'identity_hold')
        self.assertEqual(self.tick(market_open=True)['skipped'], 1)
        self.assertEqual((self.signed, self.sent), ([], []))
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual((run.status, run.error), ('skipped', 'identity_hold'))
        self.rule.refresh_from_db()
        self.assertTrue(self.rule.active)        # kept; retried when the hold ends
        del self.holds[self.owner.pk]
        self.assertEqual(self.tick(market_open=True)['sent'], 1)   # the same slot, once the hold ends


def _info(field_name, ctx):
    return SimpleNamespace(
        path=SimpleNamespace(prev=None), operation=SimpleNamespace(operation=SimpleNamespace(value='mutation')),
        field_name=field_name, context=ctx)


class SmartContextFaceTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.gate = context.SmartContextGateMiddleware()
        self.smart = self.info(self.owner, 'smart', 0).context

    def test_face_mutations_pass_the_gate_and_act_on_the_jwt_user_only(self):
        from security.schema import CompleteFaceCheck, StartFaceCheck
        with mock.patch('security.face_step_up.start_face_check',
                        return_value={'session_id': 's-1'}) as start, \
                mock.patch('security.face_step_up.complete_face_check', return_value=True) as complete:
            started = self.gate.resolve(lambda root, info, **a: StartFaceCheck().mutate(info, **a),
                                        None, _info('startFaceCheck', self.smart), purpose='withdrawal')
            completed = self.gate.resolve(lambda root, info, **a: CompleteFaceCheck().mutate(info, **a),
                                          None, _info('completeFaceCheck', self.smart), session_id='s-1')
        self.assertEqual((started.success, started.session_id), (True, 's-1'))
        self.assertEqual((completed.success, completed.passed), (True, True))
        self.assertIs(start.call_args.args[0], self.owner)
        self.assertIs(complete.call_args.args[0], self.owner)

    def test_only_the_face_mutations_were_added(self):
        for name in ('verifyAppCheck', 'requestIntegrityNonce', 'checkKycStatus'):
            with self.assertRaises(GraphQLError, msg=name):
                self.gate.resolve(lambda *a, **k: 'ran', None, _info(name, self.smart))
        face = {'startFaceCheck', 'completeFaceCheck'}
        self.assertLessEqual(face, context.ALLOWED_MUTATIONS)
        from security.schema import SecurityMutation
        security_fields = set(graphene.Schema(query=_SecurityQ, mutation=SecurityMutation)
                              .graphql_schema.mutation_type.fields)
        self.assertEqual(security_fields & context.ALLOWED_MUTATIONS, face)


class _SecurityQ(graphene.ObjectType):
    ok = graphene.Boolean()


class CancelRuleUnderHoldTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        slot = timezone.now()
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=7, state='onchain', kind='buy', token_in=VAULT,
            token_out=STOCK, amount=Decimal('25.00'), frequency='weekly',
            next_run_at=slot, scheduled_for=slot, active=True)

    def _past_identity_check(self, kind):
        """True when send_sponsored_batch got past its identity-hold check
        (the KMS signer lookup that follows it is stopped here)."""
        class Reached(Exception):
            pass
        with mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings', side_effect=Reached):
            try:
                sponsor_7702.send_sponsored_batch(self.owner, self.owner.wallet, [], 0, 0, '0x', None, kind)
            except Reached:
                return True
            except sponsor_7702.PolicyError:
                return False
        raise AssertionError('neither refused nor reached the signer')

    def test_cancelling_a_rule_is_its_own_exempt_kind(self):
        self.holds[self.owner.pk] = 'En revisión'
        batch = services.prepare_cancel_rule(self.viewer(self.owner), self.rule.internal_id)
        self.assertEqual(batch.kind, 'smart_rule_cancel')
        action = relay_policy.validate_batch(batch.calls, self.owner, self.owner.wallet, batch.request_id)
        self.assertEqual(action.kind, 'smart_rule_cancel')
        self.assertIn('smart_rule_cancel', abi.BATCH_KINDS_NOT_OUTGOING)
        self.assertEqual(abi.classify(batch.calls), 'smart_rule_cancel')
        self.assertTrue(self._past_identity_check('smart_rule_cancel'))
        self.assertFalse(self._past_identity_check('smart_rule'))     # create/update stay held

    def test_the_cancel_kind_allows_cancel_rule_alone(self):
        self.assertEqual(abi.BATCH_KIND_FUNCTIONS['smart_rule_cancel'], {'cancelRule'})
        self.assertNotIn('cancelRule', abi.BATCH_KIND_FUNCTIONS['smart_rule'])
        cancel = abi.call(self.account.contract_address, abi.encode_call('cancelRule', 7))
        from smart_account.models import SmartAccountPreparedAction
        calls = [abi.call(self.account.contract_address, abi.encode_call('withdrawAll', [VAULT])), cancel]
        SmartAccountPreparedAction.objects.create(
            request_id='sa-' + 'c' * 32, user=self.owner, signer_address=self.owner.wallet,
            target_address=self.account.contract_address, kind='smart_rule_cancel', calls=calls,
            calls_hash=services.calls_hash(calls), expires_at=timezone.now() + timedelta(minutes=5))
        with self.assertRaises(sponsor_7702.PolicyError) as raised:
            relay_policy.validate_batch(calls, self.owner, self.owner.wallet, 'sa-' + 'c' * 32)
        self.assertEqual(raised.exception.code, 'selector_not_allowed')
