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
        ('PENDING_BLOCKCHAIN', 'Pending Blockchain'),
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

    # Business relationship fields
    payer_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='payment_transactions_sent',
        null=True,
        blank=True,
        help_text='Business that made the payment (if payer is business account)'
    )
    
    # The actual merchant entity (REQUIRED - only businesses can accept payments)
    merchant_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='payment_transactions_received',
        help_text='Business entity that received the payment'
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
    
    # Phone number at transaction time (only for payer)
    payer_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text='Payer phone number at transaction time'
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
    amount = models.DecimalField(max_digits=19, decimal_places=6)  # Support up to 9,999,999,999,999.999999
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    transaction_hash = models.CharField(
        max_length=66, 
        blank=True,
        unique=True,
        help_text="Blockchain transaction hash"
    )
    error_message = models.TextField(blank=True)
    
    # Blockchain transaction data for client signing
    blockchain_data = models.JSONField(
        blank=True,
        null=True,
        help_text="Unsigned blockchain transactions for client signing"
    )
    
    # Idempotency key for preventing duplicate payments
    idempotency_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text='Optional key to prevent duplicate payments'
    )

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
            models.Index(fields=['merchant_account_user', 'status']),
            models.Index(fields=['payer_address']),
            models.Index(fields=['merchant_address']),
            models.Index(fields=['created_at']),
            models.Index(fields=['idempotency_key']),
        ]
        constraints = [
            # Prevent duplicate payments with same idempotency key from same user for same invoice
            models.UniqueConstraint(
                fields=['payer_user', 'invoice', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False, deleted_at__isnull=True),
                name='unique_payment_idempotency'
            ),
            # Prevent multiple successful payments for the same invoice (additional safety)
            models.UniqueConstraint(
                fields=['invoice'],
                condition=models.Q(status__in=['CONFIRMED'], deleted_at__isnull=True),
                name='unique_confirmed_payment_per_invoice'
            )
        ]

    def __str__(self):
        merchant_name = self.merchant_business.name
        return f"PAY-{self.payment_transaction_id}: {self.token_type} {self.amount} from {self.payer_user} to {merchant_name}"


# Update unified user activity on new payment transactions
from django.db.models.signals import post_save
from django.dispatch import receiver
from users.utils import touch_user_activity


@receiver(post_save, sender=PaymentTransaction)
def payment_txn_activity(sender, instance: PaymentTransaction, created, **kwargs):
    if created:
        try:
            if instance.payer_user_id:
                touch_user_activity(instance.payer_user_id)
            if instance.merchant_account_user_id:
                touch_user_activity(instance.merchant_account_user_id)
        except Exception:
            pass

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

    # User who created the invoice (could be business owner or cashier)
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='invoices_created_by',
        help_text='User who created this invoice (business owner or cashier)'
    )

    # The actual merchant entity (REQUIRED - only businesses can create invoices)
    merchant_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='invoices_received',
        help_text='Business entity that is the actual merchant'
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
    amount = models.DecimalField(max_digits=19, decimal_places=6)  # Support up to 9,999,999,999,999.999999
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

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

    # Expiration
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invoice_id']),
            models.Index(fields=['merchant_business', 'status']),
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        merchant_name = self.merchant_business.name
        return f"INV-{self.invoice_id}: {self.token_type} {self.amount} by {merchant_name}"

    @property
    def is_expired(self):
        """Check if the invoice has expired"""
        return timezone.now() > self.expires_at

    @property
    def qr_code_data(self):
        """Generate QR code data for the invoice"""
        return f"confio://pay/{self.invoice_id}"
