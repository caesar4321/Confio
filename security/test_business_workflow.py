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

    def test_required_document_groups_accept_local_registration_evidence(self):
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
                         ['CERTIFICATE_OF_INCORPORATION', 'REGISTRY_EXCERPT', 'TAX_REGISTRATION'])
        self.assertEqual(settings['kyb_document_max_retry_attempts'], 3)
        self.assertEqual(settings['kyb_document_max_attempts_exceeded_action'], 'REVIEW')
        for key in ('tampering', 'critical_mismatch', 'non_critical_mismatch', 'age'):
            self.assertEqual(settings[f'kyb_document_{key}_action'], 'REVIEW')

    def test_questionnaire_only_escalates_risks_and_missing_answers(self):
        self.assertEqual(self.features['QUESTIONNAIRE']['questionnaire_uuid'], '$business_questionnaire')
        root = Path(__file__).parent / 'workflows' / 'business'
        for kind in ('business', 'person'):
            workflow = json.loads((root / f'{kind}-workflow.json').read_text())
            form = json.loads((root / f'{kind}-questionnaire.json').read_text())
            config = next(f['config'] for f in workflow['features'] if f['feature'] == 'QUESTIONNAIRE')
            aml = next(f['config'] for f in workflow['features'] if f['feature'] == 'AML')
            prefix = 'kyb' if kind == 'business' else 'aml'
            # Didit approves scores strictly BELOW the approval threshold.
            # Zero made even no-hit, score-zero screenings require review.
            self.assertEqual(aml[f'{prefix}_score_approve_threshold'], 1)
            self.assertEqual(aml[f'{prefix}_score_review_threshold'], 100)
            self.assertFalse(config['review_questionnaire_manually'])
            rules = config['status_rules']
            self.assertTrue(rules)
            self.assertEqual({r['status'] for r in rules}, {'In Review'})
            # No rule can override a failed upstream check with Approved.
            required = {e['id'] for e in form['form_elements']
                        if e.get('is_required') and e['element_type'] != 'file_upload'}
            missing_guards = {r['field'].removeprefix('questionnaire.answers.')
                              for r in rules if r['operator'] == 'is_empty'}
            self.assertTrue(required <= missing_guards)
            allowed = {'pep_risk': 'no'}
            if kind == 'business':
                allowed.update(regulated_risk='no', ownership_structure_type='direct_natural')
            for field, value in allowed.items():
                self.assertIn({'field': f'questionnaire.answers.{field}',
                               'operator': 'not_equals', 'value': value,
                               'status': 'In Review', 'value_type': 'literal'}, rules)
                element = next(e for e in form['form_elements'] if e['id'] == field)
                self.assertTrue(element['is_required'])
                # Didit MULTIPLE_CHOICE returns an array; these rules compare scalars.
                self.assertEqual(element['element_type'], 'single_choice')
                self.assertIn('unsure', {o['value'] for o in element['options']})
            if kind == 'person':
                self.assertTrue(any(r['field'].endswith('.additional_tax_id') and
                                    r['operator'] == 'is_not_empty' for r in rules))
