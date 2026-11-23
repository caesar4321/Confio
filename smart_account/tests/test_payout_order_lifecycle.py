"""An automatic payment's order through failures, retries and expiry: one
fundable order at a time, the event that paid finds it, and the owner is
told only what is true. Fake values only."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from notifications.models import Notification
from payment_accounts.infinia_bridge import live_journeys
from payment_accounts.models import InfiniaJourney, PaymentBridgeTransfer
from smart_account import automation, notifications, payouts, reconcile, relayer, tasks
from smart_account.models import (
    SmartAccountEvent, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun,
    SmartAccountStandingAuthorization,
)

from . import infinia_world as w
from .infinia_base import InfiniaPayoutCase

HOUR = 3600


class OrdersCase(InfiniaPayoutCase):
    def orders(self):
        return list(PaymentBridgeTransfer.objects.filter(funding_mode='contract').select_related(
            'quote__money_flow').order_by('pk'))

    def fundable(self):
        return [b for b in self.orders() if b.status == 'submitted' and not b.source_tx_hash]

    def failing_for(self, seconds, every=300, interrupted=False):
        """`interrupted`: each pass dies with its order open, else its call is
        refused and the order closed."""
        self.world.revert_simulation = not interrupted
        passed = 0
        while passed <= seconds:
            self.leave_order_open() if interrupted else self.run_rules()
            self.assertLessEqual(len(self.fundable()), 1, 'two fundable orders at once')
            self.advance(every)
            passed += every


class RetriedHashTests(OrdersCase):
    """P2-1: the durable relayer row names the (rule, slot)."""

    def sent_with_the_hash_not_saved(self, saved=''):
        self.make_rule()
        self.assertEqual(self.run_rules()['sent'], 1)
        SmartAccountRuleRun.objects.update(status='failed', tx_hash=saved)
        return SmartAccountRelayTx.objects.get().signed_tx_hash

    def assert_funds_its_journey(self, tx_hash):
        self.mirror_chain()
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual((run.tx_hash, run.status), (tx_hash, 'ok'))
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(SmartAccountRuleRun.objects.count(), 1)     # no bare run
        self.assertNotIn('sin pago que le corresponda', self.alert_text())

    def test_a_retry_holding_the_earlier_attempts_hash_is_funded(self):
        self.assert_funds_its_journey(self.sent_with_the_hash_not_saved(saved='0x' + '3b' * 32))

    def test_a_retry_with_no_hash_is_funded(self):
        self.assert_funds_its_journey(self.sent_with_the_hash_not_saved())

    def test_the_source_wins_over_another_run_holding_that_hash(self):
        tx_hash = self.sent_with_the_hash_not_saved()
        SmartAccountRuleRun.objects.create(
            rule=self.rule, scheduled_for=self.slot + timedelta(days=1), status='sent', tx_hash=tx_hash)
        self.mirror_chain()
        paying = SmartAccountRuleRun.objects.get(scheduled_for=self.slot)
        self.assertEqual((paying.tx_hash, paying.status), (tx_hash, 'ok'))
        self.assertEqual(self.to_paid().status, 'paid')

    def test_a_revert_with_no_saved_hash_still_fails_its_run(self):
        self.make_rule()
        self.world.revert_mined = True
        self.run_rules()
        SmartAccountRuleRun.objects.update(status='pending', tx_hash='')
        self.relay_receipts()
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual((run.status, run.error), ('failed', 'transaction reverted'))
        self.assertEqual(run.tx_hash, SmartAccountRelayTx.objects.get().signed_tx_hash)

    def test_the_hash_is_saved_with_the_durable_row_before_the_broadcast(self):
        self.make_rule()
        real, seen = self.world.rpc, []

        def rpc(chain, method, params):
            if method == 'eth_sendRawTransaction':
                seen.append(tuple(SmartAccountRuleRun.objects.values_list('status', 'tx_hash').get()))
                raise w.Revert('the node timed out')
            return real(chain, method, params)
        with mock.patch.object(self.world, 'rpc', side_effect=rpc):
            self.run_rules()
        row = SmartAccountRelayTx.objects.get()
        self.assertEqual(set(seen), {('sent', row.signed_tx_hash)})     # every node saw it already saved
        self.assertEqual(row.status, 'signed')

    def test_a_sent_run_whose_final_revert_was_never_said_is_retried(self):
        self.make_rule()
        self.world.revert_mined = True
        self.run_rules()
        SmartAccountRelayTx.objects.update(status='reverted')       # and the worker died
        self.world.revert_mined = False
        self.run_rules()
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'failed')
        self.send_run()


class TransientFailureTests(OrdersCase):
    """P2-2: a failure that passes does not lose the payment."""

    def test_past_the_deposits_lifetime_the_slot_gets_a_fresh_order_and_pays(self):
        self.make_rule()
        self.failing_for(900, interrupted=True)     # 0, 5, 10 and 15 minutes
        first, second = self.orders()
        self.assertEqual((first.status, first.infinia_journey.stage), ('expired', 'failed'))
        self.assertNotEqual(first.quote.request_id, second.quote.request_id)
        self.assertNotEqual(first.deposit_address, second.deposit_address)
        bound = second.quote.money_flow.metadata['contract_funding']
        self.assertEqual((bound['attempt'], bound['replaces']), (2, str(first.internal_id)))
        self.world.revert_simulation = False
        self.send_run()
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual((len(self.world.signed), len(self.world.payouts)), (1, 1))

    def test_hours_of_failure_then_it_pays(self):
        self.make_rule()
        self.failing_for(5 * HOUR)
        orders = self.orders()
        self.assertEqual(len({b.quote.request_id for b in orders}), len(orders))
        # The first ones at once, then one an hour: not one every ten minutes.
        self.assertLessEqual(len(orders), 9)
        self.assertGreaterEqual(len(orders), 6)
        self.world.revert_simulation = False
        for _ in range(13):
            if self.run_rules().get('sent'):
                break
            self.advance(300)
        else:
            self.fail('the payment was lost')
        self.mirror_chain()
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(len(self.world.payouts), 1)

    def test_between_spaced_orders_the_owners_accounts_are_free(self):
        self.make_rule()
        self.failing_for(1800)
        self.assertEqual(self.last_run().error, 'retry_spaced')
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(confio_account=self.personal)).exists())

    def test_no_fresh_order_while_a_call_may_land(self):
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        SmartAccountRuleRun.objects.update(status='failed')
        SmartAccountRelayTx.objects.update(status='reorged')
        for _ in range(4):
            self.advance(600)
            self.assertEqual(self.run_rules()['waiting'], 1)
            self.bridges()
        self.assertEqual((len(self.orders()), len(self.world.signed)), (1, 1))
        self.assertNotEqual(self.orders()[0].status, 'expired')

    def test_money_for_a_replaced_order_goes_to_its_review_and_closes_the_fresh_one(self):
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        SmartAccountRelayTx.objects.update(status='dropped')
        SmartAccountRuleRun.objects.update(status='failed')
        self.advance(600)
        self.leave_order_open()
        first, second = self.orders()
        self.assertEqual((first.status, second.status), ('expired', 'submitted'))
        self.world.mine_held()              # the first one's call lands after all
        with mock.patch('smart_account.notifications.payout_resumed') as resumed:
            self.mirror_chain()
        resumed.assert_called_once()
        self.bridges()
        self.journeys()
        self.mirror()
        payout = self.payout()
        self.assertEqual((payout.journey.bridge_id, payout.status), (first.pk, 'review'))
        self.assertIn('ya cerrado', self.alert_text())
        self.advance(1000)
        self.bridges()
        second.refresh_from_db()
        self.assertEqual((second.status, second.source_tx_hash), ('expired', ''))
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))

    def give_up(self):
        self.make_rule()
        told = []
        with mock.patch('smart_account.notifications.rule_run',
                        side_effect=lambda run: told.append((run.status, run.message))):
            self.failing_for(600)
            self.advance(22 * HOUR)
            self.failing_for(3 * HOUR, every=HOUR)
        return told

    def test_a_failed_slot_that_becomes_final_is_told_again_and_ops_hear(self):
        told = self.give_up()
        self.assertEqual(len(told), 2, told)
        self.assertIn('lo reintentamos hasta el', told[0][1])
        rule = SmartAccountRule.objects.get()
        self.assertGreater(rule.scheduled_for, self.slot + timedelta(days=20))
        when = notifications._date(rule.scheduled_for)
        self.assertEqual(told[1], ('failed', f'No hicimos este pago; el próximo intento es el {when}.'))
        self.assertIn('pago automático no hecho', self.alert_text())
        self.assertEqual((self.fundable(), self.world.signed), ([], {}))

    def test_a_failed_slot_the_next_date_overtakes_is_told_again(self):
        self.make_rule()
        self.world.revert_simulation = True
        told = []
        with mock.patch('smart_account.notifications.rule_run', side_effect=lambda run: told.append(run.message)):
            self.run_rules()
            self.advance(32 * 24 * HOUR)
            self.account.paid_until = timezone.now() + timedelta(days=30)
            self.account.save(update_fields=['paid_until'])
            self.run_rules()
        self.assertEqual(len(told), 2, told)
        self.assertTrue(told[1].startswith('No hicimos este pago; el próximo intento es el '), told)


class WaitThatGivesUpTests(OrdersCase):
    """P2-4: never "we will pay when it ends" for a payment given up."""

    def test_a_busy_account_for_a_whole_day(self):
        self.make_rule()
        with mock.patch('payment_accounts.contract_funding.require_free',
                        side_effect=self.busy()), \
                mock.patch('smart_account.notifications.rule_run') as told:
            self.assertEqual(self.run_rules()['waiting'], 1)
            told.assert_not_called()
            self.advance(24 * HOUR)
            self.run_rules()
        told.assert_called_once()
        message = told.call_args.args[0].message
        when = notifications._date(SmartAccountRule.objects.get().scheduled_for)
        self.assertEqual(message, f'No hicimos este pago; el próximo intento es el {when}.')
        self.assertNotIn('cuando termine', message)

    def busy(self):
        from payment_accounts import contract_funding
        return contract_funding.Refused('account_busy', contract_funding.BUSY, retry=True)


class CompareAndSetTests(OrdersCase):
    """P2-3: what a stale worker may not write."""

    def test_finish_never_overwrites_sent_or_executed(self):
        self.make_rule()
        self.send_run()
        for status in ('sent', 'ok'):
            SmartAccountRuleRun.objects.update(status=status, message='')
            SmartAccountRule.objects.update(scheduled_for=self.slot)
            run = SmartAccountRuleRun.objects.get()
            run.status = 'pending'          # what the stale worker read
            rule = SmartAccountRule.objects.get()
            with mock.patch('smart_account.notifications.rule_run') as told:
                automation._finish_run(rule, run, 'skipped', 'no', 'stale', final=True)
            told.assert_not_called()
            self.assertEqual(SmartAccountRuleRun.objects.get().status, status)
            self.assertEqual(SmartAccountRule.objects.get().scheduled_for, self.slot)
            self.assertEqual(self.bridge().status, 'submitted')

    def test_a_run_another_worker_sent_is_a_wait(self):
        rule = self.make_rule()
        self.leave_order_open()
        SmartAccountRuleRun.objects.update(status='sent')
        from smart_account import infinia_payouts
        with self.assertRaises(payouts.PayoutSkip) as raised:
            infinia_payouts.open_run(rule, self.last_run())
        self.assertEqual((raised.exception.code, raised.exception.wait), ('payout_in_progress', True))
        self.assertEqual(self.bridge().status, 'submitted')

    def test_an_expired_lock_is_not_deleted_by_its_old_owner(self):
        key = 'smart_account_task_lock:test'
        cache.delete(key)

        def outlived():
            cache.set(key, 'the next worker', 60)
            return {}
        tasks._single('test', 60, outlived)
        self.assertEqual(cache.get(key), 'the next worker')
        cache.delete(key)
        tasks._single('test', 60, dict)
        self.assertIsNone(cache.get(key))


class PinnedHolderTests(OrdersCase):
    """P2-5: signed for a verified holder, it keeps needing one."""

    def verified(self, *, hours=0, status='SUCCESSFUL'):
        self.destination.refresh_from_db()
        self.destination.holder_name = 'Ana Prueba' if status == 'SUCCESSFUL' else ''
        self.destination.provider_data = dict(self.destination.provider_data, validation={
            'id': 'v1', 'status': status, 'holder_name': self.destination.holder_name,
            'checked_at': (timezone.now() - timedelta(hours=hours)).isoformat()})
        self.destination.save()

    def assert_told_and_not_paid(self):
        with mock.patch('smart_account.notifications.rule_run') as told:
            self.assertEqual(self.run_rules()['skipped'], 1)
        told.assert_called_once()
        self.assertEqual(self.last_run().error, 'holder_unverified')
        self.assertIn('No hicimos este pago', self.last_run().message)
        self.assertEqual((self.world.signed, self.orders()), ({}, []))
        self.assertTrue(SmartAccountRule.objects.get().active)      # the lookup can come back

    def test_a_row_rewritten_disabled_does_not_pay(self):
        self.verified()
        self.make_rule()
        self.verified(status='DISABLED')
        self.assert_told_and_not_paid()

    def test_the_lookup_switched_off_with_an_old_answer_does_not_pay_nor_erase_it(self):
        self.verified()
        self.make_rule()
        self.verified(hours=24 * 30)
        with mock.patch('payment_accounts.local_money.recheck_destination') as recheck:
            self.assert_told_and_not_paid()
        recheck.assert_not_called()
        self.destination.refresh_from_db()
        self.assertEqual(self.destination.provider_data['validation']['status'], 'SUCCESSFUL')

    def test_a_recent_answer_still_pays(self):
        self.verified()
        self.make_rule()
        self.send_run()

    def test_an_authorization_signed_unverified_is_unchanged(self):
        self.make_rule()
        self.send_run()


class OlderWorkerTests(OrdersCase):
    """P2-6: a fee-bearing rule an older worker stopped is seen."""

    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX')
    def test_ops_hear_and_it_is_not_switched_back_on(self):
        self.make_rule()
        self.assertGreater(SmartAccountStandingAuthorization.objects.get().max_processor_fee_usd, 0)
        SmartAccountRule.objects.update(active=False, deactivated_reason='destination_changed')
        self.assertEqual(payouts.deactivate_changed_rules(), 0)
        self.assertIn('versión anterior', self.alert_text())
        self.assertFalse(SmartAccountRule.objects.get().active)

    def test_a_rule_with_no_fee_is_not_reported(self):
        self.make_rule()
        SmartAccountRule.objects.update(active=False, deactivated_reason='destination_changed')
        payouts.deactivate_changed_rules()
        self.assertNotIn('versión anterior', self.alert_text())


class CombinedSweepTests(OrdersCase):
    """P3-1: dust in the sweep; the payment stays under what was signed."""

    def funded_with(self, extra):
        self.make_rule()
        self.send_run()
        self.bridges()
        order = self.world.orders[-1]
        self.world.stranger_pays(order['deposit'], extra)
        ours, received, sender = self.world.deposit_of(order)
        return order, (ours, received + extra, sender)

    def test_a_good_delivery_with_dust_in_the_sweep_pays(self):
        order, combined = self.funded_with(10 ** 15)
        with mock.patch.object(self.world, 'deposit_of', return_value=combined):
            self.assertEqual(self.to_paid().status, 'paid')

    def test_a_large_gift_in_the_sweep_is_delivered_and_never_paid_out_over_the_signed_amount(self):
        order, combined = self.funded_with(1000 * w.WAD)
        with mock.patch.object(self.world, 'deposit_of', return_value=combined):
            tx_hash, units = self.world.relay_fills(order, out=order['out'] + 1000 * 10 ** 6)
        self.bridges()
        self.assertEqual(self.bridge().status, 'delivered')
        self.credit_usdc(tx_hash, units)
        self.bridges()
        self.journeys()
        self.assertEqual(Decimal(str(self.world.transfers[-1]['source_amount'])), Decimal(self.amount))
        remainder = Decimal(self.journey().money_flow.metadata['fx_source_remainder']['amount'])
        self.assertGreater(remainder, 900)

    def test_a_refund_of_the_combined_sweep_is_proven(self):
        order, combined = self.funded_with(w.WAD)
        with mock.patch.object(self.world, 'deposit_of', return_value=combined):
            self.world.relay_refunds(order)
        self.workers()
        self.assertEqual((self.bridge().status, self.payout().status), ('refunded', 'refunded'))

    def test_a_refund_over_what_was_swept_is_not(self):
        order, combined = self.funded_with(w.WAD)
        with mock.patch.object(self.world, 'deposit_of', return_value=combined):
            self.world.relay_refunds(order, kept=-5 * w.WAD)
        self.workers()
        self.assertEqual(self.bridge().failure_code, 'relay_refund_amount_mismatch')

    def test_a_sweep_short_of_the_funding_is_not_evidence(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        ours, received, sender = self.world.deposit_of(self.world.orders[-1])
        with mock.patch.object(self.world, 'deposit_of', return_value=(ours, received - 1, sender)):
            self.world.relay_fills()
        self.bridges()
        self.assertNotEqual(self.bridge().status, 'delivered')


class ActivityTests(OrdersCase):
    """P3-2: the contract is the Cuenta inteligente, never "your wallet"."""

    def notice(self):
        return Notification.objects.get(notification_type='LOCAL_TRANSFER_UPDATED')

    def pushes(self):
        return [call for call in self.pushed.call_args_list
                if getattr(call.args[0] if call.args else None, 'notification_type', '') == 'LOCAL_TRANSFER_UPDATED']

    def test_a_refund_names_the_account(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        notice = self.notice()
        self.assertIn('a tu Cuenta inteligente', notice.message)
        self.assertNotIn('billetera', notice.message + notice.title)
        self.assertEqual(len(self.pushes()), 1)         # nothing else tells a refund
        from users.models_unified import UnifiedTransactionTable
        row = UnifiedTransactionTable.objects.get(local_money_flow=self.journey().money_flow)
        self.assertEqual((row.sender_display_name, row.status), ('Cuenta inteligente', 'FAILED'))
        self.assertIn('Cuenta inteligente', row.description)
        self.assertEqual(row.sender_address, self.contract)

    def test_a_paid_run_gets_no_second_generic_push(self):
        self.make_rule()
        self.send_run()
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(self.notice().data['stage'], 'completed')
        self.assertNotIn('billetera', self.notice().message + self.notice().title)
        self.assertEqual(self.pushes(), [])


class AlertsAfterCommitTests(OrdersCase):
    """P3-3: no Telegram while the event's row locks are held."""

    def test_the_amount_alert_waits_for_the_commit(self):
        self.make_rule()
        self.run_rules()
        run = SmartAccountRuleRun.objects.get()
        event = SmartAccountEvent(address=self.contract, tx_hash=run.tx_hash, name='PayoutSent',
                                  args={'id': '1', 'destination': self.bridge().deposit_address.lower(),
                                        'usdtOut': '1'})
        self.alerts.reset_mock()
        with self.captureOnCommitCallbacks(execute=False) as waiting:
            reconcile._payout_sent(self.account, event)
        self.alerts.assert_not_called()
        for callback in waiting:
            callback()
        self.assertIn('no coincide', self.alert_text())


class AuthorizationCopyTests(SimpleTestCase):
    """P3-4: one true sentence per code."""

    CODES = ('no_standing_authorization', 'destination_deleted', 'destination_changed', 'rail_not_available',
             'destination_unverified', 'holder_unverified')

    def test_each_code_has_its_own(self):
        said = {code: payouts.authorization_message(code) for code in self.CODES}
        self.assertEqual(len(set(said.values())), len(self.CODES))
        for code, message in said.items():
            self.assertLessEqual(len(message), 200, code)       # SmartAccountRuleRun.message
            if code != 'destination_changed':
                self.assertNotIn('cambió', message, code)
        self.assertNotIn('Firma', said['rail_not_available'])


class RevokedCopyTests(OrdersCase):
    def test_a_revoked_authorization_is_not_called_a_changed_destination(self):
        self.make_rule()
        SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now())
        with mock.patch('smart_account.notifications.rule_run') as told:
            self.run_rules()
        self.assertEqual(told.call_args.args[0].message, payouts.authorization_message('no_standing_authorization'))

    def test_the_daily_sweep_says_the_same(self):
        self.make_rule()
        SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now())
        self.assertEqual(payouts.deactivate_changed_rules(), 1)
        notice = Notification.objects.filter(title='Pausamos un pago automático').get()
        self.assertEqual(notice.message, payouts.authorization_message('no_standing_authorization'))
