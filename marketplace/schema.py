"""
GraphQL for Comprar (marketplace).

Browsing is open to any signed-in user and defaults to the client's GPS city;
any country/city can be browsed. Buying and selling ride the JWT's account,
personal or business, by a Didit-verified user; on a business account the
employee needs the action's permission (marketplace/permissions.py).

Delivery addresses are private to the order's two sides (buyer account and
store account, with view_transactions on a business).
"""

import logging

import graphene
from django.conf import settings
from django.db.models import Avg, Count, Q
from graphql_jwt.decorators import login_required

from . import escrow
from .checkout import CheckoutError, checkout_quote, jwt_account, prepare_order
from .permissions import (ACTION_PERMISSIONS, BUY, SHIP, STORE_ADMIN, VIEW_ORDERS, can_act_for,
                          order_actor_account)
from .models import (COUNTRY_CHOICES, MarketplaceCity, active_categories, active_category_keys, category_label,
                     Order, OrderRating, Product, Store)
from .moderation import MAX_PHOTOS, pending_prefix, start_review
from .pricing import suggested_delivery_usd
from .checkout import area_is_live
from .address_book import DeleteDeliveryAddress, SaveDeliveryAddress  # noqa: E402

logger = logging.getLogger(__name__)

VALID_COUNTRY_CODES = {code for code, _ in COUNTRY_CHOICES}
ALLOWED_IMAGE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
PAGE_MAX = 50


def _user(info):
    user = info.context.user
    return user if user and user.is_authenticated else None


def _jwt(info, permission=None):
    """JWT context; on a business account the employee must hold `permission`
    (None for the gate itself returns a context only if access is valid)."""
    from users.jwt_context import get_jwt_business_context_with_validation
    return get_jwt_business_context_with_validation(info, required_permission=permission)


def _ctx(info, permission=None):
    """(user, account) for the JWT's account, or raises CheckoutError."""
    user = _user(info)
    if not user:
        raise CheckoutError('not_authenticated')
    ctx = _jwt(info, permission)
    if ctx is None:
        raise CheckoutError('permission_denied')
    return user, jwt_account(user, ctx)


# ── types ───────────────────────────────────────────────────────────────

class MarketplaceCityType(graphene.ObjectType):
    country_code = graphene.String()
    city = graphene.String()
    currency_code = graphene.String()
    is_live = graphene.Boolean()
    delivery_estimate = graphene.String(description='Same-city estimate, local currency')
    delivery_partner = graphene.String()
    store_count = graphene.Int()
    suggested_delivery_usd = graphene.String(description="Pre-fills a new store's delivery price")
    latitude = graphene.Float(description="The city's center (where a delivery map opens)")
    longitude = graphene.Float()


class LocalReferenceType(graphene.ObjectType):
    """A display-only "≈" amount in local currency. Prices are in US dollars;
    this never quotes or changes a payment, and is null without a fresh rate."""
    amount = graphene.String()
    currency = graphene.String()


def _reference(amount_usd, country_code):
    from .pricing import reference_local
    ref = reference_local(amount_usd, country_code)
    return LocalReferenceType(amount=str(ref[0]), currency=ref[1]) if ref else None


class ReferenceRateType(graphene.ObjectType):
    currency = graphene.String()
    local_per_usd = graphene.String()


class MarketplaceCountryType(graphene.ObjectType):
    country_code = graphene.String()
    store_count = graphene.Int()


class MarketplaceCategoryType(graphene.ObjectType):
    key = graphene.String()
    label = graphene.String()
    group = graphene.String(description='Heading the pickers group it under')
    icon = graphene.String(description='Feather icon name')
    product_count = graphene.Int(description='Live listings in the given city (when asked)')


class MarketplaceAgeRulesType(graphene.ObjectType):
    minimum_age = graphene.Int(required=True)
    category_keys = graphene.List(graphene.NonNull(graphene.String), required=True,
                                  description='Adults-only categories (alcoholic beverages)')
    viewer_of_age = graphene.Boolean(required=True,
                                     description="The viewer's verified ID shows legal age")


class MarketplaceStoreType(graphene.ObjectType):
    id = graphene.ID()
    name = graphene.String()
    description = graphene.String()
    country_code = graphene.String()
    city = graphene.String()
    ships_outside_city = graphene.Boolean()
    status = graphene.String()
    is_open = graphene.Boolean()
    avg_rating = graphene.Float()
    rating_count = graphene.Int()
    completed_orders = graphene.Int()
    owner_display_name = graphene.String()
    delivery_price_usd = graphene.String(description='Same-city delivery the buyer pays, added to the order')
    outside_delivery_price_usd = graphene.String(description='Delivery to anywhere else in the country; null = not offered')

    @staticmethod
    def from_model(store):
        stats = store.ratings.aggregate(avg=Avg('rating'), count=Count('id'))
        owner = store.owner
        return MarketplaceStoreType(
            id=store.pk, name=store.name, description=store.description,
            country_code=store.country_code, city=store.city,
            ships_outside_city=store.ships_outside_city, status=store.status,
            is_open=store.is_open, avg_rating=stats['avg'], rating_count=stats['count'],
            completed_orders=store.orders.filter(status='released').count(),
            owner_display_name=(owner.first_name or owner.username or '').strip(),
            delivery_price_usd=str(store.delivery_price_usd),
            outside_delivery_price_usd=(str(store.outside_delivery_price_usd)
                                        if store.outside_delivery_price_usd is not None else None),
        )


class MarketplaceProductType(graphene.ObjectType):
    id = graphene.ID()
    title = graphene.String()
    description = graphene.String()
    category = graphene.String()
    category_label = graphene.String()
    price_usd = graphene.String(description='The price, in US dollars')
    reference_local = graphene.Field(LocalReferenceType, description='≈ in the store country currency')
    stock = graphene.Int()
    stock_revision = graphene.Int(description='Seller only')
    photo_urls = graphene.List(graphene.String)
    status = graphene.String()
    rejection_reason = graphene.String(description='Seller only')
    is_buyable = graphene.Boolean()
    store = graphene.Field(MarketplaceStoreType)

    @staticmethod
    def from_model(product, *, for_owner=False, with_store=True):
        return MarketplaceProductType(
            id=product.pk, title=product.title, description=product.description,
            category=product.category, category_label=category_label(product.category),
            price_usd=str(product.price_usd),
            reference_local=_reference(product.price_usd, product.store.country_code),
            stock=product.stock,
            photo_urls=list(product.photo_urls or []), status=product.status,
            rejection_reason=product.rejection_reason if for_owner else None,
            stock_revision=product.stock_revision if for_owner else None,
            is_buyable=product.is_buyable,
            store=MarketplaceStoreType.from_model(product.store) if with_store else None,
        )


class MarketplaceOrderType(graphene.ObjectType):
    id = graphene.ID(description='Public order id (UUID)')
    role = graphene.String(description="'buyer' or 'merchant' for the requester")
    status = graphene.String()
    pending_action = graphene.String()
    product_id = graphene.ID()
    product_title = graphene.String()
    product_photo_url = graphene.String()
    store = graphene.Field(MarketplaceStoreType)
    quantity = graphene.Int()
    unit_price_usd = graphene.String()
    delivery_usd = graphene.String(description='Included in amountUsd')
    amount_usd = graphene.String()
    reference_local = graphene.Field(LocalReferenceType, description='≈ of amountUsd, current rate')
    delivery_currency = graphene.String()
    fee_usd = graphene.String(description='Merchant only')
    merchant_net_usd = graphene.String(description='Merchant only')
    delivery_city = graphene.String()
    delivery_country = graphene.String()
    delivery_outside_city = graphene.Boolean()
    delivery_estimate_local = graphene.String()
    delivery_address = graphene.String()
    delivery_latitude = graphene.Float(description='Sides of the order only, like the address')
    delivery_longitude = graphene.Float()
    delivery_phone = graphene.String()
    delivery_note = graphene.String()
    buyer_display_name = graphene.String()
    tracking_reference = graphene.String()
    ship_by = graphene.DateTime()
    release_at = graphene.DateTime()
    disputed_at = graphene.DateTime()
    created_at = graphene.DateTime()
    settled_at = graphene.DateTime()
    available_actions = graphene.List(graphene.String)
    rating = graphene.Int()
    last_tx_hash = graphene.String()

    @staticmethod
    def from_model(order, user, account):
        from django.utils import timezone

        role = 'buyer' if order.buyer_account_id == account.id else 'merchant'
        actions = []
        if order.status == 'draft' and role == 'buyer':
            actions = ['deposit']
        elif not order.pending_action:
            now = timezone.now()
            side = order.buyer_account if role == 'buyer' else order.store.owner_account
            for action, allowed in escrow.ALLOWED_FROM.items():
                if order.status not in allowed or escrow.ACTIONS[action][1] != role:
                    continue
                if not can_act_for(user, side, ACTION_PERMISSIONS[action]):
                    continue
                if action == 'reclaim' and (order.ship_by is None or now <= order.ship_by):
                    continue
                if action == 'ship' and order.ship_by and now > order.ship_by:
                    continue
                if action == 'dispute' and order.status == 'shipped' and order.release_at \
                        and now >= order.release_at:
                    continue
                actions.append(action)
        merchant = role == 'merchant'
        fee = order.fee_usd
        rating = getattr(order, 'rating', None) if order.status == 'released' else None
        return MarketplaceOrderType(
            id=str(order.public_id), role=role, status=order.status,
            pending_action=order.pending_action or None, product_id=order.product_id,
            product_title=order.product_title,
            product_photo_url=(order.product.photo_urls or [None])[0],
            store=MarketplaceStoreType.from_model(order.store), quantity=order.quantity,
            unit_price_usd=str(order.unit_price_usd), delivery_usd=str(order.delivery_usd),
            amount_usd=str(order.amount_usd),
            reference_local=_reference(order.amount_usd, order.store.country_code),
            delivery_currency=order.delivery_currency or None,
            fee_usd=f'{fee:.2f}' if merchant else None,
            merchant_net_usd=f'{order.amount_usd - fee:.2f}' if merchant else None,
            delivery_city=order.delivery_city, delivery_country=order.delivery_country,
            delivery_outside_city=order.delivery_outside_city,
            delivery_estimate_local=(str(order.delivery_estimate_local)
                                     if order.delivery_estimate_local is not None else None),
            delivery_address=order.delivery_address, delivery_phone=order.delivery_phone,
            delivery_latitude=(float(order.delivery_latitude) if order.delivery_latitude is not None else None),
            delivery_longitude=(float(order.delivery_longitude) if order.delivery_longitude is not None else None),
            delivery_note=order.delivery_note,
            buyer_display_name=(order.buyer.first_name or 'Cliente') if merchant else None,
            tracking_reference=order.tracking_reference, ship_by=order.ship_by,
            release_at=order.release_at, disputed_at=order.disputed_at,
            created_at=order.created_at, settled_at=order.settled_at,
            available_actions=actions, rating=rating.rating if rating else None,
            last_tx_hash=order.last_tx_hash or None,
        )


class CheckoutQuoteType(graphene.ObjectType):
    unit_price_usd = graphene.String()
    product_usd = graphene.String(description='Unit price × quantity')
    delivery_usd = graphene.String(description="The store's delivery price; 0 outside its city (coordinated)")
    amount_usd = graphene.String(description='What the buyer pays, in US dollars: product + delivery')
    reference_local = graphene.Field(LocalReferenceType, description='≈ of amountUsd')
    delivery_currency = graphene.String()
    outside_city = graphene.Boolean()
    ships_outside_city = graphene.Boolean()
    delivery_estimate_local = graphene.String(description='Null when outside the store city')
    delivery_partner = graphene.String()


class MarketCallType(graphene.ObjectType):
    """One call of the sponsored 7702 batch (server-built; the client signs
    exactly these and nothing else)."""
    to = graphene.String()
    value_wei = graphene.String()
    data = graphene.String()


class MarketAuthorizationInput(graphene.InputObjectType):
    """A signed EIP-7702 authorization tuple (first use only)."""
    chain_id = graphene.Int(required=True)
    address = graphene.String(required=True)
    nonce = graphene.String(required=True)
    y_parity = graphene.Int(required=True)
    r = graphene.String(required=True)
    s = graphene.String(required=True)


class PhotoUploadType(graphene.ObjectType):
    url = graphene.String()
    key = graphene.String()
    method = graphene.String()
    fields = graphene.JSONString()
    expires_in = graphene.Int()


# ── queries ─────────────────────────────────────────────────────────────

def _visible_products():
    return Product.objects.filter(
        deleted_at__isnull=True, status='active', stock__gt=0,
        store__deleted_at__isnull=True, store__status='active',
    ).select_related('store', 'store__owner')


def _area_city_q(country_code: str, city: str, field: str = 'store__city') -> Q:
    """Matches any city of `city`'s delivery area (La Paz + El Alto), so
    listings, category counts and store counts follow where couriers go."""
    from .checkout import area_cities
    names = [c.city for c in area_cities(country_code, city)] or [(city or '').strip()]
    q = Q()
    for name in names:
        q |= Q(**{f'{field}__iexact': name})
    return q


def _selling_stores():
    """Open stores with at least one live listing — what the pickers count
    and rank by (a store with nothing to buy is not "a place to shop")."""
    return Store.objects.filter(
        deleted_at__isnull=True, status='active',
        products__status='active', products__deleted_at__isnull=True, products__stock__gt=0)


def _orders_for(account):
    """Orders where the JWT's account is a side (data isolation per account)."""
    return Order.objects.select_related(
        'store', 'store__owner', 'store__owner_account', 'product', 'buyer', 'buyer_account',
    ).filter(Q(buyer_account=account) | Q(store__owner_account=account)).exclude(status='cancelled')


class StoreReviewType(graphene.ObjectType):
    id = graphene.ID()
    rating = graphene.Int()
    comment = graphene.String(description='Only once moderation approved it; null otherwise')
    author = graphene.String(description="The buyer's Comunidad name (chosen username or pseudonym), never their name")
    product_title = graphene.String()
    created_at = graphene.DateTime()


class Query(graphene.ObjectType):
    marketplace_store_reviews = graphene.List(
        StoreReviewType, store_id=graphene.ID(required=True), limit=graphene.Int(), offset=graphene.Int(),
        description="A store's reviews, newest first: every rating, with its text once moderation approved it")

    def resolve_marketplace_store_reviews(self, info, store_id, limit=10, offset=0):
        if not _user(info):
            return []
        limit = max(1, min(int(limit or 10), PAGE_MAX))
        offset = max(0, int(offset or 0))
        rows = (OrderRating.objects.select_related('order', 'order__buyer')
                .filter(store_id=store_id, store__deleted_at__isnull=True)
                .order_by('-created_at', '-pk')[offset:offset + limit])
        from inbox.community import author_display_name

        # The Comunidad name: a chosen username or a pseudonym, never a legal
        # name nor a username signup derived from the email address.
        return [StoreReviewType(
            id=str(r.pk), rating=r.rating,
            comment=r.comment if r.comment_status == 'approved' and r.comment else None,
            author=author_display_name(r.order.buyer), product_title=r.order.product_title,
            created_at=r.created_at) for r in rows]

    my_delivery_addresses = graphene.List(
        'marketplace.address_book.DeliveryAddressType',
        description="The buyer's saved delivery addresses for the JWT account, plus the Recarga address (read-only)")

    def resolve_my_delivery_addresses(self, info):
        from .address_book import resolve_my_delivery_addresses
        return resolve_my_delivery_addresses(info)

    marketplace_reference_rate = graphene.Field(
        ReferenceRateType, country_code=graphene.String(required=True),
        description='Display-only local units per USD (for "≈ Bs" while typing a price); null without a fresh rate')
    marketplace_fee_bps = graphene.Int(description='Merchant fee in basis points (800 = 8%). '
                                                   'Never hardcode it in copy.')
    marketplace_categories = graphene.List(
        MarketplaceCategoryType, country_code=graphene.String(), city=graphene.String(),
        description='Active categories, grouped by `group` in order. With a country+city, '
                    'productCount says how many live listings each has there (browse hides empty ones).')
    marketplace_countries = graphene.List(MarketplaceCountryType)
    marketplace_cities = graphene.List(MarketplaceCityType, country_code=graphene.String(required=True))
    marketplace_city = graphene.Field(
        MarketplaceCityType, country_code=graphene.String(required=True),
        city=graphene.String(required=True),
        description='The GPS city as Comprar knows it (null = unknown city → fake door)')
    marketplace_products = graphene.List(
        MarketplaceProductType, country_code=graphene.String(required=True),
        city=graphene.String(), category=graphene.String(), search=graphene.String(),
        store_id=graphene.ID(), limit=graphene.Int(default_value=20),
        offset=graphene.Int(default_value=0))
    marketplace_product = graphene.Field(MarketplaceProductType, id=graphene.ID(required=True))
    marketplace_store = graphene.Field(MarketplaceStoreType, id=graphene.ID(required=True))
    my_market_store = graphene.Field(MarketplaceStoreType)
    my_market_store_products = graphene.List(MarketplaceProductType)
    my_market_orders = graphene.List(
        MarketplaceOrderType, role=graphene.String(description="'buyer' (default) or 'merchant'"),
        limit=graphene.Int(default_value=20), offset=graphene.Int(default_value=0))
    market_order = graphene.Field(MarketplaceOrderType, id=graphene.ID(required=True))
    # Adults-only rules: their own queries (never fields on the shared types,
    # which would fail whole shared queries against an older server).
    marketplace_age_rules = graphene.Field(MarketplaceAgeRulesType, country_code=graphene.String())
    market_order_adults_only = graphene.Boolean(id=graphene.ID(required=True))
    market_checkout_quote = graphene.Field(
        CheckoutQuoteType, product_id=graphene.ID(required=True), quantity=graphene.Int(required=True),
        delivery_country=graphene.String(required=True), delivery_city=graphene.String(required=True))

    def resolve_marketplace_reference_rate(self, info, country_code):
        from .pricing import currency_for_country, local_per_usd
        if not _user(info):
            return None
        currency = currency_for_country(country_code)
        rate = local_per_usd(currency)
        return ReferenceRateType(currency=currency, local_per_usd=str(rate)) if rate else None

    def resolve_marketplace_fee_bps(self, info):
        from .pricing import fee_bps
        return fee_bps()

    def resolve_marketplace_categories(self, info, country_code=None, city=None):
        counts = {}
        if country_code and city:
            counts = dict(
                _visible_products().filter(_area_city_q(country_code, city),
                                           store__country_code=country_code.upper().strip())
                .values_list('category').annotate(n=Count('id')))
        return [MarketplaceCategoryType(key=c.key, label=c.label, group=c.group, icon=c.icon,
                                        product_count=counts.get(c.key, 0) if counts or (country_code and city)
                                        else None)
                for c in active_categories()]

    def resolve_marketplace_countries(self, info):
        if not _user(info):
            return []
        rows = (_selling_stores().values('country_code')
                .annotate(n=Count('id', distinct=True)).order_by('-n'))
        return [MarketplaceCountryType(country_code=r['country_code'], store_count=r['n']) for r in rows]

    @staticmethod
    def _city_type(city):
        count = _selling_stores().filter(
            _area_city_q(city.country_code, city.city, field='city'),
            country_code=city.country_code).distinct().count()
        return MarketplaceCityType(
            country_code=city.country_code, city=city.city, currency_code=city.currency_code,
            # Live when this city or any city of its delivery area sells:
            # El Alto shops the La Paz stores.
            is_live=area_is_live(city.country_code, city.city),
            delivery_estimate=str(city.delivery_estimate) if city.delivery_estimate is not None else None,
            delivery_partner=city.delivery_partner, store_count=count,
            suggested_delivery_usd=str(suggested_delivery_usd(city.country_code, city.city)),
            latitude=float(city.latitude) if city.latitude is not None else None,
            longitude=float(city.longitude) if city.longitude is not None else None)

    def resolve_marketplace_cities(self, info, country_code):
        if not _user(info):
            return []
        return [Query._city_type(c) for c in
                MarketplaceCity.objects.filter(country_code=country_code.upper().strip())]

    def resolve_marketplace_city(self, info, country_code, city):
        if not _user(info):
            return None
        row = MarketplaceCity.objects.filter(
            country_code=country_code.upper().strip(), city__iexact=city.strip()).first()
        return Query._city_type(row) if row else None

    def resolve_marketplace_products(self, info, country_code, city=None, category=None,
                                     search=None, store_id=None, limit=20, offset=0):
        if not _user(info):
            return []
        country = country_code.upper().strip()
        if country not in VALID_COUNTRY_CODES:
            return []
        qs = _visible_products().filter(store__country_code=country)
        # Stores in a live city or in its delivery area (an El Alto store sells
        # with La Paz), the same rule checkout applies.
        from .checkout import live_city_names
        live_q = Q()
        for name in live_city_names(country):
            live_q |= Q(store__city__iexact=name)
        qs = qs.filter(live_q) if live_q else qs.none()
        if city:
            # The whole delivery area: an El Alto buyer sees the La Paz stores.
            qs = qs.filter(_area_city_q(country, city))
        if category:
            qs = qs.filter(category=category)
        if store_id:
            qs = qs.filter(store_id=store_id)
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search)
                           | Q(store__name__icontains=search))
        qs = qs.order_by('-created_at')[offset: offset + min(limit, PAGE_MAX)]
        return [MarketplaceProductType.from_model(p) for p in qs]

    def resolve_marketplace_product(self, info, id):
        user = _user(info)
        if not user:
            return None
        product = Product.objects.select_related('store', 'store__owner').filter(
            pk=id, deleted_at__isnull=True).first()
        if product is None:
            return None
        # Seller view only for the store's OWN account in the JWT (with the
        # store permission on a business) — not for the same person on
        # another account.
        try:
            _u, account = _ctx(info, STORE_ADMIN)
            owner = product.store.owner_account_id == account.id
        except CheckoutError:
            owner = False
        if not owner and product.status != 'active':
            return None
        return MarketplaceProductType.from_model(product, for_owner=owner)

    def resolve_marketplace_store(self, info, id):
        if not _user(info):
            return None
        store = Store.objects.select_related('owner').filter(pk=id, deleted_at__isnull=True).first()
        return MarketplaceStoreType.from_model(store) if store else None

    def resolve_my_market_store(self, info):
        try:
            _u, account = _ctx(info)
        except CheckoutError:
            return None
        store = Store.objects.select_related('owner').filter(
            owner_account=account, deleted_at__isnull=True).first()
        return MarketplaceStoreType.from_model(store) if store else None

    def resolve_my_market_store_products(self, info):
        try:
            _u, account = _ctx(info, STORE_ADMIN)
        except CheckoutError:
            return []
        qs = Product.objects.select_related('store').filter(
            store__owner_account=account, store__deleted_at__isnull=True,
            deleted_at__isnull=True).order_by('-created_at')
        return [MarketplaceProductType.from_model(p, for_owner=True, with_store=False) for p in qs]

    def resolve_my_market_orders(self, info, role='buyer', limit=20, offset=0):
        try:
            user, account = _ctx(info, VIEW_ORDERS)
        except CheckoutError:
            return []
        qs = _orders_for(account)
        qs = (qs.filter(store__owner_account=account) if role == 'merchant'
              else qs.filter(buyer_account=account))
        if role != 'merchant':
            # A draft is listed exactly while checkout would reuse it (same
            # rule), so the buyer can resume it — it may hold the last units.
            import time as _time
            from .checkout import REUSE_MIN_REMAINING_S
            qs = qs.exclude(status='draft',
                            deposit_deadline__lt=int(_time.time()) + REUSE_MIN_REMAINING_S)
        else:
            qs = qs.exclude(status__in=('draft', 'depositing'))
        return [MarketplaceOrderType.from_model(o, user, account)
                for o in qs.order_by('-created_at')[offset: offset + min(limit, PAGE_MAX)]]

    def resolve_marketplace_age_rules(self, info, country_code=None):
        from .checkout import is_of_age
        from .models import MINIMUM_AGE, age_restricted_keys
        user = _user(info)
        if not user:
            return None
        # Display hint only (the server re-checks at checkout and payment).
        return MarketplaceAgeRulesType(minimum_age=MINIMUM_AGE, category_keys=sorted(age_restricted_keys()),
                                       viewer_of_age=is_of_age(user, country_code))

    def resolve_market_order_adults_only(self, info, id):
        try:
            _, account = _ctx(info, VIEW_ORDERS)
        except CheckoutError:
            return None
        order = _orders_for(account).filter(public_id=id).first()
        if order is None or (order.buyer_account_id != account.id and order.status in ('draft', 'depositing')):
            return None
        return order.age_restricted

    def resolve_market_order(self, info, id):
        try:
            user, account = _ctx(info, VIEW_ORDERS)
        except CheckoutError:
            return None
        order = _orders_for(account).filter(public_id=id).first()
        if order is None:
            return None
        # The store sees an order only once it is paid.
        if order.buyer_account_id != account.id and order.status in ('draft', 'depositing'):
            return None
        return MarketplaceOrderType.from_model(order, user, account)

    def resolve_market_checkout_quote(self, info, product_id, quantity, delivery_country, delivery_city):
        if not _user(info):
            return None
        # Listing-eligible regardless of stock: a buyer whose own draft holds
        # the last unit must still be able to complete that checkout.
        product = Product.objects.select_related('store').filter(
            pk=product_id, deleted_at__isnull=True, status='active',
            store__deleted_at__isnull=True, store__status='active').first()
        if product is None:
            return None
        try:
            terms = checkout_quote(product, quantity, delivery_country, delivery_city)
        except CheckoutError:
            return None
        q = terms['quote']
        return CheckoutQuoteType(
            unit_price_usd=str(q.unit_price_usd), product_usd=str(q.product_usd),
            delivery_usd=str(q.delivery_usd), amount_usd=str(q.amount_usd),
            reference_local=_reference(q.amount_usd, product.store.country_code),
            delivery_currency=terms['currency'] or None,
            outside_city=terms['outside_city'], ships_outside_city=terms['ships_outside_city'],
            delivery_estimate_local=(str(terms['estimate_local'])
                                     if terms['estimate_local'] is not None else None),
            delivery_partner=terms['partner'])


# ── store & products (seller) ───────────────────────────────────────────

def _seller_store(info):
    """(user, account, store) for the JWT's account — personal, or business
    with edit_business_info — or raises CheckoutError."""
    user, account = _ctx(info, STORE_ADMIN)
    store = Store.objects.filter(owner_account=account, deleted_at__isnull=True).first()
    return user, account, store


def nearest_city(latitude: float, longitude: float):
    """The known city whose radius contains the point (closest wins)."""
    import math

    best, best_km = None, None
    for city in MarketplaceCity.objects.filter(latitude__isnull=False, longitude__isnull=False):
        lat1, lon1 = math.radians(latitude), math.radians(longitude)
        lat2, lon2 = math.radians(float(city.latitude)), math.radians(float(city.longitude))
        h = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
        km = 2 * 6371 * math.asin(math.sqrt(h))
        if km <= city.radius_km and (best_km is None or km < best_km):
            best, best_km = city, km
    return best


class LocateMarketplaceCity(graphene.Mutation):
    """The phone's GPS → Comprar's default city. The reading is kept (with
    request IP/country and the matched city) like Bre-B location checks."""

    class Arguments:
        latitude = graphene.Float(required=True)
        longitude = graphene.Float(required=True)
        accuracy = graphene.Float()

    city = graphene.Field(MarketplaceCityType)

    @login_required
    def mutate(self, info, latitude, longitude, accuracy=None):
        from .models import MarketplaceLocationCheck

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return LocateMarketplaceCity(city=None)
        user = info.context.user
        match = nearest_city(latitude, longitude)
        try:
            import ipaddress

            from security.geo import country_for_request
            from security.request_utils import extract_client_ip_from_meta

            meta = getattr(info.context, 'META', {}) or {}
            ip = extract_client_ip_from_meta(meta) or None
            try:
                ip = str(ipaddress.ip_address(ip)) if ip else None
            except ValueError:
                ip = None
            account = None
            try:
                _u, account = _ctx(info)
            except CheckoutError:
                pass
            MarketplaceLocationCheck.objects.create(
                user=user, account=account, latitude=latitude, longitude=longitude,
                accuracy_m=accuracy, ip_address=ip, ip_country=(country_for_request(meta) or '')[:2],
                matched_city=match)
        except Exception as exc:  # noqa: BLE001 — the record never changes the answer
            # The class only: a database error's text can quote the row (coordinates, IP).
            logger.warning('marketplace_location_record_failed error=%s', type(exc).__name__)
        return LocateMarketplaceCity(city=Query._city_type(match) if match else None)


class SubmitMarketplaceInterest(graphene.Mutation):
    """The fake door's probe in a city that is not live: buy or sell, what,
    at what price, and (sellers) current monthly sales and channels. One row
    per user and city; answering again updates it."""

    class Arguments:
        country_code = graphene.String(required=True)
        city = graphene.String(required=True)
        role = graphene.String(required=True, description="'buyer' | 'seller' | 'both' | 'browsing'")
        categories = graphene.List(graphene.String)
        wants = graphene.String()
        price_range = graphene.String()
        monthly_sales = graphene.String()
        channels = graphene.List(graphene.String)
        notify = graphene.Boolean()

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, country_code, city, role, categories=None, wants='', price_range='',
               monthly_sales='', channels=None, notify=True):
        from .models import MarketplaceInterest

        user = info.context.user
        country = (country_code or '').upper().strip()
        city = (city or '').strip()[:100]
        # GraphQL allows explicit nulls; the columns are not nullable.
        price_range = price_range or ''
        monthly_sales = monthly_sales or ''
        wants = wants or ''
        notify = True if notify is None else notify
        roles = {k for k, _ in MarketplaceInterest.ROLE_CHOICES}
        prices = {k for k, _ in MarketplaceInterest.PRICE_CHOICES}
        sales = {k for k, _ in MarketplaceInterest.MONTHLY_SALES_CHOICES}
        if country not in VALID_COUNTRY_CODES or not city or role not in roles:
            return SubmitMarketplaceInterest(success=False, error='bad_input')
        if (price_range and price_range not in prices) or (monthly_sales and monthly_sales not in sales):
            return SubmitMarketplaceInterest(success=False, error='bad_input')
        selling = role in ('seller', 'both')
        account = None
        try:
            _u, account = _ctx(info)
        except CheckoutError:
            pass
        headers = getattr(info.context, 'headers', None) or {}
        version = str(headers.get('X-Confio-Version', '') or '')[:20]
        MarketplaceInterest.objects.update_or_create(
            user=user, country_code=country, city=city,
            defaults={
                'account': account, 'role': role,
                'categories': sorted(set(categories or []) & active_category_keys())[:20],
                'wants': (wants or '').strip()[:300],
                'price_range': price_range if role != 'browsing' else '',
                'monthly_sales': monthly_sales if selling else '',
                'channels': sorted({c for c in (channels or [])
                                    if c in MarketplaceInterest.CHANNEL_KEYS}) if selling else [],
                'notify': bool(notify) and role != 'browsing',
                'app_version': version,
            })
        return SubmitMarketplaceInterest(success=True)


class OpenMarketStore(graphene.Mutation):
    """An account (personal or business) opens its one store, by a
    Didit-verified user. No KYB: informal sellers open from their personal
    account; a business needs edit_business_info."""

    class Arguments:
        name = graphene.String(required=True)
        description = graphene.String()
        country_code = graphene.String(required=True)
        city = graphene.String(required=True)
        ships_outside_city = graphene.Boolean()
        delivery_price_usd = graphene.String(description='US dollars; omitted = the city suggestion')
        outside_delivery_price_usd = graphene.String(description='US dollars; omitted or empty = this area only')

    success = graphene.Boolean()
    error = graphene.String()
    store = graphene.Field(MarketplaceStoreType)

    @login_required
    def mutate(self, info, name, country_code, city, description='', ships_outside_city=False,
               delivery_price_usd=None, outside_delivery_price_usd=None):
        try:
            user, account, store = _seller_store(info)
        except CheckoutError as exc:
            return OpenMarketStore(success=False, error=exc.code)
        if store is not None:
            return OpenMarketStore(success=False, error='store_exists')
        if not user.is_identity_verified:
            return OpenMarketStore(success=False, error='identity_required')
        country = country_code.upper().strip()
        name = name.strip()
        if country not in VALID_COUNTRY_CODES or not city.strip():
            return OpenMarketStore(success=False, error='bad_location')
        if not (2 <= len(name) <= 80):
            return OpenMarketStore(success=False, error='bad_name')
        known = MarketplaceCity.objects.filter(country_code=country, city__iexact=city.strip()).first()
        if delivery_price_usd in (None, ''):
            delivery = suggested_delivery_usd(country, city)
        else:
            delivery = _delivery_price(delivery_price_usd)
            if delivery is None:
                return OpenMarketStore(success=False, error='bad_delivery_price')
        outside = None
        if ships_outside_city and outside_delivery_price_usd in (None, ''):
            return OpenMarketStore(success=False, error='outside_delivery_price_required')
        if outside_delivery_price_usd not in (None, ''):
            outside = _delivery_price(outside_delivery_price_usd)
            if outside is None:
                return OpenMarketStore(success=False, error='bad_delivery_price')
        # Other cities are offered only with a price (an older build's bare
        # "ships outside" switch no longer means "coordinate it").
        store = Store.objects.create(delivery_price_usd=delivery, outside_delivery_price_usd=outside,
            owner=account.user, owner_account=account, name=name,
            description=(description or '').strip()[:1000], country_code=country,
            city=known.city if known else city.strip()[:100],
            ships_outside_city=outside is not None)
        return OpenMarketStore(success=True, store=MarketplaceStoreType.from_model(store))


def _delivery_price(value):
    """A store's delivery price from the form (US$, 0 = free), or None."""
    from decimal import Decimal, InvalidOperation

    from .pricing import MAX_DELIVERY_USD
    try:
        price = Decimal(str(value))
        if not price.is_finite():
            return None
        price = price.quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return price if Decimal('0') <= price <= MAX_DELIVERY_USD else None


class UpdateMarketStore(graphene.Mutation):
    class Arguments:
        name = graphene.String()
        description = graphene.String()
        ships_outside_city = graphene.Boolean()
        paused = graphene.Boolean()
        delivery_price_usd = graphene.String()
        outside_delivery_price_usd = graphene.String(description='Empty string = stop offering other cities')

    success = graphene.Boolean()
    error = graphene.String()
    store = graphene.Field(MarketplaceStoreType)

    @login_required
    def mutate(self, info, name=None, description=None, ships_outside_city=None, paused=None,
               delivery_price_usd=None, outside_delivery_price_usd=None):
        try:
            _user_, _account, store = _seller_store(info)
        except CheckoutError as exc:
            return UpdateMarketStore(success=False, error=exc.code)
        if store is None:
            return UpdateMarketStore(success=False, error='no_store')
        fields = {}
        if name is not None:
            name = name.strip()
            if not (2 <= len(name) <= 80):
                return UpdateMarketStore(success=False, error='bad_name')
            fields['name'] = name
        if description is not None:
            fields['description'] = description.strip()[:1000]
        if ships_outside_city is True and outside_delivery_price_usd in (None, ''):
            # An older build's bare switch: other cities need their own price now.
            return UpdateMarketStore(success=False, error='outside_delivery_price_required')
        if ships_outside_city is False:
            # An older build turning other cities off.
            fields['ships_outside_city'] = False
            fields['outside_delivery_price_usd'] = None
        if outside_delivery_price_usd is not None:
            if outside_delivery_price_usd == '':
                fields['outside_delivery_price_usd'] = None
            else:
                outside = _delivery_price(outside_delivery_price_usd)
                if outside is None:
                    return UpdateMarketStore(success=False, error='bad_delivery_price')
                fields['outside_delivery_price_usd'] = outside
            fields['ships_outside_city'] = fields['outside_delivery_price_usd'] is not None
        if delivery_price_usd is not None:
            delivery = _delivery_price(delivery_price_usd)
            if delivery is None:
                return UpdateMarketStore(success=False, error='bad_delivery_price')
            fields['delivery_price_usd'] = delivery
        if fields:
            Store.objects.filter(pk=store.pk).update(**fields)
        if paused is not None:
            # Conditional on the CURRENT status: a suspension that landed
            # after this request read the store is never undone.
            Store.objects.filter(pk=store.pk, status__in=('active', 'paused')).update(
                status='paused' if paused else 'active')
        store.refresh_from_db()
        return UpdateMarketStore(success=True, store=MarketplaceStoreType.from_model(store))


class RequestMarketPhotoUpload(graphene.Mutation):
    class Arguments:
        content_type = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    upload = graphene.Field(PhotoUploadType)

    @login_required
    def mutate(self, info, content_type):
        from inbox.community import take_upload_ticket
        from security.s3_utils import build_s3_key, generate_presigned_post

        try:
            user, _account, store = _seller_store(info)
        except CheckoutError as exc:
            return RequestMarketPhotoUpload(success=False, error=exc.code)
        if store is None:
            return RequestMarketPhotoUpload(success=False, error='no_store')
        # iOS's image picker labels JPEGs "image/jpg"; the presigned POST then
        # pins the canonical type, which is what S3 stores.
        content_type = {'image/jpg': 'image/jpeg'}.get((content_type or '').lower(), content_type)
        if content_type not in ALLOWED_IMAGE_TYPES:
            return RequestMarketPhotoUpload(success=False, error='bad_image_type')
        if not take_upload_ticket(user, 'marketplace-photo'):
            return RequestMarketPhotoUpload(success=False, error='too_many_uploads')
        key = build_s3_key(pending_prefix(user), f'upload{ALLOWED_IMAGE_TYPES[content_type]}')
        try:
            presigned = generate_presigned_post(
                key=key, content_type=content_type,
                metadata={'uploaded-by': str(user.id), 'uploaded-for': 'marketplace'},
                conditions=[['content-length-range', 1, settings.COMMUNITY_IMAGE_MAX_BYTES]],
                expires_in_seconds=600, bucket=settings.AWS_COMMUNITY_UPLOAD_BUCKET)
        except Exception:  # noqa: BLE001
            logger.exception('[COMPRAR] presign failed for user %s', user.id)
            return RequestMarketPhotoUpload(success=False, error='upload_unavailable')
        return RequestMarketPhotoUpload(success=True, upload=PhotoUploadType(
            url=presigned['url'], key=presigned['key'], method=presigned['method'],
            fields=presigned.get('fields'), expires_in=presigned['expires_in']))


class SaveMarketProduct(graphene.Mutation):
    """Create or edit a listing. Every save goes back through moderation;
    `photo_keys` (pending uploads) replace the photos when given."""

    class Arguments:
        product_id = graphene.ID()
        title = graphene.String(required=True)
        description = graphene.String()
        category = graphene.String(required=True)
        price_usd = graphene.String(required=True, description='US dollars, 2 decimals')
        stock = graphene.Int(required=True)
        expected_stock = graphene.Int(description='Edits: the stock the form loaded; the change is '
                                                  'applied as a delta from it')
        expected_stock_revision = graphene.Int(description='Edits: the stockRevision the form loaded')
        photo_keys = graphene.List(graphene.String)

    success = graphene.Boolean()
    error = graphene.String()
    product = graphene.Field(MarketplaceProductType)

    @login_required
    def mutate(self, info, title, category, price_usd, stock, product_id=None,
               description='', photo_keys=None, expected_stock=None, expected_stock_revision=None):
        from decimal import Decimal, InvalidOperation


        try:
            user, _account, store = _seller_store(info)
        except CheckoutError as exc:
            return SaveMarketProduct(success=False, error=exc.code)
        if store is None:
            return SaveMarketProduct(success=False, error='no_store')
        if not user.is_identity_verified:
            return SaveMarketProduct(success=False, error='identity_required')
        title = title.strip()
        if not (3 <= len(title) <= 100):
            return SaveMarketProduct(success=False, error='bad_title')
        try:
            price = Decimal(price_usd).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            return SaveMarketProduct(success=False, error='bad_price')
        if price < Decimal('0.50') or price > Decimal('100000'):
            return SaveMarketProduct(success=False, error='bad_price')
        if not (0 <= stock <= 10_000):
            return SaveMarketProduct(success=False, error='bad_stock')
        keys = [k for k in (photo_keys or []) if k][:MAX_PHOTOS]
        prefix = pending_prefix(user)
        if any(not k.startswith(prefix) for k in keys):
            return SaveMarketProduct(success=False, error='bad_photo')

        if product_id:
            product = Product.objects.filter(pk=product_id, store=store, deleted_at__isnull=True).first()
            if product is None:
                return SaveMarketProduct(success=False, error='product_not_found')
        else:
            if not keys:
                return SaveMarketProduct(success=False, error='photo_required')
            product = Product(store=store)
        # A new listing, or a change of category, needs an active category; an
        # existing listing keeps a category the admin has since hidden.
        unchanged = product.pk is not None and category == product.category
        if not unchanged and category not in active_category_keys():
            return SaveMarketProduct(success=False, error='bad_category')
        # Leaving an adults-only category: the kept photos were approved as
        # alcohol, so new ones must be uploaded and reviewed with the new text.
        from .checkout import category_is_age_restricted
        if (not unchanged and product.pk is not None and not keys
                and category_is_age_restricted(product.category) and not category_is_age_restricted(category)):
            return SaveMarketProduct(success=False, error='photos_required')
        from django.db import transaction
        from django.db.models import F
        from django.db.models.functions import Greatest

        content = {'title': title, 'description': (description or '').strip()[:2000],
                   'category': category, 'price_usd': price}
        if keys:
            content['pending_photo_keys'] = keys
        with transaction.atomic():
            for field, value in content.items():
                setattr(product, field, value)
            if product.pk is None:
                product.stock = stock
                start_review(product)
            else:
                # Stock moves by the seller's DELTA from what their form
                # loaded, never by overwriting: checkouts may have reserved
                # units since then, and those must stay reserved.
                if expected_stock is None or expected_stock_revision is None:
                    return SaveMarketProduct(success=False, error='stale_form')
                delta = stock - expected_stock
                if delta:
                    # Consumes the revision the form loaded: a retried save
                    # (lost response) finds it gone and changes nothing.
                    if not Product.objects.filter(
                            pk=product.pk, stock_revision=expected_stock_revision,
                    ).update(stock=Greatest(F('stock') + delta, 0),
                             stock_revision=F('stock_revision') + 1):
                        transaction.set_rollback(True)
                        return SaveMarketProduct(success=False, error='stale_form')
                start_review(product, update_fields=[*content.keys()])
        product.refresh_from_db()
        return SaveMarketProduct(success=True, product=MarketplaceProductType.from_model(
            product, for_owner=True, with_store=False))


class SetMarketProductPaused(graphene.Mutation):
    class Arguments:
        product_id = graphene.ID(required=True)
        paused = graphene.Boolean(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, product_id, paused):
        try:
            _u, _a, store = _seller_store(info)
        except CheckoutError as exc:
            return SetMarketProductPaused(success=False, error=exc.code)
        product = Product.objects.filter(pk=product_id, store=store, deleted_at__isnull=True).first()
        if product is None:
            return SetMarketProductPaused(success=False, error='product_not_found')
        # Conditional on the status AND review revision read here: an edit
        # since then rotated the claim, and only the approved revision may
        # ever be (re)activated.
        source, target = ('active', 'paused') if paused else ('paused', 'active')
        moved = Product.objects.filter(
            pk=product.pk, status=source, review_claim=product.review_claim,
        ).update(status=target)
        if not moved:
            return SetMarketProductPaused(success=False, error='bad_status')
        return SetMarketProductPaused(success=True)


class DeleteMarketProduct(graphene.Mutation):
    class Arguments:
        product_id = graphene.ID(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, product_id):
        try:
            _u, _a, store = _seller_store(info)
        except CheckoutError as exc:
            return DeleteMarketProduct(success=False, error=exc.code)
        product = Product.objects.filter(pk=product_id, store=store, deleted_at__isnull=True).first()
        if product is None:
            return DeleteMarketProduct(success=False, error='product_not_found')
        product.soft_delete()
        return DeleteMarketProduct(success=True)


# ── orders ──────────────────────────────────────────────────────────────

class PrepareMarketOrder(graphene.Mutation):
    """Step 1 of a purchase: freeze the quote, sign the escrow authorization,
    return the batch the buyer signs (then submitMarketOrderAction 'deposit')."""

    class Arguments:
        product_id = graphene.ID(required=True)
        quantity = graphene.Int(required=True)
        delivery_country = graphene.String(required=True)
        delivery_city = graphene.String(required=True)
        delivery_address = graphene.String(required=True)
        delivery_phone = graphene.String(required=True)
        delivery_note = graphene.String()
        outside_city_ack = graphene.Boolean()
        delivery_latitude = graphene.Float(description='The map pin; with a reference it can replace the address')
        delivery_longitude = graphene.Float()

    success = graphene.Boolean()
    error = graphene.String()
    order = graphene.Field(MarketplaceOrderType)
    calls = graphene.List(MarketCallType)
    intent_id = graphene.String()

    @login_required
    def mutate(self, info, product_id, quantity, delivery_country, delivery_city,
               delivery_address, delivery_phone, delivery_note='', outside_city_ack=False,
               delivery_latitude=None, delivery_longitude=None):
        user = info.context.user
        try:
            ctx = _jwt(info, BUY)
            if ctx is None:
                raise CheckoutError('permission_denied')
            order, calls, intent_id = prepare_order(
                user, ctx, product_id=product_id, quantity=quantity,
                delivery_country=delivery_country, delivery_city=delivery_city,
                delivery_address=delivery_address, delivery_phone=delivery_phone,
                delivery_note=delivery_note, outside_city_ack=bool(outside_city_ack),
                delivery_latitude=delivery_latitude, delivery_longitude=delivery_longitude)
        except CheckoutError as exc:
            return PrepareMarketOrder(success=False, error=exc.code)
        return PrepareMarketOrder(
            success=True, order=MarketplaceOrderType.from_model(order, user, order.buyer_account),
            calls=[MarketCallType(to=c['to'], value_wei=c['value'], data=c['data']) for c in calls],
            intent_id=intent_id)


def _actor_order(info, order_id, action):
    """The order if the JWT's account is the side performing `action` and the
    user holds its permission; otherwise None."""
    if action not in escrow.ACTIONS:
        return None
    try:
        user, account = _ctx(info, ACTION_PERMISSIONS[action])
    except CheckoutError:
        return None
    order = Order.objects.select_related(
        'store', 'store__owner_account', 'product', 'buyer', 'buyer_account').filter(public_id=order_id).first()
    if order is None or order_actor_account(order, action).pk != account.pk \
            or not escrow.actor_allowed(user, order, action):
        return None
    return order


class MarketOrderActionCalls(graphene.Mutation):
    """The calls the actor signs for one order action (ship, confirm,
    dispute, refund, reclaim; deposit returns the batch stored at prepare)."""

    class Arguments:
        order_id = graphene.ID(required=True)
        action = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    calls = graphene.List(MarketCallType)
    intent_id = graphene.String()

    @login_required
    def mutate(self, info, order_id, action):
        from cusd_plus import sponsor_7702

        order = _actor_order(info, order_id, action)
        if order is None:
            return MarketOrderActionCalls(success=False, error='order_not_found')
        if not escrow.enabled():
            return MarketOrderActionCalls(success=False, error='marketplace_disabled')
        if action == 'deposit':
            from .checkout import deposit_age_error
            age_error = deposit_age_error(info.context.user, order)
            if age_error:
                return MarketOrderActionCalls(success=False, error=age_error)
        calls = escrow.action_calls(order, action)
        return MarketOrderActionCalls(
            success=True,
            calls=[MarketCallType(to=c['to'], value_wei=c['value'], data=c['data']) for c in calls],
            intent_id=sponsor_7702.intent_id_hex(escrow.ACTIONS[action][0], order.pk))


class SubmitMarketOrderAction(graphene.Mutation):
    class Arguments:
        order_id = graphene.ID(required=True)
        action = graphene.String(required=True)
        nonce = graphene.String(required=True)
        deadline = graphene.String(required=True)
        intent_signature = graphene.String(required=True)
        authorization = MarketAuthorizationInput(required=False)
        dispute_reason = graphene.String()

    success = graphene.Boolean()
    error = graphene.String()
    authorization_required = graphene.Boolean()
    transaction_hash = graphene.String()

    @login_required
    def mutate(self, info, order_id, action, nonce, deadline, intent_signature,
               authorization=None, dispute_reason=None):
        user = info.context.user
        order = _actor_order(info, order_id, action)
        if order is None:
            return SubmitMarketOrderAction(success=False, error='order_not_found')
        if action == 'deposit' and not user.is_identity_verified:
            return SubmitMarketOrderAction(success=False, error='identity_required')
        if action == 'dispute':
            reason = (dispute_reason or '').strip()
            if len(reason) < 10:
                return SubmitMarketOrderAction(success=False, error='dispute_reason_required')
            Order.objects.filter(pk=order.pk).update(dispute_reason=reason[:500])
        result = escrow.submit_action(user, order, action, int(nonce), int(deadline),
                                      intent_signature, authorization)
        return SubmitMarketOrderAction(
            success=result.get('success', False), error=result.get('error'),
            authorization_required=bool(result.get('authorization_required')),
            transaction_hash=result.get('transaction_hash'))


class SetMarketOrderTracking(graphene.Mutation):
    class Arguments:
        order_id = graphene.ID(required=True)
        tracking_reference = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, order_id, tracking_reference):
        try:
            _u, account = _ctx(info, SHIP)
        except CheckoutError as exc:
            return SetMarketOrderTracking(success=False, error=exc.code)
        updated = Order.objects.filter(
            public_id=order_id, store__owner_account=account,
            status__in=('funded', 'shipped', 'disputed'),
        ).update(tracking_reference=tracking_reference.strip()[:120])
        return SetMarketOrderTracking(success=bool(updated), error=None if updated else 'order_not_found')


class RateMarketOrder(graphene.Mutation):
    class Arguments:
        order_id = graphene.ID(required=True)
        rating = graphene.Int(required=True)
        comment = graphene.String()

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, order_id, rating, comment=''):
        from django.db import IntegrityError

        try:
            _u, account = _ctx(info, BUY)
        except CheckoutError as exc:
            return RateMarketOrder(success=False, error=exc.code)
        order = Order.objects.filter(public_id=order_id, buyer_account=account,
                                     status='released').select_related('store').first()
        if order is None:
            return RateMarketOrder(success=False, error='order_not_rateable')
        if not (1 <= rating <= 5):
            return RateMarketOrder(success=False, error='bad_rating')
        from django.db import transaction
        from django.utils import timezone

        text = (comment or '').strip()[:500]
        try:
            with transaction.atomic():
                saved = OrderRating.objects.create(
                    order=order, store=order.store, rating=rating, comment=text,
                    comment_status='pending' if text else 'none',
                    comment_queued_at=timezone.now() if text else None)
                if text:
                    from .tasks import enqueue_rating_review
                    transaction.on_commit(lambda: enqueue_rating_review(saved.pk))
        except IntegrityError:
            return RateMarketOrder(success=False, error='already_rated')
        return RateMarketOrder(success=True)


class Mutation(graphene.ObjectType):
    save_delivery_address = SaveDeliveryAddress.Field()
    delete_delivery_address = DeleteDeliveryAddress.Field()
    locate_marketplace_city = LocateMarketplaceCity.Field()
    submit_marketplace_interest = SubmitMarketplaceInterest.Field()
    open_market_store = OpenMarketStore.Field()
    update_market_store = UpdateMarketStore.Field()
    request_market_photo_upload = RequestMarketPhotoUpload.Field()
    save_market_product = SaveMarketProduct.Field()
    set_market_product_paused = SetMarketProductPaused.Field()
    delete_market_product = DeleteMarketProduct.Field()
    prepare_market_order = PrepareMarketOrder.Field()
    market_order_action_calls = MarketOrderActionCalls.Field()
    submit_market_order_action = SubmitMarketOrderAction.Field()
    set_market_order_tracking = SetMarketOrderTracking.Field()
    rate_market_order = RateMarketOrder.Field()
