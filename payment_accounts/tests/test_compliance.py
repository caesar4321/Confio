from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from payment_accounts.clients import ComplianceHandoffError
from payment_accounts.compliance import (
    EvidenceFile,
    build_infinia_self_declared_payload,
    fetch_didit_evidence,
    _individual_identifiers,
    _document_type,
    _volume_fields,
    _individual_payload,
    _company,
    didit_ubo_parties,
    _business_documents,
    _reviewed_answers,
    _questionnaire_address,
    BUSINESS_WORKFLOW_ID,
    PERSON_WORKFLOW_ID,
    BUSINESS_QUESTIONNAIRE_ID,
    PERSON_QUESTIONNAIRE_ID,
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
        self.declared = SimpleNamespace(
            address_street='Calle 123 # 4-5', address_neighborhood='Chapinero', address_city='Bogota',
            address_state='Cundinamarca', address_zip_code='110111', address_country='COL',
        )
        mock.patch('payment_accounts.compliance._declared_address', side_effect=lambda user: self.declared).start()
        self.addCleanup(mock.patch.stopall)

    def profile(self, owner_type='individual'):
        return SimpleNamespace(
            internal_id='00000000-0000-0000-0000-000000000001',
            owner_type=owner_type,
            identity_verification=self.identity,
            confio_account=SimpleNamespace(user=self.user),
        )

    def test_country_identifiers_use_koywe_normalized_identity_not_raw_card_serial(self):
        for country, number, expected in [
            ('BRA', '529.982.247-25', '52998224725'),
            ('MEX', 'JENM891103HMNSRR04', 'JENM891103HMNSRR04'),
            ('CHL', '12.345.678-5', '12345678-5'),
            ('COL', '123456789', '123456789'),
        ]:
            with self.subTest(country=country):
                self.identity.document_issuing_country = country
                self.identity.document_number = number
                result = _individual_identifiers(self.identity, {'document_number': 'CARD-SERIAL'})
                self.assertEqual(result['tax_id'], expected)

    def test_invalid_cpf_and_card_serials_are_rejected(self):
        for country in ['BRA', 'MEX', 'CHL']:
            self.identity.document_issuing_country = country
            self.identity.document_number = 'CARD-SERIAL'
            with self.subTest(country=country), self.assertRaises(ComplianceHandoffError):
                _individual_identifiers(self.identity, {})

    def test_ubo_cpf_checksum_cannot_override_failed_database_verification(self):
        self.identity.document_issuing_country = 'BRA'
        self.identity.document_number = '52998224725'
        self.identity.brazilian_cpf_database_validation_present = True
        self.identity.brazilian_cpf_database_validation_valid = False
        with self.assertRaisesRegex(ComplianceHandoffError, 'database verification'):
            _individual_identifiers(self.identity, {})

    def test_argentina_requires_separate_matching_cuil(self):
        self.identity.document_issuing_country = 'ARG'
        self.identity.document_number = '12345678'
        result = _individual_identifiers(self.identity, {'extra_fields': {'cuil': '20-12345678-6'}})
        self.assertEqual(result['tax_id'], '12345678')
        self.assertEqual(result['additional_tax_id'], '20123456786')
        for check in [{}, {'extra_fields': {'cuil': '20123456780'}},
                      {'extra_fields': {'cuil': '20123456786'}, 'additional_tax_id': '27123456780'}]:
            with self.subTest(check=check), self.assertRaises(ComplianceHandoffError):
                _individual_identifiers(self.identity, check)

    def test_an_argentine_passport_needs_no_dni_or_cuil(self):
        self.identity.document_issuing_country = 'ARG'
        self.identity.document_type = 'passport'
        self.identity.document_number = 'AAB123456'
        self.assertEqual(_individual_identifiers(self.identity, {}), {'tax_id_country': 'AR', 'tax_id': 'AAB123456'})

    def test_a_brazilian_passport_needs_no_cpf(self):
        self.identity.document_issuing_country = 'BRA'
        self.identity.document_type = 'passport'
        self.identity.document_number = 'FZ123456'
        self.assertEqual(_individual_identifiers(self.identity, {}), {'tax_id_country': 'BR', 'tax_id': 'FZ123456'})

    def test_unknown_document_types_fail_closed(self):
        for kind in ['residence_permit', 'foreign_id', 'mystery', '', 'not_a_passport']:
            with self.subTest(kind=kind), self.assertRaises(ComplianceHandoffError):
                _document_type(kind)
        self.assertEqual(_document_type('Identity Card'), 'NATIONAL_ID')

    def test_registry_must_itself_be_approved(self):
        with self.assertRaisesRegex(ComplianceHandoffError, 'approved business registry'):
            _company({'status': 'Approved', 'registry_checks': [{'status': 'Rejected', 'company': {'name': 'Company'}}]})

    def test_id_evidence_cannot_skip_first_normalized_check(self):
        decision = {'status': 'Approved', 'id_verifications': [
            {'status': 'Rejected'}, {'status': 'Approved', 'document_type': 'Passport'}],
            'liveness_checks': [{'status': 'Approved'}]}
        with self.assertRaisesRegex(ComplianceHandoffError, 'identity and liveness'):
            _individual_payload(decision=decision, identity=self.identity, user=self.user, client=self.client)
        self.client.initiate_owner_document.assert_not_called()

    def test_missing_ubo_contact_does_not_use_account_owner(self):
        decision = {'status': 'Approved', 'id_verifications': [{'status': 'Approved', 'document_type': 'Passport'}],
                    'liveness_checks': [{'status': 'Approved'}]}
        with self.assertRaisesRegex(ComplianceHandoffError, 'email'):
            _individual_payload(decision=decision, identity=self.identity, user=None, client=self.client)
        self.client.initiate_owner_document.assert_not_called()

    def test_address_preflight_rejects_placeholders_before_uploads(self):
        decision = {'status': 'Approved', 'id_verifications': [{'status': 'Approved', 'document_type': 'Passport'}],
                    'liveness_checks': [{'status': 'Approved'}]}
        for city in ['Unknown City', '   ']:
            self.identity.verified_city = city
            with self.subTest(city=city), self.assertRaisesRegex(ComplianceHandoffError, 'address fields'):
                _individual_payload(decision=decision, identity=self.identity, user=self.user, client=self.client)
        self.client.initiate_owner_document.assert_not_called()

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_owner_address_is_the_self_declared_one_when_the_id_has_none(self, _fetch):
        # Many LATAM cédulas/DNIs print no address; the owner declares it.
        for field in ('verified_address', 'verified_city', 'verified_state', 'verified_postal_code'):
            setattr(self.identity, field, '')
        decision = {'session_kind': 'user', 'status': 'Approved', 'contact_details': {},
                    'id_verifications': [{'status': 'Approved', 'document_type': 'Identity Card',
                                          'full_front_image': 'https://media.didit.test/front.jpg'}],
                    'liveness_checks': [{'status': 'Approved', 'reference_image': 'https://media.didit.test/s.jpg'}]}
        payload, _ = build_infinia_self_declared_payload(profile=self.profile(), client=self.client, decision=decision)
        self.assertEqual(payload['individual']['address'], {
            'line_1': 'Calle 123 # 4-5, Chapinero', 'city': 'Bogota', 'state': 'Cundinamarca',
            'postal_code': '110111', 'country': 'CO'})

    def test_incomplete_declared_address_stops_before_uploads(self):
        self.declared.address_zip_code = ''
        decision = {'session_kind': 'user', 'status': 'Approved',
                    'id_verifications': [{'status': 'Approved', 'document_type': 'Passport'}],
                    'liveness_checks': [{'status': 'Approved'}]}
        with self.assertRaisesRegex(ComplianceHandoffError, 'Completa tu dirección'):
            build_infinia_self_declared_payload(profile=self.profile(), client=self.client, decision=decision)
        self.client.initiate_owner_document.assert_not_called()

    def test_ubo_never_inherits_the_owner_declared_address(self):
        decision = {'status': 'Approved', 'contact_details': {'email': 'ubo@example.com', 'phone': '+573009999999'},
                    'id_verifications': [{'status': 'Approved', 'document_type': 'Passport'}],
                    'liveness_checks': [{'status': 'Approved'}]}
        self.identity.verified_city = ''
        with self.assertRaisesRegex(ComplianceHandoffError, 'address fields'):
            _individual_payload(decision=decision, identity=self.identity, user=None, client=self.client)

    def test_volume_is_optional_and_must_be_finite_nonnegative(self):
        self.assertEqual(_volume_fields({}), {})
        self.assertEqual(_volume_fields({'expected_monthly_volume_usd': '0'}), {'expected_monthly_volume_usd': 0})
        for value in ['NaN', 'Infinity', '-1', True, {}, 'bad']:
            with self.subTest(value=value), self.assertRaises(ComplianceHandoffError):
                _volume_fields({'expected_monthly_volume_usd': value})

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_personal_enhanced_evidence_and_volume_are_forwarded(self, _fetch):
        decision = {
            'status': 'Approved', 'session_kind': 'user',
            'expected_monthly_volume_usd': '2500.50',
            'id_verifications': [{'status': 'Approved', 'document_type': 'Passport',
                                  'front_image': 'https://media.didit.test/id.jpg'}],
            'liveness_checks': [{'status': 'Approved', 'reference_image': 'https://media.didit.test/selfie.jpg'}],
            'document_verifications': [{'items': [
                {'status': 'Rejected', 'document_type': 'source_of_funds', 'file_url': 'https://media.didit.test/rejected.pdf'},
                {'status': 'Approved', 'document_type': 'source_of_funds', 'file_url': 'https://media.didit.test/funds.pdf'},
                {'status': 'Approved', 'document_subtype': 'utility_bill', 'document_type': 'proof_of_address', 'file_url': 'https://media.didit.test/address.pdf'},
            ]}],
        }
        payload, audits = build_infinia_self_declared_payload(profile=self.profile(), client=self.client, decision=decision)
        self.assertEqual(payload['individual']['source_of_funds_document_id'], 'doc_3')
        self.assertEqual(payload['individual']['proof_of_address_document_id'], 'doc_4')
        self.assertEqual(payload['individual']['expected_monthly_volume_usd'], 2500.5)
        self.assertEqual(len(audits), 4)
        decision['id_verifications'][0]['status'] = 'Rejected'
        self.client.reset_mock()
        with self.assertRaises(ComplianceHandoffError):
            build_infinia_self_declared_payload(profile=self.profile(), client=self.client, decision=decision)
        self.client.initiate_owner_document.assert_not_called()

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_every_approved_file_for_one_field_reaches_the_provider(self, _fetch):
        # Infinia keeps one document per owner field: payslips AND statements go as one PDF.
        decision = {
            'status': 'Approved', 'session_kind': 'user',
            'id_verifications': [{'status': 'Approved', 'document_type': 'Passport',
                                  'front_image': 'https://media.didit.test/id.jpg'}],
            'liveness_checks': [{'status': 'Approved', 'reference_image': 'https://media.didit.test/selfie.jpg'}],
            'document_verifications': [{'items': [
                {'status': 'Approved', 'document_type': 'source_of_funds', 'file_url': 'https://media.didit.test/payslip.pdf'},
                {'status': 'Approved', 'document_type': 'source_of_funds', 'file_url': 'https://media.didit.test/statement.pdf'},
                {'status': 'Approved', 'document_subtype': 'utility_bill', 'document_type': 'proof_of_address', 'file_url': 'https://media.didit.test/address.pdf'},
            ]}],
        }
        with mock.patch('payment_accounts.compliance._combined_pdf', return_value=b'%PDF-both') as combine:
            payload, audits = build_infinia_self_declared_payload(
                profile=self.profile(), client=self.client, decision=decision)
        self.assertEqual([item.url for item in combine.call_args.args[0]],
                         ['https://media.didit.test/payslip.pdf', 'https://media.didit.test/statement.pdf'])
        self.assertEqual(payload['individual']['source_of_funds_document_id'], 'doc_3')
        self.assertEqual(payload['individual']['proof_of_address_document_id'], 'doc_4')
        self.client.upload_owner_document.assert_any_call(
            'https://upload.infinia.test/3/front', b'%PDF-both', content_type='application/pdf')
        self.assertEqual(len(audits), 4)

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

        # A company registration reference is not necessarily its tax ID.
        company = decision['registry_checks'][0]['company']
        company.pop('tax_number')
        company['registration_number'] = 'REG-123'
        self.client.reset_mock()
        with self.assertRaisesRegex(ComplianceHandoffError, 'company tax ID'):
            build_infinia_self_declared_payload(
                profile=self.profile('business'), client=self.client,
                decision=decision, child_decisions={'ubo_1': child},
            )
        self.client.initiate_owner_document.assert_not_called()

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
            'key_people_checks': [{'submitted': {'parties': [
                {'role': 'ubo', 'kyc_session_id': 'ubo'}]}}],
        }

        with self.assertRaisesRegex(ComplianceHandoffError, 'incorporation_document_id'):
            build_infinia_self_declared_payload(
                profile=self.profile('business'), client=self.client, decision=decision
            )

    def questionnaire(self, *, person=False, values=None, files=None):
        return {
            'questionnaire_id': PERSON_QUESTIONNAIRE_ID if person else BUSINESS_QUESTIONNAIRE_ID,
            'status': 'Approved',
            'sections': [{'items': [
                *[{'value': key, 'answer': {'value': value}} for key, value in (values or {}).items()],
                *[{'value': key, 'answer': {'files': value}} for key, value in (files or {}).items()],
            ]}],
        }

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_business_questionnaire_evidence_maps_all_three_uploads(self, fetch):
        decision = {
            'workflow_id': BUSINESS_WORKFLOW_ID, 'session_kind': 'business', 'status': 'Approved',
            'document_verifications': [{'items': [{'status': 'Approved',
                'document_subtype': 'certificate_of_incorporation',
                'file_url': 'https://media.didit.test/incorporation.pdf'}]}],
            'questionnaire_responses': [self.questionnaire(
                values={'expected_monthly_volume_usd': '1234.50', 'company_address_line_1': 'Calle 1',
                        'company_address_city': 'Bogota', 'company_address_state': 'Cundinamarca',
                        'company_address_postal_code': '110111', 'company_address_country': 'CO'},
                files={key: [f'https://media.didit.test/{key}.pdf'] for key in (
                    'source_of_funds_document', 'proof_of_address_document', 'tax_registration_document')})],
        }
        fields, audits = _business_documents(decision, self.client)
        self.assertEqual(set(fields), {'incorporation_document_id', 'source_of_funds_document_id',
                                      'proof_of_address_document_id', 'tax_registration_document_id'})
        self.assertEqual(len(audits), 4)
        self.assertEqual(fetch.call_count, 4)
        self.assertNotIn('https://', str(audits))
        self.assertEqual(_volume_fields(decision), {'expected_monthly_volume_usd': 1234.5})
        answers = _reviewed_answers(decision, BUSINESS_QUESTIONNAIRE_ID, BUSINESS_WORKFLOW_ID)
        self.assertEqual(_questionnaire_address(answers, 'company_address')['city'], 'Bogota')

    def test_questionnaire_must_match_exact_id_and_feature_approval(self):
        from copy import deepcopy
        original = {'status': 'Approved', 'workflow_id': BUSINESS_WORKFLOW_ID,
                    'questionnaire_responses': [self.questionnaire(values={'expected_monthly_volume_usd': 1})]}
        variants = []
        for key, value in [('questionnaire_id', 'unrelated-form'), ('status', 'In Review')]:
            decision = deepcopy(original)
            decision['questionnaire_responses'][0][key] = value
            variants.append(decision)
        variants.extend([{**original, 'questionnaire_responses': []},
                         {**original, 'status': 'In Review'},
                         {**original, 'questionnaire_responses': original['questionnaire_responses'] * 2}])
        for decision in variants:
            with self.subTest(decision=decision), self.assertRaises(ComplianceHandoffError):
                _business_documents(decision, self.client)
        self.client.initiate_owner_document.assert_not_called()

    def test_reviewed_questionnaire_rejects_bad_volume_and_duplicate_answers(self):
        for amount in ('NaN', 'Infinity', '-1', 'abc', ''):
            decision = {'session_kind': 'business', 'status': 'Approved',
                        'questionnaire_responses': [self.questionnaire(values={'expected_monthly_volume_usd': amount})]}
            with self.subTest(amount=amount), self.assertRaises(ComplianceHandoffError):
                _volume_fields(decision)
        form = self.questionnaire(values={'company_address_city': 'Bogota'})
        form['sections'][0]['items'] *= 2
        with self.assertRaisesRegex(ComplianceHandoffError, 'duplicate'):
            _reviewed_answers({'status': 'Approved', 'questionnaire_responses': [form]},
                              BUSINESS_QUESTIONNAIRE_ID, BUSINESS_WORKFLOW_ID)

    @mock.patch('payment_accounts.compliance.fetch_didit_evidence', side_effect=evidence)
    def test_ubo_reviewed_address_and_cuil_require_approved_poa_and_official_tax_evidence(self, fetch):
        self.identity.document_issuing_country = 'ARG'
        self.identity.document_number = '12345678'
        self.identity.verified_city = 'Unknown City'
        form = self.questionnaire(person=True, values={
            'residential_address_line_1': 'Calle 2', 'residential_address_city': 'Salta',
            'residential_address_state': 'Salta', 'residential_address_postal_code': 'A4400',
            'residential_address_country': 'AR', 'additional_tax_id': '20-12345678-6',
        }, files={'tax_id_evidence': ['https://media.didit.test/tax.pdf']})
        decision = {
            'session_kind': 'user', 'status': 'Approved', 'workflow_id': PERSON_WORKFLOW_ID,
            'questionnaire_responses': [form],
            'id_verifications': [{'status': 'Approved', 'document_type': 'Identity Card',
                                  'front_image': 'https://media.didit.test/id.jpg'}],
            'liveness_checks': [{'status': 'Approved', 'reference_image': 'https://media.didit.test/selfie.jpg'}],
            'poa_verifications': [{'status': 'Approved', 'document_file': 'https://media.didit.test/poa.pdf'}],
            'email_verifications': [{'status': 'Approved', 'email': 'ubo@example.com'}],
            'phone_verifications': [{'status': 'Approved', 'full_number': '+541123456789'}],
        }
        payload, audits = _individual_payload(decision=decision, identity=self.identity, user=None, client=self.client)
        self.assertEqual(payload['address']['city'], 'Salta')
        self.assertEqual(payload['additional_tax_id'], '20123456786')
        self.assertEqual(payload['email'], 'ubo@example.com')
        self.assertEqual(payload['other_documents'], ['doc_4'])
        self.assertEqual(len(audits), 4)
        for status in ('In Review', 'Declined'):
            decision['poa_verifications'][0]['status'] = status
            with self.subTest(status=status), self.assertRaisesRegex(ComplianceHandoffError, 'proof of address'):
                _individual_payload(decision=decision, identity=self.identity, user=None, client=self.client)
        decision['poa_verifications'][0]['status'] = 'Approved'
        form['sections'][0]['items'] = [i for i in form['sections'][0]['items'] if i['value'] != 'tax_id_evidence']
        with self.assertRaisesRegex(ComplianceHandoffError, 'verified Argentine CUIL'):
            _individual_payload(decision=decision, identity=self.identity, user=None, client=self.client)

    def test_registry_cannot_skip_the_first_normalized_result(self):
        with self.assertRaisesRegex(ComplianceHandoffError, 'approved business registry'):
            _company({'registry_checks': [{'status': 'Declined'},
                                          {'status': 'Approved', 'company': {'company_name': 'Other'}}]})

    @mock.patch('payment_accounts.compliance._business_documents', return_value=({}, []))
    @mock.patch('payment_accounts.compliance._individual_payload', return_value=({'first_name': 'Ana'}, []))
    def test_current_business_workflow_uses_reviewed_fields_and_requires_approved_people(self, individual, documents):
        decision = {
            'session_kind': 'business', 'status': 'Approved', 'workflow_id': BUSINESS_WORKFLOW_ID,
            'registry_checks': [{'status': 'Approved', 'company': {
                'company_name': 'Acme', 'country_code': 'COL', 'incorporation_date': '2020-01-02',
                'tax_number': '901234567', 'addresses': []}}],
            'questionnaire_responses': [self.questionnaire(values={
                'company_address_line_1': 'Calle 1', 'company_address_city': 'Bogota',
                'company_address_state': 'Cundinamarca', 'company_address_postal_code': '110111',
                'company_address_country': 'CO', 'expected_monthly_volume_usd': '1000'})],
            'email_verifications': [{'status': 'Approved', 'email': 'company@example.com'}],
            'phone_verifications': [{'status': 'Approved', 'full_number': '+573001234567'}],
            'key_people_checks': [{'status': 'Approved', 'submitted': {'parties': [
                {'entity_type': 'person', 'role': 'ubo', 'kyc_session_id': 'ubo'}]},
                'ubo_kyc_summary': {'total': 1}}],
        }
        payload, _ = build_infinia_self_declared_payload(
            profile=self.profile('business'), client=self.client, decision=decision,
            child_decisions={'ubo': {'_identity': self.identity}})
        self.assertEqual(payload['organization']['email'], 'company@example.com')
        self.assertEqual(payload['organization']['address']['city'], 'Bogota')
        self.assertEqual(payload['organization']['expected_monthly_volume_usd'], 1000)
        decision['key_people_checks'][0]['status'] = 'In Review'
        with self.assertRaisesRegex(ComplianceHandoffError, 'approved key people'):
            build_infinia_self_declared_payload(profile=self.profile('business'), client=self.client, decision=decision)
        decision['key_people_checks'] = []
        with self.assertRaisesRegex(ComplianceHandoffError, 'UBO disclosure'):
            build_infinia_self_declared_payload(profile=self.profile('business'), client=self.client, decision=decision)
        decision['phone_verifications'][0]['status'] = 'Declined'
        with self.assertRaisesRegex(ComplianceHandoffError, 'email and phone'):
            build_infinia_self_declared_payload(profile=self.profile('business'), client=self.client, decision=decision)

    def test_ubo_collection_includes_registry_and_rejects_skipped_or_deleted_sessions(self):
        decision = {'key_people_checks': [{
            'registry': {'beneficial_owners': [{'uuid': 'a', 'kyc_session_id': 'registry-ubo'}],
                         'officers': [{'roles': ['director'], 'kyc_session_id': 'director'}]},
            'submitted': {'parties': [{'role': 'ubo', 'kyc_session_id': 'manual-ubo'}]},
        }]}
        self.assertEqual([p['kyc_session_id'] for p in didit_ubo_parties(decision)],
                         ['manual-ubo', 'registry-ubo'])
        party = decision['key_people_checks'][0]['registry']['beneficial_owners'][0]
        for key in ('is_skipped', 'kyc_session_deleted'):
            party[key] = True
            with self.subTest(key=key), self.assertRaisesRegex(ComplianceHandoffError, 'Skipped or deleted'):
                didit_ubo_parties(decision)
            party.pop(key)


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
