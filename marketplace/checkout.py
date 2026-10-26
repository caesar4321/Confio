"""Comprar checkout: turn a product + delivery choice into a signed, escrow-
ready Order (status 'draft') and the exact batch the buyer signs.

Gates, in order: escrow configured, the JWT's account (personal or
business; a business needs send_funds), buyer identity-verified, product
buyable from a live city, not your own store, delivery rules (other cities
only when the store ships there AND the buyer acknowledged the larger fee), a
fresh quote within the escrow's ON-CHAIN per-order and open limits, enough
dollars (cUSD, or cUSD+ normalized inside the batch), and Confío Face.
"""

import logging
import time
import uuid
from decimal import Decimal

from django.db import transaction

from . import escrow
from .models import MINIMUM_AGE, MarketplaceCity, Order, Product
from .permissions import AccountError, account_for
from .pricing import quote

logger = logging.getLogger(__name__)

DEPOSIT_AUTH_TTL_S = 20 * 60
# A draft is reused only while its authorization has at least this long left.
REUSE_MIN_REMAINING_S = 5 * 60
MAX_QUANTITY = 20


class CheckoutError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def jwt_account(user, jwt_ctx):
    """The JWT's account (personal or business), or CheckoutError."""
    try:
        return account_for(user, jwt_ctx)
    except AccountError as exc:
        raise CheckoutError(exc.code) from exc


def local_today(country_code: str | None):
    """Today's date where the sale happens (the store's country). An
    unknown country takes the furthest-west date, so a birthday never
    arrives early."""
    return local_now(country_code).date()


def buyer_age(user, today):
    """Whole years since the birth date on the buyer's primary verified
    document, or None when there is none."""
    from security.identity_status import current_document
    doc = current_document(user)
    born = getattr(doc, 'verified_date_of_birth', None)
    if born is None:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def is_of_age(user, country_code: str | None = None) -> bool:
    """Adults-only purchases: an unknown age is never an adult."""
    age = buyer_age(user, local_today(country_code))
    return age is not None and age >= MINIMUM_AGE


def category_is_age_restricted(key: str) -> bool:
    """Live (uncached) read: payment authorization must never trail an admin flag."""
    from .models import MarketplaceCategory
    return MarketplaceCategory.objects.filter(key=key, age_restricted=True).exists()


# Ley 259 art. 17: no alcohol sold 03:00–09:00 (local time). Municipal
# hours may be stricter; this is the national floor.
ALCOHOL_QUIET_HOURS = (3, 9)


def local_now(country_code: str | None):
    from zoneinfo import ZoneInfo
    from django.utils import timezone
    from users.cashflow import TIMEZONE_BY_PHONE_COUNTRY
    name = TIMEZONE_BY_PHONE_COUNTRY.get((country_code or '').upper(), 'Etc/GMT+12')
    return timezone.now().astimezone(ZoneInfo(name))


def ley_seca_error(country_code: str | None, cities) -> str | None:
    """'alcohol_paused' when any of these cities (or its delivery area) is under a ley seca. Names
    match the way delivery does (case, accents, spacing). A name Comprar does
    not know is paused whenever any city of the country is: a nationwide ley
    seca must not have a way around it."""
    rows = list(MarketplaceCity.objects.filter(country_code=(country_code or '').strip().upper())
                .values_list('city', 'alcohol_sales_paused', 'delivery_area'))
    if not any(p for _, p, _ in rows):
        return None
    # A pause covers its whole delivery area: a "La Paz" order may carry a
    # pin in El Alto (one area), so the label alone cannot clear it.
    paused_areas = {a for _, p, a in rows if p and a}
    paused = {_city_key(c) for c, p, a in rows if p or (a and a in paused_areas)}
    known = {_city_key(c) for c, _, _ in rows}
    for name in cities:
        # A blank (or symbols-only) name is unknown too, never a free pass.
        key = _city_key(name)
        if key in paused or key not in known:
            return 'alcohol_paused'
    return None


def alcohol_window_error(country_code: str | None, cities) -> str | None:
    """When alcohol may not be sold right now, regardless of buyer: the
    national quiet hours, or a "ley seca" pause on any of these cities."""
    start, end = ALCOHOL_QUIET_HOURS
    if start <= local_now(country_code).hour < end:
        return 'alcohol_hours'
    return ley_seca_error(country_code, cities)


def alcohol_sale_error(user, store, delivery_city: str = '') -> str | None:
    """Everything an adults-only sale needs beyond the buyer's age: the
    store's valid licence, the hour, and no ley seca at either end."""
    if not store.alcohol_license_valid():
        return 'store_license_required'
    return alcohol_window_error(store.country_code, [store.city, delivery_city])


def ship_alcohol_error(order) -> str | None:
    """'alcohol_paused' when an adults-only order would ship into or out of a
    city under ley seca; else None."""
    if not order.age_restricted:
        return None
    return ley_seca_error(order.store.country_code, [order.store.city, order.delivery_city])


def deposit_age_error(user, order) -> str | None:
    """The adults-only rules again when the deposit is fetched or submitted,
    on whoever pays (e.g. another employee of the buying business): age,
    licence, hour and ley seca. None when the order may be paid."""
    needs = order.age_restricted or category_is_age_restricted(order.product.category)
    if needs and not is_of_age(user, order.store.country_code):
        return 'age_required'
    if needs:
        sale_error = alcohol_sale_error(user, order.store, order.delivery_city)
        if sale_error:
            return sale_error
    if needs and not order.age_restricted:
        # Flagged after checkout: the order is adults-only from now on, so
        # the seller's notice and order view carry the ID handover rule.
        Order.objects.filter(pk=order.pk).update(age_restricted=True)
        order.age_restricted = True
    return None


def city_for(country_code: str, city: str):
    return MarketplaceCity.objects.filter(country_code=country_code, city__iexact=city.strip()).first()


def _city_key(name: str) -> str:
    """A city name as compared: case, accents and spacing never make another
    city ("La  Paz", "la paz", "Córdoba"/"Cordoba"). Same-city delivery is
    charged, so a spelling must not turn it into "another city"."""
    import unicodedata
    folded = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode()
    return ' '.join(folded.casefold().split())


def area_city_keys(country_code: str, city: str) -> set:
    """The (normalized) cities that share `city`'s delivery area, itself
    included: La Paz and El Alto are one area."""
    key = _city_key(city)
    rows = list(MarketplaceCity.objects.filter(country_code=(country_code or '').strip().upper())
                .values_list('city', 'delivery_area'))
    area = next((a for c, a in rows if _city_key(c) == key and a), '')
    if not area:
        return {key}
    return {_city_key(c) for c, a in rows if a == area} | {key}


def area_cities(country_code: str, city: str) -> list:
    """The MarketplaceCity rows sharing `city`'s delivery area (itself first)."""
    country = (country_code or '').strip().upper()
    me = next((c for c in MarketplaceCity.objects.filter(country_code=country)
               if _city_key(c.city) == _city_key(city)), None)
    if me is None:
        return []
    if not me.delivery_area:
        return [me]
    return [me] + list(MarketplaceCity.objects.filter(country_code=country, delivery_area=me.delivery_area)
                       .exclude(pk=me.pk))


def area_is_live(country_code: str, city: str) -> bool:
    """Sells when this city, or any city of its delivery area, is live: an El
    Alto store sells with La Paz."""
    return any(c.is_live for c in area_cities(country_code, city))


def live_city_names(country_code: str) -> list:
    """Cities whose stores sell: live ones and every city sharing an area with one."""
    rows = list(MarketplaceCity.objects.filter(country_code=(country_code or '').strip().upper()))
    live_areas = {c.delivery_area for c in rows if c.is_live and c.delivery_area}
    return [c.city for c in rows if c.is_live or (c.delivery_area and c.delivery_area in live_areas)]


def clean_pin(latitude, longitude):
    """(lat, lng) as 6-decimal Decimals, None without a pin, or CheckoutError."""
    from decimal import InvalidOperation

    if latitude is None and longitude is None:
        return None
    try:
        lat = Decimal(str(latitude)).quantize(Decimal('0.000001'))
        lng = Decimal(str(longitude)).quantize(Decimal('0.000001'))
    except (InvalidOperation, TypeError, ValueError):
        raise CheckoutError('bad_location_pin')
    if not (lat.is_finite() and lng.is_finite() and -90 <= lat <= 90 and -180 <= lng <= 180):
        raise CheckoutError('bad_location_pin')
    return lat, lng


def check_delivery_place(address: str, note: str, pin) -> None:
    """A courier needs a written address OR a map pin with a short reference
    ("puerta verde frente a la tienda"): written addresses often don't exist."""
    if len((address or '').strip()) >= 8:
        return
    if pin is not None and len((note or '').strip()) >= 4:
        return
    raise CheckoutError('delivery_address_required')


def _km(lat1, lng1, lat2, lng2) -> float:
    import math
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# How far from its country's known cities a pin may be and still count as in
# the country (Bolivia is ~1,500 km across; this only stops another country).
COUNTRY_REACH_KM = 800


def pin_in_destination(country_code: str, city: str, pin) -> bool:
    """For "another city": a known destination city must contain the pin
    (its radius, doubled for outskirts); otherwise the pin must at least be in
    the store's country (near one of its known cities)."""
    lat, lng = float(pin[0]), float(pin[1])
    rows = [c for c in MarketplaceCity.objects.filter(country_code=(country_code or '').strip().upper())
            if c.latitude is not None and c.longitude is not None]
    if not rows:
        return True
    known = next((c for c in rows if _city_key(c.city) == _city_key(city)), None)
    if known is not None:
        return _km(lat, lng, float(known.latitude), float(known.longitude)) <= 2 * (known.radius_km or 40)
    return any(_km(lat, lng, float(c.latitude), float(c.longitude)) <= COUNTRY_REACH_KM for c in rows)


def pin_in_area(country_code: str, city: str, pin) -> bool:
    """Whether the pin falls inside any city of `city`'s delivery area (each
    city's center + radius). Unknown geometry never refuses."""
    import math

    cities = [c for c in area_cities(country_code, city) if c.latitude is not None and c.longitude is not None]
    if not cities:
        return True
    lat, lng = float(pin[0]), float(pin[1])
    for c in cities:
        dlat, dlng = math.radians(lat - float(c.latitude)), math.radians(lng - float(c.longitude))
        a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(float(c.latitude)))
             * math.sin(dlng / 2) ** 2)
        if 6371 * 2 * math.asin(math.sqrt(a)) <= (c.radius_km or 40):
            return True
    return False


def is_outside_city(store, delivery_country: str, delivery_city: str) -> bool:
    """Outside the store's delivery AREA (not just its city name)."""
    return ((delivery_country or '').strip().upper() != store.country_code
            or _city_key(delivery_city) not in area_city_keys(store.country_code, store.city))


def delivery_terms(store, delivery_country: str, delivery_city: str) -> dict:
    outside = is_outside_city(store, delivery_country, delivery_city)
    city = city_for(store.country_code, store.city)
    return {
        'outside_city': outside,
        # None = no estimate for this city (outside it, or none set): "a coordinar".
        'estimate_local': None if outside or city is None else city.delivery_estimate,
        'currency': city.currency_code if city else '',
        'partner': city.delivery_partner if city else '',
        'ships_outside_city': store.outside_delivery_price_usd is not None,
    }


def checkout_quote(product, quantity: int, delivery_country: str, delivery_city: str) -> dict:
    if not (1 <= quantity <= MAX_QUANTITY):
        raise CheckoutError('bad_quantity')
    # Priced in dollars: price × quantity plus the store's delivery price, no
    # exchange rate. Another city is coordinated with the store (not included).
    terms = delivery_terms(product.store, delivery_country, delivery_city)
    store = product.store
    if (delivery_country or '').strip().upper() != store.country_code:
        # The flat "other cities" price is domestic: another country is never quoted.
        raise CheckoutError('store_country_only')
    if not terms['outside_city']:
        delivery = store.delivery_price_usd
    elif store.outside_delivery_price_usd is not None:
        # Anywhere else in the country: the store's one flat price, in the total.
        delivery = store.outside_delivery_price_usd
    else:
        raise CheckoutError('store_city_only')
    q = quote(product.price_usd, quantity, delivery)
    return {'quote': q, **terms}


def prepare_order(user, jwt_ctx, *, product_id, quantity: int, delivery_country: str,
                  delivery_city: str, delivery_address: str, delivery_phone: str,
                  delivery_note: str = '', outside_city_ack: bool = False,
                  delivery_latitude=None, delivery_longitude=None):
    """Create a draft Order with the server's deposit authorization. Returns
    (order, calls, intent_id_hex). Raises CheckoutError."""
    from cusd_plus import sponsor_7702

    if not escrow.enabled():
        raise CheckoutError('marketplace_disabled')
    account = jwt_account(user, jwt_ctx)
    if not user.is_identity_verified:
        raise CheckoutError('identity_required')

    product = Product.objects.select_related('store', 'store__owner_account').filter(
        pk=product_id, deleted_at__isnull=True).first()
    # Listing eligibility only. Stock is checked at reservation (or is already
    # held by the buyer's reusable draft), below.
    if product is None or product.status != 'active' or not product.store.is_open:
        raise CheckoutError('product_unavailable')
    # Read live, never from the 60s cache: a category flagged a moment ago
    # must already gate the authorization issued now.
    age_restricted = category_is_age_restricted(product.category)
    if age_restricted and not is_of_age(user, product.store.country_code):
        raise CheckoutError('age_required')
    if age_restricted:
        sale_error = alcohol_sale_error(user, product.store, delivery_city)
        if sale_error:
            raise CheckoutError(sale_error)
    # A deposit for this purchase is still settling: a second order now is how
    # an uncertain first payment turns into paying twice.
    if Order.objects.filter(buyer_account=account, product=product, status='depositing').exists():
        raise CheckoutError('payment_in_progress')
    store = product.store
    # Nobody buys from their own store, from any of their accounts: the
    # store's account owner (a person, or a business's owner) is excluded.
    # Employees may buy from their employer like anyone else.
    # Nor between two accounts of the same owner (an employee buying for
    # business A from A's owner's other store).
    if (store.owner_account_id == account.id or store.owner_account.user_id == user.id
            or store.owner_account.user_id == account.user_id):
        raise CheckoutError('own_store')
    city = city_for(store.country_code, store.city)
    if city is None or not area_is_live(store.country_code, store.city):
        raise CheckoutError('city_not_live')
    delivery_address = (delivery_address or '').strip()
    delivery_phone = ''.join(ch for ch in (delivery_phone or '') if ch.isdigit() or ch == '+')
    pin = clean_pin(delivery_latitude, delivery_longitude)
    check_delivery_place(delivery_address, delivery_note, pin)
    if len(delivery_phone) < 7:
        raise CheckoutError('delivery_phone_required')
    # Another city is priced (the store's flat price, in the total) or refused
    # (store_city_only) by checkout_quote; nothing is left to acknowledge.
    # `outside_city_ack` stays accepted for older builds and is ignored.
    terms = checkout_quote(product, quantity, delivery_country, delivery_city)
    q = terms['quote']
    # Priced as the store's own area: the pin must be in it (typing "El Alto"
    # with a pin in another city would otherwise pay the area price).
    if pin is not None and not terms['outside_city'] and not pin_in_area(store.country_code, store.city, pin):
        raise CheckoutError('pin_outside_area')
    # Another city: the pin must be in that city, or at least in the country
    # (the flat "other cities" price is domestic).
    if pin is not None and terms['outside_city'] and not pin_in_destination(store.country_code, delivery_city, pin):
        raise CheckoutError('pin_outside_area')
    # The limits live in ONE place: the escrow contract (the Safe sets them).
    try:
        max_order, max_open, open_principal = escrow.token_limits()
    except escrow.EscrowError as exc:
        raise CheckoutError(exc.code) from exc
    if max_order == 0:
        raise CheckoutError('marketplace_disabled')
    if q.amount_wei > max_order:
        raise CheckoutError('order_too_large')
    if open_principal + q.amount_wei > max_open:
        raise CheckoutError('marketplace_busy')

    buyer_addr = (account.bsc_address or '').lower()
    merchant_addr = (store.owner_account.bsc_address or '').lower()
    if not buyer_addr:
        raise CheckoutError('no_bsc_address')
    if not merchant_addr or store.owner_account.deleted_at is not None:
        raise CheckoutError('store_cannot_receive')
    if merchant_addr == buyer_addr:
        raise CheckoutError('own_store')

    delivery = dict(
        delivery_country=delivery_country.upper(), delivery_city=delivery_city.strip(),
        # The courier estimate described the old "pay the courier on arrival"
        # orders; delivery is now the store's price inside the total, so a new
        # order records none (0 + none = free; 0 + an estimate = an old order).
        delivery_outside_city=terms['outside_city'], delivery_estimate_local=None,
        delivery_currency=terms['currency'],
        delivery_address=delivery_address[:300], delivery_phone=delivery_phone[:20],
        delivery_latitude=pin[0] if pin else None, delivery_longitude=pin[1] if pin else None,
        delivery_note=(delivery_note or '').strip()[:300],
        age_restricted=age_restricted)

    # Re-opening checkout with the same terms reuses the open draft: its signed
    # authorization (and stock reservation) is still good. Only what is not
    # signed changes — delivery details, and the funding leg, which depends on
    # balances right now.
    reusable = Order.objects.filter(
        buyer=user, buyer_account=account, product=product, status='draft', quantity=quantity,
        unit_price_usd=product.price_usd, delivery_usd=q.delivery_usd, buyer_address=buyer_addr,
        merchant_address=merchant_addr, stock_reserved=True,
        deposit_deadline__gte=int(time.time()) + REUSE_MIN_REMAINING_S,
    ).order_by('-created_at').first()
    if reusable is not None:
        # Adults-only never loosens on a reused draft (its stored batch may
        # already be in a payer's hands).
        delivery['age_restricted'] = reusable.age_restricted or age_restricted
        try:
            funding = escrow.funding_leg(buyer_addr, int(reusable.amount_wei))
        except escrow.EscrowError as exc:
            raise CheckoutError(exc.code) from exc
        for field, value in delivery.items():
            setattr(reusable, field, value)
        calls = ([funding] if funding else []) + [escrow.approve_call(reusable),
                                                  escrow.deposit_call(reusable)]
        reusable.deposit_calls = escrow._normalize(calls)
        # Its authorization was issued after Confío Face; handing the same one
        # back creates nothing new to execute.
        reusable.save(update_fields=[*delivery.keys(), 'deposit_calls', 'updated_at'])
        return reusable, reusable.deposit_calls, sponsor_7702.intent_id_hex('market_deposit', reusable.pk)

    try:
        funding = escrow.funding_leg(buyer_addr, q.amount_wei)
    except escrow.EscrowError as exc:
        raise CheckoutError(exc.code) from exc

    public_id = uuid.uuid4()
    order_id32 = escrow.new_order_id32(public_id)
    # Confío Face BEFORE anything executable exists: peek (the client runs the
    # check and calls again), then consume — bound to these exact terms —
    # right before signing.
    face_terms = dict(order_id32=order_id32, buyer=buyer_addr, merchant=merchant_addr,
                      amount_wei=q.amount_wei, amount_usd=q.amount_usd)
    blocked = escrow.deposit_step_up(user, **face_terms)
    if blocked:
        raise CheckoutError(blocked)
    blocked = escrow.deposit_step_up(user, consume=True, **face_terms)
    if blocked:
        raise CheckoutError(blocked)
    token = escrow.token_address()
    deadline = int(time.time()) + DEPOSIT_AUTH_TTL_S
    digest = escrow.deposit_digest(order_id32, buyer_addr, merchant_addr, token,
                                   q.amount_wei, q.fee_bps, deadline)
    signature, signer = escrow.sign_deposit(digest)

    with transaction.atomic():
        # One open checkout per buyer and product: a second prepare supersedes
        # the first in the app. Its authorization stays spendable on chain
        # until its deadline, so it keeps its stock reservation and the keeper
        # reconciles it (resurrected if spent, released once it expired unspent).
        Order.objects.filter(buyer=user, buyer_account=account, product=product,
                             status='draft').update(status='cancelled')
        if not escrow.reserve_stock(product.pk, quantity):
            raise CheckoutError('out_of_stock')
        order = Order.objects.create(
            public_id=public_id, order_id32=order_id32, buyer=user, buyer_account=account,
            buyer_address=buyer_addr, store=store, merchant_address=merchant_addr,
            product=product, product_title=product.title, unit_price_usd=q.unit_price_usd,
            delivery_usd=q.delivery_usd,
            quantity=quantity, amount_usd=q.amount_usd, amount_wei=q.amount_wei,
            token_address=token, fee_bps=q.fee_bps, **delivery,
            deposit_deadline=deadline, deposit_signature=signature, deposit_signer=signer,
            stock_reserved=True,
        )
        calls = ([funding] if funding else []) + [escrow.approve_call(order), escrow.deposit_call(order)]
        order.deposit_calls = escrow._normalize(calls)
        order.save(update_fields=['deposit_calls'])

    intent_id = sponsor_7702.intent_id_hex('market_deposit', order.pk)
    return order, order.deposit_calls, intent_id
