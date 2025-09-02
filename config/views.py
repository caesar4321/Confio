from django.shortcuts import render
from django.utils.translation import get_language_from_request
from django.views.generic import TemplateView
from django.http import HttpResponse
import logging
import os
import json
from django.conf import settings

logger = logging.getLogger(__name__)


def _resolve_main_assets():
    """Resolve main.js and main.css URLs robustly.

    Strategy:
    1) Try manifests in likely locations: static/, staticfiles/, web/build/.
       Validate that referenced files exist on disk under one of the known
       static roots that Nginx/Django can serve.
    2) Fallback: scan for latest main.* in staticfiles/ first (preferred for prod),
       then web/build/static/, then static/.
    Returns (js_url, css_url) as URL paths beginning with /static/.
    """
    base = settings.BASE_DIR
    candidates_manifests = [
        os.path.join(base, 'static', 'asset-manifest.json'),
        os.path.join(base, 'staticfiles', 'asset-manifest.json'),
        os.path.join(base, 'web', 'build', 'asset-manifest.json'),
    ]

    # Map URL /static/... to possible on-disk roots
    static_roots = [
        os.path.join(base, 'staticfiles'),
        os.path.join(base, 'web', 'build', 'static'),
        os.path.join(base, 'static'),
    ]

    def url_exists(url_path: str) -> bool:
        if not url_path:
            return False
        rel = url_path.lstrip('/')
        for root in static_roots:
            disk_path = os.path.join(root, rel.split('static/', 1)[-1]) if 'static/' in rel else os.path.join(root, rel)
            if os.path.exists(disk_path):
                return True
        return False

    js_url = None
    css_url = None

    # Try manifests
    for manifest_path in candidates_manifests:
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            files = manifest.get('files') or {}
            cand_js = files.get('main.js')
            cand_css = files.get('main.css')
            # Fallback to entrypoints
            if (not cand_js or not cand_css) and 'entrypoints' in manifest:
                for ep in manifest.get('entrypoints') or []:
                    if ep.endswith('.js') and not cand_js:
                        cand_js = '/' + ep.lstrip('/') if not ep.startswith('/') else ep
                    if ep.endswith('.css') and not cand_css:
                        cand_css = '/' + ep.lstrip('/') if not ep.startswith('/') else ep
            # Validate existence on disk
            if cand_js and cand_css and url_exists(cand_js) and url_exists(cand_css):
                js_url, css_url = cand_js, cand_css
                break
        except Exception:
            continue

    def pick_latest_from_dir(root_dir, subdir, prefix, ext):
        try:
            full_dir = os.path.join(root_dir, subdir)
            names = [n for n in os.listdir(full_dir) if n.startswith(prefix) and n.endswith(ext)]
            if not names:
                return None
            names.sort(key=lambda n: os.path.getmtime(os.path.join(full_dir, n)), reverse=True)
            return f"/static/{subdir}/{names[0]}"
        except Exception:
            return None

    # Fallback scanning preference: staticfiles -> web/build/static -> static
    if not js_url:
        for root in static_roots:
            js_url = pick_latest_from_dir(root, 'js', 'main.', '.js')
            if js_url and url_exists(js_url):
                break
            js_url = None
    if not css_url:
        for root in static_roots:
            css_url = pick_latest_from_dir(root, 'css', 'main.', '.css')
            if css_url and url_exists(css_url):
                break
            css_url = None

    return js_url, css_url


def index(request):
	path = request.path.lower()
	lang = get_language_from_request(request)
	
	# Check for Korean language specifically
	if 'ko' in lang.lower():
		lang = 'ko'
	elif 'es' in lang.lower():
		lang = 'es'
	else:
		lang = 'en'  # Default to English for all other languages
	
	titles = {
		'es': 'Confío: PayPal de América Latina',
		'en': 'Confío: PayPal of Latin America',
		'ko': 'Confío: 라틴 아메리카의 PayPal',
		'default': 'Confío: PayPal de América Latina'
	}
	
	title = titles.get(lang, titles['default'])
	og_description = {
		'es': 'Sé de los primeros 10,000 beta testers. Envía y recibe dólares digitales sin comisiones. Protege tu dinero de la inflación en Venezuela, Argentina y Bolivia.',
		'en': 'Be among the first 10,000 beta testers. Send and receive digital dollars with no fees. Protect your money from inflation in Venezuela, Argentina and Bolivia.',
		'ko': '첫 10,000명의 베타 테스터가 되세요. 수수료 없이 디지털 달러를 보내고 받으세요. 베네수엘라, 아르헨티나, 볼리비아의 인플레이션으로부터 돈을 보호하세요.',
		'default': 'Confío: Digital payments for Latin America'
	}
	og_image = "https://confio.lat/images/ConfioApp.png"

	main_js_url, main_css_url = _resolve_main_assets()
	
	return render(request, 'index.html', {
		'lang': lang,
		'title': title or titles['default'],
		'ogDescription': og_description.get(lang, og_description['default']) or og_description['default'],
		'ogImage': og_image,
		'main_js_url': main_js_url,
		'main_css_url': main_css_url,
	})

class LegalPageView(TemplateView):
	template_name = None

	def get_template_names(self):
		page = self.kwargs.get('page')
		return [f'legal/{page}.html']

def terms_view(request):
	"""View for Terms of Service page."""
	return render(request, 'terms.html')

def privacy_view(request):
	"""View for Privacy Policy page."""
	return render(request, 'privacy.html')

def deletion_view(request):
    """View for Data Deletion page."""
    return render(request, 'deletion.html')


# Removed /health endpoint (not required for WS flow)
