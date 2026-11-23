"""The money-path audit of automatic bank payments, one class per finding.

The invariant under all of them: money that left the account is paid only
inside what the owner signed (rate, amount, recipient), and is never lost
from sight. Relay, Infinia, Pago ASAP and both chains are fakes; every
identifier is invented."""
import itertools
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.core.cache import cache
from django.db import transaction
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone

from notifications.models import Notification
from payment_accounts import contract_funding
from payment_accounts.infinia_bridge import live_journeys
from payment_accounts.models import InfiniaFeeDebt, InfiniaJourney, MoneyFlow
from smart_account import automation, offer, payouts, reconcile, relayer, services, tasks
from smart_account.models import (
    SmartAccountPayout, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun,
    SmartAccountStandingAuthorization,
)

from . import infinia_world as w
from . import test_infinia_wallet_send_unchanged as wallet
from . import test_pagomovil_payouts as pm
from .base import INFINIA_SWITCHES, SmartAccountTestCase
from .infinia_base import SETTINGS, InfiniaPayoutCase, InfiniaPayoutSteps
from .test_payout_interleavings import PATIENCE, Waits, Worker

HOUR = 3600
FLOOR = Decimal('17.945')       # reference 18.50 less the signed 3%
ABOVE, BELOW = Decimal('18.20'), Decimal('17.65')


def ban(user):
    from django.contrib.auth import get_user_model
    from security.models import UserBan
    staff = get_user_model().objects.create_user(
        username=f'staff-{user.pk}', password='x', firebase_uid=f'uid-staff-{user.pk}')
    return UserBan.objects.create(user=user, ban_type='permanent', reason='fraud', reason_details='test',
                                  banned_by=staff)


def lift(user):
    from security.models import UserBan
    UserBan.objects.filter(user=user).update(deleted_at=timezone.now())


def held_notices(user):
    return Notification.objects.filter(user=user, data__smart_account_event='payout_rate_held').count()


class InfiniaCase(InfiniaPayoutCase):
    def funded(self, amount=None, run_rate='17.98'):
        self.make_rule(amount)
        self.world.rates['MXN'] = Decimal(run_rate)
        self.send_run()
        self.deliver()

    def finish(self):
        self.journeys()
        self.credit_conversion()
        self.journeys()
        self.workers()
        return self.payout()

    def paid_rate(self):
        sent = self.world.transfers[-1]
        return Decimal(str(sent['destination_amount'])) / Decimal(str(sent['source_amount']))

    def assert_nothing_moved(self):
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))

    def parked_for_rate(self):
        self.funded()
        self.world.rates['MXN'] = BELOW
        self.journeys()
        self.advance(HOUR + 60)
        self.workers()
        self.assertEqual((self.journey().stage, self.journey().failure_code),
                         ('needs_review', 'fx_quote_outside_authorization'))

    def recheck(self):
        return self.step(payouts.recheck, self.payout(), operator='ops')


# ---------------------------------------------------------------- 1 (P1)

class SignedRateInfiniaTests(InfiniaCase):
    def test_a_lower_rate_after_delivery_waits_untold_then_is_parked_and_told_once(self):
        self.funded()
        self.world.rates['MXN'] = BELOW
        self.journeys()
        self.mirror()
        self.assert_nothing_moved()
        self.assertEqual((self.journey().stage, self.payout().status), ('awaiting_credit', 'funded'))
        self.assertEqual(held_notices(self.user), 0)
        self.assertNotIn('en revisión', self.alert_text())

        self.advance(HOUR + 60)
        self.workers()
        self.workers()
        self.assert_nothing_moved()
        self.assertEqual((self.journey().failure_code, self.payout().status),
                         ('fx_quote_outside_authorization', 'review'))
        self.assertEqual(held_notices(self.user), 1)
        told = Notification.objects.get(user=self.user, data__smart_account_event='payout_rate_held')
        self.assertIn('salió de tu Cuenta inteligente', told.message)
        self.assertNotIn('no se hizo', told.message)
        self.assertIn('en USDC en la cuenta Infinia del dueño', self.alert_text())
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(confio_account=self.personal)).exists())

    def test_a_small_payment_is_held_to_the_same_rate(self):
        self.funded('5.00')
        self.world.rates['MXN'] = BELOW
        self.journeys()
        self.assert_nothing_moved()

    def test_slippage_room_is_not_room_under_the_rate(self):
        self.funded()
        journey = self.journey()
        delivered = Decimal(self.bridge().actual_out_units) / 10 ** 6
        rate = FLOOR - Decimal('0.01')
        self.assertGreater(delivered * rate, journey.minimum_fx_output)     # the amount alone would pass
        self.world.rates['MXN'] = rate
        self.journeys()
        self.assert_nothing_moved()

    def test_a_rate_that_recovers_inside_the_window_pays_untold(self):
        self.funded()
        self.world.rates['MXN'] = BELOW
        self.journeys()
        self.advance(HOUR // 2)
        self.world.rates['MXN'] = ABOVE
        self.assertEqual(self.finish().status, 'paid')
        self.assertGreaterEqual(self.paid_rate(), FLOOR)
        self.assertEqual(held_notices(self.user), 0)

    def test_a_requote_is_held_to_the_rate_too(self):
        self.funded()
        with mock.patch('payment_accounts.infinia_journeys.submit_money_operation'):
            self.journeys()                         # quoted, never submitted
        self.advance(300)                           # that quote expired
        self.world.rates['MXN'] = BELOW
        self.journeys()
        self.assert_nothing_moved()
        self.advance(HOUR + 60)
        self.workers()
        self.assertEqual(self.journey().fx_operation.failure_code, 'never_submitted')
        self.assert_nothing_moved()

        self.world.rates['MXN'] = ABOVE
        self.recheck()
        self.assertEqual(self.finish().status, 'paid')
        self.assertGreaterEqual(self.paid_rate(), FLOOR)
        self.assertEqual(len(self.world.transfers), 1)

    def test_ops_continue_never_pays_under_the_rate_and_pays_once_it_is_back(self):
        self.parked_for_rate()
        self.recheck()
        self.workers()
        self.assert_nothing_moved()                 # still under: parked again, not told again
        self.assertEqual(self.journey().stage, 'needs_review')
        self.assertEqual(held_notices(self.user), 1)

        self.world.rates['MXN'] = ABOVE
        self.recheck()
        self.assertEqual(self.finish().status, 'paid')
        self.assertGreaterEqual(self.paid_rate(), FLOOR)
        self.assertEqual(len(self.world.payouts), 1)

    def test_ops_cannot_continue_to_a_rejected_recipient(self):
        self.parked_for_rate()
        self.world.rates['MXN'] = ABOVE
        self.destination.provider_data = dict(self.destination.provider_data, validation={'status': 'ERROR'})
        self.destination.save(update_fields=['provider_data'])
        with self.assertRaises(payouts.RecheckRefused):
            self.recheck()
        self.journeys()
        self.assert_nothing_moved()

    def test_ops_cannot_continue_what_the_chain_executed_differently(self):
        self.parked_for_rate()
        with mock.patch('smart_account.payouts.execution_problem', return_value='amount_above_signed'):
            with self.assertRaises(payouts.RecheckRefused):
                self.recheck()
        self.assertEqual(self.journey().stage, 'needs_review')

    def test_a_terms_park_that_no_longer_holds_can_continue(self):
        self.make_rule()
        self.send_run()
        with mock.patch('smart_account.payouts.execution_problem', return_value='authorization_changed'):
            self.bridges()
        self.deliver()
        self.journeys()
        self.assertEqual(self.journey().failure_code, contract_funding.TERMS_CHANGED)
        self.recheck()
        self.assertEqual(self.finish().status, 'paid')

    def test_money_back_at_the_contract_cannot_be_continued(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        with self.assertRaises(payouts.RecheckRefused):
            self.recheck()

    def test_a_retry_not_yet_funded_is_not_sent_under_the_rate(self):
        self.make_rule()
        self.world.revert_mined = True
        self.run_rules()
        self.relay_receipts()                       # reverted on chain: the order is kept for the retry
        self.assertEqual(self.bridge().status, 'submitted')
        self.world.revert_mined = False
        self.world.rates['MXN'] = BELOW
        self.assertEqual(self.run_rules()['errors'], 1)     # today's rate: asked again inside the slot
        self.assertEqual(self.last_run().error, 'fx_rate_below_limit')
        self.assertEqual((self.bridge().status, len(self.world.signed)), ('expired', 1))


class RulesSignedByTheCodeInProductionTests(InfiniaCase):
    """50e95b312 offers CLABE rules and signs them with no reference rate."""

    def test_a_rule_signed_without_a_rate_never_runs_and_is_not_switched_off(self):
        rule = self.make_rule()
        SmartAccountStandingAuthorization.objects.update(reference_fx_rate=None)
        self.assertEqual(self.run_rules()['skipped'], 1)
        self.assertEqual(self.last_run().error, 'fx_floor_unsigned')
        self.assertEqual((SmartAccountPayout.objects.count(), self.world.signed), (0, {}))
        rule.refresh_from_db()
        self.assertEqual((rule.active, rule.deactivated_reason), (True, ''))
        self.assertEqual(payouts.deactivate_changed_rules(), 0)


class VeBase(pm.RunBase):
    def setUp(self):
        from ramps import ve_send
        from ramps import pagoasap_send
        real, self.real_target = ve_send.reserve, pagoasap_send.funding_target
        real_check = pagoasap_send.pays_at_floor
        super().setUp()
        for patcher in (mock.patch('ramps.ve_send.reserve', side_effect=real),      # it keeps funding_sender
                        mock.patch('ramps.pagoasap_send.pays_at_floor', side_effect=real_check),
                        mock.patch('smart_account.payouts.ramp_funding_problem', return_value='')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.provider = mock.Mock(is_configured=True)
        self.rate('40')
        self.provider.balances.return_value = {'USD': Decimal('1000')}
        self.provider.create_payout.return_value = 'intent-test'
        client = mock.patch('ramps.pagoasap_send._client', return_value=self.provider)
        client.start()
        self.addCleanup(client.stop)

    def rate(self, value):
        value = Decimal(value)
        self.provider.rate.return_value = value
        self.provider.preview.side_effect = lambda ves: {'total': str(ves / value)}

    def settled(self, credited='49.40'):
        from ramps import ve_send
        self.assertEqual(self.run_rule()['sent'], 1)
        SmartAccountRuleRun.objects.update(status='ok', tx_hash=pm.TX)
        SmartAccountPayout.objects.update(status='funded')
        return ve_send._update(self.ramps().get().pk, status='PROCESSING', detail='settled', phase='settled',
                               quiet=True, funding_tx_hash=pm.TX, funded_wei=str(pm.EXACT), credited_usd=credited)

    def sync(self, ramp):
        from ramps import ve_send
        with self.captureOnCommitCallbacks(execute=True):
            return ve_send.sync(ramp)

    def later(self, **delta):
        moment = timezone.now() + timedelta(**delta)
        return mock.patch('django.utils.timezone.now', return_value=moment)

    def recheck(self):
        return payouts.recheck(SmartAccountPayout.objects.get(), operator='ops')


VE = dict(pm.VE_ON, RELAY_API_KEY='fake-relay-key')


@override_settings(**VE)
class SignedRatePagoMovilTests(VeBase):
    def test_the_floor_is_stored_with_the_order(self):
        self.run_rule()
        terms = self.ramps().get().metadata['ve_send']['funding_terms']
        self.assertEqual(Decimal(terms['fx_floor']), Decimal('38.8'))

    def test_under_the_floor_waits_untold_then_is_parked_and_told_once(self):
        ramp = self.settled()
        self.rate('30')
        ramp = self.sync(ramp)
        self.provider.create_payout.assert_not_called()
        self.assertEqual((ramp.status_detail, ramp.metadata['ve_send']['phase']), ('waiting_rate', 'settled'))
        self.assertEqual(held_notices(self.owner), 0)
        with self.later(hours=1, minutes=1):
            ramp = self.sync(ramp)
            payouts.mirror_ramp_payouts()
        self.provider.create_payout.assert_not_called()
        self.assertEqual(ramp.status_detail, 'needs_review:fx_quote_outside_authorization')
        self.assertEqual(SmartAccountPayout.objects.get().status, 'review')
        self.assertEqual(held_notices(self.owner), 1)

    def test_exactly_the_floor_pays(self):
        ramp = self.settled()
        self.rate('38.8')
        self.sync(ramp)
        self.provider.create_payout.assert_called_once()
        paid = self.provider.create_payout.call_args.kwargs['amount_ves']
        self.assertEqual(paid, Decimal('49.40') * Decimal('38.8'))

    def test_a_provider_fee_cannot_take_it_under_the_floor(self):
        ramp = self.settled()
        self.rate('38.9')
        self.provider.preview.side_effect = lambda ves: {'total': str(ves / Decimal('38.9') + 2)}
        self.sync(ramp)
        self.provider.create_payout.assert_not_called()

    def test_a_rate_that_recovers_inside_the_window_pays_untold(self):
        ramp = self.settled()
        self.rate('30')
        ramp = self.sync(ramp)
        self.rate('39')
        self.sync(ramp)
        self.provider.create_payout.assert_called_once()
        self.assertEqual(held_notices(self.owner), 0)

    def test_ops_continue_pays_only_once_the_rate_is_back(self):
        ramp = self.settled()
        self.rate('30')
        self.sync(ramp)
        with self.later(hours=1, minutes=1):
            self.sync(ramp)
            self.recheck()
            parked = self.sync(ramp)
            self.assertEqual(parked.status_detail, 'needs_review:fx_quote_outside_authorization')
            self.assertEqual(held_notices(self.owner), 1)
            self.provider.create_payout.assert_not_called()
            self.rate('39')
            self.recheck()
            self.sync(ramp)
        self.provider.create_payout.assert_called_once()
        self.assertGreaterEqual(self.provider.create_payout.call_args.kwargs['amount_ves'] / Decimal('49.40'),
                                Decimal('38.8'))

    def test_ops_cannot_continue_outside_the_signed_terms(self):
        ramp = self.settled()
        self.rate('30')
        self.sync(ramp)
        with self.later(hours=1, minutes=1):
            self.sync(ramp)
        with mock.patch('smart_account.payouts.ramp_funding_problem', return_value='payout_ref_changed'):
            with self.assertRaises(payouts.RecheckRefused):
                self.recheck()
        self.provider.create_payout.assert_not_called()

    def test_ops_cannot_change_who_a_signed_payment_pays(self):
        from ramps import ve_send
        ramp = self.settled()
        ve_send._update(ramp.pk, phase='payout_failed', detail='needs_review:payout_failed:refused')
        with self.assertRaises(ve_send.VeSendError):
            ve_send.update_beneficiary(ramp, {'cedula': 'V00000001', 'phone': '584120000000', 'bank_code': '0102'},
                                       operator='ops', reviewed_key='', reviewed_revision=0)
        ramp.refresh_from_db()
        self.assertEqual(ramp.metadata['ve_send']['beneficiary']['phone'], '584141234567')

    def test_a_provider_cost_under_the_floor_is_refused_before_funding(self):
        # The raw rate passes; what would really be paid does not.
        self.provider.preview.side_effect = lambda ves: {'total': str(ves / Decimal('40') + 3)}
        self.assertEqual(self.run_rule()['errors'], 1)      # asked again inside the slot
        self.assertEqual(self.last_run().error, 'fx_rate_below_limit')
        self.assertEqual((self.ramps().count(), self.relay.call_count), (0, 0))

    def test_a_retry_not_yet_funded_is_not_sent_under_the_rate(self):
        self.relay.side_effect = RuntimeError('a worker that died')     # the order is left open
        self.run_rule()
        self.assertEqual(self.ramps().get().status, 'PENDING')
        self.relay.side_effect = None
        with mock.patch('smart_account.payouts.reference_ves_rate', return_value=Decimal('30')):
            self.assertEqual(self.run_rule()['errors'], 1)
        self.assertEqual(self.last_run().error, 'fx_rate_below_limit')
        self.assertEqual(self.ramps().get().status, 'FAILED')
        self.assertEqual(self.relay.call_count, 1)


@override_settings(**VE)
class OrdersMadeByTheCodeInProductionTests(VeBase):
    """An order in flight at the deploy has no stored floor."""

    def legacy(self):
        ramp = self.settled()
        ramp.metadata['ve_send'].pop('funding_terms')
        ramp.save(update_fields=['metadata'])
        return ramp

    def test_it_is_held_to_its_authorizations_floor(self):
        ramp = self.legacy()
        self.rate('30')
        self.assertEqual(self.sync(ramp).status_detail, 'waiting_rate')
        self.provider.create_payout.assert_not_called()

    def test_a_floor_signed_after_it_is_not_its_floor(self):
        ramp = self.legacy()
        SmartAccountStandingAuthorization.objects.update(
            authorized_at=timezone.now() + timedelta(minutes=5), reference_fx_rate=Decimal('20'))
        self.rate('30')
        self.assertEqual(self.sync(ramp).status_detail, 'needs_review:contract_funding_terms_changed')
        self.provider.create_payout.assert_not_called()

    def test_a_rule_without_a_rate_is_refused_before_funding(self):
        SmartAccountStandingAuthorization.objects.update(reference_fx_rate=None)
        self.assertEqual(self.run_rule()['skipped'], 1)
        self.assertEqual((self.last_run().error, self.relay.call_count), ('fx_floor_unsigned', 0))


class RecheckAdminTests(InfiniaCase):
    def action(self, user):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from smart_account.admin import SmartAccountPayoutAdmin
        request = RequestFactory().post('/')
        request.user, request.session = user, {}
        request._messages = FallbackStorage(request)
        model_admin = SmartAccountPayoutAdmin(SmartAccountPayout, admin.AdminSite())
        return model_admin, request

    def test_superusers_only_and_every_use_is_recorded(self):
        from django.contrib.auth import get_user_model
        staff = get_user_model().objects.create_user(username='staff', password='x', firebase_uid='uid-staff',
                                                     is_staff=True)
        boss = get_user_model().objects.create_user(username='boss', password='x', firebase_uid='uid-boss',
                                                    is_staff=True, is_superuser=True)
        self.parked_for_rate()
        model_admin, request = self.action(staff)
        self.assertNotIn('recheck_payouts', model_admin.get_actions(request))
        model_admin, request = self.action(boss)
        self.assertIn('recheck_payouts', model_admin.get_actions(request))
        self.world.rates['MXN'] = ABOVE
        self.step(model_admin.recheck_payouts, request, SmartAccountPayout.objects.all())
        self.assertEqual(LogEntry.objects.get(object_id=str(self.payout().pk)).user, boss)
        self.assertEqual(self.finish().status, 'paid')


# --------------------------------------------------------------------- 2

class LaterProvenTests(InfiniaCase):
    def parked_by_delay(self, code):
        self.assertEqual((self.bridge().failure_code, self.journey().stage, self.journey().failure_code),
                         (code, 'needs_review', 'bridge_not_delivered'))

    def proven_and_paid(self):
        self.deliver()
        self.workers()
        self.assertEqual(self.finish().status, 'paid')
        self.assertEqual((len(self.world.transfers), len(self.world.payouts)), (1, 1))

    def test_unreported_then_proven(self):
        self.make_rule()
        self.assertEqual(self.run_rules()['sent'], 1)       # mined; the mirror lags
        self.age(4500)
        self.bridges()
        self.journeys()
        self.parked_by_delay('contract_funding_unreported')
        self.mirror_chain()
        self.proven_and_paid()

    def test_a_receipt_that_came_late(self):
        self.make_rule()
        self.send_run()
        self.age(4500)
        with mock.patch('payment_accounts.bridge_chain.final_receipt', return_value=None):
            self.bridges()
        self.journeys()
        self.parked_by_delay('source_confirmation_delayed')
        self.proven_and_paid()

    def test_a_relay_outage_then_delivered(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.age(4500)
        with mock.patch('payment_accounts.contract_funding.settlement_request',
                        side_effect=contract_funding.RelayError('down')):
            self.bridges()
        self.journeys()
        self.parked_by_delay('relay_settlement_delayed')
        self.proven_and_paid()

    def delayed_then_delivered(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.age(4500)
        self.bridges()
        self.journeys()
        self.parked_by_delay('relay_settlement_delayed')
        self.deliver()

    def test_changed_terms_stay_parked(self):
        self.delayed_then_delivered()
        with mock.patch('smart_account.payouts.execution_problem', return_value='authorization_changed'):
            self.workers()
        self.journeys()
        self.assertEqual(self.journey().failure_code, contract_funding.TERMS_CHANGED)
        self.assert_nothing_moved()

    def test_a_changed_payee_stays_parked(self):
        self.delayed_then_delivered()
        self.destination.provider_data = dict(self.destination.provider_data, validation={'status': 'ERROR'})
        self.destination.save(update_fields=['provider_data'])
        self.workers()
        self.journeys()
        self.assertEqual(self.journey().failure_code, contract_funding.PAYEE_CHANGED)
        self.assert_nothing_moved()

    def test_a_bank_still_answering_is_a_delay_and_not_another_payee(self):
        self.delayed_then_delivered()
        with mock.patch('smart_account.payouts.funded_payee_problem', return_value=payouts.PAYEE_PENDING), \
                mock.patch('smart_account.payouts.refresh_funded_payee') as asked:
            self.mirror()
            self.assertEqual((self.journey().stage, self.journey().failure_code),
                             ('needs_review', 'bridge_not_delivered'))
            # Not a lookup a minute while the bank is slow.
            contract_funding.reopen_delayed(self.bridge().pk)
            self.assertEqual(asked.call_count, 1)
        self.assert_nothing_moved()
        cache.clear()
        self.mirror()
        self.assertEqual(self.finish().status, 'paid')

    def test_a_banned_owner_stays_parked(self):
        self.delayed_then_delivered()
        ban(self.user)
        self.workers()
        self.journeys()
        self.assertEqual(self.journey().failure_code, contract_funding.NOT_PAYABLE)
        self.assert_nothing_moved()

    def test_accounts_that_no_longer_pass_stay_parked(self):
        self.delayed_then_delivered()
        self.profile.status = 'suspended'
        self.profile.save(update_fields=['status'])
        self.workers()
        self.assertEqual(self.journey().stage, 'needs_review')
        self.assert_nothing_moved()

    def test_it_never_races_the_owners_own_payment(self):
        self.delayed_then_delivered()
        flow = MoneyFlow.objects.create(confio_account=self.personal, kind='fund', status='processing',
                                        source_asset='MXN', source_amount=10, target_asset='USDT_BSC', metadata={})
        own = InfiniaJourney.objects.create(
            money_flow=flow, confio_account=self.personal, request_id=uuid.uuid4(), direction='to_wallet',
            local_account=self.local, crypto_account=self.crypto, minimum_fx_output=1, wallet_address=self.wallet)
        self.mirror()
        self.assertEqual(self.journey().stage, 'needs_review')      # two live ones would wait on each other
        InfiniaJourney.objects.filter(pk=own.pk).update(stage='completed')
        self.mirror()
        self.assertEqual(self.finish().status, 'paid')


# --------------------------------------------------------------------- 3

class RecoveryAddressTests(InfiniaCase):
    def test_the_quote_names_the_owners_wallet_and_still_refunds_to_the_contract(self):
        self.make_rule()
        self.send_run()
        body = self.world.orders[-1]['body']
        self.assertEqual((body['recoveryAddress'], body['refundTo'], body['strict']),
                         (self.wallet, self.contract, True))

    def test_what_relay_recorded_is_checked(self):
        self.make_rule()
        self.send_run()
        self.world.recovery_recorded = '0x' + '66' * 20
        self.deliver()
        self.assertIn('recoveryAddress', self.alert_text())

    def test_a_stuck_refund_says_who_can_sign(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.depositor = self.wallet
        self.world.relay_fails('MANUAL_REFUND_REQUIRED')
        self.workers()
        self.assertIn(self.wallet, self.alert_text())
        self.assertIn('contrato no puede firmar', self.alert_text())
        self.assertNotIn('pedir el reembolso al contrato', self.alert_text())

    def test_a_stuck_refund_only_the_contract_could_sign_goes_to_relay_support(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.depositor = self.contract
        self.world.relay_fails('MANUAL_REFUND_REQUIRED')
        self.workers()
        self.assertIn('soporte de Relay', self.alert_text())


@override_settings(**VE)
class RecoveryPagoMovilTests(VeBase):
    def test_the_quote_names_the_owners_wallet(self):
        self.run_rule()
        ramp = self.ramps().get()
        bodies = []

        def request(client, method, path, body=None, params=None):
            bodies.append(body)
            raise contract_funding.RelayError('stop here')
        with mock.patch('payment_accounts.relay.RelayClient._request', request):
            from ramps.ve_pagomovil import VePagoMovilError
            with self.assertRaises(VePagoMovilError):
                self.real_target(ramp)
        self.assertEqual((bodies[0]['recoveryAddress'], bodies[0]['refundTo']),
                         (self.owner.wallet, self.address))
        self.assertIs(bodies[0]['strict'], True)        # one-time, as an Infinia run's


# --------------------------------------------------------------------- 4

class FeeDebtTests(InfiniaCase):
    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX')
    def test_automated_debts_never_park_an_incoming_deposit(self):
        from payment_accounts import auto_payin, infinia_fee_policy
        from payment_accounts.models import AutomaticPayin, LedgerEntry
        self.make_rule()
        self.send_run()
        self.to_paid()
        for number in range(4):
            flow = MoneyFlow.objects.create(
                confio_account=self.personal, kind='withdraw', status='succeeded', source_asset='USDT_BSC',
                source_amount=50, target_asset='USDC_POL', metadata={'contract_funding': {'run': 9000 + number}})
            InfiniaFeeDebt.objects.create(source_flow=flow, amount_usd=Decimal('0.5'))
        self.world.account_assets['acct-usdc'] = 'USDC'
        self.world.rates['USDC'] = Decimal('1') / Decimal('18.5')
        entry = LedgerEntry.objects.create(
            provider='infinia', provider_entry_id=uuid.uuid4().hex, financial_account=self.local,
            direction='credit', asset='MXN', amount=Decimal('50'), occurred_at=timezone.now(),
            provider_data={'third_party': {'type': 'FIAT'}, 'operation': {'type': 'PAYIN'}})
        row = AutomaticPayin.objects.create(entry=entry, status='pending')

        def route(*args, **kwargs):
            units = int(args[2]) * 10 ** 12
            return [{'messenger': 'relay', 'amountOutMin': str(units * 99 // 100), 'amountOut': str(units)}]
        with mock.patch('payment_accounts.bridge_routing.quote_routes', side_effect=route), \
                mock.patch('cusd_plus.cusd_vault.preview_mint_wei', side_effect=lambda g: SimpleNamespace(
                    fee_bps=90, net_wei=g * 9910 // 10000, fee_wei=g * 90 // 10000)), \
                mock.patch('payment_accounts.auto_payin.is_automatic_payin', return_value=True), \
                mock.patch('payment_accounts.auto_payin.has_unallocated_debit', return_value=False), \
                mock.patch('payment_accounts.payin_admission.assess',
                           return_value=SimpleNamespace(allowed=True, reason='')), \
                mock.patch('payment_accounts.payin_admission.decision', return_value=(True, '', None, None)), \
                mock.patch('payment_accounts.payin_admission.require_admitted'), \
                mock.patch('payment_accounts.payin_hold.require_conversion_allowed'), \
                mock.patch('payment_accounts.payin_hold.hold_required', return_value=False), \
                mock.patch('payment_accounts.payin_hold.record_open_consent'), \
                mock.patch('payment_accounts.activation.collector', return_value='0x' + 'c0' * 20):
            self.assertEqual((auto_payin.process(row.pk).status, auto_payin.process(row.pk).reason), ('started', ''))
            outgoing = infinia_fee_policy.price(self.local, 'to_bank', destination=self.destination)
        debts = InfiniaFeeDebt.objects.all()
        self.assertEqual(debts.count(), 5)
        self.assertFalse(debts.exclude(reserved_flow__isnull=True, settled_tx_hash='').exists())      # carried
        self.assertEqual(Decimal(outgoing['debt_usd']), Decimal('2.5'))     # the next signed send collects them


# --------------------------------------------------------------------- 5, 6

@override_settings(**VE)
class LostReportTests(VeBase):
    def lost(self):
        self.run_rule()
        SmartAccountRuleRun.objects.update(status='ok', tx_hash=pm.TX)
        SmartAccountPayout.objects.update(status='onchain_sent')        # mirrored; the report was lost
        return self.ramps().get()

    def test_the_mirror_reports_the_hash_again(self):
        ramp = self.lost()
        payouts.mirror_ramp_payouts()
        ramp.refresh_from_db()
        self.assertEqual(ramp.metadata['ve_send']['funding_tx_hashes'], [pm.TX])

    def test_the_task_that_follows_money_out_does_it_with_the_product_off(self):
        ramp = self.lost()
        with override_settings(SMART_ACCOUNT_ENABLED=False), \
                mock.patch('smart_account.reconcile.reconcile', return_value={}):
            cache.clear()
            tasks.reconcile_events()
        ramp.refresh_from_db()
        self.assertEqual(ramp.metadata['ve_send']['funding_tx_hashes'], [pm.TX])

    def test_ops_continue_works_from_a_parked_unreported_order(self):
        from ramps import ve_send
        ramp = self.lost()
        ve_send._update(ramp.pk, status='PROCESSING', detail='needs_review:funding_not_found', quiet=True)
        self.recheck()
        with mock.patch('ramps.ve_send._check_receipt', return_value=(pm.TX, pm.EXACT)):
            ramp = self.sync(ramp)
        self.assertEqual((ramp.metadata['ve_send']['phase'], ramp.status_detail), ('funded', 'funded'))
        with mock.patch('ramps.pagoasap_send.settle', return_value=ve_send.Settlement('review', reason='bridge')):
            self.sync(ramp)
        self.recheck()
        ramp.refresh_from_db()
        self.assertEqual(ramp.metadata['ve_send']['phase'], 'funded')


@override_settings(**VE)
class SettlementByFundingTests(VeBase):
    QUOTED, REGENERATED = '0x' + '01' * 32, '0x' + '02' * 32
    SWEEP, FILL = '0x' + '03' * 32, '0x' + '04' * 32
    RECIPIENT = '0x' + '9a' * 20

    def funded(self, deadline=None):
        from ramps import ve_send
        self.run_rule()
        SmartAccountPayout.objects.update(status='funded')
        deadline = deadline or int(timezone.now().timestamp()) + 600
        return ve_send._update(
            self.ramps().get().pk, status='PROCESSING', detail='funded', phase='funded', quiet=True,
            funding_tx_hash=pm.TX, funded_wei=str(pm.EXACT),
            bridge={'request_id': self.QUOTED, 'recipient': self.RECIPIENT, 'amount_out': '49400000',
                    'amount_out_min': '48500000', 'deadline': deadline,
                    'response': {'protocol': {'v2': {'paymentDetails': {
                        'chainId': 'bnb', 'currency': w.USDT, 'amount': str(pm.EXACT),
                        'depository': w.DEPOSITORY}}}}})

    def relay_and_chain(self, gift=0, out=49_400_000, published=True):
        def request(client, method, path, body=None, params=None):
            if path == '/requests/v3':
                rows = [{'id': self.REGENERATED, 'status': 'success',
                         'depositAddress': {'address': pm.DEPOSIT, 'depositTxHash': pm.TX}}]
                return {'requests': rows if published else []}
            if params['requestId'] == self.QUOTED:
                return {'status': 'waiting'}
            return {'status': 'success', 'originChainId': 56, 'destinationChainId': 137,
                    'inTxHashes': [self.SWEEP], 'txHashes': [self.FILL]}

        def receipt(tx, number, log):
            return {'transactionHash': tx, 'status': '0x1', 'blockNumber': hex(number), 'transactionIndex': '0x0',
                    'logs': [dict(log, transactionHash=tx, logIndex='0x0')]}
        receipts = {
            pm.TX: receipt(pm.TX, 100, w.transfer_log(w.USDT, pm.CUSD, pm.DEPOSIT, pm.EXACT)),
            self.SWEEP: receipt(self.SWEEP, 101, w.transfer_log(w.USDT, pm.DEPOSIT, w.DEPOSITORY, pm.EXACT + gift)),
            self.FILL: receipt(self.FILL, 9, w.transfer_log(w.USDC, w.SOLVER, self.RECIPIENT, out)),
        }
        return (mock.patch('payment_accounts.relay.RelayClient._request', request),
                mock.patch('payment_accounts.bridge_chain.final_receipt', side_effect=lambda c, tx: receipts.get(tx)))

    def settle(self, ramp, **world):
        relay, chain = self.relay_and_chain(**world)
        with relay, chain:
            return self.sync(ramp)

    def test_a_regenerated_request_settles(self):
        ramp = self.settle(self.funded())
        self.assertEqual((ramp.status_detail, ramp.metadata['ve_send']['credited_usd']), ('settled', '49.4'))

    def test_a_larger_sweep_settles_and_never_pays_over_the_signed_amount(self):
        ramp = self.settle(self.funded(), gift=100 * 10 ** 18, out=149_150_000)
        self.assertEqual((ramp.status_detail, ramp.metadata['ve_send']['credited_usd']), ('settled', '49.4'))
        self.sync(ramp)
        self.assertLessEqual(self.provider.create_payout.call_args.kwargs['amount_ves'], Decimal('50') * 40)

    def test_a_delivery_larger_than_its_sweep_explains_is_not_attributed(self):
        ramp = self.settle(self.funded(), out=99_000_000)
        self.assertEqual(ramp.status_detail, 'needs_review:settlement:delivery_amount_unattributable')

    def test_a_delay_is_still_followed_after_review(self):
        from ramps import ve_send
        ramp = self.funded(deadline=int(timezone.now().timestamp()) - 4000)
        ramp = self.settle(ramp, published=False)
        self.assertEqual(ramp.status_detail, 'needs_review:settlement:relay_settlement_delayed')
        self.assertTrue(ve_send.due_for_sync(ramp))
        self.assertEqual(self.settle(ramp).status_detail, 'settled')


# --------------------------------------------------------------------- 7

@override_settings(**VE)
class BannedOwnerPagoMovilTests(VeBase):
    def test_a_banned_owner_opens_nothing(self):
        ban(self.owner)
        self.assertEqual(self.run_rule()['waiting'], 1)      # a ban may be lifted: a wait
        self.assertEqual(self.last_run().error, 'account_suspended')
        self.assertEqual((self.ramps().count(), self.relay.call_count), (0, 0))

    def test_a_disabled_owner_opens_nothing(self):
        type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.run_rule()['waiting'], 1)
        self.assertEqual((self.last_run().error, self.relay.call_count), ('account_unavailable', 0))

    def test_banned_after_funding_is_not_dispatched_until_ops_continue_a_cleared_one(self):
        ramp = self.settled()
        ban(self.owner)
        ramp = self.sync(ramp)
        self.provider.create_payout.assert_not_called()
        self.assertEqual(ramp.status_detail, 'needs_review:contract_funding_not_payable')
        with self.assertRaises(payouts.RecheckRefused):
            self.recheck()
        lift(self.owner)
        self.recheck()
        self.sync(ramp)
        self.provider.create_payout.assert_called_once()

    def test_a_replay_is_a_dispatch_too(self):
        from ramps.pagoasap_client import PagoAsapAmbiguousError
        ramp = self.settled()
        self.provider.create_payout.side_effect = PagoAsapAmbiguousError('no answer')
        ramp = self.sync(ramp)
        ban(self.owner)
        with self.later(minutes=11):
            ramp = self.sync(ramp)
        self.assertEqual(self.provider.create_payout.call_count, 1)
        self.assertTrue(ramp.status_detail.startswith('needs_review:payout_unknown'))


class BannedOwnerInfiniaTests(InfiniaCase):
    def test_banned_after_funding_neither_converts_nor_pays(self):
        self.funded()
        ban(self.user)
        self.workers()
        self.assert_nothing_moved()
        self.assertEqual((self.journey().failure_code, self.payout().status),
                         (contract_funding.NOT_PAYABLE, 'review'))
        with self.assertRaises(payouts.RecheckRefused):
            self.recheck()

    def test_banned_after_conversion_is_not_paid_out(self):
        self.funded()
        self.journeys()
        self.credit_conversion()
        ban(self.user)
        self.workers()
        self.assertEqual(self.world.payouts, [])
        self.assertIn('en la cuenta local', self.alert_text())
        lift(self.user)
        self.recheck()
        self.journeys()
        self.workers()
        self.assertEqual((self.payout().status, len(self.world.transfers), len(self.world.payouts)), ('paid', 1, 1))


class BannedOwnerSendAndBuyTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner, self.payee = self.make_user('owner'), self.make_user('payee')
        self.account = self.make_account(self.owner)
        self.address = self.account.contract_address.lower()
        self.fund(pm.CUSD, self.address, 500 * pm.WAD)
        self.slot = timezone.now().replace(microsecond=0) - timedelta(minutes=3)
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 0

    def rule(self, kind, **fields):
        self.chain.rules[(self.address, 1)] = {
            'kind': kind, 'active': True, 'frequency': 'weekly', 'amount_usd_wei': 25 * pm.WAD,
            'payee': self.payee.wallet, 'next_run_at': int(self.slot.timestamp())}
        return SmartAccountRule.objects.create(
            smart_account=self.account, kind=kind, state='onchain', active=True, onchain_id=1, token_in=pm.CUSD,
            amount=Decimal('25.00'), frequency='weekly', scheduled_for=self.slot, next_run_at=self.slot, **fields)

    def send_rule(self):
        auth = SmartAccountStandingAuthorization.objects.create(
            kind='send', user=self.owner, payee_address=self.payee.wallet, amount_usd=25, frequency='weekly',
            face_required=False,
            binding_hash=payouts.send_binding_hash(self.address, self.payee.wallet, Decimal('25.00'), 'weekly'))
        return self.rule('send', payee_user=self.payee, payee_address=self.payee.wallet, standing_authorization=auth)

    def refused_and_untouched(self, rule, code):
        with mock.patch('smart_account.relayer.send_relayer_call') as relay, \
                mock.patch('smart_account.notifications.rule_run'):
            self.assertEqual(automation.run_rules()['skipped'], 1)
        relay.assert_not_called()
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual((run.status, run.error), ('skipped', code))
        rule.refresh_from_db()
        self.assertEqual((rule.active, rule.deactivated_reason, rule.scheduled_for), (True, '', self.slot))

    def test_a_banned_owners_send_does_not_run_and_withdraw_stays_open(self):
        rule = self.send_rule()
        ban(self.owner)
        self.refused_and_untouched(rule, 'account_suspended')
        with mock.patch('smart_account.services._resolve_units',
                        return_value=(('dollar', 'cUSD', pm.CUSD, 18), pm.WAD)), \
                mock.patch('smart_account.services._token_usd', return_value=Decimal('1')):
            self.assertTrue(services.prepare_withdraw(self.viewer(self.owner), 'cusd', '1').calls)

    def test_a_disabled_owners_send_does_not_run(self):
        rule = self.send_rule()
        type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False)
        self.refused_and_untouched(rule, 'account_unavailable')

    def test_a_banned_owners_buy_does_not_run(self):
        rule = self.rule('buy', token_out='0x' + '77' * 20)
        ban(self.owner)
        self.refused_and_untouched(rule, 'account_suspended')

    def test_a_disabled_owners_buy_does_not_run(self):
        rule = self.rule('buy', token_out='0x' + '77' * 20)
        type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False)
        self.refused_and_untouched(rule, 'account_unavailable')


# --------------------------------------------------------------------- 8

class ReleaseSafetyTests(InfiniaCase):
    def test_every_combination_of_rails_and_flags_is_fail_closed(self):
        switches = [name for name in INFINIA_SWITCHES if name not in ('LOCAL_MONEY_METHODS', 'RELAY_API_KEY')]
        named_lists = ('', 'pagoasap', 'infinia', 'infinia,pagoasap,co_breb,ar_cvu')
        listed = ('', 'mx_clabe', 'br_pix', 've_pagomovil', 'co_breb,ar_cvu,br_qr',
                  'mx_clabe,br_pix,ve_pagomovil,co_breb,ar_cvu,unknown')
        for rails, verified, named, key, ve_on, polygon, off in itertools.product(
                listed, (False, True), named_lists, ('', ' ', 'k'), (False, True), ('', '0x' + '9a' * 20),
                [None, *switches]):
            values = dict({name: name != off for name in switches}, SMART_ACCOUNT_PAYOUT_RAILS=rails,
                          SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=verified, RELAY_API_KEY=key,
                          SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS=named, VE_PAGOMOVIL_SEND_ENABLED=ve_on,
                          PAGOASAP_DEPOSIT_ADDRESS_POLYGON=polygon)
            with override_settings(**values):
                allowed = set()
                if key.strip() and verified and off is None:
                    allowed |= {'mx_clabe', 'br_pix'}
                if key.strip() and 'pagoasap' in named and ve_on and polygon:
                    allowed.add('ve_pagomovil')
                self.assertEqual(set(offer.payout_rails()), allowed & set(rails.split(',')), values)

    @override_settings(SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=False, SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe')
    def test_unverified_with_a_rail_and_a_key_offers_nothing_infinia(self):
        self.assertEqual((offer.payout_rails(), offer.payout_rail_options()), ([], []))

    def test_unverified_deactivates_nothing(self):
        rule = self.make_rule()
        with override_settings(SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=False):
            self.assertEqual(payouts.deactivate_changed_rules(), 0)
            self.run_rules()
        rule.refresh_from_db()
        self.assertEqual((rule.active, rule.deactivated_reason, rule.scheduled_for), (True, '', self.slot))
        self.assertEqual(self.run_rules()['sent'], 1)

    def test_money_already_out_is_followed_to_paid_with_every_flag_off(self):
        self.make_rule()
        self.send_run()
        with override_settings(SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=False, SMART_ACCOUNT_PAYOUT_RAILS='',
                               SMART_ACCOUNT_ENABLED=False):
            self.assertEqual(self.to_paid().status, 'paid')

    def test_money_out_while_the_key_is_missing_pays_when_it_is_back(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.age(4500)
        with override_settings(RELAY_API_KEY=''):
            self.bridges()
            self.journeys()
        self.assertEqual(self.journey().stage, 'needs_review')
        self.deliver()
        self.workers()
        self.assertEqual(self.finish().status, 'paid')


# -------------------------------------------------------------------- 10

class NothingBroadcastClosesTests(InfiniaCase):
    def test_a_reverting_simulation_does_not_hold_the_owners_accounts(self):
        self.make_rule()
        self.world.revert_simulation = True
        self.run_rules()
        self.assertEqual((self.bridge().status, self.payout().status), ('expired', 'cancelled'))
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(confio_account=self.personal)).exists())
        contract_funding.require_free(self.personal, self.local, self.crypto)

    def test_one_that_may_have_been_broadcast_is_never_closed(self):
        self.make_rule()
        real = self.world.rpc

        def rpc(chain, method, params):
            if method == 'eth_sendRawTransaction':
                raise w.Revert('timeout after the node took it')
            return real(chain, method, params)
        with mock.patch.object(self.world, 'rpc', side_effect=rpc):
            self.run_rules()
        self.assertEqual(SmartAccountRelayTx.objects.get().status, 'signed')
        self.assertEqual((self.bridge().status, self.journey().stage), ('submitted', 'awaiting_credit'))


@override_settings(**VE)
class NothingBroadcastClosesPagoMovilTests(VeBase):
    def test_a_refused_call_closes_the_order_quietly(self):
        self.relay.side_effect = relayer.RelayError('simulation_reverted')
        self.run_rule()
        ramp = self.ramps().get()
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'payout_not_sent'))
        self.assertFalse(Notification.objects.filter(user=self.owner, notification_type='RAMP_FAILED').exists())


# -------------------------------------------------------------------- 11

class SwitchedOffWaitsTests(InfiniaCase):
    def waits_then_pays(self, **off):
        self.make_rule()
        with override_settings(**off):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.rule.refresh_from_db()
        run = self.last_run()
        self.assertEqual((run.status, run.notified_at, self.rule.scheduled_for), ('pending', None, self.slot))
        self.assertEqual(self.run_rules()['sent'], 1)

    def test_no_key(self):
        self.waits_then_pays(RELAY_API_KEY='')

    def test_rail_off(self):
        self.waits_then_pays(SMART_ACCOUNT_PAYOUT_RAILS='')

    def test_not_verified(self):
        self.waits_then_pays(SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=False)

    def test_a_provider_switch(self):
        self.waits_then_pays(PAYMENT_BRIDGE_BSC_ENABLED=False)

    def test_off_for_the_whole_slot_is_told_and_alerted(self):
        self.make_rule()
        with override_settings(RELAY_API_KEY=''):
            self.run_rules()
            self.advance(24 * HOUR + 60)
            self.run_rules()
        run = self.last_run()
        self.assertEqual(run.status, 'failed')
        self.assertTrue(run.message.startswith(automation.NOT_PAID.rstrip('.')))
        self.assertIn('se agotó su plazo', self.alert_text())


@override_settings(**VE)
class SwitchedOffWaitsPagoMovilTests(VeBase):
    def waits_then_pays(self, **off):
        with override_settings(**off):
            self.assertEqual(self.run_rule()['waiting'], 1)
        self.assertEqual(self.last_run().status, 'pending')
        self.assertEqual(self.run_rule()['sent'], 1)

    def test_no_key(self):
        self.waits_then_pays(RELAY_API_KEY='')

    def test_sends_off(self):
        self.waits_then_pays(VE_PAGOMOVIL_SEND_ENABLED=False)

    def test_the_providers_key_missing(self):
        from ramps.ve_pagomovil import VePagoMovilError
        self.quote.side_effect = VePagoMovilError('Los envíos en bolívares no están disponibles por ahora.')
        self.assertEqual(self.run_rule()['waiting'], 1)
        self.quote.side_effect = None
        self.assertEqual(self.run_rule()['sent'], 1)


# -------------------------------------------------------------------- 12

class SponsorLockTests(InfiniaCase):
    def broadcasts(self):
        return self.world.count('BSC', 'eth_sendRawTransaction')

    def test_a_lock_lost_during_the_checks_signs_nothing(self):
        self.make_rule()
        real = automation._Send.before_sign

        def slow(send):
            real(send)
            cache.set(relayer.NONCE_LOCK, 'another-signer', 15)
        with mock.patch.object(automation._Send, 'before_sign', slow):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.broadcasts(), self.world.signed, SmartAccountRelayTx.objects.count()), (0, {}, 0))

    def test_a_lock_lost_while_claiming_records_and_broadcasts_nothing(self):
        self.make_rule()
        real = automation._Send.claim

        def slow(send, tx_hash):
            real(send, tx_hash)
            cache.set(relayer.NONCE_LOCK, 'another-signer', 15)
        with mock.patch.object(automation._Send, 'claim', slow):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.broadcasts(), SmartAccountRelayTx.objects.count()), (0, 0))
        self.assertNotEqual(self.last_run().status, 'sent')

    def test_a_lock_lost_after_the_commit_broadcasts_nothing_and_the_slot_retries(self):
        self.make_rule()
        real = relayer._hold
        calls = []

        def hold(token, seconds):
            real(token, seconds)
            calls.append(seconds)
            if len(calls) == 3:     # the last one inside the claim's transaction
                cache.set(relayer.NONCE_LOCK, 'another-signer', 15)     # someone released it for us
        with mock.patch('smart_account.relayer._hold', side_effect=hold):
            self.run_rules()
        self.assertEqual(self.broadcasts(), 0)
        self.assertEqual(SmartAccountRelayTx.objects.get().status, 'signed')
        self.assertEqual(self.bridge().status, 'submitted')     # not closed: the row says it may land
        SmartAccountRelayTx.objects.update(updated_at=timezone.now() - timedelta(minutes=5))
        self.step(tasks.reconcile_relay_txs)
        self.assertEqual(self.run_rules()['sent'], 1)
        self.assertEqual(self.broadcasts(), 1)

    def test_the_lock_outlives_the_broadcast(self):
        self.make_rule()
        real, held = self.world.rpc, []

        def rpc(chain, method, params):
            if method == 'eth_sendRawTransaction':
                held.append(cache.get(relayer.NONCE_LOCK))
            return real(chain, method, params)
        with mock.patch.object(self.world, 'rpc', side_effect=rpc):
            self.run_rules()
        self.assertEqual(held, ['token'])
        # Renewed while it runs (test_release_audit3), not taken for minutes.
        self.assertLess(relayer.RENEW_SECONDS * 2, relayer.STEP_HOLD_SECONDS)


@override_settings(**SETTINGS)
class LockWaitTests(Waits, InfiniaPayoutSteps, TransactionTestCase):
    def step(self, fn, *args, **kwargs):
        cache.clear()
        return fn(*args, **kwargs)

    def test_a_row_lock_never_outwaits_the_sponsor_lock(self):
        import threading
        from smart_account.models import SmartAccount
        self.make_rule()
        held, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold():
            with transaction.atomic():
                SmartAccount.objects.select_for_update().get(pk=self.account.pk)
                held.set()
                release.wait(PATIENCE)
        holder = Worker(hold)
        self.assertTrue(held.wait(PATIENCE))
        with mock.patch('smart_account.relayer.CLAIM_LOCK_WAIT', '300ms'):
            sender = Worker(automation.run_rules)
            sender.join(6)
            self.assertFalse(sender.is_alive(), 'waited for a row lock inside the nonce lock')
        release.set()
        holder.done()
        self.assertEqual(sender.done()['waiting'], 1)
        self.assertEqual(SmartAccountRuleRun.objects.get().error, 'claim_busy')
        self.assertFalse(SmartAccountRelayTx.objects.exists())

    # ---------------------------------------------------------------- 13

    def test_the_event_waits_for_the_payout_row_and_keeps_what_was_written(self):
        import threading
        self.make_rule()
        self.run_rules()
        payout = SmartAccountPayout.objects.get()
        event = SimpleNamespace(tx_hash=self.last_run().tx_hash, args={
            'id': 1, 'destination': payout.deposit_address, 'usdtOut': str(w.WAD)})
        written, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def write():
            with transaction.atomic():
                SmartAccountPayout.objects.filter(pk=payout.pk).update(status='review')
                written.set()
                release.wait(PATIENCE)

        def apply():
            with transaction.atomic():
                reconcile._payout_sent(self.account, event)
        writer = Worker(write)
        self.assertTrue(written.wait(PATIENCE))
        applier = Worker(apply)
        self.assert_waits(applier)
        release.set()
        writer.done()
        applier.done()
        self.assertEqual(SmartAccountPayout.objects.get().status, 'review')


# ---------------------------------------- live callers of the same code

@override_settings(RELAY_API_KEY='')
class PaymentIntentPathUnchangedTests(InfiniaCase):
    """A payment approved in the chat (intent_rails, payment_intents) is a
    wallet bridge and journey: none of the contract rules reach it."""
    prepared = wallet.WalletFundedSendTests.prepared
    signed = wallet.WalletFundedSendTests.signed

    def test_it_is_priced_bridged_and_judged_as_before(self):
        from payment_accounts import intent_rails
        bridge, _journey = self.prepared()
        body = self.world.orders[-1]['body']
        self.assertEqual((body['refundTo'], 'recoveryAddress' in body, 'strict' in body),
                         (self.wallet, False, False))
        shown = SimpleNamespace(destination=self.destination, minimum_local=Decimal('300'))
        self.assertTrue(intent_rails.bridged_minimum_ok(self.personal, shown, bridge))

        self.signed(bridge)
        fill, units = self.world.relay_fills()
        self.bridges()
        self.credit_usdc(fill, units)
        self.bridges()
        InfiniaJourney.objects.update(minimum_fx_output=Decimal('300'))
        self.world.rates['MXN'] = Decimal('10')
        self.journeys()
        row = InfiniaJourney.objects.select_related('money_flow').get()
        self.assertEqual((row.stage, row.failure_code), ('needs_review', 'fx_quote_outside_authorization'))
        self.assertNotIn('fx_wait_since', row.money_flow.metadata)
        self.assertEqual(held_notices(self.user), 0)
        self.assertEqual(self.world.count('relay', '/requests/v3'), 0)


# -------------------------------------------------------------------- 14

class MirrorTaskTests(InfiniaCase):
    def test_mirrors_run_when_the_event_scan_fails(self):
        with mock.patch('smart_account.reconcile.reconcile', side_effect=RuntimeError('rpc down')), \
                mock.patch('smart_account.infinia_payouts.mirror_payouts') as journeys, \
                mock.patch('smart_account.payouts.mirror_ramp_payouts') as ramps:
            cache.clear()
            with self.assertRaises(RuntimeError):
                tasks.reconcile_events()
        journeys.assert_called_once()
        ramps.assert_called_once()
