# Django models for unified transaction tables
from django.db import models
from django.conf import settings
from django.utils import timezone


class UnifiedTransactionTable(models.Model):
    """
    Actual table for unified transactions across all transaction types.
    Maintains foreign keys to source tables for data integrity.
    """
    TRANSACTION_TYPES = [
        ('send', 'Send/Receive'),
        ('payment', 'Payment'),
        ('payroll', 'Payroll'),
        ('conversion', 'Conversion'),
        ('exchange', 'P2P Exchange'),
        ('reward', 'Reward'),
        ('presale', 'Presale Purchase'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PENDING_SIG', 'Pending Signature'),
        ('PENDING_BLOCKCHAIN', 'Pending Blockchain'),
        ('SPONSORING', 'Sponsoring'),
        ('SIGNED', 'Signed'),
        ('SUBMITTED', 'Submitted'),
        ('CONFIRMED', 'Confirmed'),
        ('FAILED', 'Failed'),
        ('AML_REVIEW', 'Under AML Review')
    ]

    TOKEN_TYPES = [
        ('CUSD', 'Confío Dollar'),
        ('CONFIO', 'Confío Token'),
        ('USDC', 'USD Coin'),
        ('ALGO', 'ALGO'),
    ]

    ACCOUNT_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
        ('external', 'External'),
    ]

    # Primary key
    id = models.BigAutoField(primary_key=True)
    
    # Transaction type
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, db_index=True)
    
    # Foreign keys to source tables (only one will be set)
    send_transaction = models.OneToOneField(
        'send.SendTransaction',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    payment_transaction = models.OneToOneField(
        'payments.PaymentTransaction',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    conversion = models.OneToOneField(
        'conversion.Conversion',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    p2p_trade = models.OneToOneField(
        'p2p_exchange.P2PTrade',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    payroll_item = models.OneToOneField(
        'payroll.PayrollItem',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    referral_reward_event = models.OneToOneField(
        'achievements.ReferralRewardEvent',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )

    presale_purchase = models.OneToOneField(
        'presale.PresalePurchase',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    
    # Denormalized fields for quick access/filtering
    amount = models.CharField(max_length=32)
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    transaction_hash = models.CharField(max_length=66, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    
    # Sender info
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='unified_table_sent_transactions',
        null=True,
        blank=True
    )
    sender_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='unified_table_sent_transactions',
        null=True,
        blank=True
    )
    sender_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES)
    sender_display_name = models.CharField(max_length=255, blank=True)
    sender_phone = models.CharField(max_length=30, blank=True)
    sender_address = models.CharField(max_length=66, blank=True, default='')
    
    # Counterparty info (recipient for sends, merchant for payments)
    counterparty_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='unified_table_counterparty_transactions',
        null=True,
        blank=True
    )
    counterparty_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='unified_table_counterparty_transactions',
        null=True,
        blank=True
    )
    counterparty_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES)
    counterparty_display_name = models.CharField(max_length=255, blank=True)
    counterparty_phone = models.CharField(max_length=30, blank=True, null=True)
    counterparty_address = models.CharField(max_length=66, blank=True, default='')
    
    # Additional fields
    description = models.TextField(blank=True)
    invoice_id = models.CharField(max_length=32, blank=True, null=True)
    payment_reference_id = models.CharField(max_length=32, blank=True, null=True)
    
    # Address fields for easy filtering
    from_address = models.CharField(max_length=66, blank=True, default='')
    to_address = models.CharField(max_length=66, blank=True, default='')
    
    # Invitation tracking fields
    is_invitation = models.BooleanField(default=False)
    invitation_claimed = models.BooleanField(default=False)
    invitation_reverted = models.BooleanField(default=False)
    invitation_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)  # When record is created in unified table
    transaction_date = models.DateTimeField()  # Original transaction date from source
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'unified_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['transaction_type', '-created_at']),
            models.Index(fields=['sender_user', '-created_at']),
            models.Index(fields=['sender_business', '-created_at']),
            models.Index(fields=['counterparty_user', '-created_at']),
            models.Index(fields=['counterparty_business', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['token_type', '-created_at']),
        ]

    def get_direction_for_address(self, address):
        """
        Determine if this transaction is incoming or outgoing for a given address
        """
        if not address:
            return 'unknown'
        if self.from_address and self.from_address == address:
            return 'sent'
        if self.to_address and self.to_address == address:
            return 'received'
        return 'unknown'
            
    def get_display_info_for_address(self, address):
        """
        Get display information based on the perspective of the given address
        """
        direction = self.get_direction_for_address(address)
        
        if direction == 'sent':
            return {
                'direction': 'sent',
                'counterparty_name': self.counterparty_display_name,
                'counterparty_type': self.counterparty_type,
                'amount': f'-{self.amount}',
                'description': self.description or 'Enviado'
            }
        elif direction == 'received':
            return {
                'direction': 'received',
                'counterparty_name': self.sender_display_name,
                'counterparty_type': self.sender_type,
                'amount': f'+{self.amount}',
                'description': self.description or 'Recibido'
            }
        else:
            return {
                'direction': 'unknown',
                'counterparty_name': 'Unknown',
                'counterparty_type': 'unknown',
                'amount': self.amount,
                'description': self.description or 'Unknown transaction'
            }

    def get_conversion_type(self):
        """Resolve conversion type from related Conversion first, then description fallback."""
        if self.transaction_type == 'conversion':
            if self.conversion_id and self.conversion:
                return self.conversion.conversion_type
        if self.transaction_type == 'conversion' and self.description:
            if 'USDC → cUSD' in self.description:
                return 'usdc_to_cusd'
            elif 'cUSD → USDC' in self.description:
                return 'cusd_to_usdc'
        return None
    
    def get_from_amount(self):
        """For conversions, this is the amount field"""
        if self.transaction_type == 'conversion':
            return self.amount
        return None
    
    def get_to_amount(self):
        """Extract to_amount from conversion description"""
        if self.transaction_type == 'conversion' and self.description:
            import re
            # Match the amount after the arrow
            match = re.search(r'→\s*([\d.]+)\s*(?:cUSD|USDC)', self.description)
            if match:
                return match.group(1)
        return None
    
    def get_from_token(self):
        """For conversions, determine from token"""
        if self.transaction_type == 'conversion':
            conversion_type = self.get_conversion_type()
            if conversion_type == 'usdc_to_cusd':
                return 'USDC'
            elif conversion_type == 'cusd_to_usdc':
                return 'cUSD'
        return None
    
    def get_to_token(self):
        """For conversions, determine to token"""
        if self.transaction_type == 'conversion':
            conversion_type = self.get_conversion_type()
            if conversion_type == 'usdc_to_cusd':
                return 'cUSD'
            elif conversion_type == 'cusd_to_usdc':
                return 'USDC'
        return None
    
    @property
    def internal_id(self):
        """Return standardized internal_id from linked source models"""
        if self.transaction_type == 'exchange' and self.p2p_trade:
            return self.p2p_trade.internal_id
        if self.transaction_type == 'payroll' and self.payroll_item:
            return self.payroll_item.internal_id
        if self.transaction_type == 'payment' and self.payment_transaction:
            return self.payment_transaction.internal_id
        if self.transaction_type == 'send' and self.send_transaction:
            return self.send_transaction.internal_id
        if self.transaction_type == 'conversion' and self.conversion:
            return self.conversion.internal_id
        if self.transaction_type == 'reward' and self.referral_reward_event:
            return self.referral_reward_event.internal_id
        if self.transaction_type == 'presale' and self.presale_purchase:
            return self.presale_purchase.internal_id
        return None

    @property
    def p2p_trade_id(self):
        """Return P2P trade ID if this is an exchange transaction"""
        if self.transaction_type == 'exchange' and self.p2p_trade:
            # Return internal_id as the public ID
            return self.p2p_trade.internal_id
        return None

    def __str__(self):
        return f"{self.transaction_type.upper()}-{self.transaction_hash or 'pending'}: {self.token_type} {self.amount}"
