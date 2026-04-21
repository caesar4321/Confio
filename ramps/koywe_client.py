import logging
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache
from ramps.koywe import RAMP_NETWORK_DISPLAY, RAMP_USDC_ALGORAND_NOTE

logger = logging.getLogger(__name__)

_TOKEN_CURRENCIES_CACHE_KEY = 'koywe:token-currencies'
_TOKEN_CURRENCIES_CACHE_TTL = 60 * 15
_RAMP_LIMITS_CACHE_TTL = 60 * 10
_ACCOUNT_PROFILE_SYNC_CACHE_TTL = 60 * 60 * 24

_MINIMUM_AMOUNT_PATTERN = re.compile(
    r'(?:less than|below|under|is below|is less than|does not reach)\s+the\s+(?:minimun|minimum)'
    r'(?:\s+available)?(?:\s+for\s+(?P<currency>[A-Z]{3}))?[\.\s:-]*'
    r'(?P<actual>[\d.,]+)\s*<\s*(?P<minimum>[\d.,]+)',
    re.IGNORECASE,
)

_MAXIMUM_AMOUNT_PATTERN = re.compile(
    r'(?:exceeds|exceed|greater than|more than|bigger than|higher than|above|over|surpasses)'
    r'\s+the\s+(?:maximun|maximum)(?:\s+available)?(?:\s+for\s+(?P<currency>[A-Z]{3}))?[\.\s:-]*'
    r'(?P<actual>[\d.,]+)\s*>\s*(?P<maximum>[\d.,]+)',
    re.IGNORECASE,
)


class KoyweError(Exception):
    pass


class KoyweConfigurationError(KoyweError):
    pass


class KoyweMinimumAmountError(KoyweError):
    def __init__(self, message: str, *, currency: str | None = None, actual: str | None = None, minimum: str | None = None):
        super().__init__(message)
        self.currency = currency
        self.actual = actual
        self.minimum = minimum


class KoyweMaximumAmountError(KoyweError):
    def __init__(self, message: str, *, currency: str | None = None, actual: str | None = None, maximum: str | None = None):
        super().__init__(message)
        self.currency = currency
        self.actual = actual
        self.maximum = maximum


@dataclass
class KoyweOrderResult:
    order_id: str
    amount_in: str
    amount_out: str
    total_change_display: str
    rate_display: str
    payment_method_display: str
    next_step: str
    next_action_url: str | None = None
    payment_provider: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class KoyweOrderStatusResult:
    order_id: str
    status: str
    status_details: str | None = None
    next_action_url: str | None = None
    raw_response: dict[str, Any] | None = None


_COUNTRY_ALPHA3 = {
    'AR': 'ARG',
    'BO': 'BOL',
    'BR': 'BRA',
    'CL': 'CHL',
    'CO': 'COL',
    'MX': 'MEX',
    'PE': 'PER',
    'US': 'USA',
}

_ACCOUNT_TYPE_MAP = {
    'ahorro': 'savings',
    'ahorros': 'savings',
    'savings': 'savings',
    'corriente': 'checking',
    'checking': 'checking',
    'nomina': 'checking',
    'payroll': 'checking',
    'interbancaria': 'interbanking',
    'interbanking': 'interbanking',
}

_BANK_CODE_ALIASES = {
    'BRA': {
        'BANCO_DO_BRASIL': 'BANCO_DO_BRASIL',
        'BANCO DO BRASIL': 'BANCO_DO_BRASIL',
        'BRADESCO': 'BANCO_BRADESCO',
        'BANCO_BRADESCO': 'BANCO_BRADESCO',
        'ITAU': 'BANCO_ITAU',
        'ITAU UNIBANCO': 'BANCO_ITAU',
        'ITAÚ': 'BANCO_ITAU',
        'ITAÚ UNIBANCO': 'BANCO_ITAU',
        'BANCO_ITAU': 'BANCO_ITAU',
        'NUBANK': 'NUBANK',
        'NU PAGAMENTOS': 'NUBANK',
        'NU PAGAMENTOS (NUBANK)': 'NUBANK',
        'BANCO_INTER': 'BANCO_INTER',
        'BANCO INTER': 'BANCO_INTER',
        'INTER': 'BANCO_INTER',
        'SANTANDER': 'SANTANDER',
        'BANCO SANTANDER BRASIL': 'SANTANDER',
        'CAIXA': 'CAIXA_ECONOMICA_FEDERAL',
        'CAIXA ECONOMICA FEDERAL': 'CAIXA_ECONOMICA_FEDERAL',
        'CAIXA ECONÔMICA FEDERAL': 'CAIXA_ECONOMICA_FEDERAL',
        'BANESTES': 'BANESTES',
        'BTG_PACTUAL': 'BANCO_BTG_PACTUAL',
        'BTG PACTUAL': 'BANCO_BTG_PACTUAL',
        'BANCO_BTG_PACTUAL': 'BANCO_BTG_PACTUAL',
        'BANCO BTG PACTUAL': 'BANCO_BTG_PACTUAL',
        'BANCO SAFRA': 'BANCO_SAFRA',
        'SAFRA': 'BANCO_SAFRA',
        'CITIBANK': 'CITIBANK',
        'BANCO ORIGINAL': 'BANCO_ORIGINAL',
        'ORIGINAL': 'BANCO_ORIGINAL',
        'SICREDI': 'BANCO_COOPERATIVO_SICREDI',
        'BANCO COOPERATIVO SICREDI': 'BANCO_COOPERATIVO_SICREDI',
        'MERCANTIL': 'BANCO_MERCANTIL_BRASIL',
        'BANCO MERCANTIL DO BRASIL': 'BANCO_MERCANTIL_BRASIL',
    },
    'CHL': {
        'BCI': 'BCI',
        'BANCO_BCI': 'BCI',
        'BANCO_CHILE': 'CHILE',
        'BANCO DE CHILE': 'CHILE',
        'BANCO_ESTADO': 'ESTADO',
        'BANCOESTADO': 'ESTADO',
        'SANTANDER_CHILE': 'SANTANDER',
        'SCOTIABANK_CHILE': 'SCOTIABANK',
        'BANCO_FALABELLA': 'FALABELLA',
        'BANCO_CONSORCIO': 'CONSORCIO',
        'ITAU_CHILE': 'ITAU',
    },
    'COL': {
        'NEQUI': 'co_nequi',
        'CO_NEQUI': 'co_nequi',
        'BANCOLOMBIA': 'co_bancolombia',
        'CO_BANCOLOMBIA': 'co_bancolombia',
        'DAVIPLATA': 'co_daviplata',
        'CO_DAVIPLATA': 'co_daviplata',
    },
    'PER': {
        'BCP': 'CREDITO',
        'BCP_PERU': 'CREDITO',
        'BCP': 'CREDITO',
        'BANCO DE CREDITO DEL PERU': 'CREDITO',
        'BANCO DE CRÉDITO DEL PERÚ': 'CREDITO',
        'CREDITO': 'CREDITO',
        'BBVA_PERU': 'BBVA',
        'BBVA': 'BBVA',
        'BBVA PERU': 'BBVA',
        'BBVA PERÚ': 'BBVA',
        'SCOTIABANK_PERU': 'SCOTIA',
        'SCOTIABANK': 'SCOTIA',
        'SCOTIABANK PERU': 'SCOTIA',
        'SCOTIABANK PERÚ': 'SCOTIA',
        'INTERBANK_PERU': 'INTERBANK',
        'INTERBANK': 'INTERBANK',
        'BANCO_NACION_PERU': 'NACION',
        'BANCO DE LA NACION': 'NACION',
        'BANCO DE LA NACIÓN': 'NACION',
        'NACION': 'NACION',
        'CITIBANK_PERU': 'CITIBANK',
        'CITIBANK': 'CITIBANK',
        'LIGO': 'LIGO',
    },
}

_DOCUMENT_TYPE_MAP = {
    'AR': 'DNI',
    'BO': 'CI',
    'BR': 'CPF',
    'CL': 'RUT',
    'CO': 'CED_CIU',
    'MX': 'RFC',
    'PE': 'DNI',
}

_COUNTRY_DOCUMENT_TYPE_MAP = {
    'AR': {
        'national_id': 'DNI',
        'dni': 'DNI',
        'cuit': 'CUIT',
    },
    'BO': {
        'national_id': 'CI',
        'ci': 'CI',
        'nit': 'NIT',
    },
    'BR': {
        'national_id': 'CPF',
        'cpf': 'CPF',
        'cnpj': 'CNPJ',
    },
    'CL': {
        'national_id': 'RUT',
        'rut': 'RUT',
    },
    'CO': {
        'national_id': 'CED_CIU',
        'foreign_id': 'CED_EXT',
        'passport': 'PASS',
        'ced_ciu': 'CED_CIU',
        'ced_ext': 'CED_EXT',
        'ti': 'TI',
        'nuip': 'NUIP',
        'te': 'TE',
        'ppt': 'PPT',
        'pass': 'PASS',
        'pep': 'PEP',
        'rc': 'RC',
        'nit': 'NIT',
    },
    'MX': {
        'national_id': 'RFC',
        'rfc': 'RFC',
        'curp': 'CURP',
    },
    'PE': {
        'national_id': 'DNI',
        'dni': 'DNI',
        'ruc': 'RUC',
        'ce': 'CE',
    },
}


def _normalize_koywe_document_number(*, country_code: str, document_type: str | None, document_number: str | None) -> str:
    normalized_country = (country_code or '').strip().upper()
    normalized_type = str(document_type or '').strip().upper()
    raw_number = str(document_number or '').strip().upper()
    if not raw_number:
        return ''

    if normalized_country == 'CL' and normalized_type == 'RUT':
        cleaned = re.sub(r'[^A-Z0-9]', '', raw_number)
        if cleaned.startswith('RUT'):
            cleaned = cleaned[3:]
        if len(cleaned) >= 2:
            return f'{cleaned[:-1]}-{cleaned[-1]}'
        return cleaned

    return raw_number


def _normalize_account_type(value: str | None) -> str | None:
    raw_value = str(value or '').strip()
    if not raw_value:
        return None
    normalized_key = unicodedata.normalize('NFKD', raw_value)
    normalized_key = ''.join(ch for ch in normalized_key if not unicodedata.combining(ch))
    normalized_key = normalized_key.lower().replace('-', '_').replace(' ', '_')
    normalized_key = normalized_key.replace('cuenta_', '').replace('de_', '')
    return _ACCOUNT_TYPE_MAP.get(normalized_key, raw_value)


class KoyweClient:
    def __init__(self):
        self.base_url = getattr(settings, 'KOYWE_API_URL', 'https://api.koywe.com').rstrip('/')
        self.client_id = getattr(settings, 'KOYWE_CLIENT_ID', '')
        self.secret = getattr(settings, 'KOYWE_SECRET', '')
        self.crypto_symbol = getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Algorand')
        self.timeout = getattr(settings, 'KOYWE_TIMEOUT_SECONDS', 20)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; ConfioApp/1.0)',
        })

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.secret)

    def ensure_configured(self):
        if not self.is_configured:
            raise KoyweConfigurationError('Koywe credentials are not configured')

    def list_token_currencies(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        if not force_refresh:
            cached = cache.get(_TOKEN_CURRENCIES_CACHE_KEY)
            if cached:
                return cached

        data = self._request('GET', '/rest/token-currencies', auth=False)
        if not isinstance(data, list):
            data = data.get('items') or data.get('results') or []
        cache.set(_TOKEN_CURRENCIES_CACHE_KEY, data, timeout=_TOKEN_CURRENCIES_CACHE_TTL)
        return data

    def get_dynamic_ramp_limits(self, *, fiat_symbol: str, crypto_symbol: str | None = None) -> dict[str, Decimal]:
        normalized_fiat = (fiat_symbol or '').strip().upper()
        normalized_crypto = (crypto_symbol or self.crypto_symbol or '').strip()
        cache_key = f'koywe:ramp-limits:{normalized_fiat}:{normalized_crypto.replace(" ", "_")}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        pair_limits = self._get_pair_limits(
            fiat_symbol=normalized_fiat,
            crypto_symbol=normalized_crypto,
        )
        if not pair_limits:
            raise KoyweError(f'Koywe pair limits not found for {normalized_fiat} / {normalized_crypto}')

        fiat_min = Decimal(str(pair_limits['min']))
        fiat_max = Decimal(str(pair_limits['max']))
        off_ramp_min = self._estimate_crypto_amount_for_fiat_output(
            crypto_symbol=normalized_crypto,
            fiat_symbol=normalized_fiat,
            target_amount=fiat_min,
        )
        off_ramp_max = self._estimate_crypto_amount_for_fiat_output(
            crypto_symbol=normalized_crypto,
            fiat_symbol=normalized_fiat,
            target_amount=fiat_max,
        )
        result = {
            'on_ramp_min_amount': fiat_min,
            'on_ramp_max_amount': fiat_max,
            'off_ramp_min_amount': off_ramp_min,
            'off_ramp_max_amount': off_ramp_max,
        }
        cache.set(cache_key, result, timeout=_RAMP_LIMITS_CACHE_TTL)
        return result

    def get_public_ramp_limits(self, *, fiat_symbol: str, crypto_symbol: str | None = None) -> dict[str, Decimal]:
        normalized_fiat = (fiat_symbol or '').strip().upper()
        normalized_crypto = (crypto_symbol or self.crypto_symbol or '').strip()
        cache_key = f'koywe:public-ramp-limits:{normalized_fiat}:{normalized_crypto.replace(" ", "_")}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        pair_limits = self._get_pair_limits(
            fiat_symbol=normalized_fiat,
            crypto_symbol=normalized_crypto,
        )
        if not pair_limits:
            raise KoyweError(f'Koywe pair limits not found for {normalized_fiat} / {normalized_crypto}')

        result = {
            'on_ramp_min_amount': Decimal(str(pair_limits['min'])),
            'on_ramp_max_amount': Decimal(str(pair_limits['max'])),
        }
        cache.set(cache_key, result, timeout=_RAMP_LIMITS_CACHE_TTL)
        return result

    def _token_cache_key(self, email: str | None) -> str:
        return f'koywe:token:{email or "default"}'

    def authenticate(self, *, email: str | None = None) -> str:
        self.ensure_configured()
        cache_key = self._token_cache_key(email)
        cached = cache.get(cache_key)
        if cached:
            return cached

        normalized_email = str(email or '').strip() or None
        payload: dict[str, Any] = {
            'clientId': self.client_id,
            'secret': self.secret,
        }
        if normalized_email:
            payload['email'] = normalized_email

        response = self.session.post(
            f'{self.base_url}/rest/auth',
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=self.timeout,
        )
        data = self._parse_response(response, 'Koywe auth failed')
        token = data.get('token') or data.get('accessToken') or data.get('access_token')
        if not token:
            raise KoyweError('Koywe auth response did not include a token')
        cache.set(cache_key, token, timeout=60 * 45)
        return token

    def _request(self, method: str, path: str, *, email: str | None = None, params: dict[str, Any] | None = None, json_payload: dict[str, Any] | None = None, auth: bool = True) -> dict[str, Any]:
        headers = {'Content-Type': 'application/json'}
        normalized_email = str(email or '').strip() or None
        if auth:
            headers['Authorization'] = f'Bearer {self.authenticate(email=normalized_email)}'
        try:
            response = self.session.request(
                method,
                f'{self.base_url}{path}',
                params=params,
                json=json_payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise KoyweError(f'Koywe request failed: {method} {path}: {exc}') from exc
        return self._parse_response(response, f'Koywe request failed: {method} {path}')

    def _parse_response(self, response: requests.Response, default_message: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {'message': response.text}

        if response.ok:
            return data

        message = data.get('message') or data.get('error') or default_message
        text = str(message)
        match = _MINIMUM_AMOUNT_PATTERN.search(text)
        if match:
            raise KoyweMinimumAmountError(
                message,
                currency=match.group('currency'),
                actual=match.group('actual'),
                minimum=match.group('minimum'),
            )
        match = _MAXIMUM_AMOUNT_PATTERN.search(text)
        if match:
            raise KoyweMaximumAmountError(
                message,
                currency=match.group('currency'),
                actual=match.group('actual'),
                maximum=match.group('maximum'),
            )
        raise KoyweError(message)

    def list_payment_providers(self, *, fiat_symbol: str, email: str | None = None) -> list[dict[str, Any]]:
        data = self._request('GET', '/rest/payment-providers', email=email, params={'symbol': fiat_symbol})
        if isinstance(data, list):
            return data
        return data.get('items') or data.get('paymentProviders') or data.get('results') or []

    def create_preview_quote(self, *, symbol_in: str, symbol_out: str, amount: Decimal) -> dict[str, Any]:
        payload = {
            'symbolIn': symbol_in,
            'symbolOut': symbol_out,
            'amountIn': float(amount),
            'executable': False,
        }
        return self._request('POST', '/rest/quotes', auth=False, json_payload=payload)

    def resolve_payment_provider(self, *, fiat_symbol: str, payment_method_code: str, email: str | None = None) -> tuple[str, str, dict[str, Any] | None]:
        providers = self.list_payment_providers(fiat_symbol=fiat_symbol, email=email)
        normalized = (payment_method_code or '').strip().upper()
        for provider in providers:
            provider_code = str(provider.get('code') or provider.get('symbol') or provider.get('name') or '').strip().upper()
            provider_id = str(provider.get('_id') or provider.get('id') or provider.get('paymentMethodId') or provider_code)
            display = provider.get('displayName') or provider.get('name') or provider_code
            if provider_code == normalized or provider_id.upper() == normalized:
                return provider_id, display, provider
        return normalized, payment_method_code, None

    def create_quote(self, *, direction: str, amount: Decimal, fiat_symbol: str, payment_method_id: str | None = None, email: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'symbolIn': fiat_symbol if direction == 'ON_RAMP' else self.crypto_symbol,
            'symbolOut': self.crypto_symbol if direction == 'ON_RAMP' else fiat_symbol,
            'amountIn': float(amount),
            'executable': True,
        }
        if direction == 'ON_RAMP' and payment_method_id:
            payload['paymentMethodId'] = payment_method_id
        return self._request('POST', '/rest/quotes', email=email, json_payload=payload)

    def get_ramp_quote(
        self,
        *,
        direction: str,
        amount: Decimal,
        fiat_symbol: str,
        payment_method_code: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        normalized_direction = direction.upper()
        payment_method_id = None
        if normalized_direction == 'ON_RAMP' and payment_method_code:
            payment_method_id, _, _ = self.resolve_payment_provider(
                fiat_symbol=fiat_symbol,
                payment_method_code=payment_method_code,
                email=email,
            )
        quote = self.create_quote(
            direction=normalized_direction,
            amount=amount,
            fiat_symbol=fiat_symbol,
            payment_method_id=payment_method_id,
            email=email,
        )
        amount_in = Decimal(str(quote.get('amountIn') or amount))
        amount_out = Decimal(str(quote.get('amountOut') or 0))
        exchange_rate = Decimal(str(quote.get('exchangeRate') or 0))
        koywe_fee = Decimal(str(quote.get('koyweFee') or 0))
        network_fee = Decimal(str(quote.get('networkFee') or 0))
        fee_currency = fiat_symbol if normalized_direction == 'ON_RAMP' else self.crypto_symbol
        network_fee_currency = fiat_symbol if normalized_direction == 'ON_RAMP' else self.crypto_symbol
        total_change_display = (
            f'{amount_in.normalize()} {fiat_symbol} -> {amount_out.normalize()} {self.crypto_symbol}'
            if normalized_direction == 'ON_RAMP'
            else f'{amount_in.normalize()} {self.crypto_symbol} -> {amount_out.normalize()} {fiat_symbol}'
        )
        rate_display = (
            f'1 {self.crypto_symbol} ~= {exchange_rate.normalize()} {fiat_symbol}'
            if exchange_rate
            else ''
        )
        return {
            'direction': normalized_direction,
            'country_code': '',
            'fiat_currency': fiat_symbol,
            'amount_in': amount_in,
            'amount_out': amount_out,
            'exchange_rate': exchange_rate,
            'fee_amount': koywe_fee,
            'fee_currency': fee_currency,
            'network_fee_amount': network_fee,
            'network_fee_currency': network_fee_currency,
            'rate_display': rate_display,
            'total_change_display': total_change_display,
            'token_symbol': self.crypto_symbol,
            'network_symbol': getattr(settings, 'KOYWE_CRYPTO_SYMBOL', self.crypto_symbol),
            'network_display': RAMP_NETWORK_DISPLAY,
            'asset_note': RAMP_USDC_ALGORAND_NOTE,
        }

    def create_order(self, *, quote_id: str, email: str | None = None, destination_address: str | None = None, external_id: str | None = None, document_number: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {'quoteId': quote_id}
        if email:
            payload['email'] = email
        if document_number:
            payload['documentNumber'] = document_number
        if destination_address:
            payload['destinationAddress'] = destination_address
        if external_id:
            payload['externalId'] = external_id
        return self._request('POST', '/rest/orders', email=email, json_payload=payload)

    def get_order(self, *, order_id: str, email: str | None = None) -> dict[str, Any]:
        return self._request('GET', f'/rest/orders/{order_id}', email=email)

    def create_bank_account(self, *, bank_info: Any, email: str | None, country_code: str, fiat_symbol: str, contact_profile: dict[str, Any] | None = None, previous_emails: list[str] | None = None) -> dict[str, Any]:
        alpha3 = _COUNTRY_ALPHA3.get((country_code or '').upper(), (country_code or '').upper())
        normalized_contact_profile = self._normalize_contact_profile(
            contact_profile=contact_profile,
            country_code=country_code,
        )
        resolved_email = self.ensure_account_profile(
            email=email,
            country_code=country_code,
            contact_profile=normalized_contact_profile,
            previous_emails=previous_emails,
        )
        if resolved_email:
            email = resolved_email
        provider_metadata = getattr(bank_info, 'provider_metadata', None) or {}
        payment_method = getattr(bank_info, 'payment_method', None)
        payment_method_code = (
            getattr(payment_method, 'name', None)
            or getattr(payment_method, 'display_name', None)
            or ''
        ).strip().upper().replace('_', '-')
        account_number = (
            provider_metadata.get('pixKey')
            or provider_metadata.get('cci')
            or bank_info.account_number
            or bank_info.phone_number
            or bank_info.email
            or bank_info.username
        )
        payload: dict[str, Any] = {
            'countryCode': alpha3,
            'currencySymbol': fiat_symbol,
        }
        normalized_email = str(email or normalized_contact_profile.get('email') or '').strip()
        document_number = str(normalized_contact_profile.get('documentNumber') or '').strip()
        if normalized_email:
            payload['email'] = normalized_email
        if document_number:
            payload['documentNumber'] = document_number
        if account_number is not None:
            payload['accountNumber'] = str(account_number)
        if alpha3 == 'ARG' and payment_method_code == 'WIREAR':
            normalized_account_number = ''.join(ch for ch in str(payload.get('accountNumber') or '') if ch.isdigit())
            if len(normalized_account_number) != 22:
                raise KoyweError('El CBU o CVU debe tener exactamente 22 dígitos.')
            payload['accountNumber'] = normalized_account_number
        if provider_metadata.get('bankCode'):
            raw_bank_code = str(provider_metadata['bankCode']).strip()
            resolved_bank_code = self._resolve_bank_code(
                country_code=alpha3,
                bank_name=raw_bank_code,
            ) or raw_bank_code
            if not (alpha3 == 'BRA' and raw_bank_code.upper() in {'PIX_QR', 'SULPAYMENTS'} and resolved_bank_code == raw_bank_code):
                payload['bankCode'] = resolved_bank_code
        elif provider_metadata.get('bankName'):
            resolved_bank_code = self._resolve_bank_code(
                country_code=alpha3,
                bank_name=str(provider_metadata['bankName']),
            )
            if resolved_bank_code:
                payload['bankCode'] = resolved_bank_code
        elif getattr(bank_info, 'bank', None) and getattr(bank_info.bank, 'code', None):
            raw_bank_code = str(bank_info.bank.code).strip().upper()
            resolved_bank_code = self._resolve_bank_code(
                country_code=alpha3,
                bank_name=raw_bank_code,
            ) or raw_bank_code
            if not (alpha3 == 'BRA' and raw_bank_code in {'PIX_QR', 'SULPAYMENTS'} and resolved_bank_code == raw_bank_code):
                payload['bankCode'] = resolved_bank_code
        elif alpha3 == 'COL' and payment_method_code == 'NEQUI':
            payload['bankCode'] = 'co_nequi'
        elif alpha3 == 'COL' and payment_method_code == 'BANCOLOMBIA':
            payload['bankCode'] = 'co_bancolombia'
        elif alpha3 == 'COL' and not payload.get('bankCode'):
            raise KoyweError('"bankCode" is required for COP payouts — select a bank')
        elif alpha3 == 'BRA' and not payload.get('bankCode'):
            raise KoyweError('"bankCode" is required for BRL payouts — select a supported bank from Koywe bank-info/BRA')
        elif alpha3 == 'MEX' and payment_method_code == 'STP':
            payload['bankCode'] = 'STP'
        elif alpha3 == 'PER' and payment_method_code == 'QRI-PE':
            payload['bankCode'] = 'LIGO'
        elif alpha3 == 'PER' and payment_method_code == 'RECAUDO-PE':
            payload['bankCode'] = 'CREDITO'
        elif alpha3 == 'BOL' and payment_method_code in {'QRI-BO', 'QRI_BO'}:
            payload['bankCode'] = 'SIP_QR'
        normalized_account_type = _normalize_account_type(getattr(bank_info, 'account_type', None))
        if normalized_account_type:
            payload['accountType'] = normalized_account_type
        elif alpha3 == 'COL' and payment_method_code in {'NEQUI', 'BANCOLOMBIA', 'WIRECO'}:
            # Koywe's Colombia payout schema requires accountType even for wallet-like rails.
            # Nequi does not expose this in the user UX, so default to savings server-side.
            payload['accountType'] = 'savings'
        elif alpha3 == 'PER' and payment_method_code == 'QRI-PE':
            payload['accountType'] = 'interbanking'
        return self._request('POST', '/rest/bank-accounts', email=email, json_payload=payload)

    def _resolve_bank_code(self, *, country_code: str, bank_name: str) -> str | None:
        normalized_country = (country_code or '').strip().upper()
        normalized_name = (bank_name or '').strip().upper().replace('-', '_')
        if not normalized_name:
            return None
        return _BANK_CODE_ALIASES.get(normalized_country, {}).get(normalized_name)

    def create_ramp_order(self, *, direction: str, amount: Decimal, fiat_symbol: str, payment_method_code: str, email: str | None, wallet_address: str | None, country_code: str, bank_info: Any = None, external_id: str | None = None, contact_profile: dict[str, Any] | None = None, previous_emails: list[str] | None = None) -> KoyweOrderResult:
        normalized_direction = direction.upper()
        if normalized_direction == 'ON_RAMP' and not wallet_address:
            raise KoyweError('The active account does not have a destination wallet address configured')
        normalized_contact_profile = self._normalize_contact_profile(
            contact_profile=contact_profile,
            country_code=country_code,
        )
        resolved_email = self.ensure_account_profile(
            email=email,
            country_code=country_code,
            contact_profile=normalized_contact_profile,
            previous_emails=previous_emails,
        )
        if resolved_email:
            email = resolved_email
        payment_method_id, payment_method_display, payment_provider = self.resolve_payment_provider(
            fiat_symbol=fiat_symbol,
            payment_method_code=payment_method_code,
            email=email,
        )
        quote = self.create_quote(
            direction=normalized_direction,
            amount=amount,
            fiat_symbol=fiat_symbol,
            payment_method_id=payment_method_id,
            email=email,
        )
        quote_id = str(quote.get('quoteId') or quote.get('_id') or quote.get('id') or '')
        if not quote_id:
            raise KoyweError('Koywe quote response did not include quoteId')

        destination_address = wallet_address if normalized_direction == 'ON_RAMP' else None
        if normalized_direction == 'OFF_RAMP':
            if not bank_info:
                raise KoyweError('A saved payout method is required for off-ramp orders')
            bank_account = self.create_bank_account(
                bank_info=bank_info,
                email=email,
                country_code=country_code,
                fiat_symbol=fiat_symbol,
                contact_profile=normalized_contact_profile,
                previous_emails=previous_emails,
            )
            created_bank_account_id = str(bank_account.get('_id') or bank_account.get('id') or bank_account.get('bankAccountId') or '')
            if not created_bank_account_id:
                raise KoyweError('Koywe bank account response did not include an id')
            destination_address = created_bank_account_id

        order = self.create_order(
            quote_id=quote_id,
            email=email,
            destination_address=destination_address,
            external_id=external_id,
            document_number=str(normalized_contact_profile.get('documentNumber') or '').strip() or None,
        )
        enriched_order = self._merge_payment_provider_details(
            order=order,
            payment_provider=payment_provider,
        )

        order_id = str(enriched_order.get('_id') or enriched_order.get('id') or enriched_order.get('orderId') or quote_id)
        next_action_url = self._extract_action_url(enriched_order)
        next_step = self._determine_next_step(direction=normalized_direction, next_action_url=next_action_url, order=enriched_order)
        return KoyweOrderResult(
            order_id=order_id,
            amount_in=str(quote.get('amountIn') or amount),
            amount_out=str(quote.get('amountOut') or ''),
            total_change_display=str(quote.get('totalChangeDisplay') or ''),
            rate_display=str(quote.get('rateDisplay') or ''),
            payment_method_display=payment_method_display,
            next_step=next_step,
            next_action_url=next_action_url,
            payment_provider=payment_provider,
            raw_response=enriched_order,
        )

    def get_ramp_order_status(self, *, order_id: str, email: str | None = None) -> KoyweOrderStatusResult:
        order = self.get_order(order_id=order_id, email=email)
        resolved_order_id = str(order.get('orderId') or order.get('_id') or order.get('id') or order_id)
        status = str(order.get('status') or '').strip().upper()
        status_details = str(order.get('statusDetails') or '').strip() or None
        next_action_url = self._extract_action_url(order)
        return KoyweOrderStatusResult(
            order_id=resolved_order_id,
            status=status,
            status_details=status_details,
            next_action_url=next_action_url,
            raw_response=order,
        )

    def add_order_tx_hash(self, *, order_id: str, tx_hash: str, email: str | None = None) -> dict[str, Any]:
        """
        Associate a transaction hash with an order using POST /rest/orders/{orderId}/txHash.
        Required by Koywe for Algorand off-ramp orders to confirm funding.
        """
        payload = {'txHash': tx_hash}
        return self._request('POST', f'/rest/orders/{order_id}/txHash', email=email, json_payload=payload)

    def _normalize_contact_profile(self, *, contact_profile: dict[str, Any] | None, country_code: str) -> dict[str, Any]:
        if not contact_profile:
            return {}
        normalized = dict(contact_profile)
        document_type = normalized.get('documentType')
        document_number = normalized.get('documentNumber')
        if document_number:
            resolved_document_type = self._resolve_document_type(
                country_code=country_code,
                document_type=document_type,
            )
            normalized['documentType'] = resolved_document_type
            normalized['documentNumber'] = _normalize_koywe_document_number(
                country_code=country_code,
                document_type=resolved_document_type,
                document_number=document_number,
            )
        return {key: value for key, value in normalized.items() if value}

    def _resolve_document_type(self, *, country_code: str, document_type: str | None) -> str:
        normalized_country = (country_code or '').strip().upper()
        normalized_document_type = str(document_type or '').strip().lower()
        country_map = _COUNTRY_DOCUMENT_TYPE_MAP.get(normalized_country, {})
        resolved = country_map.get(normalized_document_type)
        if resolved:
            return resolved

        if normalized_document_type == 'drivers_license':
            raise KoyweError(f'Document type "{normalized_document_type}" is not supported for Koywe delegated KYC in country {normalized_country}')
        if normalized_document_type == 'passport':
            raise KoyweError(f'Document type "{normalized_document_type}" is not supported for Koywe delegated KYC in country {normalized_country}')
        if not normalized_document_type:
            default_document_type = _DOCUMENT_TYPE_MAP.get(normalized_country)
            if default_document_type:
                return default_document_type

        raise KoyweError(f'Document type "{document_type or "unknown"}" is not mapped for Koywe delegated KYC in country {normalized_country}')

    def ensure_account_profile(self, *, email: str | None, country_code: str, contact_profile: dict[str, Any] | None = None, previous_emails: list[str] | None = None) -> str | None:
        """Sync the Koywe account profile, returning the resolved email.

        Returns the email that owns the account at Koywe. This may differ from
        the requested *email* when the document already exists under a previous
        email and Koywe does not allow email migration.
        """
        normalized_contact = self._normalize_contact_profile(
            contact_profile=contact_profile,
            country_code=country_code,
        )
        if not normalized_contact:
            return None

        normalized_email = str(email or normalized_contact.get('email') or '').strip().lower()
        document_number = str(normalized_contact.get('documentNumber') or '').strip()
        if not normalized_email or not document_number:
            return None

        cache_key = f'koywe:account-profile:{normalized_email}:{country_code.upper()}:{document_number}'
        if cache.get(cache_key):
            return None

        payload = self._build_account_profile_payload(
            email=normalized_email,
            country_code=country_code,
            contact_profile=normalized_contact,
        )
        if not payload:
            return None

        try:
            self._request('POST', '/rest/accounts', email=normalized_email, json_payload=payload)
        except KoyweError as exc:
            if self._is_existing_account_error(str(exc)):
                resolved = self._ensure_existing_account_profile(
                    email=normalized_email,
                    country_code=country_code,
                    payload=payload,
                    previous_emails=previous_emails,
                )
                cache.set(cache_key, True, timeout=_ACCOUNT_PROFILE_SYNC_CACHE_TTL)
                return resolved
            raise

        cache.set(cache_key, True, timeout=_ACCOUNT_PROFILE_SYNC_CACHE_TTL)
        return None

    def _ensure_existing_account_profile(self, *, email: str, country_code: str, payload: dict[str, Any], previous_emails: list[str] | None = None) -> str | None:
        """Update an existing Koywe account profile.

        Returns ``None`` when the account already belongs to *email*.  When the
        account is found under a previous email, it is migrated to *email* via
        Koywe's ``updateEmail`` field, and ``None`` is returned (the caller
        should continue using *email*).
        """
        try:
            existing = self.get_account(email=email)
        except KoyweError:
            existing = {}

        # If account not found by current email, try previous emails.
        # The account may exist under an old email with the same document number.
        if not existing and previous_emails:
            for prev_email in previous_emails:
                prev_email = str(prev_email or '').strip().lower()
                if not prev_email or prev_email == email:
                    continue
                try:
                    existing = self.get_account(email=prev_email)
                    if existing:
                        migration_payload = self._build_migration_payload(
                            existing=existing,
                            target_payload=payload,
                            current_email=prev_email,
                            new_email=email,
                        )
                        self.update_account(email=prev_email, payload=migration_payload)
                        return None
                except KoyweError:
                    continue

        if self._account_profile_satisfies_payload(existing, payload):
            return None

        update_payload = self._build_migration_payload(
            existing=existing,
            target_payload=payload,
            current_email=email,
            new_email=None,
        )
        self.update_account(email=email, payload=update_payload)
        return None

    def _build_migration_payload(self, *, existing: dict[str, Any], target_payload: dict[str, Any], current_email: str, new_email: str | None) -> dict[str, Any]:
        """Build a PUT payload with updateEmail/updateDocumentNumber/updateDocumentType as needed."""
        result = {**target_payload, 'email': current_email}

        if new_email and new_email != current_email:
            result['updateEmail'] = new_email

        existing_doc = existing.get('document') or {}
        target_doc = target_payload.get('document') or {}

        existing_doc_number = str(existing_doc.get('documentNumber') or '').strip()
        target_doc_number = str(target_doc.get('documentNumber') or '').strip()
        if target_doc_number and target_doc_number != existing_doc_number:
            result['updateDocumentNumber'] = target_doc_number

        existing_doc_type = str(existing_doc.get('documentType') or '').strip().upper()
        target_doc_type = str(target_doc.get('documentType') or '').strip().upper()
        if target_doc_type and target_doc_type != existing_doc_type:
            result['updateDocumentType'] = target_doc_type

        return result

    def get_account(self, *, email: str) -> dict[str, Any]:
        normalized_email = str(email or '').strip().lower()
        if not normalized_email:
            raise KoyweError('Koywe account email is required')
        encoded_email = quote(normalized_email, safe='')
        return self._request('GET', f'/rest/accounts/{encoded_email}', email=normalized_email)

    def update_account(self, *, email: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_email = str(email or '').strip().lower()
        if not normalized_email:
            raise KoyweError('Koywe account email is required')
        payload.setdefault('email', normalized_email)
        return self._request('PUT', '/rest/accounts', email=normalized_email, json_payload=payload)

    def _build_account_profile_payload(self, *, email: str, country_code: str, contact_profile: dict[str, Any]) -> dict[str, Any] | None:
        alpha3 = _COUNTRY_ALPHA3.get((country_code or '').upper(), (country_code or '').upper())
        first_name = str(contact_profile.get('firstName') or '').strip()
        last_name = str(contact_profile.get('lastName') or '').strip()
        document_number = str(contact_profile.get('documentNumber') or '').strip()
        document_type = str(contact_profile.get('documentType') or '').strip()
        phone = str(contact_profile.get('phone') or '').strip()
        if not (first_name and last_name and document_number and document_type and alpha3):
            return None

        address_street = str(contact_profile.get('addressStreet') or contact_profile.get('address') or '').strip()
        address_city = str(contact_profile.get('addressCity') or '').strip()
        address_state = str(contact_profile.get('addressState') or '').strip()
        address_country = str(contact_profile.get('addressCountry') or '').strip()
        address_zip_code = str(contact_profile.get('addressZipCode') or '').strip()
        dob = contact_profile.get('dob')
        dob_value = str(dob).strip() if dob else '1900-01-01'

        payload: dict[str, Any] = {
            'document': {
                'documentNumber': document_number,
                'documentType': document_type,
                'country': alpha3,
                'isCompany': False,
            },
            'personalInfo': {
                'names': first_name,
                'firstLastname': last_name,
                'activity': str(contact_profile.get('activity') or 'OTHER'),
                'phoneNumber': phone or '0000000000',
                'dob': dob_value,
            },
        }
        address_fields = {
            'addressStreet': address_street,
            'addressCountry': address_country,
            'addressZipCode': address_zip_code,
            'addressCity': address_city,
            'addressState': address_state,
        }
        missing_address_fields = [key for key, value in address_fields.items() if not value]
        if missing_address_fields:
            missing_display = ', '.join(missing_address_fields)
            raise KoyweError(
                f'Koywe delegated KYC requires address fields before syncing account profile: {missing_display}'
            )
        payload['address'] = address_fields
        return payload

    def _account_profile_satisfies_payload(self, existing: dict[str, Any], payload: dict[str, Any]) -> bool:
        if not isinstance(existing, dict):
            return False

        existing_document = existing.get('document') or {}
        existing_personal_info = existing.get('personalInfo') or {}
        existing_address = existing.get('address') or {}

        wanted_document = payload.get('document') or {}
        wanted_personal_info = payload.get('personalInfo') or {}
        wanted_address = payload.get('address') or {}

        document_matches = (
            str(existing_document.get('documentNumber') or '').strip() == str(wanted_document.get('documentNumber') or '').strip()
            and str(existing_document.get('documentType') or '').strip().upper() == str(wanted_document.get('documentType') or '').strip().upper()
            and str(existing_document.get('country') or '').strip().upper() == str(wanted_document.get('country') or '').strip().upper()
        )
        personal_present = all(
            str(existing_personal_info.get(field) or '').strip()
            for field in ('names', 'firstLastname', 'phoneNumber', 'dob')
        )
        address_present = all(
            str(existing_address.get(field) or '').strip()
            for field in ('addressStreet', 'addressCountry', 'addressZipCode', 'addressCity', 'addressState')
        )
        return document_matches and personal_present and address_present

    def _is_existing_account_error(self, message: str) -> bool:
        normalized = str(message or '').strip().lower()
        return any(fragment in normalized for fragment in (
            'already exists',
            'already registered',
            'account already',
            'profile already',
            'document already exists',
            'duplicate',
        ))

    def _extract_action_url(self, payload: Any) -> str | None:
        if isinstance(payload, str) and payload.startswith('http'):
            return payload
        if isinstance(payload, dict):
            action_keys = (
                'providedAction',
                'redirectUrl',
                'redirect_url',
                'actionUrl',
                'actionURL',
                'deeplink',
                'url',
            )
            for key in (
                *action_keys,
            ):
                value = payload.get(key)
                if isinstance(value, str) and value.startswith('http'):
                    return value
                if isinstance(value, (dict, list)):
                    found = self._extract_action_url(value)
                    if found:
                        return found
        elif isinstance(payload, list):
            for item in payload:
                found = self._extract_action_url(item)
                if found:
                    return found
        return None

    def _merge_payment_provider_details(self, *, order: dict[str, Any] | None, payment_provider: dict[str, Any] | None) -> dict[str, Any]:
        enriched = dict(order or {})
        provider = dict(payment_provider or {})
        if not provider:
            return enriched

        enriched.setdefault('paymentProvider', provider)

        provider_details = provider.get('details')
        if isinstance(provider_details, str) and provider_details.strip() and not str(enriched.get('providedAddress') or '').strip():
            enriched['providedAddress'] = provider_details.strip()

        provider_image = provider.get('image')
        if isinstance(provider_image, str) and provider_image.strip() and not str(enriched.get('providedAction') or '').strip():
            enriched['providedAction'] = provider_image.strip()

        provider_display = provider.get('displayName') or provider.get('name')
        if provider_display and not enriched.get('paymentMethodDisplay'):
            enriched['paymentMethodDisplay'] = provider_display

        provider_id = provider.get('_id') or provider.get('id') or provider.get('paymentMethodId')
        if provider_id and not enriched.get('paymentMethodId'):
            enriched['paymentMethodId'] = provider_id

        return enriched

    def _determine_next_step(self, *, direction: str, next_action_url: str | None, order: dict | None = None) -> str:
        if direction == 'OFF_RAMP':
            return 'WAIT_FOR_USDC_TRANSFER'
        if next_action_url:
            return 'OPEN_PROVIDER_FLOW'
        return 'SHOW_PAYMENT_INSTRUCTIONS'

    def _split_name(self, full_name: str) -> tuple[str, str]:
        parts = [part for part in (full_name or '').strip().split() if part]
        if not parts:
            return 'Usuario', 'Confio'
        if len(parts) == 1:
            return parts[0], parts[0]
        return parts[0], ' '.join(parts[1:])

    def _get_pair_limits(self, *, fiat_symbol: str, crypto_symbol: str) -> dict[str, Any] | None:
        normalized_fiat = (fiat_symbol or '').strip().upper()
        candidates = self._crypto_symbol_candidates(crypto_symbol)
        token_entries = self.list_token_currencies()

        for candidate in candidates:
            token = next((entry for entry in token_entries if str(entry.get('symbol') or '').strip() == candidate), None)
            if not token:
                continue
            currencies = token.get('currencies') or []
            match = next((currency for currency in currencies if str(currency.get('symbol') or '').strip().upper() == normalized_fiat), None)
            if match:
                limits = match.get('limits') or {}
                min_amount = limits.get('min', match.get('minimum'))
                max_amount = limits.get('max', match.get('maximum'))
                if min_amount is not None and max_amount is not None:
                    return {'min': min_amount, 'max': max_amount}
        return None

    def _crypto_symbol_candidates(self, crypto_symbol: str) -> list[str]:
        normalized = (crypto_symbol or '').strip()
        if not normalized:
            return ['USDC']
        candidates = [normalized]
        if normalized.startswith('USDC') and 'USDC' not in candidates:
            candidates.append('USDC')
        if normalized.startswith('USDT') and 'USDT' not in candidates:
            candidates.append('USDT')
        return candidates

    def _estimate_crypto_amount_for_fiat_output(self, *, crypto_symbol: str, fiat_symbol: str, target_amount: Decimal) -> Decimal:
        if target_amount <= 0:
            return Decimal('0')

        sample_quote = self.create_preview_quote(
            symbol_in=crypto_symbol,
            symbol_out=fiat_symbol,
            amount=Decimal('1000'),
        )
        sample_amount_in = Decimal(str(sample_quote.get('amountIn') or '0'))
        sample_amount_out = Decimal(str(sample_quote.get('amountOut') or '0'))
        if sample_amount_in <= 0 or sample_amount_out <= 0:
            raise KoyweError(f'Unable to estimate Koywe off-ramp limits for {fiat_symbol}')

        effective_rate = sample_amount_out / sample_amount_in
        high = (target_amount / effective_rate) * Decimal('1.25')
        high = max(high, Decimal('1'))
        low = Decimal('0')

        for _ in range(6):
            quote = self._safe_preview_quote(symbol_in=crypto_symbol, symbol_out=fiat_symbol, amount=high)
            if quote and Decimal(str(quote.get('amountOut') or '0')) >= target_amount:
                break
            high *= Decimal('2')

        for _ in range(16):
            midpoint = (low + high) / Decimal('2')
            quote = self._safe_preview_quote(symbol_in=crypto_symbol, symbol_out=fiat_symbol, amount=midpoint)
            amount_out = Decimal(str(quote.get('amountOut') or '0')) if quote else Decimal('0')
            if amount_out >= target_amount:
                high = midpoint
            else:
                low = midpoint

        return high.quantize(Decimal('0.01'))

    def register_webhook(self, *, url: str, secret: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {'url': url}
        if secret:
            payload['secret'] = secret
        return self._request('POST', '/rest/clients/updateWebhook', json_payload=payload)

    def get_bank_info(self, *, country_code: str) -> list[dict[str, Any]]:
        """
        Fetch available banks for a country from GET /rest/bank-info/{countryCode}.
        country_code must be ISO 3166-1 alpha-3 (e.g. 'COL', 'PER').
        Returns list of {bankCode, name, institutionName} dicts.
        """
        url = f'{self.base_url}/rest/bank-info/{country_code.upper()}'
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 400:
                return []
            if not resp.ok:
                raise KoyweError(f'Koywe bank-info returned {resp.status_code} for {country_code}')
            data = resp.json()
            if not isinstance(data, list):
                return []
            return data
        except requests.RequestException as exc:
            raise KoyweError(f'Koywe bank-info request failed for {country_code}: {exc}') from exc

    def _safe_preview_quote(self, *, symbol_in: str, symbol_out: str, amount: Decimal) -> dict[str, Any] | None:
        try:
            return self.create_preview_quote(symbol_in=symbol_in, symbol_out=symbol_out, amount=amount)
        except KoyweMinimumAmountError:
            return None
        except KoyweError as exc:
            message = str(exc).lower()
            if 'less than the minimun available' in message or 'less than the minimum available' in message:
                return None
            raise
