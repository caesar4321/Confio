import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, RequestFactory, override_settings

from ramps.stereum_client import StereumError
from ramps.stereum_service import build_call, execute, permitted, refresh
from ramps.stereum_views import webhook


@override_settings(STEREUM_TEST_ENABLED=True, STEREUM_ENV='sandbox', STEREUM_API_KEY='key', STEREUM_SECRET_KEY='secret')
class StereumServiceTests(SimpleTestCase):
    def setUp(self):
        atomic = patch('ramps.stereum_service.transaction.atomic')
        atomic.start()
        self.addCleanup(atomic.stop)
        self.user = SimpleNamespace(pk=1, is_active=True, is_superuser=True)
        self.client = Mock(scope='scope', account_id='test-bob-account')
        self.identifier = uuid.uuid4()

    def test_inactive_and_non_admin_cannot_operate(self):
        for active, admin in [(False, True), (True, False)]:
            with self.assertRaises(StereumError):
                permitted(SimpleNamespace(is_active=active, is_superuser=admin))

    @override_settings(STEREUM_TEST_ENABLED=False)
    def test_disabled_integration_blocks_admin(self):
        with self.assertRaises(StereumError):
            permitted(self.user)

    def test_unexpected_recipient_override_is_rejected(self):
        with self.assertRaises(StereumError):
            execute(self.user, 'pay_qr', {'destination_name': 'Attacker'}, self.identifier, client=self.client)
        self.client.send_transfer.assert_not_called()

    @patch('ramps.stereum_service.reference')
    def test_expired_quote_cannot_create_order(self, reference):
        reference.return_value.response_data = {'id': 'quote', 'expireAt': (time.time() - 1) * 1000}
        with self.assertRaises(StereumError):
            build_call(self.user, self.client, 'order', {}, self.identifier)
        self.client.create_order.assert_not_called()

    @patch('ramps.stereum_service.reference')
    def test_qr_recipient_comes_only_from_decoded_data(self, reference):
        reference.return_value.response_data = self.decoded()
        self.client.banks.return_value = [{'type': 'CSL', 'code': 'MLD3046'}]
        build_call(self.user, self.client, 'pay_qr', self.payment(), self.identifier)()
        payload = self.client.send_transfer.call_args.args[0]
        self.assertEqual(payload['destination_name'], 'Decoded Receiver')
        self.assertEqual(payload['destination_account_address'], '123456')
        self.assertEqual(payload['destination_network'], 'CSL')
        self.assertEqual(payload['id_qr'], 'qr-id')
        self.assertEqual(payload['idempotency_key'], str(self.identifier))
        self.assertTrue(self.client.send_transfer.call_args.kwargs['qr'])

    def decoded(self):
        return {'id': 'qr-id', 'currency': 'BOB', 'expiration_date': '2099-01-01', 'amount': '10',
                'bank_code': '3046', 'destination_name': 'Decoded Receiver', 'account_number': '123456',
                'document_number': '987654', 'single_use': False}

    def payment(self):
        return {'decode_request_id': str(uuid.uuid4()), 'amount': '10', 'comment': 'Test payment',
                'sender_name': 'Test Sender', 'sender_document': '111111'}

    @patch('ramps.stereum_service.reference')
    def test_invalid_closed_qr_and_amount_mismatch_block_submission(self, reference):
        for qr_amount in ['NaN', 'invalid', '11']:
            reference.return_value.response_data = {**self.decoded(), 'amount': qr_amount}
            with self.subTest(qr_amount=qr_amount), self.assertRaises(StereumError):
                build_call(self.user, self.client, 'pay_qr', self.payment(), self.identifier)
        self.client.send_transfer.assert_not_called()

    @patch('ramps.stereum_service.reference')
    def test_qr_minimum_and_expiration_are_enforced(self, reference):
        reference.return_value.response_data = {**self.decoded(), 'amount': '0'}
        with self.assertRaises(StereumError):
            build_call(self.user, self.client, 'pay_qr', {**self.payment(), 'amount': '.99'}, self.identifier)
        reference.return_value.response_data = {**self.decoded(), 'expiration_date': '2000-01-01'}
        with self.assertRaises(StereumError):
            build_call(self.user, self.client, 'pay_qr', self.payment(), self.identifier)

    @patch('ramps.stereum_service.reference')
    def test_simulator_requires_explicit_test_resource(self, reference):
        for response in [{}, {'on_main_net': True}, {'on_main_net': 'true'}]:
            reference.return_value.response_data = response
            with self.assertRaises(StereumError):
                build_call(self.user, self.client, 'confirm_charge', {}, self.identifier)
        self.client.confirm_test_charge.assert_not_called()

    @patch('ramps.stereum_service.StereumTestOperation.objects.select_for_update')
    def test_balance_verified_is_not_payment_success(self, get):
        op = get.return_value.get.return_value
        op.action, op.provider_id, op.response_data = 'pay_qr', 'transfer', {}
        self.client.get_transfer.return_value = {'id': 'transfer', 'status': 'SALDO_VERIFICADO'}
        refresh(self.user, self.identifier, client=self.client)
        self.assertEqual(op.status, 'pending')

    @patch('ramps.stereum_service.StereumTestOperation.objects.select_for_update')
    def test_status_from_different_resource_is_rejected(self, get):
        get.return_value.get.return_value.action, get.return_value.get.return_value.provider_id = 'charge', 'expected'
        self.client.get_charge.return_value = {'id': 'different', 'status': 'PAGADO'}
        with self.assertRaises(StereumError):
            refresh(self.user, self.identifier, client=self.client)
        get.return_value.get.return_value.save.assert_not_called()

    @patch('ramps.stereum_views.StereumTestWebhook.objects.get_or_create')
    def test_webhook_signature_and_duplicate_handling(self, create):
        raw = b'{"notification_type":"order"}'
        signature = hmac.new(b'secret', raw, hashlib.sha256).hexdigest()
        factory = RequestFactory()
        rejected = webhook(factory.post('/', raw, content_type='application/json', HTTP_X_SIGNATURE='wrong'))
        self.assertEqual(rejected.status_code, 403)
        create.assert_not_called()
        for created in [True, False]:
            create.return_value = (Mock(), created)
            response = webhook(factory.post('/', raw, content_type='application/json', HTTP_X_SIGNATURE=signature))
            self.assertEqual(json.loads(response.content), {'ok': True, 'duplicate': not created})
        first, second = create.call_args_list
        self.assertEqual(first.kwargs['digest'], second.kwargs['digest'])

    @patch('ramps.stereum_service.transaction.atomic')
    @patch('ramps.stereum_service.StereumTestOperation.objects')
    @patch('ramps.stereum_service.build_call')
    def test_timeout_is_saved_and_same_uuid_never_resubmits(self, build, objects, atomic):
        class Administrator:
            pk = 1
            is_active = True
            is_superuser = True
            objects = Mock()
        user = Administrator()
        data = {'amount': '1', 'name': 'Test', 'lastname': 'User', 'document_number': '123', 'reason': 'Sandbox'}
        objects.filter.return_value.first.return_value = None
        operation = objects.create.return_value
        operation.actor_id, operation.credential_scope = user.pk, self.client.scope
        operation.action, operation.request_data = 'charge', data
        def timeout():
            # The durable record must exist before any mutation reaches the network.
            objects.create.assert_called_once()
            raise StereumError('Timeout; reconcile.', ambiguous=True)
        build.return_value.side_effect = timeout
        first = execute(user, 'charge', data, self.identifier, client=self.client)
        self.assertEqual(first.status, 'unknown')
        first.save.assert_called_once()
        objects.filter.return_value.first.return_value = first
        second = execute(user, 'charge', data, self.identifier, client=self.client)
        self.assertIs(first, second)
        self.assertEqual(build.return_value.call_count, 1)
        with self.assertRaises(StereumError):
            execute(user, 'charge', {**data, 'amount': '2'}, self.identifier, client=self.client)
        self.assertEqual(build.return_value.call_count, 1)

    def test_console_accepts_empty_object_but_rejects_arrays(self):
        from ramps.stereum_views import TestForm
        for action in ['banks', 'balance', 'orders']:
            form = TestForm({'action': action, 'request_id': str(self.identifier), 'payload': '{}'})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data['payload'], {})
        form = TestForm({'action': 'banks', 'request_id': str(self.identifier), 'payload': '[]'})
        self.assertFalse(form.is_valid())

    @patch('ramps.stereum_service.reference')
    def test_nan_quote_expiry_cannot_create_order(self, reference):
        reference.return_value.response_data = {'id': 'quote', 'expireAt': float('nan')}
        with self.assertRaises(StereumError):
            build_call(self.user, self.client, 'order', {}, self.identifier)

    @patch('ramps.stereum_service.reference')
    def test_missing_negative_or_null_qr_amount_is_not_open_amount(self, reference):
        for value in [None, '-1', '', False]:
            reference.return_value.response_data = {**self.decoded(), 'amount': value}
            with self.subTest(value=value), self.assertRaises(StereumError):
                build_call(self.user, self.client, 'pay_qr', self.payment(), self.identifier)
        self.client.send_transfer.assert_not_called()

    @patch('ramps.stereum_service.reference')
    def test_single_use_reservation_survives_redecoding(self, reference):
        from ramps.stereum_service import consumption_key
        previous = reference.return_value
        previous.response_data = {**self.decoded(), 'single_use': True}
        previous.request_data = {'qrs': 'same-bank-QR-string'}
        first = consumption_key(self.user, self.client, 'pay_qr', self.payment())
        previous.provider_id = 'different-decode-id'
        second = consumption_key(self.user, self.client, 'pay_qr', self.payment())
        self.assertEqual(first, second)
        previous.response_data['single_use'] = False
        self.assertIsNone(consumption_key(self.user, self.client, 'pay_qr', self.payment()))

    @patch('ramps.stereum_service.StereumTestOperation.objects.select_for_update')
    def test_terminal_status_cannot_be_overwritten_by_stale_poll(self, lock):
        op = lock.return_value.get.return_value
        op.action, op.provider_id, op.status, op.response_data = 'charge', 'charge', 'succeeded', {}
        self.client.get_charge.return_value = {'id': 'charge', 'status': 'PENDIENTE'}
        with self.assertRaises(StereumError):
            refresh(self.user, self.identifier, client=self.client)
        op.save.assert_not_called()

    @patch('ramps.stereum_service.StereumTestOperation.objects.select_for_update')
    def test_malformed_history_does_not_overwrite_status(self, lock):
        op = lock.return_value.get.return_value
        op.action, op.provider_id = 'order', 'order-id'
        for response in [None, {'items': None}, {'items': ['bad']}, 42]:
            self.client.list_orders.return_value = response
            with self.subTest(response=response), self.assertRaises(StereumError):
                refresh(self.user, self.identifier, client=self.client)
        op.save.assert_not_called()

    @patch('ramps.stereum_views.StereumTestWebhook.objects.get_or_create')
    def test_webhook_bounds_reads_and_rejects_nonfinite_json(self, create):
        factory = RequestFactory()
        oversized = webhook(factory.post('/', b'x' * 262145, content_type='application/json'))
        self.assertEqual(oversized.status_code, 413)
        raw = b'{"amount":NaN}'
        signature = hmac.new(b'secret', raw, hashlib.sha256).hexdigest()
        response = webhook(factory.post('/', raw, content_type='application/json', HTTP_X_SIGNATURE=signature))
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()
