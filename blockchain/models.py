from django.db import models
from django.conf import settings
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
