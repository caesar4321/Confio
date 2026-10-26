"""
Comprar — Confío's marketplace for repeat sellers of physical goods.

docs/designs/comprar-marketplace.md. Key invariants:

- A store hangs off one account, personal or business, opened by a
  Didit-verified user. Never require KYB: informal sellers open from their
  personal account. Business employees act per their role's permissions.
- Buyers must be identity-verified too; browsing is open.
- Money moves only through ConfioMarketEscrow (BSC). The Order row mirrors
  the chain; `escrow.sync_order` reads the contract and is the only writer of
  the money states (funded … released/refunded).
- The merchant fee (8% at launch) is signed into each order. The partner
  revenue split (Bolivia GTM) is admin accounting only: MarketplaceFeeLedger
  rows, never on-chain and never in the app.
- Delivery is paid by the buyer to the courier, off-platform. Confío only
  shows the per-city estimate set in admin.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from users.country_codes import COUNTRY_CODES
from users.models import SoftDeleteModel

COUNTRY_CHOICES = [(code[2], f"{code[0]} ({code[1]})") for code in COUNTRY_CODES]

# Physical goods only; prohibited goods are screened by moderation. The
# taxonomy lives in the database (MarketplaceCategory, admin-managed), so a
# new kind of seller never waits for a release. Seeded by migration 0004.


def active_categories():
    return MarketplaceCategory.objects.filter(is_active=True).order_by('group_order', 'sort_order', 'label')


def active_category_keys() -> set:
    return set(MarketplaceCategory.objects.filter(is_active=True).values_list('key', flat=True))


CATEGORY_LABELS_CACHE_KEY = 'comprar:category-labels'
AGE_RESTRICTED_CACHE_KEY = 'comprar:age-restricted-categories'
# Legal drinking age everywhere Comprar sells (Bolivia, and LATAM generally).
MINIMUM_AGE = 18


def age_restricted_keys() -> set:
    """Category keys for adults only (hidden ones too), cached 60s."""
    from django.core.cache import cache
    keys = cache.get(AGE_RESTRICTED_CACHE_KEY)
    if keys is None:
        keys = set(MarketplaceCategory.objects.filter(age_restricted=True).values_list('key', flat=True))
        cache.set(AGE_RESTRICTED_CACHE_KEY, keys, 60)
    return keys


def category_label(key: str) -> str:
    """Label for any key (hidden ones too), from a 60s cached map: one query
    per minute, not one per serialized product."""
    from django.core.cache import cache
    labels = cache.get(CATEGORY_LABELS_CACHE_KEY)
    if labels is None:
        labels = dict(MarketplaceCategory.objects.values_list('key', 'label'))
        cache.set(CATEGORY_LABELS_CACHE_KEY, labels, 60)
    return labels.get(key) or key


class MarketplaceCategory(models.Model):
    """One kind of physical product. Admin-managed: add, rename, reorder or
    hide (is_active=False keeps existing listings, stops new ones)."""

    key = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=60)
    group = models.CharField(max_length=60, help_text='Heading the pickers group it under')
    group_order = models.PositiveSmallIntegerField(default=100)
    sort_order = models.PositiveSmallIntegerField(default=100)
    icon = models.CharField(max_length=30, blank=True, default='tag', help_text='Feather icon name')
    is_active = models.BooleanField(default=True, db_index=True)
    # Adults only (alcoholic beverages): the reviewer allows alcohol only in
    # such a category, and only a buyer of verified legal age can check out.
    age_restricted = models.BooleanField(
        default=False, help_text='Adults only: buyers must be of legal age (verified ID)')

    class Meta:
        verbose_name_plural = 'marketplace categories'
        ordering = ['group_order', 'sort_order', 'label']

    def __str__(self):
        return f'{self.group} › {self.label}'


class MarketplaceCity(models.Model):
    """A city Comprar knows about: whether it is live and what delivery costs.

    The delivery estimate is what checkout shows ("Envío ~15 Bs, pagas al
    repartidor"). Lowering it when Yango volume pricing lands is an admin edit,
    never a release.
    """

    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES, db_index=True)
    city = models.CharField(max_length=100)
    currency_code = models.CharField(max_length=3, help_text='Local currency, e.g. BOB')
    is_live = models.BooleanField(
        default=False, help_text='Off = the fake door ("Próximamente en tu ciudad")')
    delivery_estimate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Same-city delivery estimate in local currency, paid to the courier '
                  '(empty = "a coordinar")')
    delivery_partner = models.CharField(max_length=40, blank=True, default='')
    # City centre, for matching the phone's GPS to a known city server-side
    # (no third-party geocoder; each reading is kept in MarketplaceLocationCheck).
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_km = models.PositiveIntegerField(default=40)
    # Cities with the same area (same country) are ONE delivery area: a buyer
    # in El Alto shops the La Paz stores at the city delivery price, the way a
    # courier actually covers the metro. Blank = the city alone.
    delivery_area = models.CharField(max_length=40, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'marketplace cities'
        constraints = [
            models.UniqueConstraint(fields=['country_code', 'city'], name='marketplace_city_unique'),
        ]
        ordering = ['country_code', 'city']

    def __str__(self):
        return f'{self.city}, {self.country_code}'


class MarketplaceLocationCheck(models.Model):
    """Each GPS reading Comprar used to pick a city, kept like Bre-B's
    location checks (covered by the Privacy Policy): when, who, the device
    reading, the request IP/country and the city it matched."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    account = models.ForeignKey('users.Account', null=True, blank=True, on_delete=models.PROTECT,
                                related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy_m = models.FloatField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    ip_country = models.CharField(max_length=2, blank=True)
    matched_city = models.ForeignKey(MarketplaceCity, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')

    class Meta:
        indexes = [models.Index(fields=['user', '-created_at'])]


class Store(SoftDeleteModel):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused by owner'),
        ('suspended', 'Suspended by Confío'),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='market_stores')
    # The personal account that sells and is paid. One store per account.
    owner_account = models.ForeignKey(
        'users.Account', on_delete=models.CASCADE, related_name='market_stores')
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default='', max_length=1000)
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES, db_index=True)
    city = models.CharField(max_length=100, db_index=True)
    ships_outside_city = models.BooleanField(
        default=False, help_text='Kept in sync: true when outside_delivery_price_usd is set')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='active', db_index=True)
    suspended_reason = models.CharField(max_length=300, blank=True, default='')
    # What the buyer pays for same-city delivery, in US dollars, added to the
    # order total. The store books and pays the courier itself (Yango Envíos,
    # its own moto…) and gets it back in the payout.
    delivery_price_usd = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0'))
    # One flat price for anywhere else in the country (bus parcel, courier);
    # null = the store delivers in its own delivery area only.
    outside_delivery_price_usd = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['owner_account'], condition=models.Q(deleted_at__isnull=True),
                name='marketplace_one_store_per_account'),
        ]

    def __str__(self):
        return f'{self.name} ({self.city}, {self.country_code})'

    @property
    def is_open(self):
        return self.status == 'active' and self.deleted_at is None


class Product(SoftDeleteModel):
    STATUS_CHOICES = [
        ('pending_review', 'Pending review'),
        ('active', 'Active'),
        ('rejected', 'Rejected by moderation'),
        ('paused', 'Paused by seller'),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='products')
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='', max_length=2000)
    # A MarketplaceCategory.key (kept as a plain key so retiring a category
    # never cascades into listings).
    category = models.CharField(max_length=40, db_index=True)
    # US dollars: the escrow's unit and what the seller receives. Local
    # currency is only ever a display reference (pricing.reference_local).
    price_usd = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.50'))],
        help_text='Price in US dollars')
    stock = models.PositiveIntegerField(default=1)
    # Bumped by every seller stock edit (never by reservations). An edit must
    # name the revision its form loaded, so a retried save cannot apply twice.
    stock_revision = models.PositiveIntegerField(default=0)
    # Public URLs of moderated photos, in display order.
    photo_urls = models.JSONField(default=list, blank=True)
    # Private pending upload keys awaiting review (replaced on every edit).
    pending_photo_keys = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default='pending_review', db_index=True)
    review_claim = models.CharField(max_length=32, blank=True, default='')
    review_verdict = models.JSONField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['store', 'status'])]

    def __str__(self):
        return self.title

    @property
    def is_buyable(self):
        return (self.status == 'active' and self.deleted_at is None
                and self.stock > 0 and self.store.is_open)


class Order(models.Model):
    """One escrowed purchase: a single product × quantity from one store.

    Money states are written only by escrow.sync_order from the contract.
    """

    STATUS_CHOICES = [
        ('draft', 'Prepared, not paid'),
        ('depositing', 'Payment broadcast'),
        ('funded', 'Paid, waiting to ship'),
        ('shipped', 'Shipped'),
        ('disputed', 'Disputed'),
        ('released', 'Completed (merchant paid)'),
        ('refunded', 'Refunded to buyer'),
        ('cancelled', 'Cancelled before payment'),
    ]
    OPEN_STATUSES = ('funded', 'shipped', 'disputed')
    FINAL_STATUSES = ('released', 'refunded', 'cancelled')

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # bytes32 orderId on chain, hex without 0x.
    order_id32 = models.CharField(max_length=64, unique=True)

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='market_orders')
    buyer_account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, related_name='market_orders')
    buyer_address = models.CharField(max_length=42)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='orders')
    merchant_address = models.CharField(max_length=42)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='orders')
    # What the buyer agreed to, frozen at checkout.
    product_title = models.CharField(max_length=100)
    unit_price_usd = models.DecimalField(max_digits=12, decimal_places=2)
    # Included in amount_usd (product + delivery), so in the escrow deposit.
    delivery_usd = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0'))
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(20)])
    amount_usd = models.DecimalField(max_digits=14, decimal_places=6)
    amount_wei = models.DecimalField(max_digits=40, decimal_places=0)
    token_address = models.CharField(max_length=42)
    fee_bps = models.PositiveIntegerField()

    # Delivery (off-platform; buyer pays the courier).
    delivery_country = models.CharField(max_length=2)
    delivery_city = models.CharField(max_length=100)
    delivery_outside_city = models.BooleanField(default=False)
    # The one local-currency amount: the courier is paid in cash/QR locally.
    delivery_estimate_local = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Same-city estimate shown at checkout; null when outside the city')
    delivery_currency = models.CharField(max_length=3, blank=True, default='')
    delivery_address = models.CharField(max_length=300)
    # The buyer's map pin: in much of LATAM the written address does not find
    # the door; the courier app (Yango…) opens straight at this point.
    delivery_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_phone = models.CharField(max_length=20)
    delivery_note = models.CharField(max_length=300, blank=True, default='')
    # Frozen at checkout from the product's category: an adults-only order
    # (the seller hands it over only to an adult showing ID).
    age_restricted = models.BooleanField(default=False)
    tracking_reference = models.CharField(
        max_length=120, blank=True, default='', help_text='Yango Envío tracking id / link')

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='draft', db_index=True)
    # Server deposit authorization (EIP-712), pinned for the submit validator.
    deposit_deadline = models.BigIntegerField()
    deposit_signature = models.CharField(max_length=132)
    deposit_signer = models.CharField(max_length=42)
    # The exact deposit batch built at prepare ([unwrap?, approve, deposit]).
    deposit_calls = models.JSONField(default=list, blank=True)
    # An action broadcast and not yet reflected by sync (one at a time).
    pending_action = models.CharField(max_length=16, blank=True, default='')
    pending_action_at = models.DateTimeField(null=True, blank=True)
    last_tx_hash = models.CharField(max_length=66, blank=True, default='')
    # The deposit's own tx (last_tx_hash moves on with later actions).
    deposit_tx_hash = models.CharField(max_length=66, blank=True, default='')

    # Chain mirror.
    ship_by = models.DateTimeField(null=True, blank=True)
    release_at = models.DateTimeField(null=True, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    dispute_reason = models.CharField(max_length=500, blank=True, default='')
    funded_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    # Stock is reserved when the deposit authorization is issued and handed
    # back only once it provably expired unspent.
    stock_reserved = models.BooleanField(default=False)
    # Block of the last mirrored chain snapshot; older snapshots are dropped.
    chain_block = models.BigIntegerField(default=0)
    # Last block at which the order was seen OPEN: the settlement event lies
    # after it. Only moves while open, so a failed event lookup never skips it.
    open_block = models.BigIntegerField(default=0)
    # How far the settlement-event search has scanned (resumes across syncs).
    settle_scan_block = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['buyer', '-created_at']),
            models.Index(fields=['store', 'status']),
            models.Index(fields=['status', 'release_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'Order {self.public_id} ({self.status})'

    @property
    def fee_usd(self):
        from .pricing import fee_wei
        return Decimal(fee_wei(int(self.amount_wei), self.fee_bps)) / Decimal(10**18)


class OrderRating(models.Model):
    """Reputation counts only completed escrow orders: one rating per order,
    from its buyer, after release."""

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='rating')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='ratings')
    COMMENT_STATUS = [('none', 'No review'), ('pending', 'In review'), ('approved', 'Published'),
                      ('rejected', 'Rejected')]

    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.CharField(max_length=500, blank=True, default='')
    # The stars count at once; the text is public only once the AI reviewer
    # approves it (fail closed: pending or rejected text is never shown).
    comment_status = models.CharField(max_length=10, choices=COMMENT_STATUS, default='none', db_index=True)
    comment_verdict = models.JSONField(default=dict, blank=True)
    comment_reviewed_at = models.DateTimeField(null=True, blank=True)
    comment_queued_at = models.DateTimeField(null=True, blank=True, help_text='Last handed to the reviewer')
    created_at = models.DateTimeField(auto_now_add=True)


class MarketplacePartnerAgreement(models.Model):
    """A local GTM partner's share of the marketplace fee in one country.

    Bolivia: Jason, 50% of the 8% fee, accruing WHILE he stays engaged in
    marketplace GTM, expansion and upkeep. Set `active=False` with an
    `ended_at` the day that stops; released orders after that accrue nothing.
    """

    partner_name = models.CharField(max_length=100)
    partner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='marketplace_partner_agreements')
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES, db_index=True)
    share_bps = models.PositiveIntegerField(
        validators=[MaxValueValidator(10_000)], help_text='Share of the marketplace fee (5000 = 50%)')
    active = models.BooleanField(default=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['country_code'], condition=models.Q(active=True),
                name='marketplace_one_active_partner_per_country'),
        ]

    def __str__(self):
        return f'{self.partner_name} — {self.country_code} {self.share_bps / 100:.0f}%'


class MarketplaceFeeLedger(models.Model):
    """One row per released order: the fee and the partner's share of it.

    Written once, by escrow.sync_order, when the order is released. Top-ups,
    withdrawals, conversion and Pay fees never enter this ledger.
    """

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name='fee_entry')
    country_code = models.CharField(max_length=2, db_index=True)
    gross_usd = models.DecimalField(max_digits=14, decimal_places=6)
    fee_usd = models.DecimalField(max_digits=14, decimal_places=6)
    partner_agreement = models.ForeignKey(
        MarketplacePartnerAgreement, null=True, blank=True, on_delete=models.PROTECT,
        related_name='ledger_entries')
    partner_share_usd = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    confio_share_usd = models.DecimalField(max_digits=14, decimal_places=6)
    released_at = models.DateTimeField(db_index=True)
    partner_paid_at = models.DateTimeField(
        null=True, blank=True, help_text='Set when the monthly partner settlement is paid')

    class Meta:
        ordering = ['-released_at']


class MarketplaceInterest(models.Model):
    """The fake door's answer in a city that is not live yet: who would buy
    or sell, what, at what price, and (sellers) how much they sell today and
    where. An intent probe, never a deposit or a listing.

    Ranges are in US dollars so cities compare across inflationary currencies.
    One row per user and city; answering again updates it.
    """

    ROLE_CHOICES = [('buyer', 'Quiere comprar'), ('seller', 'Quiere vender'), ('both', 'Ambos'),
                    ('browsing', 'Solo miraba')]
    PRICE_CHOICES = [('lt10', '< US$10'), ('10_30', 'US$10–30'), ('30_100', 'US$30–100'),
                     ('100_300', 'US$100–300'), ('gt300', '> US$300')]
    MONTHLY_SALES_CHOICES = [('none', 'Aún no vende'), ('lt200', '< US$200'),
                             ('200_1000', 'US$200–1.000'), ('1000_5000', 'US$1.000–5.000'),
                             ('gt5000', '> US$5.000')]
    CHANNEL_KEYS = {'instagram', 'whatsapp', 'facebook', 'tiktok', 'feria', 'local', 'delivery_app', 'other'}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='marketplace_interests')
    account = models.ForeignKey('users.Account', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES, db_index=True)
    city = models.CharField(max_length=100, db_index=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, db_index=True)
    categories = models.JSONField(default=list, blank=True)
    wants = models.CharField(max_length=300, blank=True, default='',
                             help_text='What they want to buy or sell, in their words')
    price_range = models.CharField(max_length=10, choices=PRICE_CHOICES, blank=True, default='',
                                   help_text='Typical price per item (expected or current)')
    monthly_sales = models.CharField(max_length=10, choices=MONTHLY_SALES_CHOICES, blank=True,
                                     default='', help_text='Sellers: what they sell per month today')
    channels = models.JSONField(default=list, blank=True, help_text='Sellers: where they sell today')
    notify = models.BooleanField(default=True, help_text='Wants to hear when Comprar opens here')
    app_version = models.CharField(max_length=20, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'country_code', 'city'],
                                    name='marketplace_one_interest_per_user_city'),
        ]
        indexes = [models.Index(fields=['country_code', 'city', 'role'])]

    def __str__(self):
        return f'{self.get_role_display()} — {self.city}, {self.country_code}'


class DeliveryAddress(models.Model):
    """A buyer's saved delivery address (Comprar's address book).

    Scoped to the user AND the JWT account they buy from: employees of one
    business never see each other's addresses, and a personal book stays
    personal. The Recarga (KYC) address is not copied here; the book offers
    it live, read-only (schema.recarga_address)."""

    MAX_PER_BOOK = 20

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='delivery_addresses')
    account = models.ForeignKey('users.Account', on_delete=models.CASCADE, related_name='+')
    label = models.CharField(max_length=40, blank=True, default='', help_text='"Casa", "Trabajo"…')
    country_code = models.CharField(max_length=2)
    city = models.CharField(max_length=100)
    address = models.CharField(max_length=300, blank=True, default='')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # Same limits as the order's delivery fields, so a saved address pays as is.
    phone = models.CharField(max_length=20)
    note = models.CharField(max_length=300, blank=True, default='', help_text='Referencia para el repartidor')
    is_default = models.BooleanField(default=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-is_default', '-last_used_at', '-updated_at']
        indexes = [models.Index(fields=['user', 'account', 'deleted_at'])]

    def __str__(self):
        return f'{self.label or "Dirección"} — {self.city}'
