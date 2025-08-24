from django.db import models
from django.conf import settings
from users.models import SoftDeleteModel
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError

class P2PPaymentMethod(SoftDeleteModel):
    """Payment methods available for P2P trading"""
    PROVIDER_TYPES = [
        ('bank', 'Traditional Bank'),
        ('fintech', 'Fintech/Digital Wallet'),
        ('cash', 'Cash/Physical'),
        ('other', 'Other'),
    ]
    
    name = models.CharField(max_length=50, help_text="Unique identifier (e.g., 'banco_venezuela', 'nequi')")
    display_name = models.CharField(max_length=100, help_text="User-friendly name (e.g., 'Banco de Venezuela', 'Nequi')")
    provider_type = models.CharField(max_length=10, choices=PROVIDER_TYPES, default='other')
    is_active = models.BooleanField(default=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Frontend icon reference")
    country_code = models.CharField(max_length=2, blank=True, null=True, help_text="ISO country code (e.g., 'VE', 'US'). Leave empty for global methods.")
    
    # Link to Bank model for bank-based payment methods
    bank = models.ForeignKey(
        'users.Bank', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        help_text="Reference to Bank model if this is a bank-based payment method"
    )
    
    # Link to Country model for non-bank payment methods
    country = models.ForeignKey(
        'users.Country',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Country for non-bank payment methods (e.g., fintech, mobile payments)"
    )
    
    # Additional metadata
    description = models.TextField(blank=True, help_text="Optional description of the payment method")
    requires_phone = models.BooleanField(default=False, help_text="Whether this method requires a phone number (e.g., Pago Móvil)")
    requires_email = models.BooleanField(default=False, help_text="Whether this method requires an email (e.g., PayPal)")
    requires_account_number = models.BooleanField(default=True, help_text="Whether this method requires an account number")
    
    # Display order for UI
    display_order = models.IntegerField(default=0, help_text="Order for displaying in UI (lower numbers first)")
    
    class Meta:
        unique_together = ['name', 'country_code']
        ordering = ['display_order', 'display_name']
    
    def __str__(self):
        if self.country_code:
            return f"{self.display_name} ({self.country_code})"
        return self.display_name
    
    @property
    def is_bank_based(self):
        """Check if this payment method is linked to a traditional bank"""
        return self.provider_type == 'bank' and self.bank is not None
    
    @property 
    def is_fintech(self):
        """Check if this payment method is a fintech/digital wallet"""
        return self.provider_type == 'fintech'

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
    
    # Payment methods accepted
    payment_methods = models.ManyToManyField(P2PPaymentMethod, related_name='offers')
    
    # Country where this offer is available
    country_code = models.CharField(max_length=2, help_text="ISO country code (e.g., 'VE', 'US', 'AS')")
    currency_code = models.CharField(max_length=3, default='', help_text="Currency code (e.g., 'VES', 'COP', 'ARS')")
    
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
        return f"{self.get_exchange_type_display()} {self.token_type} (min {self.min_amount} / max {self.max_amount}) @ {self.rate}"

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
        ('AML_REVIEW', 'Under AML Review'), # Trade flagged for compliance review
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
    
    # Country and currency info (inherited from offer)
    country_code = models.CharField(max_length=2, default='VE', help_text="ISO country code from the offer")
    currency_code = models.CharField(max_length=3, default='VES', help_text="Currency code (e.g., 'VES', 'COP', 'ARS')")
    
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
    
    # Dispute handling is now tracked in the separate P2PDispute model
    
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
        token_type = self.offer.token_type if self.offer else 'UNKNOWN'
        # Format token type nicely
        if token_type == 'CUSD':
            token_display = 'cUSD'
        elif token_type == 'CONFIO':
            token_display = 'CONFIO'
        else:
            token_display = token_type
        return f"Trade {self.id}: {self.crypto_amount} {token_display} ⇄ {self.fiat_amount} {self.currency_code}"

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
    
    # Average rating from completed trades
    avg_rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        help_text="Average rating from completed trades (0-5)"
    )
    
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
    
    RELEASE_TYPES = [
        ('NORMAL', 'Normal Release to Buyer'),       # Standard trade completion (crypto released to buyer)
        ('REFUND', 'Refund to Seller'),              # Refund back to seller (trade cancelled/expired)
        ('PARTIAL_REFUND', 'Partial Refund'),        # Split payment after dispute
        ('DISPUTE_RELEASE', 'Dispute Release to Buyer'),  # Dispute resolved in favor of buyer
    ]
    
    trade = models.OneToOneField(P2PTrade, on_delete=models.CASCADE, related_name='escrow')
    
    # Escrow details
    escrow_amount = models.DecimalField(max_digits=10, decimal_places=2)
    token_type = models.CharField(max_length=10)
    
    # Blockchain details (for future implementation)
    escrow_transaction_hash = models.CharField(max_length=66, blank=True)
    release_transaction_hash = models.CharField(max_length=66, blank=True)
    
    # Status tracking
    is_escrowed = models.BooleanField(default=False, help_text="Funds are currently held in escrow")
    is_released = models.BooleanField(default=False, help_text="Funds have been released from escrow")
    
    # Release details
    release_type = models.CharField(
        max_length=20, 
        choices=RELEASE_TYPES, 
        blank=True, 
        help_text="How the funds were released from escrow"
    )
    release_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Amount released (may be less than escrow_amount for partial refunds)"
    )
    
    # Timestamps
    escrowed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    
    # Dispute resolution tracking
    resolved_by_dispute = models.BooleanField(
        default=False, 
        help_text="True if this escrow was resolved through dispute resolution"
    )
    dispute_resolution = models.ForeignKey(
        'P2PDispute',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escrow_resolutions',
        help_text="Link to dispute that resolved this escrow"
    )
    
    class Meta:
        ordering = ['-created_at']
        db_table = 'p2p_escrows'
    
    def __str__(self):
        status = "Escrowed" if self.is_escrowed and not self.is_released else "Released" if self.is_released else "Pending"
        return f"Escrow for Trade {self.trade.id}: {self.escrow_amount} {self.token_type} ({status})"
    
    @property
    def status_display(self):
        """Human-readable status"""
        if not self.is_escrowed:
            return "Pending Escrow"
        elif not self.is_released:
            return "Funds in Escrow"
        else:
            release_display = dict(self.RELEASE_TYPES).get(self.release_type, "Released")
            return f"Released ({release_display})"
    
    def release_funds(self, release_type, amount=None, dispute=None, released_by=None):
        """Helper method to properly release funds with tracking"""
        from django.utils import timezone
        
        if self.is_released:
            raise ValueError("Funds have already been released")
        
        if not self.is_escrowed:
            raise ValueError("Cannot release funds that are not escrowed")
        
        self.is_released = True
        self.release_type = release_type
        self.release_amount = amount or self.escrow_amount
        self.released_at = timezone.now()
        
        if dispute:
            self.resolved_by_dispute = True
            self.dispute_resolution = dispute
            
        self.save()
        
        return self


class PremiumUpgradeRequest(SoftDeleteModel):
    """Represents a request to upgrade to Trader Premium (verification level 2).

    Requests can originate from a personal user context or a business context.
    Admins can approve or reject; on approval, the stats.verification_level should be set to 2.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    # Context
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='premium_upgrade_requests',
        null=True,
        blank=True,
        help_text="Request in personal account context"
    )
    business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='premium_upgrade_requests',
        null=True,
        blank=True,
        help_text="Request in business account context"
    )

    # Metadata
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_premium_requests'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        ctx = self.business.name if self.business else (self.user.username if self.user else 'Unknown')
        return f"PremiumUpgradeRequest({ctx}) - {self.status}"

class P2PTradeConfirmation(SoftDeleteModel):
    """
    Track confirmations for each step of a P2P trade.
    This provides an audit trail of who confirmed what and when.
    """
    
    CONFIRMATION_TYPES = [
        ('PAYMENT_SENT', 'Payment Sent'),        # Buyer confirms they sent payment
        ('PAYMENT_RECEIVED', 'Payment Received'), # Seller confirms they received payment
        ('CRYPTO_RELEASED', 'Crypto Released'),   # System/Seller releases crypto
        ('CRYPTO_RECEIVED', 'Crypto Received'),   # Buyer confirms crypto received
    ]
    
    # Trade being confirmed
    trade = models.ForeignKey(P2PTrade, on_delete=models.CASCADE, related_name='confirmations')
    
    # Type of confirmation
    confirmation_type = models.CharField(max_length=20, choices=CONFIRMATION_TYPES)
    
    # Who is confirming - either user or business
    confirmer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_confirmations',
        null=True,
        blank=True
    )
    confirmer_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_confirmations',
        null=True,
        blank=True
    )
    
    # Reference/proof
    reference = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    proof_image_url = models.URLField(blank=True)
    
    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        db_table = 'p2p_trade_confirmations'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['trade', 'confirmation_type', 'confirmer_user'],
                condition=models.Q(confirmer_user__isnull=False),
                name='unique_user_confirmation'
            ),
            models.UniqueConstraint(
                fields=['trade', 'confirmation_type', 'confirmer_business'],
                condition=models.Q(confirmer_business__isnull=False),
                name='unique_business_confirmation'
            ),
        ]
    
    def __str__(self):
        confirmer = self.confirmer_display_name
        return f"{self.get_confirmation_type_display()} by {confirmer} for Trade #{self.trade.id}"
    
    @property
    def confirmer_type(self):
        """Returns 'user' or 'business' for the confirmer"""
        if self.confirmer_business:
            return 'business'
        return 'user'
    
    @property
    def confirmer_display_name(self):
        """Returns display name for the confirmer"""
        if self.confirmer_business:
            return self.confirmer_business.name
        elif self.confirmer_user:
            return self.confirmer_user.get_full_name() or self.confirmer_user.username
        return 'Unknown'
    
    def clean(self):
        """Validate that either user or business is set, not both"""
        if not self.confirmer_user and not self.confirmer_business:
            raise ValidationError("Either confirmer_user or confirmer_business must be set")
        if self.confirmer_user and self.confirmer_business:
            raise ValidationError("Cannot set both confirmer_user and confirmer_business")


class P2PTradeRating(SoftDeleteModel):
    """Rating for P2P trades"""
    
    # Trade being rated
    trade = models.ForeignKey(P2PTrade, on_delete=models.CASCADE, related_name='ratings')
    
    # Who is rating (the rater)
    rater_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_ratings_given',
        null=True,
        blank=True
    )
    rater_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_ratings_given',
        null=True,
        blank=True
    )
    
    # Who is being rated (the ratee)
    ratee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='p2p_ratings_received',
        null=True,
        blank=True
    )
    ratee_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='p2p_ratings_received',
        null=True,
        blank=True
    )
    
    # Ratings
    overall_rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    communication_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    speed_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    reliability_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    # Feedback
    comment = models.TextField(max_length=500, blank=True)
    tags = models.JSONField(default=list, blank=True)  # List of tag strings
    
    # Metadata
    rated_at = models.DateTimeField(auto_now_add=True)
    
    # Helper properties
    @property
    def rater_type(self):
        return 'business' if self.rater_business else 'user'
    
    @property
    def ratee_type(self):
        return 'business' if self.ratee_business else 'user'
    
    @property
    def rater_display_name(self):
        if self.rater_business:
            return self.rater_business.name
        elif self.rater_user:
            return f"{self.rater_user.first_name} {self.rater_user.last_name}".strip() or self.rater_user.username
        return "Unknown"
    
    @property
    def ratee_display_name(self):
        if self.ratee_business:
            return self.ratee_business.name
        elif self.ratee_user:
            return f"{self.ratee_user.first_name} {self.ratee_user.last_name}".strip() or self.ratee_user.username
        return "Unknown"
    
    class Meta:
        ordering = ['-rated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['trade', 'rater_user', 'rater_business'],
                name='unique_rating_per_rater_per_trade'
            )
        ]
    
    def __str__(self):
        return f"Rating for Trade {self.trade.id}: {self.overall_rating}/5 stars"


class P2PDispute(SoftDeleteModel):
    """Detailed dispute tracking for P2P trades"""
    
    DISPUTE_STATUS = [
        ('OPEN', 'Open'),
        ('UNDER_REVIEW', 'Under Review'),
        ('RESOLVED', 'Resolved'),
        ('ESCALATED', 'Escalated'),
    ]
    
    RESOLUTION_TYPE = [
        ('REFUND_BUYER', 'Refund to Buyer'),
        ('RELEASE_TO_SELLER', 'Release to Seller'),
        ('PARTIAL_REFUND', 'Partial Refund'),
        ('CANCELLED', 'Trade Cancelled'),
        ('NO_ACTION', 'No Action Taken'),
    ]
    
    # Trade being disputed
    trade = models.OneToOneField(P2PTrade, on_delete=models.CASCADE, related_name='dispute_details')
    
    # Who initiated the dispute
    initiator_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='disputes_initiated',
        null=True,
        blank=True
    )
    initiator_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='disputes_initiated',
        null=True,
        blank=True
    )
    
    # Dispute details
    reason = models.TextField(help_text="Initial reason for dispute")
    status = models.CharField(max_length=20, choices=DISPUTE_STATUS, default='OPEN')
    priority = models.IntegerField(default=1, help_text="1=Low, 2=Medium, 3=High")
    
    # Evidence and communication
    evidence_urls = models.JSONField(default=list, blank=True, help_text="List of evidence URLs")
    admin_notes = models.TextField(blank=True, help_text="Internal notes from admin/support")
    
    # Resolution
    resolution_type = models.CharField(max_length=20, choices=RESOLUTION_TYPE, null=True, blank=True)
    resolution_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disputes_resolved'
    )
    
    # Timestamps
    opened_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    # Helper properties
    @property
    def initiator_type(self):
        return 'business' if self.initiator_business else 'user'
    
    @property
    def initiator_display_name(self):
        if self.initiator_business:
            return self.initiator_business.name
        elif self.initiator_user:
            return f"{self.initiator_user.first_name} {self.initiator_user.last_name}".strip() or self.initiator_user.username
        return "Unknown"
    
    @property
    def is_resolved(self):
        return self.status == 'RESOLVED'
    
    @property
    def duration_hours(self):
        """Hours the dispute has been open"""
        if self.resolved_at:
            duration = self.resolved_at - self.opened_at
        else:
            from django.utils import timezone
            duration = timezone.now() - self.opened_at
        return duration.total_seconds() / 3600
    
    class Meta:
        ordering = ['-priority', '-opened_at']
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['opened_at']),
            models.Index(fields=['resolved_at']),
        ]
    
    def __str__(self):
        return f"Dispute for Trade #{self.trade.id} - {self.get_status_display()}"
    
    def clean(self):
        """Validate that either user or business initiated, not both"""
        if not self.initiator_user and not self.initiator_business:
            raise ValidationError("Either initiator_user or initiator_business must be set")
        if self.initiator_user and self.initiator_business:
            raise ValidationError("Cannot set both initiator_user and initiator_business")

class P2PDisputeTransaction(SoftDeleteModel):
    """Track financial transactions resulting from dispute resolutions"""
    
    TRANSACTION_TYPES = [
        ('REFUND', 'Refund to Buyer'),
        ('RELEASE', 'Release to Seller'),
        ('PARTIAL_REFUND', 'Partial Refund'),
        ('SPLIT', 'Split Payment'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    # Related dispute and trade
    dispute = models.ForeignKey(P2PDispute, on_delete=models.CASCADE, related_name='transactions')
    trade = models.ForeignKey(P2PTrade, on_delete=models.CASCADE, related_name='dispute_transactions')
    
    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=20, decimal_places=8)
    token_type = models.CharField(max_length=10)
    
    # Recipients
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='dispute_transactions_received',
        null=True,
        blank=True
    )
    recipient_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='dispute_transactions_received',
        null=True,
        blank=True
    )
    
    # Blockchain details
    transaction_hash = models.CharField(max_length=66, blank=True)
    block_number = models.BigIntegerField(null=True, blank=True)
    gas_used = models.BigIntegerField(null=True, blank=True)
    
    # Status and metadata
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dispute_transactions_processed'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    
    # Audit trail
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'p2p_dispute_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['dispute', 'status']),
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['processed_at']),
        ]
    
    def __str__(self):
        return f"Dispute Transaction {self.id}: {self.transaction_type} of {self.amount} {self.token_type}"
    
    def clean(self):
        """Validate that either user or business recipient, not both"""
        if not self.recipient_user and not self.recipient_business:
            raise ValidationError("Either recipient_user or recipient_business must be set")
        if self.recipient_user and self.recipient_business:
            raise ValidationError("Cannot set both recipient_user and recipient_business")


class P2PFavoriteTrader(SoftDeleteModel):
    """Track favorite traders for users in their specific account context"""
    
    # User who is favoriting
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favorite_traders'
    )
    
    # Account context - which account is adding the favorite
    # This allows personal and business accounts to have separate favorites
    favoriter_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='business_favorite_traders',
        null=True,
        blank=True,
        help_text="If favoriting from a business account"
    )
    
    # Trader being favorited (could be user or business)
    favorite_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favorited_by_users',
        null=True,
        blank=True
    )
    
    favorite_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='favorited_by_users',
        null=True,
        blank=True
    )
    
    # Optional note about why favorited
    note = models.TextField(blank=True, help_text="Personal note about this trader")
    
    class Meta:
        db_table = 'p2p_favorite_traders'
        unique_together = [
            ('user', 'favoriter_business', 'favorite_user'),
            ('user', 'favoriter_business', 'favorite_business'),
        ]
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['favoriter_business', 'created_at']),
        ]
    
    def clean(self):
        super().clean()
        # Ensure either favorite_user or favorite_business is set, but not both
        if not self.favorite_user and not self.favorite_business:
            raise ValidationError("Either favorite_user or favorite_business must be set")
        if self.favorite_user and self.favorite_business:
            raise ValidationError("Cannot set both favorite_user and favorite_business")
        
        # Account-specific validation
        if self.favoriter_business:
            # Business account favoriting - no restrictions on favoriting own personal account
            # This is valid: business can favorite the owner's personal account
            pass
        else:
            # Personal account favoriting
            # Prevent users from favoriting their own personal account
            if self.favorite_user and self.favorite_user == self.user:
                raise ValidationError("Cannot favorite your own personal account")
    
    def __str__(self):
        favorite = self.favorite_user or self.favorite_business
        return f"{self.user} → {favorite}"
