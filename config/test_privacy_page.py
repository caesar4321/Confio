from pathlib import Path

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve

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


class OldStaticPolicyTests(SimpleTestCase):
    def test_old_html_links_redirect_to_the_binding_pages(self):
        for page in ('privacy', 'deletion', 'terms'):
            for path in (f'/{page}.html', f'/{page}.html/'):
                match = resolve(path)
                response = match.func(RequestFactory().get(path), *match.args, **match.kwargs)
                self.assertEqual((response.status_code, response['Location']), (301, f'/{page}'))
            self.assertEqual(resolve(f'/{page}').url_name, page)

    def test_no_static_copy_shadows_the_redirect(self):
        # web/build too: it is what WhiteNoise serves at the root.
        for folder in ('web/public', 'web/build', 'staticfiles'):
            for page in ('privacy', 'deletion', 'terms'):
                self.assertFalse((Path(settings.BASE_DIR) / folder / f'{page}.html').exists(), f'{folder}/{page}')
