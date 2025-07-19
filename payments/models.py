from django.db import models
from django.conf import settings
from users.models import SoftDeleteModel
import uuid

def generate_invoice_id():
    """Generate a unique invoice ID"""
    return f"INV{uuid.uuid4().hex[:8].upper()}"

class Invoice(SoftDeleteModel):
    """Model for storing payment invoices (what merchants create to request payment)"""
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('EXPIRED', 'Expired'),
        ('CANCELLED', 'Cancelled')
    ]

    TOKEN_TYPES = [
        ('CUSD', 'Confío Dollar'),
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

    # User who created the invoice (merchant/seller)
    merchant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='invoices_created'
    )

    # Account that created the invoice
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
    paid_at = models.DateTimeField(null=True, blank=True)
    transaction = models.ForeignKey(
        'send.Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice'
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
        return f"INV-{self.invoice_id}: {self.token_type} {self.amount} by {self.merchant_user}"

    @property
    def is_expired(self):
        """Check if the invoice has expired"""
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def qr_code_data(self):
        """Generate QR code data for the invoice"""
        return f"confio://pay/{self.invoice_id}"
