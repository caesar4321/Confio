import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from ramps.koywe import RAMP_NETWORK_DISPLAY, RAMP_USDC_ALGORAND_NOTE

logger = logging.getLogger(__name__)

_TOKEN_CURRENCIES_CACHE_KEY = 'koywe:token-currencies'
_TOKEN_CURRENCIES_CACHE_TTL = 60 * 15
_RAMP_LIMITS_CACHE_TTL = 60 * 10


class KoyweError(Exception):
    pass


class KoyweConfigurationError(KoyweError):
    pass


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
    'corriente': 'checking',
    'nomina': 'checking',
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
    'BO': 'CED_CIU',
    'BR': 'PASS',
    'CL': 'RUT',
    'CO': 'CED_CIU',
    'MX': 'RFC',
    'PE': 'DNI',
    'US': 'PASS',
}

_VERIFICATION_DOCUMENT_TYPE_MAP = {
    'passport': 'PASS',
    'drivers_license': 'PASS',
    'foreign_id': 'CED_EXT',
    'national_id': None,
}


class KoyweClient:
    def __init__(self):
        self.base_url = getattr(settings, 'KOYWE_API_URL', 'https://api.koywe.com').rstrip('/')
        self.client_id = getattr(settings, 'KOYWE_CLIENT_ID', '')
        self.secret = getattr(settings, 'KOYWE_SECRET', '')
        self.crypto_symbol = getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Solana')
        self.timeout = getattr(settings, 'KOYWE_TIMEOUT_SECONDS', 20)
        self.session = requests.Session()

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

        payload: dict[str, Any] = {
            'clientId': self.client_id,
            'secret': self.secret,
        }
        if email:
            payload['email'] = email

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
        if auth:
            headers['Authorization'] = f'Bearer {self.authenticate(email=email)}'
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

    def resolve_payment_provider(self, *, fiat_symbol: str, payment_method_code: str, email: str | None = None) -> tuple[str, str]:
        providers = self.list_payment_providers(fiat_symbol=fiat_symbol, email=email)
        normalized = (payment_method_code or '').strip().upper()
        for provider in providers:
            provider_code = str(provider.get('code') or provider.get('symbol') or provider.get('name') or '').strip().upper()
            provider_id = str(provider.get('_id') or provider.get('id') or provider.get('paymentMethodId') or provider_code)
            display = provider.get('displayName') or provider.get('name') or provider_code
            if provider_code == normalized or provider_id.upper() == normalized:
                return provider_id, display
        return normalized, payment_method_code

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
            payment_method_id, _ = self.resolve_payment_provider(
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

    def create_order(self, *, quote_id: str, email: str | None = None, destination_address: str | None = None, external_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {'quoteId': quote_id}
        if destination_address:
            payload['destinationAddress'] = destination_address
        if external_id:
            payload['externalId'] = external_id
        return self._request('POST', '/rest/orders', email=email, json_payload=payload)

    def get_order(self, *, order_id: str, email: str | None = None) -> dict[str, Any]:
        return self._request('GET', f'/rest/orders/{order_id}', email=email)

    def create_bank_account(self, *, bank_info: Any, email: str | None, country_code: str, fiat_symbol: str, contact_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        alpha3 = _COUNTRY_ALPHA3.get((country_code or '').upper(), (country_code or '').upper())
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
            'accountNumber': account_number,
        }
        if provider_metadata.get('bankCode'):
            resolved_bank_code = self._resolve_bank_code(
                country_code=alpha3,
                bank_name=str(provider_metadata['bankCode']),
            ) or str(provider_metadata['bankCode']).strip().upper()
            payload['bankCode'] = resolved_bank_code
        elif provider_metadata.get('bankName'):
            resolved_bank_code = self._resolve_bank_code(
                country_code=alpha3,
                bank_name=str(provider_metadata['bankName']),
            )
            if resolved_bank_code:
                payload['bankCode'] = resolved_bank_code
        elif getattr(bank_info, 'bank', None) and getattr(bank_info.bank, 'code', None):
            resolved_bank_code = self._resolve_bank_code(
                country_code=alpha3,
                bank_name=str(bank_info.bank.code),
            ) or str(bank_info.bank.code).strip().upper()
            payload['bankCode'] = resolved_bank_code
        elif alpha3 == 'COL' and payment_method_code in {'NEQUI', 'BANCOLOMBIA'}:
            payload['bankCode'] = payment_method_code
        elif alpha3 == 'MEX' and payment_method_code == 'STP':
            payload['bankCode'] = 'STP'
        elif alpha3 == 'PER' and payment_method_code == 'QRI-PE':
            payload['bankCode'] = 'LIGO'
        elif alpha3 == 'PER' and payment_method_code == 'RECAUDO-PE':
            payload['bankCode'] = 'CREDITO'
        if getattr(bank_info, 'account_type', None):
            payload['accountType'] = _ACCOUNT_TYPE_MAP.get(bank_info.account_type, bank_info.account_type)
        elif alpha3 == 'COL' and payment_method_code in {'NEQUI', 'BANCOLOMBIA'}:
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

    def create_ramp_order(self, *, direction: str, amount: Decimal, fiat_symbol: str, payment_method_code: str, email: str | None, wallet_address: str | None, country_code: str, bank_info: Any = None, external_id: str | None = None, contact_profile: dict[str, Any] | None = None) -> KoyweOrderResult:
        normalized_direction = direction.upper()
        if normalized_direction == 'ON_RAMP' and not wallet_address:
            raise KoyweError('The active account does not have a destination wallet address configured')
        payment_method_id, payment_method_display = self.resolve_payment_provider(
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
                contact_profile=contact_profile,
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
        )

        order_id = str(order.get('_id') or order.get('id') or order.get('orderId') or quote_id)
        next_action_url = self._extract_action_url(order)
        next_step = self._determine_next_step(direction=normalized_direction, next_action_url=next_action_url)
        return KoyweOrderResult(
            order_id=order_id,
            amount_in=str(quote.get('amountIn') or amount),
            amount_out=str(quote.get('amountOut') or ''),
            total_change_display=str(quote.get('totalChangeDisplay') or ''),
            rate_display=str(quote.get('rateDisplay') or ''),
            payment_method_display=payment_method_display,
            next_step=next_step,
            next_action_url=next_action_url,
            raw_response=order,
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

    def _normalize_contact_profile(self, *, contact_profile: dict[str, Any] | None, country_code: str) -> dict[str, Any]:
        if not contact_profile:
            return {}
        normalized = dict(contact_profile)
        document_type = normalized.get('documentType')
        if document_type in _VERIFICATION_DOCUMENT_TYPE_MAP:
            normalized['documentType'] = _VERIFICATION_DOCUMENT_TYPE_MAP[document_type] or _DOCUMENT_TYPE_MAP.get(country_code.upper(), 'PASS')
        elif not document_type and normalized.get('documentNumber'):
            normalized['documentType'] = _DOCUMENT_TYPE_MAP.get(country_code.upper(), 'PASS')
        return {key: value for key, value in normalized.items() if value}

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

    def _determine_next_step(self, *, direction: str, next_action_url: str | None) -> str:
        if next_action_url:
            return 'OPEN_PROVIDER_FLOW'
        if direction == 'ON_RAMP':
            return 'SHOW_PAYMENT_INSTRUCTIONS'
        return 'WAIT_FOR_USDC_TRANSFER'

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

    def _safe_preview_quote(self, *, symbol_in: str, symbol_out: str, amount: Decimal) -> dict[str, Any] | None:
        try:
            return self.create_preview_quote(symbol_in=symbol_in, symbol_out=symbol_out, amount=amount)
        except KoyweError as exc:
            message = str(exc).lower()
            if 'less than the minimun available' in message or 'less than the minimum available' in message:
                return None
            raise
