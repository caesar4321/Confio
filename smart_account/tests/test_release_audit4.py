"""The fourth money-path audit: what a rate limit, a lost transaction, a ban
or a late event may do to a payment, and what its owner and ops hear.
Synthetic ids, keys, names and addresses only."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from notifications.models import Notification
from payment_accounts import contract_funding
from payment_accounts import tasks as payment_tasks
from payment_accounts.clients import InfiniaClient, ProviderAPIError
from payment_accounts.providers.infinia import InfiniaProvider
from ramps import pagoasap_send, ve_send
from ramps.models import RampTransaction
from ramps.pagoasap_client import PagoAsapClient
from smart_account import automation, payouts, quotes, relayer, tasks
from smart_account.models import SmartAccountPayout, SmartAccountRelayTx, SmartAccountRuleRun

from . import infinia_world as w
from . import test_infinia_wallet_send_unchanged as wallet
from . import test_money_path_audit as mpa
from . import test_pagomovil_payouts as pm
from . import test_payout_signed_terms as signed
from . import test_rule_retry_notices as rn
from .infinia_base import InfiniaPayoutCase

DAY, HOUR, MINUTE = timedelta(days=1), timedelta(hours=1), timedelta(minutes=1)
CONVERSION, PAYOUT = '/v1/accounts/internal-transfer/', '/v2/payouts/'
QUOTE = '/v1/accounts/internal-transfer/quote/'
VE = mpa.VE


@override_settings(**VE)
class VeCase(pm.RunBase):
    """One Pago Móvil payout of US$100, up to each state these tests need."""
    event = signed.PagoMovilSignedTermsTests.event
    paid_onchain = signed.PagoMovilSignedTermsTests.paid_onchain

    def prepare(self, destination, **kwargs):
        kwargs.setdefault('amount_usd', '100.00')
        return super().prepare(destination, **kwargs)

    def setUp(self):
        real = ve_send.reserve
        super().setUp()
        self.chain.rules[(self.address, 1)]['amount_usd_wei'] = 100 * signed.WAD
        self.quote.return_value = dict(pm.quote(ves='3920.00', usdt='99.10'), usd_amount='100.00')
        for patcher in (mock.patch('ramps.ve_send.reserve', side_effect=real),
                        mock.patch('cusd_plus.cusd_vault.preview_redeem_wei',
                                   return_value=SimpleNamespace(net_wei=signed.HUNDRED_NET))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.alert = self.ops_alert_mock
        self.block = 100
        Notification.objects.filter(user=self.owner).delete()

    def settled(self):
        self.run_rule()
        ramp = self.paid_onchain()
        ramp = ve_send._update(ramp.pk, phase='settled', detail='settled', credited_usd='98.80')
        payouts.mirror_ramp_payouts()
        return ramp

    def notes(self, kind=None):
        rows = Notification.objects.filter(user=self.owner)
        return list(rows.filter(data__smart_account_event=kind) if kind else rows)

    def ramp_pushes(self):
        return [n.notification_type for n in self.notes() if n.notification_type.startswith('RAMP_')]

    def at(self, offset):
        return mock.patch('django.utils.timezone.now', return_value=timezone.now() + offset)


# ----------------------------------------------------------------- P1-1

PAGOASAP = dict(PAGOASAP_CLIENT_ID='x', PAGOASAP_CLIENT_SECRET='x', PAGOASAP_AUTH_URL='https://auth.invalid',
                PAGOASAP_AUDIENCE='x', PAGOASAP_API_URL='https://pay.invalid', PAGOASAP_SIGNING_PRIVATE_KEY='')


@override_settings(**VE, **PAGOASAP)
class PagoAsapBusyTests(VeCase):
    TERMS = dict(ves_amount='3900.00', cost='98.00', phone='04141234567', cedula='V12345678', bank_code='0134')

    def setUp(self):
        super().setUp()
        self.auth, self.post = (200, {'access_token': 't'}), (200, {'payload': {'intentId': 'intent-test'}})
        self.auth_error, self.keys = None, []

        def authorize(session, url, **kwargs):
            if self.auth_error:
                raise self.auth_error
            return w.Response(self.auth[1], self.auth[0])

        def send(session, request, **kwargs):
            self.keys.append(request.headers.get('idempotency-key'))
            if isinstance(self.post, Exception):
                raise self.post
            return w.Response(self.post[1], self.post[0])
        for patcher in (mock.patch('requests.Session.post', authorize), mock.patch('requests.Session.send', send),
                        mock.patch('ramps.pagoasap_send.payout_terms', return_value=self.TERMS)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def dispatch(self, ramp, offset=timedelta(0)):
        cache.clear()       # no token in the cache
        with self.at(offset):
            ramp = ve_send.sync(ramp)
            payouts.mirror_ramp_payouts()
        return ramp

    def assert_not_parked(self, ramp):
        self.assertNotIn('needs_review', ramp.status_detail)
        self.assertEqual(SmartAccountPayout.objects.get().status, 'funded')

    def test_a_429_is_replayed_under_the_same_key(self):
        ramp = self.settled()
        self.post = (429, {'error': 'Too Many Requests'})
        ramp = self.dispatch(ramp)
        self.assertEqual(ve_send._phase(ramp), 'paying')
        self.assert_not_parked(ramp)
        self.post = (200, {'payload': {'intentId': 'intent-test'}})
        ramp = self.dispatch(ramp, 11 * MINUTE)
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')
        self.assertEqual((len(self.keys), len(set(self.keys))), (2, 1))

    def token_fails(self):
        ramp = self.dispatch(self.settled())
        self.assertEqual((ve_send._phase(ramp), self.keys), ('settled', []))        # nothing was sent
        self.assert_not_parked(ramp)
        self.auth, self.auth_error = (200, {'access_token': 't'}), None
        ramp = self.dispatch(ramp, MINUTE)
        self.assertEqual((ve_send._phase(ramp), len(self.keys)), ('payout_pending', 1))

    def test_a_token_refused_for_rate(self):
        self.auth = (429, {})
        self.token_fails()

    def test_a_token_service_down(self):
        self.auth = (503, {})
        self.token_fails()

    def test_a_token_timed_out(self):
        import requests
        self.auth_error = requests.Timeout('slow')
        self.token_fails()

    def test_no_token_on_a_replay_keeps_the_key_and_is_not_a_refusal(self):
        ramp = self.settled()
        self.post = (429, {})
        ramp = self.dispatch(ramp)
        self.auth = (503, {})
        ramp = self.dispatch(ramp, 11 * MINUTE)
        self.assertEqual((ve_send._phase(ramp), len(self.keys)), ('paying', 1))
        self.assert_not_parked(ramp)
        self.auth, self.post = (200, {'access_token': 't'}), (200, {'payload': {'intentId': 'intent-test'}})
        ramp = self.dispatch(ramp, 22 * MINUTE)
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')
        self.assertEqual(len(set(self.keys)), 1)

    def test_any_other_refusal_is_still_one(self):
        ramp = self.settled()
        self.post = (400, {'error': 'Invalid Bank'})
        self.assertIn('payout_failed', self.dispatch(ramp).status_detail)


@override_settings(**PAGOASAP)
class PagoAsapClientTests(SimpleTestCase):
    def test_a_token_that_cannot_be_refreshed_after_a_401_sent_nothing(self):
        with mock.patch.object(PagoAsapClient, '_token', autospec=True) as token, \
                mock.patch('requests.Session.send', return_value=w.Response({}, 401)):
            from ramps import pagoasap_client
            token.side_effect = ['t', pagoasap_client.PagoAsapAuthError('refused', status=429)]
            outcome = pagoasap_send.dispatch(SimpleNamespace(internal_id='i'), dict(
                key='k', ves_amount='10', phone='0', cedula='V1', bank_code='0134'))
        self.assertEqual((outcome.kind, outcome.reason), ('retry', 'not_sent'))


# ----------------------------------------------------------------- P1-2

class InfiniaBusyCase(InfiniaPayoutCase):
    def setUp(self):
        super().setUp()
        self.refuse, self.posts, self.expired = set(), [], False
        real = self.world.infinia

        def infinia(method, path, body, params):
            if method == 'GET' and path in (CONVERSION, PAYOUT):
                field = 'idempotency_key' if path == CONVERSION else 'originId'
                key = params.get('idempotency_key') or params.get('origin_id')
                made = self.world.transfers if path == CONVERSION else self.world.payouts
                return w.Response({'status': 'success', 'data': [r for r in made if r.get(field) == key]})
            if method == 'POST':
                self.posts.append((path, dict(body or {})))
                if path in self.refuse:
                    return w.Response({'status': 'fail', 'message': 'Too Many Requests'}, 429)
                if path == CONVERSION and self.expired:
                    self.expired = False
                    return w.Response({'status': 'fail', 'message': f'Quote: {body["quote_id"]} is expired'}, 400)
            return real(method, path, body, params)
        patcher = mock.patch.object(self.world, 'infinia', side_effect=infinia)
        patcher.start()
        self.addCleanup(patcher.stop)

    def keys(self, path):
        field = 'idempotency_key' if path == CONVERSION else 'originId'
        return [body[field] for at, body in self.posts if at == path]

    def replay(self):
        self.advance(31 * 60)
        self.step(payment_tasks.reconcile_operations)


class InfiniaRateLimitTests(InfiniaBusyCase):
    def funded(self):
        self.make_rule()
        self.send_run()
        self.deliver()

    def finish(self):
        self.credit_conversion()
        self.journeys()
        self.workers()
        return self.payout()

    def test_a_429_on_the_conversion_is_replayed_under_its_key(self):
        self.funded()
        self.refuse = {CONVERSION}
        self.journeys()
        self.mirror()
        self.assertEqual((self.journey().stage, self.payout().status), ('converting', 'funded'))
        self.assertEqual(self.journey().fx_operation.status, 'unknown')
        self.refuse = set()
        self.replay()
        self.assertEqual(self.finish().status, 'paid')
        self.assertEqual((len(self.keys(CONVERSION)), len(set(self.keys(CONVERSION)))), (2, 1))
        self.assertEqual(len(self.world.transfers), 1)

    def test_a_429_on_the_payout_is_replayed_under_its_key(self):
        self.funded()
        self.journeys()
        self.credit_conversion()
        self.refuse = {PAYOUT}
        self.journeys()
        self.mirror()
        self.assertEqual(self.payout().status, 'funded')
        self.refuse = set()
        self.replay()
        self.workers()
        self.assertEqual(self.payout().status, 'paid')
        self.assertEqual((len(self.keys(PAYOUT)), len(set(self.keys(PAYOUT)))), (2, 1))
        self.assertEqual(len(self.world.payouts), 1)

    def test_a_quote_that_expired_meanwhile_is_requoted_without_a_false_alarm(self):
        self.funded()
        self.refuse = {CONVERSION}
        self.journeys()
        self.refuse, self.expired = set(), True
        self.pushed.reset_mock()
        self.replay()       # refused: the quote expired
        self.assertEqual(self.pushed.call_count, 0)     # "en revisión" is not true of it
        self.journeys()
        self.assertEqual(self.finish().status, 'paid')
        self.assertEqual(len(self.world.transfers), 1)

    def test_requotes_used_up_by_rate_limits_can_be_rechecked(self):
        self.funded()
        self.refuse = {CONVERSION}
        self.journeys()
        for _ in range(4):
            self.refuse, self.expired = set(), True
            self.replay()
            self.refuse = {CONVERSION}
            self.journeys()
        self.assertEqual(self.journey().failure_code, 'fx_quote_retries_exhausted')
        self.refuse = set()
        self.step(payouts.recheck, self.payout(), operator='ops')
        self.journeys()
        self.assertEqual(self.finish().status, 'paid')

    def test_a_replay_never_pays_for_a_banned_owner(self):
        self.funded()
        self.journeys()
        self.credit_conversion()
        self.refuse = {PAYOUT}
        self.journeys()
        self.refuse = set()
        mpa.ban(self.user)
        self.replay()
        self.assertEqual((len(self.keys(PAYOUT)), self.world.payouts), (1, []))
        self.assertIn('no se reenvía', self.alert_text())
        mpa.lift(self.user)
        self.replay()
        self.workers()
        self.assertEqual(self.payout().status, 'paid')

    def test_a_quote_429_waits_and_is_never_an_operation(self):
        self.funded()
        self.refuse = {QUOTE}
        self.journeys()
        self.assertEqual((self.journey().stage, self.journey().fx_operation_id), ('awaiting_credit', None))
        self.refuse = set()
        self.journeys()
        self.assertEqual(self.finish().status, 'paid')


@override_settings(RELAY_API_KEY='')
class ManualInfiniaSendUnchangedTests(InfiniaBusyCase):
    """A manual send is what it was: a 429 is ops', nothing is sent again."""
    prepared = wallet.WalletFundedSendTests.prepared
    signed = wallet.WalletFundedSendTests.signed

    def funded(self):
        bridge, journey = self.prepared()
        self.signed(bridge)
        fill, units = self.world.relay_fills()
        self.bridges()
        self.credit_usdc(fill, units)
        self.bridges()
        return journey

    def assert_never_sent_again(self, journey, path):
        journey.refresh_from_db()
        self.assertEqual((journey.stage, journey.failure_code), ('needs_review', 'provider_leg_requires_review'))
        self.refuse = set()
        for _ in range(2):
            self.replay()
            self.journeys()
        self.assertEqual(len(self.keys(path)), 1)

    def test_a_429_on_the_conversion(self):
        journey = self.funded()
        self.refuse = {CONVERSION}
        self.journeys()
        self.assert_never_sent_again(journey, CONVERSION)

    def test_a_429_on_the_payout(self):
        journey = self.funded()
        self.journeys()
        self.credit_conversion()
        self.refuse = {PAYOUT}
        self.journeys()
        self.assert_never_sent_again(journey, PAYOUT)


@override_settings(INFINIA_SECRET_ID='fake', INFINIA_SECRET_PASSWORD='fake', INFINIA_ACCOUNT_VALIDATION_ENABLED=True,
                   PAYMENT_ACCOUNTS_CALLBACK_BASE_URL='')
class OnlyKeyedContractPostsAreReplayedTests(SimpleTestCase):
    def refusing(self):
        session = mock.Mock(headers={})
        session.request.return_value = w.Response({'status': 'fail'}, 429)
        return InfiniaClient(session=session)

    def test_no_post_is_retryable_by_the_client(self):
        calls = {'create_owner': ({},), 'create_account': ({},), 'create_transfer_quote': ({},),
                 'create_payout': ({},), 'create_internal_transfer': ({},), 'create_bank_account_validation': ({},),
                 'update_owner': ('owner', {})}
        for name, args in calls.items():
            with self.assertRaises(ProviderAPIError) as raised:
                getattr(self.refusing(), name)(*args)
            self.assertFalse(raised.exception.retryable, name)
        for name, kwargs in (('refund_deposit', dict(movement_id=1, idempotency_key='k')),
                             ('initiate_owner_document', dict(document_type='passport'))):
            with self.assertRaises(ProviderAPIError) as raised:
                getattr(self.refusing(), name)(**kwargs)
            self.assertFalse(raised.exception.retryable, name)

    def raised(self, kind, *, key='key-1', contract=True):
        flow = SimpleNamespace(metadata={'contract_funding': {}} if contract else {})
        operation = SimpleNamespace(
            pk=1, idempotency_key=key, money_flow=flow, money_flow_id=None, provider_data={}, source_asset='MXN',
            source_amount=Decimal('10'), source_account=SimpleNamespace(provider_account_id='a'),
            destination_account=SimpleNamespace(provider_account_id='b'),
            external_destination={'country': 'MEX', 'destination_account': {'type': 'CLABE', 'clabe': '0' * 18}})
        with self.assertRaises(ProviderAPIError) as raised:
            getattr(InfiniaProvider(client=self.refusing()), kind)(operation)
        return raised.exception.retryable

    def test_a_contract_funded_leg_with_its_key(self):
        for kind in ('create_payout', 'create_transfer'):
            self.assertTrue(self.raised(kind), kind)

    def test_never_without_a_key_nor_for_a_manual_send(self):
        for kind in ('create_payout', 'create_transfer'):
            self.assertFalse(self.raised(kind, key=''), kind)
            self.assertFalse(self.raised(kind, contract=False), kind)


# ----------------------------------------------------------------- P2-1

class ClosedMarketTests(rn.RetryCase):
    def weekend(self, frequency='monthly', reason='market_closed'):
        self.make_rule('buy', frequency, balance=500)
        self.quote.side_effect = quotes.QuoteUnavailable(reason, retry_later=reason == 'market_closed')
        self.assertEqual(self.tick()['waiting'], 1)
        self.tick(30 * HOUR)

    def still_waiting(self):
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scheduled_for, self.slot)
        self.assertEqual(self.notices, [])
        self.assertTrue(self.run_row().error.startswith('market_'))

    def opens_and_buys(self):
        self.quote.side_effect = None
        self.assertEqual(self.tick(60 * HOUR)['sent'], 1)

    def test_an_unreadable_share_price_while_closed(self):
        self.weekend()
        with mock.patch('smart_account.automation._PlusPrices.limit_bounds',
                        side_effect=quotes.QuoteUnavailable('share_price_unavailable', retry_later=True)):
            self.assertEqual(self.tick(40 * HOUR)['waiting'], 1)
        self.still_waiting()
        self.opens_and_buys()

    def hiccup_at_the_open(self, code):
        self.weekend('weekly')
        self.quote.side_effect = None
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=relayer.RelayError(code)):
            self.tick(50 * HOUR)
        self.still_waiting()
        self.opens_and_buys()

    def test_claim_busy_at_the_open(self):
        self.hiccup_at_the_open('claim_busy')

    def test_a_lost_lock_at_the_open(self):
        self.hiccup_at_the_open('sponsor_lock_lost')

    def test_an_unreadable_rule_at_the_open(self):
        self.hiccup_at_the_open('rule_unreadable')

    def test_a_busy_sponsor_at_the_open(self):
        self.hiccup_at_the_open('sponsor_busy')

    def test_an_unreadable_session_waits_like_a_closed_one(self):
        self.weekend(reason='market_status_unavailable')
        self.still_waiting()
        self.opens_and_buys()

    def test_the_deadline_is_the_next_slot(self):
        for code in ('market_closed', 'market_status_unavailable'):
            for frequency in ('daily', 'weekly', 'monthly'):
                self.assertEqual(automation.retry_deadline(code, frequency, self.start),
                                 automation.next_slot(frequency, self.start))

    def test_a_market_that_never_opens_still_ends_at_the_next_slot(self):
        self.weekend('weekly')
        self.tick(7 * DAY + HOUR)
        self.rule.refresh_from_db()
        self.assertNotEqual(self.rule.scheduled_for, self.slot)
        self.assertEqual(self.signed, [])


# ----------------------------------------------------------------- P2-2

class DroppedTransactionTests(rn.RetryCase):
    def drop(self, at):
        self.broadcast_error = 'every node timed out'
        self.tick(at)
        self.broadcast_error = None
        self.offset = at + 5 * MINUTE
        self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 1)

    def test_a_dropped_call_keeps_the_three_days(self):
        self.make_rule()
        self.tick()
        self.balance(500)
        self.drop(2 * DAY)
        message = self.run_row().message
        self.assertIn(self.date(self.slot + 3 * DAY), message)
        self.assertNotIn('Agrega saldo', message)       # it is there
        self.assertEqual(self.tick(2 * DAY + 10 * MINUTE)['sent'], 1)

    def test_a_dropped_call_keeps_the_market_wait(self):
        self.make_rule('buy', 'weekly', balance=500)
        self.quote.side_effect = quotes.QuoteUnavailable('market_closed', retry_later=True)
        self.tick()
        self.quote.side_effect = None
        self.drop(50 * HOUR)
        self.assertEqual(self.tick(51 * HOUR)['sent'], 1)

    def test_a_real_revert_still_keeps_24_hours(self):
        self.make_rule()
        self.tick()
        self.balance(500)
        self.assertEqual(self.tick(2 * DAY)['sent'], 1)
        row = SmartAccountRelayTx.objects.get()
        SmartAccountRelayTx.objects.update(status='reverted')
        row.refresh_from_db()
        automation.on_relay_tx_final(row)
        self.assertEqual(self.tick(2 * DAY + 5 * MINUTE)['sent'], 0)
        self.rule.refresh_from_db()
        self.assertNotEqual(self.rule.scheduled_for, self.slot)


# ----------------------------------------------------------------- P2-3

class HeldBeforeSigningTests(rn.RetryCase):
    def held(self, kind, hold):
        self.make_rule(kind, balance=500)
        real = relayer.simulate

        def simulate(*args):
            real(*args)
            hold()
        with mock.patch('smart_account.relayer.simulate', side_effect=simulate):
            self.assertEqual(self.tick()['waiting'], 1)
        self.assertEqual((self.signed, SmartAccountRelayTx.objects.count()), ([], 0))
        self.assertEqual(self.run_row().error.split(':')[0], 'owner_held')     # with the refusal's code

    def test_a_ban(self):
        self.held('send', lambda: mpa.ban(self.owner))

    def test_a_disabled_owner(self):
        # Committed by someone else: the worker's object still says active.
        self.held('buy', lambda: type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False))

    def test_an_identity_hold(self):
        self.held('send', lambda: self.holds.update({self.owner.pk: 'held'}))


class HeldPayoutBeforeSigningTests(InfiniaPayoutCase):
    def test_a_banned_owners_payout_is_not_signed(self):
        self.make_rule()
        real = relayer.simulate

        def simulate(*args):
            real(*args)
            mpa.ban(self.user)
        with mock.patch('smart_account.relayer.simulate', side_effect=simulate):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual(self.world.signed, {})


# ----------------------------------------------------------------- P2-4

@override_settings(**VE)
class RampPushTests(VeCase):
    def test_nothing_is_announced_before_money_left(self):
        self.relay.side_effect = relayer.RelayError('simulation_unreadable', 'node')
        self.run_rule()
        self.assertTrue(self.ramps().exists())
        self.assertEqual(self.ramp_pushes(), [])

    def test_a_paid_payout_is_told_once(self):
        ramp = self.settled()
        ve_send._update(ramp.pk, status='COMPLETED', detail='delivered', phase='paid')
        payouts.mirror_ramp_payouts()
        self.assertEqual([n.data.get('smart_account_event') for n in self.notes()], ['payout_delivered'])

    def test_a_wallet_send_is_announced_as_before(self):
        row = RampTransaction(provider='pagoasap', direction='off_ramp', status='PENDING', country_code='VE',
                              actor_user=self.owner, destination='cusd_plus', fiat_currency='VES',
                              external_id='wallet-send', metadata={'ve_send': {'phase': 'awaiting_funding'}})
        row.save()
        for status in ('PROCESSING', 'COMPLETED', 'FAILED'):
            row.status = status
            row.save()
        self.assertEqual(sorted(self.ramp_pushes()),
                         ['RAMP_COMPLETED', 'RAMP_FAILED', 'RAMP_PENDING', 'RAMP_PROCESSING'])


# ----------------------------------------------------------------- P2-5

@override_settings(**VE)
class OwnerToldTests(VeCase):
    def told_once(self, kind):
        payouts.mirror_ramp_payouts()
        payouts.mirror_ramp_payouts()
        self.assertEqual(len(self.notes()), 1, [n.title for n in self.notes()])
        note, = self.notes(kind)
        return note

    def test_a_parked_payment(self):
        ramp = self.settled()
        with mock.patch('smart_account.payouts.ramp_owner_problem', return_value='identity_hold'):
            ve_send.sync(ramp)
        note = self.told_once('payout_review')
        self.assertIn('US$100.00', note.message)
        self.assertIn('No lo repitas', note.message)

    def test_a_bank_refusal(self):
        ramp = self.settled()
        ramp = ve_send._update(ramp.pk, phase='paying', detail='paying', payout_key='k')
        ve_send.apply_outcome(ramp, ve_send.Outcome('failed', reason='invalid_account'), 'k')
        self.told_once('payout_review')

    def test_a_refund(self):
        ramp = self.settled()
        ve_send._update(ramp.pk, status='FAILED', detail='refunded_to_wallet', phase='refunded')
        note = self.told_once('payout_refunded')
        self.assertIn('volvió a tu Cuenta inteligente', note.message)

    def test_a_state_already_told_is_not_told_again(self):
        ramp = self.settled()
        ve_send._update(ramp.pk, detail=f'needs_review:{ve_send.RATE_OUTSIDE}', phase='payout_review')
        payouts.tell_rate_held(self.ramps().get())
        self.told_once('payout_rate_held')

    def test_the_rate_notice_wins_whoever_is_first(self):
        ramp = self.settled()
        ve_send._update(ramp.pk, detail=f'needs_review:{ve_send.RATE_OUTSIDE}', phase='payout_review')
        payouts.mirror_ramp_payouts()
        payouts.tell_rate_held(self.ramps().get())
        self.told_once('payout_rate_held')

    def test_money_after_closure_is_told_by_its_own_notice(self):
        self.run_rule()
        ve_send.close_unsent(self.ramps().get())
        payouts.mirror_ramp_payouts()
        self.paid_onchain()
        self.told_once('payout_resumed')


# ----------------------------------------------------------------- P2-6

@override_settings(**VE)
class StallTests(VeCase):
    def stalled(self):
        self.assertNotIn('detenido', str(self.alert.call_args_list))
        with self.at(2 * HOUR + MINUTE):
            payouts.mirror_ramp_payouts()
        self.assertIn('detenido más de 2 horas', str(self.alert.call_args_list))

    def test_a_funded_payout_waiting_for_balance(self):
        ramp = self.settled()
        ve_send._update(ramp.pk, detail='waiting_balance')
        payouts.mirror_ramp_payouts()
        self.stalled()

    def test_money_sent_and_not_proven(self):
        self.run_rule()
        SmartAccountPayout.objects.update(status='onchain_sent')
        payouts.mirror_ramp_payouts()
        self.stalled()


# ----------------------------------------------------------------- P3-1

@override_settings(**VE)
class EventNotSeenYetTests(VeCase):
    def test_funding_waits_for_the_event_and_then_pays(self):
        self.run_rule()
        ramp = ve_send.report_funding(self.ramps().get(), pm.TX, by_payout=True)
        units = int(ve_send._section(ramp)['deposit_wei'])
        with mock.patch('ramps.ve_send._check_receipt', return_value=(pm.TX, units)):
            ramp = ve_send.sync(ramp)
            self.assertEqual((ve_send._phase(ramp), ramp.status), ('funding_reported', 'PENDING'))
            self.assertNotIn('funding_terms_problem', ve_send._section(ramp))
            self.event('PayoutSent', {'id': '1', 'payoutRef': self.rule.payout_ref, 'destination': pm.DEPOSIT,
                                      'usdtOut': str(units)}, pm.TX)
            self.assertEqual(ve_send._phase(ve_send.sync(ramp)), 'funded')

    def test_a_settled_payment_waits_for_it(self):
        ramp = self.settled()
        with mock.patch('smart_account.payouts.ramp_funding_problem', return_value='event_not_found'), \
                mock.patch('ramps.pagoasap_send.payout_terms') as terms:
            ramp = ve_send.sync(ramp)
        terms.assert_not_called()
        self.assertEqual(ve_send._phase(ramp), 'settled')

    def test_an_event_of_another_deposit_still_parks(self):
        self.run_rule()
        ramp = ve_send.report_funding(self.ramps().get(), pm.TX, by_payout=True)
        self.event('PayoutSent', {'id': '1', 'payoutRef': self.rule.payout_ref, 'destination': '0x' + 'd5' * 20}, pm.TX)
        units = int(ve_send._section(ramp)['deposit_wei'])
        with mock.patch('ramps.ve_send._check_receipt', return_value=(pm.TX, units)):
            ramp = ve_send.sync(ramp)
        self.assertEqual(ramp.status_detail, ve_send.TERMS_CHANGED_DETAIL)


class EventNotSeenYetInfiniaTests(InfiniaPayoutCase):
    def test_a_journey_waits_for_the_event_and_then_pays(self):
        self.make_rule()
        self.send_run()
        with mock.patch('smart_account.payouts.execution_problem', return_value='event_not_found'):
            self.bridges()
            self.deliver()
            self.journeys()
            self.assertEqual((self.journey().stage, self.world.transfers), ('awaiting_credit', []))
        self.assertNotIn('terms_changed', self.bridge().binding['contract_funding'])
        self.journeys()
        self.credit_conversion()
        self.journeys()
        self.workers()
        self.assertEqual(self.payout().status, 'paid')

    def test_a_recheck_before_the_event_parks_nothing_more(self):
        self.make_rule()
        self.send_run()
        self.deliver()
        type(self.journey()).objects.update(stage='needs_review', failure_code=contract_funding.DELAYED)
        with mock.patch('smart_account.payouts.execution_problem', return_value='event_not_found'):
            self.step(contract_funding.reopen_delayed, self.bridge().pk)
        self.assertEqual(self.journey().failure_code, contract_funding.DELAYED)


# ----------------------------------------------------------------- P3-2

@override_settings(**VE)
class LateFundingConsoleTests(VeCase):
    def test_the_console_cannot_pay_late_funding(self):
        self.run_rule()
        ve_send.close_unsent(self.ramps().get())
        payouts.mirror_ramp_payouts()
        ramp = self.paid_onchain()
        with mock.patch('ramps.ve_send._find_funding', return_value=(pm.TX, signed.HUNDRED_NET)):
            ramp = ve_send.sync(ramp)
        self.assertEqual(ramp.status_detail, 'needs_review:late_funding')
        for confirmed in (False, True):
            with self.assertRaises(ve_send.VeSendError):
                ve_send.retry_payout(ramp, operator='ops', reviewed_key='', reviewed_revision=0,
                                     confirmed_unpaid=confirmed)
        self.assertEqual(ve_send._phase(self.ramps().get()), 'payout_review')


# ----------------------------------------------------------------- P3-3

class ReorgedRunTests(rn.RetryCase):
    def test_a_run_left_sent_by_a_reorg_runs_again(self):
        self.make_rule(balance=500)
        self.assertEqual(self.tick()['sent'], 1)
        SmartAccountRelayTx.objects.update(status='reorged')        # and the worker died before saying so
        self.tick(5 * MINUTE)
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'failed')
        self.assertEqual(self.tick(10 * MINUTE)['sent'], 1)
