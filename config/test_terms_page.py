from django.test import RequestFactory, SimpleTestCase

from config.views import terms_view
from users.legal.documents import TERMS


class TermsPageTests(SimpleTestCase):
    def test_public_page_renders_the_binding_document(self):
        # confio.lat/terms and the app must show the same terms: the page is
        # rendered from users/legal/documents.py, never a hand-kept copy.
        html = terms_view(RequestFactory().get('/terms')).content.decode()
        self.assertIn(f"Versión {TERMS['version']}", html)
        for section in TERMS['sections']:
            self.assertIn(section['title'], html)
        self.assertIn('<strong>cUSD (Confío Dollar)</strong>', html)
        self.assertIn('Preventa de $CONFIO:', html)
        self.assertIn('mailto:legal@confio.lat', html)
        self.assertNotIn('2 de mayo de 2025', html)
