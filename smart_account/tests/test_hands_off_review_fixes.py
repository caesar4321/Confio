"""Review fixes for hands-off chat trades and purchases: a row resumed after
its cap/move card is never 'withdrawn' (P2-1), no row is stranded 'pending'
(P2-2: errors before signing, the task's own errors, the beat sweep), the
order is created and linked in one transaction (P3-2), and a second raise
offer is a new note (P3-3)."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from marketplace.models import Order
from smart_account import relay_purchases, relay_trades
from smart_account.models import SmartRelayPurchase, SmartRelayTrade
from smart_account.tests import test_hands_off_purchases as purchase_tests, test_hands_off_trades as trade_tests


class TradeResumeReplyStateTests(trade_tests.ChatCardTests):
    def test_a_trade_resumed_after_the_cap_card_is_not_withdrawn(self):
        from inbox.models import SupportMessage
        from inbox.schema import get_or_create_support_conversation
        from smart_account.context import personal_account
        conv = get_or_create_support_conversation(self.user, personal_account(self.user), None)
        SupportMessage.objects.create(conversation=conv, sender_type='USER', message_type='TEXT', body='sí')
        (_d, _r, extra), _s = self.answer('no_rule', suggested=Decimal('250'))
        row = SmartRelayTrade.objects.get()
        self.assertEqual(row.conversation_id, conv.pk)
        SupportMessage.objects.create(conversation=conv, sender_type='AGENT', message_type='TEXT', body='x',
                                      metadata={'actions': extra['actions']})
        with mock.patch('smart_account.tasks.run_relay_trade.apply_async'), \
                self.captureOnCommitCallbacks(execute=True):
            relay_trades.resume(self.user, row.internal_id)
        SmartRelayTrade.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=2))
        self.assertEqual(relay_trades._reply_state(SmartRelayTrade.objects.get(pk=row.pk)), 'shown')


class TradeNeverStrandedTests(trade_tests.ExecutionTests):
    def test_an_error_before_signing_is_retried_then_told(self):
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=RuntimeError('kms down')):
            for _ in range(relay_trades.MAX_ERRORS - 1):
                with self.assertRaises(relay_trades.Later):
                    relay_trades.run(self.row.pk)
            relay_trades.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('failed', 'error'))
        self.assertIn('no se movió nada', self.notes[0][0])

    def test_the_task_retries_other_errors_then_tells_it_failed(self):
        from smart_account import tasks
        with mock.patch('smart_account.relay_trades.run', side_effect=RuntimeError('rpc')), \
                mock.patch.object(tasks.run_relay_trade, 'retry', side_effect=RuntimeError('retry')) as retry:
            for _ in range(relay_trades.MAX_ERRORS - 1):
                with self.assertRaisesMessage(RuntimeError, 'retry'):
                    tasks.run_relay_trade.run(self.row.pk)
            tasks.run_relay_trade.run(self.row.pk)
        self.assertEqual(retry.call_count, relay_trades.MAX_ERRORS - 1)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'failed')

    def test_the_sweep_reruns_stale_rows_and_gives_up_old_ones(self):
        old = timezone.now() - timedelta(hours=1)
        SmartRelayTrade.objects.filter(pk=self.row.pk).update(updated_at=old)
        with mock.patch('smart_account.relay_trades.schedule') as scheduled:
            self.assertEqual(relay_trades.sweep()['rerun'], 1)
        scheduled.assert_called_once_with(self.row.pk, countdown=1)
        SmartRelayTrade.objects.filter(pk=self.row.pk).update(
            updated_at=old, created_at=timezone.now() - timedelta(hours=7))
        self.assertEqual(relay_trades.sweep()['gave_up'], 1)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'failed')

    def test_a_second_raise_offer_is_a_new_note(self):
        self.used = 240 * 10 ** 18
        relay_trades.run(self.row.pk)
        SmartRelayTrade.objects.filter(pk=self.row.pk).update(status='pending',
                                                              updated_at=timezone.now() + timedelta(minutes=5))
        relay_trades.run(self.row.pk)
        self.assertEqual(len({tag for _body, tag in self.notes}), 2)


class PurchaseNeverStrandedTests(purchase_tests.ExecutionTests):
    def test_an_error_before_signing_is_retried_then_told_and_the_order_dropped(self):
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=RuntimeError('kms down')):
            for _ in range(relay_purchases.MAX_ERRORS - 1):
                with self.assertRaises(relay_purchases.Later):
                    relay_purchases.run(self.row.pk)
            relay_purchases.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('failed', 'error'))
        self.assertEqual(Order.objects.count(), 1)              # one order across every retry
        self.assertEqual(self.row.order.status, 'cancelled')

    def test_a_kms_failure_creating_the_order_is_retried_by_the_task(self):
        from smart_account import tasks
        with mock.patch('marketplace.escrow.sign_deposit', side_effect=RuntimeError('kms')), \
                mock.patch.object(tasks.run_relay_purchase, 'retry', side_effect=RuntimeError('retry')):
            with self.assertRaisesMessage(RuntimeError, 'retry'):
                tasks.run_relay_purchase.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.attempts), ('pending', 1))
        self.assertFalse(Order.objects.exists())                 # rolled back: no orphan draft holding stock

    def test_a_changed_price_leaves_no_order_behind(self):
        from marketplace.models import Product
        Product.objects.filter(pk=self.product.pk).update(price_usd=Decimal('40'))
        relay_purchases.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('failed', 'price_changed'))
        self.assertFalse(Order.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_the_order_is_made_once_and_linked(self):
        order = relay_purchases.make_order(self.row, self.own)
        again = relay_purchases.make_order(SmartRelayPurchase.objects.get(pk=self.row.pk), self.own)
        self.assertEqual(order.pk, again.pk)
        self.assertEqual(SmartRelayPurchase.objects.get(pk=self.row.pk).order_id, order.pk)

    def test_the_sweep_rereads_a_sent_row(self):
        SmartRelayPurchase.objects.filter(pk=self.row.pk).update(
            status='sent', updated_at=timezone.now() - timedelta(hours=1))
        relay_purchases.schedule_finish.reset_mock()
        self.assertEqual(relay_purchases.sweep()['finish'], 1)
        relay_purchases.schedule_finish.assert_called_once_with(self.row.pk, countdown=1)

    def test_a_second_raise_offer_is_a_new_note(self):
        self.used = 130 * 10 ** 18
        relay_purchases.run(self.row.pk)
        SmartRelayPurchase.objects.filter(pk=self.row.pk).update(status='pending',
                                                                 updated_at=timezone.now() + timedelta(minutes=5))
        relay_purchases.run(self.row.pk)
        self.assertEqual(len({tag for _body, tag in self.notes}), 2)
