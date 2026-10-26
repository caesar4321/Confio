"""Which verified document Stereum (QR Bolivia) registers a person with."""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from ramps.models import StereumCustomer
from ramps.stereum_client import StereumError
from ramps.stereum_customers import current_identity, identity_data, needs_document
from security.models import IdentityVerification
from users.models import User

SCOPE = 'test-scope'


def _document(user, number, **overrides):
    values = dict(
        user=user, status='verified', verified_first_name='ANA', verified_last_name='QUISPE',
        verified_date_of_birth=date(1990, 1, 1), verified_country='PER', verified_nationality='PER',
        document_type='national_id', document_number=number, document_issuing_country='PER',
        risk_factors={'provider': 'didit', 'didit': {'session_id': f'session-{number}'}},
        verified_at=timezone.now(),
    )
    values.update(overrides)
    return IdentityVerification.all_documents.create(**values)


class StereumDocumentChoiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='stereum-doc-choice', firebase_uid='stereum-doc-choice')

    def test_foreign_cedula_alone_needs_a_passport(self):
        _document(self.user, 'DNI-1')
        self.assertTrue(needs_document(self.user, SCOPE))
        with self.assertRaises(StereumError):
            current_identity(self.user, scope=SCOPE)

    def test_passport_added_after_a_cedula_is_used(self):
        _document(self.user, 'DNI-1')
        _document(self.user, 'CO-1', is_additional_document=True, document_issuing_country='COL')
        passport = _document(self.user, 'P-1', is_additional_document=True, document_type='passport')
        self.assertFalse(needs_document(self.user, SCOPE))
        self.assertEqual(current_identity(self.user, scope=SCOPE), passport)
        self.assertEqual(identity_data(passport)['document_type'], 'PASSPORT')

    def test_passport_holder_abroad_is_accepted(self):
        # Residence is not a condition: verified_country says Peru.
        passport = _document(self.user, 'P-2', document_type='passport')
        self.assertEqual(identity_data(passport)['country'], 'BO')

    def test_bolivian_ci_is_preferred_as_primary(self):
        ci = _document(self.user, 'CI-1', document_issuing_country='BOL', verified_country='BOL')
        _document(self.user, 'P-3', is_additional_document=True, document_type='passport')
        self.assertEqual(current_identity(self.user, scope=SCOPE), ci)
        self.assertEqual(identity_data(ci)['document_type'], 'CI')

    def test_foreign_resident_card_is_not_accepted(self):
        card = _document(self.user, 'CE-1', document_type='foreign_id', document_issuing_country='BOL')
        self.assertTrue(needs_document(self.user, SCOPE))
        with self.assertRaises(StereumError):
            identity_data(card)

    def test_expired_passport_is_skipped(self):
        _document(self.user, 'P-4', document_type='passport',
                  document_expiry_date=date.today() - timedelta(days=30))
        self.assertTrue(needs_document(self.user, SCOPE))

    def test_registration_stays_bound_to_its_document(self):
        first = _document(self.user, 'P-5', is_additional_document=True, document_type='passport')
        StereumCustomer.objects.create(user=self.user, credential_scope=SCOPE, source_verification=first,
                                       identity_fingerprint='x', request_snapshot={}, status='registered',
                                       consent_at=timezone.now())
        _document(self.user, 'CI-2', document_issuing_country='BOL')
        self.assertEqual(current_identity(self.user, scope=SCOPE), first)
        IdentityVerification.all_documents.filter(pk=first.pk).update(status='rejected')
        with self.assertRaises(StereumError):
            current_identity(self.user, scope=SCOPE)
