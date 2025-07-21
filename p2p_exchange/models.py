from django.db import models
from django.conf import settings
from users.models import SoftDeleteModel
from django.core.validators import MinValueValidator, MaxValueValidator

class P2PPaymentMethod(SoftDeleteModel):
    """Payment methods available for P2P trading"""
    name = models.CharField(max_length=50)
    display_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    icon = models.CharField(max_length=50, blank=True)  # For frontend icon reference
    country_code = models.CharField(max_length=2, blank=True, null=True, help_text="ISO country code (e.g., 'VE', 'US'). Leave empty for global methods.")
    
    class Meta:
        unique_together = ['name', 'country_code']
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
    
    # DEPRECATED: Old user field (kept for migration compatibility)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_offers_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use offer_user or offer_business instead"
    )
    
    # DEPRECATED: Old account field (kept for migration compatibility)
    account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='p2p_offers_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use offer_user or offer_business instead"
    )
    
    # NEW: Direct foreign key relationships (clearer semantics)
    offer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_offers_as_user',
        null=True,
        blank=True,
        help_text="User creating this offer (for personal offers)"
    )
    offer_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_offers',
        null=True,
        blank=True,
        help_text="Business creating this offer (for business offers)"
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
    
    # Country where this offer is available
    country_code = models.CharField(max_length=2, help_text="ISO country code (e.g., 'VE', 'US', 'AS')")
    
    # Terms and conditions
    terms = models.TextField(blank=True)
    response_time_minutes = models.IntegerField(default=15)  # Expected response time in minutes
    
    # Status
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Auto-complete settings
    auto_complete_enabled = models.BooleanField(default=False)
    auto_complete_time_minutes = models.IntegerField(default=30)
    
    # Helper methods for the new design
    @property
    def offer_entity(self):
        """Returns the actual offer entity (User or Business)"""
        if self.offer_user:
            return self.offer_user
        elif self.offer_business:
            return self.offer_business
        # Fallback to old system
        elif self.user:
            return self.user
        return None
    
    @property
    def offer_type(self):
        """Returns 'user' or 'business' for the offer creator"""
        if self.offer_user:
            return 'user'
        elif self.offer_business:
            return 'business'
        # Fallback to old system
        elif self.account:
            return self.account.account_type
        return 'user'  # Default fallback
    
    @property
    def offer_display_name(self):
        """Returns display name for the offer creator"""
        if self.offer_user:
            return f"{self.offer_user.first_name} {self.offer_user.last_name}".strip() or self.offer_user.username
        elif self.offer_business:
            return self.offer_business.name
        # Fallback to old system
        elif self.user:
            return f"{self.user.first_name} {self.user.last_name}".strip() or self.user.username
        return "Unknown"
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['exchange_type', 'token_type', 'status']),
            models.Index(fields=['rate']),
            models.Index(fields=['created_at']),
            # New indexes for direct relationships
            models.Index(fields=['offer_user', 'status']),
            models.Index(fields=['offer_business', 'status']),
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
    
    # DEPRECATED: Old fields (kept for migration compatibility)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_purchases_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use buyer_user or buyer_business instead"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_sales_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use seller_user or seller_business instead"
    )
    buyer_account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='p2p_purchases_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use buyer_user or buyer_business instead"
    )
    seller_account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='p2p_sales_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use seller_user or seller_business instead"
    )
    
    # NEW: Direct foreign key relationships (clearer semantics)
    buyer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_purchases_as_user',
        null=True,
        blank=True,
        help_text="User who is buying (for personal trades)"
    )
    buyer_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_purchases',
        null=True,
        blank=True,
        help_text="Business that is buying (for business trades)"
    )
    seller_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_sales_as_user',
        null=True,
        blank=True,
        help_text="User who is selling (for personal trades)"
    )
    seller_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_sales',
        null=True,
        blank=True,
        help_text="Business that is selling (for business trades)"
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
    
    # Helper methods for the new design
    @property
    def buyer_entity(self):
        """Returns the actual buyer entity (User or Business)"""
        if self.buyer_user:
            return self.buyer_user
        elif self.buyer_business:
            return self.buyer_business
        # Fallback to old system
        elif self.buyer:
            return self.buyer
        return None
    
    @property
    def seller_entity(self):
        """Returns the actual seller entity (User or Business)"""
        if self.seller_user:
            return self.seller_user
        elif self.seller_business:
            return self.seller_business
        # Fallback to old system
        elif self.seller:
            return self.seller
        return None
    
    @property
    def buyer_type(self):
        """Returns 'user' or 'business' for the buyer"""
        if self.buyer_user:
            return 'user'
        elif self.buyer_business:
            return 'business'
        # Fallback to old system
        elif self.buyer_account:
            return self.buyer_account.account_type
        return 'user'  # Default fallback
    
    @property
    def seller_type(self):
        """Returns 'user' or 'business' for the seller"""
        if self.seller_user:
            return 'user'
        elif self.seller_business:
            return 'business'
        # Fallback to old system
        elif self.seller_account:
            return self.seller_account.account_type
        return 'user'  # Default fallback
    
    @property
    def buyer_display_name(self):
        """Returns display name for the buyer"""
        if self.buyer_user:
            return f"{self.buyer_user.first_name} {self.buyer_user.last_name}".strip() or self.buyer_user.username
        elif self.buyer_business:
            return self.buyer_business.name
        # Fallback to old system
        elif self.buyer:
            return f"{self.buyer.first_name} {self.buyer.last_name}".strip() or self.buyer.username
        return "Unknown"
    
    @property
    def seller_display_name(self):
        """Returns display name for the seller"""
        if self.seller_user:
            return f"{self.seller_user.first_name} {self.seller_user.last_name}".strip() or self.seller_user.username
        elif self.seller_business:
            return self.seller_business.name
        # Fallback to old system
        elif self.seller:
            return f"{self.seller.first_name} {self.seller.last_name}".strip() or self.seller.username
        return "Unknown"
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Old indexes (kept for compatibility)
            models.Index(fields=['buyer', 'status']),
            models.Index(fields=['seller', 'status']),
            # New indexes for direct relationships
            models.Index(fields=['buyer_user', 'status']),
            models.Index(fields=['buyer_business', 'status']),
            models.Index(fields=['seller_user', 'status']),
            models.Index(fields=['seller_business', 'status']),
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
    
    # DEPRECATED: Old sender field (kept for migration compatibility)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_messages_sent_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use sender_user or sender_business instead"
    )
    
    # NEW: Direct foreign key relationships (clearer semantics)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_messages_sent_as_user',
        null=True,
        blank=True,
        help_text="User sending this message (for personal messages)"
    )
    sender_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_messages_sent',
        null=True,
        blank=True,
        help_text="Business sending this message (for business messages)"
    )
    
    message_type = models.CharField(max_length=15, choices=MESSAGE_TYPES, default='TEXT')
    content = models.TextField()
    
    # For file attachments (payment proofs, etc.)
    attachment_url = models.URLField(blank=True)
    attachment_type = models.CharField(max_length=50, blank=True)  # image, document, etc.
    
    # Message status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Helper methods for the new design
    @property
    def sender_entity(self):
        """Returns the actual sender entity (User or Business)"""
        if self.sender_user:
            return self.sender_user
        elif self.sender_business:
            return self.sender_business
        # Fallback to old system
        elif self.sender:
            return self.sender
        return None
    
    @property
    def sender_type(self):
        """Returns 'user' or 'business' for the sender"""
        if self.sender_user:
            return 'user'
        elif self.sender_business:
            return 'business'
        # Fallback to old system
        return 'user'  # Default fallback
    
    @property
    def sender_display_name(self):
        """Returns display name for the sender"""
        if self.sender_user:
            return f"{self.sender_user.first_name} {self.sender_user.last_name}".strip() or self.sender_user.username
        elif self.sender_business:
            return self.sender_business.name
        # Fallback to old system
        elif self.sender:
            return f"{self.sender.first_name} {self.sender.last_name}".strip() or self.sender.username
        return "Unknown"
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['trade', 'created_at']),
            # Old indexes (kept for compatibility)
            models.Index(fields=['sender', 'is_read']),
            # New indexes for direct relationships
            models.Index(fields=['sender_user', 'is_read']),
            models.Index(fields=['sender_business', 'is_read']),
        ]
    
    def __str__(self):
        return f"Message from {self.sender_display_name} in Trade {self.trade.id}"

class P2PUserStats(SoftDeleteModel):
    """Statistics for P2P trading users and businesses"""
    
    # DEPRECATED: Old user field (kept for migration compatibility)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_stats_old',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use stats_user or stats_business instead"
    )
    
    # NEW: Direct foreign key relationships (clearer semantics)
    stats_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_stats',
        null=True,
        blank=True,
        help_text="User these stats belong to (for personal account stats)"
    )
    stats_business = models.OneToOneField(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_stats',
        null=True,
        blank=True,
        help_text="Business these stats belong to (for business account stats)"
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
    
    # Helper methods for the new design
    @property
    def stats_entity(self):
        """Returns the actual stats entity (User or Business)"""
        if self.stats_user:
            return self.stats_user
        elif self.stats_business:
            return self.stats_business
        # Fallback to old system
        elif self.user:
            return self.user
        return None
    
    @property
    def stats_type(self):
        """Returns 'user' or 'business' for the stats owner"""
        if self.stats_user:
            return 'user'
        elif self.stats_business:
            return 'business'
        # Fallback to old system
        return 'user'  # Default fallback
    
    @property
    def stats_display_name(self):
        """Returns display name for the stats owner"""
        if self.stats_user:
            return f"{self.stats_user.first_name} {self.stats_user.last_name}".strip() or self.stats_user.username
        elif self.stats_business:
            return self.stats_business.name
        # Fallback to old system
        elif self.user:
            return f"{self.user.first_name} {self.user.last_name}".strip() or self.user.username
        return "Unknown"
    
    class Meta:
        ordering = ['-success_rate', '-completed_trades']
    
    def __str__(self):
        return f"P2P Stats for {self.stats_display_name}: {self.success_rate}% success rate"

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