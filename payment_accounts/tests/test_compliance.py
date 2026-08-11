from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from payment_accounts.clients import ComplianceHandoffError
from payment_accounts.compliance import (
    EvidenceFile,
    build_infinia_self_declared_payload,
    fetch_didit_evidence,
)


def evidence(url, *, session=None):
    return EvidenceFile(
        url=url,
        content=b'evidence',
        content_type='image/jpeg' if not url.endswith('.pdf') else 'application/pdf',
        sha256='hash',
    )


class InfiniaComplianceHandoffTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(
            email='person@example.com',
            phone_number='3001234567',
            phone_country_code='+57',
        )
        self.identity = SimpleNamespace(
            status='verified',
            verified_first_name='Ana',
            verified_last_name='Perez',
            verified_date_of_birth=date(1994, 7, 21),
            verified_address='Calle 123 # 4-5',
            verified_city='Bogota',
            verified_state='Cundinamarca',
            verified_postal_code='110111',
            verified_country='COL',
            document_type='national_id',
            document_number='123456789',
            document_issuing_country='COL',
            risk_factors={'provider': 'didit'},
        )
        self.client = mock.Mock()
        self.client.session = mock.Mock()
        counter = iter(range(1, 20))

        def initiate(*, document_type, double_sided=False):
            number = next(counter)
            return {
                'id': f'doc_{number}',
                'upload_front_url': f'https://upload.infinia.test/{number}/front',
                'upload_back_url': f'https://upload.infinia.test/{number}/back',
            }

        self.client.initiate_owner_document.side_effect = initiate

    def profile(self, owner_type='individual'):
        return SimpleNamespace(
            internal_id='00000000-0000-0000-0000-000000000001',
            owner_type=owner_type,
            identity_verification=self.identity,
            confio_account=SimpleNamespace(user=self.user),
        )

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_individual_uploads_didit_id_and_liveness_before_owner(self, _fetch):
        decision = {
            'session_kind': 'user',
            'status': 'Approved',
            'contact_details': {},
            'id_verifications': [{
                'status': 'Approved',
                'document_type': 'Identity Card',
                'full_front_image': 'https://media.didit.test/front.jpg',
                'full_back_image': 'https://media.didit.test/back.jpg',
            }],
            'liveness_checks': [{
                'status': 'Approved',
                'reference_image': 'https://media.didit.test/selfie.jpg',
            }],
        }

        payload, audit = build_infinia_self_declared_payload(
            profile=self.profile(), client=self.client, decision=decision
        )

        self.assertEqual(payload['kyc_mode'], 'SELF_DECLARED')
        self.assertEqual(payload['type'], 'INDIVIDUAL')
        self.assertEqual(payload['individual']['identity_document_id'], 'doc_1')
        self.assertEqual(payload['individual']['selfie_document_id'], 'doc_2')
        self.assertEqual(payload['individual']['tax_id_country'], 'CO')
        self.assertEqual(len(audit), 2)
        self.assertEqual(self.client.upload_owner_document.call_count, 3)

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_business_requires_kyb_documents_and_uploads_verified_ubo(self, _fetch):
        company_documents = [
            ('CERTIFICATE_OF_INCORPORATION', 'legal_presence.pdf'),
            ('SOURCE_OF_FUNDS', 'source_of_funds.pdf'),
            ('PROOF_OF_ADDRESS', 'proof_of_address.pdf'),
        ]
        decision = {
            'session_kind': 'business',
            'status': 'Approved',
            'contact_details': {'email': 'ops@acme.co', 'phone': '+573001234567'},
            'registry_checks': [{
                'status': 'Approved',
                'company': {
                    'company_name': 'Acme SAS',
                    'incorporation_date': '2020-01-02',
                    'tax_number': '901234567',
                    'country_code': 'COL',
                    'addresses': [{
                        'line_1': 'Carrera 1 # 2-3',
                        'city': 'Bogota',
                        'state': 'Cundinamarca',
                        'postal_code': '110111',
                        'country_code': 'COL',
                    }],
                },
            }],
            'document_verifications': [{
                'items': [
                    {
                        'status': 'Approved',
                        'document_type': kind,
                        'file_url': f'https://media.didit.test/{filename}',
                    }
                    for kind, filename in company_documents
                ],
            }],
            'key_people_checks': [{
                'submitted': {'parties': [{
                    'entity_type': 'person',
                    'role': 'ubo',
                    'kyc_session_id': 'ubo_1',
                }]},
                'ubo_kyc_summary': {'total': 1, 'approved': 1},
            }],
        }
        child_identity = SimpleNamespace(**vars(self.identity))
        child = {
            'session_kind': 'user',
            'status': 'Approved',
            'contact_details': {'email': 'ubo@example.com', 'phone': '+573009999999'},
            'id_verifications': [{
                'status': 'Approved',
                'document_type': 'Passport',
                'front_image': 'https://media.didit.test/ubo-id.jpg',
            }],
            'liveness_checks': [{
                'status': 'Approved',
                'reference_image': 'https://media.didit.test/ubo-selfie.jpg',
            }],
            '_identity': child_identity,
        }

        payload, audit = build_infinia_self_declared_payload(
            profile=self.profile('business'),
            client=self.client,
            decision=decision,
            child_decisions={'ubo_1': child},
        )

        organization = payload['organization']
        self.assertEqual(payload['type'], 'ORGANIZATION')
        self.assertEqual(organization['name'], 'Acme SAS')
        self.assertEqual(organization['tax_id_country'], 'CO')
        self.assertEqual(len(organization['ultimate_beneficial_owners']), 1)
        self.assertEqual(len(audit), 5)

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_business_fails_closed_when_didit_workflow_omits_mandatory_documents(self, _fetch):
        decision = {
            'session_kind': 'business',
            'status': 'Approved',
            'contact_details': {'email': 'ops@acme.co', 'phone': '+573001234567'},
            'registry_checks': [{
                'status': 'Approved',
                'company': {
                    'company_name': 'Acme SAS',
                    'incorporation_date': '2020-01-02',
                    'tax_number': '901234567',
                    'country_code': 'COL',
                    'addresses': [{
                        'line_1': 'Carrera 1', 'city': 'Bogota',
                        'state': 'Cundinamarca', 'postal_code': '110111',
                        'country_code': 'COL',
                    }],
                },
            }],
            'document_verifications': [{'items': []}],
            'key_people_checks': [],
        }

        with self.assertRaisesRegex(ComplianceHandoffError, 'incorporation_document_id'):
            build_infinia_self_declared_payload(
                profile=self.profile('business'), client=self.client, decision=decision
            )


class DiditEvidenceDownloadTests(SimpleTestCase):
    @mock.patch('payment_accounts.compliance.socket.getaddrinfo')
    def test_missing_media_host_allowlist_fails_before_dns_or_network(self, getaddrinfo):
        with self.settings(DIDIT_MEDIA_ALLOWED_HOSTS=[]):
            with self.assertRaisesRegex(ComplianceHandoffError, 'allowlist is not configured'):
                fetch_didit_evidence('https://media.didit.test/front.jpg')
        getaddrinfo.assert_not_called()

    @mock.patch(
        'payment_accounts.compliance.socket.getaddrinfo',
        return_value=[(None, None, None, None, ('8.8.8.8', 443))],
    )
    def test_invalid_content_length_is_rejected_and_response_closed(self, _getaddrinfo):
        response = mock.Mock()
        response.headers = {
            'Content-Type': 'image/jpeg',
            'Content-Length': 'not-a-number',
        }
        session = mock.Mock()
        session.get.return_value = response

        with self.settings(DIDIT_MEDIA_ALLOWED_HOSTS=['didit.test']):
            with self.assertRaisesRegex(ComplianceHandoffError, 'invalid content length'):
                fetch_didit_evidence(
                    'https://media.didit.test/front.jpg', session=session
                )

        response.close.assert_called_once()
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
