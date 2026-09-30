from django.test import RequestFactory, SimpleTestCase

from config.views import privacy_view
from users.legal.documents import PRIVACY


class PrivacyPageTests(SimpleTestCase):
    def test_public_page_renders_the_binding_document(self):
        # confio.lat/privacy and the app must show the same policy: the
        # page is rendered from users/legal/documents.py, never a copy.
        html = privacy_view(RequestFactory().get('/privacy')).content.decode()
        self.assertIn(f"Versión {PRIVACY['version']}", html)
        for section in PRIVACY['sections']:
            self.assertIn(section['title'], html)
        self.assertIn('Datos biométricos (rostro)', html)
