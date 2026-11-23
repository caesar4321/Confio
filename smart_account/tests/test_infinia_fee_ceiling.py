"""Founder decision 36 (2026-11-22): the processor's fixed Pix / CLABE fee is
outside the rule's bridge-cost limit, and the fee the owner signed is the
most a run ever charges. Fake values only."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings

from notifications.models import Notification
from payment_accounts import contract_funding, infinia_fee_policy
from payment_accounts.models import InfiniaFeeDebt, MoneyFlow, PaymentBridgeTransfer
from smart_account import payouts, reconcile, services
from smart_account.models import (
    SmartAccountPayout, SmartAccountRule, SmartAccountStandingAuthorization,
)

from . import infinia_world as w
from .infinia_base import InfiniaPayoutCase
from .test_pagomovil_payouts import VE_ON, PagoMovilBase


@override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX,BR')
class MinimumWithTheFeeOutsideTests(InfiniaPayoutCase):
    """On the cost model of BRIDGING.md: US$0.043 + 0.19%."""
    below, above = '3.31', '3.32'
    fee = Decimal('0.50')

    def test_just_below_is_refused_before_face(self):
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare(self.below)
        self.assertEqual(raised.exception.code, 'bridge_cost_above_limit')
        message = raised.exception.message
        self.assertIn('más del 1,5%', message)
        self.assertNotIn('(1,5%)', message)
        self.assertIn('desde unos US$4.00', message)
        self.assertIn(f'US${self.fee:.2f} por pago va aparte', message)
        self.face.assert_not_called()
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())

    def test_just_above_pays_and_owes_the_fee(self):
        rule = self.make_rule(self.above)
        self.assertEqual(rule.standing_authorization.max_processor_fee_usd, self.fee)
        self.send_run()
        details = self.bridge().quote.money_flow.metadata['contract_funding']
        self.assertLessEqual(details['cost_bps'], 150)
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(InfiniaFeeDebt.objects.get().amount_usd, self.fee)

    def test_the_bridges_fixed_part_stays_inside_the_limit(self):
        self.world.relay_fixed = Decimal('0.14')
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare('10.00')
        self.assertEqual(raised.exception.code, 'bridge_cost_above_limit')

    def test_the_providers_minimum_is_still_refused(self):
        self.world.fx_error = (400, {'message': 'below minimum'})
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare('10.00')
        self.assertEqual(raised.exception.code, 'fx_quote_refused')
        self.face.assert_not_called()

    def test_an_amount_that_cannot_cover_the_fee_is_refused(self):
        self.world.relay_fixed = Decimal(0)
        with mock.patch('payment_accounts.contract_funding.processor_fee', return_value={'total_usd': '9.90'}):
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare('10.00')       # 9.91 USDT leaves, 9.89 arrives
        self.assertEqual(raised.exception.code, 'amount_too_small')
        self.face.assert_not_called()

    def test_the_suggested_amount_really_passes(self):
        for fixed in ('0.043', '0.09', '0.25'):
            self.world.relay_fixed = Decimal(fixed)
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare('2.00')
            amount = raised.exception.message.rsplit('US$', 1)[1].rstrip('.')
            self.assertEqual(self.prepare(amount).kind, 'smart_rule', fixed)


class MinimumFromPlusTests(MinimumWithTheFeeOutsideTests):
    token = w.VAULT


class MinimumByPixTests(MinimumWithTheFeeOutsideTests):
    rail = 'br_pix'
    fee = Decimal('0.10')


class MinimumByPixFromPlusTests(MinimumByPixTests):
    token = w.VAULT


@override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX,BR', INFINIA_PROCESSING_FEE_TIER=1)
class SignedCeilingTests(InfiniaPayoutCase):
    signed, raised_to, lowered_to = Decimal('0.45'), Decimal('0.50'), Decimal('0.25')

    def nothing_left_the_account(self):
        self.assertEqual((PaymentBridgeTransfer.objects.count(), SmartAccountPayout.objects.count(),
                          self.world.signed, InfiniaFeeDebt.objects.count()), (0, 0, {}, 0))

    def test_the_owner_sees_it_before_signing(self):
        batch = self.prepare()
        shown = [line for line in batch.summary
                 if contract_funding.fee_text(self.signed) in line and 'Comisión del procesador' in line]
        self.assertEqual(len(shown), 1)
        self.assertIn('por pago', shown[0])
        self.assertTrue(any('próxima transferencia de tu cuenta local que firmes' in line for line in batch.summary))
        self.assertTrue(any('firmes la regla de nuevo' in line for line in batch.summary))

    def test_it_is_part_of_what_face_confirmed(self):
        with mock.patch('smart_account.payouts.claim_face', wraps=payouts.claim_face) as claimed:
            self.prepare()
        authorization = SmartAccountStandingAuthorization.objects.get()
        digest = payouts.binding_hash(self.destination, Decimal(self.amount), 'monthly', self.signed)
        self.assertEqual(authorization.binding_hash, digest)
        self.assertNotEqual(digest, payouts.binding_hash(self.destination, Decimal(self.amount), 'monthly'))
        _viewer, _namespace, identifier, payload = claimed.call_args.args[:4]
        self.assertEqual(identifier, payouts.face_identifier(digest, authorization.pk))
        self.assertEqual(Decimal(payload['max_processor_fee_usd']), self.signed)

    def test_another_tariff_at_prepare_is_another_face_check(self):
        self.prepare()
        with override_settings(INFINIA_PROCESSING_FEE_TIER=0):
            self.prepare()
        rows = SmartAccountStandingAuthorization.objects.order_by('pk')
        self.assertEqual([row.max_processor_fee_usd for row in rows], [self.signed, self.raised_to])
        self.assertNotEqual(rows[0].binding_hash, rows[1].binding_hash)

    def test_a_changed_stored_ceiling_stops_the_rule(self):
        self.make_rule()
        SmartAccountStandingAuthorization.objects.update(max_processor_fee_usd=Decimal('9'))
        self.run_rules()
        self.nothing_left_the_account()
        self.assertEqual(self.last_run().error, 'destination_changed')
        self.assertFalse(SmartAccountRule.objects.get().active)

    def test_a_raised_tariff_skips_tells_and_asks_for_a_signature(self):
        rule = self.make_rule()
        with override_settings(INFINIA_PROCESSING_FEE_TIER=0):
            self.assertEqual(self.run_rules()['skipped'], 1)
            self.run_rules()        # the slot is over: nothing is asked or told twice
        self.nothing_left_the_account()
        run = self.last_run()
        self.assertEqual((run.status, run.error), ('skipped', 'processor_fee_increased'))
        self.assertIn('fírmala de nuevo', run.message)
        self.assertIn(contract_funding.fee_text(self.raised_to), run.message)
        self.assertIn(contract_funding.fee_text(self.signed), run.message)
        self.assertLess(len(run.message), 200)
        self.assertEqual([n.message for n in Notification.objects.filter(user=self.user)
                          if (n.data or {}).get('smart_account_event') == 'rule_skipped'], [run.message])
        rule.refresh_from_db()
        self.assertTrue(rule.active)        # it runs again by itself if the tariff returns
        self.assertGreater(rule.scheduled_for, self.slot)

    def test_signed_again_the_new_fee_is_the_ceiling(self):
        rule = self.make_rule()
        old = rule.standing_authorization
        with override_settings(INFINIA_PROCESSING_FEE_TIER=0):
            self.prepare(rule_id=str(rule.internal_id))
            draft = SmartAccountRule.objects.get(state='draft')
            event = SimpleNamespace(args={'id': 1}, tx_hash='0x' + 'ab' * 32)
            with mock.patch('smart_account.reconcile._draft_rule', return_value=draft):
                reconcile._rule_updated(self.account, event)
            rule.refresh_from_db()
            old.refresh_from_db()
            self.assertEqual(rule.standing_authorization.max_processor_fee_usd, self.raised_to)
            self.assertIsNotNone(old.revoked_at)
            self.send_run()
            self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(InfiniaFeeDebt.objects.get().amount_usd, self.raised_to)

    def test_a_fee_switched_on_after_signing_is_a_raise(self):
        with override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES=''):
            self.make_rule()
        self.run_rules()
        self.nothing_left_the_account()
        self.assertEqual(self.last_run().error, 'processor_fee_increased')

    def test_an_authorization_without_a_ceiling_authorizes_no_fee(self):
        with override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES=''):
            self.make_rule()
        SmartAccountStandingAuthorization.objects.update(max_processor_fee_usd=None)
        self.run_rules()
        self.nothing_left_the_account()
        self.assertEqual(self.last_run().error, 'processor_fee_increased')

    def test_a_lowered_tariff_charges_the_lower(self):
        self.make_rule()
        with override_settings(INFINIA_PROCESSING_FEE_TIER=5):
            self.send_run()
            self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(InfiniaFeeDebt.objects.get().amount_usd, self.lowered_to)

    def test_a_tariff_raised_after_the_run_was_sent_changes_nothing(self):
        self.make_rule()
        self.send_run()
        with override_settings(INFINIA_PROCESSING_FEE_TIER=0):
            self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(InfiniaFeeDebt.objects.get().amount_usd, self.signed)

    def test_the_transaction_checks_the_ceiling_again(self):
        self.make_rule()
        real = contract_funding.price

        def moved(**kwargs):
            priced = real(**kwargs)
            priced.fee = dict(priced.fee, total_usd='9')
            return priced
        with mock.patch('payment_accounts.contract_funding.price', side_effect=moved):
            self.run_rules()
        self.nothing_left_the_account()
        self.assertEqual(self.last_run().error, 'processor_fee_increased')

    @override_settings(INFINIA_MAINTENANCE_FEES_ENABLED=True)
    def test_maintenance_and_older_debt_are_never_folded_in(self):
        flow = MoneyFlow.objects.create(confio_account=self.personal, kind='withdraw', source_asset='USDT_BSC',
                                        source_amount=1, target_asset=self.local.asset)
        InfiniaFeeDebt.objects.create(source_flow=flow, amount_usd=Decimal('3'))
        with mock.patch('payment_accounts.infinia_maintenance.quoted_charges', return_value=([], Decimal('0.10'))):
            signed_send = infinia_fee_policy.price(self.local, 'to_bank', destination=self.destination)
            self.assertEqual(Decimal(signed_send['total_usd']), self.signed + Decimal('3.10'))
            rule = self.make_rule()
            self.assertEqual(rule.standing_authorization.max_processor_fee_usd, self.signed)
            self.send_run()
        fee = self.bridge().quote.money_flow.metadata['contract_funding']['fee']
        self.assertEqual(Decimal(fee['total_usd']), self.signed)


class SignedCeilingFromPlusTests(SignedCeilingTests):
    token = w.VAULT


class SignedCeilingByPixTests(SignedCeilingTests):
    rail = 'br_pix'
    signed, raised_to, lowered_to = Decimal('0.075'), Decimal('0.10'), Decimal('0.025')


class SignedCeilingByPixFromPlusTests(SignedCeilingByPixTests):
    token = w.VAULT


@override_settings(**VE_ON, INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX,BR,VE', INFINIA_PROCESSING_FEE_TIER=0)
class PagoMovilIsUnchangedTests(PagoMovilBase):
    def test_no_fee_line_no_ceiling_and_the_same_binding(self):
        destination = self.destination()
        batch = self.prepare(destination)
        self.assertEqual(len(batch.summary), 6)      # what and when, to whom, holder, what comes out, local amount, floor
        self.assertFalse(any('Comisión' in line for line in batch.summary))
        authorization = SmartAccountStandingAuthorization.objects.get()
        self.assertIsNone(authorization.max_processor_fee_usd)
        self.assertEqual(authorization.binding_hash,
                         payouts.pagomovil_binding_hash(destination, Decimal('50.00'), 'monthly'))
        self.assertNotIn('max_processor_fee_usd', self.face_mock.call_args[0][3])
