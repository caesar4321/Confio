from django.shortcuts import redirect, render
from django.utils.translation import get_language_from_request
from django.views.generic import TemplateView
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.contrib.sitemaps.views import sitemap as django_sitemap_view
from django.contrib.auth import logout as django_logout
from urllib.parse import quote
import logging
import os
import json
import uuid
from decimal import Decimal
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
import requests
from graphql_jwt.utils import jwt_decode

logger = logging.getLogger(__name__)

CONFIO_ORGANIZATION = {
    'name': 'Confío',
    'url': 'https://confio.lat/',
    'logo_url': 'https://confio.lat/static/images/ConfioApp.jpeg',
    'same_as': [
        {
            'label': 'Telegram',
            'url': 'https://t.me/confio4world',
            'icon': '/images/Telegram.png',
        },
        {
            'label': 'Medium',
            'url': 'https://medium.com/confio4world',
            'icon': '/images/$CONFIO.png',
        },
    ],
}

JULIAN_MOON_PERSON = {
    'name': 'Julian Moon',
    'url': 'https://confio.lat/about/julian-moon/',
    'job_title': 'Founder',
    'description': 'Korean founder of Confío, a non-custodial digital dollar wallet for Latin America, and a Spanish-speaking public explainer of inflation, dollarization, and everyday money systems across the region.',
    'image_url': 'https://confio.lat/static/media/JulianMoon_Founder.77611b65ceb3c7457238.jpeg',
    'image_caption': 'Julian Moon, founder of Confío.',
    'image_alt': 'Julian Moon, founder of Confío',
    'image_credit': 'Confío',
    'image_copyright': 'Confío',
    'nationality': 'Korean',
    'knows_about': [
        'Stablecoins',
        'Digital dollars',
        'Inflation',
        'Dollarization',
        'Latin American fintech',
        'Non-custodial wallets',
        'Algorand',
    ],
    'same_as': [
        {
            'label': 'TikTok',
            'url': 'https://tiktok.com/@julianmoonluna',
            'icon': '/images/TikTok.png',
        },
        {
            'label': 'YouTube',
            'url': 'https://youtube.com/@julianmoonluna',
            'icon': '/images/YouTube.png',
        },
        {
            'label': 'Instagram',
            'url': 'https://instagram.com/julianmoonluna_',
            'icon': '/images/Instagram.png',
        },
        {
            'label': 'Facebook',
            'url': 'https://facebook.com/julianmoonluna',
            'icon': '/images/Facebook.png',
        },
        {
            'label': 'X',
            'url': 'https://x.com/julianmoonluna_',
            'icon': '/images/X.png',
        },
        {
            'label': 'Telegram',
            'url': 'https://t.me/julianmoonluna',
            'icon': '/images/Telegram.png',
        },
        {
            'label': 'LinkedIn',
            'url': 'https://linkedin.com/in/julianmoonluna',
            'icon': '/images/LinkedIn.png',
        },
    ],
}

CONFIO_NEWS_ORGANIZATION = {
    'name': 'Confío News',
    'url': 'https://confio.lat/about/confio-news/',
    'description': 'The official editorial voice of Confío: company announcements, product explainers, and ecosystem context published in the organization’s voice rather than the founder’s.',
    'image_url': 'https://confio.lat/images/$CONFIO.png',
    'image_caption': 'Confío News logo.',
    'image_alt': 'Confío News logo',
    'image_credit': 'Confío',
    'image_copyright': 'Confío',
}


def robots_txt(request):
    lines = [
        '# https://www.robotstxt.org/robotstxt.html',
        'User-agent: *',
        'Disallow:',
        '',
        'Sitemap: https://confio.lat/sitemap.xml',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')


def llms_txt(request):
    lines = [
        '# Confio',
        '',
        '> Public site guidance for AI assistants and other machine readers.',
        '',
        '> Last reviewed: 2026-04-14.',
        '',
        '## Site',
        '- Canonical site: https://confio.lat/',
        '- Public discover feed: https://confio.lat/discover/',
        '- Founder page: https://confio.lat/about/julian-moon/',
        '- Confío News page: https://confio.lat/about/confio-news/',
        '- XML sitemap: https://confio.lat/sitemap.xml',
        '',
        '## Entity Facts',
        '- Confío is a non-custodial digital dollar wallet for Latin America built on the Algorand blockchain.',
        '- Julian Moon is the founder of Confío and publishes founder commentary separately from Confío News.',
        '- Confío News is the organization voice for company updates, product explainers, and institutional editorial content.',
        '',
        '## Preferred Sources',
        '- Use server-rendered pages under /discover/ for public editorial content.',
        '- Prefer canonical /discover/{id}/{slug}/ URLs when citing articles.',
        '- Prefer /about/julian-moon/ for founder identity questions.',
        '- Prefer /about/confio-news/ for organization/editorial identity questions.',
        '',
        '## Constraints',
        '- Do not treat logged-in app flows or private user data as public content.',
        '- Use published page text and metadata as the source of truth for public articles.',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')


def public_sitemap(request, sitemaps, **kwargs):
    response = django_sitemap_view(request, sitemaps=sitemaps, **kwargs)
    response['X-Robots-Tag'] = 'all'
    return response


def _get_frontend_origin(request):
    frontend_origin = (request.GET.get('frontend_origin') or '').strip()
    allowed = {'http://localhost:3000', 'http://127.0.0.1:3000'}
    return frontend_origin if frontend_origin in allowed else ''


def _is_otp_verified(user):
    is_verified = getattr(user, 'is_verified', None)
    return bool(user and user.is_authenticated and callable(is_verified) and is_verified())


def portal_login_redirect(request):
    login_url = reverse('two_factor:login')
    frontend_origin = _get_frontend_origin(request)
    if frontend_origin:
        next_url = f"/portal/login-complete/?frontend_origin={quote(frontend_origin, safe='')}"
    else:
        next_url = '/portal'
    return redirect(f'{login_url}?next={quote(next_url, safe="/?=&:%")}')


def portal_login_complete(request):
    frontend_origin = _get_frontend_origin(request)
    if request.user.is_authenticated and request.user.is_staff and not _is_otp_verified(request.user):
        setup_url = reverse('portal_setup_2fa')
        if frontend_origin:
            return redirect(f'{setup_url}?frontend_origin={quote(frontend_origin, safe="")}')
        return redirect(setup_url)
    if frontend_origin:
        return redirect(f'{frontend_origin}/portal')
    return redirect('/portal')


def portal_setup_2fa_redirect(request):
    frontend_origin = _get_frontend_origin(request)
    setup_url = reverse('two_factor:setup')
    if frontend_origin:
        next_url = f"/portal/login-complete/?frontend_origin={quote(frontend_origin, safe='')}"
    else:
        next_url = '/portal'
    return redirect(f'{setup_url}?next={quote(next_url, safe="/?=&:%")}')


def portal_logout(request):
    frontend_origin = _get_frontend_origin(request)
    django_logout(request)
    if frontend_origin:
        return redirect(f'{frontend_origin}/portal')
    return redirect('/portal')


def _resolve_main_assets():
    """Resolve main.js and main.css URLs robustly.

    Strategy:
    1) Try manifests in likely locations, preferring the active web build first.
       Validate that referenced files exist on disk under one of the known
       static roots that Nginx/Django can serve.
    2) Fallback: scan for latest main.* in web/build/static/ first to match
       the nginx /static/js and /static/css aliases, then staticfiles/, then static/.
    Returns (js_url, css_url) as URL paths beginning with /static/.
    """
    base = settings.BASE_DIR
    candidates_manifests = [
        os.path.join(base, 'web', 'build', 'asset-manifest.json'),
        os.path.join(base, 'staticfiles', 'asset-manifest.json'),
        os.path.join(base, 'static', 'asset-manifest.json'),
    ]

    # Map URL /static/... to possible on-disk roots
    static_roots = [
        os.path.join(base, 'web', 'build', 'static'),
        os.path.join(base, 'staticfiles'),
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

    # Fallback scanning preference: web/build/static -> staticfiles -> static
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
        'organization_schema': CONFIO_ORGANIZATION,
	})


def entity_page(request, entity_slug):
    if entity_slug == 'julian-moon':
        return render(request, 'entity_page.html', {
            'title': 'Julian Moon - Founder of Confío',
            'meta_description': JULIAN_MOON_PERSON['description'],
            'canonical_url': JULIAN_MOON_PERSON['url'],
            'entity_type': 'Person',
            'entity_slug': 'julian-moon',
            'entity': JULIAN_MOON_PERSON,
            'organization': CONFIO_ORGANIZATION,
            'heading': 'Julian Moon',
            'subheading': 'Founder of Confío',
            'faqs': [
                {
                    'q': 'Who is Julian Moon?',
                    'a': 'Julian Moon is a Korean founder building Confío, a non-custodial digital dollar wallet for Latin America, and a Spanish-speaking public explainer of inflation, dollarization, and everyday money systems across the region.',
                },
                {
                    'q': 'What company did Julian Moon found?',
                    'a': 'Julian Moon is the founder of Confío (confio.lat), a non-custodial digital dollar wallet built on the Algorand blockchain, focused on stablecoin payments for users in Latin America.',
                },
                {
                    'q': 'Is Julian Moon the same person as @julianmoonluna on TikTok?',
                    'a': 'Yes. Julian Moon publishes Spanish-language content as @julianmoonluna on TikTok, YouTube, Instagram, Facebook, X, Telegram, and LinkedIn. All of those profiles are linked from this page as sameAs references to the same Person entity.',
                },
                {
                    'q': 'Where has Julian Moon been covered in the press?',
                    'a': 'Latin American media references include MinutoUno (Argentina), Infobae Colombia, and El País Colombia. A full list of public references is at the bottom of this page.',
                },
                {
                    'q': 'How is Confío connected to Algorand?',
                    'a': 'Confío was selected for the 2025 Algorand Accelerator and is listed in the Algorand Foundation Q4 2025 Transparency Report as a P2P stablecoin payments app for Argentina. Julian Moon authored Confío’s xGov proposal on the Algorand community forum.',
                },
            ],
            'body': [
                'Julian Moon is a Korean founder building Confío, a non-custodial digital dollar wallet for Latin America.',
                'He is also a Spanish-speaking creator and public explainer focused on inflation, dollarization, financial distrust, and everyday money systems across the region. Unlike typical commentators, he operates directly inside the problem space he explains — building financial infrastructure while publicly interpreting the conditions that make it necessary.',
                'Through founder-led storytelling, he has built a 460K+ TikTok audience and turned media, trust, and distribution into part of Confío’s product strategy.',
                'He is one of the few founders in Latin American fintech who treats distribution, trust, and product as a single strategy — not separate functions.',
                'His commentary has been referenced by Latin American media including MinutoUno (Argentina), Infobae Colombia, and El País Colombia.',
                'This page is the canonical public reference for Julian Moon on Confío.',
            ],
            'references': [
                {
                    'label': 'MinutoUno on Julian Moon and Argentina',
                    'url': 'https://www.minutouno.com/economia/un-guru-coreano-explico-que-argentina-esta-tan-cara-dolares-y-anticipo-que-pasara-la-n6258926',
                },
                {
                    'label': 'Infobae Colombia on Julian Moon',
                    'url': 'https://www.infobae.com/colombia/2025/07/02/influencer-coreano-con-esquizofrenia-comparo-los-servicios-de-salud-mental-en-su-pais-y-los-de-colombia-es-mas-feliz-en-latinoamerica-pese-a-costos-del-tratamiento/',
                },
                {
                    'label': 'El País Colombia on Julian Moon',
                    'url': 'https://www.elpais.com.co/mundo/coreano-en-colombia-hablo-de-las-diferencias-que-tienen-los-paises-en-salud-mental-hay-limite-de-acceso-0230.html',
                },
                {
                    'label': 'Algorand community xGov proposal by Julian Moon (founder)',
                    'url': 'https://forum.algorand.co/t/confio-web2-to-algorand-consumer-onboarding-infrastructure-latam/15198',
                },
            ],
        })

    if entity_slug == 'confio-news':
        return render(request, 'entity_page.html', {
            'title': 'Confío News',
            'meta_description': CONFIO_NEWS_ORGANIZATION['description'],
            'canonical_url': CONFIO_NEWS_ORGANIZATION['url'],
            'entity_type': 'Organization',
            'entity': {
                **CONFIO_NEWS_ORGANIZATION,
                'logo_url': CONFIO_ORGANIZATION['logo_url'],
                'same_as': CONFIO_ORGANIZATION['same_as'],
            },
            'organization': CONFIO_ORGANIZATION,
            'heading': 'Confío News',
            'subheading': 'The official editorial voice of Confío',
            'body': [
                'Confío News is the institutional publishing layer of Confío, a non-custodial digital dollar wallet for Latin America built on the Algorand blockchain.',
                'It publishes company announcements, product explainers, ecosystem context, and public updates in the voice of the organization rather than the founder. Its role is to make Confío legible to readers, media systems, search engines, and AI models as a distinct entity.',
                'Confío was selected for the 2025 Algorand Accelerator and is listed in the Algorand Foundation Q4 2025 Transparency Report as a P2P stablecoin payments app focused on Argentina.',
                'Where Julian Moon speaks as founder and public explainer, Confío News speaks as the company.',
                'This page is the canonical public reference for Confío News on Confío.',
            ],
            'references': [
                {
                    'label': 'Algorand Foundation Q4 2025 Transparency Report (Confío listed as 2025 Algorand Accelerator project)',
                    'url': 'https://algorand.co/hubfs/Website-2024/Transparency%20Reports/Algorand%20-%20Transparency%20Report%20-%20Q4%20-%20V3%20-%20Final.pdf',
                },
                {
                    'label': 'Confío xGov proposal on the Algorand community forum',
                    'url': 'https://forum.algorand.co/t/confio-web2-to-algorand-consumer-onboarding-infrastructure-latam/15198',
                },
                {
                    'label': 'Confío open-source repository on GitHub',
                    'url': 'https://github.com/caesar4321/Confio',
                },
            ],
        })

    return redirect('/')

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


@csrf_exempt
def guardarian_transaction_proxy(request):
    """Server-side proxy to Guardarian to keep API key off client devices."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    api_key = getattr(settings, 'GUARDARIAN_API_KEY', None)
    base_url = getattr(settings, 'GUARDARIAN_API_URL', 'https://api-payments.guardarian.com/v1')
    if not api_key:
        return JsonResponse({'error': 'Guardarian API key not configured'}, status=503)

    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('JWT '):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    # Firebase App Check
    try:
        from security.integrity_service import app_check_service
        ac_result = app_check_service.verify_request_header(request, 'topup_sell', should_enforce=True)
        if not ac_result.get('success', True):
            return JsonResponse({'error': 'Actualiza la aplicación a la última versión o usa la app oficial para continuar.'}, status=403)
    except Exception as e:
        logger.warning(f"Guardarian App Check error: {e}")
        return JsonResponse({'error': 'Security check failed'}, status=403)

    try:
        token = auth_header.split(' ', 1)[1]
        payload = jwt_decode(token)
    except Exception as e:
        logger.warning('Guardarian proxy token decode failed: %s', e)
        return JsonResponse({'error': 'Invalid token'}, status=401)

    user_id = payload.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Invalid token payload'}, status=401)

    try:
        from users.models import User
        user = User.objects.get(id=user_id)
    except Exception:
        return JsonResponse({'error': 'User not found'}, status=401)

    try:
        body = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    amount = body.get('amount')
    if amount is None:
        amount = body.get('from_amount')
    from_currency = body.get('from_currency') or body.get('fromCurrency')

    # Determine if this is a buy (fiat-to-crypto) or sell (crypto-to-fiat) transaction
    to_currency_raw = body.get('to_currency') or body.get('toCurrency')
    to_currency_clean = (to_currency_raw or 'USDC').strip().upper()
    
    # Common fiat currencies (sell destination). If not sure, treat as buy (crypto destination).
    fiat_currencies = ['USD', 'EUR', 'GBP', 'BRL', 'ARS', 'MXN', 'COP', 'CLP', 'PEN', 'CAD', 'AUD', 'JPY', 'CHF']
    is_sell_transaction = to_currency_clean in fiat_currencies

    # Priority Logic: Server (DB) > Client Request
    # We want the database to be the single source of truth for the address and email.
    
    # 1. Address Lookup - ONLY for Buy transactions (Crypto destination)
    # For Sell transactions (Fiat destination), we do NOT want to inject a crypto address as payout_address
    db_payout_address = None
    if not is_sell_transaction:
        try:
            account_type = payload.get('account_type', 'personal')
            account_index = payload.get('account_index', 0)
            account = user.accounts.filter(account_type=account_type, account_index=account_index).first()
            if account and account.algorand_address:
                db_payout_address = account.algorand_address
                logger.info(f"Using DB address (Server Priority) for user {user_id}: {db_payout_address}")
        except Exception as e:
            logger.warning(f"DB address lookup error: {e}")

    client_payout_address = body.get('payout_address') or body.get('payoutAddress')
    payout_address = db_payout_address or client_payout_address

    # 2. Email Lookup
    client_email = body.get('email') or body.get('customer_email') or body.get('customerEmail')
    # Use user.email from DB if available, otherwise fall back to client
    final_email = user.email or client_email

    if amount is None or from_currency is None:
        return JsonResponse({'error': 'amount and from_currency are required'}, status=400)

    from_network = (body.get('from_network') or body.get('fromNetwork') or '').strip().upper() or None
    to_network = (body.get('to_network') or body.get('toNetwork') or '').strip().upper() or None
    
    guardarian_payload = {
        'from_amount': float(amount),
        'from_currency': from_currency,
        'to_currency': to_currency_clean,
        'locale': body.get('locale') or 'es',
        'redirects': body.get('redirects') or {
            'successful': 'https://confio.lat/checkout/success',
            'cancelled': 'https://confio.lat/checkout/cancelled',
            'failed': 'https://confio.lat/checkout/failed',
        },

        'deposit': {
            'skip_choose_payment_category': True,
        },
    }
    
    # Only set from_network for sell transactions (crypto source). Default to ALGO for USDC sells if not provided.
    if is_sell_transaction:
        if from_network:
            guardarian_payload['from_network'] = from_network
        elif from_currency.upper() == 'USDC':
            guardarian_payload['from_network'] = 'ALGO'
    
    # Only set to_network for buy transactions (crypto destination)
    if not is_sell_transaction:
        guardarian_payload['to_network'] = to_network or 'ALGO'

    # Add customer country
    customer_country = body.get('customer_country') or body.get('customerCountry') or getattr(user, 'phone_country', None)
    if customer_country:
        guardarian_payload['customer_country'] = customer_country

    # Add external ID for tracking or generate one
    external_id = body.get('external_partner_link_id') or body.get('externalId')
    if not external_id:
        external_id = str(uuid.uuid4())
    guardarian_payload['external_partner_link_id'] = external_id

    # Add payout info - this should pre-fill the address
    if payout_address:
        guardarian_payload['payout_info'] = {
            'payout_address': payout_address,
            'skip_choose_payout_address': True,
        }
        # Also add as top-level for some Guardarian versions/widgets just in case
        guardarian_payload['default_payout_address'] = payout_address
        guardarian_payload['skip_payout_address_selection'] = True

    # Add customer info if email is present
    # Add customer info if email is present
    if final_email:
        guardarian_payload['customer'] = {
            'contact_info': {
                'email': final_email,
            }
        }
        # Flat email just in case, as some integrations use it
        guardarian_payload['email'] = final_email

    # Log the payload for debugging
    # Log the payload for debugging
    logger.info(f'Guardarian transaction request for user {user_id}: '
                f'amount={amount}, currency={from_currency}, '
                f'email={bool(user.email)}, address={bool(payout_address)}')
    logger.info(f'Guardarian payload: {json.dumps(guardarian_payload, indent=2)}')

    try:
        resp = requests.post(
            f'{base_url.rstrip("/")}/transaction',
            json=guardarian_payload,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': api_key,
            },
            timeout=20,
        )

    except requests.RequestException as e:
        logger.error('Guardarian proxy network error: %s', e)
        return JsonResponse({'error': 'Servicio no disponible temporalmente. Por favor intenta más tarde.'}, status=502)

    # Log response for debugging
    logger.info(f'Guardarian response status: {resp.status_code}')

    try:
        data = resp.json()
        logger.info(f"Guardarian response body: {json.dumps(data)}")
        if resp.ok:
            g_id = data.get('id')
            if g_id:
                try:
                    from usdc_transactions.models import GuardarianTransaction
                    GuardarianTransaction.objects.create(
                        guardarian_id=str(g_id),
                        external_id=external_id,
                        user=user,
                        from_amount=Decimal(str(guardarian_payload['from_amount'])),
                        from_currency=guardarian_payload['from_currency'],
                        to_currency=guardarian_payload['to_currency'],
                        network=guardarian_payload.get('to_network', 'ALGO'),
                        status=data.get('status', 'waiting'),
                        to_amount_estimated=Decimal(str(data.get('estimated_exchange_amount'))) if data.get('estimated_exchange_amount') else None
                    )
                except Exception as e:
                    logger.error(f"Failed to save GuardarianTransaction: {e}")

            redirect_url = data.get("redirect_url")
            if redirect_url:
                # Append query parameters to prefill data (Backend fallback)
                from urllib.parse import urlencode
                
                params = {}
                if final_email:
                    params['email'] = final_email

                # Address prefill (Attempting as fallback)
                if payout_address:
                    params['payout_address'] = payout_address
                    params['default_payout_address'] = payout_address
                    params['skip_choose_payout_address'] = 'true'
                    params['read_only_payout_address'] = 'true'

                if params:
                    # Parse existing query params from redirect_url to avoid duplication/errors
                    from urllib.parse import urlparse, parse_qs, urlunparse
                    
                    url_parts = list(urlparse(redirect_url))
                    query = dict(parse_qs(url_parts[4]))
                    
                    # Merge our params into existing query
                    query.update(params)
                    
                    # Re-encode
                    url_parts[4] = urlencode(query, doseq=True)
                    redirect_url = urlunparse(url_parts)
                    data['redirect_url'] = redirect_url

            logger.debug(f'Guardarian redirect_url: {data.get("redirect_url", "No URL")}')
    except ValueError:
        data = {'error': 'Respuesta inválida de Guardarian'}

    if not resp.ok:
        # Translate common Guardarian errors to Spanish
        error_msg = data.get('error') or data.get('message') or 'Error de Guardarian'

        # Check if there are detailed errors array
        if 'errors' in data and isinstance(data['errors'], list) and len(data['errors']) > 0:
            error_msg = data['errors'][0].get('reason') or error_msg

        # Pattern matching for dynamic amount messages with regex
        import re

        # Pattern: "USD amount must be higher than 19.185 and lower than 29069"
        amount_range_pattern = r'(\w+)\s+amount\s+must\s+be\s+higher\s+than\s+([\d.,]+)\s+and\s+lower\s+than\s+([\d.,]+)'
        match = re.search(amount_range_pattern, error_msg, re.IGNORECASE)
        if match:
            currency, min_amt, max_amt = match.groups()
            error_msg = f'El monto en {currency} debe ser mayor a {min_amt} y menor a {max_amt}.'
        else:
            # Pattern: "Amount must be at least 20"
            min_pattern = r'amount\s+must\s+be\s+at\s+least\s+([\d.,]+)'
            match = re.search(min_pattern, error_msg, re.IGNORECASE)
            if match:
                min_amt = match.group(1)
                error_msg = f'El monto mínimo es {min_amt}.'
            else:
                # Pattern: "Amount must be less than 30000"
                max_pattern = r'amount\s+must\s+be\s+less\s+than\s+([\d.,]+)'
                match = re.search(max_pattern, error_msg, re.IGNORECASE)
                if match:
                    max_amt = match.group(1)
                    error_msg = f'El monto máximo es {max_amt}.'
                else:
                    # Common error translations
                    error_translations = {
                        'amount is too low': 'El monto es demasiado bajo',
                        'amount is too high': 'El monto es demasiado alto',
                        'invalid amount': 'Monto inválido',
                        'currency not supported': 'Moneda no soportada',
                        'country not supported': 'País no soportado',
                        'invalid email': 'Correo electrónico inválido',
                        'invalid address': 'Dirección inválida',
                        'minimum amount': 'Monto mínimo no alcanzado',
                        'maximum amount': 'Monto máximo excedido',
                    }

                    # Translate if match found
                    lower_error = error_msg.lower()
                    for eng, esp in error_translations.items():
                        if eng in lower_error:
                            error_msg = esp
                            break

        return JsonResponse({'error': error_msg, 'message': error_msg}, status=resp.status_code)

    return JsonResponse(data)


def _guardarian_request(path: str, method: str = 'GET', payload: dict | None = None):
    api_key = getattr(settings, 'GUARDARIAN_API_KEY', None)
    base_url = getattr(settings, 'GUARDARIAN_API_URL', 'https://api-payments.guardarian.com/v1')
    if not api_key:
        return None, JsonResponse({'error': 'Guardarian API key not configured'}, status=503)

    url = f'{base_url.rstrip("/")}{path}'
    try:
        if method.upper() == 'GET':
            resp = requests.get(url, params=payload, headers={'x-api-key': api_key}, timeout=15)
        else:
            resp = requests.request(method, url, json=payload, headers={'x-api-key': api_key}, timeout=15)
    except requests.RequestException as e:
        logger.error('Guardarian proxy network error (%s): %s', path, e)
        return None, JsonResponse({'error': 'Guardarian unavailable'}, status=502)

    try:
        data = resp.json()
    except ValueError:
        data = {'error': 'Invalid response from Guardarian'}

    if not resp.ok:
        return None, JsonResponse(data or {'error': 'Guardarian error'}, status=resp.status_code)

    return data, None


@csrf_exempt
def guardarian_fiat_currencies(request):
    """Expose available fiat currencies (filtered to available ones) without leaking API key."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    data, error_response = _guardarian_request('/currencies/fiat', payload={'available': True})
    if error_response:
        return error_response

    # Temporary: Filter out ARS and CRC for Buy/TopUp flows because Guardarian returns no payment methods
    # This forces the App to fallback to USD for Argentine and Costa Rican users.
    if isinstance(data, list):
        data = [currency for currency in data if currency.get('ticker') not in ['ARS', 'CRC']]

    return JsonResponse(data, safe=False)
