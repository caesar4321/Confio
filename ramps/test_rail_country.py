"""Rail-country order and the document Koywe sends (ramps.rail_country,
security.identity_status.rail_identity)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ramps.rail_country import rail_countries
from security import identity_status as ids
from security.models import IdentityVerification

User = get_user_model()


def document(user, number, *, issuing, document_type='national_id', additional=False):
    return IdentityVerification.all_documents.create(
        user=user, status='verified', verified_at=timezone.now(), document_number=number,
        verified_date_of_birth=date(1990, 1, 1),
        document_type=document_type, document_issuing_country=issuing, verified_country=issuing,
        verified_nationality=issuing, verified_first_name='Ana', verified_last_name='Pérez',
        verified_address='x', verified_city='y', verified_state='z',
        is_additional_document=additional,
    )


class RailCountryOrderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='rail-user', firebase_uid='rail-user')
        User.objects.filter(pk=self.user.pk).update(country='BO')
        self.user.refresh_from_db()

    def test_order_is_choice_then_residence_then_documents_then_device(self):
        # protects=the documented priority; fails_when=a document outranks where the user pays; no_claim=client rendering
        document(self.user, 'V-1', issuing='VEN')
        self.assertEqual(rail_countries(self.user, device_region='ar'), ['BO', 'VE', 'AR'])
        User.objects.filter(pk=self.user.pk).update(preferred_rail_country='PE')
        self.user.refresh_from_db()
        self.assertEqual(rail_countries(self.user), ['PE', 'BO', 'VE'])

    def test_bolivia_qr_follows_the_first_rail_country(self):
        # protects=a Bolivia resident with a Venezuelan ID keeps QR Bolivia; fails_when=the document country decides; no_claim=QR rollout flags
        from ramps.bolivia_qr import is_bolivian
        document(self.user, 'V-2', issuing='VEN')
        self.assertTrue(is_bolivian(self.user))
        User.objects.filter(pk=self.user.pk).update(preferred_rail_country='CO')
        self.user.refresh_from_db()
        self.assertFalse(is_bolivian(self.user))


class RailIdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='rail-id', firebase_uid='rail-id')

    def test_only_a_document_of_the_rail_country_counts(self):
        # protects=Koywe CO never receives a Venezuelan ID; fails_when=any primary document is sent; no_claim=Koywe's own acceptance
        document(self.user, 'V-3', issuing='VEN')
        self.assertIsNone(ids.rail_identity(self.user, 'CO'))
        colombian = document(self.user, 'PPT-1', issuing='COL', additional=True)
        self.assertEqual(ids.rail_identity(self.user, 'CO'), colombian)
        self.assertEqual(ids.rail_identity(self.user, 'COL'), colombian)

    def test_a_national_id_is_preferred_over_a_passport(self):
        # protects=a person with both is sent with the document Koywe takes; fails_when=the newer passport wins; no_claim=none beyond protects
        cedula = document(self.user, 'C-1', issuing='PER')
        document(self.user, 'P-1', issuing='PER', document_type='passport', additional=True)
        self.assertEqual(ids.rail_identity(self.user, 'PE'), cedula)

    def test_koywe_error_names_the_country_it_needs(self):
        # protects=the person learns which document opens this country; fails_when=the old phone-number copy shows; no_claim=app rendering
        from ramps.koywe_client import KoyweError
        from ramps.schema import _get_koywe_contact_profile
        document(self.user, 'V-4', issuing='VEN')
        with self.assertRaisesRegex(KoyweError, 'Colombia'):
            _get_koywe_contact_profile(user=self.user, country_code='CO')
