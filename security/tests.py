from datetime import date
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from security.didit import create_didit_session, sync_didit_session, verify_didit_webhook_signature
from security.didit import DiditConfigurationError
from security.models import IdentityVerification, SuspiciousActivity

User = get_user_model()


@override_settings(
    DIDIT_API_KEY='test-api-key',
    DIDIT_WORKFLOW_IDS_BY_PHONE_COUNTRY={
        'PY': 'workflow-paraguay',
        'AR': 'workflow-argentina',
        'PT': 'workflow-portugal',
        'DE': 'workflow-europe',
    },
    DIDIT_BUSINESS_WORKFLOW_ID='workflow-business',
)
class DiditIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='didit-user',
            password='secret123',
            firebase_uid='firebase-didit-user',
            first_name='Ana',
            last_name='Perez',
            phone_country='AR',
        )

    def _mock_response(self, payload):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    @patch('security.didit.requests.request')
    def test_create_session_uses_business_workflow_and_vendor_data(self, mock_request):
        mock_request.return_value = self._mock_response({
            'session_id': 'sess_123',
            'session_token': 'token_abc',
            'status': 'In progress',
        })

        session = create_didit_session(
            user=self.user,
            account_type='business',
            business_id='42',
            callback_url='https://confio.lat/api/didit/webhook/',
        )

        self.assertEqual(session['session_id'], 'sess_123')
        self.assertEqual(session['session_token'], 'token_abc')

        _, url = mock_request.call_args.args[:2]
        kwargs = mock_request.call_args.kwargs
        self.assertEqual(url, 'https://verification.didit.me/v3/session/')
        self.assertEqual(kwargs['headers']['x-api-key'], 'test-api-key')
        self.assertEqual(kwargs['json']['workflow_id'], 'workflow-business')
        self.assertEqual(kwargs['json']['callback'], 'https://confio.lat/api/didit/webhook/')
        self.assertEqual(kwargs['json']['vendor_data'], '{"user_id":1,"account_type":"business","business_id":"42"}')

    @patch('security.didit.requests.request')
    def test_create_session_uses_phone_country_workflow_for_personal_accounts(self, mock_request):
        mock_request.return_value = self._mock_response({
            'session_id': 'sess_456',
            'session_token': 'token_xyz',
            'status': 'In progress',
        })

        create_didit_session(user=self.user, account_type='personal')

        kwargs = mock_request.call_args.kwargs
        self.assertEqual(kwargs['json']['workflow_id'], 'workflow-argentina')

    def test_create_session_rejects_unsupported_phone_country(self):
        self.user.phone_country = 'JP'

        with self.assertRaises(DiditConfigurationError):
            create_didit_session(user=self.user, account_type='personal')

    @patch('security.didit.requests.request')
    def test_sync_session_updates_existing_pending_verification(self, mock_request):
        verification = IdentityVerification.objects.create(
            user=self.user,
            verified_first_name='Pending',
            verified_last_name='Verification',
            verified_date_of_birth=date(1900, 1, 1),
            verified_nationality='UNK',
            verified_address='Pending Didit verification',
            verified_city='Unknown City',
            verified_state='Unknown State',
            verified_country='UNK',
            document_type='national_id',
            document_number='didit:sess_123',
            document_issuing_country='UNK',
            status='pending',
            risk_factors={
                'provider': 'didit',
                'didit': {
                    'session_id': 'sess_123',
                    'status': 'pending',
                },
            },
        )

        mock_request.return_value = self._mock_response({
            'session_id': 'sess_123',
            'status': 'Approved',
            'vendor_data': '{"user_id":1,"account_type":"personal"}',
            'first_name': 'Ana',
            'last_name': 'Perez',
            'date_of_birth': '1994-07-21',
            'id_verifications': [{
                'nationality': 'VEN',
                'document_type': 'passport',
                'document_number': 'P123456',
                'issuing_state': 'VEN',
                'expiration_date': '2030-12-31',
                'parsed_address': {
                    'street': 'Calle 123',
                    'street_number': '45',
                    'city': 'Bogota',
                    'state': 'Cundinamarca',
                    'postal_code': '110111',
                    'country': 'CO',
                },
            }],
        })

        synced, payload = sync_didit_session(session_id='sess_123', expected_user=self.user)

        verification.refresh_from_db()
        self.assertEqual(payload['status'], 'Approved')
        self.assertEqual(synced.id, verification.id)
        self.assertEqual(verification.status, 'verified')
        self.assertEqual(verification.verified_first_name, 'Ana')
        self.assertEqual(verification.verified_last_name, 'Perez')
        self.assertEqual(verification.verified_date_of_birth, date(1994, 7, 21))
        self.assertEqual(verification.verified_country, 'COL')
        self.assertEqual(verification.document_type, 'passport')
        self.assertEqual(verification.document_number, 'P123456')
        self.assertEqual(verification.document_issuing_country, 'VEN')

    @patch('security.didit.requests.request')
    def test_sync_session_defers_duplicate_personal_identity(self, mock_request):
        other_user = User.objects.create_user(
            username='didit-user-2',
            password='secret123',
            firebase_uid='firebase-didit-user-2',
            first_name='Ana',
            last_name='Perez',
            phone_country='AR',
        )
        IdentityVerification.objects.create(
            user=other_user,
            verified_first_name='Ana',
            verified_last_name='Perez',
            verified_date_of_birth=date(1994, 7, 21),
            verified_nationality='VEN',
            verified_address='Main street',
            verified_city='Bogota',
            verified_state='Cundinamarca',
            verified_country='COL',
            document_type='passport',
            document_number='P-123 456',
            document_issuing_country='VEN',
            status='verified',
            risk_factors={},
        )

        verification = IdentityVerification.objects.create(
            user=self.user,
            verified_first_name='Pending',
            verified_last_name='Verification',
            verified_date_of_birth=date(1900, 1, 1),
            verified_nationality='UNK',
            verified_address='Pending Didit verification',
            verified_city='Unknown City',
            verified_state='Unknown State',
            verified_country='UNK',
            document_type='national_id',
            document_number='didit:sess_dup',
            document_issuing_country='UNK',
            status='pending',
            risk_factors={
                'provider': 'didit',
                'didit': {
                    'session_id': 'sess_dup',
                    'status': 'pending',
                },
            },
        )

        mock_request.return_value = self._mock_response({
            'session_id': 'sess_dup',
            'status': 'Approved',
            'vendor_data': '{"user_id":1,"account_type":"personal"}',
            'first_name': 'Ana',
            'last_name': 'Perez',
            'date_of_birth': '1994-07-21',
            'id_verifications': [{
                'nationality': 'VEN',
                'document_type': 'passport',
                'document_number': 'P123456',
                'issuing_state': 'VEN',
                'expiration_date': '2030-12-31',
                'parsed_address': {
                    'street': 'Calle 123',
                    'street_number': '45',
                    'city': 'Bogota',
                    'state': 'Cundinamarca',
                    'postal_code': '110111',
                    'country': 'CO',
                },
            }],
        })

        synced, _ = sync_didit_session(session_id='sess_dup', expected_user=self.user)

        verification.refresh_from_db()
        synced.refresh_from_db()
        self.assertEqual(verification.id, synced.id)
        self.assertEqual(verification.status, 'pending')
        self.assertEqual(verification.document_number_normalized, 'P123456')
        self.assertIn('duplicate_identity', verification.risk_factors)
        self.assertTrue(
            SuspiciousActivity.objects.filter(
                user=self.user,
                activity_type='multiple_accounts',
            ).exists()
        )


@override_settings(DIDIT_WEBHOOK_SECRET='super-secret')
class DiditWebhookSignatureTests(TestCase):
    def test_signature_verification_matches_hmac_hex(self):
        body = b'{"session_id":"sess_123"}'
        import hmac
        import hashlib

        signature = hmac.new(b'super-secret', body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_didit_webhook_signature(body, signature))
        self.assertFalse(verify_didit_webhook_signature(body, 'invalid'))
