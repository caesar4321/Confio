"""Recargar asks for this country's ID or residence permit (Didit 'RP').

TopUpScreen sends documentTypes ['ID', 'RP'] for a person verified with
another country's document; before 'RP' was allowed the server refused that
request with 'Tipo de documento no válido.' and the button did nothing.
"""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase

from security.didit import (
    _extract_verification_payload, _review_additional_document, normalize_document_request,
)
from security.models import IdentityVerification
from users.models import Account, User

TOP_UP_REQUEST = {'id_country': 'COL', 'document_types': ['ID', 'RP']}


class ResidencePermitRequestTests(SimpleTestCase):
    def test_top_up_request_is_valid(self):
        self.assertEqual(normalize_document_request('COL', ['ID', 'RP']), TOP_UP_REQUEST)
        self.assertEqual(normalize_document_request('co', ['rp']), {'id_country': 'COL', 'document_types': ['RP']})

    def test_rp_is_dropped_where_the_rail_cannot_use_a_residence_permit(self):
        for country in ('BOL', 'MEX', 'BRA'):
            self.assertEqual(normalize_document_request(country, ['ID', 'RP'])['document_types'], ['ID'], country)
        for country in ('ARG', 'CHL', 'COL', 'PER'):
            self.assertEqual(normalize_document_request(country, ['ID', 'RP'])['document_types'], ['ID', 'RP'],
                             country)

    def test_rp_countries_match_koywe(self):
        from ramps.koywe_client import _COUNTRY_DOCUMENT_TYPE_MAP
        from security.didit import RESIDENCE_PERMIT_RAIL_COUNTRIES
        from security.geo import to_iso3
        mapped = {to_iso3(iso2) for iso2, types in _COUNTRY_DOCUMENT_TYPE_MAP.items() if 'foreign_id' in types}
        self.assertEqual(RESIDENCE_PERMIT_RAIL_COUNTRIES, mapped)

    def test_didit_residence_permit_is_stored_as_foreign_id(self):
        fields = _extract_verification_payload({'id_verifications': [{
            'document_type': 'Residence Permit', 'issuing_state': 'COL', 'first_name': 'Ana', 'last_name': 'Perez'}]})
        self.assertEqual(fields['document_type'], 'foreign_id')


class ResidencePermitReviewTests(TestCase):
    def setUp(self):
        face = mock.patch('security.didit._same_face', return_value='match')
        face.start()
        self.addCleanup(face.stop)
        self.user = User.objects.create_user(username='resident', firebase_uid='resident')
        Account.objects.create(user=self.user, account_type='personal')
        self.document('ARG-1', document_issuing_country='ARG')

    def document(self, number, **overrides):
        values = dict(
            user=self.user, status='verified', verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth=date(1990, 1, 1), document_type='national_id', document_number=number,
            document_issuing_country='ARG', risk_factors={'provider': 'didit'},
        )
        values.update(overrides)
        return IdentityVerification.all_documents.create(**values)

    def review(self, document_type, country='COL', request=None):
        row = self.document(f'{document_type}-{country}-{len(request or [])}', status='pending',
                            is_additional_document=True,
                            risk_factors={'provider': 'didit', 'document_request': request or TOP_UP_REQUEST})
        extracted = dict(document_issuing_country=country, document_type=document_type,
                         verified_first_name='ANA', verified_last_name='PEREZ',
                         verified_date_of_birth=date(1990, 1, 1))
        return _review_additional_document(row, extracted, {})[0]

    def test_this_countrys_residence_permit_or_id_meets_the_top_up_request(self):
        self.assertEqual(self.review('foreign_id'), 'verified')
        self.assertEqual(self.review('national_id'), 'verified')

    def test_a_passport_or_another_countrys_permit_does_not(self):
        self.assertEqual(self.review('passport'), 'rejected')
        self.assertEqual(self.review('foreign_id', country='PER'), 'rejected')

    def test_other_requests_keep_refusing_a_residence_permit(self):
        self.assertEqual(self.review('foreign_id', request={'id_country': '', 'document_types': ['ID', 'P']}),
                         'rejected')
        self.assertEqual(self.review('national_id', request={'id_country': 'COL', 'document_types': ['RP']}),
                         'rejected')
