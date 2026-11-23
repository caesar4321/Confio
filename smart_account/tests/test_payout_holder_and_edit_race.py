"""Where the destination checks of a payment rule meet its money path: the
signed holder pin, a run's own holder check, a rejection Enviar's shared row
forgets, an edit that gets past the prepare check, and who a delivery notice
names. Fake values only."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from blockchain.models import SponsoredBatch
from payment_accounts import local_money
from payment_accounts.models import PayoutDestination
from smart_account import abi, notifications, payouts, reconcile, services
from smart_account.models import (
    SmartAccountEvent, SmartAccountPagoMovilDestination, SmartAccountPayout, SmartAccountPreparedAction,
    SmartAccountRule, SmartAccountRuleRun, SmartAccountStandingAuthorization,
)

from . import infinia_world as w
from .base import CUSD, WAD
from .infinia_base import CLABE, InfiniaPayoutCase
from .test_pagomovil_payouts import DEPOSIT, TX, VE_ON, RunBase, quote

LOOKUP_ON = dict(INFINIA_ACCOUNT_VALIDATION_ENABLED=True)
OTHER_CLABE = '012180000000001234'      # fake
PAYEE_REVIEW = 'contract_funding_payee_changed'
TERMS_REVIEW = 'contract_funding_terms_changed'


def land_update(case, batch, tx_hash):
    """The prepared update as the relay consumed it: its batch carries the tx."""
    action = SmartAccountPreparedAction.objects.filter(kind='smart_rule').order_by('-pk').first()
    sponsored = SponsoredBatch.objects.create(
        user=action.user, user_bsc_address=action.signer_address, kind='smart_rule', num_calls=1, calls_json='[]',
        tx_hash=tx_hash, gas_limit=1, max_fee_wei='1', status='confirmed')
    SmartAccountPreparedAction.objects.filter(pk=action.pk).update(consumed=True, sponsored_batch=sponsored)


def updated_terms(batch):
    name, args = abi.decode_call(batch.calls[0]['data'])
    assert name == 'updateRule'
    _kind, _frequency, token_in, _out, _payee, ref, amount_wei, _first = args[1]
    return token_in.lower(), '0x' + bytes(ref).hex(), int(amount_wei)


class HolderCase(InfiniaPayoutCase):
    def answer(self, status, name='', hours=0):
        return {'id': 'v1' if status != 'DISABLED' else '', 'status': status, 'holder_name': name,
                'checked_at': (timezone.now() - timedelta(hours=hours)).isoformat()}

    def set_answer(self, status, name='', hours=0):
        row = PayoutDestination.objects.get(pk=self.destination.pk)
        row.holder_name = name if status == 'SUCCESSFUL' else ''
        row.provider_data = dict(row.provider_data, validation=self.answer(status, name, hours))
        row.save()
        self.destination = row

    def stored(self):
        return PayoutDestination.objects.get(pk=self.destination.pk).provider_data

    def lookup(self, status, name=''):
        return mock.patch('payment_accounts.local_money._validate', return_value=self.answer(status, name))

    def unsent_order(self):
        self.make_rule()
        self.leave_order_open()
        self.assertEqual(self.bridge().status, 'submitted')

    def delivered_order(self):
        self.make_rule()
        self.send_run()
        self.deliver()

    def assert_payee_review(self):
        self.mirror()
        self.assertEqual((self.journey().stage, self.journey().failure_code), ('needs_review', PAYEE_REVIEW))
        self.assertEqual(self.payout().status, 'review')
        self.assertEqual(self.bridge().status, 'delivered')     # held for ops, never closed
        self.assertIsNotNone(self.bridge().provider_credit_id)


class SignedPinTests(HolderCase):
    """1. The signed pin is exactly what this prepare showed."""

    def prepared(self):
        self.prepare()
        return SmartAccountRule.objects.filter(state='draft').order_by('-pk').first().standing_authorization

    def pin(self, authorization):
        return (self.stored().get(payouts.RULE_HOLDERS_KEY) or {}).get(str(authorization.internal_id), '')

    def test_another_verified_holder_is_another_authorization(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        first = self.prepared()
        self.set_answer('SUCCESSFUL', 'Bia Prueba')
        second = self.prepared()
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual((self.pin(first), self.pin(second)),
                         (payouts._holder_digest('Ana Prueba'), payouts._holder_digest('Bia Prueba')))

    def test_shown_unverified_never_reuses_a_pinned_one(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        first = self.prepared()
        self.set_answer('DISABLED')
        second = self.prepared()
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(self.pin(second), '')

    def test_shown_verified_never_pins_one_signed_unverified(self):
        first = self.prepared()
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        second = self.prepared()
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual((self.pin(first), self.pin(second)), ('', payouts._holder_digest('Ana Prueba')))

    def test_an_exact_retry_still_costs_no_new_authorization(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.assertEqual(self.prepared().pk, self.prepared().pk)
        self.assertEqual(SmartAccountStandingAuthorization.objects.count(), 1)

    def test_the_rule_signed_second_runs(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.prepare()
        SmartAccountRule.objects.all().delete()
        self.set_answer('SUCCESSFUL', 'Bia Prueba')
        self.make_rule()
        self.send_run()


class NothingBroadcastHolderTests(HolderCase):
    """2. An order nothing was broadcast for is asked again, then judged."""

    def test_the_lookup_switched_on_rechecks_and_sends_the_same_order(self):
        self.unsent_order()
        order = self.bridge().pk
        with override_settings(**LOOKUP_ON), self.lookup('SUCCESSFUL', 'Ana Prueba') as asked:
            self.assertEqual(self.run_rules()['sent'], 1)
        asked.assert_called_once()
        self.assertEqual(self.bridge().pk, order)

    @override_settings(**LOOKUP_ON)
    def test_an_answer_past_its_ttl_rechecks_and_sends_the_same_order(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.unsent_order()
        order = self.bridge().pk
        self.set_answer('SUCCESSFUL', 'Ana Prueba', hours=30)
        with self.lookup('SUCCESSFUL', 'Ana Prueba'):
            self.assertEqual(self.run_rules()['sent'], 1)
        self.assertEqual(self.bridge().pk, order)

    @override_settings(**LOOKUP_ON)
    def test_a_changed_holder_is_never_paid_and_the_empty_order_closes(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.unsent_order()
        self.set_answer('SUCCESSFUL', 'Ana Prueba', hours=30)
        with self.lookup('SUCCESSFUL', 'Otra Persona'):
            self.run_rules()
        self.assertEqual((self.last_run().error, self.bridge().status, self.world.signed),
                         ('destination_changed', 'expired', {}))

    @override_settings(**LOOKUP_ON)
    def test_no_answer_waits_and_keeps_the_banks_earlier_answer(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.unsent_order()
        self.set_answer('SUCCESSFUL', 'Ana Prueba', hours=30)
        before = self.stored()['validation']
        with self.lookup('TEMPORARY_FAILURE'):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.last_run().error, self.bridge().status), ('holder_check_pending', 'submitted'))
        self.assertEqual(self.stored()['validation'], before)

    def test_an_unpinned_stale_rule_runs_without_rewriting_the_address_book(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba', hours=24 * 30)
        before = self.stored()['validation']
        self.make_rule()
        self.send_run()
        self.assertEqual(self.stored()['validation'], before)
        self.assertEqual(self.destination.__class__.objects.get(pk=self.destination.pk).holder_name, 'Ana Prueba')
        shown = self.journey().destination_snapshot['display_label']
        self.assertNotIn('Ana Prueba', shown)       # signed unverified, so never shown as the holder
        self.assertEqual(self.to_paid().status, 'paid')

    @override_settings(**LOOKUP_ON)
    def test_one_that_may_land_is_neither_asked_nor_judged_nor_closed(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        SmartAccountRuleRun.objects.update(status='failed')
        from smart_account.models import SmartAccountRelayTx
        SmartAccountRelayTx.objects.update(status='reorged')
        self.set_answer('SUCCESSFUL', 'Otra Persona', hours=30)
        with self.lookup('ERROR') as asked:
            self.assertEqual(self.run_rules()['waiting'], 1)
        asked.assert_not_called()
        self.assertEqual((self.last_run().error, self.bridge().status), ('payout_in_progress', 'submitted'))
        self.assertTrue(SmartAccountRule.objects.get().active)


class FundedHolderTests(HolderCase):
    """2. Money already out: never closed, never paid to a changed holder."""

    def test_a_changed_holder_after_funding_is_parked_before_conversion(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.delivered_order()
        self.set_answer('SUCCESSFUL', 'Otra Persona')
        self.journeys()
        self.assert_payee_review()
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))

    def test_a_changed_holder_after_conversion_is_parked_before_the_payout(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.delivered_order()
        self.journeys()
        self.assertEqual(len(self.world.transfers), 1)
        self.set_answer('SUCCESSFUL', 'Otra Persona')
        self.credit_conversion()
        self.journeys()
        self.assert_payee_review()
        self.assertEqual(self.world.payouts, [])
        self.assertIn('en la cuenta local', self.alert_text())

    @override_settings(**LOOKUP_ON)
    def test_an_answer_that_aged_in_flight_is_asked_again(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.delivered_order()
        self.set_answer('SUCCESSFUL', 'Ana Prueba', hours=30)
        with self.lookup('SUCCESSFUL', 'Ana Prueba') as asked:
            self.journeys()
        asked.assert_called_once()
        self.credit_conversion()
        self.journeys()
        self.workers()
        self.assertEqual(self.payout().status, 'paid')

    @override_settings(**LOOKUP_ON)
    def test_an_answer_that_aged_in_flight_and_names_another_is_parked(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.delivered_order()
        self.set_answer('SUCCESSFUL', 'Ana Prueba', hours=30)
        with self.lookup('SUCCESSFUL', 'Otra Persona'):
            self.journeys()
        self.assert_payee_review()
        self.assertEqual(self.world.transfers, [])

    @override_settings(**LOOKUP_ON)
    def test_no_answer_holds_the_money_then_stops_holding_the_owner(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.delivered_order()
        self.set_answer('SUCCESSFUL', 'Ana Prueba', hours=30)
        with self.lookup('TEMPORARY_FAILURE'):
            self.journeys()
            self.assertEqual((self.journey().stage, self.world.transfers), ('awaiting_credit', []))
            self.age(4300)
            self.journeys()
        self.assert_payee_review()
        from payment_accounts import contract_funding
        contract_funding.require_free(self.personal, self.local, self.crypto)

    def test_a_pinned_holder_that_cannot_be_confirmed_is_parked(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.delivered_order()
        self.set_answer('DISABLED')
        self.journeys()
        self.assert_payee_review()

    def test_a_key_the_bank_rejected_since_is_parked(self):
        self.delivered_order()
        self.set_answer('ERROR')
        self.journeys()
        self.assert_payee_review()

    def test_a_leg_created_but_not_submitted_stops_reserving_when_parked(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.delivered_order()
        self.journeys()
        self.credit_conversion()
        with mock.patch('payment_accounts.infinia_journeys.submit_money_operation'):     # the worker died here
            self.journeys()
        self.assertEqual(self.journey().payout_operation.status, 'created')
        self.set_answer('SUCCESSFUL', 'Otra Persona')
        self.journeys()
        self.assert_payee_review()
        self.assertEqual((self.journey().payout_operation.status, self.world.payouts), ('failed', []))
        from payment_accounts import contract_funding
        contract_funding.require_free(self.personal, self.local, self.crypto)

    def test_a_toggle_alone_does_not_stop_a_payment_signed_unverified(self):
        self.delivered_order()
        with override_settings(**LOOKUP_ON):
            self.journeys()
            self.credit_conversion()
            self.journeys()
            self.workers()
        self.assertEqual(self.payout().status, 'paid')


class RejectedKeyTests(HolderCase):
    """3. Enviar may rewrite ERROR as DISABLED; a run does not forget it."""

    def enviar(self):
        local_money.resolve_destination(self.personal, 'mx_clabe', CLABE)
        self.assertEqual(self.stored()['validation']['status'], 'DISABLED')

    def test_a_rejected_key_rewritten_disabled_does_not_run(self):
        self.make_rule()
        self.set_answer('ERROR')
        self.enviar()
        self.run_rules()
        self.assertEqual((self.last_run().error, self.world.signed), ('destination_unverified', {}))

    def test_a_rejection_recorded_before_this_code_is_kept_at_the_overwrite(self):
        self.make_rule()
        PayoutDestination.objects.filter(pk=self.destination.pk).update(
            provider_data=dict(self.stored(), validation=self.answer('ERROR')))
        self.enviar()
        self.run_rules()
        self.assertEqual((self.last_run().error, self.world.signed), ('destination_unverified', {}))

    def test_nor_is_it_signed_for_before_face(self):
        self.set_answer('ERROR')
        self.enviar()
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, 'payout_method_rejected')
        self.face.assert_not_called()

    def test_a_check_with_no_answer_in_between_does_not_forget_it(self):
        self.make_rule()
        self.set_answer('ERROR')
        self.set_answer('TEMPORARY_FAILURE')
        self.enviar()
        self.run_rules()
        self.assertEqual(self.last_run().error, 'destination_unverified')

    def test_funded_money_is_not_paid_to_it(self):
        self.delivered_order()
        self.set_answer('ERROR')
        self.enviar()
        self.journeys()
        self.assert_payee_review()

    def test_a_later_verification_lifts_it(self):
        self.set_answer('ERROR')
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.make_rule()
        self.send_run()

    def test_a_key_never_rejected_still_runs(self):
        self.enviar()
        self.make_rule()
        self.send_run()


class EditRaceTests(HolderCase):
    """4. The funding invariant holds with the prepare check bypassed."""
    amount = '100.00'

    def edit(self, *, bypass, amount='2000.00'):
        other = PayoutDestination.objects.create(
            confio_account=self.personal, provider='infinia', kind='bank_account', status='active', holder_name='',
            country='MEX', asset='MXN', label=f'CLABE · {OTHER_CLABE}',
            details={'type': 'CLABE', 'clabe': OTHER_CLABE, 'reference': 'Confio'},
            provider_data={'method_id': 'mx_clabe', 'validation': self.answer('DISABLED')})
        args = dict(amount=amount, rule_id=str(self.rule.internal_id), payout_method_id=str(other.internal_id))
        if bypass:
            with mock.patch('smart_account.services.require_no_run_in_flight'):
                return other, self.prepare(**args)
        return other, self.prepare(**args)

    def land(self, batch):
        token, ref, amount_wei = updated_terms(batch)
        self.world.rules[(self.contract, 1)]['token_in'] = token
        tx_hash = self.update_on_chain(amount_usd=Decimal(amount_wei) / w.WAD, payout_ref=ref)
        land_update(self, batch, tx_hash)

    def assert_old_recipient_never_gets_the_new_amount(self, other):
        self.bridges()
        order = self.world.orders[-1]
        tx_hash, units = self.world.relay_fills(order, out=1975 * 10 ** 6)
        self.bridges()
        self.credit_usdc(tx_hash, units)
        for _ in range(3):
            self.run_rules()
            self.workers()
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))
        self.assertEqual((self.journey().failure_code, self.payout().status), (TERMS_REVIEW, 'review'))
        self.assertIn('no es lo que firmó', self.alert_text())
        # The mirror adopted the edit: only this payment is parked.
        rule = SmartAccountRule.objects.get(pk=self.rule.pk)
        self.assertEqual((rule.amount, rule.payout_method, rule.active), (Decimal('2000.00'), other, True))

    def test_an_edit_between_the_order_and_execute_rule_with_the_check_bypassed(self):
        self.unsent_order()             # the order exists, nothing is broadcast
        other, batch = self.edit(bypass=True)
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        self.land(batch)                # mined before executeRule
        self.world.mine_held()
        self.mirror_chain()
        self.assert_old_recipient_never_gets_the_new_amount(other)

    def test_an_edit_prepared_before_the_run_opened_and_signed_after(self):
        self.make_rule()
        other, batch = self.edit(bypass=False)      # nothing to refuse yet
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        self.land(batch)
        self.mirror_chain()                         # known before the payment
        self.world.mine_held()
        self.mirror_chain()
        self.assert_old_recipient_never_gets_the_new_amount(other)

    def test_an_edit_never_closes_an_order_whose_call_may_land(self):
        self.unsent_order()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        SmartAccountRuleRun.objects.update(status='failed')
        SmartAccountRule.objects.update(scheduled_for=self.slot + timedelta(minutes=1))
        payouts.close_superseded_orders(self.rule.pk)
        self.assertEqual(self.bridge().status, 'submitted')

    def test_an_edit_that_lands_before_signing_pays_only_the_new_recipient(self):
        self.unsent_order()
        old = self.bridge()
        other, batch = self.edit(bypass=True)
        self.land(batch)
        self.assertEqual(self.run_rules()['waiting'], 1)        # mirror behind
        self.assertEqual(self.world.signed, {})
        self.mirror_chain()
        old.refresh_from_db()
        self.assertEqual(old.status, 'expired')     # unsent, and no longer the rule
        self.advance(2)
        self.assertEqual(self.run_rules()['sent'], 1)
        payout = SmartAccountPayout.objects.order_by('-pk').first()
        self.assertEqual(payout.journey.destination_snapshot['destination_account']['clabe'], OTHER_CLABE)
        self.assertNotEqual(payout.deposit_address, old.deposit_address.lower())


HUNDRED_NET = 99_100_000_000_000_000_000


@override_settings(**VE_ON)
class PagoMovilEditRaceTests(RunBase):
    """4. The same on Pago Móvil."""

    def prepare(self, destination, **kwargs):
        kwargs.setdefault('amount_usd', '100.00')
        return super().prepare(destination, **kwargs)

    def setUp(self):
        from ramps import ve_send
        real = ve_send.reserve
        super().setUp()
        self.chain.rules[(self.address, 1)].update(
            amount_usd_wei=100 * WAD, token_in=self.rule.token_in.lower(), token_out=abi.ZERO_ADDRESS,
            payee=abi.ZERO_ADDRESS, payout_ref=self.rule.payout_ref)
        self.quote.return_value = dict(quote(ves='3920.00', usdt='99.10'), usd_amount='100.00')
        for patcher in (
                mock.patch('ramps.ve_send.reserve', side_effect=real),
                mock.patch('cusd_plus.cusd_vault.preview_redeem_wei',
                           return_value=SimpleNamespace(net_wei=HUNDRED_NET))):
            patcher.start()
            self.addCleanup(patcher.stop)
        alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)
        self.alert = alert.start()
        self.addCleanup(alert.stop)

    def edit(self, *, bypass):
        other = SmartAccountPagoMovilDestination.objects.create(
            user=self.owner, phone='584120000000', bank_code='0102', id_number='V00000001',
            holder_name='Otra Persona', label='Pago Móvil · Banco de Venezuela · 0000')
        args = dict(amount_usd='2000.00', rule_id=str(self.rule.internal_id))
        if bypass:
            with mock.patch('smart_account.services.require_no_run_in_flight'):
                return other, self.prepare(other, **args)
        return other, self.prepare(other, **args)

    def event(self, name, args, tx_hash, block):
        return SmartAccountEvent.objects.create(
            smart_account=self.account, address=self.address, tx_hash=tx_hash, log_index=1, name=name, args=args,
            block_number=block, block_time=timezone.now())

    def land_then_execute(self, batch):
        token, ref, amount_wei = updated_terms(batch)
        self.chain.rules[(self.address, 1)].update(
            token_in=token, payout_ref=ref, amount_usd_wei=amount_wei, next_run_at=int(timezone.now().timestamp()))
        land_update(self, batch, '0x' + '4e' * 32)
        self.event('RuleUpdated', {'id': '1'}, '0x' + '4e' * 32, 101)
        units = 1982 * WAD
        self.event('PayoutSent', {'id': '1', 'payoutRef': ref, 'destination': DEPOSIT, 'tokenIn': CUSD,
                                  'amountIn': str(amount_wei), 'usdtOut': str(units)}, TX, 102)
        from ramps import ve_send
        log = {'address': ve_send.USDT_BSC, 'data': hex(units),
               'topics': [ve_send.TRANSFER_TOPIC, '0x' + '0' * 24 + CUSD[2:], '0x' + '0' * 24 + DEPOSIT[2:]]}

        def rpc(method, params):
            if method == 'eth_getBlockByNumber':
                return {'number': hex(10 ** 6)} if params[0] == 'finalized' else {'hash': '0xb1'}
            if method == 'eth_getTransactionReceipt':
                return {'status': '0x1', 'blockNumber': '0x66', 'blockHash': '0xb1', 'logs': [log]}
            raise AssertionError(method)
        with mock.patch('ramps.ve_send._rpc_default', return_value=rpc), \
                mock.patch('smart_account.reconcile.backfill_pending', return_value=set()), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(reconcile.apply_pending(), {'applied': 2, 'failed': 0})

    def assert_parked(self, other):
        ramp = SmartAccountPayout.objects.get().ramp
        section = ramp.metadata['ve_send']
        self.assertEqual((section['beneficiary']['phone'], section['phase'], ramp.status_detail),
                         ('584141234567', 'payout_review', f'needs_review:{TERMS_REVIEW}'))
        self.assertEqual(section['funded_wei'], str(1982 * WAD))
        rule = SmartAccountRule.objects.get(pk=self.rule.pk)
        self.assertEqual((rule.amount, rule.pagomovil_destination), (Decimal('2000.00'), other))

    def test_an_edit_between_the_order_and_execute_rule_with_the_check_bypassed(self):
        self.relay.side_effect = [RuntimeError('the worker died'), (SimpleNamespace(signed_tx_hash=TX), True)]
        self.run_rule()                 # the order exists, nothing is broadcast
        other, batch = self.edit(bypass=True)
        self.assertEqual(self.run_rule()['sent'], 1)
        self.land_then_execute(batch)
        self.assert_parked(other)

    def test_an_edit_prepared_before_the_run_opened_and_signed_after(self):
        other, batch = self.edit(bypass=False)
        self.assertEqual(self.run_rule()['sent'], 1)
        self.land_then_execute(batch)
        self.assert_parked(other)


@override_settings(**VE_ON)
class PagoMovilNoticeTests(RunBase):
    """5. A typed name is never shown as the holder."""

    def delivered(self, run):
        with mock.patch('smart_account.notifications._send') as sent:
            notifications.payout_delivered(run, '1.960,00', 'Bs.')
        return sent.call_args

    def test_a_typed_name_is_marked_as_the_owners(self):
        run = SmartAccountRuleRun.objects.create(rule=self.rule, scheduled_for=self.slot)
        sent = self.delivered(run)
        self.assertEqual(
            sent.args[2], f'Enviamos Bs. 1.960,00 a {self.dest.label} (escribiste: Ana Pérez).')
        self.assertFalse((sent.kwargs.get('data') or {}).get('holderName'))

    def test_it_names_who_was_paid_not_the_rules_recipient_now(self):
        self.run_rule()
        other = SmartAccountPagoMovilDestination.objects.create(
            user=self.owner, phone='584120000000', bank_code='0102', id_number='V00000001',
            holder_name='Otra Persona', label='Pago Móvil · Banco de Venezuela · 0000')
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(pagomovil_destination=other)
        body = self.delivered(SmartAccountRuleRun.objects.get()).args[2]
        self.assertIn('(escribiste: Ana Pérez)', body)
        self.assertNotIn('Otra Persona', body)


class InfiniaNoticeTests(HolderCase):
    def delivered(self):
        with mock.patch('smart_account.notifications._send') as sent:
            notifications.payout_delivered(self.last_run(), '900,00', 'MXN')
        return sent.call_args.args[2]

    def test_a_typed_name_is_marked(self):
        PayoutDestination.objects.filter(pk=self.destination.pk).update(
            provider_data=dict(self.stored(), owner_holder_name='Ana Prueba'))
        self.make_rule()
        self.send_run()
        self.assertEqual(self.delivered(), f'Enviamos 900,00 MXN a CLABE · …{CLABE[-4:]} (escribiste: Ana Prueba).')

    def test_a_bank_answer_is_not(self):
        self.set_answer('SUCCESSFUL', 'Ana Prueba')
        self.make_rule()
        self.send_run()
        self.assertNotIn('escribiste', self.delivered())
        self.assertIn('Ana Prueba', self.delivered())
