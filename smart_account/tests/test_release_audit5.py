"""The fifth money-path audit: a passing cost or rate refusal, a Relay
request never bound, a replay refused for ever, a long rate limit, a held
owner, a refunded bank payment and a renamed payee.
Synthetic ids, keys, names and addresses only."""
import time
from datetime import timedelta
from unittest import mock

from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from payment_accounts.models import MoneyOperation
from ramps import ve_send
from ramps.models import RampTransaction
from smart_account.models import SmartAccountRule, SmartAccountRuleRun, SmartAccountStandingAuthorization

from . import test_money_path_audit as mpa
from .infinia_base import InfiniaPayoutCase
from .test_release_audit4 import PAYOUT, InfiniaBusyCase, PagoAsapBusyTests, VeCase

DAY, HOUR, MINUTE = timedelta(days=1), timedelta(hours=1), timedelta(minutes=1)


# ----------------------------------------------------------------- P2

class RunTimeLimitTests(InfiniaPayoutCase):
    """A cost or rate over the rule's limit at run time is today's, not the
    month's: the slot is asked again inside its 24 hours."""

    def limited(self, **signed):
        rule = self.make_rule()
        slot = SmartAccountRule.objects.get(pk=rule.pk).scheduled_for
        before = SmartAccountStandingAuthorization.objects.filter(pk=rule.standing_authorization_id)
        kept = before.values(*signed).get()
        before.update(**signed)
        out = self.run_rules()
        run = self.last_run()
        self.assertEqual((out['skipped'], run.status), (0, 'failed'), (out, run.error))
        self.assertNotIn('próxima fecha', run.message)
        self.assertEqual(SmartAccountRule.objects.get(pk=rule.pk).scheduled_for, slot)
        before.update(**kept)
        self.advance(3601)      # limit retries are asked again hourly (audit 6)
        self.assertEqual(self.run_rules()['sent'], 1)
        return run

    def test_a_cost_spike(self):
        self.assertEqual(self.limited(max_bridge_cost_bps=0).error, 'bridge_cost_above_limit')

    def test_a_rate_under_the_floor(self):
        self.assertEqual(self.limited(fx_tolerance_bps=0, reference_fx_rate=99).error, 'fx_rate_below_limit')


@override_settings(**mpa.VE)
class PagoMovilRunTimeLimitTests(mpa.VeBase):
    def test_a_provider_cost_under_the_floor_is_asked_again(self):
        from decimal import Decimal
        self.provider.preview.side_effect = lambda ves: {'total': str(ves / Decimal('40') + 3)}
        out = self.run_rule()
        run = SmartAccountRuleRun.objects.get(rule=self.rule)
        self.assertEqual((out['skipped'], run.status, run.error), (0, 'failed', 'fx_rate_below_limit'))
        self.assertNotIn('próxima fecha', run.message)


# ----------------------------------------------------------------- P3-1

class UnboundRelayTests(InfiniaPayoutCase):
    """A funded deposit Relay never binds, or leaves in a failure that is not
    final, goes to ops an hour past its deadline, and is still followed."""

    def late(self, relay=lambda: None):
        self.make_rule()
        self.send_run()
        self.bridges()
        relay()
        self.bridges()
        self.assertEqual(self.bridge().status, 'bridging')
        self.advance(self.bridge().deadline - int(time.time()) + 3601)
        self.bridges()
        bridge = self.bridge()
        self.assertEqual(bridge.status, 'needs_review')
        self.assertTrue(bridge.failure_code.startswith('relay_'), bridge.failure_code)
        self.journeys()
        self.mirror()
        # Parked: the owner's own sends are free (live_journeys), and it is still followed.
        self.assertEqual((self.journey().stage, self.payout().status), ('needs_review', 'review'))
        self.world.publish_deposit_hash = True
        self.world.requests.clear()
        self.world.relay_fills()
        self.bridges()
        self.assertEqual(self.bridge().status, 'delivered')

    def test_never_bound(self):
        self.world.publish_deposit_hash = False
        self.late()

    def test_a_failure_that_is_not_final(self):
        self.late(self.world.relay_fails)


class ContractSettlementEscalationTests(SimpleTestCase):
    """The shared step both contract-funded callers use (an Infinia bridge,
    a Pago Móvil send): no outcome an hour past the deadline is review."""

    def transfer(self, late):
        return SimpleNamespace(funding_mode='contract', binding={'contract_funding': {'sender': '0x' + '1' * 40}},
                               deadline=int(time.time()) - (3601 if late else 0), status='bridging',
                               failure_code='', quote=None)

    def reconcile(self, found, late=True):
        from payment_accounts import relay_settlement
        transfer = self.transfer(late)
        with mock.patch('payment_accounts.contract_funding.follow_request', return_value=found), \
                mock.patch('payment_accounts.contract_funding.needs_manual_refund', return_value=False):
            relay_settlement.reconcile_relay(transfer, client=mock.Mock())
        return transfer.status, transfer.failure_code

    def test_never_bound(self):
        self.assertEqual(self.reconcile(None), ('needs_review', 'relay_settlement_delayed'))
        self.assertEqual(self.reconcile(None, late=False), ('bridging', ''))

    def test_a_failure_that_is_not_final(self):
        failure = ('0x' + 'a' * 64, {'status': 'failure'})
        self.assertEqual(self.reconcile(failure), ('needs_review', 'relay_settlement_delayed'))
        self.assertEqual(self.reconcile(failure, late=False), ('bridging', ''))


# ----------------------------------------------------------------- P3-2

class RefusedReplayTests(InfiniaBusyCase):
    """A replay refused for the owner or the payee is not refused for ever:
    after a day the operation and its journey are parked, and ops told once."""

    def refused(self):
        self.make_rule()
        self.send_run()
        self.deliver()
        self.journeys()
        self.credit_conversion()
        self.refuse = {PAYOUT}
        self.journeys()
        self.refuse = set()
        mpa.ban(self.user)
        return self.journey().payout_operation

    def test_a_ban_that_lasts(self):
        operation = self.refused()
        self.replay()
        self.assertEqual((MoneyOperation.objects.get(pk=operation.pk).status, self.journey().stage),
                         ('unknown', 'paying_out'))
        for _ in range(2):
            self.replay()
        self.alerts.reset_mock()
        self.advance(DAY.total_seconds())
        self.replay()
        self.replay()
        self.workers()
        operation.refresh_from_db()
        self.assertEqual((operation.status, operation.failure_code), ('needs_review', 'replay_refused'))
        self.assertEqual(self.journey().stage, 'needs_review')
        self.assertEqual(self.payout().status, 'review')
        self.assertEqual((len(self.keys(PAYOUT)), self.world.payouts), (1, []))
        texts = [str(call.args[0]) for call in self.alerts.call_args_list]
        self.assertEqual(len([t for t in texts if str(operation.internal_id) in t]), 1, texts)

    def test_a_ban_lifted_the_same_day_still_pays(self):
        self.refused()
        self.replay()
        mpa.lift(self.user)
        self.replay()
        self.workers()
        self.assertEqual(self.payout().status, 'paid')


# ----------------------------------------------------------------- P3-3

class PagoAsapLongRateLimitTests(PagoAsapBusyTests):
    """A 429 took nothing: the key's replay window starts at an answer that
    may have been taken, never at a refusal for rate."""

    def test_a_rate_limit_longer_than_the_window_is_still_replayed(self):
        ramp = self.settled()
        self.post = (429, {})
        ramp = self.dispatch(ramp)
        for minutes in (11, 22, 33, 44, 55):
            ramp = self.dispatch(ramp, minutes * MINUTE)
            self.assertEqual(ve_send._phase(ramp), 'paying', ramp.status_detail)
            self.assert_not_parked(ramp)
        self.post = (200, {'payload': {'intentId': 'intent-test'}})
        ramp = self.dispatch(ramp, 66 * MINUTE)
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')
        self.assertEqual((len(self.keys), len(set(self.keys))), (7, 1))

    def test_an_answer_lost_before_still_ends_at_the_window(self):
        import requests
        ramp = self.settled()
        self.post = requests.Timeout('slow')
        ramp = self.dispatch(ramp)
        self.post = (429, {})
        ramp = self.dispatch(ramp, 11 * MINUTE)
        ramp = self.dispatch(ramp, 22 * MINUTE)
        ramp = self.dispatch(ramp, 33 * MINUTE)
        self.assertEqual(ramp.status_detail, 'needs_review:payout_unknown:replay_window')
        self.assertEqual(len(set(self.keys)), 1)

    def test_a_worker_that_died_after_sending_still_ends_at_the_window(self):
        ramp = self.settled()
        with mock.patch('ramps.pagoasap_send.dispatch', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.dispatch(ramp)
        self.post = (429, {})
        ramp = self.dispatch(RampTransaction.objects.get(pk=ramp.pk), 11 * MINUTE)
        ramp = self.dispatch(ramp, 22 * MINUTE)
        ramp = self.dispatch(ramp, 33 * MINUTE)
        self.assertEqual(ramp.status_detail, 'needs_review:payout_unknown:replay_window')


# ----------------------------------------------------------------- P3-4

class HeldOwnerAtTheAdapterTests(InfiniaPayoutCase):
    """A ban, a disabled account or an identity hold may be lifted: the run
    waits inside its slot, as before signing. A minor stays a minor."""

    def waits(self, patcher):
        self.make_rule()
        with patcher:
            out = self.run_rules()
        run = self.last_run()
        self.assertEqual((out['waiting'], out['skipped'], run.status), (1, 0, 'pending'), (out, run.error))
        self.assertEqual(self.world.signed, {})
        self.advance(600)
        self.assertEqual(self.run_rules()['sent'], 1)

    def test_a_ban(self):
        self.waits(mock.patch('security.utils.check_user_banned', return_value=(True, 'test')))

    def test_an_identity_hold(self):
        self.waits(mock.patch('security.identity_reuse.outgoing_identity_restriction', return_value='held'))

    def test_a_minor_is_final(self):
        self.make_rule()
        with mock.patch('security.minors.is_known_minor', return_value=True):
            out = self.run_rules()
        self.assertEqual((out['skipped'], self.last_run().error), (1, 'minor'))


@override_settings(**mpa.VE)
class HeldOwnerPagoMovilTests(mpa.VeBase):
    def test_a_ban_waits(self):
        mpa.ban(self.owner)
        out = self.run_rule()
        run = SmartAccountRuleRun.objects.get(rule=self.rule)
        self.assertEqual((out['waiting'], run.status, run.error), (1, 'pending', 'account_suspended'))
        self.told.assert_not_called()

    def test_a_disabled_owner_waits(self):
        type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.run_rule()['waiting'], 1)

    def test_a_minor_is_final(self):
        with mock.patch('security.minors.is_known_minor', return_value=True):
            self.assertEqual(self.run_rule()['skipped'], 1)
        self.assertIn('mayores de 18', SmartAccountRuleRun.objects.get(rule=self.rule).message)


# ----------------------------------------------------------------- P3-5

class RunToldWhereItEndedTests(InfiniaPayoutCase):
    """The run's own line follows the payment: a refund or a review is not
    "Pago en camino." any more."""
    rail = 'mx_clabe'

    def test_a_refunded_clabe_payment(self):
        self.make_rule()
        self.send_run()
        self.assertEqual(self.last_run().message, 'Pago en camino.')
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        self.mirror()
        self.assertEqual(self.payout().status, 'refunded')
        self.assertIn('volvió a tu Cuenta inteligente', self.last_run().message)

    def test_a_payment_in_review(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.publish_deposit_hash = False
        self.advance(self.bridge().deadline - int(time.time()) + 3601)
        self.workers()
        self.mirror()
        self.assertEqual(self.payout().status, 'review')
        self.assertIn('revisando', self.last_run().message)
        self.assertNotIn('en camino', self.last_run().message)
        from smart_account import payouts
        payouts.tell_run(self.last_run().pk, 'paid')       # a review that ended paid
        self.assertEqual(self.last_run().message, 'Pago en camino.')


@override_settings(**mpa.VE)
class PagoMovilRunToldTests(mpa.VeBase):
    def test_a_refund(self):
        from ramps import ve_send as send
        ramp = self.settled()
        send._update(ramp.pk, status='FAILED', detail='refunded_to_wallet', phase='refunded')
        from smart_account import payouts
        payouts.mirror_ramp_payouts()
        self.assertIn('volvió a tu Cuenta inteligente', SmartAccountRuleRun.objects.get(rule=self.rule).message)


# ----------------------------------------------------------------- P3-6

@override_settings(**mpa.VE)
class SignedNameTests(VeCase):
    """Saving the same beneficiary under another name does not rename an
    already signed rule's payee at Pago ASAP: its orders carry the name its
    first order was made with."""

    def names(self):
        return [r.metadata['ve_send']['beneficiary']['name'] for r in self.ramps().order_by('pk')]

    def test_a_rename_after_signing(self):
        from smart_account import relayer
        self.relay.side_effect = relayer.RelayError('simulation_reverted', 'execution reverted')
        self.run_rule()
        first, = self.names()
        self.save(holder_name='Otro Nombre')
        self.assertEqual(self.rule.pagomovil_destination.__class__.objects.get(
            pk=self.rule.pagomovil_destination_id).holder_name, 'Otro Nombre')
        with self.at(5 * MINUTE):
            self.run_rule()
        self.assertEqual(self.names(), [first, first])
