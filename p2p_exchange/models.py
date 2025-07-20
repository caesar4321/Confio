from django.db import models
from django.conf import settings
from users.models import SoftDeleteModel
from django.core.validators import MinValueValidator, MaxValueValidator

class P2PPaymentMethod(SoftDeleteModel):
    """Payment methods available for P2P trading"""
    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    icon = models.CharField(max_length=50, blank=True)  # For frontend icon reference
    
    class Meta:
        ordering = ['display_name']
    
    def __str__(self):
        return self.display_name

class P2POffer(SoftDeleteModel):
    """P2P trading offers/orders in the marketplace"""
    EXCHANGE_TYPES = [
        ('BUY', 'Buy'),   # User wants to buy crypto (sell fiat)
        ('SELL', 'Sell'), # User wants to sell crypto (buy fiat)
    ]
    
    TOKEN_TYPES = [
        ('cUSD', 'Confío Dollar'),
        ('CONFIO', 'Confío Token'),
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    # User who created the exchange offer
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_offers'
    )
    
    # Exchange details
    exchange_type = models.CharField(max_length=4, choices=EXCHANGE_TYPES)
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    
    # Pricing
    rate = models.DecimalField(max_digits=10, decimal_places=2)  # Rate in fiat per token
    min_amount = models.DecimalField(max_digits=10, decimal_places=2)  # Min crypto amount
    max_amount = models.DecimalField(max_digits=10, decimal_places=2)  # Max crypto amount
    available_amount = models.DecimalField(max_digits=10, decimal_places=2)  # Available crypto amount
    
    # Payment methods accepted
    payment_methods = models.ManyToManyField(P2PPaymentMethod, related_name='offers')
    
    # Terms and conditions
    terms = models.TextField(blank=True)
    response_time_minutes = models.IntegerField(default=15)  # Expected response time in minutes
    
    # Status
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Auto-complete settings
    auto_complete_enabled = models.BooleanField(default=False)
    auto_complete_time_minutes = models.IntegerField(default=30)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['exchange_type', 'token_type', 'status']),
            models.Index(fields=['rate']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_exchange_type_display()} {self.available_amount} {self.token_type} @ {self.rate} Bs"

class P2PTrade(SoftDeleteModel):
    """Individual P2P trades between users"""
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),           # Trade initiated, waiting for buyer action
        ('PAYMENT_PENDING', 'Payment Pending'),  # Waiting for fiat payment
        ('PAYMENT_SENT', 'Payment Sent'),      # Buyer claims payment sent
        ('PAYMENT_CONFIRMED', 'Payment Confirmed'),  # Seller confirms payment received
        ('CRYPTO_RELEASED', 'Crypto Released'),    # Crypto sent to buyer
        ('COMPLETED', 'Completed'),        # Trade successfully completed
        ('DISPUTED', 'Disputed'),          # Trade in dispute
        ('CANCELLED', 'Cancelled'),        # Trade cancelled
        ('EXPIRED', 'Expired'),           # Trade expired due to timeout
    ]
    
    # Related offer and users
    offer = models.ForeignKey(P2POffer, on_delete=models.CASCADE, related_name='trades', null=True, blank=True)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_purchases'
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_sales'
    )
    
    # Trade details
    crypto_amount = models.DecimalField(max_digits=10, decimal_places=2)
    fiat_amount = models.DecimalField(max_digits=10, decimal_places=2)
    rate_used = models.DecimalField(max_digits=10, decimal_places=2)  # Rate at time of trade
    
    # Payment method used for this trade
    payment_method = models.ForeignKey(P2PPaymentMethod, on_delete=models.PROTECT)
    
    # Status and timing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    expires_at = models.DateTimeField()  # When trade expires if not completed
    
    # Payment details
    payment_reference = models.CharField(max_length=200, blank=True)  # Payment reference/receipt
    payment_notes = models.TextField(blank=True)  # Additional payment notes
    
    # Completion details
    crypto_transaction_hash = models.CharField(max_length=66, blank=True)  # Sui transaction hash
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Dispute handling
    dispute_reason = models.TextField(blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['buyer', 'status']),
            models.Index(fields=['seller', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Trade {self.id}: {self.crypto_amount} {self.offer.token_type} @ {self.rate_used} Bs"

class P2PMessage(SoftDeleteModel):
    """Chat messages between traders"""
    MESSAGE_TYPES = [
        ('TEXT', 'Text'),
        ('SYSTEM', 'System'),
        ('PAYMENT_PROOF', 'Payment Proof'),
    ]
    
    trade = models.ForeignKey(P2PTrade, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_messages_sent'
    )
    
    message_type = models.CharField(max_length=15, choices=MESSAGE_TYPES, default='TEXT')
    content = models.TextField()
    
    # For file attachments (payment proofs, etc.)
    attachment_url = models.URLField(blank=True)
    attachment_type = models.CharField(max_length=50, blank=True)  # image, document, etc.
    
    # Message status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['trade', 'created_at']),
            models.Index(fields=['sender', 'is_read']),
        ]
    
    def __str__(self):
        return f"Message from {self.sender} in Trade {self.trade.id}"

class P2PUserStats(SoftDeleteModel):
    """Statistics for P2P trading users"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_stats'
    )
    
    # Trading statistics
    total_trades = models.IntegerField(default=0)
    completed_trades = models.IntegerField(default=0)
    cancelled_trades = models.IntegerField(default=0)
    disputed_trades = models.IntegerField(default=0)
    
    # Success rate (calculated field, stored for performance)
    success_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Response time statistics (in minutes)
    avg_response_time = models.IntegerField(default=0)
    last_seen_online = models.DateTimeField(auto_now=True)
    
    # Volume statistics
    total_volume_cusd = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_volume_confio = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Trust indicators
    is_verified = models.BooleanField(default=False)
    verification_level = models.IntegerField(default=0)  # 0-5 verification levels
    
    class Meta:
        ordering = ['-success_rate', '-completed_trades']
    
    def __str__(self):
        return f"P2P Stats for {self.user.username}: {self.success_rate}% success rate"

class P2PEscrow(SoftDeleteModel):
    """Escrow records for P2P trades (for future Sui blockchain integration)"""
    trade = models.OneToOneField(P2PTrade, on_delete=models.CASCADE, related_name='escrow')
    
    # Escrow details
    escrow_amount = models.DecimalField(max_digits=10, decimal_places=2)
    token_type = models.CharField(max_length=10)
    
    # Blockchain details (for future implementation)
    escrow_transaction_hash = models.CharField(max_length=66, blank=True)
    release_transaction_hash = models.CharField(max_length=66, blank=True)
    
    # Status
    is_escrowed = models.BooleanField(default=False)
    is_released = models.BooleanField(default=False)
    escrowed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Escrow for Trade {self.trade.id}: {self.escrow_amount} {self.token_type}"