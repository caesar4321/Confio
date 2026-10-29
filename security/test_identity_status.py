"""Who is verified: a person verified ONLY by an additional document (a passport
from another country) is verified everywhere; Koywe reads a document of the
order's country (rail_identity), whichever kind it is."""
from datetime import date, timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from security import identity_status as ids
from security.models import FaceReference, IdentityVerification
from users.models import User


def document(user, number, **overrides):
    values = dict(
        user=user, status='verified', verified_first_name='Ana', verified_last_name='Perez',
        verified_date_of_birth=date(1990, 1, 1), verified_country='VEN', verified_nationality='VEN',
        document_type='national_id', document_number=number, document_issuing_country='VEN',
        risk_factors={'provider': 'didit', 'didit': {'session_id': f'session-{number}'}},
        verified_at=timezone.now(),
    )
    values.update(overrides)
    return IdentityVerification.all_documents.create(**values)


def info_for(user):
    return SimpleNamespace(context=SimpleNamespace(user=user, META={}))


class AdditionalDocumentOnlyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='passport-only', firebase_uid='passport-only')
        self.passport = document(self.user, 'P-ONLY', document_type='passport', document_issuing_country='VEN',
                                 verified_country='COL', is_additional_document=True)

    def test_vocabulary(self):
        self.assertTrue(ids.is_identity_verified(self.user))
        # A Venezuelan passport naming Colombia as residence is still not a Colombian document.
        self.assertIsNone(ids.rail_identity(self.user, 'CO'))
        self.assertEqual(ids.rail_identity(self.user, 'VE'), self.passport)
        self.assertTrue(ids.has_ever_passed_kyc(self.user))
        self.assertEqual(ids.identity_status(self.user), 'verified')
        self.assertEqual(ids.verified_at(self.user), self.passport.verified_at)
        self.assertEqual(ids.current_document(self.user), self.passport)
        self.assertIn(self.user.id, set(ids.verified_user_ids()))

    def test_user_properties_agree(self):
        self.assertTrue(self.user.is_identity_verified)
        self.assertTrue(self.user.has_verified_identity_document)
        self.assertTrue(self.user.has_passed_identity_verification)
        self.assertTrue(self.user.has_rail_identity)  # primary rail country = the document's
        self.assertEqual(self.user.verification_status, 'verified')
        self.assertEqual(self.user.last_verified_date, self.passport.verified_at)

    def test_graphql_fields_the_app_reads(self):
        from security.schema import SecurityQuery
        from users.schema import UserType
        status = SecurityQuery.resolve_my_identity_status(None, info_for(self.user))
        self.assertEqual((status.verified, status.phone_country_verified, status.ever_passed_kyc, status.status),
                         (True, True, True, 'verified'))
        self.assertEqual(SecurityQuery.resolve_my_personal_verified_kyc(None, info_for(self.user)), self.passport)
        self.assertTrue(UserType.resolve_is_identity_verified(self.user, None))
        self.assertEqual(UserType.resolve_verification_status(self.user, None), 'verified')
        self.assertEqual(UserType.resolve_last_verified_date(self.user, None), self.passport.verified_at)

    def test_koywe_reads_a_document_of_the_order_country(self):
        # protects=Koywe gets the order country's document, primary or not; fails_when=it reads "the primary" again; no_claim=Koywe acceptance
        from ramps.schema import _get_latest_personal_verification
        self.assertIsNone(_get_latest_personal_verification(self.user, 'PE'))
        peruvian = document(self.user, 'PE-1', document_issuing_country='PER', verified_country='PER',
                            verified_nationality='PER')
        self.assertEqual(_get_latest_personal_verification(self.user, 'PE'), peruvian)
        self.assertTrue(ids.has_rail_identity(self.user, 'PE'))

    def test_koywe_tells_a_passport_only_person_which_document_it_needs(self):
        from ramps.koywe_client import KoyweError
        from ramps.schema import _get_koywe_contact_profile
        with self.assertRaisesRegex(KoyweError, 'documento de identidad de Perú'):
            _get_koywe_contact_profile(user=self.user, country_code='PE')

    def test_payment_accounts_find_the_personal_document(self):
        # Personal rows carry no account_type key; .exclude() on it dropped them all.
        from payment_accounts.schema import _verified_identity
        self.assertEqual(_verified_identity(SimpleNamespace(account_type='personal', user=self.user)), self.passport)
        primary = document(self.user, 'V-2', verified_at=timezone.now() - timedelta(days=90))
        self.assertEqual(_verified_identity(SimpleNamespace(account_type='personal', user=self.user)), primary)

    def test_humanitarian_country_kyc_counts_the_passport(self):
        from humanitarian.models import HumanitarianVolunteerApplication
        has = HumanitarianVolunteerApplication.has_verified_country_kyc.fget
        self.assertTrue(has(SimpleNamespace(user=self.user, campaign=SimpleNamespace(country_code='VEN'))))
        self.assertFalse(has(SimpleNamespace(user=self.user, campaign=SimpleNamespace(country_code='PER'))))

    def test_p2p_badge_and_trust_score(self):
        from p2p_exchange.schema import _identity_verified
        from users.abuse_prevention import AbusePreventionService
        self.assertTrue(_identity_verified(self.user))
        self.assertTrue(AbusePreventionService.check_activity_requirements(self.user)['kyc_verified'])

    def test_face_reference_from_the_passport_when_none_stands(self):
        from security.face_step_up import _newer_reference_exists
        self.assertFalse(_newer_reference_exists(self.passport))
        primary = document(self.user, 'V-3', verified_at=timezone.now() - timedelta(days=30))
        FaceReference.objects.create(user=self.user, identity_verification=primary, s3_key='k', sha256='0' * 64,
                                     source='didit_liveness')
        # The primary document's selfie is never displaced by an additional one.
        self.assertTrue(_newer_reference_exists(self.passport))


class WhatDoesNotCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='not-verified', firebase_uid='not-verified')

    def test_business_kyb_is_not_a_persons_kyc(self):
        document(self.user, 'B-1', risk_factors={'provider': 'didit', 'account_type': 'business', 'business_id': '7'})
        self.assertFalse(ids.is_identity_verified(self.user))
        self.assertFalse(ids.has_ever_passed_kyc(self.user))
        self.assertEqual(ids.identity_status(self.user), 'unverified')
        self.assertTrue(ids.is_business_verified(7))
        self.assertEqual(ids.business_status(7), 'verified')
        from users.schema import BusinessType
        business = SimpleNamespace(id=7)
        self.assertTrue(BusinessType.resolve_is_verified(business, None))
        self.assertEqual(BusinessType.resolve_verification_status(business, None), 'verified')
        self.assertIsNotNone(BusinessType.resolve_last_verified_date(business, None))
        self.assertFalse(BusinessType.resolve_is_verified(SimpleNamespace(id=8), None))

    def test_an_expired_document_is_ever_passed_but_not_current(self):
        document(self.user, 'P-EXP', status='expired', is_additional_document=True)
        self.assertFalse(ids.is_identity_verified(self.user))
        self.assertTrue(ids.has_ever_passed_kyc(self.user))
        self.assertTrue(self.user.has_passed_identity_verification)

    def test_pending_additional_document_shows_pending(self):
        document(self.user, 'P-PEND', status='pending', verified_at=None, is_additional_document=True)
        self.assertEqual(ids.identity_status(self.user), 'pending')
        self.assertFalse(ids.is_identity_verified(self.user))
