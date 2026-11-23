"""The rails a prepared payment (payment_intents.py) can ride, behind one shape.

Every rail answers the same three questions, and nothing else about a rail
leaks into the card:

  read(owner, user, request)   who would be paid, how far the rail vouches
                               for that, and what it costs: the facts of the
                               card. Moves no money, reserves nothing, creates
                               no order.
  reread(...)                  the same facts again, at confirmation; anything
                               that moved against the owner ends the card.
  status(intent)               what the payment is doing once it exists.

How a confirmed intent becomes money differs by family, and in every family
the last step is the owner's own signature on the existing flow:

  local_charge    an exact local amount (a Pix charge)        provider journey + bridge
  local_transfer  a dollar amount to a key, account or QR     provider journey + bridge
  ramp_order      a provider order                            ramps.ve_send
  confio_send     dollars to another Confío account           send.bsc_flow

Rail and provider are two things. The rail is what the person pays with (a
Pix key, a CVU, Pago Móvil, a Bolivian QR); the provider is who carries it
(Infinia, Pago ASAP, Dinaria, Mesa de pagos). A rail can have several
providers; which one prices a new card is the server's choice
(`provider_for`: PAYMENT_INTENTS_RAIL_PROVIDERS, else the rail's default),
never the client's, and it is stored on the intent. Nothing above this module
(the card, the hash, the assistant tool, the GraphQL API) knows a provider.

Adding a provider for a rail (for example Dinaria payouts to a CVU or a Pix
key) is one OrderRail subclass registered with `register_order_rail`: how to
read the payee and the price, and how to create its order. Its status comes
from the shared order machinery. Rails that are served by the provider's own
journey machinery (Infinia today) stay in the local_* families.

A `request` is what the person gave: {'method_id', 'code', 'value',
'amount_usd', 'amount_local', 'phone', 'cedula', 'bank_code', 'holder_name',
'recipient', 'meta'}. It never contains an account id, a payee name to show,
or a price: those are the rail's answer.
"""
import logging
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import local_money
from .services import PaymentAccountError

logger = logging.getLogger(__name__)

CENT = Decimal('0.01')
UNSIGNED_SEND_WINDOW = timedelta(minutes=15)
VE_PAGOMOVIL, BO_QR, CONFIO_SEND = 've_pagomovil_send', 'bo_qr', 'confio_send'
INFINIA_METHODS = tuple(m.id for m in local_money.METHODS.values() if m.direction == 'send')


def _refuse(code, message=None):
    from .payment_intents import _refuse as refuse
    return refuse(code, message)


def _clean(value, limit):
    from .payment_intents import _clean as clean
    return clean(value, limit)


def _allowed(level):
    from .payment_intents import allowed_levels
    if level not in allowed_levels():
        raise _refuse('payee_level')
    return level


def usd_amount(value):
    """A dollar amount the person gave: positive, in cents, or None."""
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and Decimal(0) < amount < Decimal('1e9') else None


def _margin():
    """How far below the estimate the shown minimum sits (transfers): the
    estimate is made before the bridge is prepared and the rate can move."""
    bps = Decimal(str(getattr(settings, 'PAYMENT_INTENTS_TRANSFER_MARGIN_BPS', 50)))
    return bps / Decimal(10000) if bps.is_finite() and 0 <= bps < 1000 else Decimal('0.005')


# ------------------------------------------------------------------- routing

def detect_method(code):
    """The Infinia rail a pasted or scanned payment code belongs to, read
    from the code itself, or None. (A Bolivian QR has no public format we
    parse: it is named by the app, never guessed.)"""
    value = str(code or '').strip()
    if not value:
        return None
    try:
        local_money.pix_code(value)
        return 'br_qr'
    except PaymentAccountError:
        pass
    fields = local_money.emv_fields(value) if len(value) <= 4096 else None
    if fields and fields.get('58') == 'AR':
        return 'ar_qr'
    try:
        if local_money.decode_breb_qr(value):
            return 'co_qr'
    except PaymentAccountError:
        pass
    return None


JOURNEY_PROVIDER = 'infinia'   # the provider whose own journey machinery serves the local_* families
CONFIO = 'confio'
ORDER_RAILS = {}               # rail id -> [OrderRail, ...] in registration order


class OrderRail:
    """One rail carried by one provider as an order (ramps.ve_send). Subclass
    it for a new provider or a new rail and register it."""
    rail = ''

    def provider(self):
        """The provider's name, as stored on the intent."""
        raise NotImplementedError

    def read(self, owner, user, request):
        """The facts of the card. No money, no reservation, no order."""
        raise NotImplementedError

    def request_of(self, intent, meta=None):
        """The request that reads this intent again, from its stored details."""
        raise NotImplementedError

    def create(self, info, intent):
        """Make the order from the intent's stored details through the
        rail's own mutation. Returns (order id, payload)."""
        raise NotImplementedError


def register_order_rail(rail):
    ORDER_RAILS.setdefault(rail.rail, []).append(rail)
    return rail


def providers_of(rail_id):
    """Every provider that can carry this rail, the default first."""
    names = [JOURNEY_PROVIDER] if rail_id in INFINIA_METHODS else []
    names += [rail.provider() for rail in ORDER_RAILS.get(rail_id, [])]
    if rail_id == CONFIO_SEND:
        names.append(CONFIO)
    return [name for name in dict.fromkeys(names) if name]


def provider_for(rail_id):
    """Who carries a NEW payment on this rail: PAYMENT_INTENTS_RAIL_PROVIDERS
    ('ar_cvu=dinaria,br_pix=infinia'), else the rail's default. None when no
    provider serves it."""
    available = providers_of(rail_id)
    wanted = {}
    for part in str(getattr(settings, 'PAYMENT_INTENTS_RAIL_PROVIDERS', '') or '').split(','):
        key, _, value = part.partition('=')
        key, value = key.strip().lower(), value.strip().lower()
        if not key and not value:
            continue
        if key not in known_rails() or not value:
            # A typo here must be seen, not quietly ignored.
            logger.error('PAYMENT_INTENTS_RAIL_PROVIDERS: unknown entry %r', part.strip())
            continue
        if wanted.get(key, value) != value:
            # Two answers for one rail: neither is trusted.
            logger.error('PAYMENT_INTENTS_RAIL_PROVIDERS: conflicting providers for %s', key)
            value = '?'
        wanted[key] = value
    choice = wanted.get(rail_id, '')
    if choice:
        # A configured provider that cannot carry the rail is no provider:
        # never a silent fall back to another one.
        return choice if choice in available else None
    return available[0] if available else None


def order_rail(rail_id, provider):
    return next((rail for rail in ORDER_RAILS.get(rail_id, []) if rail.provider() == provider), None)


def known_rails():
    return tuple(dict.fromkeys(INFINIA_METHODS + tuple(ORDER_RAILS) + (CONFIO_SEND,)))


def route(request):
    """(family, method_id, provider) for a request, or a refusal. The rail is
    the one the app named, or the one the code itself declares; the provider
    is the server's choice for that rail."""
    method_id = str(request.get('method_id') or '').strip()
    code = str(request.get('code') or request.get('value') or '').strip()
    if not method_id:
        method_id = detect_method(code) or ''
        if not method_id:
            raise _refuse('no_code')
    if method_id not in known_rails():
        raise _refuse('no_code', 'Este medio de pago no está disponible.')
    provider = provider_for(method_id)
    if provider is None:
        raise _refuse('rail', 'Este medio de pago no está disponible ahora.')
    family = _family(method_id, provider, code)
    return family, method_id, provider


def _family(method_id, provider, code):
    if method_id == CONFIO_SEND:
        return 'confio_send'
    if provider != JOURNEY_PROVIDER or method_id not in INFINIA_METHODS:
        return 'ramp_order'
    if method_id == 'br_qr':
        try:
            fixed = local_money.fixed_pix_charge(local_money.METHODS['br_qr'], code)
        except PaymentAccountError as exc:
            raise _refuse('no_code', str(exc)) from exc
        if fixed:
            return 'local_charge'
    return 'local_transfer'


# ---------------------------------------------------- Infinia: dollar transfers

def transfer_payee(destination):
    """Who an Infinia recipient is, as far as the rail says. With the holder
    lookup off (the case today) a key, an account or a QR is only itself."""
    view = local_money.destination_view(destination)
    method = local_money.METHODS.get(view['method_id'])
    if method is None:
        raise _refuse('no_payee')
    state = view['verification']
    if method.id == 'co_qr':
        identifier = (destination.details or {}).get(method.field, '')  # the key inside the QR, not its text
    elif method.kind == 'qr':
        identifier = view['label'].split(' · ')[-1]
    else:
        identifier = local_money._destination_value(destination, method)
    identifier = _clean(identifier, 140)
    if state == 'verified':
        return {'payee_name': _clean(view['holder_name'], 140), 'payee_level': _allowed('holder_verified'),
                'payee_document': _clean(view['holder_document'], 32),
                'institution': _clean(view['institution'], 140), 'payee_account': identifier}
    if state != 'not_checked':
        # The lookup ran and did not confirm anyone (pending, not found,
        # could not run): the manual screen asks the person; a card does not.
        raise _refuse('payee_level', 'El banco no confirmó a quién pertenece este destino. '
                                     'Ábrelo en Pagar para revisarlo tú.')
    if method.kind == 'qr' or method.id == 'co_qr':
        fields = local_money.emv_fields(local_money._destination_value(destination, method)) or {}
        name = _clean(view.get('qr_merchant_name') or fields.get('59'), 140)
        if not name:
            raise _refuse('no_payee')
        return {'payee_name': name, 'payee_level': _allowed('self_reported'), 'payee_document': '',
                'institution': '', 'payee_account': identifier}
    return {'payee_name': method.title, 'payee_level': _allowed('unverified'), 'payee_document': '',
            'institution': '', 'payee_account': identifier}


def _transfer_price(owner, destination, amount, *, client=None):
    quote = local_money.payout_quote(owner, destination, amount=amount, client=client)
    fee = local_money.payout_fee(owner, destination)
    floor = (Decimal(quote['minimum_target']) * (1 - _margin())).quantize(CENT, rounding=ROUND_DOWN)
    if floor <= 0:
        raise _refuse('rail', 'El monto es demasiado bajo para este envío.')
    return {
        'amount_exact': False, 'currency': str(quote['asset']),
        'amount_local': Decimal(quote['expected_target']).quantize(CENT, rounding=ROUND_DOWN),
        'minimum_local': floor, 'total_usd': amount,
        'fee_usd': Decimal(str((fee or {}).get('total_usd') or 0)).quantize(CENT, rounding=ROUND_UP),
        'estimated_return_usd': Decimal('0.00'),
        'rate': Decimal(quote['rate']).quantize(Decimal('0.0001'), rounding=ROUND_DOWN),
        'charge_expires_at': None,
    }


def _location(owner, method, meta):
    # Colombia (Bre-B) needs a current location pass from an allowed IP, as
    # every Bre-B operation does. No request, no pass.
    from . import breb_location
    breb_location.require_for_country(owner, method.country, meta or {})


# A store's SPEI order: its CLABE, exact pesos and the order's reference, as
# the store's own checkout screen showed them (agent_tasks). The dollars are
# priced so that the conversion's guaranteed minimum covers the order; the
# payout is exactly the order (infinia_journeys); what the conversion lands
# above it stays in the person's own peso account (founder, 2026-11-23).
STORE_ORDER_SOURCE = 'agent_checkout'
SPEI_REFERENCE_MAX = 40
_PRICE_TRIES = 5


def exact_local(request):
    """The exact local amount a person typed for a key, an account or an open
    QR ('' when none). A store's order reference never rides along: that is
    only read off a checkout (store_order_terms)."""
    raw = request.get('amount_local')
    if raw in (None, ''):
        return ''
    if request.get('reference') not in (None, ''):
        # Never silently a dollar send instead: the amount and its reference
        # belong to a store's checkout, and this is not one.
        raise _refuse('no_amount', 'Este monto con referencia solo se paga desde el pago de una tienda.')
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0:
        raise _refuse('no_amount', 'Escribe el monto en moneda local con hasta dos decimales.')
    if amount >= Decimal('1e9'):   # before quantizing: a huge exponent cannot be quantized
        raise _refuse('no_amount', 'Ese monto es demasiado alto para un envío.')
    if amount != amount.quantize(CENT):
        raise _refuse('no_amount', 'Escribe el monto en moneda local con hasta dos decimales.')
    return str(amount.quantize(CENT))


def store_order_terms(request):
    """{'amount', 'reference'} when this request pays one store order, else None."""
    if request.get('_source') != STORE_ORDER_SOURCE or request.get('reference') in (None, ''):
        return None
    reference = ' '.join(str(request.get('reference') or '').split())
    if not 1 <= len(reference) <= SPEI_REFERENCE_MAX or not all(c.isascii() and (c.isalnum() or c == ' ')
                                                                 for c in reference):
        raise _refuse('no_code', 'La referencia del pedido no es válida para SPEI.')
    try:
        amount = Decimal(str(request.get('amount_local')))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0 or amount != amount.quantize(CENT) \
            or amount >= Decimal('1e8'):
        raise _refuse('no_amount', 'No pude leer el monto del pedido.')
    return {'amount': str(amount.quantize(CENT)), 'reference': reference}


def _require_unpaid(destination):
    """A dynamic fixed-amount QR someone already paid ends the card
    (charge_changed), before any bridge is prepared for it."""
    try:
        local_money.require_unpaid_qr(destination)
    except PaymentAccountError as exc:
        raise _refuse('charge_changed', str(exc)) from exc


ORDER_PRICE_CACHE_SECONDS = 20


def _order_price_key(owner_pk, destination_pk, exact):
    return f'order_price:{owner_pk}:{destination_pk}:{Decimal(str(exact)).quantize(CENT):f}'


def forget_order_price(destination, exact):
    """A fresh check said the price moved: the next ask prices it again."""
    from django.core.cache import cache
    try:
        cache.delete(_order_price_key(destination.confio_account_id, destination.pk, exact))
    except (InvalidOperation, TypeError, ValueError):
        pass


def _order_price(owner, destination, exact, *, client=None):
    """The dollars whose guaranteed minimum covers `exact` local units.
    Kept a few seconds per recipient and amount: typing asks again often, and
    every try is a bridge estimate and a provider quote."""
    from django.core.cache import cache
    key = _order_price_key(owner.pk, destination.pk, exact)
    cached = cache.get(key)
    if cached is not None:
        return dict(cached)
    price = _search_order_price(owner, destination, exact, client=client)
    cache.set(key, dict(price), ORDER_PRICE_CACHE_SECONDS)
    return price


def _search_order_price(owner, destination, exact, *, client=None):
    dollars = Decimal('10.00')
    for _ in range(_PRICE_TRIES):
        price = _transfer_price(owner, destination, dollars, client=client)
        # Scaled both ways from the probe: an amount under the probe is not
        # charged the probe's dollars.
        needed = (dollars * exact / price['minimum_local']).quantize(CENT, rounding=ROUND_UP) + CENT
        if price['minimum_local'] >= exact and dollars <= needed:
            return price
        dollars = needed
    raise _refuse('rail', 'No pudimos cotizar este pago. Intenta de nuevo.')


# The bank a CLABE belongs to is its first three digits (Banxico's institution codes).
CLABE_BANKS = {'002': 'Banamex', '012': 'BBVA México', '014': 'Santander', '021': 'HSBC', '030': 'BanBajío',
               '036': 'Inbursa', '044': 'Scotiabank', '058': 'Banregio', '072': 'Banorte', '127': 'Banco Azteca',
               '137': 'BanCoppel', '646': 'STP', '722': 'Mercado Pago'}


def _order_facts(destination, order, price):
    exact = Decimal(order['amount'])
    clabe = (destination.details or {}).get('clabe', '')
    return {
        # Read off the store's own checkout; no holder lookup (founder, 2026-11-23).
        'payee_name': 'Cuenta de la tienda', 'payee_level': _allowed('store_checkout'), 'payee_document': '',
        'institution': CLABE_BANKS.get(clabe[:3], ''), 'payee_account': _clean(clabe, 140),
        **price, 'amount_exact': True, 'amount_local': exact, 'minimum_local': exact,
    }


def read_store_order(owner, user, method_id, request, order, *, client=None):
    from .payment_intents import _identity
    method = local_money.get_method(method_id, 'send')
    if method.id != 'mx_clabe':
        raise _refuse('no_code', 'Este medio no paga pedidos de tiendas.')
    raw = str(request.get('code') or request.get('value') or '').strip()
    try:
        value = local_money.normalize_value(method, raw)
    except PaymentAccountError as exc:
        raise _refuse('no_code', str(exc)) from exc
    local_money.require_rail(owner, _identity(owner), method)
    destination = local_money.resolve_destination(owner, method_id, value, client=client, store_order=order)
    facts = _order_facts(destination, order, _order_price(owner, destination, Decimal(order['amount']),
                                                          client=client))
    facts.update(family='local_transfer', provider=JOURNEY_PROVIDER, destination=destination,
                 params={'store_order': order})
    return facts


def read_transfer(owner, user, method_id, request, *, client=None):
    from .payment_intents import _identity
    order = store_order_terms(request)
    if order is not None:
        return read_store_order(owner, user, method_id, request, order, client=client)
    method = local_money.get_method(method_id, 'send')
    raw = str(request.get('code') or request.get('value') or '').strip()
    try:
        value = local_money.normalize_value(method, raw)
    except PaymentAccountError as exc:
        raise _refuse('no_code', str(exc)) from exc
    exact = local_money.qr_amount(method, value)
    if exact and not local_money.fixed_qr_build_supported(request.get('meta')):
        # An older build would show this card without saying where the spare
        # goes, and pay it as its own: told to update, as on Pagar.
        raise _refuse('rail', local_money.UPDATE_FOR_FIXED_QR)
    typed = '' if exact else exact_local(request)
    amount = usd_amount(request.get('amount_usd'))
    if amount is None and not exact and not typed:
        raise _refuse('no_amount', 'Dime cuántos dólares quieres enviar.')
    local_money.require_rail(owner, _identity(owner), method)
    _location(owner, method, request.get('meta'))
    destination = local_money.recheck_destination(local_money.resolve_destination(owner, method_id, value,
                                                                                  client=client), client=client)
    facts = transfer_payee(destination)
    _require_unpaid(destination)
    if exact:
        # A QR with a fixed amount (Bre-B, Argentina): priced in dollars so the
        # guaranteed minimum covers it; the journey pays exactly its amount and the
        # rest stays in the person's own peso account (store_order_snapshot).
        exact = Decimal(exact).quantize(CENT)
        facts.update(_order_price(owner, destination, exact, client=client))
        facts.update(amount_exact=True, amount_local=exact, minimum_local=exact)
    elif typed:
        # The person named an exact local amount for a key or an account: the
        # same pricing, and the payment (not the recipient) carries the amount.
        exact = Decimal(typed)
        facts.update(_order_price(owner, destination, exact, client=client))
        facts.update(amount_exact=True, amount_local=exact, minimum_local=exact)
        facts.update(family='local_transfer', provider=JOURNEY_PROVIDER, destination=destination,
                     params={'exact_local': typed})
        return facts
    else:
        facts.update(_transfer_price(owner, destination, amount, client=client))
    facts.update(family='local_transfer', provider=JOURNEY_PROVIDER, destination=destination, params={})
    return facts


def reread_transfer(owner, intent, request_meta=None, *, client=None):
    """At confirmation: the recipient still reads as shown and the price did
    not move against the owner. Returns the recipient row."""
    method = local_money.get_method(intent.rail_method_id, 'send')
    _location(owner, method, request_meta)
    order = (intent.params or {}).get('store_order')
    if order:
        # The same order: its row still carries it, and the dollars shown still cover it.
        destination = intent.destination
        if (destination.provider_data or {}).get('store_order') != order:
            raise _refuse('charge_changed', 'El pedido cambió desde que lo viste. Revísalo de nuevo.')
        price = _transfer_price(owner, destination, intent.total_usd, client=client)
        if price['minimum_local'] < Decimal(order['amount']) or price['fee_usd'] > intent.fee_usd \
                or price['currency'] != intent.currency:
            raise _refuse('quote_changed')
        return destination
    destination = local_money.recheck_destination(intent.destination, client=client)
    payee = transfer_payee(destination)
    if any(payee[key] != getattr(intent, key) for key in payee):
        raise _refuse('charge_changed', 'El destino cambió desde que lo viste. Revísalo de nuevo.')
    if not intent.amount_exact and local_money.is_fixed_amount_qr(destination):
        # A dollar card shown before this QR was paid exactly: the card is over.
        raise _refuse('charge_changed', 'Este QR cobra un monto exacto. Escanéalo de nuevo para pagarlo.')
    _require_unpaid(destination)
    price = _transfer_price(owner, destination, intent.total_usd, client=client)
    if price['minimum_local'] < intent.minimum_local or price['fee_usd'] > intent.fee_usd \
            or price['currency'] != intent.currency:
        if intent.amount_exact:
            # The new card is priced fresh, not from the few seconds' memory.
            forget_order_price(destination, intent.minimum_local)
        raise _refuse('quote_changed')
    return destination


def bridged_minimum_ok(owner, intent, transfer, *, client=None):
    """With the bridge prepared, what will land is known: never below the
    minimum the card showed."""
    final = local_money.payout_quote(owner, intent.destination, bridge=transfer, client=client)
    enough = Decimal(final['minimum_target']) >= intent.minimum_local
    if not enough and intent.amount_exact:
        forget_order_price(intent.destination, intent.minimum_local)
    return enough


# ------------------------------------------------- provider orders (ramps.ve_send)

def _order_refusal(exc):
    # (A provider error with no words still needs some: 'rail' has no stock message.)
    return _refuse('rail', str(exc) or 'No pudimos crear este pago. Intenta de nuevo.')


def _saved_pagomovil(owner, beneficiary):
    """The owner's own saved recipient with these exact details, or None."""
    from .models import AgendaEntry
    for entry in AgendaEntry.objects.filter(confio_account=owner, rail='ve_pagomovil',
                                            deleted_at__isnull=True)[:200]:
        details = entry.details or {}
        if all(str(details.get(key) or '') == str(beneficiary.get(key) or '')
               for key in ('cedula', 'phone', 'bank_code')):
            return entry
    return None


def read_pagomovil(owner, user, request, *, client=None):
    from ramps import ve_pagomovil
    from ramps.ve_pagomovil import VePagoMovilError
    meta = request.get('meta') or {}
    if not (ve_pagomovil.enabled(ve_pagomovil.SEND) and ve_pagomovil.client_supports(ve_pagomovil.SEND, meta)):
        raise _refuse('rail', 'Pago Móvil no está disponible ahora.')
    exact = exact_local(request)
    amount = usd_amount(request.get('amount_usd'))
    if amount is None and not exact:
        raise _refuse('no_amount', 'Dime cuántos dólares quieres enviar.')
    try:
        beneficiary = {'cedula': ve_pagomovil.normalize_cedula(request.get('cedula')),
                       'phone': ve_pagomovil.normalize_phone(request.get('phone')),
                       'bank_code': ve_pagomovil.normalize_bank(request.get('bank_code'))}
        if exact:
            # Exact bolívares: the provider prices them in dollars and pays
            # exactly them; one that cannot is refused, never guessed.
            adapter = ve_pagomovil.send_adapter()
            if not callable(getattr(adapter, 'quote_exact', None)):
                raise _refuse('rail', 'Por ahora solo puedes enviar un monto en dólares por Pago Móvil.')
            quote = adapter.quote_exact(exact)
            amount = Decimal(str(quote['usd_amount']))
        else:
            quote = ve_pagomovil.send_adapter().quote(amount)
    except VePagoMovilError as exc:
        raise _order_refusal(exc) from exc
    saved = _saved_pagomovil(owner, beneficiary)
    typed = _clean(request.get('holder_name'), 140)
    # Pago Móvil has no payee lookup at all: the details are only as right as
    # whoever typed them. A recipient in the owner's own agenda is one they
    # entered and kept themselves (not one anybody verified): the card says
    # "guardado por ti", and its name is the saved one, never one typed now.
    level = _allowed('saved_payee' if saved is not None else 'unverified')
    name = (_clean(saved.holder_name or saved.label, 140) if saved is not None else typed)
    bank = ve_pagomovil.BANK_NAMES.get(beneficiary['bank_code'], beneficiary['bank_code'])
    fees = sum((Decimal(str(quote.get(key) or 0)) for key in ('confio_fee_usd', 'processor_fee_usd')), Decimal(0))
    return {
        'family': 'ramp_order', 'destination': None, 'provider': PagoMovilRail().provider(),
        'payee_name': name or 'Pago Móvil', 'payee_level': level, 'payee_document': '',
        'institution': _clean(bank, 140),
        'payee_account': _clean(f"{beneficiary['phone']} · {beneficiary['cedula']}", 140),
        # The dollars are fixed; bolívares are priced when the payout runs
        # (exactly the amount asked for, when one was).
        'amount_exact': bool(exact), 'currency': 'VES',
        'amount_local': Decimal(str(quote['estimated_ves'])).quantize(CENT, rounding=ROUND_DOWN),
        'minimum_local': Decimal(exact) if exact else None, 'total_usd': amount, 'fee_usd': fees.quantize(CENT, rounding=ROUND_UP),
        'estimated_return_usd': Decimal('0.00'),
        'rate': Decimal(str(quote.get('rate') or 0)).quantize(Decimal('0.0001'), rounding=ROUND_DOWN),
        'charge_expires_at': None,
        # What the order is created with is what the card shows.
        'params': {**beneficiary, 'holder_name': name, **({'exact_ves': exact} if exact else {})},
    }


def read_bolivia_qr(owner, user, request, *, client=None):
    from ramps import bolivia_qr, bolivia_qr_send
    from ramps.bolivia_qr import BoliviaQrError
    if not bolivia_qr.offered(bolivia_qr.SEND, request.get('meta') or {}, user):
        raise _refuse('rail', 'QR Bolivia no está disponible ahora.')
    qr_text = str(request.get('code') or request.get('value') or '').strip()
    try:
        preview = bolivia_qr_send.decode(qr_text)
        if not preview.get('fixed_amount') and request.get('amount_local') in (None, ''):
            raise _refuse('no_amount', 'Este QR no trae un monto. Dime cuántos bolivianos quieres pagar.')
        terms = bolivia_qr_send.quote(qr_text, request.get('amount_local'))
    except BoliviaQrError as exc:
        raise _order_refusal(exc) from exc
    preview = terms['preview']
    name = _clean(preview.get('holder_name'), 140)
    if not name:
        raise _refuse('no_payee')
    last4 = _clean(preview.get('account_last4'), 8)
    return {
        'family': 'ramp_order', 'destination': None, 'provider': BoliviaQrRail().provider(),
        # The paying provider decoded the bank's QR and named its holder.
        'payee_name': name, 'payee_level': _allowed('provider_named'), 'payee_document': '',
        'institution': _clean(preview.get('bank_name'), 140),
        'payee_account': f'•••• {last4}' if last4 else '',
        'amount_exact': True, 'currency': 'BOB',
        'amount_local': Decimal(terms['bob_amount']).quantize(CENT), 'minimum_local': None,
        'total_usd': Decimal(terms['usd_amount']).quantize(CENT, rounding=ROUND_UP),
        'fee_usd': Decimal(str(terms.get('confio_fee_usd') or 0)).quantize(CENT, rounding=ROUND_UP),
        'estimated_return_usd': Decimal('0.00'),
        'rate': Decimal(str(terms.get('rate') or 0)).quantize(Decimal('0.0001'), rounding=ROUND_DOWN),
        'charge_expires_at': None,
        'params': {'qr_text': qr_text,
                   'bob_amount': '' if preview.get('fixed_amount') else terms['bob_amount']},
    }


def _rail_of(intent):
    rail = order_rail(intent.rail_method_id, intent.provider)
    if rail is None:
        # The provider that priced this card no longer carries the rail (it
        # was switched): the card is over, a new one is priced by the new one.
        raise _refuse('quote_changed')
    return rail


def order_request(intent, meta=None):
    """The request that reads this order intent again, from its own stored
    details (never from the client)."""
    # The stored details describe the recipient on the rail, whoever carries
    # it: after a switch of provider, the new one reads the same request.
    rails = ORDER_RAILS.get(intent.rail_method_id, [])
    rail = (order_rail(intent.rail_method_id, provider_for(intent.rail_method_id))
            or order_rail(intent.rail_method_id, intent.provider) or (rails[0] if rails else None))
    if rail is None:
        raise _refuse('rail', 'Este medio de pago no está disponible ahora.')
    return rail.request_of(intent, meta)


def reread_order(owner, user, intent, meta=None):
    rail = _rail_of(intent)
    if provider_for(intent.rail_method_id) != intent.provider:
        raise _refuse('quote_changed')
    facts = rail.read(owner, user, rail.request_of(intent, meta))
    same = ('payee_name', 'payee_level', 'institution', 'payee_account', 'currency')
    if any(facts[key] != getattr(intent, key) for key in same) or (
            intent.amount_exact and facts['amount_local'] != intent.amount_local):
        raise _refuse('charge_changed', 'El destino cambió desde que lo viste. Revísalo de nuevo.')
    # Where the dollars are fixed (Pago Móvil) the fee line moves with the
    # market inside the same total: only the total and the estimate matter.
    # Exact bolívares: the provider's fee line follows the market reference
    # inside the same total, so only the total binds (create() refuses a
    # higher one again).
    fee_binds = intent.amount_exact and intent.rail_method_id != VE_PAGOMOVIL
    if facts['total_usd'] > intent.total_usd or (fee_binds and facts['fee_usd'] > intent.fee_usd):
        raise _refuse('quote_changed')
    if not intent.amount_exact and facts['amount_local'] < intent.amount_local * (1 - 4 * _margin()):
        # The estimate fell noticeably since the card: show the new one.
        raise _refuse('quote_changed')
    return facts


class PagoMovilRail(OrderRail):
    """Venezuelan Pago Móvil. ramps.ve_pagomovil picks the provider (Pago
    ASAP or Dinaria) itself: this rail is the same whichever carries it."""
    rail = VE_PAGOMOVIL

    def provider(self):
        return str(getattr(settings, 'VE_PAGOMOVIL_SEND_PROVIDER', 'pagoasap') or '').strip().lower()

    def read(self, owner, user, request):
        return read_pagomovil(owner, user, request)

    def request_of(self, intent, meta=None):
        params = intent.params or {}
        return {'method_id': VE_PAGOMOVIL, 'amount_usd': intent.total_usd, 'meta': meta,
                'amount_local': params.get('exact_ves'),
                **{key: params.get(key) for key in ('cedula', 'phone', 'bank_code', 'holder_name')}}

    def create(self, info, intent):
        from ramps.ve_pagomovil_schema import CreateVePagoMovilSend
        params = intent.params or {}
        return CreateVePagoMovilSend().mutate(
            info, usd_amount=format(intent.total_usd, 'f'), cedula=params.get('cedula'), phone=params.get('phone'),
            bank_code=params.get('bank_code'), beneficiary_name=params.get('holder_name') or None,
            **({'ves_amount': params['exact_ves']} if params.get('exact_ves') else {}))


class BoliviaQrRail(OrderRail):
    """QR Bolivia, provider-neutral in ramps.bolivia_qr."""
    rail = BO_QR

    def provider(self):
        from ramps import bolivia_qr
        return bolivia_qr.provider_name(bolivia_qr.SEND)

    def read(self, owner, user, request):
        return read_bolivia_qr(owner, user, request)

    def request_of(self, intent, meta=None):
        params = intent.params or {}
        return {'method_id': BO_QR, 'code': params.get('qr_text'),
                'amount_local': params.get('bob_amount') or None, 'meta': meta}

    def create(self, info, intent):
        from ramps.bolivia_qr_schema import CreateBoliviaQrSend
        params = intent.params or {}
        return CreateBoliviaQrSend().mutate(
            info, qr_text=params.get('qr_text'), max_usd_amount=format(intent.total_usd, 'f'),
            bob_amount=params.get('bob_amount') or None)


register_order_rail(PagoMovilRail())
register_order_rail(BoliviaQrRail())


def create_order(info, intent):
    """Make the provider order from the intent's own details, through the
    very mutation the manual screen calls (same product rules, same Face
    peek). Returns the order id. Nothing is funded: the owner still claims the
    funding and signs it."""
    out = _rail_of(intent).create(info, intent)
    if not getattr(out, 'success', False) or not getattr(out, 'order_id', None):
        error = getattr(out, 'error', None) or 'No pudimos crear este pago. Intenta de nuevo.'
        from ramps.pagoasap_send import PRICE_MOVED
        # A moved price is a new quote for the same card, not a failed payment.
        refusal = _refuse('quote_changed' if error == PRICE_MOVED else 'rail', error)
        refusal.next_step = getattr(out, 'next_step', None) or ''
        raise refusal
    return str(out.order_id), out


def _order(intent):
    from ramps.models import RampTransaction
    if not intent.order_ref:
        return None
    return RampTransaction.objects.filter(internal_id=intent.order_ref, actor_user_id=intent.user_id).first()


def order_status(intent):
    """(status, order) of a provider order, in the card's words."""
    from ramps import ve_send
    ramp = _order(intent)
    if ramp is None:
        return None, None
    phase = ve_send.view(ramp).get('phase') or ''
    if ramp.status == 'COMPLETED':
        return 'paid', ramp
    if ramp.status == 'FAILED':
        detail = str(getattr(ramp, 'status_detail', '') or '')
        section = ve_send._section(ramp) if getattr(ramp, 'metadata', None) is not None else {}
        funded = any(section.get(key) for key in ('funding_started_at', 'funding_tx_hashes', 'funding_tx_hash',
                                                  'funded_wei'))
        if detail in ve_send.CLOSED_UNFUNDED or (not funded and detail != 'refunded_to_wallet'):
            # Closed without ever being funded: nothing left the wallet (not a failed payment).
            return ('cancelled' if detail == 'cancelled_by_user' else 'expired'), ramp
        if detail == 'refunded_to_wallet' or phase == 'refunded':
            return 'refunded', ramp
        return 'failed', ramp
    if phase in ('payout_failed', 'payout_review') or str(getattr(ramp, 'status_detail', '') or '').startswith(
            'needs_review'):
        return 'under_review', ramp
    if phase in ('preparing', 'awaiting_funding'):
        return 'awaiting_signature', ramp
    return 'paying', ramp


# ---------------------------------------------------------- Confío to Confío

def _confio_recipient(user, request):
    from users.models import Account, User
    raw = str(request.get('recipient') or '').strip().lstrip('@')
    if not raw or len(raw) > 64:
        raise _refuse('no_payee', 'Dime a qué usuario de Confío quieres enviarle (su @usuario).')
    target = User.objects.filter(username__iexact=raw, is_active=True).first()
    if target is None or target.pk == user.pk:
        raise _refuse('no_payee', 'No encontré ese @usuario en Confío.')
    if not Account.objects.filter(user=target, account_type='personal', account_index=0,
                                  deleted_at__isnull=True).exclude(bsc_address__isnull=True).exclude(
                                      bsc_address='').exists():
        raise _refuse('no_payee', 'Esa persona todavía no puede recibir en Confío.')
    return target


def read_confio_send(owner, user, request, *, client=None):
    from users.name_visibility import display_name_for
    if not (getattr(settings, 'CUSD_PLUS_7702_ENABLED', False) and getattr(settings, 'BSC_SEND_ENABLED', False)):
        raise _refuse('rail', 'Los envíos entre cuentas Confío no están disponibles ahora.')
    amount = usd_amount(request.get('amount_usd'))
    if amount is None:
        raise _refuse('no_amount', 'Dime cuántos dólares quieres enviar.')
    target = _confio_recipient(user, request)
    from users import direct_receive
    if direct_receive.is_blocked(target):
        raise _refuse('no_payee', 'Esa persona solo recibe con su propio QR. Pídele su QR y págalo desde Pagar.')
    return {
        'family': 'confio_send', 'destination': None, 'provider': CONFIO,
        # The same rule as everywhere in the app: a short name only once the
        # two have paid each other, the @usuario otherwise.
        'payee_name': _clean(display_name_for(user, target), 140), 'payee_level': _allowed('confio_account'),
        'payee_document': '', 'institution': 'Confío', 'payee_account': f'@{target.username}',
        'amount_exact': True, 'currency': 'USD', 'amount_local': amount, 'minimum_local': None,
        'total_usd': amount, 'fee_usd': Decimal('0.00'), 'estimated_return_usd': Decimal('0.00'),
        'rate': Decimal('1.0000'), 'charge_expires_at': None,
        'params': {'recipient_user_id': target.pk, 'username': target.username},
    }


def reread_confio_send(owner, user, intent):
    params = intent.params or {}
    facts = read_confio_send(owner, user, {'recipient': params.get('username'), 'amount_usd': intent.total_usd})
    if facts['params']['recipient_user_id'] != params.get('recipient_user_id') or any(
            facts[key] != getattr(intent, key) for key in ('payee_name', 'payee_level', 'payee_account')):
        # The @usuario now belongs to someone else, or reads differently.
        raise _refuse('charge_changed', 'El destino cambió desde que lo viste. Revísalo de nuevo.')
    return facts


def create_confio_send(info, intent):
    """Prepare the send through the mutation the Enviar screen calls: the
    server builds and stores the exact batch; the owner signs it. Refused if
    it would cost more than the card showed."""
    from send.schema import PrepareBscSend
    out = PrepareBscSend().mutate(
        info, amount=intent.total_usd, recipient_user_id=str((intent.params or {}).get('recipient_user_id')),
        idempotency_key=f'intent:{intent.internal_id}')
    if not getattr(out, 'success', False) or not getattr(out, 'send_id', None):
        from security.face_step_up import FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP
        error = str(getattr(out, 'error', '') or '')
        codes = {'recipient_not_on_confio': 'Esa persona todavía no puede recibir en Confío.',
                 'rate_limited': 'Hiciste muchos intentos seguidos. Espera un momento.',
                 'insufficient_balance': 'No tienes saldo suficiente para este envío.'}
        # A sentence the send flow wrote for the person (Face, identity) is
        # passed on as it is; a bare code we do not know is not shown.
        message = codes.get(error) or (error if ' ' in error else '') or 'No pudimos preparar este envío.'
        refusal = _refuse('rail', message)
        # Confío Face first: the card stays, the person verifies and taps again.
        refusal.next_step = FACE_STEP_UP_NEXT_STEP if error == FACE_STEP_UP_MESSAGE else ''
        # Nothing was prepared and the card's figures still hold: it stays
        # for another try (after a top-up, a moment later).
        refusal.keep_card = error in ('insufficient_balance', 'rate_limited') or ' ' in error
        raise refusal
    if Decimal(str(out.fee_amount or 0)) > intent.fee_usd or Decimal(str(out.gross_amount or 0)) > intent.total_usd:
        raise _refuse('quote_changed')
    return str(out.send_id), out


def _send_row(intent):
    from send.models import SendTransaction
    if not intent.order_ref:
        return None
    return SendTransaction.objects.filter(internal_id=intent.order_ref, sender_user_id=intent.user_id).first()


def close_created(intent, ref):
    """Undo what a confirmation just created when its intent was taken from
    under it (declared dead and replaced meanwhile): an unfunded order is
    cancelled, an unsigned send is failed. Best effort; True when closed."""
    try:
        if intent.family == 'confio_send':
            from send.bsc_flow import fail_unbroadcast_send
            from send.models import SendTransaction
            send = SendTransaction.objects.filter(internal_id=ref, sender_user_id=intent.user_id).first()
            return send is None or bool(fail_unbroadcast_send(send, 'superseded'))
        from ramps import ve_send
        from ramps.models import RampTransaction
        ramp = RampTransaction.objects.filter(internal_id=ref, actor_user_id=intent.user_id).first()
        if ramp is not None:
            ve_send.cancel(ramp)
        return True
    except Exception:  # noqa: BLE001 - reported, never raised over the refusal
        logger.exception('payment intent: could not close what a superseded confirmation created')
        return False


def retire_unsigned_send(intent):
    """Before a Confío send is quoted again: its earlier send, if it was
    prepared and never signed, is failed (under the same lock a broadcast
    takes). False when it is being broadcast or already left."""
    send = _send_row(intent)
    if send is None or str(send.status) in ('FAILED',):
        return True
    if str(send.status) not in ('PENDING', 'SPONSORING'):
        return False
    from send.bsc_flow import fail_unbroadcast_send
    return bool(fail_unbroadcast_send(send, 'superseded'))


def send_status(intent):
    from send.models import SendTransaction
    if not intent.order_ref:
        return None, None
    send = SendTransaction.objects.filter(internal_id=intent.order_ref, sender_user_id=intent.user_id).first()
    if send is None:
        return None, None
    if str(send.status) in ('PENDING', 'SPONSORING') and timezone.now() - send.created_at > UNSIGNED_SEND_WINDOW:
        # Prepared and never signed: nothing left the wallet, and the card
        # may be quoted again.
        return 'expired', send
    if str(send.status) == 'FAILED' and not (getattr(send, 'transaction_hash', '') or ''):
        # Failed before anything was broadcast (never signed, or superseded
        # by a new quote): nothing left the wallet. Not a failed payment.
        return 'expired', send
    return {'CONFIRMED': 'paid', 'FAILED': 'failed', 'AML_REVIEW': 'under_review', 'PENDING': 'awaiting_signature',
            'SPONSORING': 'awaiting_signature'}.get(str(send.status), 'paying'), send


# ------------------------------------------------------------------ dispatch

def read(owner, user, family, method_id, provider, request, *, client=None):
    """The facts of the card for every family but the exact local charge
    (which payment_intents reads itself)."""
    if family == 'local_transfer':
        return read_transfer(owner, user, method_id, request, client=client)
    if family == 'confio_send':
        return read_confio_send(owner, user, request)
    rail = order_rail(method_id, provider)
    if rail is None:
        raise _refuse('rail', 'Este medio de pago no está disponible ahora.')
    facts = rail.read(owner, user, request)
    facts.update(family='ramp_order', provider=provider)
    return facts
