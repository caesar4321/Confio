from django.db import models
from django.conf import settings
import uuid
from django.utils import timezone
from decimal import Decimal


class Conversion(models.Model):
    """Every conversion between two Confío-held tokens, on either chain.

    ONE model for both rails, the same way SendTransaction covers Algorand
    and BSC: chain-specific tokens are extra `CONVERSION_TYPES`, chain-
    specific stages are extra `STATUS_CHOICES`, and chain-specific tracking
    lives in nullable columns (SendTransaction's `bsc_calls_json` pattern).

    The BSC savings rows (to_savings / from_savings) are a resumable SAGA
    rather than a one-shot swap, so they use the extra statuses and the
    bridge/scan columns below; the Algorand rows leave those null. Merged
    from a parallel CusdPlusConversion model on 2026-08-01 — the fork made
    UnifiedTransactionTable carry two FKs for one concept, and every reader
    that checked only one silently mis-rendered the other's rows.
    """

    CONVERSION_TYPES = [
        ('usdc_to_cusd', 'USDC to cUSD'),
        ('cusd_to_usdc', 'cUSD to USDC'),
        # Coinbase offramp leg: Tinyman USDC→ALGO + payment to Coinbase's
        # sell deposit address in one atomic group.
        ('usdc_to_algo', 'USDC to ALGO'),
        # BSC savings rails. The on-chain leg is always USDT <-> cUSD+
        # whatever the origin (in-app convert, external deposit, ramp);
        # the origin is `source`.
        ('to_savings', 'USDT -> cUSD+ (Ahorrar)'),
        ('from_savings', 'cUSD+ -> USDT (Retirar)'),
        ('usdt_to_cusd', 'USDT -> cUSD (BSC)'),
        ('cusd_to_usdt', 'cUSD -> USDT (BSC)'),
    ]

    # All BSC dollar conversions share the exact-fee/sponsored ledger and
    # unified-history writer. The historical name remains for compatibility.
    SAVINGS_TYPES = frozenset({
        'to_savings', 'from_savings', 'usdt_to_cusd', 'cusd_to_usdt',
    })

    # The token pair each type moves, in display form. Single source of truth:
    # the unified ledger and the GraphQL type both read it. Every reader used
    # to keep its own copy that fell through to USDC->cUSD for anything it did
    # not recognise, which mislabelled usdc_to_algo from the day it was added
    # and every savings row from the day they merged in.
    TOKEN_PAIRS = {
        'usdc_to_cusd': ('USDC', 'cUSD'),
        'cusd_to_usdc': ('cUSD', 'USDC'),
        'usdc_to_algo': ('USDC', 'ALGO'),
        'to_savings': ('USDT', 'cUSD+'),
        'from_savings': ('cUSD+', 'USDT'),
        'usdt_to_cusd': ('USDT', 'cUSD'),
        'cusd_to_usdt': ('cUSD', 'USDT'),
    }

    @property
    def from_token(self):
        """Source token, or None for an unrecognised type — never a guess."""
        pair = self.TOKEN_PAIRS.get(self.conversion_type)
        return pair[0] if pair else None

    @property
    def to_token(self):
        pair = self.TOKEN_PAIRS.get(self.conversion_type)
        return pair[1] if pair else None

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PENDING_SIG', 'Pending Signature'),
        ('SUBMITTED', 'Submitted'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        # Savings-saga stages. Client-driven and monotonic; every halt leaves
        # value at a user-owned address (never a treasury), so there is no
        # REFUNDING state.
        ('CREATED', 'Created (quote accepted, nothing signed)'),
        ('SRC_COMMITTED', 'Source leg committed - bridge in flight'),
        ('STUCK', 'Bridge exceeded timeout - ops attention'),
        ('DEST_ARRIVED', 'Funds at user destination address'),
        ('ABANDONED', 'Never signed - expired'),
        # Terminal, and NOT a failure: the money arrived and remains raw USDT
        # because this mint attempt was refused (eligibility or safe-amount
        # floor). It may be converted later with other funds as a new event.
        ('DELIVERED_USDT', 'Delivered as raw USDT'),
    ]

    # Allowed saga transitions (enforced in the Advance mutation and tasks).
    # Applies to SAVINGS_TYPES rows only — the Algorand swap rows use the
    # flat statuses above, exactly as SPONSORING/SIGNED apply only to
    # sponsored sends.
    TRANSITIONS = {
        'CREATED': {'SRC_COMMITTED', 'ABANDONED'},
        'SRC_COMMITTED': {'DEST_ARRIVED', 'STUCK'},
        'STUCK': {'DEST_ARRIVED'},  # late delivery resolves a stuck bridge
        'DEST_ARRIVED': {'COMPLETED', 'DELIVERED_USDT'},
        'COMPLETED': set(),
        'ABANDONED': set(),
        'DELIVERED_USDT': set(),
    }

    IN_FLIGHT_STATUSES = ('CREATED', 'SRC_COMMITTED', 'STUCK', 'DEST_ARRIVED')

    # How the row was born. 'convert' rows start at CREATED from a user
    # quote; chain-observed inflows (external USDT sends, ramp deliveries)
    # are born directly at DEST_ARRIVED — the funds are already at the
    # user's address, so only the mint leg remains. Keeps inflow accounting
    # honest: a conversion moves existing Confío money, the others are NEW.
    SOURCES = [
        ('convert', 'In-app conversion (user-quoted)'),
        ('external_deposit', 'External USDT-BSC deposit'),
        ('ramp', 'Ramp (Koywe) delivery'),
    ]

    ASSET_CHOICES = [
        ('CUSD_ALGO', 'cUSD (Algorand)'),
        ('USDC_ALGO', 'USDC (Algorand)'),
        ('USDT_BSC', 'USDT (BSC)'),
        ('CUSD_BSC', 'cUSD (BSC)'),
        ('CUSD_PLUS_BSC', 'cUSD+ (BSC)'),
    ]
    PERIMETER_DIRECTIONS = [
        ('entry', 'USDT -> Confio dollars'),
        ('exit', 'Confio dollars -> USDT'),
        ('internal', 'cUSD <-> cUSD+'),
    ]

    # Unique identifier
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Direct User/Business actor pattern
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_conversions',
        null=True,
        blank=True,
        help_text='User who initiated the conversion (if personal account)'
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='business_conversions',
        null=True,
        blank=True,
        help_text='Business that initiated the conversion (if business account)'
    )
    
    ACTOR_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
    ]
    
    actor_type = models.CharField(
        max_length=10,
        choices=ACTOR_TYPE_CHOICES,
        help_text='Type of actor (user or business)'
    )
    actor_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name of the actor at conversion time'
    )
    actor_address = models.CharField(
        max_length=66,
        blank=True,
        help_text='Blockchain address of the actor'
    )
    
    # Conversion details
    conversion_type = models.CharField(max_length=20, choices=CONVERSION_TYPES)
    from_amount = models.DecimalField(max_digits=19, decimal_places=6)  # Amount being converted from
    to_amount = models.DecimalField(max_digits=19, decimal_places=6)  # Amount received after conversion
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal('1.000000'))  # Exchange rate used
    fee_amount = models.DecimalField(max_digits=19, decimal_places=6, default=Decimal('0'))  # Fee charged (if any)

    # Exact BSC fee ledger. The six-decimal fields above remain compatibility
    # projections for existing clients; contract reconciliation uses these
    # 18-decimal values and never reconstructs a fee from rounded display
    # amounts.
    gross_amount_exact = models.DecimalField(
        max_digits=78, decimal_places=18, null=True, blank=True,
        help_text='Authoritative gross amount from the prepared call/contract event.',
    )
    fee_amount_exact = models.DecimalField(
        max_digits=78, decimal_places=18, null=True, blank=True,
        help_text='Authoritative Confio conversion fee at token precision.',
    )
    net_amount_exact = models.DecimalField(
        max_digits=78, decimal_places=18, null=True, blank=True,
        help_text='Authoritative net amount after the conversion fee.',
    )
    conversion_fee_bps = models.PositiveSmallIntegerField(null=True, blank=True)
    from_asset_id = models.CharField(max_length=32, choices=ASSET_CHOICES, blank=True, default='')
    to_asset_id = models.CharField(max_length=32, choices=ASSET_CHOICES, blank=True, default='')
    perimeter_direction = models.CharField(
        max_length=10, choices=PERIMETER_DIRECTIONS, blank=True, default='',
    )
    prepared_intent_id = models.UUIDField(null=True, blank=True, unique=True)
    contract_event_index = models.PositiveIntegerField(null=True, blank=True)
    
    # Transaction hashes for blockchain tracking. 88 chars fits an Algorand
    # base32 txid as well as an 0x EVM hash.
    from_transaction_hash = models.CharField(max_length=88, blank=True, null=True)  # source-token tx (saga: source leg / Allbridge key)
    to_transaction_hash = models.CharField(max_length=88, blank=True, null=True)  # destination-token tx (saga: final mint/swap)

    # ── Savings-saga columns (null on the Algorand swap rows) ────────────
    source = models.CharField(
        max_length=20, choices=SOURCES, default='convert',
        help_text='How the row was born (savings rows; Algorand swaps are always in-app)',
    )
    quoted_cost_pct = models.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal('0'),
        help_text='Total cost pct the user accepted at quote time',
    )
    user_bsc_address = models.CharField(
        max_length=42, blank=True,
        help_text="The user's own BSC address (non-custodial; informational). "
                  'The Algorand side lives in actor_address.',
    )
    bridge_arrival_tx = models.CharField(
        max_length=88, blank=True,
        help_text='On-chain arrival at the user destination (chain-observed, not vendor-reported)',
    )
    dest_scan_from_block = models.BigIntegerField(
        null=True, blank=True,
        help_text='Destination-chain scan cursor set when monitoring starts',
    )
    src_committed_at = models.DateTimeField(blank=True, null=True)
    dest_arrived_at = models.DateTimeField(blank=True, null=True)

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    
    # Soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
        db_table = 'conversions'
        indexes = [
            models.Index(fields=['actor_user', 'status'], name='conv_actor_user_status_idx'),
            models.Index(fields=['actor_business', 'status'], name='conv_actor_bus_status_idx'),
            models.Index(fields=['actor_type', 'status'], name='conv_actor_type_status_idx'),
            models.Index(fields=['internal_id']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['to_transaction_hash', 'contract_event_index'],
                condition=(
                    models.Q(contract_event_index__isnull=False)
                    & models.Q(to_transaction_hash__isnull=False)
                    & ~models.Q(to_transaction_hash='')
                ),
                name='uniq_conversion_contract_event',
            ),
        ]
    
    def __str__(self):
        actor_name = self.actor_display_name or "Unknown"
        return f"{actor_name} - {self.get_conversion_type_display()} - {self.from_amount} to {self.to_amount} - {self.status}"
    
    def clean(self):
        """Validate that either actor_user or actor_business is set, but not both"""
        from django.core.exceptions import ValidationError
        
        if self.actor_type == 'user' and not self.actor_user:
            raise ValidationError("actor_user must be set when actor_type is 'user'")
        elif self.actor_type == 'business' and not self.actor_business:
            raise ValidationError("actor_business must be set when actor_type is 'business'")
        
        if self.actor_user and self.actor_business:
            raise ValidationError("Only one of actor_user or actor_business should be set")

        exact = (self.gross_amount_exact, self.fee_amount_exact, self.net_amount_exact)
        if any(value is not None for value in exact):
            if any(value is None for value in exact):
                raise ValidationError('gross, fee, and net exact amounts must be stored together')
            if any(value < 0 for value in exact):
                raise ValidationError('exact conversion amounts cannot be negative')
            if self.gross_amount_exact != self.fee_amount_exact + self.net_amount_exact:
                raise ValidationError('exact fee plus net must equal gross')
        if self.conversion_fee_bps is not None and self.conversion_fee_bps > 90:
            raise ValidationError('conversion fee exceeds the immutable 90 bps ceiling')
    
    @property
    def is_savings(self) -> bool:
        """A BSC savings saga row rather than an Algorand one-shot swap."""
        return self.conversion_type in self.SAVINGS_TYPES

    def can_transition(self, new_status: str) -> bool:
        return new_status in self.TRANSITIONS.get(self.status, set())

    @property
    def is_completed(self):
        return self.status == 'COMPLETED'

    @property
    def is_failed(self):
        return self.status == 'FAILED'
    
    def mark_completed(self, to_transaction_hash=None):
        """Mark the conversion as completed"""
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        if to_transaction_hash:
            self.to_transaction_hash = to_transaction_hash
        self.save()
    
    def mark_failed(self, error_message):
        """Mark the conversion as failed"""
        self.status = 'FAILED'
        self.error_message = error_message
        self.save()


class CusdFeeScanState(models.Model):
    """Durable finalized-log cursor for permissionless cUSD exits."""

    chain_id = models.PositiveBigIntegerField(primary_key=True)
    last_finalized_block = models.PositiveBigIntegerField(default=0)
    last_finalized_hash = models.CharField(max_length=66, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cusd_fee_scan_state'


# Update unified user activity on new conversions
from django.db.models.signals import post_save
from django.dispatch import receiver
from users.utils import touch_user_activity


@receiver(post_save, sender=Conversion)
def conversion_activity(sender, instance: Conversion, created, **kwargs):
    if created:
        try:
            if instance.actor_user_id:
                touch_user_activity(instance.actor_user_id)
        except Exception:
            pass
