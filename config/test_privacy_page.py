from django.test import RequestFactory, SimpleTestCase

from config.views import deletion_view, privacy_view
from users.legal.documents import DELETION, PRIVACY


class PrivacyPageTests(SimpleTestCase):
    def test_public_page_renders_the_binding_document(self):
        # confio.lat/privacy and the app must show the same policy: the
        # page is rendered from users/legal/documents.py, never a copy.
        html = privacy_view(RequestFactory().get('/privacy')).content.decode()
        self.assertIn(f"Versión {PRIVACY['version']}", html)
        for section in PRIVACY['sections']:
            self.assertIn(section['title'], html)
        self.assertIn('Datos biométricos (rostro)', html)


class DeletionPageTests(SimpleTestCase):
    def test_public_page_renders_the_binding_document(self):
        html = deletion_view(RequestFactory().get('/deletion')).content.decode()
        self.assertIn(f"Versión {DELETION['version']}", html)
        for section in DELETION['sections']:
            self.assertIn(section['title'], html)
        self.assertIn('Su memoria de Confío IA', html)
