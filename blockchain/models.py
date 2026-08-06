from django.db import models
from django.conf import settings
from django.utils import timezone
from users.models import Account


class Balance(models.Model):
    """Cached token balances for accounts"""
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='balances')
    token = models.CharField(max_length=20, choices=[
        ('ALGO', 'ALGO'),
        ('CUSD', 'cUSD'),
        ('CONFIO', 'CONFIO'),
        ('CONFIO_PRESALE', 'CONFIO_PRESALE'),
        ('USDC', 'USDC'),
    ])
    amount = models.DecimalField(max_digits=36, decimal_places=18)
    pending_amount = models.DecimalField(max_digits=36, decimal_places=18, default=0)  # For in-flight transactions
    last_synced = models.DateTimeField(auto_now=True)
    is_stale = models.BooleanField(default=False, help_text="True if balance needs refresh")
    last_blockchain_check = models.DateTimeField(null=True, blank=True)
    sync_attempts = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ['account', 'token']
        indexes = [
            models.Index(fields=['account', 'token']),
            models.Index(fields=['is_stale', 'last_synced']),
        ]
    
    def __str__(self):
        return f"{self.account} - {self.amount} {self.token}"
    
    @property
    def available_amount(self):
        """Amount available for spending (total - pending)"""
        return self.amount - self.pending_amount
    
    def mark_stale(self):
        """Mark balance as needing refresh"""
        self.is_stale = True
        self.save(update_fields=['is_stale'])




class Payment(models.Model):
    """Track payments made through the payment smart contract"""
    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    CURRENCY_CHOICES = [
        ('CUSD', 'cUSD'),
        ('CONFIO', 'CONFIO'),
        ('USDC', 'USDC'),
        ('ALGO', 'ALGO'),
    ]
    
    # Payment ID for tracking
    internal_id = models.CharField(max_length=100, unique=True, db_index=True)
    
    # Parties involved
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payments_sent'
    )
    sender_business = models.ForeignKey(
        'users.Business',
        on_delete=models.PROTECT,
        related_name='payments_sent',
        null=True,
        blank=True,
        help_text="Business account that sent the payment (if from business)"
    )
    
    # Recipients - always businesses in payment contract flow
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payments_received',
        null=True,
        blank=True,
        help_text="Business owner (for tracking)"
    )
    recipient_business = models.ForeignKey(
        'users.Business',
        on_delete=models.PROTECT,
        related_name='payments_received',
        null=True,
        blank=True,
        help_text="Business that received the payment"
    )
    
    # Payment details
    amount = models.DecimalField(max_digits=36, decimal_places=18)
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES)
    fee_amount = models.DecimalField(max_digits=36, decimal_places=18, default=0)
    net_amount = models.DecimalField(max_digits=36, decimal_places=18)
    
    # Blockchain details
    blockchain_network = models.CharField(max_length=20, default='algorand')
    sender_address = models.CharField(max_length=100)
    recipient_address = models.CharField(max_length=100)
    transaction_hash = models.CharField(max_length=100, blank=True, db_index=True)
    confirmed_at_block = models.BigIntegerField(null=True, blank=True)
    
    # Status and metadata
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    note = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    blockchain_data = models.JSONField(null=True, blank=True, help_text="Store sponsor transactions and other blockchain data")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['sender', 'status', '-created_at']),
            models.Index(fields=['recipient', 'status', '-created_at']),
            models.Index(fields=['internal_id']),
            models.Index(fields=['transaction_hash']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Payment {self.internal_id[:8]}... ({self.amount} {self.currency})"


class PaymentReceipt(models.Model):
    """On-chain payment receipts stored in contract boxes"""
    payment = models.OneToOneField(
        Payment,
        on_delete=models.CASCADE,
        related_name='receipt'
    )
    transaction_hash = models.CharField(max_length=100, unique=True, db_index=True)
    block_number = models.BigIntegerField()
    receipt_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['block_number']),
        ]
    
    def __str__(self):
        return f"Receipt for {self.payment.internal_id[:8]}..."



class ProcessedIndexerTransaction(models.Model):
    """Idempotency guard for processed on-chain transactions from the Indexer."""
    txid = models.CharField(max_length=100, db_index=True)
    asset_id = models.BigIntegerField(null=True, blank=True)
    sender = models.CharField(max_length=100, blank=True)
    receiver = models.CharField(max_length=100, blank=True)
    confirmed_round = models.BigIntegerField(default=0)
    intra = models.IntegerField(default=0, help_text="Intra-round offset if available")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['asset_id', 'confirmed_round']),
            models.Index(fields=['receiver']),
        ]
        unique_together = [('txid', 'intra')]

    def __str__(self):
        return f"{self.txid[:10]}... ({self.asset_id})"


class IndexerAssetCursor(models.Model):
    """Per-asset global cursor for Indexer scanning (asset-centric strategy)."""
    asset_id = models.BigIntegerField(unique=True, db_index=True)
    last_scanned_round = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['last_scanned_round']),
        ]

    def __str__(self):
        return f"asset:{self.asset_id} @ {self.last_scanned_round}"


class PendingAutoSwap(models.Model):
    """Actionable auto-swap work that must be completed by the client signer."""

    ASSET_CHOICES = [
        ('USDC', 'USDC'),
        ('ALGO', 'ALGO'),
        # BSC twin: mis-deposited native BNB swapped to USDT via PancakeSwap.
        # Rows are the authoritative allowlist for outbound native BNB — an
        # outbound transfer absent from this table is dust extraction and
        # disqualifies the address's owner from further gas/MBR subsidies.
        # (Merged 2026-08-01 from a 4-field cusd_plus.BnbAutoConvert, which
        # was this same concept written fresh inside the BSC app.)
        ('BNB', 'BNB'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUBMITTED', 'Submitted'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='pending_auto_swaps',
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pending_auto_swaps',
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pending_auto_swaps',
    )
    actor_type = models.CharField(
        max_length=10,
        choices=[('user', 'Personal'), ('business', 'Business')],
        default='user',
    )
    actor_address = models.CharField(max_length=100, blank=True, default='')
    asset_type = models.CharField(max_length=10, choices=ASSET_CHOICES)
    amount_micro = models.BigIntegerField(default=0)
    amount_decimal = models.DecimalField(max_digits=19, decimal_places=6, default=0)
    source_address = models.CharField(max_length=100, blank=True, default='')
    source_tx_hash = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True)
    usdc_deposit = models.OneToOneField(
        'usdc_transactions.USDCDeposit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_auto_swap',
    )
    conversion = models.OneToOneField(
        'conversion.Conversion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_auto_swap',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['account', 'status', '-created_at']),
            models.Index(fields=['actor_user', 'status', '-created_at']),
            models.Index(fields=['actor_business', 'status', '-created_at']),
            models.Index(fields=['asset_type', 'status', '-created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.account_id}:{self.asset_type}:{self.status}:{self.amount_decimal}"


# ── EVM sponsorship ─────────────────────────────────────────────────────
# Moved out of the cusd_plus app on 2026-08-01: this ledger is written by
# send, payments, payroll, presale and invites — it is chain infrastructure
# like the models above, not a savings feature. Only the app label and the
# table name changed; the rows never moved.
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
        # 'signed' is the DURABLE pre-broadcast state (audit 2026-07-31
        # P1-2): the row + deterministic tx_hash are written BEFORE
        # eth_sendRawTransaction, so a crash mid-broadcast leaves a
        # reconcilable record instead of a lost chain tx.
        ('signed', 'Signed, broadcast unconfirmed'),
        ('sent', 'Broadcast, receipt pending'),
        ('confirmed', 'Mined, executed and final'),
        ('reverted', 'Mined but reverted'),
        ('noop_failed', 'Mined, but delegation did not apply (no-op)'),
        ('reorged', 'Was mined then orphaned by a reorg'),
        # A 'signed' row whose deterministic hash no node knows after the
        # grace window: the broadcast never landed and the KMS-signed raw is
        # not reproducible. Terminal-fail so the domain flow fails and the
        # user can retry (the delegate's monotonic nonce makes a retry safe).
        ('dropped', 'Signed but never reached the chain'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='sponsored_batches',
    )
    user_bsc_address = models.CharField(max_length=42)
    # 'subscribe' | 'redeem' | 'presale_buy' | Phase-2 kinds:
    # send_cusd_plus | send_redeem | send_usdt | send_confio | pay_cusd_plus |
    # pay_usdt | pay_confio | payroll_fund | payroll_payout | invite_create |
    # invite_reclaim | ...
    kind = models.CharField(max_length=32)
    # The domain row this batch settles (SendTransaction / PaymentTransaction
    # / PayrollItem / …) — confirm tasks verify (kind, source_id, tx_hash)
    # against the row before settling, so one batch can only settle its own
    # source (audit P2 batch isolation).
    source_id = models.BigIntegerField(null=True, blank=True)
    num_calls = models.PositiveSmallIntegerField()
    calls_json = models.TextField()
    tx_hash = models.CharField(max_length=66, blank=True)
    # Delegate nonce (7702) or 0 for plain KMS txs — matched against the
    # BatchExecuted(nonce,...) log to prove the batch actually executed.
    delegate_nonce = models.BigIntegerField(null=True, blank=True)
    # Finality: the block the receipt landed in; re-checked canonical before
    # settling and after, so a reorg flips the row to 'reorged'.
    block_number = models.BigIntegerField(null=True, blank=True)
    block_hash = models.CharField(max_length=66, blank=True)
    gas_limit = models.PositiveIntegerField()
    # Wei doesn't fit typical decimal columns; store as digits string.
    max_fee_wei = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='sent')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'sponsored_batches'
        indexes = [
            models.Index(fields=['user', 'created_at'], name='cpsb_user_created_idx'),
            models.Index(fields=['tx_hash'], name='cpsb_tx_hash_idx'),
            models.Index(fields=['status'], name='cpsb_status_idx'),
            models.Index(fields=['kind', 'source_id'], name='cpsb_kind_source_idx'),
        ]
        constraints = [
            # One batch per tx hash — blocks the same broadcast being
            # recorded twice (audit P2 batch isolation). Partial so legacy
            # blank-hash rows don't collide.
            models.UniqueConstraint(
                fields=['tx_hash'],
                condition=models.Q(tx_hash__gt=''),
                name='cpsb_unique_tx_hash',
            ),
            # ONE live batch per presale purchase. The application-level guard
            # in presale.bsc_flow.submit_purchase can be beaten: two requests
            # can both pass its existence check before either writes a row,
            # and the cache claim backing it is not a correctness boundary (a
            # flush, per-worker LocMemCache, or a TTL expiring during a stall
            # all drop it). Without this a prepared batch could be re-signed
            # with a fresh delegate nonce and executed twice — redeeming the
            # user's savings and calling buy() again while the database books
            # one purchase.
            #
            # Scoped to the LIVE statuses on purpose: reverted / noop_failed /
            # reorged / dropped are exactly the cases a user must be able to
            # retry, and leaving those states frees the slot automatically.
            models.UniqueConstraint(
                fields=['kind', 'source_id'],
                condition=models.Q(
                    kind='presale_buy',
                    status__in=('signed', 'sent', 'confirmed'),
                ),
                name='cpsb_unique_active_presale_buy',
            ),
            # Same protection for wages. Without it two concurrent submits of
            # one PREPARED item both broadcast: the first pays, the second
            # reverts on the contract's itemUsed guard, and then they race to
            # write item.transaction_hash. If the reverting one wins, a wage
            # that actually paid is recorded FAILED and the retry can never
            # succeed because the item id is spent on chain. The sponsor
            # nonce lock serialises nonces, not items — this claims the item.
            models.UniqueConstraint(
                fields=['kind', 'source_id'],
                condition=models.Q(
                    kind='payroll_payout',
                    status__in=('signed', 'sent', 'confirmed'),
                ),
                name='cpsb_unique_active_payroll_payout',
            ),
            # And for invoices. Two concurrent submits of one
            # PENDING_BLOCKCHAIN payment both passed the unlocked status check
            # and both broadcast: one paid the merchant, the other reverted on
            # the contract's invoiceDone guard, and then they clobbered each
            # other's transaction_hash. If the reverting one landed last, the
            # successful batch's confirmer refused its own settlement (hash
            # mismatch) and the reverting one marked the payment FAILED — a
            # merchant paid, an invoice still PENDING, and a payer told it
            # failed. One live batch per payment, whatever the token.
            # Keyed on source_id ALONE, not (kind, source_id): the funding
            # token is part of `kind`, so keying on both let one payment hold a
            # live pay_cusd_plus batch AND a live pay_usdt batch at once — a
            # re-prepare after changed balances picks a different token and
            # slips straight past the index. Both broadcast; the contract stops
            # the second payout, but the losing batch can still be the hash the
            # database adopts, leaving the invoice FAILED after the merchant
            # was paid. The condition keeps this scoped to payment batches.
            models.UniqueConstraint(
                fields=['source_id'],
                condition=models.Q(
                    kind__in=('pay_cusd_plus', 'pay_usdt', 'pay_confio'),
                    status__in=('signed', 'sent', 'confirmed'),
                ),
                name='cpsb_unique_active_payment',
            ),
        ]

    def __str__(self):
        return f'7702 {self.kind} x{self.num_calls} [{self.status}] {self.tx_hash or "pending"}'


# ── Solana sponsorship ──────────────────────────────────────────────────
class SolanaSponsorDailySpend(models.Model):
    """Durable per-account fee reservation for one UTC day."""

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='solana_sponsor_daily_spend',
    )
    day = models.DateField()
    spent_lamports = models.BigIntegerField(default=0)
    transaction_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'day'],
                name='solana_spend_account_day_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(spent_lamports__gte=0),
                name='solana_account_spend_nonnegative',
            ),
        ]


class SolanaSponsorGlobalDailySpend(models.Model):
    """Single locked row per UTC day for the relay-wide circuit breaker."""

    day = models.DateField(unique=True)
    spent_lamports = models.BigIntegerField(default=0)
    transaction_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(spent_lamports__gte=0),
                name='solana_global_spend_nonnegative',
            ),
        ]


class SolanaSponsorBalanceState(models.Model):
    """Singleton lock and last observed sponsor balance across day rollovers."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    observed_balance_lamports = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(observed_balance_lamports__gte=0),
                name='sol_sponsor_observed_balance_nonnegative',
            ),
        ]


class SolanaSponsoredTransaction(models.Model):
    """Pre-broadcast audit record and idempotency key for a sponsored message."""

    STATUS_CHOICES = [
        ('reserved', 'Fee reserved, broadcast not confirmed'),
        ('signed', 'Sponsor signature recorded before RPC exposure'),
        ('sent', 'RPC accepted transaction'),
        ('unknown', 'Broadcast outcome unknown'),
        ('confirmed_pending', 'Confirmed; awaiting a balance observation at that slot'),
        ('confirmed', 'Transaction reached confirmed commitment'),
        ('expired', 'Blockhash expired without a recorded transaction'),
        ('failed', 'Failed before a sponsor signature was exposed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='solana_sponsored_transactions',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='solana_sponsored_transactions',
    )
    message_hash = models.CharField(max_length=64, unique=True)
    recent_blockhash = models.CharField(max_length=64)
    confirmation_slot = models.BigIntegerField(null=True, blank=True)
    fee_lamports = models.BigIntegerField()
    signature = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='reserved')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['account', 'created_at'], name='sol_sponsor_acct_created'),
            models.Index(fields=['status'], name='sol_sponsor_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fee_lamports__gte=0),
                name='sol_sponsor_fee_nonnegative',
            ),
        ]
