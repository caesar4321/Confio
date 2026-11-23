"""Prepared payments: the record behind a payment card and its signing sheet.

A payment the assistant (or a scan or a share) prepares is one PaymentIntent
row. Preparing it moves no money: it reads the code, asks the rail what the
charge is, prices it all in, and stores exactly what the person will be shown.

Rules this module keeps (docs/designs/ai-assistant-first-redesign.md, section 3):

- The owner's signature is the only way money moves. Confirming an intent only
  prepares the same bridge the Pagar screen prepares; the person still passes
  Confío Face, the journey is still created by `createInfiniaJourney`, and the
  batch is still signed on the phone.
- Displayed facts come from the row, never from assistant text. The payee is
  the rail's answer, stored with how far the rail vouches for it.
- What was shown is what is signed: `display_hash` covers every displayed
  field; a confirmation with another hash, or after the charge or the price
  moved against the person, is refused and needs a new quote (a new row).
- The code comes from the person: their own message, their camera, or a share.
  One other source: the screen where the owner just finished a store's checkout
  themselves (source 'agent_checkout', agent_tasks/runner.after_checkout), read
  by code. A code in tool output or assistant text never reaches here.
- Fail closed: no row unless the charge is readable, payable and priced.
"""
import hashlib
import json
import logging
import re
import time
import unicodedata
import uuid
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import intent_rails, local_money
from .models import FundingInstruction, InfiniaJourney, PaymentIntent
from .services import PaymentAccountError

logger = logging.getLogger(__name__)

RAIL = 'br_qr'
OPEN_STATES = ('quoted', 'awaiting_signature')
# How far the rail vouches for the payee's name, by where the name came from.
# Only 'holder_verified' is a name a bank stands behind. A dynamic charge's
# payload is signed by the site the code points to (any site with a public TLS
# certificate; pix_payload does not check it against the Pix participant
# list), so its names are what that site says, never a verified holder.
LEVELS = {
    ('dict', False): 'holder_verified', ('dict', True): 'holder_verified',
    # The signed payload itself names the receiver (due-date charges).
    ('charge', True): 'signed_charge',
    # An immediate charge: amount, expiry and receiving key are in the signed
    # payload, which carries no name; the name is the code's own text.
    ('qr', True): 'signed_amount',
    ('qr', False): 'self_reported',
}
INSTITUTION_LEVELS = {'signed_charge': 'institution_charge', 'signed_amount': 'institution_amount'}
# What a card may show without anyone opting in: a holder the bank verified,
# a Confío account, a holder the paying provider named, a charge signed by a
# known payment institution, a recipient the owner saved in their own Agenda
# (entered and kept by them: not verified by anyone, not necessarily paid
# before). The rest
# (a site we cannot tie to an institution, a name that is only the code's
# text, an identifier nobody looked up) need PAYMENT_INTENTS_PAYEE_LEVELS.
DEFAULT_LEVELS = ('holder_verified,confio_account,provider_named,institution_charge,institution_amount,saved_payee,'
                  # A store order's account as the store's own checkout screen showed it (agent_tasks,
                  # founder 2026-11-23): only that source makes it, and the card says it is unverified.
                  'store_checkout')
CLIENT_EVENTS = frozenset({'card_shown', 'sheet_opened'})
# Control, format (bidi, zero-width, tags), private-use, unassigned, line/paragraph separators.
_UNSAFE_CATEGORIES = frozenset({'Cc', 'Cf', 'Co', 'Cn', 'Cs', 'Zl', 'Zp'})
_CODE_START = '000201'
_CODE_END = re.compile(r'6304[0-9A-Fa-f]{4}')
_MAX_CODE_CHARS = 1024


class IntentRefused(PaymentAccountError):
    """A payment that cannot be prepared or confirmed; `code` is for metrics
    and for the app to pick the card state, the message is for the person."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


MESSAGES = {
    'unavailable': 'Todavía no puedo preparar pagos desde aquí. Abre Pagar para hacerlo.',
    'not_personal': 'Los pagos preparados por Confío IA funcionan solo en tu cuenta personal.',
    'no_code': 'No encontré un código de pago en tu mensaje. Pega el código Pix (copia e cola) completo.',
    'several_codes': 'Encontré más de un código de pago. Envíame uno solo.',
    'not_asked': ('El código viene dentro de un texto largo. Si quieres pagarlo, envíame solo el código '
                  'y dime que lo pague.'),
    'cut_off': 'Tu mensaje llegó recortado y el código quedó incompleto. Envíame solo el código.',
    'not_said': ('Para preparar un pago necesito que escribas tú, en tu mensaje, a quién y cuánto '
                 '(por ejemplo: "envía 20 dólares a @ana").'),
    'no_saved_payee': ('Desde el chat solo preparo Pago Móvil a un destinatario que ya tengas guardado. '
                       'Dime su nombre como lo guardaste, o envíale desde Pagar.'),
    'no_amount': 'Este código no trae un monto. Ábrelo en Pagar para escribir cuánto quieres enviar.',
    'payee_level': 'El banco no confirma a quién le pagarías con este código. Ábrelo en Pagar para revisarlo tú.',
    'no_payee': 'Este código no dice a quién le pagarías. Pide un código nuevo.',
    'rate_limited': 'Preparaste muchos pagos seguidos. Espera unos minutos y vuelve a intentar.',
    'not_found': 'No encontré ese pago.',
    'expired': 'La cotización venció. Cotiza de nuevo para ver el monto actual.',
    'changed': 'El pago cambió desde que lo viste. Revísalo de nuevo.',
    'charge_changed': 'El comercio cambió este cobro. Revísalo de nuevo antes de pagar.',
    'quote_changed': 'El precio subió desde que lo viste. Cotiza de nuevo para ver el monto actual.',
    'not_open': 'Este pago ya no se puede confirmar.',
    'in_progress': 'Este pago ya está en curso.',
    'still_open': 'Este pago todavía se puede firmar. Ábrelo de nuevo para pagarlo.',
    'closing': 'Estamos cerrando el intento anterior. Vuelve a intentar en unos minutos.',
}


def _refuse(code, message=None):
    return IntentRefused(code, message or MESSAGES.get(code) or 'No pude preparar este pago ahora. Intenta de nuevo.')


# ------------------------------------------------------------------ switches

def _ids(name):
    return {part.strip() for part in str(getattr(settings, name, '') or '').split(',') if part.strip()}


def allowed(user) -> bool:
    """PAYMENT_INTENTS_ALLOWED_USER_IDS: empty = nobody (the default), '*' =
    everyone, otherwise the listed user ids (the tester group)."""
    ids = _ids('PAYMENT_INTENTS_ALLOWED_USER_IDS')
    return user is not None and ('*' in ids or str(getattr(user, 'pk', '')) in ids)


def _version(value):
    try:
        return tuple(int(part) for part in str(value or '').strip().split('.')) if str(value or '').strip() else None
    except ValueError:
        return None


def build_supported(meta) -> bool:
    """The build draws the payment card (PAYMENT_INTENTS_MIN_APP_VERSION;
    empty = no build). Only the assistant tool asks: an older build would
    get a reply that points at a card it cannot show."""
    floor = _version(getattr(settings, 'PAYMENT_INTENTS_MIN_APP_VERSION', ''))
    version = _version((meta or {}).get('HTTP_X_CONFIO_VERSION', ''))
    return floor is not None and version is not None and version >= floor


def allowed_levels():
    return _ids('PAYMENT_INTENTS_PAYEE_LEVELS') or set(DEFAULT_LEVELS.split(','))


def _quote_seconds():
    return max(30, int(getattr(settings, 'PAYMENT_INTENTS_QUOTE_SECONDS', 300)))


# -------------------------------------------------------------------- codes

def find_pix_codes(text):
    """Every well-formed Pix BR Code inside the person's own text.

    A code can hold spaces (the merchant's name) and the bytes '6304' before
    its real end, so each start is tried against each possible end and only a
    code whose own CRC holds counts.
    """
    text = str(text or '')
    found, position = [], 0
    while len(found) < 3:
        start = text.find(_CODE_START, position)
        if start < 0:
            break
        position = start + 1
        window = text[start:start + _MAX_CODE_CHARS]
        for end in _CODE_END.finditer(window):
            candidate = window[:end.end()]
            try:
                local_money.pix_code(candidate)
            except PaymentAccountError:
                continue
            if candidate not in found:
                found.append(candidate)
            position = start + len(candidate)
            break
    return found


# A message that is a code plus a short request ("paga esto porfa"). A code
# buried in a longer text is material the person pasted (to translate, to ask
# whether it is a scam), not a request to pay it.
MAX_CHARS_AROUND_CODE = 160


def code_in_words(*texts):
    """The one code the person sent: from their latest message first, then
    the one before it. Refuses none, several (never a guess), and a code that
    sits inside a long text."""
    for text in texts:
        text = str(text or '')
        codes = find_pix_codes(text)
        if len(codes) > 1:
            raise _refuse('several_codes')
        if codes:
            if len(' '.join(text.replace(codes[0], ' ').split())) > MAX_CHARS_AROUND_CODE:
                raise _refuse('not_asked')
            return codes[0]
        if _CODE_START in text:
            # This message carries a code that is cut or mis-copied: never
            # answer it with the code of an earlier message.
            raise _refuse('cut_off' if text.rstrip().endswith('[mensaje recortado]') else 'no_code')
        if len(' '.join(text.split())) > MAX_REQUEST_CHARS:
            # A long message with no code is not "pay the code I sent before".
            raise _refuse('not_asked')
    raise _refuse('no_code')


def _clean(value, limit):
    """Text a merchant or its bank wrote, made safe to show: one line, no
    invisible or direction-changing characters, bounded."""
    text = ''.join(' ' if unicodedata.category(ch) in _UNSAFE_CATEGORIES else ch for ch in str(value or ''))
    return ' '.join(text.split())[:limit]


# ----------------------------------------------------------------- analytics

def _track(intent, name, *, user=None, **properties):
    """One FunnelEvent row; analytics never break a payment."""
    try:
        from users.models_analytics import FunnelEvent
        with transaction.atomic():
            FunnelEvent.objects.create(
                event_name=f'payment_intent_{name}'[:64],
                user=user if user is not None else intent.user,
                source_type=(intent.created_by if intent is not None else properties.pop('created_by', ''))[:32],
                properties={**({'intent': str(intent.internal_id), 'rail': intent.rail_method_id,
                                'payee_level': intent.payee_level} if intent is not None else {}),
                            **{key: str(value) for key, value in properties.items()}})
    except Exception:  # noqa: BLE001
        logger.warning('payment intent event %s was not recorded', name, exc_info=True)


# ---------------------------------------------------------------- displaying

def _stamp(value):
    return '' if value is None else str(int(value.timestamp()))


def _money(value, places='0.01'):
    return format(Decimal(value).quantize(Decimal(places)), 'f')


def display_fields(intent):
    """Every fact the card and the sheet show, as the strings that are hashed."""
    return {
        'method': intent.rail_method_id, 'family': intent.family,
        'destination': str(intent.destination.internal_id) if intent.destination_id else '',
        'payee_name': intent.payee_name, 'payee_level': intent.payee_level,
        'payee_account': intent.payee_account,
        'payee_document': intent.payee_document, 'institution': intent.institution,
        'amount_exact': '1' if intent.amount_exact else '0',
        'amount_local': _money(intent.amount_local), 'currency': intent.currency,
        'minimum_local': '' if intent.minimum_local is None else _money(intent.minimum_local),
        'total_usd': _money(intent.total_usd), 'fee_usd': _money(intent.fee_usd),
        'estimated_return_usd': _money(intent.estimated_return_usd), 'rate': _money(intent.rate, '0.0001'),
        'charge_expires_at': _stamp(intent.charge_expires_at), 'expires_at': _stamp(intent.expires_at),
    }


def display_hash(intent):
    return hashlib.sha256(json.dumps(display_fields(intent), sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode('utf-8')).hexdigest()


# ----------------------------------------------------------------- preparing

def _require_owner(owner, user):
    if not allowed(user):
        raise _refuse('unavailable')
    if getattr(owner, 'account_type', None) != 'personal' or owner.user_id != getattr(user, 'pk', None):
        raise _refuse('not_personal')
    from security.minors import minor_refusal
    minor = minor_refusal(user)
    if minor:
        raise _refuse('unavailable', minor)


def _identity(owner):
    from .schema import _verified_identity
    try:
        return _verified_identity(owner)
    except PaymentAccountError:
        return None


def _read_charge(owner, destination):
    """What the rail says this charge is, before any pricing: who is paid, how
    far the rail vouches for that name, the exact local amount and the expiry.
    Raises when the charge cannot be paid now or may not be shown."""
    charge = local_money.require_payable_charge(owner, destination)
    validation = charge['validation']
    # A reading with no stated source is a registered holder only when it is
  # the provider's own lookup (which carries its id); anything else is unknown.
    source = str(validation.get('holder_source') or (
        'dict' if validation.get('id') and validation.get('source') != 'pix_network' else ''))
    level = LEVELS.get((source, bool(charge['dynamic'])))
    # A charge whose site is a Pix participant's (pix_participants) is signed
    # by a known payment institution: said as such, with its name.
    hosted_by = validation.get('host_institution') or {}
    if level in INSTITUTION_LEVELS and hosted_by.get('name'):
        level = INSTITUTION_LEVELS[level]
    name = _clean(validation.get('holder_name'), 140)
    if not name:
        raise _refuse('no_payee')
    if level is None or level not in allowed_levels():
        raise _refuse('payee_level')
    return {
        'payee_name': name, 'payee_level': level,
        # Only a registered holder's (masked) document is a fact worth showing.
        'payee_document': _clean(validation.get('holder_document'), 32) if level == 'holder_verified' else '',
        'institution': _clean(hosted_by.get('name') if level in INSTITUTION_LEVELS.values()
                              else validation.get('institution'), 140),
        'amount_local': charge['amount'], 'charge_expires_at': charge['expires_at'],
    }


def _price(owner, destination, charge, *, client=None):
    """What paying it costs the person, all in. The priced charge must be the
    one just read."""
    quote = local_money.pix_charge_quote(owner, destination, client=client)
    if Decimal(quote['amount']) != charge['amount_local']:
        raise _refuse('charge_changed')
    # Stored at the precision of their columns, so the hash of what was shown
    # is the hash of what the row holds.
    cent, up = Decimal('0.01'), ROUND_UP
    return {
        'currency': str(quote['asset']), 'total_usd': Decimal(quote['total_usd']).quantize(cent, rounding=up),
        'fee_usd': Decimal(quote['fee_usd']).quantize(cent, rounding=up),
        'estimated_return_usd': Decimal(quote['estimated_return_usd']).quantize(cent, rounding=ROUND_DOWN),
        'rate': Decimal(quote['rate']).quantize(Decimal('0.0001'), rounding=ROUND_DOWN),
    }


def _fresh_charge(destination, *, client=None):
    """The charge as read now, by this call. A reading another call made
    (ours was dropped as the older one) is not good enough to price or sign on."""
    started = timezone.now()
    destination = local_money.refresh_charge(destination, client=client)
    checked = local_money._aware(((destination.provider_data or {}).get('validation') or {}).get('checked_at'))
    if checked is None or checked < started:
        raise _refuse('rail', 'No pudimos leer este cobro ahora. Intenta de nuevo.')
    return destination


def _count_attempt(owner):
    """Every call that reaches the Pix network or the provider counts, whether
    or not it ends in a card (a refused one costs the same lookups)."""
    from django.core.cache import cache
    key = f'payment_intents:attempts:{owner.pk}'
    limit = 4 * int(getattr(settings, 'PAYMENT_INTENTS_PER_HOUR', 12))
    try:
        cache.add(key, 0, 3600)
        used = cache.incr(key)
    except Exception:  # noqa: BLE001 - no cache: the row count below still limits cards
        logger.warning('payment intent attempt counter unavailable', exc_info=True)
        return
    if used > limit:
        raise _refuse('rate_limited')


def _retire_earlier(intent):
    """An earlier card for the same code must not stay confirmable beside this one."""
    earlier = PaymentIntent.objects.filter(confio_account_id=intent.confio_account_id, state='quoted',
                                           rail_method_id=intent.rail_method_id)
    # The same payment: the same Infinia recipient, or the same payee on a
    # rail without one.
    earlier = (earlier.filter(destination_id=intent.destination_id) if intent.destination_id
               else earlier.filter(destination__isnull=True, payee_account=intent.payee_account,
                                   payee_name=intent.payee_name))
    earlier.exclude(pk=intent.pk).update(state='expired', state_reason='superseded', updated_at=timezone.now())


def _read_pix_charge(owner, value, *, client=None):
    """The facts of an exact Pix charge (family 'local_charge')."""
    method = local_money.METHODS[RAIL]
    local_money.require_rail(owner, _identity(owner), method)
    started = timezone.now()
    destination = local_money.resolve_destination(owner, RAIL, value, client=client)
    # A card always starts from a reading made for it: a recipient checked
    # for an earlier scan may describe a charge the merchant has since revised.
    checked = local_money._aware(((destination.provider_data or {}).get('validation') or {}).get('checked_at'))
    if checked is None or checked < started:
        destination = _fresh_charge(destination, client=client)
    facts = _read_charge(owner, destination)
    facts.update(_price(owner, destination, facts, client=client))
    facts.update(family='local_charge', provider=intent_rails.JOURNEY_PROVIDER, destination=destination,
                 amount_exact=True, minimum_local=None, payee_account='', params={})
    return facts


def prepare(owner, user, raw_code=None, *, created_by, source, request=None, message_id=None, supersedes=None,
            client=None, retire_earlier=True):
    """Read, check and price one payment; returns the PaymentIntent.

    `raw_code` is a payment code; `request` (intent_rails) carries anything
    else the person gave: the rail, an identifier, an amount, a recipient.
    No money moves, nothing is reserved and no order is created. Raises
    IntentRefused (with a Spanish message for the person) when no card may
    be shown.
    """
    refusal_source = {'created_by': created_by}
    request = dict(request or {})
    # Where the request came from is the caller's argument, never a request field.
    request['_source'] = source
    if raw_code is not None:
        request['code'] = str(raw_code or '').strip()
    try:
        _require_owner(owner, user)
        _count_attempt(owner)
        family, method_id, provider = intent_rails.route(request)
        window = timezone.now() - timedelta(hours=1)
        limit = int(getattr(settings, 'PAYMENT_INTENTS_PER_HOUR', 12))
        if PaymentIntent.objects.filter(confio_account=owner, created_at__gte=window).count() >= limit:
            raise _refuse('rate_limited')
        if family == 'local_charge':
            try:
                value = local_money.normalize_value(local_money.METHODS[RAIL],
                                                     request.get('code') or request.get('value') or '')
            except PaymentAccountError as exc:
                raise _refuse('no_code', str(exc)) from exc
            asked = request.get('amount_local')
            if asked not in (None, ''):
                # A code that states its amount (field 54) is compared before
                # anything is read or priced; a dynamic charge after it is read.
                stated = (local_money.emv_fields(value) or {}).get('54')
                try:
                    early = stated is not None and Decimal(str(asked)) != Decimal(stated)
                except (ArithmeticError, TypeError, ValueError):
                    early = True
                if early:
                    raise _refuse('no_amount', 'Este QR ya trae su monto. Paga ese monto o pide otro QR.')
            facts = _read_pix_charge(owner, value, client=client)
            if asked not in (None, ''):
                # The charge's own amount is paid: another one asked for is
                # refused, never silently replaced.
                try:
                    differs = Decimal(str(asked)) != Decimal(str(facts['amount_local']))
                except (ArithmeticError, TypeError, ValueError):
                    differs = True
                if differs:
                    raise _refuse('no_amount', 'Este QR ya trae su monto. Paga ese monto o pide otro QR.')
        else:
            facts = intent_rails.read(owner, user, family, method_id, provider, request, client=client)
    except IntentRefused as exc:
        # Someone the feature is not open to is not a refused payment (and
        # must not be able to write rows at will).
        if exc.code not in ('unavailable', 'not_personal'):
            _track(None, 'refused', user=user, reason=exc.code, **refusal_source)
        raise
    except PaymentAccountError as exc:
        _track(None, 'refused', user=user, reason='rail', **refusal_source)
        raise IntentRefused('rail', str(exc)) from exc
    except Exception:
        # A provider or network failure: no card. The caller words it.
        _track(None, 'refused', user=user, reason='error', **refusal_source)
        raise
    expires = timezone.now() + timedelta(seconds=_quote_seconds())
    if facts['charge_expires_at'] is not None:
        # Never confirmable later than the charge can still settle.
        floor = int(getattr(settings, 'LOCAL_MONEY_PIX_MIN_SECONDS_LEFT', 600))
        # A minute of margin: after confirming, the person still passes Face
        # and the journey asks for the same time left.
        expires = min(expires, facts['charge_expires_at'] - timedelta(seconds=floor + 60))
    if expires <= timezone.now() + timedelta(seconds=30):
        # No time left to review and sign it: no card, rather than one born expired.
        _track(None, 'refused', user=user, reason='expiring', **refusal_source)
        raise _refuse('rail', 'Este cobro vence muy pronto para pagarlo con seguridad. Pide un QR nuevo.')
    if source == 'agent_checkout' and supersedes is not None and (
            (facts['currency'], facts['amount_local']) != (supersedes.currency, supersedes.amount_local)):
        # The order's amount was what the first card showed. Checked before anything is saved or
        # retired: a row with another amount would become what the next re-quote compares to.
        _track(None, 'refused', user=user, reason='changed', **refusal_source)
        raise _refuse('changed')
    with transaction.atomic():
        intent = PaymentIntent(
            confio_account=owner, user=user, created_by=created_by, source=source, rail_method_id=method_id,
            expires_at=expires, message_id=message_id, supersedes=supersedes, **facts)
        intent.display_hash = display_hash(intent)
        intent.save()
        if retire_earlier:
            _retire_earlier(intent)
    _track(intent, 'prepared')
    return intent


def prepare_from_words(owner, user, *texts, client=None):
    """The assistant's path: the code must be in the person's own messages."""
    try:
        code = code_in_words(*texts)
    except IntentRefused as exc:
        _track(None, 'refused', user=user, reason=exc.code, created_by='assistant')
        raise
    # The earlier card is retired only once this one is on a message the
    # person can see (attach_message): a reply that is dropped (team takeover,
    # a failed generation) must not leave them with no card at all.
    return prepare(owner, user, code, created_by='assistant', source='pasted_code', client=client,
                   retire_earlier=False)


# The rails the assistant may be asked for by name. A code names its own
# rail; QR Bolivia needs the app (its QR is read by the provider).
# Whichever provider carries them: the model names a rail, never a provider.
WORD_RAILS = ('br_pix', 'ar_cvu', 'co_breb', 'mx_clabe', intent_rails.CONFIO_SEND, intent_rails.VE_PAGOMOVIL)


def _fold(text):
    text = unicodedata.normalize('NFKD', str(text or '').lower())
    return ''.join(ch for ch in text if not unicodedata.combining(ch))


# Who gets the money is matched strictly, as its own token: people choose
# their own usernames and keys, so a stranger called @mama or 'ana' must never
# pass because the owner wrote "mi mamá" or "mañana".
MAX_REQUEST_CHARS = 300
_MASK_CHARS = frozenset('*•·…×')
_OPENING, _CLOSING = '("\'«¿¡[<', '.,;:!?)"\'»]>'
_PLAIN_NUMBER = re.compile(r'\d[\d.\-/]*\d', re.ASCII)
# Only a phone written with its + may have spaces inside: the rail then checks
# it as a phone (country code, length), which a bare run of digits never gets.
_PHONE_NUMBER = re.compile(r'(?<![\w@*•·…×.])\+\d[\d ()\-.]*\d(?![\w@*•·…×])', re.ASCII)
_DATE_SHAPED = re.compile(r'\d{1,4}[/\-.]\d{1,2}[/\-.]\d{2,4}', re.ASCII)
_CNPJ_SHAPED = re.compile(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', re.ASCII)
_CURRENCY_WORDS = frozenset({
    'pesos', 'peso', 'pesitos', 'dolares', 'dolar', 'dólares', 'dólar', 'usd', 'usdc', 'usdt', 'cusd', 'reales',
    'real', 'reais', 'bs', 'bolivares', 'bolívares', 'bolivianos', 'soles', 'cop', 'mxn', 'ars', 'brl', 'ves', 'bob',
    'pen', 'clp', 'mil', 'millones', 'millon', 'millón', 'lucas', 'col', 'us', 'r', 'u$s'})
# A bare number or a plain alias is a recipient only where the owner's own
# sentence presents it as one: right after a word of direction, or right
# after a word that names an account (with at most a filler between). Listing
# what a number is NOT (a date, an amount, a tail, a reference…) never ends;
# saying what makes it a recipient does.
_TOWARDS = frozenset({'a', 'al', 'para'})
_ACCOUNT_NOUNS = frozenset({
    'llave', 'clabe', 'cvu', 'cbu', 'cuenta', 'cpf', 'cnpj', 'pix', 'celular', 'cel', 'telefono', 'teléfono',
    'cedula', 'cédula', 'cc', 'nit', 'alias', 'chave', 'bre-b', 'breb', 'whatsapp', 'movil', 'móvil',
    'destinatario', 'nequi', 'daviplata', 'tarjeta'})
_PHONE_NOUNS = frozenset({'celular', 'cel', 'telefono', 'teléfono', 'whatsapp', 'movil', 'móvil', 'telefone'})
_FILLERS = frozenset({'numero', 'número', 'nro', 'n°', 'es', 'la', 'el', 'mi', 'su', 'este', 'esta', 'o', 'é',
                      'interbancaria', 'pix', 'bre-b', 'breb', 'cuenta', 'celular', 'llave'})
# Before an account noun these make it a source, a balance or a reference
# ("de la cuenta", "en mi cuenta", "desde la cuenta"), not where money goes.
_NOT_TOWARDS = frozenset({'de', 'del', 'desde', 'en'})
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.ASCII)
_EMAIL = re.compile(r'[^@\s]+@[^@\s.]+(\.[^@\s.]+)+')


def _normalized(text):
    """The owner's text as it is matched: full-width and other compatibility
    forms folded to plain ones, every script's digits to 0-9, odd spaces to a
    space, invisible characters gone. What is sent to the rail is taken from
    this, so it is plain too."""
    out = []
    for ch in unicodedata.normalize('NFKC', str(text or '')):
        category = unicodedata.category(ch)
        if category == 'Cf':
            continue
        if category == 'Nd':
            ch = str(unicodedata.digit(ch))
        elif category in ('Zs', 'Zl', 'Zp') or ch in '\t\r\n':
            ch = ' '
        out.append(ch)
    return ''.join(out)


def _bare(word):
    return word.lstrip(_OPENING).rstrip(_CLOSING)


def _mask_only(word):
    """A word that hides something: stars, bullets, dots, x's."""
    word = word.strip('("\'«[<)»]>,;:!?')
    return len(word) >= 2 and all(ch in _MASK_CHARS or ch in '.-_xX#●∗⁎' for ch in word)


def _money_word(word):
    return word.strip('$:').lower() in _CURRENCY_WORDS or word.strip(':') in ('$', '€', 's/', 's/.')


def _hidden(raw):
    """A word that hides something: a mask word, or anything with an
    ellipsis glued to it ("cuenta… 345678", "34567895...")."""
    return _mask_only(raw) or '..' in raw


def _presented_as_recipient(words, index, rail=None, digits=''):
    """The word at `index` is where the owner's sentence says the money goes:
    it is the whole message (or everything before it is filler: "es …", "el
    número es …"), or it comes right after "a / al / para", or right after a
    word that names an account ("llave", "cuenta", "clabe"…), with at most two
    fillers between ("a la cuenta número …"). Not after a negation, not when
    the account is named as a source ("de la cuenta …"), and nothing in that
    stretch may be hidden."""
    if _hidden(words[index]) or any(_bare(w).lower() == 'no' for w in words[max(0, index - 4):index]):
        return False
    before = [_bare(w).lower().rstrip(':.') for w in words[:index]]
    if len(words) == 1:
        return True  # the message is just this
    if before and all(word in _FILLERS for word in before):
        return not any(_hidden(w) for w in words[:index])  # "es …", "el número es …"
    seen = 0
    for position in range(index - 1, max(-1, index - 4), -1):
        raw = words[position]
        if _hidden(raw):
            return False
        word = before[position]
        if word in _ACCOUNT_NOUNS:
            # "de la cuenta 123", "en mi cuenta 123": a source, not a destination.
            earlier = [w for w in before[max(0, position - 2):position] if w not in ('la', 'el', 'mi', 'su')]
            if earlier and earlier[-1] in _NOT_TOWARDS:
                return False
            if rail == 'br_pix' and word in _PHONE_NOUNS:
                return False  # a phone is a Pix key only with its +55 (the + form)
            return True
        if word in _TOWARDS:
            # On a rail whose keys can be any digits, "a 150000" is as likely an
            # amount: a bare direction word counts only for a mobile number.
            return rail != 'co_breb' or not digits or (len(digits) == 10 and digits.startswith('3'))
        if word in _FILLERS and seen < 2:
            seen += 1
            continue
        return False
    return False


def _owner_number(message, digits, rail=None):
    """The owner's own writing, in ONE message, of the number whose digits are
    `digits`, as the string to send to the rail, or None. Deliberately narrow,
    because a looser reading can turn an amount, a date, a slice or a mask
    into someone's key:

    - one word made only of digits and . - / (a CLABE, a CVU, a CPF with its
      dots), with nothing glued to it, that the sentence presents as the
      recipient (_presented_as_recipient), and that is not written as money
      or a date; or
    - a phone written with its + (spaces allowed inside), sent with its +, so
      the rail checks it as a phone.

    A number written in spaced groups without a leading + is not read (the
    assistant asks for it in one piece)."""
    words = message.split()
    for index, raw in enumerate(words):
        word = _bare(raw)
        if not _PLAIN_NUMBER.fullmatch(word) or re.sub(r'\D', '', word) != digits:
            continue
        after = [_bare(w).lower() for w in words[index + 1:index + 3]]
        if '/' in word and not _CNPJ_SHAPED.fullmatch(word):
            continue  # a date, a fraction, a reference
        if _DATE_SHAPED.fullmatch(word) or raw.lstrip(_OPENING)[:1] in '$#€':
            continue
        if after and (_money_word(after[0]) or (after[0] in ('de', 'en') and any(_money_word(w) for w in after[1:]))):
            continue  # "150.000 pesos", "1.000.000 de pesos": an amount of money
        if index + 1 < len(words) and _hidden(words[index + 1]):
            continue  # "34567895 ****"
        if not _presented_as_recipient(words, index, rail, digits):
            continue
        return digits
    for match in _PHONE_NUMBER.finditer(message):
        if re.sub(r'\D', '', match.group()) == digits:
            return '+' + digits
    return None


def _handle_denied(message, handle):
    """Every place the owner wrote this @usuario comes after a "no" ("no le
    envíes a @pedro, mándale a @ana"): they named it to rule it out."""
    words = _fold(message).split()
    probe = _fold(handle)
    places = [index for index, raw in enumerate(words) if _bare(raw).lstrip('@').rstrip('.,;:!?') == probe]
    return bool(places) and all(
        any(_bare(word).rstrip('.,;:!?') == 'no' for word in words[max(0, index - 4):index]) for index in places)


def owner_recipient(said, value, rail=None):
    """The recipient the model points at, in the OWNER'S own writing: the
    string that is sent to the rail is theirs, never the model's. None when
    the owner did not write it as one clear token. `said` is the owner's
    message, or a list of their messages; each is read on its own, so nothing
    in one message qualifies a word of another.

    - Confío: the exact @usuario (smart_account's strict handle match).
    - A number: see _owner_number.
    - A key: one whole word of a message (ordinary punctuation around it
      aside), not masked, that is an e-mail, an @alias or a random key by its
      own shape, or else a plain alias the sentence presents as the recipient.
      Compared without case except where the rail's keys are case-sensitive
      (Bre-B), which go exactly as written; an e-mail key elsewhere goes in
      lower case."""
    messages = [_normalized(text) for text in ([said] if isinstance(said, str) or said is None else said)]
    value = _normalized(value).strip()
    if rail == intent_rails.CONFIO_SEND:
        from smart_account.assistant_ops import _said_handle
        handle = value.lstrip('@')
        return handle if any(_said_handle(message, value) and not _handle_denied(message, handle)
                             for message in messages) else None
    digits = re.sub(r'[^0-9]', '', value)
    if digits and re.fullmatch(r'\+?[0-9\s.\-/()]+', value):
        if len(digits) < 6:
            return None
        return next((found for found in (_owner_number(message, digits, rail) for message in messages) if found),
                    None)
    if (len(value) < 4 or any(ch in _MASK_CHARS for ch in value) or '...' in value
            or value[:1] in '$#€' or any(ch in value for ch in ',:%=') or not any(ch.isalpha() for ch in value)
            or re.search(r'x{3,}', value.lower())):
        return None  # money, a reference, a time, a mask: never a key
    own_shape = bool(_EMAIL.fullmatch(value) or _UUID.fullmatch(value.lower())
                     or (value.startswith('@') and len(value) >= 4))
    exact = rail == 'co_breb'
    for message in messages:
        words = message.split()
        for index, raw in enumerate(words):
            word = _bare(raw)
            if (word == value) if exact else (word.lower() == value.lower()):
                if '..' in raw or (index and _hidden(words[index - 1])) or (
                        index + 1 < len(words) and _hidden(words[index + 1])):
                    continue  # "*** silva@example.com", "silva@example.co..."
                if not own_shape and not _presented_as_recipient(words, index, rail):
                    continue
                return word if exact else word.lower()
    return None


def _cpf_ok(digits):
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(digits[i]) * (size + 1 - i) for i in range(size))
        if (total * 10) % 11 % 10 != int(digits[size]):
            return False
    return True


def _cnpj_ok(digits):
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        rest = sum(int(d) * w for d, w in zip(digits[:size], weights)) % 11
        if (0 if rest < 2 else 11 - rest) != int(digits[size]):
            return False
    return True


def word_rails():
    """The rails the assistant may take from the owner's WORDS (a code names
    its own rail and is always allowed). Reading a recipient out of a sentence
    is strict for an @usuario and for a saved Pago Móvil name; for typed keys
    and account numbers it is a careful heuristic, so those rails are opt-in
    (PAYMENT_INTENTS_WORD_RAILS)."""
    # The setting ADDS rails (typed keys and account numbers): the two that are
    # read strictly are always on, however it is written.
    configured = {str(rail).strip().lower() for rail in _ids('PAYMENT_INTENTS_WORD_RAILS')}
    configured |= {intent_rails.CONFIO_SEND, intent_rails.VE_PAGOMOVIL}
    return {rail for rail in configured if rail in WORD_RAILS}


def _said_identifier(said, value, rail=None):
    return owner_recipient(said, value, rail) is not None


def _phrase_spans(text, phrase):
    """Where `phrase` stands in `text` as whole words (not inside an e-mail,
    a hyphenated name or a longer word)."""
    if len(phrase) < 3:
        return []
    return [match.span() for match in re.finditer(rf'(?<![\w@.\-]){re.escape(phrase)}(?![\w@\-]|\.\w)', text)]


# Around a saved name in the owner's sentence. Before it: nothing, punctuation
# or one of these ("a Ana", "para mi mamá"); any other word means the name is
# part of a longer one ("Santa Ana") or is not who the money is for. After
# it: nothing, punctuation, a number or one of these ("Ana por pago móvil",
# "Ana 20 dólares"); any other word is the rest of a name ("Ana Gómez").
# Not "de": "la mamá de Pedro", "el hermano de Ana", "de parte de Pedro" name
# someone else's relative or the sender, never the person to pay. Not "que"
# after it: "dile a Ana que…" is talk about Ana, not a payment to her.
_NAME_LEADS = frozenset({'a', 'al', 'para', 'mi', 'mis', 'la', 'el', 'le', 'su', 'tu'})
_NAME_FOLLOWS = frozenset({'por', 'con', 'y', 'pago', 'movil', 'pagomovil', 'dolares', 'dolar', 'usd', 'hoy',
                           'ahora', 'ya', 'manana', 'porfa', 'porfavor', 'gracias', 'via', 'usando', 'mediante',
                           'en', 'desde'})
_NEGATIONS = frozenset({'no', 'nunca', 'jamas', 'ni', 'tampoco', 'menos', 'excepto', 'salvo', 'sin'})
_EDGE_PUNCTUATION = '.,;:!?¡¿()"\'«»'


def _addressed(text, start, end):
    """The words at text[start:end] are who the money is for, and all of
    their name: see _NAME_LEADS / _NAME_FOLLOWS. Never after a "no" ("no le
    envíes a Ana, envía a otra")."""
    before, after = text[:start].rstrip(), text[end:].lstrip()
    words_before = before.split()
    if any(word.strip(_EDGE_PUNCTUATION) in _NEGATIONS for word in words_before[-4:]):
        return False
    if before and before[-1] not in _EDGE_PUNCTUATION:
        if words_before[-1].strip(_EDGE_PUNCTUATION) not in _NAME_LEADS:
            return False
        # "la/el/su/mi/tu <name>" must itself hang from nothing or from a word
        # of direction: "a la mamá" yes, "de la mamá" / "con mi mamá" no.
        lead = words_before[-1].strip(_EDGE_PUNCTUATION)
        if lead in ('la', 'el', 'su', 'mi', 'mis', 'tu') and len(words_before) > 1:
            earlier = words_before[-2]
            if earlier[-1:] not in _EDGE_PUNCTUATION and earlier.strip(_EDGE_PUNCTUATION) not in (
                    'a', 'para', 'le', 'mandale', 'enviale', 'pagale', 'pasale', 'transferile', 'transfierele',
                    'manda', 'envia', 'paga', 'pasa', 'dale') and not earlier[:1].isdigit():
                return False
    if after and after[0] not in _EDGE_PUNCTUATION:
        following = after.split()[0].strip(_EDGE_PUNCTUATION)
        if not (following[:1].isdigit() or following[:1] == '$' or following in _NAME_FOLLOWS):
            return False
    return True


def _addressed_spans(text, phrase):
    return [(start, end) for start, end in _phrase_spans(text, phrase) if _addressed(text, start, end)]


def _saved_pagomovil_by_name(owner, messages, name):
    """The one saved Pago Móvil recipient the OWNER named, by its label or
    its holder's name. Chosen from the owner's words: every saved entry whose
    name stands in them is a candidate, a name that is only part of a longer
    saved name they wrote ("Ana" inside "Ana María") is not, exactly one must
    remain, and it must be the one the model pointed at. Never a guess."""
    from .models import AgendaEntry
    probe = ' '.join(_fold(_normalized(name)).split())
    texts = [' '.join(_fold(_normalized(text)).split()) for text in messages]
    entries = list(AgendaEntry.objects.filter(confio_account=owner, rail='ve_pagomovil',
                                              deleted_at__isnull=True)[:200])
    # Decided inside ONE message: the newest one in which the name stands
    # (an earlier message may be about another payment to another person).
    chosen = next((text for text in texts if _phrase_spans(text, probe)), None)
    if chosen is None:
        raise _refuse('not_said')
    spans = []
    for entry in entries:
        for label in {' '.join(_fold(entry.label).split()), ' '.join(_fold(entry.holder_name).split())}:
            # Only where the sentence addresses that name, whole: "Ana" in
            # "Ana Gómez" or "Santa Ana" is somebody else.
            spans += [(start, end, entry) for start, end in _addressed_spans(chosen, label)]
    # A name inside a longer saved name the owner wrote is that longer name.
    candidates = {entry.pk: entry for start, end, entry in spans
                  if not any(s <= start and end <= e and (e - s) > (end - start) for s, e, _ in spans)}
    if len(candidates) != 1:
        raise _refuse('no_saved_payee')
    entry = next(iter(candidates.values()))
    if probe not in (' '.join(_fold(entry.label or '').split()), ' '.join(_fold(entry.holder_name or '').split())):
        raise _refuse('no_saved_payee')
    details = entry.details or {}
    return {'cedula': details.get('cedula'), 'phone': details.get('phone'), 'bank_code': details.get('bank_code'),
            'holder_name': entry.holder_name}


_DOLLAR_WORDS = frozenset({'dolares', 'dolar', 'usd', 'usdc', 'usdt', 'cusd', 'us', 'u$s', 'dolaritos', 'verdes'})
# Other money and multipliers, beyond _CURRENCY_WORDS: slang, signs written
# apart from the number, and "k".
_OTHER_UNITS = frozenset({
    'bolos', 'bolo', 'bolivar', 'bolivares', 'bolivas', 'bss', 'vef', 'ves', 'cops', 'sol', 'soles', 'guaranies',
    'quetzales', 'colones', 'lempiras', 'cordobas', 'euros', 'euro', 'eur', 'libras', 'k', 'luca', 'lucas', 'palo',
    'palos', 'millon', 'millones', 'mil', 'miles', 'cien', 'cientos', 's/', '€', 'r', 'mxn', 'ars', 'brl', 'cop',
    'bob', 'pen', 'clp', 'pesos', 'peso', 'pesitos', 'reales', 'real', 'reais', 'bs', 'bolivianos', 'varos', 'lana',
    'plata'})
_UNIT_BRIDGES = frozenset({'de', 'del', 'los', 'las', 'en', 'unos', 'unas', 'como', 'aprox', 'casi'})
_AMOUNT_TOKEN = re.compile(r'(?P<unit>r\$|bs\.?|s/\.?|€)?\$?(?P<number>\d+(?:[.,]\d+)*)(?P<suffix>[a-z$€/]+)?')


_MONTHS = frozenset({'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre',
                     'setiembre', 'octubre', 'noviembre', 'diciembre'})


def _amount_values(number):
    """What a written amount means. A mark before one or two last digits is
    the decimal ("1.02" is never 102, "1.500,50" never 150050); marks between
    groups of three are thousands ("1.000"). Anything else means nothing."""
    number = number.rstrip('.,')
    parts = re.split(r'[.,]', number)
    if not all(parts):
        return set()
    if len(parts) == 1:
        return {Decimal(number)}
    head, tail = parts[:-1], parts[-1]
    grouped = 0 < len(head[0]) <= 3 and not head[0].startswith('0') and all(len(part) == 3 for part in head[1:])
    marks = re.findall(r'[.,]', number)
    if len(tail) == 3 and grouped and len(set(marks)) == 1:
        return {Decimal(''.join(parts))}
    if len(head) == 1:
        return {Decimal(f'{head[0]}.{tail}')}
    if len(tail) <= 2 and grouped and len(set(marks[:-1])) == 1 and marks[-1] != marks[0]:
        return {Decimal(f"{''.join(head)}.{tail}")}
    return set()


def _amount_written(message, amount):
    """The owner wrote this amount in THIS message, as a number of its own,
    meaning dollars. Read here, strictly, and not from any other module:
    never part of an account, a phone, a date or an @usuario (the token must
    be a number and nothing else), never one they denied ("no 500", "en vez
    de 500"), never in another unit (_other_unit says that one), never a day
    of the month ("el 20 de noviembre")."""
    others = frozenset(_fold(word) for word in _CURRENCY_WORDS) - _DOLLAR_WORDS
    words = _fold(_normalized(message)).split()
    target = Decimal(str(amount))
    for index, raw in enumerate(words):
        match = _AMOUNT_TOKEN.fullmatch(raw.strip(_EDGE_PUNCTUATION))
        if not match or match.group('unit'):
            continue
        try:
            if target not in _amount_values(match.group('number')):
                continue
        except ArithmeticError:
            continue
        before = [word.strip(_EDGE_PUNCTUATION) for word in words[max(0, index - 3):index]]
        after = [word.strip(_EDGE_PUNCTUATION + '$') for word in words[index + 1:index + 3]]
        if 'no' in before or before[-3:] == ['en', 'vez', 'de'] or before[-2:] == ['vez', 'de']:
            continue
        if after[:1] == ['de'] and after[1:2] and after[1] in _MONTHS:
            continue
        near = set(before[-1:] + after)
        if near & others and not near & _DOLLAR_WORDS:
            continue
        return True
    return False


def _other_unit(said, amount):
    """Every place the owner wrote this number says something that is not
    dollars: another currency ("500 bolívares", "500 bolos", "R$50", "Bs 500",
    "S/ 500", "500 de los bolívares") or a multiplier ("20 mil", "20k",
    "2 lucas"). The model saying amount_usd=500 does not make "500 bolívares"
    five hundred dollars. A bare number, or one written with dollars, is not
    this."""
    others = (frozenset(_fold(word) for word in _CURRENCY_WORDS) | _OTHER_UNITS) - _DOLLAR_WORDS
    words = _fold(_normalized(said)).split()
    seen = other = 0
    for index, raw in enumerate(words):
        match = _AMOUNT_TOKEN.fullmatch(raw.strip(_EDGE_PUNCTUATION))
        if not match:
            continue
        number = match.group('number')
        try:
            # Only ever used to say why it was refused, so a misreading counts
            # here too: "100.000 pesos" taken as 100 is still pesos.
            readings = _amount_values(number) | {Decimal(re.sub(r'[.,]', '', number))}
            if number.count('.') + number.count(',') == 1:
                readings.add(Decimal(number.replace(',', '.')))
            if Decimal(str(amount)) not in readings:
                continue
        except ArithmeticError:
            continue
        seen += 1
        clean = [word.strip(_EDGE_PUNCTUATION + '$') or word.strip(_EDGE_PUNCTUATION) for word in words]
        # The unit may stand one word before ("Bs 500", "S/ 500") or after,
        # past a small bridge ("500 de los bolívares", "500 en pesos").
        following = [word for word in clean[index + 1:index + 5] if word not in _UNIT_BRIDGES][:2]
        near = set(clean[max(0, index - 1):index] + following)
        suffix = (match.group('suffix') or '').strip('$')
        if suffix:
            near.add(suffix)
        if match.group('unit') or (near & others and not near & _DOLLAR_WORDS):
            other += 1
    return seen > 0 and other == seen


def prepare_from_request(owner, user, texts, *, rail=None, recipient=None, amount_usd=None, meta=None,
                         client=None):
    """request_from_words, priced into a card."""
    request, source = request_from_words(owner, user, texts, rail=rail, recipient=recipient, amount_usd=amount_usd,
                                         meta=meta)
    return prepare(owner, user, created_by='assistant', source=source, request=request, client=client,
                   retire_earlier=False)


def request_from_words(owner, user, texts, *, rail=None, recipient=None, amount_usd=None, meta=None, around=None):
    """The assistant's path for any payment; nothing is prepared or saved. Everything that decides where
    money goes comes from the owner's own typed words (`texts`): the code, or
    the recipient and the amount. The model only says which of them to use;
    a recipient or an amount that is not in those words is refused."""
    # Only a short message is a request to pay. A long one is material the
    # person pasted (to translate, to ask whether it is a scam): a recipient
    # and an amount inside it are not theirs to act on.
    texts = [str(text or '') for text in texts]
    rail = str(rail or '').strip() or None
    try:
        code = None
        if rail is None:
            code = code_in_words(*texts)
        # The words around a code, without the code itself (a QR's text is long).
        worded = [text.replace(code, ' ') if code else text for text in texts]
        if not worded or len(' '.join(worded[0].split())) > MAX_REQUEST_CHARS:
            # The latest message is the request. A long one is not one, and an
            # earlier short message does not speak for it.
            raise _refuse('not_asked', 'Tu mensaje es muy largo para tomarlo como un pedido de pago. '
                                       'Escríbeme en una frase a quién y cuánto.')
        messages = [text for text in worded if len(' '.join(text.split())) <= MAX_REQUEST_CHARS]
        amount = None
        if amount_usd not in (None, ''):
            amount = intent_rails.usd_amount(amount_usd)
            if rail is not None:
                # A question is not a request to pay: "¿cuánto es 500 dólares
                # en bolívares?" and "¿quién es @pedro?" must never add up to
                # 500 for @pedro. Who and how much come from what the owner
                # stated ("mándale 20 dólares", then "la llave es …").
                messages = [text for text in messages if '?' not in text and '¿' not in text]
            from .dollars import other_money, said_dollars
            # As dollars, or plain with no other money in play ("500 a @ana en bolívares" is not US$500), in
            # anything they said: questions, voice, captions and long pastes too. A code's own text is not theirs.
            named = [str(text or '').replace(code, ' ') if code else str(text or '')
                     for text in [*(around or ()), *worded]]
            if amount is None or not said_dollars(messages, amount, around=named):
                if amount is not None and any(other_money(text) for text in named):
                    raise _refuse('not_said', 'Dime el monto en dólares y escríbelo con la palabra (por ejemplo: '
                                              '"20 dólares"). No lo convierto yo de otra moneda.')
                if amount is not None and _other_unit(' · '.join(messages), amount):
                    raise _refuse('not_said', 'Dime el monto en dólares (por ejemplo: "20 dólares"). Desde el chat '
                                              'los envíos se preparan en dólares.')
                raise _refuse('not_said')
        if rail is None:
            # A code the person pasted names its own rail; an open one also needs the amount.
            request = {'code': code, 'amount_usd': amount, 'meta': meta}
            source = 'pasted_code'
        elif rail not in word_rails():
            raise _refuse('no_code', 'Ese medio de pago no se puede preparar desde el chat. Ábrelo en Pagar.')
        elif amount is None:
            raise _refuse('no_amount', 'Dime cuántos dólares quieres enviar.')
        elif rail == intent_rails.VE_PAGOMOVIL:
            request = {'method_id': rail, 'amount_usd': amount, 'meta': meta,
                       **_saved_pagomovil_by_name(owner, messages, recipient)}
            source = 'saved_payee'
        else:
            written = owner_recipient(messages, recipient, rail)
            if written is None:
                raise _refuse('not_said')
            if rail == 'br_pix' and written.isdigit() and not (_cpf_ok(written) or _cnpj_ok(written)):
                # Eleven digits that are no CPF are most likely a phone: Pix
                # takes a phone only with its +55, and a number that is not a
                # real document must never be looked up as one.
                raise _refuse('not_said', 'Ese número no es un CPF ni un CNPJ válido. Si es un celular, '
                                          'escríbelo con +55 delante.')
            # What goes to the rail is the owner's own writing of it.
            key = 'recipient' if rail == intent_rails.CONFIO_SEND else 'value'
            request = {'method_id': rail, key: written, 'amount_usd': amount, 'meta': meta}
            source = 'owner_words'
    except IntentRefused as exc:
        _track(None, 'refused', user=user, reason=exc.code, created_by='assistant')
        raise
    return request, source


def attach_message(intent_id, message_id, *, retire_earlier=False):
    """The intent is now on a message the person sees."""
    with transaction.atomic():
        if not PaymentIntent.objects.filter(internal_id=intent_id, message_id__isnull=True).update(
                message_id=message_id):
            return
        if retire_earlier:
            _retire_earlier(PaymentIntent.objects.get(internal_id=intent_id))


def requote(owner, user, intent_id, *, client=None, meta=None):
    """New figures for the same payment: a new row, a new card, a new signature."""
    _require_owner(owner, user)
    old = _owned(owner, intent_id)
    if old.family in ('ramp_order', 'confio_send'):
        current, _ = status(old)
        if old.state == 'awaiting_signature' and not old.order_ref and not _claim_is_stale(old):
            raise _refuse('in_progress')  # its order is being created right now
        if old.order_ref and current not in ('expired', 'cancelled', 'failed', 'refunded'):
            # Its order exists and is still alive (awaiting the owner, paying,
            # paid or under review): that order is the payment.
            raise _refuse('still_open' if current == 'awaiting_signature' else 'in_progress')
        if old.family == 'confio_send' and not intent_rails.retire_unsigned_send(old):
            # The earlier send is being broadcast (or left): never a second one.
            raise _refuse('in_progress')
        if old.state == 'awaiting_signature' and not old.order_ref:
            # A claim that went stale: close it for good before a new card
            # exists, so a confirmation that finishes late finds nothing to
            # attach its order to (and closes what it created).
            if not PaymentIntent.objects.filter(pk=old.pk, state='awaiting_signature', order_ref='').update(
                    state='expired', state_reason='order_failed', updated_at=timezone.now()):
                raise _refuse('in_progress')
        return prepare(owner, user, created_by=old.created_by, source=old.source, request=_request_of(old, meta),
                       message_id=old.message_id, supersedes=old, client=client)
    journey = _journey(old)
    if journey is not None and journey.stage != 'failed':
        # A journey whose batch was never signed is closed by the worker once
        # its signing window passes; until then no second payment can start.
        # (What the card calls 'expired' is 'closing' here, never 'in progress'.)
        raise _refuse('closing' if _never_signed(journey) and not (
            _bridge_signable(journey.bridge) and _charge_has_time(old)) else 'in_progress')
    if journey is None and old.state == 'submitted':
        raise _refuse('in_progress')
    if old.state == 'awaiting_signature' and _bridge_signable(old.bridge) and _charge_has_time(old):
        # Its unsigned transfer holds the wallet until its deadline: a second
        # card could not be confirmed meanwhile.
        raise _refuse('still_open')
    # A card still 'quoted' is retired by the new one only once that exists
    # (prepare): a refused re-quote must not take the valid card away. One
    # whose signing window passed is closed now.
    PaymentIntent.objects.filter(pk=old.pk, state='awaiting_signature').update(
        state='expired', state_reason='requoted', updated_at=timezone.now())
    return prepare(owner, user, created_by=old.created_by, source=old.source, request=_request_of(old, meta),
                   message_id=old.message_id, supersedes=old, client=client)


def _request_of(intent, meta=None):
    """The request that reads an intent's payment again, from the intent's
    own stored details (never from the client)."""
    if intent.family in ('local_charge', 'local_transfer'):
        method = local_money.METHODS[intent.rail_method_id]
        order = (intent.params or {}).get('store_order')
        if order:
            return {'method_id': method.id, 'value': local_money._destination_value(intent.destination, method),
                    'amount_local': order['amount'], 'reference': order['reference'], 'meta': meta}
        exact = (intent.params or {}).get('exact_local')
        # An exact card is read again by its local amount alone (dollars and a
        # local amount together are refused).
        return {'method_id': method.id, 'value': local_money._destination_value(intent.destination, method),
                'amount_usd': None if intent.family == 'local_charge' or exact else intent.total_usd,
                'amount_local': exact, 'meta': meta}
    if intent.family == 'confio_send':
        return {'method_id': intent_rails.CONFIO_SEND, 'recipient': (intent.params or {}).get('username'),
                'amount_usd': intent.total_usd, 'meta': meta}
    return intent_rails.order_request(intent, meta)


# ---------------------------------------------------------------- confirming

def _owned(owner, intent_id, *, lock=False):
    try:
        intent_id = uuid.UUID(str(intent_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _refuse('not_found') from exc
    rows = PaymentIntent.objects.select_related('destination', 'bridge')
    if lock:
        rows = PaymentIntent.objects.select_for_update()
    intent = rows.filter(internal_id=intent_id, confio_account=owner).first()
    if intent is None:
        raise _refuse('not_found')
    return intent


def _journey(intent):
    """The payment of this intent: the outgoing journey under its request id.
    (journey_guard lets no other journey take that id.)"""
    return InfiniaJourney.objects.select_related('bridge', 'money_flow').filter(
        confio_account_id=intent.confio_account_id, request_id=intent.request_id, direction='to_bank').first()


def _never_signed(journey):
    bridge = journey.bridge
    return bridge is not None and not bridge.source_tx_hash and bridge.status in ('prepared', 'expired')


def _bridge_signable(bridge):
    return (bridge is not None and bridge.status == 'prepared' and not bridge.source_tx_hash
            and int(bridge.deadline) > int(time.time()) + 45)


def _charge_has_time(intent):
    """The charge can still settle if the payment starts now (the journey asks
    for the same time left)."""
    if intent.charge_expires_at is None:
        return True
    floor = int(getattr(settings, 'LOCAL_MONEY_PIX_MIN_SECONDS_LEFT', 600))
    return (intent.charge_expires_at - timezone.now()).total_seconds() >= floor


def _expire(intent, reason):
    PaymentIntent.objects.filter(pk=intent.pk, state__in=OPEN_STATES).update(
        state='expired', state_reason=reason, updated_at=timezone.now())
    _track(intent, 'expired', reason=reason)


# Funding refusals (bridge_execution) already written for the person: passed on as they are.
PERSONS_FUNDING_WORDS = ('Ya tienes un envío en curso', 'Tu envío anterior sigue reservado')


def confirm(owner, user, intent_id, shown_hash, *, client=None, bridge_client=None, intents=None, meta=None):
    """The person tapped "Revisar y pagar" and saw this intent's figures
    (Infinia families: an exact charge or a dollar transfer; the others go
    through confirm_any).

    Reads the charge and its price again, refuses anything that moved against
    the person, and prepares the bridge for the stored total. Returns
    (intent, transfer, local_account, crypto_account). Still no money moved:
    the transfer is unsigned and no journey exists.
    """
    _require_owner(owner, user)
    with transaction.atomic():
        intent = _owned(owner, intent_id, lock=True)
        if intent.state == 'submitted':
            # The journey exists but its batch was never signed (the app was
            # closed, the network dropped): the same sheet signs the same
            # transfer while it still can be. Anything else is in progress.
            journey = _journey(intent)
            if (journey is not None and journey.stage != 'failed' and _never_signed(journey)
                    and _bridge_signable(journey.bridge) and _charge_has_time(intent)
                    and str(shown_hash or '') == intent.display_hash):
                try:
                    pair = local_money._active_pair(owner, intent.destination.country, intent.destination.asset)
                except PaymentAccountError as exc:
                    raise IntentRefused('rail', str(exc)) from exc
                return (intent, journey.bridge, *pair)
            raise _refuse('in_progress')
        if intent.state not in OPEN_STATES:
            raise _refuse('not_open')
        if str(shown_hash or '') != intent.display_hash or display_hash(intent) != intent.display_hash:
            raise _refuse('changed')
        if intent.state == 'quoted' and intent.expires_at <= timezone.now():
            intent.state, intent.state_reason = 'expired', 'quote_expired'
            intent.save(update_fields=['state', 'state_reason', 'updated_at'])
            expired = True
        else:
            expired = False
    if expired:
        _track(intent, 'expired', reason='quote_expired')
        raise _refuse('expired')
    intent = _owned(owner, intent_id)
    try:
        local, crypto = local_money._active_pair(owner, intent.destination.country, intent.destination.asset)
    except PaymentAccountError as exc:
        raise IntentRefused('rail', str(exc)) from exc
    if intent.state == 'awaiting_signature':
        # The same sheet opened again: the same unsigned transfer, while it can still be signed.
        if _journey(intent) is not None:
            raise _refuse('in_progress')
        if _bridge_signable(intent.bridge) and _charge_has_time(intent):
            return intent, intent.bridge, local, crypto
        _expire(intent, 'signature_window_passed')
        raise _refuse('expired')
    if intent.family == 'local_transfer':
        # A dollar transfer: the recipient still reads as shown, and what
        # should arrive is not below the minimum the card showed.
        try:
            _count_attempt(owner)
            destination = intent_rails.reread_transfer(owner, intent, meta, client=client)
        except IntentRefused as exc:
            if exc.code in ('charge_changed', 'quote_changed'):
                _expire(intent, exc.code)
            raise
        except PaymentAccountError as exc:
            raise IntentRefused('rail', str(exc)) from exc
    else:
        destination = _reread_charge(owner, intent, client=client)
    instruction = FundingInstruction.objects.filter(
        financial_account=crypto, kind='crypto_address', status='active').first()
    if instruction is None:
        raise IntentRefused('rail', 'Tu cuenta local todavía no está activa.')
    from .bridge import quote_provider_funding
    from .bridge_execution import prepare_bridge
    from .allbridge_next import NextError
    try:
        quote = quote_provider_funding(
            confio_account=owner, funding_instruction_id=instruction.internal_id, amount=intent.total_usd,
            request_id=intent.request_id, direction='to_provider', destination_id=destination.internal_id,
            client=bridge_client)
        transfer = prepare_bridge(owner, quote.internal_id, 0, client=bridge_client, intents=intents)
    except Exception as exc:
        # Nothing was signed. This intent's request id may now hold a bridge
        # quote that expires in a minute, so the way forward is a new quote
        # (a new row, a new request id): the card must not keep reading 'quoted'.
        # (While another unsigned transfer holds the wallet, that new quote
        # can be confirmed once the hold ends; the message says when.)
        if PaymentIntent.objects.filter(pk=intent.pk, state='quoted').update(
                state='expired', state_reason='bridge_failed', updated_at=timezone.now()):
            _track(intent, 'expired', reason='bridge_failed')
        if str(exc) == 'Savings redemption is below its minimum':
            # The redemption could not be priced to cover it (an edge of rounding): nothing personal to fix.
            raise IntentRefused('bridge', 'No pude preparar este pago ahora. Vuelve a prepararlo en un momento.') from exc
        from .shortfall import TOO_FEW_DOLLARS, short_of_dollars
        if str(exc) in TOO_FEW_DOLLARS:
            # Said in the person's words, with what is missing when it is known.
            raise IntentRefused('bridge', str(short_of_dollars(owner, intent.total_usd))) from exc
        if isinstance(exc, PaymentAccountError):
            raise IntentRefused('bridge', str(exc)) from exc
        from .infinia_fees import FeePricingError
        if isinstance(exc, NextError) and str(exc).startswith(PERSONS_FUNDING_WORDS):
            raise IntentRefused('bridge', str(exc)) from exc   # already written for the person, with when
        if isinstance(exc, (NextError, FeePricingError)):
            # The funding's own words are for us (the log). Only a moved price is said as one.
            logger.warning('payment intent funding refused: %s', exc)
            moved = any(word in str(exc) for word in ('fresh quote', 'new quote', 'price changed', 'fee changed',
                                                      'balance changed', 'Quote expired'))
            raise IntentRefused('bridge', 'El precio cambió mientras lo preparábamos. Vuelve a prepararlo.' if moved
                                else 'No pude preparar este pago ahora. Inténtalo más tarde.') from exc
        raise
    if intent.family == 'local_transfer':
        # With the bridge prepared the exact figure is known. It is never
        # signed below the shown minimum (the unsigned transfer then simply
        # runs out; the wallet hold lasts until its deadline).
        try:
            enough = intent_rails.bridged_minimum_ok(owner, intent, transfer, client=client)
        except PaymentAccountError as exc:
            _expire(intent, 'bridge_failed')
            raise IntentRefused('bridge', str(exc)) from exc
        if not enough:
            _expire(intent, 'quote_changed')
            raise _refuse('quote_changed')
    with transaction.atomic():
        locked = _owned(owner, intent_id, lock=True)
        if locked.state not in OPEN_STATES:
            raise _refuse('not_open')
        locked.state, locked.bridge = 'awaiting_signature', transfer
        locked.save(update_fields=['state', 'bridge', 'updated_at'])
    intent = _owned(owner, intent_id)
    _track(intent, 'confirmed')
    return intent, transfer, local, crypto


def _reread_charge(owner, intent, *, client=None):
    """An exact charge at confirmation: read again, compared before pricing,
    then priced; anything that moved against the owner ends the card."""
    try:
        _count_attempt(owner)
        destination = _fresh_charge(intent.destination, client=client)
        facts = _read_charge(owner, destination)
    except IntentRefused:
        raise
    except PaymentAccountError as exc:
        raise IntentRefused('rail', str(exc)) from exc
    # Compared before pricing: a charge that is no longer the one shown is
    # never priced, let alone signed.
    if any(facts[key] != getattr(intent, key) for key in facts):
        _expire(intent, 'charge_changed')
        raise _refuse('charge_changed')
    try:
        facts.update(_price(owner, destination, facts, client=client))
    except IntentRefused as exc:
        if exc.code == 'charge_changed':
            _expire(intent, 'charge_changed')
        raise
    except PaymentAccountError as exc:
        raise IntentRefused('rail', str(exc)) from exc
    if facts['currency'] != intent.currency:
        _expire(intent, 'charge_changed')
        raise _refuse('charge_changed')
    if facts['total_usd'] > intent.total_usd or facts['fee_usd'] > intent.fee_usd:
        # Cheaper is fine (the difference comes back with the unused buffer);
        # dearer than what was shown is never signed.
        _expire(intent, 'quote_changed')
        raise _refuse('quote_changed')
    return destination


def journey_minimum(intent):
    """The local amount the journey of an Infinia intent is created with: the
    exact charge, or the minimum the card showed for a transfer."""
    return intent.amount_local if intent.family == 'local_charge' else intent.minimum_local


def confirm_any(owner, user, intent_id, shown_hash, info=None):
    """Confirmation for every family. Returns (intent, signing): what the app
    hands the owner to sign, by `signing['kind']`:

      journey_bridge   {'transfer', 'local', 'crypto', 'minimum_fx_output'}
                       → Face, createInfiniaJourney, sign the batch
      ramp_order       {'order_id', 'order'} → claim the funding of that order
                       and sign it (the rail's own mutations)
      bsc_send         {'send_id', 'send'} → sign that send (submitBscSend)

    Nothing has moved: every kind still needs the owner's signature."""
    _require_owner(owner, user)
    meta = getattr(getattr(info, 'context', None), 'META', None) or {}
    intent = _owned(owner, intent_id)
    if intent.state == 'quoted' and intent_rails.provider_for(intent.rail_method_id) != intent.provider:
        # The rail moved to another provider since this card was priced: its
        # price is not that provider's. A new quote is.
        _expire(intent, 'quote_changed')
        raise _refuse('quote_changed')
    if intent.family in ('local_charge', 'local_transfer'):
        intent, transfer, local, crypto = confirm(owner, user, intent_id, shown_hash, meta=meta)
        return intent, {'kind': 'journey_bridge', 'transfer': transfer, 'local': local, 'crypto': crypto,
                        'minimum_fx_output': journey_minimum(intent)}
    kind = 'ramp_order' if intent.family == 'ramp_order' else 'bsc_send'
    _count_attempt(owner)
    with transaction.atomic():
        intent = _owned(owner, intent_id, lock=True)
        if str(shown_hash or '') != intent.display_hash or display_hash(intent) != intent.display_hash:
            raise _refuse('changed')
        if intent.state == 'submitted' and intent.order_ref:
            # The order (or send) exists: the same sheet continues it.
            reopen = True
        elif _claim_is_stale(intent):
            # A confirmation that never finished (the request died): over.
            intent.state, intent.state_reason = 'expired', 'order_failed'
            intent.save(update_fields=['state', 'state_reason', 'updated_at'])
            reopen = None
        elif intent.state != 'quoted':
            raise _refuse('in_progress' if intent.state in ('awaiting_signature', 'submitted') else 'not_open')
        elif intent.expires_at <= timezone.now():
            intent.state, intent.state_reason = 'expired', 'quote_expired'
            intent.save(update_fields=['state', 'state_reason', 'updated_at'])
            reopen = None
        else:
            # Claimed before the provider is asked: a second tap never makes
            # a second order.
            intent.state = 'awaiting_signature'
            intent.save(update_fields=['state', 'updated_at'])
            reopen = False
    if reopen is None:
        _track(intent, 'expired', reason=intent.state_reason)
        raise _refuse('expired')
    if reopen:
        current, row = status(intent)
        if current != 'awaiting_signature':
            raise _refuse('in_progress' if current in ('paying', 'paid', 'under_review') else 'expired')
        if kind == 'ramp_order':
            return intent, {'kind': kind, 'order_id': intent.order_ref, 'order': None}
        # The same send again: its idempotency key replays the stored batch.
        try:
            ref, row = intent_rails.create_confio_send(info, intent)
        except PaymentAccountError as exc:
            raise exc if isinstance(exc, IntentRefused) else IntentRefused('rail', str(exc))
        if ref != intent.order_ref:
            raise _refuse('in_progress')
        return intent, {'kind': kind, 'send_id': ref, 'send': row}
    try:
        if intent.family == 'ramp_order':
            intent_rails.reread_order(owner, user, intent, meta)
            ref, row = intent_rails.create_order(info, intent)
        else:
            intent_rails.reread_confio_send(owner, user, intent)
            ref, row = intent_rails.create_confio_send(info, intent)
    except Exception as exc:
        claimed = PaymentIntent.objects.filter(pk=intent.pk, state='awaiting_signature', order_ref='')
        if getattr(exc, 'next_step', '') or getattr(exc, 'keep_card', False):
            # The rail wants a step first (Confío Face), or refused for a
            # reason that leaves the card's figures true (no balance yet):
            # nothing was created and the card stays for another tap.
            claimed.update(state='quoted', updated_at=timezone.now())
            raise
        # No order exists. A new quote (a new row) is the way forward.
        reason = exc.code if isinstance(exc, IntentRefused) and exc.code in (
            'charge_changed', 'quote_changed') else 'order_failed'
        claimed.update(state='expired', state_reason=reason, updated_at=timezone.now())
        _track(intent, 'expired', reason=reason)
        if isinstance(exc, (IntentRefused, PaymentAccountError)):
            raise exc if isinstance(exc, IntentRefused) else IntentRefused('rail', str(exc))
        raise
    if not PaymentIntent.objects.filter(pk=intent.pk, state='awaiting_signature', order_ref='').update(
            state='submitted', order_ref=ref, updated_at=timezone.now()):
        # This confirmation took so long that the card was declared dead (and
        # may have been quoted again): what it just created is closed, so no
        # order or send lives outside a card.
        intent_rails.close_created(intent, ref)
        raise _refuse('expired')
    intent = _owned(owner, intent_id)
    _track(intent, 'confirmed')
    return intent, {'kind': kind, 'order_id' if kind == 'ramp_order' else 'send_id': ref,
                    'order' if kind == 'ramp_order' else 'send': row}


def cancel(owner, intent_id):
    with transaction.atomic():
        intent = _owned(owner, intent_id, lock=True)
        if intent.family in ('ramp_order', 'confio_send'):
            # Once its order exists, that order is cancelled where it lives.
            if intent.state != 'quoted':
                raise _refuse('in_progress' if intent.state in ('submitted', 'awaiting_signature') else 'not_open')
        elif intent.state not in OPEN_STATES or _journey(intent) is not None:
            raise _refuse('in_progress' if intent.state in ('submitted', 'awaiting_signature') else 'not_open')
        intent.state, intent.state_reason = 'cancelled', 'owner'
        intent.save(update_fields=['state', 'state_reason', 'updated_at'])
    _track(intent, 'cancelled')
    return _owned(owner, intent_id)


def track_client(owner, intent_id, event):
    """What only the app knows: the card was drawn, the sheet was opened."""
    if event not in CLIENT_EVENTS:
        raise PaymentAccountError('Invalid event')
    intent = _owned(owner, intent_id)
    from users.models_analytics import FunnelEvent
    # Once per intent and step: a card redrawn on every scroll is one card.
    if not FunnelEvent.objects.filter(event_name=f'payment_intent_{event}',
                                      properties__intent=str(intent.internal_id)).exists():
        _track(intent, event)


# ------------------------------------------------- the journey of an intent

def journey_guard(owner, request_id, *, direction, bridge, destination, minimum_fx_output):
    """Called, inside the journey's transaction, before any journey is created.
    A request id that belongs to an intent may only become the payment that
    intent showed: outgoing, its bridge, its destination, its exact local
    amount, and the charge still reading as it was shown. Returns the intent,
    or None for a payment that did not start from one."""
    intent = PaymentIntent.objects.select_for_update().filter(confio_account=owner, request_id=request_id).first()
    if intent is None:
        # A bridge prepared for an intent is that intent's alone, linked to it
        # or not (a confirmation that lost a race leaves it unlinked): it never
        # funds a journey under another request id.
        if bridge is not None and (
                PaymentIntent.objects.filter(bridge=bridge).exists()
                or PaymentIntent.objects.filter(confio_account=owner, request_id=bridge.quote.request_id).exists()):
            raise _refuse('changed')
        return None
    if direction != 'to_bank' or intent.family not in ('local_charge', 'local_transfer'):
        raise _refuse('changed')
    if intent.state == 'submitted':
        return intent  # the same request retried; create_journey returns its row
    if not allowed(intent.user):
        # Switched off since the card was confirmed: nothing new starts from it.
        raise _refuse('unavailable')
    try:
        amount = Decimal(str(minimum_fx_output))
    except ArithmeticError as exc:
        raise _refuse('changed') from exc
    if (intent.state != 'awaiting_signature' or bridge is None or intent.bridge_id != bridge.pk
            or destination is None or intent.destination_id != destination.pk
            or intent.family not in ('local_charge', 'local_transfer') or amount != journey_minimum(intent)
            or display_hash(intent) != intent.display_hash):
        raise _refuse('changed')
    if not _bridge_signable(bridge) or not _charge_has_time(intent):
        raise _refuse('expired')
    if intent.family == 'local_transfer' and (intent.params or {}).get('store_order'):
        # A store order: the very order the card showed, on its own row.
        if (destination.provider_data or {}).get('store_order') != intent.params['store_order']:
            raise _refuse('charge_changed')
        return intent
    if intent.family == 'local_transfer':
        # The recipient must still read as the card showed it.
        try:
            current = intent_rails.transfer_payee(destination)
        except PaymentAccountError as exc:
            raise _refuse('charge_changed', str(exc)) from exc
        if any(current[key] != getattr(intent, key) for key in current):
            raise _refuse('charge_changed')
        return intent
    # The journey snapshots the recipient as it reads now. If anything read it
    # again since the sheet was shown (another scan, another card), what would
    # be paid is no longer what was shown.
    try:
        current = _read_charge(owner, destination)
    except IntentRefused as exc:
        raise _refuse('charge_changed', str(exc)) from exc
    except PaymentAccountError as exc:
        # No longer verified, read too long ago, already paid: the card is
        # over; a new quote reads the charge again and says why.
        raise _refuse('charge_changed', str(exc)) from exc
    if any(current[key] != getattr(intent, key) for key in current):
        raise _refuse('charge_changed')
    return intent


def journey_refused(owner, request_id, reason):
    """Called after the journey's transaction rolled back on a guard refusal
    that no retry can fix: the card must stop offering the same sheet."""
    intent = PaymentIntent.objects.filter(confio_account=owner, request_id=request_id,
                                          state='awaiting_signature').first()
    if intent is not None:
        _expire(intent, reason)


def journey_created(intent):
    if intent is not None and intent.state == 'awaiting_signature':
        intent.state = 'submitted'
        intent.save(update_fields=['state', 'updated_at'])
        # Not yet signed: the batch is signed right after (the journey's own
        # funding is the evidence of that).
        _track(intent, 'journey_created')


# -------------------------------------------------------------------- status

def status(intent):
    """What the card says now: (status, journey). The intent's own state until
    a journey exists, then the journey's. Never 'paid' before the rail's
    completion."""
    if intent.family in ('ramp_order', 'confio_send'):
        return _order_status(intent)
    journey = _journey(intent) if intent.state in ('awaiting_signature', 'submitted') else None
    if journey is None:
        if intent.state == 'quoted' and intent.expires_at <= timezone.now():
            return 'expired', None
        if intent.state == 'awaiting_signature' and not (
                _bridge_signable(intent.bridge) and _charge_has_time(intent)):
            return 'expired', None
        return intent.state, None
    from .activity import display_stage
    stage = display_stage(journey)
    bridge = journey.bridge
    if stage == 'completed':
        result = 'paid'
    elif stage == 'failed' and _never_signed(journey):
        # Closed without ever being signed: nothing left the wallet.
        result = 'expired'
    elif stage in ('refunded', 'failed'):
        result = stage
    elif stage == 'refunding':
        result = 'refunding'
    elif stage == 'needs_review':
        result = 'under_review'
    elif _never_signed(journey):
        # The journey exists but the batch was never signed (still signable,
        # or past its window and waiting for the worker to close it).
        result = 'awaiting_signature' if _bridge_signable(bridge) and _charge_has_time(intent) else 'expired'
    else:
        result = 'paying'
    if result in ('paid', 'refunded', 'failed') and not intent.outcome:
        if PaymentIntent.objects.filter(pk=intent.pk, outcome='').update(outcome=result, updated_at=timezone.now()):
            intent.outcome = result
            _track(intent, result)
    return result, journey


CLAIM_WINDOW = timedelta(seconds=120)


def _claim_is_stale(intent):
    """An order or send intent claimed for creation long ago with nothing to
    show for it: the request that claimed it died."""
    return (intent.state == 'awaiting_signature' and not intent.order_ref
            and intent.family in ('ramp_order', 'confio_send')
            and timezone.now() - intent.updated_at > CLAIM_WINDOW)


def _order_status(intent):
    """Status of an intent whose payment is a provider order or a Confío send:
    the intent's own state until that exists, then the order's."""
    if intent.state == 'quoted':
        return ('expired' if intent.expires_at <= timezone.now() else 'quoted'), None
    if _claim_is_stale(intent):
        return 'expired', None
    if intent.state != 'submitted' or not intent.order_ref:
        # 'awaiting_signature' here is the moment the order is being created.
        return intent.state, None
    result, row = (intent_rails.order_status if intent.family == 'ramp_order' else intent_rails.send_status)(intent)
    if result is None:
        return 'under_review', None  # an order we cannot find is never shown as paid or open
    if result in ('paid', 'refunded', 'failed') and not intent.outcome:
        if PaymentIntent.objects.filter(pk=intent.pk, outcome='').update(outcome=result, updated_at=timezone.now()):
            intent.outcome = result
            _track(intent, result)
    return result, row


def for_message(owner, message_id):
    """The current intent of one assistant message (the latest after re-quotes)."""
    try:
        message_id = int(message_id)
    except (TypeError, ValueError):
        return None
    return PaymentIntent.objects.select_related('destination', 'bridge').filter(
        confio_account=owner, message_id=message_id).order_by('-created_at', '-pk').first()


def get(owner, intent_id):
    try:
        return _owned(owner, intent_id)
    except IntentRefused:
        return None


# ------------------------------------------------------------------- metric

def repeat_payers(*, since, until=None, created_by='assistant', window_days=30):
    """The agreed success metric: among people whose first prepared payment
    was paid in the period, how many paid a second one within `window_days`.
    Read from the payments themselves (journey, order or send), not from `outcome` (written lazily)."""
    paid = {}
    rows = PaymentIntent.objects.filter(state='submitted', created_by=created_by).order_by('created_at')
    for intent in rows.select_related('destination', 'bridge').iterator():
        result, row = status(intent)
        if result == 'paid':
            paid.setdefault(intent.user_id, []).append(getattr(row, 'created_at', None) or intent.created_at)
    until = until or timezone.now()
    first = {user: times[0] for user, times in paid.items() if since <= times[0] < until}
    again = sum(1 for user, start in first.items()
                if any(start < other <= start + timedelta(days=window_days) for other in paid[user][1:]))
    return {'first_time_payers': len(first), 'repeat_payers': again}
