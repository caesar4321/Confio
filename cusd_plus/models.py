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
    # The on-BSC leg is always USDT <-> cUSD+, whatever the origin (bridge
    # saga, external deposit, ramp) — origin is the `source` field. The old
    # labels said "cUSD -> cUSD+", which was only true for the bridge saga
    # and read wrong on external USDT deposits in the admin.
    DIRECTIONS = [
        ('to_savings', 'USDT -> cUSD+ (Ahorrar)'),
        ('from_savings', 'cUSD+ -> USDT (Retirar)'),
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


class BnbAutoConvert(models.Model):
    """Ledger of relay-observed BNB→USDT auto-convert swaps.

    Mis-deposited BNB at a user's BSC address is swapped to USDT via
    PancakeSwap (client-signed, mirrors the mainnet ALGO→USDC auto-convert).
    Every row is written by the relay at submission time, so this table is
    the authoritative allowlist for outbound native BNB: an outbound BNB
    transfer NOT in this table is dust extraction (farming) and disqualifies
    the address's owner from further gas/MBR subsidies. The swap's USDT
    output lands at the user's own address, where monitor_bridge_arrivals
    picks it up like any external deposit.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='bnb_auto_converts',
    )
    # Wei doesn't fit typical decimal columns; store as digits string.
    value_wei = models.CharField(max_length=32)
    tx_hash = models.CharField(max_length=66, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        db_table = 'cusd_plus_bnb_auto_converts'
        indexes = [
            models.Index(fields=['user', 'created_at'], name='cpbac_user_created_idx'),
            models.Index(fields=['tx_hash'], name='cpbac_tx_hash_idx'),
        ]

    def __str__(self):
        return f'BNB autoconvert {self.value_wei} wei [{self.tx_hash or "pending"}]'


class SponsoredBatch(models.Model):
    """Audit ledger of EIP-7702 sponsored batch executions (sponsor_7702).

    One row per type-4 transaction the sponsor broadcast on a user's
    behalf: the exact validated call batch, the gas ceiling the sponsor
    committed to, and the receipt outcome. `noop_failed` flags the 7702
    silent-failure mode — the tx mined "successfully" but emitted no logs,
    meaning the delegation never applied (authorization nonce raced) and
    nothing executed; the client retries with a fresh authorization.
    """
    STATUS_CHOICES = [
        ('sent', 'Broadcast, receipt pending'),
        ('confirmed', 'Mined and executed'),
        ('reverted', 'Mined but reverted'),
        ('noop_failed', 'Mined, but delegation did not apply (no-op)'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='sponsored_batches',
    )
    user_bsc_address = models.CharField(max_length=42)
    # 'subscribe' | 'redeem' | 'presale_buy' | Phase-2 kinds:
    # send_cusd_plus | send_redeem | send_usdt | pay_cusd_plus | pay_usdt |
    # payroll_fund | payroll_payout
    kind = models.CharField(max_length=32)
    num_calls = models.PositiveSmallIntegerField()
    calls_json = models.TextField()
    tx_hash = models.CharField(max_length=66, blank=True)
    gas_limit = models.PositiveIntegerField()
    # Wei doesn't fit typical decimal columns; store as digits string.
    max_fee_wei = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='sent')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'cusd_plus_sponsored_batches'
        indexes = [
            models.Index(fields=['user', 'created_at'], name='cpsb_user_created_idx'),
            models.Index(fields=['tx_hash'], name='cpsb_tx_hash_idx'),
            models.Index(fields=['status'], name='cpsb_status_idx'),
        ]

    def __str__(self):
        return f'7702 {self.kind} x{self.num_calls} [{self.status}] {self.tx_hash or "pending"}'


class CusdPlusMovement(models.Model):
    """The savings-account ledger: one human-legible row per money event on
    the BSC dollar account (deposits, withdrawals, sends, receives,
    payments, payroll, stock buys/sells, weekly yield summaries).

    This is a DISPLAY ledger, not an accounting source of truth — the chain
    is. Rows are written by confirm tasks / the inbound scanner, idempotent
    on `reference` so replays and rescans never duplicate. Feeds
    cusdPlusMovements (SavingsScreen's Movimientos + SavingsMovements).
    """
    MOVEMENT_TYPES = [
        ('deposit', 'Deposit into savings'),
        ('withdraw', 'Withdrawal from savings'),
        ('send', 'Sent to someone'),
        ('receive', 'Received'),
        ('payment', 'Paid a business'),
        ('payroll', 'Payroll'),
        ('buy', 'Stock buy'),
        ('sell', 'Stock sell'),
        ('yield', 'Yield summary'),
    ]

    account = models.ForeignKey(
        'users.Account', on_delete=models.CASCADE,
        related_name='cusd_plus_movements',
    )
    movement_type = models.CharField(max_length=16, choices=MOVEMENT_TYPES)
    title = models.CharField(max_length=120)
    # Signed: inflows to the account positive, outflows negative.
    amount_usd = models.DecimalField(max_digits=20, decimal_places=6)
    tx_hash = models.CharField(max_length=66, blank=True)
    # Idempotency + provenance: 'send_transaction:<id>',
    # 'conversion:<internal_id>', 'scan:<txhash>:<logIndex>', ...
    reference = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        db_table = 'cusd_plus_movements'
        indexes = [
            models.Index(fields=['account', 'created_at'], name='cpmov_acct_created_idx'),
        ]

    def __str__(self):
        return f'{self.movement_type} {self.amount_usd} [{self.reference}]'
