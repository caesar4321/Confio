"""
cUSD+ conversion tracking — the server-side OBSERVER of the client-driven
saga (contracts/cusd_plus/ORCHESTRATION.md).

The server never moves user funds: the client signs every leg. These rows
power resume-on-foreground, the Movimientos history, bridge polling, gas
dusting, reconciliation and support. Mirrors conversion.models.Conversion
conventions (actor pattern, soft delete, uuid internal id).
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class CusdPlusConversion(models.Model):
    DIRECTIONS = [
        ('to_savings', 'cUSD -> cUSD+ (Ahorrar)'),
        ('from_savings', 'cUSD+ -> cUSD (Retirar)'),
    ]

    # Client-driven saga states. Monotonic; every halt leaves value at a
    # user-owned address (never a treasury), so there is no REFUNDING state.
    STATUS_CHOICES = [
        ('CREATED', 'Created (quote accepted, nothing signed)'),
        ('SRC_COMMITTED', 'Source leg committed - bridge in flight'),
        ('STUCK', 'Bridge exceeded timeout - ops attention'),
        ('DEST_ARRIVED', 'Funds at user destination address'),
        ('COMPLETED', 'Final leg committed'),
        ('ABANDONED', 'Never signed - expired'),
    ]

    # Allowed transitions (enforced in the Advance mutation and tasks).
    TRANSITIONS = {
        'CREATED': {'SRC_COMMITTED', 'ABANDONED'},
        'SRC_COMMITTED': {'DEST_ARRIVED', 'STUCK'},
        'STUCK': {'DEST_ARRIVED'},  # late delivery resolves a stuck bridge
        'DEST_ARRIVED': {'COMPLETED'},
        'COMPLETED': set(),
        'ABANDONED': set(),
    }

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # Actor pattern (JWT-derived; never client-supplied account ids)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cusd_plus_conversions',
        null=True,
        blank=True,
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='cusd_plus_conversions',
        null=True,
        blank=True,
    )
    actor_type = models.CharField(
        max_length=10,
        choices=[('user', 'Personal'), ('business', 'Business')],
    )
    actor_display_name = models.CharField(max_length=255, blank=True)

    # How the row was born. 'convert' rows start at CREATED from a user
    # quote; chain-observed inflows (external USDT sends, ramp deliveries)
    # are born directly at DEST_ARRIVED — the funds are already at the
    # user's address, so only leg C (mint) remains. Keeps inflow accounting
    # honest: a conversion moves existing Confío money, the others are NEW.
    SOURCES = [
        ('convert', 'In-app conversion (user-quoted)'),
        ('external_deposit', 'External USDT-BSC deposit'),
        ('ramp', 'Ramp (Koywe) delivery'),
    ]

    direction = models.CharField(max_length=15, choices=DIRECTIONS)
    source = models.CharField(max_length=20, choices=SOURCES, default='convert')
    amount_usd = models.DecimalField(max_digits=19, decimal_places=6)
    quoted_cost_pct = models.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal('0'),
        help_text='Total cost pct the user accepted (client-quoted, decision b)',
    )
    quoted_receive_usd = models.DecimalField(max_digits=19, decimal_places=6)

    # The user's own addresses on both chains (non-custodial; informational)
    user_algo_address = models.CharField(max_length=58, blank=True)
    user_bsc_address = models.CharField(max_length=42, blank=True)

    # Chain references, keyed for idempotent resume + support
    src_tx_id = models.CharField(
        max_length=88, blank=True,
        help_text='Source-chain tx id (leg AB group txid on ALG / redeem tx on BSC); also the Allbridge tracking key',
    )
    dest_tx_hash = models.CharField(
        max_length=88, blank=True,
        help_text='Final-leg tx (vault mint on BSC / auto-swap on ALG)',
    )
    bridge_arrival_tx = models.CharField(
        max_length=88, blank=True,
        help_text='On-chain arrival tx at the user destination (chain-observed, not vendor-reported)',
    )
    dest_scan_from_block = models.BigIntegerField(
        null=True, blank=True,
        help_text='Destination-chain scan cursor set when monitoring starts',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CREATED')
    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    src_committed_at = models.DateTimeField(blank=True, null=True)
    dest_arrived_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    # Soft delete (house rule)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'cusd_plus_conversions'
        indexes = [
            models.Index(fields=['actor_user', 'status'], name='cpc_user_status_idx'),
            models.Index(fields=['status', 'updated_at'], name='cpc_status_updated_idx'),
        ]

    IN_FLIGHT_STATUSES = ('CREATED', 'SRC_COMMITTED', 'STUCK', 'DEST_ARRIVED')

    def can_transition(self, new_status: str) -> bool:
        return new_status in self.TRANSITIONS.get(self.status, set())

    def __str__(self):
        return f'{self.direction} {self.amount_usd} [{self.status}] {self.internal_id}'
