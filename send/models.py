from django.db import models
from django.conf import settings

# Create your models here.

class Transaction(models.Model):
    """Model for storing transaction data"""
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SPONSORING', 'Sponsoring'),
        ('SIGNED', 'Signed'),
        ('SUBMITTED', 'Submitted'),
        ('CONFIRMED', 'Confirmed'),
        ('FAILED', 'Failed')
    ]

    TOKEN_TYPES = [
        ('CUSD', 'Confío Dollar'),
        ('CONFIO', 'Confío Token'),
        ('USDC', 'USD Coin')
    ]

    # User references (from our database)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_transactions'
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_transactions'
    )

    # Blockchain addresses
    sender_address = models.CharField(max_length=64)  # Sui addresses are 32 bytes (64 hex chars)
    recipient_address = models.CharField(max_length=64)  # Sui addresses are 32 bytes (64 hex chars)

    # Transaction details
    amount = models.CharField(max_length=32)  # Store as string to handle large numbers
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    memo = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    transaction_hash = models.CharField(
        max_length=64, 
        blank=True,
        unique=True,
        help_text="Sui transaction digest (32 bytes, 64 hex characters)"
    )  # Sui transaction hash
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['sender_user', 'status']),
            models.Index(fields=['recipient_user', 'status']),
            models.Index(fields=['sender_address']),
            models.Index(fields=['recipient_address']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"TX-{self.transaction_hash or 'pending'}: {self.token_type} {self.amount} from {self.sender_user} to {self.recipient_user or self.recipient_address}"
