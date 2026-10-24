import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from ramps import ve_pagomovil, vexpay
from ramps.models import RampTransaction, RampWebhookEvent
from ramps.signals import find_provider_tx_hash
from ramps.vexpay_client import (
    VexPayAmbiguousError,
    VexPayClient,
    VexPayError,
    verify_webhook_signature,
)
from ramps.views import vexpay_webhook

ADDRESS = '0x' + '12' * 20
TX_HASH = '0x' + 'ab' * 32
SECRET = 'whsec_test'

# Tests run with real AWS credentials: an unpatched ops alert would reach the
# team's Telegram group. Tests that check alerting patch it again themselves.
_ops_alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)


def setUpModule():
    _ops_alert.start()


def tearDownModule():
    _ops_alert.stop()


def _signature(body: bytes, secret: str = SECRET, t: int | None = None) -> str:
    t = int(time.time()) if t is None else t
    v1 = hmac.new(secret.encode(), f'{t}.'.encode() + body, hashlib.sha256).hexdigest()
    return f't={t},v1={v1}'


def _payment(status='COMPLETED', onward_status=None, **extra):
    payment = {'paymentId': 'pay-1', 'status': status, 'vesAmount': 20280, 'externalRef': 'ref'}
    if onward_status:
        payment['onwardPayout'] = {
            'status': onward_status, 'network': 'BEP20', 'address': ADDRESS,
            'amountUsdt': '18.94', 'feeUsdt': '0.75',
            **({'txHash': TX_HASH} if onward_status == 'completed' else {}),
        }
    payment.update(extra)
    return payment


class SignatureTests(SimpleTestCase):
    body = b'{"event":"payment.completed"}'

    def test_valid_signature(self):
        self.assertTrue(verify_webhook_signature(self.body, _signature(self.body), SECRET))

    def test_wrong_secret_or_body_rejected(self):
        self.assertFalse(verify_webhook_signature(self.body, _signature(self.body, 'other'), SECRET))
        self.assertFalse(verify_webhook_signature(self.body + b' ', _signature(self.body), SECRET))

    def test_stale_timestamp_rejected(self):
        old = int(time.time()) - 3600
        self.assertFalse(verify_webhook_signature(self.body, _signature(self.body, t=old), SECRET))

    def test_missing_secret_or_header_fails_closed(self):
        self.assertFalse(verify_webhook_signature(self.body, _signature(self.body), ''))
        self.assertFalse(verify_webhook_signature(self.body, '', SECRET))
        self.assertFalse(verify_webhook_signature(self.body, 'garbage', SECRET))

    def test_any_v1_may_match(self):
        t = int(time.time())
        good = _signature(self.body, t=t).split(',')[1]
        self.assertTrue(verify_webhook_signature(self.body, f't={t},v1=deadbeef,{good}', SECRET))


class ClientErrorTests(SimpleTestCase):
    def _client(self, status, payload):
        response = mock.Mock(status_code=status, ok=200 <= status < 300)
        response.json.return_value = payload
        session = mock.Mock()
        session.request.return_value = response
        return VexPayClient(api_key='k', base_url='https://x', session=session)

    def test_post_5xx_is_ambiguous(self):
        with self.assertRaises(VexPayAmbiguousError):
            self._client(502, {'error': 'processor_unavailable'}).c2p_request(
                usd_amount=Decimal('10'), debtor_id='V1', debtor_phone='58', debtor_bank_code=102,
                external_ref='r', onward=vexpay.OnwardPayout('BEP20', ADDRESS))

    def test_4xx_carries_code_and_message(self):
        with self.assertRaises(VexPayError) as ctx:
            self._client(422, {'error': 'insufficient_balance', 'message': ['a', 'b']}).get_payment('p')
        self.assertEqual(ctx.exception.code, 'insufficient_balance')
        self.assertEqual(ctx.exception.status, 422)
        self.assertNotIsInstance(ctx.exception, VexPayAmbiguousError)

    def test_post_transport_failure_is_ambiguous(self):
        import requests
        session = mock.Mock()
        session.request.side_effect = requests.ConnectionError('reset')
        client = VexPayClient(api_key='k', base_url='https://x', session=session)
        with self.assertRaises(VexPayAmbiguousError):
            client.pago_movil_verify(usd_amount=Decimal('1'), reference='1234', external_ref='r',
                                     onward=vexpay.OnwardPayout('BEP20', ADDRESS))

    def test_post_success_with_unreadable_body_is_ambiguous(self):
        client = self._client(201, None)
        client.session.request.return_value.json.side_effect = ValueError
        with self.assertRaises(VexPayAmbiguousError):
            client.c2p_request(usd_amount=Decimal('10'), debtor_id='V1', debtor_phone='58', debtor_bank_code=102,
                               external_ref='r', onward=vexpay.OnwardPayout('BEP20', ADDRESS))

    def test_idempotency_key_is_sent(self):
        client = self._client(201, {'paymentId': 'p'})
        client.c2p_request(usd_amount=Decimal('10'), debtor_id='V1', debtor_phone='58', debtor_bank_code=102,
                           external_ref='r', onward=vexpay.OnwardPayout('BEP20', ADDRESS), idempotency_key='k-1')
        self.assertEqual(client.session.request.call_args.kwargs['headers']['Idempotency-Key'], 'k-1')

    def test_unconfigured_client_refuses(self):
        with self.assertRaises(VexPayError):
            VexPayClient(api_key='').get_payment('p')


class NormalizationTests(SimpleTestCase):
    def test_cedula(self):
        self.assertEqual(vexpay.normalize_cedula('v-12.345.678'), 'V12345678')
        self.assertEqual(vexpay.normalize_cedula('12345678'), 'V12345678')
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.normalize_cedula('X1')

    def test_phone(self):
        for raw in ('0414 1234567', '+58 414-123-4567', '584141234567', '4141234567'):
            self.assertEqual(vexpay.normalize_phone(raw), '584141234567')
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.normalize_phone('3001234567')  # Colombian mobile

    def test_bank_code(self):
        self.assertEqual(vexpay.normalize_bank_code('0134'), 134)
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.normalize_bank_code('')

    def test_estimate(self):
        terms = {'payin_fee_percent': '2', 'spread_percent': '1.5', 'payout_fee_usdt': '0.75'}
        # 100 * 0.98 / 1.015 - 0.75 = 95.80...
        self.assertEqual(vexpay.estimate_usdt(Decimal('100'), terms), Decimal('95.80'))


class VexPayRampTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='vexpay-user', firebase_uid='vexpay-user')

    def _ramp(self, **overrides):
        values = dict(
            provider='vexpay', direction='on_ramp', status='PENDING', country_code='VE',
            actor_user=self.user, actor_address=ADDRESS, destination='cusd_plus',
            fiat_currency='VES', crypto_currency='USDT', final_currency='USDT BSC',
            crypto_amount_estimated=Decimal('18.90'),
            metadata={'vexpay': {'method': 'c2p', 'usd_amount': '20.00', 'intent_id': 'int-1',
                                 'payer': {'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': 134}}},
        )
        values.update(overrides)
        ramp = RampTransaction(**values)
        ramp.external_id = str(ramp.internal_id)
        ramp.save()
        return ramp

    def test_payment_pending_stays_pending(self):
        ramp = vexpay.apply_payment(self._ramp(), _payment('PENDING'))
        self.assertEqual((ramp.status, ramp.status_detail), ('PENDING', 'awaiting_payment'))
        self.assertEqual(ramp.provider_order_id, 'pay-1')

    def test_completed_payment_converting_is_processing(self):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'converting'))
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'onward_converting'))
        self.assertEqual(ramp.fiat_amount, Decimal('20280'))

    def test_onward_completed_completes_and_exposes_tx_hash(self):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'completed'))
        self.assertEqual(ramp.status, 'COMPLETED')
        self.assertIsNotNone(ramp.completed_at)
        self.assertEqual(ramp.crypto_amount_actual, Decimal('18.94'))
        # The BSC arrival scanner proves delivery from this hash.
        self.assertEqual(find_provider_tx_hash(ramp.metadata), TX_HASH)

    def test_failed_payment_fails(self):
        ramp = vexpay.apply_payment(self._ramp(), _payment('FAILED', failureCode='51'))
        self.assertEqual(ramp.status, 'FAILED')
        self.assertIn('51', ramp.status_detail)

    @mock.patch('ramps.vexpay._alert')
    def test_held_onward_never_shows_failure_and_alerts_once(self, alert):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'held', ))
        self.assertEqual(ramp.status, 'PROCESSING')
        self.assertTrue(ramp.status_detail.startswith('needs_review:onward_held'))
        vexpay.apply_payment(ramp, _payment('COMPLETED', 'held'))
        alert.assert_called_once()

    @mock.patch('ramps.vexpay._alert')
    def test_reversal_after_payout_keeps_delivery(self, alert):
        payment = _payment('REVERSED', 'completed')
        ramp = vexpay.apply_payment(self._ramp(status='PROCESSING'), payment)
        self.assertEqual(ramp.status, 'PROCESSING')
        self.assertEqual(ramp.status_detail, 'needs_review:reversed_after_payout')
        alert.assert_called_once()

    def test_final_status_is_monotonic(self):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'completed'))
        ramp = vexpay.apply_payment(ramp, _payment('FAILED'))
        self.assertEqual(ramp.status, 'COMPLETED')

    def test_unverified_pago_movil_waits_days_without_polling(self):
        # Nothing exists at VEXPay before the reference is verified.
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20'}})
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(days=3))
        client = mock.Mock()
        self.assertEqual(vexpay.sync_vexpay_ramp(ramp, client).status, 'PENDING')
        client.get_payment_by_ref.assert_not_called()

    def test_unverified_pago_movil_closes_inside_the_attribution_window(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20'}})
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(days=11))
        ramp = vexpay.sync_vexpay_ramp(ramp, mock.Mock())
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'expired_unpaid'))

    @mock.patch('ramps.bsc_provider_hash.attach_after_provider_sync')
    def test_settled_orders_are_rechecked_hourly_for_reversals(self, _attach):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'completed'))
        RampTransaction.objects.filter(pk=ramp.pk).update(metadata={**ramp.metadata, 'bsc_arrival_tx_hash': TX_HASH})
        ramp.refresh_from_db()
        self.assertIn(ramp.pk, vexpay.open_ramps().values_list('pk', flat=True))
        ramp = vexpay.apply_payment(ramp, _payment('COMPLETED', 'completed'))  # stamps the check
        self.assertFalse(vexpay.due_for_sync(ramp))

    def test_delivered_but_uncredited_order_is_resumed(self):
        ramp = self._ramp(status='COMPLETED', completed_at=timezone.now())
        self.assertEqual(vexpay.active_order(self.user).pk, ramp.pk)

    def test_c2p_without_any_intent_expires(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'c2p', 'usd_amount': '20'}})
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(hours=1))
        client = mock.Mock()
        client.get_payment_by_ref.side_effect = VexPayError('nf', status=404)
        ramp = vexpay.sync_vexpay_ramp(ramp, client)
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'expired_unpaid'))

    def test_preparing_order_is_not_confirmable_until_prepared(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'phase': 'preparing'}})
        self.assertFalse(vexpay.can_confirm(ramp))
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay._claim(ramp, 'pago_movil')
        self.assertTrue(vexpay.can_confirm(vexpay.mark_prepared(ramp)))

    def test_failed_preparation_cannot_close_a_confirmable_order(self):
        ramp = self._ramp()  # phase created
        self.assertEqual(vexpay.fail_preparation(ramp, 'start_failed').status, 'PENDING')

    def test_poll_during_submission_changes_nothing(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'c2p', 'usd_amount': '20', 'intent_id': 'i',
                                               'phase': 'submitting',
                                               'submitting_since': timezone.now().isoformat()}})
        ramp = vexpay.apply_payment(ramp, _payment('PENDING'))
        self.assertEqual(ramp.status, 'PENDING')
        self.assertEqual(ramp.metadata['vexpay']['phase'], 'submitting')

    def test_lost_c2p_request_recovers_the_intent(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'c2p', 'usd_amount': '20', 'phase': 'preparing'}})
        ramp = vexpay.apply_payment(ramp, _payment('PENDING'))
        self.assertEqual(ramp.metadata['vexpay']['intent_id'], 'pay-1')
        self.assertTrue(vexpay.can_confirm(ramp))

    @mock.patch('ramps.bsc_provider_hash.attach_after_provider_sync')
    def test_completed_orders_keep_retrying_arrival_proof(self, attach):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'completed'))
        vexpay.apply_payment(ramp, _payment('COMPLETED', 'completed'))
        self.assertEqual(attach.call_count, 2)
        self.assertIn(ramp.pk, vexpay.open_ramps().values_list('pk', flat=True))

    @mock.patch('ramps.vexpay._alert')
    @mock.patch('ramps.bsc_provider_hash.attach_after_provider_sync')
    def test_completed_order_takes_late_hash_and_reversal(self, _attach, alert):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'completed'))
        late = _payment('REVERSED', 'completed')
        late['onwardPayout']['txHash'] = '0x' + 'cd' * 32
        ramp = vexpay.apply_payment(ramp, late)
        self.assertEqual(ramp.status, 'COMPLETED')
        self.assertEqual(ramp.status_detail, 'needs_review:reversed_after_payout')
        self.assertEqual(ramp.metadata['vexpay']['onward']['txHash'], '0x' + 'cd' * 32)
        alert.assert_called_once()

    def test_disabled_ves_conversions_are_unavailable(self):
        from django.core.cache import cache
        cache.delete(vexpay.FEE_TERMS_CACHE_KEY)
        client = mock.Mock()
        client.conversion_settings.return_value = {'enabled': True, 'sourceCurrencies': {'VES': False},
                                                   'spreadPercent': {'VES': '1.5'}, 'minimumUsdt': '1'}
        client.crypto_networks.return_value = [{'network': 'BEP20', 'payoutFee': '0.75', 'minPayout': '1',
                                                'available': True, 'payoutEnabled': True}]
        client.balance.return_value = {'feePercent': '2'}
        client.quote_usd.return_value = {'rateSource': 'MARKET'}
        self.assertFalse(vexpay.fee_terms(client)['payout_available'])
        cache.delete(vexpay.FEE_TERMS_CACHE_KEY)

    def test_fixed_pay_in_fee_is_in_the_minimum(self):
        terms = {'payin_fee_percent': '2', 'payin_fee_fixed_usd': '0.50', 'spread_percent': '1.5',
                 'payout_fee_usdt': '0.75', 'minimum_conversion_usdt': '10', 'minimum_payout_usdt': '10'}
        minimum = vexpay.provider_minimum_usd(terms)
        # At the minimum, the converted USDT still clears payout fee + minimum.
        self.assertGreaterEqual(vexpay._converted_usdt(minimum, terms), Decimal('10.75'))

    def test_interrupted_preparation_frees_the_slot(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'phase': 'preparing'}})
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(minutes=10))
        ramp = vexpay.sync_vexpay_ramp(ramp, mock.Mock())
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'preparation_interrupted'))

    def test_old_submitting_orders_stay_reconciled(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'phase': 'submitting'}})
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(days=30))
        self.assertIn(ramp.pk, vexpay.open_ramps().values_list('pk', flat=True))

    def test_verify_asks_for_the_shown_bolivares_at_todays_rate(self):
        client = mock.Mock()
        client.quote_usd.return_value = {'rate': 1020}
        # Shown 20,100 Bs when the rate was 1,000; today 20,100 Bs = $19.70.
        self.assertEqual(vexpay.verify_usd_amount({'usd_amount': '20', 'expected_ves': '20100'}, client),
                         Decimal('19.70'))

    def test_rate_lookup_failure_before_verify_is_not_ambiguous(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20',
                                               'expected_ves': '20100', 'payer': {}}})
        client = mock.Mock()
        client.quote_usd.side_effect = VexPayError('down', status=503)
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.verify_pago_movil(ramp, '12345678', client)
        ramp.refresh_from_db()
        self.assertTrue(vexpay.can_confirm(ramp))
        client.pago_movil_verify.assert_not_called()

    @mock.patch('ramps.vexpay._alert')
    def test_lost_verification_is_replayed_then_escalated(self, alert):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '12345678',
            'attempt': 1, 'payer': {'phone': '584141234567', 'bank_code': 134}}})
        RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        client = mock.Mock()
        client.get_payment_by_ref.side_effect = VexPayError('nf', status=404)
        client.pago_movil_verify.side_effect = VexPayError('nf', status=404)
        client.quote_usd.return_value = {'rate': 1020}
        vexpay.sync_vexpay_ramp(ramp, client)
        kwargs = client.pago_movil_verify.call_args.kwargs
        # A fresh key: the original would only replay a cached 404.
        self.assertEqual(kwargs['idempotency_key'], f'{ramp.external_id}:verify:1:replay1')
        self.assertEqual(kwargs['usd_amount'], Decimal('20'))  # no expected_ves: the order's own amount
        RampTransaction.objects.filter(pk=ramp.pk).update(metadata={**RampTransaction.objects.get(pk=ramp.pk).metadata,
            'vexpay': {**RampTransaction.objects.get(pk=ramp.pk).metadata['vexpay'], 'verify_retries': 5}})
        ramp = vexpay.sync_vexpay_ramp(ramp, client)
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'needs_review:verification_lost'))
        alert.assert_called_once()

    def test_interrupted_verify_still_has_its_reference(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'payer': {}}})
        ramp = vexpay._claim(ramp, 'pago_movil', reference='12345678')
        self.assertEqual(ramp.metadata['vexpay']['reference'], '12345678')
        self.assertEqual(ramp.metadata['vexpay']['phase'], 'submitting')

    def test_failed_alert_is_retried_until_delivered(self):
        ramp = self._ramp(status='PROCESSING')
        RampTransaction.objects.filter(pk=ramp.pk).update(status_detail='needs_review:onward_held:x')
        ramp.refresh_from_db()
        with mock.patch('config.ops_alerts.send_ops_alert', return_value=False) as send:
            vexpay.ensure_alerted(ramp)
            vexpay.ensure_alerted(RampTransaction.objects.get(pk=ramp.pk))
        self.assertEqual(send.call_count, 2)  # not recorded, so retried
        with mock.patch('config.ops_alerts.send_ops_alert', return_value=True) as send:
            vexpay.ensure_alerted(RampTransaction.objects.get(pk=ramp.pk))
            vexpay.ensure_alerted(RampTransaction.objects.get(pk=ramp.pk))
        self.assertEqual(send.call_count, 1)  # delivered once, then remembered

    def test_movement_not_found_is_retried_inline_then_succeeds(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'payer': {}}})
        client = mock.Mock()
        not_found = VexPayError('MOVEMENT_NOT_FOUND', status=400, payload={'failureCode': 'MOVEMENT_NOT_FOUND'})
        client.pago_movil_verify.side_effect = [not_found, _payment('COMPLETED', 'converting')]
        ramp = vexpay.verify_pago_movil(ramp, '12345678', client, wait=lambda s: None)
        self.assertEqual(ramp.status, 'PROCESSING')
        keys = [c.kwargs['idempotency_key'] for c in client.pago_movil_verify.call_args_list]
        self.assertEqual(len(set(keys)), 2)  # fresh key per try

    def test_unmatched_verification_is_reopened_only_by_a_direct_answer(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '1234',
            'attempt': 1, 'payer': {}}})
        # A looked-up failure never reopens an order whose outcome is unknown.
        ramp = vexpay.apply_payment(ramp, _payment('FAILED', failureCode='MOVEMENT_NOT_FOUND'))
        self.assertEqual(ramp.status, 'PROCESSING')
        # The replay's own direct answer does.
        RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        client = mock.Mock()
        client.get_payment_by_ref.return_value = _payment('FAILED', failureCode='MOVEMENT_NOT_FOUND')
        client.pago_movil_verify.side_effect = VexPayError(
            'MOVEMENT_NOT_FOUND', status=400, payload={'failureCode': 'MOVEMENT_NOT_FOUND'})
        ramp = vexpay.sync_vexpay_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        self.assertEqual((ramp.status, ramp.status_detail), ('PENDING', 'verify_movement_not_found'))
        self.assertTrue(vexpay.can_confirm(ramp))

    def test_lost_retry_behind_a_rejected_try_is_replayed_then_escalated(self):
        # Try A was rejected by the bank (answered directly); try B's request
        # was lost, so the lookup keeps returning A.
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '1234',
            'attempt': 2, 'payer': {}, 'known_failed_ids': ['pay-A']}})
        client = mock.Mock()
        client.get_payment_by_ref.return_value = _payment('FAILED', paymentId='pay-A', failureCode='BANK_REJECTED')
        client.pago_movil_verify.side_effect = VexPayAmbiguousError('timeout')
        for _ in range(vexpay.VERIFY_MAX_RETRIES + 1):
            RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=timezone.now() - timedelta(hours=1))
            ramp = vexpay.sync_vexpay_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
            self.assertEqual(ramp.status, 'PROCESSING')
        self.assertEqual(client.pago_movil_verify.call_count, vexpay.VERIFY_MAX_RETRIES)
        self.assertEqual(ramp.status_detail, 'needs_review:verification_lost')

    def test_looked_up_rejection_never_closes_an_in_doubt_submission(self):
        # Try A's rejection carried no id; try B (4 s later) timed out. The
        # lookup's A cannot be told apart from B by time: replay instead.
        now = timezone.now()
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '1234',
            'attempt': 2, 'payer': {}, 'last_request_at': now.isoformat()}})
        RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=now - timedelta(hours=1))
        client = mock.Mock()
        client.get_payment_by_ref.return_value = _payment(
            'FAILED', paymentId='pay-A', failureCode='BANK_REJECTED',
            createdAt=(now - timedelta(seconds=4)).isoformat())
        client.pago_movil_verify.return_value = _payment('COMPLETED', 'converting', paymentId='pay-B')
        ramp = vexpay.sync_vexpay_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        self.assertEqual((ramp.status, ramp.provider_order_id), ('PROCESSING', ''))
        # The next due poll replays; the replay's own answer settles it.
        RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=now - timedelta(hours=1))
        ramp = vexpay.sync_vexpay_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        self.assertEqual((ramp.status, ramp.provider_order_id), ('PROCESSING', 'pay-B'))

    def test_direct_rejection_still_closes(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted'}})
        ramp = vexpay.apply_payment(ramp, _payment('FAILED', paymentId='pay-A', failureCode='BANK_REJECTED'),
                                    direct=True)
        self.assertEqual(ramp.status, 'FAILED')

    def test_payment_date_is_absolute(self):
        today = vexpay._bank_today()
        self.assertEqual(vexpay.parse_payment_date(''), today.isoformat())
        yesterday = (today - timedelta(days=1)).isoformat()
        self.assertEqual(vexpay.parse_payment_date(yesterday), yesterday)
        for bad in ((today + timedelta(days=3)).isoformat(), (today - timedelta(days=30)).isoformat(), 'ayer'):
            with self.assertRaises(vexpay.VexPayRampError):
                vexpay.parse_payment_date(bad)

    def test_superseded_failed_try_cannot_reopen_an_accepted_payment(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted'}},
                          status='PROCESSING')
        ramp = vexpay.apply_payment(ramp, _payment('COMPLETED', 'converting', paymentId='pay-B'))
        self.assertEqual((ramp.status, ramp.provider_order_id), ('PROCESSING', 'pay-B'))
        ramp = vexpay.apply_payment(ramp, _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND'))
        self.assertEqual(ramp.status, 'PROCESSING')
        self.assertFalse(vexpay.can_confirm(ramp))

    def test_superseded_bank_rejection_cannot_close_an_accepted_payment(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted'}},
                          status='PROCESSING')
        ramp = vexpay.apply_payment(ramp, _payment('COMPLETED', 'converting', paymentId='pay-B'))
        for code in ('BANK_REJECTED', ''):
            ramp = vexpay.apply_payment(ramp, _payment('FAILED', paymentId='pay-A', failureCode=code))
            self.assertEqual((ramp.status, ramp.provider_order_id), ('PROCESSING', 'pay-B'))
        ramp = vexpay.apply_payment(ramp, _payment('CANCELED', paymentId='pay-A'))
        self.assertEqual(ramp.status, 'PROCESSING')
        ramp = vexpay.apply_payment(ramp, _payment('COMPLETED', 'completed', paymentId='pay-B'))
        self.assertEqual(ramp.status, 'COMPLETED')

    def test_unaccepted_pago_movil_follows_the_latest_try(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '1234'}})
        ramp = vexpay.apply_payment(ramp, _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND'))
        self.assertEqual(ramp.provider_order_id, '')  # a failed try is never pinned
        vexpay._update(ramp.pk, phase='submitted')
        client = mock.Mock()
        client.get_payment_by_ref.return_value = _payment('COMPLETED', 'converting', paymentId='pay-B')
        ramp = vexpay.sync_vexpay_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        client.get_payment.assert_not_called()
        self.assertEqual((ramp.status, ramp.provider_order_id), ('PROCESSING', 'pay-B'))

    def test_stale_failed_try_cannot_reopen_a_newer_submission(self):
        now = timezone.now()
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted',
            'submitting_since': now.isoformat()}})
        old_try = _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND',
                           createdAt=(now - timedelta(minutes=3)).isoformat())
        ramp = vexpay.apply_payment(ramp, old_try)
        self.assertEqual(ramp.status, 'PROCESSING')
        self.assertFalse(vexpay.can_confirm(ramp))

    def test_pinned_try_that_fails_is_unpinned(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted'}})
        ramp = vexpay.apply_payment(ramp, _payment('COMPLETED', 'converting', paymentId='pay-A'))
        self.assertEqual(ramp.provider_order_id, 'pay-A')
        # VEXPay later reports that same attempt unmatched (it was not final).
        RampTransaction.objects.filter(pk=ramp.pk).update(status='PROCESSING')
        ramp = vexpay.apply_payment(ramp, _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND'))
        self.assertEqual(ramp.provider_order_id, '')
        self.assertNotIn('accepted_payment_id', ramp.metadata['vexpay'])

    def test_pending_pago_movil_try_is_not_pinned(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted'}})
        ramp = vexpay.apply_payment(ramp, _payment('PENDING', paymentId='pay-A'))
        self.assertEqual(ramp.provider_order_id, '')

    def test_lost_retry_behind_a_stale_failure_is_replayed(self):
        now = timezone.now()
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '1234',
            'attempt': 2, 'submitting_since': now.isoformat(), 'payer': {}}})
        RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=now - timedelta(hours=1))
        client = mock.Mock()
        client.get_payment_by_ref.return_value = _payment(
            'FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND',
            createdAt=(now - timedelta(minutes=5)).isoformat())
        client.pago_movil_verify.return_value = _payment('COMPLETED', 'converting', paymentId='pay-B')
        ramp = vexpay.sync_vexpay_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        client.pago_movil_verify.assert_called_once()
        self.assertEqual((ramp.status, ramp.provider_order_id), ('PROCESSING', 'pay-B'))

    def test_attempt_numbers_are_unique(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'c2p', 'usd_amount': '20', 'intent_id': 'i', 'attempt': 3}})
        stale_copy = RampTransaction.objects.get(pk=ramp.pk)
        vexpay._update(ramp.pk, attempt=4)  # another request claimed and released meanwhile
        claimed = vexpay._claim(stale_copy, 'c2p')
        self.assertEqual(claimed.metadata['vexpay']['attempt'], 5)

    def test_earlier_inline_failure_cannot_resolve_a_later_ambiguous_try(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'payer': {}}})
        client = mock.Mock()
        first = VexPayError('MOVEMENT_NOT_FOUND', status=400,
                            payload={'failureCode': 'MOVEMENT_NOT_FOUND', 'paymentId': 'pay-A'})
        client.pago_movil_verify.side_effect = [first, VexPayAmbiguousError('timeout')]
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.verify_pago_movil(ramp, '12345678', client, wait=lambda s: None)
        ramp = RampTransaction.objects.get(pk=ramp.pk)
        self.assertEqual(ramp.status, 'PROCESSING')
        # A lookup now returns the FIRST try's failure: it must not reopen.
        ramp = vexpay.apply_payment(ramp, _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND',
                                                   createdAt=timezone.now().isoformat()))
        self.assertEqual(ramp.status, 'PROCESSING')
        self.assertFalse(vexpay.can_confirm(ramp))

    def test_replay_refuses_once_another_attempt_moved_on(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '1234',
            'attempt': 1, 'payer': {}}})
        RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        stale = RampTransaction.objects.get(pk=ramp.pk)
        vexpay._update(ramp.pk, attempt=2)  # the user confirmed again meanwhile
        client = mock.Mock()
        vexpay._retry_lost_verification(stale, client)
        client.pago_movil_verify.assert_not_called()

    def test_known_failed_try_triggers_bounded_recovery(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {
            'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted', 'reference': '1234',
            'attempt': 1, 'known_failed_ids': ['pay-A'], 'payer': {}}})
        RampTransaction.objects.filter(pk=ramp.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        client = mock.Mock()
        client.get_payment_by_ref.return_value = _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND')
        client.pago_movil_verify.side_effect = VexPayError('nf', status=400)
        vexpay.sync_vexpay_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        client.pago_movil_verify.assert_called_once()

    def test_reconciled_failure_is_remembered_before_the_next_attempt(self):
        ramp = self._ramp(status='PROCESSING', metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20',
                                                                    'phase': 'submitted'}})
        ramp = vexpay.apply_payment(ramp, _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND'))
        self.assertIn('pay-A', ramp.metadata['vexpay']['known_failed_ids'])
        vexpay._update(ramp.pk, phase='submitted', status='PROCESSING')  # attempt B, outcome unknown
        ramp = vexpay.apply_payment(RampTransaction.objects.get(pk=ramp.pk),
                                    _payment('FAILED', paymentId='pay-A', failureCode='MOVEMENT_NOT_FOUND'))
        self.assertEqual(ramp.status, 'PROCESSING')

    def test_old_processing_orders_stay_reconciled(self):
        ramp = self._ramp(status='PROCESSING')
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(days=30))
        self.assertIn(ramp.pk, vexpay.open_ramps().values_list('pk', flat=True))

    def test_bcv_priced_account_is_unavailable(self):
        from django.core.cache import cache
        cache.delete(vexpay.FEE_TERMS_CACHE_KEY)
        client = mock.Mock()
        client.conversion_settings.return_value = {'enabled': True, 'sourceCurrencies': {'VES': True},
                                                   'spreadPercent': {'VES': '1.5'}, 'minimumUsdt': '1'}
        client.crypto_networks.return_value = [{'network': 'BEP20', 'payoutFee': '0.75', 'minPayout': '1',
                                                'available': True, 'payoutEnabled': True}]
        client.balance.return_value = {'feePercent': '2'}
        client.quote_usd.return_value = {'rateSource': 'BCV'}
        self.assertFalse(vexpay.fee_terms(client)['payout_available'])
        cache.delete(vexpay.FEE_TERMS_CACHE_KEY)

    def test_submitted_pago_movil_is_never_expired(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'phase': 'submitted'}},
                          status='PROCESSING')
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(days=2))
        client = mock.Mock()
        client.get_payment_by_ref.side_effect = VexPayError('nf', status=404)
        self.assertEqual(vexpay.sync_vexpay_ramp(ramp, client).status, 'PROCESSING')

    def test_only_one_confirmation_can_be_in_flight(self):
        ramp = self._ramp()
        vexpay._claim(ramp, 'c2p')
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay._claim(ramp, 'c2p')

    def test_c2p_pending_after_execute_is_processing_and_closed(self):
        ramp = self._ramp()
        client = mock.Mock()
        client.c2p_execute.return_value = _payment('PENDING')
        ramp = vexpay.execute_c2p(ramp, '123456', client)
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'bank_confirming'))
        self.assertFalse(vexpay.can_confirm(ramp))

    def test_late_ambiguity_never_reopens_a_completed_order(self):
        ramp = vexpay.apply_payment(self._ramp(), _payment('COMPLETED', 'completed'))
        ramp = vexpay._mark_ambiguous(ramp, 'c2p_execute_ambiguous')
        self.assertEqual(ramp.status, 'COMPLETED')

    def test_verify_keeps_evidence_written_meanwhile(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'payer': {
            'cedula': 'V1', 'phone': '584141234567', 'bank_code': 134}}})
        client = mock.Mock()

        def verify(**kwargs):
            # A webhook-driven sync lands while the verify call is in flight.
            RampTransaction.objects.filter(pk=ramp.pk).update(
                metadata={**RampTransaction.objects.get(pk=ramp.pk).metadata, 'bsc_arrival_tx_hash': TX_HASH})
            return _payment('COMPLETED', 'converting')
        client.pago_movil_verify.side_effect = verify
        ramp = vexpay.verify_pago_movil(ramp, '12345678', client)
        self.assertEqual(ramp.metadata.get('bsc_arrival_tx_hash'), TX_HASH)
        self.assertEqual(ramp.metadata['vexpay']['reference'], '12345678')

    def test_rejected_reference_can_be_corrected(self):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '20', 'payer': {}}})
        client = mock.Mock()
        client.pago_movil_verify.side_effect = VexPayError('nf', status=404)
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.verify_pago_movil(ramp, '12345678', client)
        ramp.refresh_from_db()
        self.assertTrue(vexpay.can_confirm(ramp))

    @mock.patch('ramps.vexpay._alert')
    def test_overpayment_counts_in_limits_and_alerts(self, alert):
        ramp = self._ramp(metadata={'vexpay': {'method': 'pago_movil', 'usd_amount': '5'}})
        ramp = vexpay.apply_payment(ramp, _payment('COMPLETED', 'converting', usdAmount=150))
        self.assertEqual(vexpay.counted_usd(ramp), Decimal('150'))
        alert.assert_called_once()

    def test_cancel_only_before_submission(self):
        ramp = vexpay.cancel_on_ramp(self._ramp())
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'cancelled_by_user'))
        submitted = self._ramp(status='PROCESSING', metadata={'vexpay': {'method': 'c2p', 'phase': 'submitted'}})
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.cancel_on_ramp(submitted)

    def test_provider_minimum(self):
        terms = {'payin_fee_percent': '2', 'spread_percent': '1.5', 'payout_fee_usdt': '0.75',
                 'minimum_conversion_usdt': '10', 'minimum_payout_usdt': '10'}
        # needs 10.75 USDT before the payout fee → 10.75 * 1.015 / 0.98 = 11.14
        self.assertEqual(vexpay.provider_minimum_usd(terms), Decimal('11.14'))
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.check_provider_minimums(Decimal('11'), terms)
        vexpay.check_provider_minimums(Decimal('11.14'), terms)

    def test_execute_ambiguous_never_asks_for_a_second_token(self):
        ramp = self._ramp()
        client = mock.Mock()
        client.c2p_execute.side_effect = VexPayAmbiguousError('timeout')
        ramp = vexpay.execute_c2p(ramp, '123456', client)
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'c2p_execute_ambiguous'))
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.execute_c2p(ramp, '123456', client)

    def test_execute_sends_onward_payout_to_wallet(self):
        ramp = self._ramp()
        client = mock.Mock()
        client.c2p_execute.return_value = _payment('COMPLETED', 'converting')
        vexpay.execute_c2p(ramp, '123456', client)
        kwargs = client.c2p_execute.call_args.kwargs
        self.assertEqual(kwargs['onward'].address, ADDRESS)
        self.assertEqual(kwargs['onward'].network, 'BEP20')
        self.assertEqual(kwargs['external_ref'], ramp.external_id)

    @override_settings(VE_PAGOMOVIL_TOPUP_MIN_USD='5', VE_PAGOMOVIL_TOPUP_MAX_USD='100',
                       VE_PAGOMOVIL_TOPUP_USER_DAILY_USD='50', VE_PAGOMOVIL_TOPUP_GLOBAL_DAILY_USD='1000')
    def test_limits(self):
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.check_limits(self.user, Decimal('4'))
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.check_limits(self.user, Decimal('101'))
        self._ramp(status='COMPLETED', metadata={'vexpay': {'usd_amount': '40'}})
        self._ramp(status='FAILED', metadata={'vexpay': {'usd_amount': '40'}})  # never counted
        vexpay.check_limits(self.user, Decimal('10'))
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.check_limits(self.user, Decimal('11'))

    @override_settings(VE_PAGOMOVIL_TOPUP_MIN_USD='5', VE_PAGOMOVIL_TOPUP_MAX_USD='100',
                       VE_PAGOMOVIL_TOPUP_USER_DAILY_USD='50', VE_PAGOMOVIL_TOPUP_GLOBAL_DAILY_USD='1000')
    def test_old_orders_paid_or_payable_today_count(self):
        old = timezone.now() - timedelta(days=3)
        paid = self._ramp(status='COMPLETED', metadata={'vexpay': {'usd_amount': '20'}})
        payable = self._ramp(status='PENDING', metadata={'vexpay': {'usd_amount': '20'}})
        stale = self._ramp(status='COMPLETED', metadata={'vexpay': {'usd_amount': '40'}})
        RampTransaction.objects.filter(pk__in=[paid.pk, payable.pk, stale.pk]).update(created_at=old)
        RampTransaction.objects.filter(pk=paid.pk).update(completed_at=timezone.now())
        RampTransaction.objects.filter(pk=stale.pk).update(completed_at=old)
        vexpay.check_limits(self.user, Decimal('10'))  # 20 + 20 + 10; the stale 40 is out
        with self.assertRaises(vexpay.VexPayRampError):
            vexpay.check_limits(self.user, Decimal('11'))

    def test_proven_but_unlinked_order_stays_polled_for_30_days(self):
        ramp = self._ramp(status='COMPLETED', metadata={'bsc_arrival_tx_hash': TX_HASH, 'vexpay': {}})
        RampTransaction.objects.filter(pk=ramp.pk).update(completed_at=timezone.now() - timedelta(days=8))
        self.assertIn(ramp.pk, list(vexpay.open_ramps().values_list('pk', flat=True)))

    def test_reserve_refuses_a_second_pending_order(self):
        self._ramp()
        account = SimpleNamespace(pk=1, bsc_address=ADDRESS, display_name='')
        locked = mock.Mock(bsc_address=ADDRESS)
        with mock.patch('users.models.Account.objects') as accounts:
            accounts.select_for_update.return_value.filter.return_value.first.return_value = locked
            with self.assertRaises(vexpay.VexPayRampError):
                vexpay.reserve_on_ramp(user=self.user, account=account, usd_amount=Decimal('20'),
                                       method='c2p', payer={}, terms={'payin_fee_percent': '2',
                                       'spread_percent': '1.5', 'payout_fee_usdt': '0.75'})


@override_settings(VEXPAY_WEBHOOK_SECRET=SECRET)
class WebhookTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        user = get_user_model().objects.create(username='vexpay-hook', firebase_uid='vexpay-hook')
        self.ramp = RampTransaction.objects.create(
            provider='vexpay', direction='on_ramp', status='PENDING', actor_user=user,
            actor_address=ADDRESS, destination='cusd_plus', provider_order_id='pay-1')

    def _post(self, body: dict, *, signature=None, event_id='evt-1'):
        raw = json.dumps(body).encode()
        return vexpay_webhook(self.factory.post(
            '/api/vexpay/webhook/', data=raw, content_type='application/json',
            HTTP_VEXPAY_SIGNATURE=signature if signature is not None else _signature(raw),
            HTTP_VEXPAY_EVENT_ID=event_id,
        ))

    def test_invalid_signature_rejected(self):
        response = self._post({'event': 'payment.completed'}, signature='t=1,v1=00')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RampWebhookEvent.objects.exists())

    @mock.patch('ramps.tasks.sync_ve_pagomovil_order.delay')
    def test_event_stored_once_and_enqueued(self, delay):
        body = {'event': 'onward_payout.updated', 'data': {'paymentId': 'pay-1'}}
        self.assertEqual(self._post(body).status_code, 200)
        delay.assert_called_once_with(self.ramp.pk)
        duplicate = self._post(body)
        self.assertTrue(json.loads(duplicate.content)['duplicate'])
        self.assertEqual(delay.call_count, 1)

    @mock.patch('ramps.tasks.sync_ve_pagomovil_order.delay', side_effect=RuntimeError('broker down'))
    def test_enqueue_failure_still_acknowledges(self, _delay):
        body = {'event': 'payment.completed', 'data': {'paymentId': 'pay-1'}}
        self.assertEqual(self._post(body, event_id='evt-2').status_code, 200)


class BankMessageTests(SimpleTestCase):
    def test_provider_texts_never_reach_users(self):
        from ramps.vexpay_client import VexPayError
        for text in ('VEXPay returned HTTP 401', 'VEXPay request failed (ConnectionError)'):
            self.assertNotIn('VEXPay', vexpay.bank_message(VexPayError(text)))

    def test_strips_vexpay_code_prefix(self):
        exc = VexPayError('ECBG14Es posible que el beneficiario no se encuentre afiliado al servicio de Pago Móvil',
                          status=422, code='ECBG14ES')
        self.assertEqual(vexpay.bank_message(exc),
                         'El banco respondió: Es posible que el beneficiario no se encuentre afiliado al servicio de Pago Móvil')
        exc = VexPayError('ECBG56000000Tarjeta/Telf no Registrado', status=422, code='ECBG56000000TARJETA')
        self.assertEqual(vexpay.bank_message(exc), 'El banco respondió: Tarjeta/Telf no Registrado')

    def test_empty_falls_back(self):
        self.assertIn('no pudo procesar', vexpay.bank_message(VexPayError('', status=422)))


class ClientSupportTests(SimpleTestCase):
    def test_floor_gates_old_builds(self):
        with override_settings(VE_PAGOMOVIL_TOPUP_MIN_APP_VERSION='5.2.8'):
            self.assertTrue(ve_pagomovil.client_supports(ve_pagomovil.TOPUP, {'HTTP_X_CONFIO_VERSION': '5.2.8'}))
            self.assertTrue(ve_pagomovil.client_supports(ve_pagomovil.TOPUP, {'HTTP_X_CONFIO_VERSION': '5.10.0'}))
            self.assertFalse(ve_pagomovil.client_supports(ve_pagomovil.TOPUP, {'HTTP_X_CONFIO_VERSION': '5.2.7'}))
            self.assertFalse(ve_pagomovil.client_supports(ve_pagomovil.TOPUP, {}))

    def test_unset_floor_shows_nobody(self):
        with override_settings(VE_PAGOMOVIL_TOPUP_MIN_APP_VERSION=''):
            self.assertFalse(ve_pagomovil.client_supports(ve_pagomovil.TOPUP, {'HTTP_X_CONFIO_VERSION': '9.9.9'}))
