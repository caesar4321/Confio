from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, SimpleTestCase, TransactionTestCase
from django.utils import timezone

from ramps.koywe_client import KoyweClient, KoyweError
from ramps.koywe_refunds import reconcile_refund
from ramps.koywe_sync import sync_koywe_ramp_transaction_from_order
from ramps.models import KoyweRefund, RampTransaction
from ramps.tasks import poll_koywe_ramp_transactions


class RefundTests(TestCase):
    def setUp(self):
        self.ramp = RampTransaction.objects.create(
            provider='koywe', direction='off_ramp', status='FAILED',
            provider_order_id='refund-order', status_detail='invalid_withdrawals_details: bad beneficiary',
            actor_address='0x' + '12' * 20, crypto_currency='USDT BSC', destination='cusd_plus',
            metadata={'auth_email': 'original@example.com'},
        )
        self.client = Mock(is_configured=True)
        self.status('INVALID_WITHDRAWALS_DETAILS')
        self.client.request_offramp_refund.return_value = {'code': 'REFUND_000', 'data': {'orderId': 'refund-order'}}

    def status(self, status, **extras):
        self.client.get_ramp_order_status.return_value = SimpleNamespace(
            raw_response={'orderId': 'refund-order', 'status': status, 'symbolIn': 'USDT BSC', **extras},
            next_action_url=None,
        )

    def run_refund(self):
        reconcile_refund(ramp_id=self.ramp.pk, client=self.client)

    def expire(self):
        KoyweRefund.objects.update(last_attempt_at=timezone.now() - timedelta(minutes=11))

    def test_request_uses_original_wallet_and_email_without_completing_payout(self):
        self.run_refund()
        self.client.request_offramp_refund.assert_called_once_with(
            order_id='refund-order', destination_address=self.ramp.actor_address, email='original@example.com')
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'FAILED')
        self.assertEqual(self.ramp.status_detail, 'refund_requested')
        self.assertIsNone(self.ramp.completed_at)
        self.run_refund()
        self.expire()
        self.run_refund()
        self.assertEqual(self.client.request_offramp_refund.call_count, 1)

    def test_timeout_reconciles_before_retry_and_keeps_frozen_destination(self):
        self.client.request_offramp_refund.side_effect = KoyweError('timeout')
        with self.assertRaises(KoyweError):
            self.run_refund()
        self.assertEqual(KoyweRefund.objects.get().state, 'unknown')
        RampTransaction.objects.filter(pk=self.ramp.pk).update(actor_address='0x' + '34' * 20)
        self.expire()
        self.client.request_offramp_refund.side_effect = None
        self.run_refund()
        self.assertEqual(self.client.request_offramp_refund.call_args.kwargs['destination_address'], self.ramp.actor_address)
        self.assertEqual(self.client.get_ramp_order_status.call_count, 2)

    def test_webhook_progress_between_get_and_post_prevents_another_request(self):
        from ramps.koywe_refunds import _advance
        result = self.client.get_ramp_order_status.return_value
        def get_status(**kwargs):
            _advance(KoyweRefund.objects.get().pk, 'started')
            return result
        self.client.get_ramp_order_status.side_effect = get_status
        self.run_refund()
        self.client.request_offramp_refund.assert_not_called()
        self.assertEqual(KoyweRefund.objects.get().state, 'started')

    def test_timeout_followed_by_provider_progress_does_not_repost(self):
        self.client.request_offramp_refund.side_effect = KoyweError('timeout')
        with self.assertRaises(KoyweError):
            self.run_refund()
        self.expire()
        self.status('REFUND_IN_PROGRESS')
        self.run_refund()
        self.assertEqual(KoyweRefund.objects.get().state, 'in_progress')
        self.assertEqual(self.client.request_offramp_refund.call_count, 1)

    def test_provider_duplicate_codes_are_accepted(self):
        for code in ['REFUND_004', 'REFUND_005']:
            with self.subTest(code=code):
                KoyweRefund.objects.all().delete()
                self.client.request_offramp_refund.return_value = {'code': code}
                self.run_refund()
                self.assertEqual(KoyweRefund.objects.get().state, 'requested')

    def test_delivered_and_late_events_never_reopen_refund(self):
        self.run_refund()
        self.expire()
        self.status('REFUND_DELIVERED')
        self.run_refund()
        for status in ['INVALID_WITHDRAWALS_DETAILS', 'REFUND_STARTED', 'WAITING']:
            sync_koywe_ramp_transaction_from_order(ramp_tx=self.ramp, order_payload={'status': status})
            self.ramp.refresh_from_db()
            self.assertEqual(self.ramp.status_detail, 'refund_delivered')
        self.assertEqual(KoyweRefund.objects.get().state, 'delivered')
        self.assertEqual(self.client.request_offramp_refund.call_count, 1)

    def test_stale_completion_never_reaches_signals_or_sets_completion_time(self):
        from django.db.models.signals import post_save
        self.run_refund()
        self.expire()
        self.status('REFUND_DELIVERED')
        self.run_refund()
        observed = []
        def observe(sender, instance, **kwargs):
            observed.append((instance.status, instance.status_detail, instance.completed_at))
        post_save.connect(observe, sender=RampTransaction, weak=False)
        try:
            sync_koywe_ramp_transaction_from_order(
                ramp_tx=self.ramp, order_payload={'status': 'FIAT_DELIVERED'},
            )
        finally:
            post_save.disconnect(observe, sender=RampTransaction)
        self.assertEqual(observed, [('FAILED', 'refund_delivered', None)])
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'FAILED')
        self.assertIsNone(self.ramp.completed_at)

    def test_mismatched_mongo_order_id_cannot_trigger_refund(self):
        self.client.get_ramp_order_status.return_value.raw_response = {
            '_id': 'another-order', 'status': 'INVALID_WITHDRAWALS_DETAILS',
        }
        self.run_refund()
        self.client.request_offramp_refund.assert_not_called()

    def test_pending_refund_does_not_hide_real_provider_completion(self):
        KoyweRefund.objects.create(ramp=self.ramp, provider_order_id=self.ramp.provider_order_id,
                                   destination_address=self.ramp.actor_address)
        sync_koywe_ramp_transaction_from_order(
            ramp_tx=self.ramp, order_payload={'status': 'FIAT_DELIVERED'},
        )
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'COMPLETED')
        self.assertEqual(KoyweRefund.objects.get().state, 'not_required')

    def test_sync_rejects_status_from_another_order(self):
        self.run_refund()
        with self.assertRaises(KoyweError):
            sync_koywe_ramp_transaction_from_order(
                ramp_tx=self.ramp, order_payload={'_id': 'other', 'status': 'REFUND_DELIVERED'},
            )
        self.assertEqual(KoyweRefund.objects.get().state, 'requested')

    def test_no_refund_for_ineligible_status_or_wrong_provider_order_or_asset(self):
        for fields in [{'status': 'FIAT_DELIVERED'}, {'orderId': 'other'}, {'symbolIn': 'USDC Polygon'}]:
            KoyweRefund.objects.all().delete()
            self.status('INVALID_WITHDRAWALS_DETAILS', **fields) if 'status' not in fields else self.status(fields['status'])
            self.run_refund()
        self.client.request_offramp_refund.assert_not_called()

    def test_invalid_wallet_or_unknown_rail_is_not_submitted(self):
        for fields in [{'actor_address': ''}, {'actor_address': '0x' + '00' * 20}, {'crypto_currency': 'USDT'}]:
            RampTransaction.objects.filter(pk=self.ramp.pk).update(**fields)
            self.run_refund()
        self.client.request_offramp_refund.assert_not_called()
        self.assertFalse(KoyweRefund.objects.exists())

    def test_algorand_refund_uses_valid_original_algorand_wallet(self):
        from algosdk.account import generate_account
        _, address = generate_account()
        RampTransaction.objects.filter(pk=self.ramp.pk).update(actor_address=address, crypto_currency='USDC Algorand')
        self.status('INVALID_WITHDRAWALS_DETAILS', symbolIn='USDC Algorand')
        self.run_refund()
        self.assertEqual(self.client.request_offramp_refund.call_args.kwargs['destination_address'], address)

    def test_get_failure_claim_can_recover_after_lease(self):
        self.client.get_ramp_order_status.side_effect = KoyweError('unavailable')
        with self.assertRaises(KoyweError):
            self.run_refund()
        self.client.request_offramp_refund.assert_not_called()
        self.expire()
        self.client.get_ramp_order_status.side_effect = None
        self.run_refund()
        self.assertEqual(KoyweRefund.objects.get().state, 'requested')

    def test_real_success_closes_unsubmitted_refund_without_post(self):
        self.status('FIAT_DELIVERED')
        self.run_refund()
        self.assertEqual(KoyweRefund.objects.get().state, 'not_required')
        self.client.request_offramp_refund.assert_not_called()

    def test_completed_and_onramp_orders_are_not_refunded(self):
        for fields in [{'status': 'COMPLETED'}, {'status': 'FAILED', 'direction': 'on_ramp'}]:
            RampTransaction.objects.filter(pk=self.ramp.pk).update(**fields)
            self.run_refund()
        self.client.get_ramp_order_status.assert_not_called()

    def test_duplicate_local_order_cannot_refund_to_another_wallet(self):
        self.run_refund()
        other = RampTransaction.objects.create(provider='koywe', direction='off_ramp', status='FAILED',
            provider_order_id=self.ramp.provider_order_id, actor_address='0x' + '34' * 20, crypto_currency='USDT BSC')
        reconcile_refund(ramp_id=other.pk, client=self.client)
        self.assertEqual(self.client.request_offramp_refund.call_count, 1)

    def test_poller_recovers_old_invalid_order_and_stops_after_delivery(self):
        RampTransaction.objects.filter(pk=self.ramp.pk).update(created_at=timezone.now() - timedelta(days=30))
        with patch('ramps.tasks.KoyweClient', return_value=self.client):
            self.assertIn('Polled 1', poll_koywe_ramp_transactions())
            self.assertEqual(KoyweRefund.objects.get().state, 'requested')
            self.status('REFUND_DELIVERED')
            poll_koywe_ramp_transactions()
            self.assertEqual(KoyweRefund.objects.get().state, 'delivered')
            self.assertEqual(poll_koywe_ramp_transactions(), 'No pending Koywe ramps')

    def test_rejected_destination_is_not_retried_and_malformed_response_is_unknown(self):
        self.client.request_offramp_refund.return_value = {'code': 'REFUND_006'}
        self.run_refund()
        self.expire()
        self.run_refund()
        self.assertEqual(KoyweRefund.objects.get().state, 'rejected')
        self.assertEqual(self.client.request_offramp_refund.call_count, 1)
        KoyweRefund.objects.all().delete()
        self.client.request_offramp_refund.return_value = {'message': 'ok'}
        self.run_refund()
        self.assertEqual(KoyweRefund.objects.get().state, 'unknown')


class RefundClientTests(SimpleTestCase):
    def test_exact_endpoint_payload_and_non_success_duplicate_response(self):
        client = KoyweClient()
        client.authenticate = Mock(return_value='token')
        response = Mock(ok=False, status_code=400)
        response.json.return_value = {'code': 'REFUND_005', 'message': 'Already requested'}
        client.session.request = Mock(return_value=response)
        result = client.request_offramp_refund(order_id='order/id', destination_address='wallet', email='source@example.com')
        self.assertEqual(result['code'], 'REFUND_005')
        args, kwargs = client.session.request.call_args
        self.assertEqual(args, ('POST', client.base_url + '/rest/orders/offramp/order%2Fid/refund'))
        self.assertEqual(kwargs['json'], {'destinationAddress': 'wallet'})
        client.authenticate.assert_called_once_with(email='source@example.com')


class RefundConcurrencyTests(TransactionTestCase):
    def test_two_workers_submit_only_one_request(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from django.db import close_old_connections

        ramp = RampTransaction.objects.create(
            provider='koywe', direction='off_ramp', status='FAILED', provider_order_id='concurrent-refund',
            actor_address='0x' + '12' * 20, crypto_currency='USDT BSC',
        )
        entered = Event()
        release = Event()
        client = Mock()
        def get_status(**kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Test did not release provider request')
            return SimpleNamespace(raw_response={'status': 'INVALID_WITHDRAWALS_DETAILS'})
        client.get_ramp_order_status.side_effect = get_status
        client.request_offramp_refund.return_value = {'code': 'REFUND_000'}
        def worker():
            close_old_connections()
            try:
                reconcile_refund(ramp_id=ramp.pk, client=client)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(worker)
            try:
                self.assertTrue(entered.wait(5))
                reconcile_refund(ramp_id=ramp.pk, client=client)
            finally:
                release.set()
            pending.result(timeout=5)
        client.request_offramp_refund.assert_called_once()
        self.assertEqual(KoyweRefund.objects.get().state, 'requested')
