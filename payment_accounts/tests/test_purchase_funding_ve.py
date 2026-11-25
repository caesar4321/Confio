"""A Venezuelan store purchase paid by Pago Móvil from the account (payment_accounts.purchase_funding_ve),
on the real code: agent_tasks.account_pay, smart_account.purchases, the spender pull through the relayer,
ramps.ve_send's contract-funded send. The chains and Relay are the test world; Pago ASAP's API, its
settlement proof on Polygon and the browser leg's service calls are faked."""
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from agent_tasks import account_pay, runner
from agent_tasks.models import AgentTask
from payment_accounts import payment_intents, purchase_funding_ve
from payment_accounts.models import PaymentIntent
from payment_accounts.tests import test_purchase_funding as mx
from payment_accounts.tests.test_purchase_funding import SPENDER, PurchaseWorld, event
from ramps import pagoasap_send, ve_send
from ramps.models import RampTransaction
from smart_account import abi, purchases
from smart_account.models import SmartAccountCardSpender, SmartAccountRelayTx
from smart_account.tests import infinia_world as w
from smart_account.tests.infinia_base import SETTINGS, InfiniaPayoutSteps

WAD = 10 ** 18
EXACT_VES = '1500.00'
TOTAL_USD = Decimal('12.00')
PAYEE = {'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0134'}
POLYGON = '0x' + '7a' * 20
QUOTE = {'usd_amount': '12.00', 'usdt_amount': '12.000000', 'confio_fee_usd': '0.00',
         'processor_fee_usd': '0.50', 'estimated_ves': EXACT_VES, 'exact_ves': EXACT_VES, 'rate': '125.0000'}


class FakePagoAsap:
    """Pago ASAP's partner API as the send adapter uses it."""

    def __init__(self):
        self.is_configured = True
        self.cost = Decimal('11.00')
        self.balance = Decimal('1000')
        self.created = []
        self.state = {'state': 'completed', 'reference': '00123456', 'amountVES': EXACT_VES,
                      'originBankCode': '0156'}

    def preview(self, ves):
        return {'total': str(self.cost)}

    def balances(self):
        return {'USD': self.balance}

    def rate(self, *_):
        return Decimal('125')

    def create_payout(self, **kwargs):
        self.created.append(kwargs)
        return f'intent-{len(self.created)}'

    def payout(self, intent_id):
        return dict(self.state)


@override_settings(**SETTINGS, SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS=SPENDER, BSC_SPONSOR_ADDRESS=w.SPONSOR,
                   SMART_ACCOUNT_CARD_RULES_ENABLED=True, CUSD_CONVERSION_FEE_ENABLED=False,
                   PAGOASAP_DEPOSIT_ADDRESS_POLYGON=POLYGON, VE_PURCHASE_PAYOUT_WAIT_MINUTES=30)
class VenezuelanPurchasePaidByTheAccountTests(InfiniaPayoutSteps, TestCase):
    switch_on = mx.PurchasePaidByTheAccountTests.switch_on

    def setUp(self):
        with mock.patch.object(w, 'World', PurchaseWorld):
            super().setUp()
        self.posted = mock.Mock(return_value=1)
        self.pagoasap = FakePagoAsap()
        self.store_paid = mock.Mock()
        self.store_unpaid = mock.Mock()
        for patcher in (
                mock.patch('agent_tasks.notes.post', self.posted),
                mock.patch.object(pagoasap_send, '_client', return_value=self.pagoasap),
                mock.patch.object(pagoasap_send, 'quote_exact_now', side_effect=lambda ves: dict(QUOTE)),
                mock.patch.object(pagoasap_send, '_require_payable'),
                # Relay's delivery on Polygon is pagoasap_send.settle's own (tested there): given here.
                mock.patch.object(pagoasap_send, 'settle', side_effect=self.delivered),
                mock.patch('agent_tasks.service.store_paid', self.store_paid, create=True),
                mock.patch('agent_tasks.service.store_unpaid', self.store_unpaid, create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        SmartAccountCardSpender.objects.create(address=SPENDER, allowed=True, label=purchases.RULE_LABEL)

    def delivered(self, ramp):
        return ve_send.Settlement('delivered', credited_usd='11.93', evidence='0x' + 'ee' * 32)

    # ── fixtures ───────────────────────────────────────────────────────

    def order(self, *, total_usd=TOTAL_USD, approved=True, held=False):
        intent = PaymentIntent(
            confio_account=self.personal, user=self.user, created_by='assistant', source='agent_checkout',
            rail_method_id='ve_pagomovil_send', family='ramp_order', provider='pagoasap', destination=None,
            params={**PAYEE, 'holder_name': 'Tienda Caracas', 'exact_ves': EXACT_VES},
            payee_name='Tienda Caracas', payee_level='unverified', payee_account='584141234567 · V12345678',
            # As read_pagomovil makes it: the provider's estimate (above), the exact bolívares as the minimum.
            institution='Banesco', amount_exact=True, amount_local=Decimal(EXACT_VES) + Decimal('3.17'),
            minimum_local=Decimal(EXACT_VES), currency='VES', total_usd=total_usd, fee_usd=Decimal('0.50'),
            estimated_return_usd=Decimal('0.00'), rate=Decimal('125.0000'),
            expires_at=timezone.now() + timedelta(minutes=5))
        intent.display_hash = payment_intents.display_hash(intent)
        intent.save()
        self.task = AgentTask.objects.create(
            account=self.personal, user=self.user, goal='harina', site='tienda.example.com.ve', country='VE',
            # The first attempt pays from the pay-first step itself (working, phase 'paying'); a held one resumes
            # as awaiting_code.
            state='awaiting_code' if held else 'working', lease=uuid.uuid4(),
            lease_until=timezone.now() + timedelta(minutes=3), checkout_at=timezone.now(),
            phase='ordering' if held else 'paying',
            # As agent_tasks.pagomovil.pay_first leaves it: `approved` cleared, `pay_first` set.
            order={'item': 'Harina', 'total': 'Bs 1.500,00', 'amount': EXACT_VES,
                   'approved': None, 'pay_first': bool(approved)})
        return intent

    def pay(self, intent, **kwargs):
        step = runner.Step(AgentTask.objects.get(pk=self.task.pk), self.task.lease)
        kwargs.setdefault('code', PAYEE['phone'])
        kwargs.setdefault('extra', {'amount_local': EXACT_VES})
        return self.step(account_pay.pay, step, intent, **kwargs)

    def ramp(self):
        return RampTransaction.objects.get(metadata__ve_send__funding_terms__purpose='purchase')

    def sync(self, times=1):
        for _ in range(times):
            ramp = self.step(ve_send.sync, self.ramp())
        return ramp

    # ── the account pays ───────────────────────────────────────────────

    def test_the_spender_pulls_exactly_the_purchase_and_the_store_gets_exactly_the_bolivares(self):
        rule = self.switch_on()
        intent = self.order()
        self.assertTrue(self.pay(intent))
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason, task.payment_intent_id), ('payment_ready', 'account', intent.pk))
        ramp = self.ramp()
        section = ve_send._section(ramp)
        units = int(TOTAL_USD * WAD)
        self.assertEqual((section['funding_sender'], int(section['deposit_wei'])), (SPENDER, units))
        self.assertEqual(ramp.actor_address, self.contract, 'a Relay refund returns to the account')
        self.assertEqual(section['estimate']['exact_ves'], EXACT_VES)
        intent.refresh_from_db()
        self.assertEqual((intent.state, intent.order_ref), ('submitted', str(ramp.internal_id)))
        row = SmartAccountRelayTx.objects.get(kind=abi.PURCHASE_KIND)
        account, rule_id, out, to, ref = abi.decode_purchase_pull(row.calldata)
        self.assertEqual((account, rule_id, out, to), (self.contract, rule.onchain_id, units,
                                                       section['deposit_address']))
        self.assertEqual(ref, purchases.ref_for(intent.request_id))
        self.assertEqual(section['funding_tx_hashes'], [row.signed_tx_hash.lower()])
        self.assertEqual(self.world.deposits_to(section['deposit_address'])[-1][1:],
                         (units, w.word_address(SPENDER)))

        ramp = self.sync()          # proven by the pull's own events
        self.assertEqual((ramp.status, ve_send._phase(ramp)), ('PROCESSING', 'funded'))
        self.assertEqual(ve_send._section(ramp)['purchase_proof']['rule_id'], rule.onchain_id)
        ramp = self.sync(3)          # settled, paid out, polled
        self.assertEqual(len(self.pagoasap.created), 1)
        sent = self.pagoasap.created[0]
        self.assertEqual((sent['amount_ves'], sent['cedula'], sent['bank_code'], sent['phone']),
                         (Decimal(EXACT_VES), PAYEE['cedula'], PAYEE['bank_code'], '04141234567'))
        self.assertEqual(ramp.status, 'COMPLETED')
        self.store_paid.assert_called_once()
        args, kwargs = self.store_paid.call_args
        self.assertEqual(args, (self.task.pk,))
        self.assertEqual((kwargs['reference'], kwargs['paid_ves'], kwargs['origin_bank']),
                         ('00123456', EXACT_VES, '0156'))
        self.assertTrue(kwargs['paid_at'])
        # Once: the webhook, the poller and the sweep all ask again.
        self.step(ve_send.sync, ramp)
        purchase_funding_ve.sweep()
        self.assertEqual(self.store_paid.call_count, 1)
        self.store_unpaid.assert_not_called()

    def test_a_refused_payout_after_the_pull_is_an_owed_refund_and_the_store_unpaid(self):
        self.switch_on()
        self.assertTrue(self.pay(self.order()))
        self.pagoasap.state = {'state': 'failed', 'reason': 'invalid_beneficiary'}
        ramp = self.sync(4)
        section = ve_send._section(ramp)
        self.assertEqual(ve_send._phase(ramp), 'payout_failed')
        # What left the account (the gross its cap counted), with what Relay delivered beside it.
        gross = Decimal(int(section['purchase_proof']['gross'])) / WAD
        self.assertEqual(Decimal(section['refund_owed']['usd']), gross)
        self.assertEqual(section['refund_owed']['delivered_usd'], '11.93')
        self.assertGreater(gross, Decimal('11.93'))
        self.assertEqual(section['refund_owed']['to'], self.contract)
        self.assertTrue(ramp.status_detail.startswith(purchase_funding_ve.REFUND_OWED))
        self.store_unpaid.assert_called_once_with(self.task.pk, why='payout_failed')
        self.store_paid.assert_not_called()
        self.assertIn('devolución pendiente', self.alert_text())
        # Never a late payment to the store once the task was told.
        with self.assertRaises(ve_send.VeSendError):
            ve_send.retry_payout(ramp, operator='ops', reviewed_key=section['payout_key'],
                                 reviewed_revision=0)
        purchase_funding_ve.sweep()
        self.assertEqual(self.store_unpaid.call_count, 1)

    def test_a_payout_that_cannot_be_made_in_time_is_given_up_with_the_refund_owed(self):
        self.switch_on()
        self.assertTrue(self.pay(self.order()))
        self.pagoasap.balance = Decimal('0')
        ramp = self.sync(3)
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail), ('settled', 'waiting_balance'))
        self.assertEqual(self.pagoasap.created, [])
        self.advance(31 * 60)
        ramp = self.sync()
        self.assertEqual(ve_send._phase(ramp), 'payout_failed')
        self.assertIn('refund_owed', ve_send._section(ramp))
        self.store_unpaid.assert_called_once_with(self.task.pk, why='payout_failed')
        self.assertEqual(self.pagoasap.created, [], 'never paid after it was given up')

    def test_a_held_purchase_resumed_as_awaiting_code_still_pays(self):
        self.switch_on()
        self.assertTrue(self.pay(self.order(held=True)))
        self.assertEqual(AgentTask.objects.get(pk=self.task.pk).state, 'payment_ready')

    def test_a_purchase_parked_for_review_is_never_paid_late_and_the_task_is_told(self):
        self.switch_on()
        self.assertTrue(self.pay(self.order()))
        ramp = self.sync(2)
        ve_send._update(ramp.pk, phase='payout_review', detail='needs_review:funding_not_found')
        purchase_funding_ve.sweep()                     # first seen: the store's wait starts
        self.store_unpaid.assert_not_called()
        self.advance(61 * 60)
        purchase_funding_ve.sweep()
        ramp = self.ramp()
        section = ve_send._section(ramp)
        self.assertEqual(ve_send._phase(ramp), 'payout_failed')
        self.assertIn('refund_owed', section)
        self.store_unpaid.assert_called_once_with(self.task.pk, why='payout_failed')
        self.assertEqual(self.pagoasap.created, [], 'never paid after it was given up')

    def test_a_refused_service_answer_is_not_marked_told(self):
        self.switch_on()
        self.assertTrue(self.pay(self.order()))
        self.store_paid.return_value = False
        ramp = self.sync(4)
        self.assertNotIn('store_told', ve_send._section(ramp))
        self.store_paid.return_value = True
        purchase_funding_ve.sweep()
        self.assertIn('store_told', ve_send._section(self.ramp()))

    def test_a_pago_movil_hold_lasts_minutes(self):
        held = account_pay.new_hold('584141234567', {'amount_local': EXACT_VES}, 've_pagomovil_send')
        until = timezone.datetime.fromisoformat(held['until']) - timezone.datetime.fromisoformat(held['since'])
        self.assertLessEqual(until, timedelta(minutes=15))

    def test_a_dropped_pull_closes_the_order_and_tells_the_task(self):
        self.switch_on()
        intent = self.order()
        self.world.hold_broadcast = True
        self.assertTrue(self.pay(intent))
        self.assertTrue(purchase_funding_ve.may_land(self.ramp()))
        ramp = self.sync()
        self.assertEqual(ramp.status, 'PENDING', 'followed while it may land')
        SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).update(status='dropped')
        ramp = self.sync()
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', purchase_funding_ve.PULL_NOT_LANDED))
        self.store_unpaid.assert_called_once_with(self.task.pk, why=purchase_funding_ve.PULL_NOT_LANDED)
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')
        self.assertNotIn('refund_owed', ve_send._section(ramp), 'nothing left the account')

    def test_a_pull_that_paid_anything_else_is_never_paid_out(self):
        self.switch_on()
        intent = self.order()
        other = '0x' + '0d' * 20

        def elsewhere(logs):
            logs[-1] = event(SPENDER, 'Forwarded', abi.FORWARDED_FIELDS,
                             [self.contract, 2, other, int(TOTAL_USD * WAD), purchases.ref_for(intent.request_id)])
            return logs
        self.world.tamper = elsewhere
        self.assertTrue(self.pay(intent))
        ramp = self.sync(3)
        self.assertEqual(ve_send._phase(ramp), 'payout_review')
        self.assertEqual(ve_send._section(ramp)['funding_terms_problem'], 'forwarded_mismatch')
        self.assertEqual(self.pagoasap.created, [])
        self.store_paid.assert_not_called()

    # ── before anything moves ──────────────────────────────────────────

    def test_without_the_rule_it_waits_and_nothing_is_reserved(self):
        intent = self.order()
        self.assertTrue(self.pay(intent))
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason, task.order['account_wait']['code']),
                         ('needs_person', 'account_wait', 'no_rule'))
        self.assertAlmostEqual((task.wait_until - timezone.now()).total_seconds(), 15 * 60, delta=60,
                               msg="a store's Pago Móvil is paid before its order: the checkout waits minutes")
        self.assertFalse(RampTransaction.objects.exists())
        self.assertFalse(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).exists())

    def test_a_price_above_the_approved_dollars_reserves_nothing_and_tries_again(self):
        self.switch_on()
        intent = self.order()
        with mock.patch.object(pagoasap_send, 'quote_exact_now', return_value=dict(QUOTE, usd_amount='12.40')):
            self.assertTrue(self.pay(intent))
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.order['pay_hold']['tries']), ('awaiting_code', 1))
        self.assertFalse(RampTransaction.objects.exists())

    def test_a_route_that_cannot_cover_the_bolivares_closes_the_order_unsent(self):
        self.switch_on()
        intent = self.order()
        self.pagoasap.cost = Decimal('50.00')
        self.assertTrue(self.pay(intent))
        self.assertEqual(self.ramp().status, 'FAILED')
        self.assertFalse(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).exists())
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.order['pay_hold']['tries']), ('awaiting_code', 1))
        purchase_funding_ve.sweep()
        self.store_unpaid.assert_not_called()       # the step retries it: not the task's payment

    def test_a_simulated_refusal_closes_the_order_before_anything_is_signed(self):
        self.switch_on()
        intent = self.order()
        with mock.patch.object(PurchaseWorld, 'pull', side_effect=w.Revert('CapExceeded')):
            self.assertTrue(self.pay(intent))
        self.assertEqual(self.ramp().status, 'FAILED')
        self.assertFalse(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).exists())
        self.assertEqual(AgentTask.objects.get(pk=self.task.pk).state, 'awaiting_code')

    def test_an_order_the_person_did_not_approve_is_never_paid(self):
        self.switch_on()
        intent = self.order(approved=False)
        self.assertTrue(self.pay(intent))
        self.assertFalse(RampTransaction.objects.exists())
        self.assertFalse(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).exists())


class PullUnitsTests(TestCase):
    def test_the_conversion_fee_is_the_pulls_own_exit(self):
        intent = SimpleNamespace(total_usd=Decimal('12.00'), rail_method_id='ve_pagomovil_send')
        with mock.patch.object(ve_send, 'confio_amounts', return_value=(12 * WAD, 11_892_000 * 10 ** 12)):
            self.assertEqual(account_pay.units_of(intent), 11_892_000 * 10 ** 12)
        with mock.patch.object(ve_send, 'confio_amounts', side_effect=ve_send.VeSendError('x')):
            with self.assertRaises(ValueError):
                account_pay.units_of(intent)

    def test_origin_bank_only_a_four_digit_code(self):
        self.assertEqual(pagoasap_send.origin_bank_of({'originBankCode': '0156'}), '0156')
        self.assertEqual(pagoasap_send.origin_bank_of({'origin': {'bankCode': '0105'}}), '0105')
        self.assertEqual(pagoasap_send.origin_bank_of({'originBank': '100% Banco'}), '')
        self.assertEqual(pagoasap_send.origin_bank_of({}), '')
