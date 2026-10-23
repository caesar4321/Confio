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
from .models import MarketplaceCity, Order, Product
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


def city_for(country_code: str, city: str):
    return MarketplaceCity.objects.filter(country_code=country_code, city__iexact=city.strip()).first()


def _city_key(name: str) -> str:
    """A city name as compared: case, accents and spacing never make another
    city ("La  Paz", "la paz", "Córdoba"/"Cordoba"). Same-city delivery is
    charged, so a spelling must not turn it into "another city"."""
    import unicodedata
    folded = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode()
    return ' '.join(folded.casefold().split())


def is_outside_city(store, delivery_country: str, delivery_city: str) -> bool:
    return ((delivery_country or '').strip().upper() != store.country_code
            or _city_key(delivery_city) != _city_key(store.city))


def delivery_terms(store, delivery_country: str, delivery_city: str) -> dict:
    outside = is_outside_city(store, delivery_country, delivery_city)
    city = city_for(store.country_code, store.city)
    return {
        'outside_city': outside,
        # None = no estimate for this city (outside it, or none set): "a coordinar".
        'estimate_local': None if outside or city is None else city.delivery_estimate,
        'currency': city.currency_code if city else '',
        'partner': city.delivery_partner if city else '',
        'ships_outside_city': store.ships_outside_city,
    }


def checkout_quote(product, quantity: int, delivery_country: str, delivery_city: str) -> dict:
    if not (1 <= quantity <= MAX_QUANTITY):
        raise CheckoutError('bad_quantity')
    # Priced in dollars: price × quantity plus the store's delivery price, no
    # exchange rate. Another city is coordinated with the store (not included).
    terms = delivery_terms(product.store, delivery_country, delivery_city)
    delivery = Decimal('0') if terms['outside_city'] else product.store.delivery_price_usd
    q = quote(product.price_usd, quantity, delivery)
    return {'quote': q, **terms}


def prepare_order(user, jwt_ctx, *, product_id, quantity: int, delivery_country: str,
                  delivery_city: str, delivery_address: str, delivery_phone: str,
                  delivery_note: str = '', outside_city_ack: bool = False):
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
    if city is None or not city.is_live:
        raise CheckoutError('city_not_live')
    delivery_address = (delivery_address or '').strip()
    delivery_phone = ''.join(ch for ch in (delivery_phone or '') if ch.isdigit() or ch == '+')
    if len(delivery_address) < 8:
        raise CheckoutError('delivery_address_required')
    if len(delivery_phone) < 7:
        raise CheckoutError('delivery_phone_required')
    terms = checkout_quote(product, quantity, delivery_country, delivery_city)
    if terms['outside_city']:
        if not store.ships_outside_city:
            raise CheckoutError('store_city_only')
        if not outside_city_ack:
            raise CheckoutError('outside_city_ack_required')
    q = terms['quote']
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
        delivery_note=(delivery_note or '').strip()[:300])

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
