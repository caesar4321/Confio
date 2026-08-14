from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from achievements.models import ReferralRewardEvent, UserReferral
from security.didit import (
    DiditAPIError,
    DiditConfigurationError,
    _enforce_brazilian_cpf_database_validation,
    _extract_verification_payload,
    create_didit_session,
    sync_didit_session,
    verify_didit_webhook_signature,
)
from security.models import IdentityVerification, SuspiciousActivity, normalize_brazilian_cpf
from ramps.koywe_client import KoyweClient, KoyweError
from security.schema import SecurityQuery

User = get_user_model()


class DiditPayloadExtractionTests(SimpleTestCase):
    def test_brazilian_cpf_validator_normalizes_and_checks_digits(self):
        self.assertEqual(normalize_brazilian_cpf('529.982.247-25'), '52998224725')
        self.assertIsNone(normalize_brazilian_cpf('123.456.789-01'))
        self.assertIsNone(normalize_brazilian_cpf('111.111.111-11'))

    def test_prefers_brazilian_tax_number_over_rg(self):
        extracted = _extract_verification_payload({
            'first_name': 'Vitoria',
            'last_name': 'Silva',
            'date_of_birth': '1994-07-21',
            'id_verifications': [{
                'nationality': 'BRA',
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
                'extra_fields': {
                    'tax_number': '529.982.247-25',
                },
            }],
        })

        self.assertEqual(extracted['document_number'], '52998224725')
        self.assertEqual(extracted['document_issuing_country'], 'BRA')

    def test_prefers_authoritative_bra_cpf_over_conflicting_ocr(self):
        extracted = _extract_verification_payload({
            'id_verifications': [{
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
                'extra_fields': {'tax_number': '168.995.350-09'},
            }],
            'database_validations': [{
                'status': 'Approved',
                'match_type': 'full_match',
                'screened_data': {'tax_number': '529.982.247-25'},
                'validations': [{
                    'service_id': 'bra_cpf',
                    'outcome_code': 'MATCH',
                    'validation': {
                        'identification_number': 'full_match',
                        'date_of_birth': 'full_match',
                    },
                    'source_data': {'identification_number': '52998224725'},
                }],
            }],
        })

        self.assertEqual(extracted['document_number'], '52998224725')
        self.assertTrue(extracted['brazilian_cpf_database_validation_present'])
        self.assertTrue(extracted['brazilian_cpf_database_validation_valid'])

    def test_does_not_fallback_to_ocr_when_bra_cpf_does_not_match(self):
        extracted = _extract_verification_payload({
            'id_verifications': [{
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
                'extra_fields': {'tax_number': '529.982.247-25'},
            }],
            'database_validations': [{
                'status': 'Declined',
                'match_type': 'no_match',
                'screened_data': {'tax_number': '529.982.247-25'},
                'validations': [{
                    'service_id': 'bra_cpf',
                    'outcome_code': 'NO_MATCH',
                    'validation': {
                        'identification_number': 'no_match',
                        'date_of_birth': 'no_match',
                    },
                }],
            }],
        })

        self.assertEqual(extracted['document_number'], '123456789')
        self.assertTrue(extracted['brazilian_cpf_database_validation_present'])
        self.assertFalse(extracted['brazilian_cpf_database_validation_valid'])

    def test_rejects_conflicting_bra_cpf_registry_values(self):
        extracted = _extract_verification_payload({
            'id_verifications': [{
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
            }],
            'database_validations': [{
                'status': 'Approved',
                'match_type': 'full_match',
                'screened_data': {'tax_number': '529.982.247-25'},
                'validations': [{
                    'service_id': 'bra_cpf',
                    'outcome_code': 'MATCH',
                    'validation': {
                        'identification_number': 'full_match',
                        'date_of_birth': 'full_match',
                    },
                    'source_data': {'identification_number': '16899535009'},
                }],
            }],
        })

        self.assertEqual(extracted['document_number'], '123456789')
        self.assertTrue(extracted['brazilian_cpf_database_validation_present'])
        self.assertFalse(extracted['brazilian_cpf_database_validation_valid'])

    def test_failed_bra_cpf_result_routes_top_level_approval_to_review(self):
        risk_factors = {}

        status = _enforce_brazilian_cpf_database_validation(
            status='verified',
            document_issuing_country='BRA',
            extracted={
                'brazilian_cpf_database_validation_present': True,
                'brazilian_cpf_database_validation_valid': False,
            },
            risk_factors=risk_factors,
        )

        self.assertEqual(status, 'pending')
        self.assertTrue(risk_factors['requires_review'])
        self.assertEqual(
            risk_factors['brazilian_cpf_validation']['result'],
            'not_full_match',
        )

    def test_valid_bra_cpf_result_preserves_verified_status(self):
        risk_factors = {}

        status = _enforce_brazilian_cpf_database_validation(
            status='verified',
            document_issuing_country='BRA',
            extracted={
                'brazilian_cpf_database_validation_present': True,
                'brazilian_cpf_database_validation_valid': True,
            },
            risk_factors=risk_factors,
        )

        self.assertEqual(status, 'verified')
        self.assertEqual(risk_factors, {})

    def test_does_not_replace_brazilian_rg_with_invalid_tax_number(self):
        extracted = _extract_verification_payload({
            'id_verifications': [{
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
                'extra_fields': {
                    'tax_number': '12345678901',
                },
            }],
        })

        self.assertEqual(extracted['document_number'], '123456789')

    def test_rejects_conflicting_brazilian_cpf_fields(self):
        extracted = _extract_verification_payload({
            'tax_number': '529.982.247-25',
            'id_verifications': [{
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
                'extra_fields': {'tax_number': '168.995.350-09'},
            }],
        })

        self.assertEqual(extracted['document_number'], '123456789')

    def test_koywe_normalizes_valid_brazilian_cpf(self):
        profile = KoyweClient()._normalize_contact_profile(
            contact_profile={
                'documentNumber': '529.982.247-25',
                'documentType': 'national_id',
            },
            country_code='BR',
        )

        self.assertEqual(profile['documentNumber'], '52998224725')
        self.assertEqual(profile['documentType'], 'CPF')

    def test_koywe_blocks_invalid_brazilian_cpf_before_provider_call(self):
        with self.assertRaisesRegex(KoyweError, 'validar tu CPF'):
            KoyweClient()._normalize_contact_profile(
                contact_profile={
                    'documentNumber': '123456789',
                    'documentType': 'national_id',
                },
                country_code='BR',
            )

    def test_koywe_requires_brazilian_cpf_before_provider_call(self):
        with self.assertRaisesRegex(KoyweError, 'validar tu CPF'):
            KoyweClient()._normalize_contact_profile(
                contact_profile={'documentType': 'national_id'},
                country_code='BRA',
            )

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

    def test_business_kyc_query_does_not_expose_another_users_verification(self):
        other = User.objects.create_user(
            username='other-business-owner',
            password='secret123',
            firebase_uid='other-business-owner-firebase',
        )
        IdentityVerification.objects.create(
            user=other,
            verified_first_name='Private Company',
            verified_last_name='Business',
            verified_date_of_birth=date(2020, 1, 1),
            verified_nationality='COL',
            verified_address='Private address',
            verified_city='Bogota',
            verified_state='Cundinamarca',
            verified_country='COL',
            document_type='national_id',
            document_number='private-tax-id',
            document_issuing_country='COL',
            status='verified',
            risk_factors={'account_type': 'business', 'business_id': '42'},
        )
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))

        result = SecurityQuery().resolve_business_kyc_status(info, business_id='42')

        self.assertIsNone(result)

    @patch('security.didit.requests.request')
    def test_sync_rejects_session_owned_by_another_confio_user(self, mock_request):
        mock_request.return_value = self._mock_response({
            'session_id': 'sess_other',
            'status': 'Approved',
            'vendor_data': '{"user_id":999999,"account_type":"personal"}',
        })

        with self.assertRaisesRegex(DiditAPIError, 'different Confio user'):
            sync_didit_session(session_id='sess_other', expected_user=self.user)

    @patch('security.didit.requests.request')
    def test_sync_rejects_session_without_confio_user_binding(self, mock_request):
        mock_request.return_value = self._mock_response({
            'session_id': 'sess_unbound',
            'status': 'Approved',
        })

        with self.assertRaisesRegex(DiditAPIError, 'missing its Confio user binding'):
            sync_didit_session(session_id='sess_unbound', expected_user=self.user)

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
        self.assertEqual(
            kwargs['json']['vendor_data'],
            f'{{"user_id":{self.user.id},"account_type":"business","business_id":"42"}}',
        )

    @patch('security.didit.requests.request')
    def test_business_session_requires_business_id_before_network(self, mock_request):
        with self.assertRaisesRegex(DiditConfigurationError, 'requires a business ID'):
            create_didit_session(user=self.user, account_type='business')
        mock_request.assert_not_called()

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
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Ana',
            'last_name': 'Perez',
            'date_of_birth': '1994-07-21',
            'id_verifications': [{
                'nationality': 'VEN',
                'document_type': 'passport',
                'document_number': 'P123456',
                'front_image': 'https://media.didit.example/front.jpg?signature=secret',
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
        stored_session = verification.risk_factors['didit']['session']
        self.assertNotIn('front_image', stored_session['id_verifications'][0])

    @patch('security.didit.requests.request')
    def test_sync_uses_authoritative_bra_cpf_database_match(self, mock_request):
        mock_request.return_value = self._mock_response({
            'session_id': 'sess_bra_cpf_match',
            'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Ana',
            'last_name': 'Perez',
            'date_of_birth': '1994-07-21',
            'id_verifications': [{
                'nationality': 'BRA',
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
                'extra_fields': {'tax_number': '168.995.350-09'},
            }],
            'database_validations': [{
                'status': 'Approved',
                'match_type': 'full_match',
                'screened_data': {'tax_number': '529.982.247-25'},
                'validations': [{
                    'service_id': 'bra_cpf',
                    'outcome_code': 'MATCH',
                    'validation': {
                        'identification_number': 'full_match',
                        'date_of_birth': 'full_match',
                    },
                    'source_data': {'identification_number': '52998224725'},
                }],
            }],
        })

        verification, _ = sync_didit_session(
            session_id='sess_bra_cpf_match',
            expected_user=self.user,
        )

        self.assertEqual(verification.status, 'verified')
        self.assertEqual(verification.document_number, '52998224725')
        self.assertFalse((verification.risk_factors or {}).get('requires_review', False))

    @patch('security.didit.requests.request')
    def test_sync_routes_approved_bra_cpf_no_match_to_review(self, mock_request):
        mock_request.return_value = self._mock_response({
            'session_id': 'sess_bra_cpf_no_match',
            'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Ana',
            'last_name': 'Perez',
            'date_of_birth': '1994-07-21',
            'id_verifications': [{
                'nationality': 'BRA',
                'document_type': 'Identity Card',
                'document_number': '123456789',
                'issuing_state': 'BRA',
                'extra_fields': {'tax_number': '529.982.247-25'},
            }],
            'database_validations': [{
                'status': 'Declined',
                'match_type': 'no_match',
                'screened_data': {'tax_number': '529.982.247-25'},
                'validations': [{
                    'service_id': 'bra_cpf',
                    'outcome_code': 'NO_MATCH',
                    'validation': {
                        'identification_number': 'no_match',
                        'date_of_birth': 'no_match',
                    },
                }],
            }],
        })

        verification, _ = sync_didit_session(
            session_id='sess_bra_cpf_no_match',
            expected_user=self.user,
        )

        self.assertEqual(verification.status, 'pending')
        self.assertEqual(verification.document_number, '123456789')
        self.assertTrue(verification.risk_factors['requires_review'])
        self.assertEqual(
            verification.risk_factors['brazilian_cpf_validation']['result'],
            'not_full_match',
        )

    @patch('security.didit.requests.request')
    def test_sync_session_extracts_mexico_address_and_prefers_document_postal_code(self, mock_request):
        mock_request.return_value = self._mock_response({
            'session_id': 'sess_mex_address',
            'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Martin',
            'last_name': 'De Jesus Neri',
            'date_of_birth': '1989-11-03',
            'id_verifications': [{
                'nationality': 'MEX',
                'document_type': 'Identity Card',
                'document_number': '1234567890',
                'personal_number': 'JENM891103HMNSRR04',
                'issuing_state': 'MEX',
                'address': 'C Cuitlahuac S/N,Pblo San Francisco Chilpan 54946,Tultitlan, Mex.',
                'parsed_address': {
                    'city': 'Buenavista',
                    'region': 'Estado de México',
                    'country': 'MX',
                    'street_1': 'Cuitláhuac',
                    'postal_code': '54913',
                    'raw_results': {
                        'address_components': [{
                            'types': ['sublocality', 'sublocality_level_1'],
                            'long_name': 'San Francisco Chilpan',
                            'short_name': 'San Francisco Chilpan',
                        }],
                    },
                },
            }],
        })

        verification, _ = sync_didit_session(
            session_id='sess_mex_address',
            expected_user=self.user,
        )

        self.assertEqual(verification.verified_address, 'Cuitláhuac S/N')
        self.assertEqual(verification.verified_address_neighborhood, 'San Francisco Chilpan')
        self.assertEqual(verification.verified_city, 'Buenavista')
        self.assertEqual(verification.verified_state, 'Estado de México')
        self.assertEqual(verification.verified_postal_code, '54946')
        self.assertEqual(verification.verified_country, 'MEX')
        self.assertEqual(verification.document_number, 'JENM891103HMNSRR04')

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
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
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

        with self.captureOnCommitCallbacks(execute=True):
            synced, _ = sync_didit_session(session_id='sess_dup', expected_user=self.user)

        verification.refresh_from_db()
        synced.refresh_from_db()
        self.assertEqual(verification.id, synced.id)
        self.assertEqual(verification.status, 'verified')
        self.assertEqual(verification.document_number_normalized, 'P123456')
        self.assertIn('duplicate_identity', verification.risk_factors)
        self.assertFalse(verification.requires_manual_review)
        self.assertEqual(verification.status_detail, 'Tu identidad quedó verificada correctamente.')
        self.assertTrue(
            SuspiciousActivity.objects.filter(
                user=self.user,
                activity_type='multiple_accounts',
            ).exists()
        )

    @patch('security.didit.requests.request')
    def test_duplicate_verified_identity_blocks_later_referee_reward(self, mock_request):
        referrer = User.objects.create_user(
            username='didit-referrer',
            password='secret123',
            firebase_uid='firebase-didit-referrer',
        )
        other_user = User.objects.create_user(
            username='didit-user-3',
            password='secret123',
            firebase_uid='firebase-didit-user-3',
            phone_country='AR',
        )

        earlier_referral = UserReferral.objects.create(
            referred_user=other_user,
            referrer_identifier='didit-referrer',
            referrer_user=referrer,
            reward_status='eligible',
            referee_reward_status='eligible',
        )
        later_referral = UserReferral.objects.create(
            referred_user=self.user,
            referrer_identifier='didit-referrer',
            referrer_user=referrer,
            reward_status='eligible',
            referee_reward_status='eligible',
        )
        ReferralRewardEvent.objects.create(
            referral=earlier_referral,
            user=other_user,
            trigger='conversion_usdc_to_cusd',
            actor_role='referee',
            amount=0,
            occurred_at=date(2026, 3, 1),
            reward_status='eligible',
        )
        later_event = ReferralRewardEvent.objects.create(
            referral=later_referral,
            user=self.user,
            trigger='conversion_usdc_to_cusd',
            actor_role='referee',
            amount=0,
            occurred_at=date(2026, 3, 2),
            reward_status='eligible',
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
            document_number='P123456',
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
            document_number='didit:sess_dup_2',
            document_issuing_country='UNK',
            status='pending',
            risk_factors={
                'provider': 'didit',
                'didit': {
                    'session_id': 'sess_dup_2',
                    'status': 'pending',
                },
            },
        )

        mock_request.return_value = self._mock_response({
            'session_id': 'sess_dup_2',
            'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
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

        with self.captureOnCommitCallbacks(execute=True):
            synced, _ = sync_didit_session(session_id='sess_dup_2', expected_user=self.user)

        synced.refresh_from_db()
        later_referral.refresh_from_db()
        later_event.refresh_from_db()
        self.assertEqual(synced.status, 'verified')
        self.assertEqual(later_referral.referee_reward_status, 'failed')
        self.assertEqual(later_referral.reward_status, 'failed')
        self.assertIn('Solo se permite un bono de referido', later_referral.reward_error)
        self.assertEqual(later_event.reward_status, 'failed')


@override_settings(DIDIT_WEBHOOK_SECRET='super-secret')
class DiditWebhookSignatureTests(TestCase):
    def test_signature_verification_matches_hmac_hex(self):
        body = b'{"session_id":"sess_123"}'
        import hmac
        import hashlib

        signature = hmac.new(b'super-secret', body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_didit_webhook_signature(body, signature))
        self.assertFalse(verify_didit_webhook_signature(body, 'invalid'))
