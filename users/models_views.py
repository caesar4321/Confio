# Django models for database views
from django.db import models
from django.conf import settings


class UnifiedTransaction(models.Model):
    """
    Unified view of all transactions (send and payment).
    This is a database view, not a table, so it's read-only.
    """
    TRANSACTION_TYPES = [
        ('send', 'Send/Receive'),
        ('payment', 'Payment'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SPONSORING', 'Sponsoring'),
        ('SIGNED', 'Signed'),
        ('SUBMITTED', 'Submitted'),
        ('CONFIRMED', 'Confirmed'),
        ('FAILED', 'Failed')
    ]

    TOKEN_TYPES = [
        ('cUSD', 'Confío Dollar'),
        ('CONFIO', 'Confío Token'),
        ('USDC', 'USD Coin')
    ]

    ACCOUNT_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
    ]

    # Transaction type
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    
    # Common fields
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True, blank=True)
    amount = models.CharField(max_length=32)
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    transaction_hash = models.CharField(max_length=66, blank=True)
    error_message = models.TextField(blank=True)
    
    # Sender info (payer in case of payments)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='unified_sent_transactions',
        null=True,
        blank=True
    )
    sender_business = models.ForeignKey(
        'users.Business',
        on_delete=models.DO_NOTHING,
        related_name='unified_sent_transactions',
        null=True,
        blank=True
    )
    sender_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES)
    sender_display_name = models.CharField(max_length=255, blank=True)
    sender_phone = models.CharField(max_length=30, blank=True)
    sender_address = models.CharField(max_length=66)
    
    # Counterparty info (recipient for sends, merchant for payments)
    counterparty_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='unified_counterparty_transactions',
        null=True,
        blank=True
    )
    counterparty_business = models.ForeignKey(
        'users.Business',
        on_delete=models.DO_NOTHING,
        related_name='unified_counterparty_transactions',
        null=True,
        blank=True
    )
    counterparty_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES)
    counterparty_display_name = models.CharField(max_length=255, blank=True)
    counterparty_phone = models.CharField(max_length=30, blank=True, null=True)
    counterparty_address = models.CharField(max_length=66)
    
    # Additional fields
    description = models.TextField(blank=True)
    invoice_id = models.CharField(max_length=32, blank=True, null=True)
    payment_transaction_id = models.CharField(max_length=32, blank=True, null=True)
    
    # Address fields for easy filtering
    from_address = models.CharField(max_length=66)
    to_address = models.CharField(max_length=66)
    
    # Invitation tracking fields
    is_invitation = models.BooleanField(default=False)
    invitation_claimed = models.BooleanField(default=False)
    invitation_reverted = models.BooleanField(default=False)
    invitation_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False  # Don't create/delete this table, it's a view
        db_table = 'unified_transactions_view'
        ordering = ['-created_at']

    def get_direction_for_address(self, address):
        """
        Determine if this transaction is incoming or outgoing for a given address
        """
        if self.from_address == address:
            return 'sent'
        elif self.to_address == address:
            return 'received'
        else:
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

    def __str__(self):
        return f"{self.transaction_type.upper()}-{self.transaction_hash or 'pending'}: {self.token_type} {self.amount}"