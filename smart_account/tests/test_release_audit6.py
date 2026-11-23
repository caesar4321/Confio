"""The sixth money-path audit (of round 5's delta): a rate limit that never
ends, a refusal counted from its own start, limit retries that churn, a held
owner told why, and the name the owner signed.
Synthetic ids, keys, names and addresses only."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from payment_accounts import contract_funding
from payment_accounts.models import MoneyOperation
from ramps import ve_send
from ramps.models import RampTransaction
from ramps.pagoasap_client import PagoAsapError
from ramps.tests import test_ve_send as core
from smart_account.models import SmartAccountStandingAuthorization

from . import test_money_path_audit as mpa
from .infinia_base import InfiniaPayoutCase
from .test_release_audit4 import PAYOUT, InfiniaBusyCase, PagoAsapBusyTests, VeCase

MINUTE = timedelta(minutes=1)
RATE_LIMITED_REVIEW = 'needs_review:payout_unknown:rate_limited'


def setUpModule():
    core.setUpModule()


def tearDownModule():
    core.tearDownModule()


# ----------------------------------------------------------------- P2

class EndlessRateLimitTests(PagoAsapBusyTests):
    """Replays refused for rate end 2 hours after the key's first dispatch:
    review, with one ops alert."""

    def test_two_hours_of_429_go_to_review_once(self):
        ramp = self.settled()
        self.post = (429, {})
        ramp = self.dispatch(ramp)
        step = 0
        while ramp.status_detail != RATE_LIMITED_REVIEW and step < 40:
            step += 1
            ramp = self.dispatch(ramp, step * 11 * MINUTE)
            if step * 11 < 110:
                self.assert_not_parked(ramp)
        self.assertEqual(ramp.status_detail, RATE_LIMITED_REVIEW)
        self.assertLessEqual(step * 11, 132)
        sent = len(self.keys)
        for later in range(step + 1, step + 6):
            ramp = self.dispatch(ramp, later * 11 * MINUTE)
        self.assertEqual((len(self.keys), len(set(self.keys))), (sent, 1))
        # The send's own review alert, once (the rule's payout mirror adds its usual one).
        texts = [str(c.args[0]) for c in self.alert.call_args_list
                 if 'rate_limited' in str(c.args[0]) and 'requiere revisión' in str(c.args[0])]
        self.assertEqual(len(texts), 1, texts)

    def test_paid_inside_the_two_hours(self):
        ramp = self.settled()
        self.post = (429, {})
        ramp = self.dispatch(ramp)
        for step in range(1, 9):        # 88 minutes, past the 30-minute window
            ramp = self.dispatch(ramp, step * 11 * MINUTE)
        self.post = (200, {'payload': {'intentId': 'intent-test'}})
        ramp = self.dispatch(ramp, 99 * MINUTE)
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')


class WalletSendRateLimitTests(TestCase):
    """A wallet-signed send: a short 429 no longer parks it at 30 minutes,
    and a long one ends the same way."""
    setUp = core.SendCoreTests.setUp
    _ramp = core.SendCoreTests._ramp
    _funded = core.SendCoreTests._funded

    def pay(self, ramp, client, offset):
        later = timezone.now() + offset
        ve_send._update(ramp.pk, dispatch_lease_until=None)
        with mock.patch('django.utils.timezone.now', return_value=later), \
                mock.patch('ramps.pagoasap_send._client', return_value=client):
            return ve_send.sync(RampTransaction.objects.get(pk=ramp.pk))

    def test_a_short_and_a_long_rate_limit(self):
        busy = core.pagoasap_client(create=PagoAsapError('busy', status=429))
        ramp = self.pay(self._funded(), busy, timedelta(0))
        self.assertEqual(ve_send._phase(ramp), 'paying')
        ramp = self.pay(ramp, busy, 40 * MINUTE)
        self.assertEqual(ve_send._phase(ramp), 'paying')       # not parked at 30 minutes
        paid = core.pagoasap_client()
        self.assertEqual(ve_send._phase(self.pay(ramp, paid, 50 * MINUTE)), 'payout_pending')
        keys = {c.kwargs['idempotency_key'] for c in busy.create_payout.call_args_list + paid.create_payout.call_args_list}
        self.assertEqual(len(keys), 1)

        other = self._funded()
        ramp = self.pay(other, busy, timedelta(0))
        for minutes in range(11, 140, 11):
            ramp = self.pay(ramp, busy, minutes * MINUTE)
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail), ('payout_review', RATE_LIMITED_REVIEW))


# ----------------------------------------------------------------- P3-1

class RefusalClockTests(InfiniaBusyCase):
    def unanswered(self):
        self.make_rule()
        self.send_run()
        self.deliver()
        self.journeys()
        self.credit_conversion()
        self.refuse = {PAYOUT}
        self.journeys()
        self.refuse = set()
        return self.journey().payout_operation

    def test_the_day_counts_from_the_first_refusal(self):
        operation = self.unanswered()
        self.advance(23 * 3600)         # no pass meanwhile: nothing refused it yet
        mpa.ban(self.user)
        self.replay()
        self.advance(2 * 3600)
        self.replay()
        self.assertEqual(MoneyOperation.objects.get(pk=operation.pk).status, 'unknown')
        self.advance(23 * 3600)
        self.replay()
        self.assertEqual(MoneyOperation.objects.get(pk=operation.pk).status, 'needs_review')

    def test_a_replay_that_passes_clears_the_clock(self):
        operation = self.unanswered()
        mpa.ban(self.user)
        self.replay()
        self.assertIn(contract_funding.REPLAY_REFUSED_SINCE,
                      MoneyOperation.objects.get(pk=operation.pk).provider_data)
        mpa.lift(self.user)
        self.replay()
        self.assertNotIn(contract_funding.REPLAY_REFUSED_SINCE,
                         MoneyOperation.objects.get(pk=operation.pk).provider_data)

    def test_a_bank_check_pending_is_a_wait(self):
        operation = self.unanswered()
        self.alerts.reset_mock()
        with mock.patch('payment_accounts.contract_funding.payee_problem', return_value=('payee_pending', True)):
            self.replay()
            self.advance(25 * 3600)
            self.replay()
        operation.refresh_from_db()
        self.assertEqual(operation.status, 'unknown')
        self.assertNotIn(contract_funding.REPLAY_REFUSED_SINCE, operation.provider_data)
        self.assertNotIn(str(operation.internal_id), self.alert_text())
        self.assertEqual(len(self.keys(PAYOUT)), 1)


# ----------------------------------------------------------------- P3-2

class LimitRetrySpacingTests(InfiniaPayoutCase):
    def over_limit(self):
        rule = self.make_rule()
        SmartAccountStandingAuthorization.objects.filter(pk=rule.standing_authorization_id).update(
            max_bridge_cost_bps=0)
        return rule

    def test_asked_again_hourly_not_every_pass(self):
        self.over_limit()
        real = contract_funding.price
        with mock.patch('payment_accounts.contract_funding.price', side_effect=real) as priced:
            for _ in range(12):
                self.run_rules()
                self.advance(300)
            self.assertLessEqual(priced.call_count, 2)
            self.advance(3600)
            self.run_rules()
            self.assertGreater(priced.call_count, 1)

    def test_a_rule_always_over_its_limit_does_not_page_ops(self):
        self.over_limit()
        for _ in range(27):
            self.run_rules()
            self.advance(3600)
        run = self.last_run()
        self.assertEqual((run.status, run.error), ('failed', 'bridge_cost_above_limit'))
        self.assertIsNotNone(run.notified_at)
        self.assertNotIn('no hecho', self.alert_text())


# ----------------------------------------------------------------- P3-3

class HeldOwnerToldWhyTests(InfiniaPayoutCase):
    def test_a_ban_that_outlasts_the_slot_says_why(self):
        self.make_rule()
        with mock.patch('security.utils.check_user_banned', return_value=(True, 'test')):
            for _ in range(26):
                self.run_rules()
                self.advance(3600)
        run = self.last_run()
        self.assertEqual(run.error, 'account_suspended')
        self.assertIn('suspendida', run.message)
        self.assertIn('Escríbenos por soporte', run.message)

    def test_a_deleted_account_is_final(self):
        with self.assertRaises(contract_funding.Refused) as refused:
            contract_funding.require_owner(mock.Mock(deleted_at=timezone.now(), account_type='personal',
                                                     user=self.user))
        self.assertEqual((refused.exception.code, refused.exception.retry), ('account_unavailable', False))

    def test_a_business_account_is_final(self):
        with self.assertRaises(contract_funding.Refused) as refused:
            contract_funding.require_owner(mock.Mock(deleted_at=None, account_type='business', user=self.user))
        self.assertFalse(refused.exception.retry)

    def test_a_disabled_user_waits(self):
        user = get_user_model()(is_active=False)
        with self.assertRaises(contract_funding.Refused) as refused:
            contract_funding.require_owner(mock.Mock(deleted_at=None, account_type='personal', user=user))
        self.assertTrue(refused.exception.retry)


# ----------------------------------------------------------------- P3-4

@override_settings(**mpa.VE)
class SignedNameAtPrepareTests(VeCase):
    def test_the_name_signed_is_stored_and_sent(self):
        authorization = self.rule.standing_authorization
        self.assertEqual(authorization.holder_name, 'Ana Pérez')
        self.save(holder_name='Otro Nombre')       # renamed before the first run
        self.run_rule()
        ramp = RampTransaction.objects.filter(provider='pagoasap').get()
        self.assertEqual(ramp.metadata['ve_send']['beneficiary']['name'], 'Ana Pérez')

    def test_an_authorization_signed_before_falls_back(self):
        SmartAccountStandingAuthorization.objects.filter(pk=self.rule.standing_authorization_id).update(
            holder_name=None)
        self.run_rule()
        ramp = RampTransaction.objects.filter(provider='pagoasap').get()
        self.assertEqual(ramp.metadata['ve_send']['beneficiary']['name'], 'Ana Pérez')

