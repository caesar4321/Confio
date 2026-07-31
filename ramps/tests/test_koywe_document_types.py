from django.test import SimpleTestCase

from ramps.koywe_client import KoyweClient, KoyweError


class KoyweDocumentTypeResolutionTests(SimpleTestCase):
    """Foreign-resident IDs (Didit normalizes residence permits to
    ``foreign_id``) must resolve to the Koywe document type of the country
    that issued the card — migrants are the core user base."""

    def setUp(self):
        self.client = KoyweClient()

    def resolve(self, country, doc_type):
        return self.client._resolve_document_type(
            country_code=country, document_type=doc_type
        )

    def test_chile_foreign_id_maps_to_rut(self):
        # Chilean foreign-resident cards carry a RUN in RUT format.
        self.assertEqual(self.resolve('CL', 'foreign_id'), 'RUT')

    def test_peru_foreign_id_maps_to_ce(self):
        self.assertEqual(self.resolve('PE', 'foreign_id'), 'CE')

    def test_argentina_foreign_id_maps_to_dni(self):
        self.assertEqual(self.resolve('AR', 'foreign_id'), 'DNI')

    def test_colombia_foreign_id_maps_to_ced_ext(self):
        self.assertEqual(self.resolve('CO', 'foreign_id'), 'CED_EXT')

    def test_national_ids_unchanged(self):
        self.assertEqual(self.resolve('CL', 'national_id'), 'RUT')
        self.assertEqual(self.resolve('PE', 'national_id'), 'DNI')
        self.assertEqual(self.resolve('AR', 'national_id'), 'DNI')

    def test_mexico_foreign_id_still_rejected(self):
        # MX residence-card numbers are not reliably CURPs; keep rejecting
        # until the correct Koywe type is confirmed.
        with self.assertRaises(KoyweError):
            self.resolve('MX', 'foreign_id')
