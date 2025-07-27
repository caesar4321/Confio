from django.db import models
from django.conf import settings
from users.models import SoftDeleteModel

# Create your models here.

class SendTransaction(SoftDeleteModel):
    """Model for storing send transaction data (direct user-to-user transfers)"""
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

    # User references (from our database) - LEGACY
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_transactions',
        null=True,
        blank=True,
        help_text='User who sent the transaction (null for external deposits)'
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_transactions'
    )

    # NEW: Direct User/Business relationship fields
    sender_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='sent_transactions',
        null=True,
        blank=True,
        help_text='Business that sent the transaction (if sent by business)'
    )
    recipient_business = models.ForeignKey(
        'users.Business', 
        on_delete=models.CASCADE,
        related_name='received_transactions',
        null=True,
        blank=True,
        help_text='Business that received the transaction (if received by business)'
    )

    # Computed fields for GraphQL
    ACCOUNT_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
        ('external', 'External'),
    ]
    
    sender_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='user',
        help_text='Type of sender (user or business)'
    )
    recipient_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='user',
        help_text='Type of recipient (user or business)'
    )
    sender_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name for the sender'
    )
    recipient_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name for the recipient'
    )
    
    # Phone numbers at transaction time
    sender_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text='Sender phone number at transaction time'
    )
    recipient_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text='Recipient phone number at transaction time'
    )

    # Blockchain addresses
    sender_address = models.CharField(max_length=66)  # Sui addresses are 0x + 32 bytes (66 chars total)
    recipient_address = models.CharField(max_length=66)  # Sui addresses are 0x + 32 bytes (66 chars total)

    # Transaction details
    amount = models.CharField(max_length=32)  # Store as string to handle large numbers
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    memo = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    transaction_hash = models.CharField(
        max_length=66, 
        blank=True,
        unique=True,
        help_text="Sui transaction digest (0x + 32 bytes, 66 hex characters total)"
    )  # Sui transaction hash
    error_message = models.TextField(blank=True)
    
    # Idempotency key for preventing duplicate transactions
    idempotency_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text='Optional key to prevent duplicate transactions'
    )
    
    # Invitation tracking
    is_invitation = models.BooleanField(
        default=False,
        help_text='True if this transaction includes an invitation to join Confío'
    )
    invitation_claimed = models.BooleanField(
        default=False,
        help_text='True if the invitation was claimed by the recipient'
    )
    invitation_reverted = models.BooleanField(
        default=False,
        help_text='True if the invitation expired and funds were returned to sender'
    )
    invitation_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the invitation expires (7 days after creation)'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['sender_user', 'status']),
            models.Index(fields=['recipient_user', 'status']),
            models.Index(fields=['sender_business', 'status']),
            models.Index(fields=['recipient_business', 'status']),
            models.Index(fields=['sender_address']),
            models.Index(fields=['recipient_address']),
            models.Index(fields=['created_at']),
            models.Index(fields=['idempotency_key']),
        ]
        constraints = [
            # Prevent duplicate transactions with same idempotency key from same user
            models.UniqueConstraint(
                fields=['sender_user', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False, deleted_at__isnull=True),
                name='unique_send_idempotency'
            ),
        ]

    def __str__(self):
        return f"SEND-{self.transaction_hash or 'pending'}: {self.token_type} {self.amount} from {self.sender_user} to {self.recipient_user or self.recipient_address}"
