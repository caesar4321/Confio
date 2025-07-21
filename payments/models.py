from django.db import models
from django.conf import settings
from django.utils import timezone
from users.models import SoftDeleteModel
import secrets
import string

def generate_invoice_id():
    """Generate a unique invoice ID"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

def generate_payment_transaction_id():
    """Generate a unique payment transaction ID"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(12))

class PaymentTransaction(SoftDeleteModel):
    """Model for storing payment transaction data (specific to invoice payments)"""
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

    # Unique identifier for the payment transaction
    payment_transaction_id = models.CharField(
        max_length=32,
        unique=True,
        default=generate_payment_transaction_id,
        editable=False
    )

    # User who initiated the payment (personal account user or business account user)
    payer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_transactions_sent',
        help_text='User who initiated the payment'
    )
    
    # User associated with merchant business (business owner or cashier)
    merchant_account_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_transactions_merchant_account',
        null=True,
        blank=True,
        help_text='User associated with the merchant business (owner or cashier)'
    )
    
    # LEGACY: Keep for backward compatibility
    merchant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_transactions_received_legacy',
        null=True,
        blank=True,
        help_text='DEPRECATED: Use merchant_account_user instead'
    )

    # Business relationship fields
    payer_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='payment_transactions_sent',
        null=True,
        blank=True,
        help_text='Business that made the payment (if payer is business account)'
    )
    
    # The actual merchant entity (WILL BE REQUIRED after data migration)
    merchant_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='payment_transactions_received',
        null=True,
        blank=True,
        help_text='Business entity that received the payment (will be required after migration)'
    )

    # Computed fields for GraphQL
    ACCOUNT_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
    ]
    
    payer_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='user',
        help_text='Type of payer (user or business)'
    )
    merchant_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='business',
        help_text='Type of merchant (always business for payments)'
    )
    payer_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name for the payer'
    )
    merchant_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name for the merchant'
    )

    # Legacy Account references
    payer_account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='payment_transactions_sent'
    )
    merchant_account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='payment_transactions_received'
    )

    # Blockchain addresses
    payer_address = models.CharField(max_length=66)  # Sui addresses are 0x + 32 bytes (66 chars total)
    merchant_address = models.CharField(max_length=66)  # Sui addresses are 0x + 32 bytes (66 chars total)

    # Transaction details
    amount = models.CharField(max_length=32)  # Store as string to handle large numbers
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    transaction_hash = models.CharField(
        max_length=66, 
        blank=True,
        unique=True,
        help_text="Sui transaction digest (0x + 32 bytes, 66 hex characters total)"
    )
    error_message = models.TextField(blank=True)

    # Invoice reference
    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='payment_transactions'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payment_transaction_id']),
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['payer_user', 'status']),
            models.Index(fields=['merchant_user', 'status']),
            models.Index(fields=['payer_address']),
            models.Index(fields=['merchant_address']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"PAY-{self.payment_transaction_id}: {self.token_type} {self.amount} from {self.payer_user} to {self.merchant_business.name}"

class Invoice(SoftDeleteModel):
    """Model for storing payment invoices (what merchants create to request payment)"""
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('EXPIRED', 'Expired'),
        ('CANCELLED', 'Cancelled')
    ]

    TOKEN_TYPES = [
        ('cUSD', 'Confío Dollar'),
        ('CONFIO', 'Confío Token'),
        ('USDC', 'USD Coin')
    ]

    # Unique identifier for the invoice
    invoice_id = models.CharField(
        max_length=32,
        unique=True,
        default=generate_invoice_id,
        editable=False
    )

    # User who created the invoice (could be business owner or cashier)
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='invoices_created_by',
        null=True,
        blank=True,
        help_text='User who created this invoice (business owner or cashier)'
    )
    
    # LEGACY: Keep for backward compatibility during transition
    merchant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='invoices_created_legacy',
        null=True,
        blank=True,
        help_text='DEPRECATED: Use created_by_user instead'
    )

    # The actual merchant entity (WILL BE REQUIRED after data migration)
    merchant_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='invoices_received',
        null=True,
        blank=True,
        help_text='Business entity that is the actual merchant (will be required after migration)'
    )

    # Computed fields for GraphQL
    merchant_type = models.CharField(
        max_length=10,
        choices=[('user', 'Personal'), ('business', 'Business')],
        default='business',
        help_text='Type of merchant (always business for invoices)'
    )
    merchant_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name for the merchant'
    )

    # Legacy Account that created the invoice
    merchant_account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='invoices_created'
    )

    # Invoice details
    amount = models.CharField(max_length=32)  # Store as string to handle large numbers
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')

    # Payment completion details
    paid_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices_paid'
    )
    paid_by_business = models.ForeignKey(
        'users.Business',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices_paid',
        help_text='Business that paid the invoice (if payer is business)'
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    # Note: The actual payment transaction is now stored in PaymentTransaction model
    # This field is kept for backward compatibility but will be deprecated
    transaction = models.ForeignKey(
        'send.SendTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice',
        help_text="DEPRECATED: Use payment_transactions instead"
    )

    # Expiration
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invoice_id']),
            models.Index(fields=['merchant_user', 'status']),
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"INV-{self.invoice_id}: {self.token_type} {self.amount} by {self.merchant_business.name}"

    @property
    def is_expired(self):
        """Check if the invoice has expired"""
        return timezone.now() > self.expires_at

    @property
    def qr_code_data(self):
        """Generate QR code data for the invoice"""
        return f"confio://pay/{self.invoice_id}"
