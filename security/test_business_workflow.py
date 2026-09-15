"""Policy checks for the deployable Didit KYB definitions.

Didit preserves unknown nested keys, so successful API publication alone does
not prove that a role or document requirement will be enforced.
"""
import json
from pathlib import Path

from django.test import SimpleTestCase


class BusinessWorkflowPolicyTests(SimpleTestCase):
    def setUp(self):
        root = Path(__file__).parent / 'workflows' / 'business'
        self.workflow = json.loads((root / 'business-workflow.json').read_text())
        self.features = {item['feature']: item.get('config', {})
                         for item in self.workflow['features']}

    def test_all_collected_roles_require_unskippable_person_verification(self):
        settings = self.features['KYB_KEY_PEOPLE']
        roles = {item['role']: item for item in settings['kyb_role_config']}
        self.assertEqual(set(roles), {
            'ubo', 'shareholder', 'beneficiary', 'settlor', 'protector', 'investor',
            'director', 'non_executive_director', 'chairman', 'secretary',
            'representative', 'authorized_signatory', 'trustee', 'company_officer',
            'founder', 'legal_advisor', 'other',
        })
        for role in roles.values():
            self.assertTrue(role['require_kyc'])
            self.assertNotIn('require_verification', role)  # Ignored by Didit.
            self.assertFalse(role['allow_skip'])
            self.assertEqual(role['verification_workflow'], '$person_workflow')
        self.assertFalse(settings['kyb_reuse_verified_individuals'])
        self.assertTrue(settings['kyb_wait_for_all_ubos'])

    def test_required_document_groups_can_be_completed_and_require_incorporation(self):
        settings = self.features['KYB_DOCUMENTS']
        catalog = {
            'LEGAL_PRESENCE': ['CERTIFICATE_OF_INCORPORATION', 'CERTIFICATE_OF_GOOD_STANDING',
                               'CERTIFICATE_OF_INCUMBENCY', 'REGISTRY_EXCERPT',
                               'BUSINESS_LICENSE', 'TAX_REGISTRATION'],
            'COMPANY_DETAILS': ['CONFIRMATION_STATEMENT', 'ANNUAL_RETURN', 'STATEMENT_OF_INFORMATION'],
            'OWNERSHIP_STRUCTURE': ['SHAREHOLDER_REGISTRY', 'MEMORANDUM_OF_ASSOCIATION', 'ARTICLES_OF_ASSOCIATION'],
            'REPRESENTATIVES_AUTHORIZATION': ['DIRECTOR_REGISTRY', 'POWER_OF_ATTORNEY', 'TRUST_AGREEMENT'],
        }
        self.assertEqual(set(settings['kyb_required_document_groups']), set(catalog))
        subtypes = settings['kyb_document_subtype_config']
        for group, types in catalog.items():
            self.assertTrue(any(subtypes[k]['enabled'] for k in types), group)
        self.assertEqual([k for k in catalog['LEGAL_PRESENCE'] if subtypes[k]['enabled']],
                         ['CERTIFICATE_OF_INCORPORATION'])

    def test_business_evidence_requires_manual_review(self):
        self.assertEqual(self.features['QUESTIONNAIRE']['questionnaire_uuid'], '$business_questionnaire')
        self.assertTrue(self.features['QUESTIONNAIRE']['review_questionnaire_manually'])
