from django.shortcuts import render
from django.utils.translation import get_language_from_request
from django.views.generic import TemplateView
from django.http import HttpResponse, JsonResponse
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

    # Firebase App Check (Warning Mode)
    try:
        from security.integrity_service import app_check_service
        # should_enforce=False means it logs failures but returns success=True
        app_check_service.verify_request_header(request, 'topup_sell', should_enforce=False)
    except Exception as e:
        logger.warning(f"Guardarian App Check error: {e}")

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
