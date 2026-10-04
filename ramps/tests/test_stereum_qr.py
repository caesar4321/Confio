from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid
import graphene
from django.test import SimpleTestCase, override_settings

from ramps import stereum_qr
from ramps.stereum_schema import Query, Mutation
from ramps.stereum_client import StereumError


@override_settings(STEREUM_ENV='sandbox', STEREUM_TEST_ENABLED=True,
    STEREUM_MOBILE_QR_TEST_ENABLED=True, STEREUM_API_KEY='test-key')
class StereumMobileQrTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_superuser=True)
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        self.schema = graphene.Schema(query=Query, mutation=Mutation)

    def test_corporate_sandbox_is_not_exposed_to_regular_users_or_businesses(self):
        self.assertTrue(stereum_qr.available(self.user))
        self.assertFalse(stereum_qr.available(self.user, personal=False))
        self.user.is_superuser = False
        self.assertFalse(stereum_qr.available(self.user))
        result = self.schema.execute('{ stereumQrAvailability { enabled canPay } }', context_value=self.info.context)
        self.assertIsNone(result.errors)
        self.assertFalse(result.data['stereumQrAvailability']['enabled'])

    @override_settings(STEREUM_ENV='production')
    def test_production_is_not_enabled_by_mobile_flag(self):
        self.assertFalse(stereum_qr.available(self.user))

    @patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={'account_type':'business'})
    def test_personal_context_required_even_for_admin(self, context):
        with self.assertRaises(StereumError):
            stereum_qr.require_operator(self.info)

    def test_preview_rejects_invalid_expired_or_wrong_currency_qr(self):
        data = {'amount':'10', 'currency':'BOB', 'single_use':True, 'expiration_date':'2099-01-01',
            'destination_name':'Test Recipient', 'account_number':'12345678', 'bank_name':'Test Bank'}
        op = SimpleNamespace(status='received', request_id=uuid.uuid4(), response_data=data)
        result = stereum_qr.preview(op)
        self.assertEqual(result['account_last4'], '5678')
        self.assertTrue(result['fixed_amount'])
        self.assertNotIn('document_number', result)
        for update in [{'amount':'NaN'}, {'amount':'-1'}, {'amount':'1.001'}, {'currency':'USD'}, {'expiration_date':'2000-01-01'}]:
            op.response_data = {**data, **update}
            with self.subTest(update=update), self.assertRaises(StereumError):
                stereum_qr.preview(op)
        op.response_data = {**data, 'amount':'0'}
        self.assertFalse(stereum_qr.preview(op)['fixed_amount'])

    @patch('ramps.stereum_qr.execute')
    @patch('ramps.stereum_qr.current_identity')
    @patch('ramps.stereum_qr.can_pay', return_value=True)
    def test_sender_identity_is_server_derived(self, can_pay, identity, execute):
        identity.return_value = SimpleNamespace(verified_first_name='Test', verified_last_name='User', document_number='123')
        stereum_qr.pay(self.user, uuid.uuid4(), uuid.uuid4(), '10')
        payload = execute.call_args.args[2]
        self.assertEqual(payload['sender_name'], 'Test User')
        self.assertEqual(payload['sender_document'], '123')
        self.assertEqual(execute.call_args.args[1], 'pay_qr')

    @patch('ramps.stereum_qr.StereumTestOperation.objects.filter')
    def test_status_lookup_is_scoped_to_actor_credential_and_payout_action(self, query):
        query.return_value.first.return_value = None
        self.assertIsNone(stereum_qr.payment(self.user, uuid.uuid4()))
        self.assertIs(query.call_args.kwargs['actor'], self.user)
        self.assertEqual(query.call_args.kwargs['action'], 'pay_qr')
        self.assertEqual(len(query.call_args.kwargs['credential_scope']), 64)

    @patch('ramps.stereum_qr.execute')
    @override_settings(STEREUM_TEST_WRITES_ENABLED=False)
    def test_disabled_writes_cannot_submit_payment(self, execute):
        with self.assertRaises(StereumError):
            stereum_qr.pay(self.user, uuid.uuid4(), uuid.uuid4(), '10')
        execute.assert_not_called()
