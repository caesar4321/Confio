from datetime import timedelta

from django.db import models
from django.conf import settings
from django.utils import timezone
from users.models import SoftDeleteModel

# The hard ceiling on an invoice's life, measured from creation. Lives on
# the model so EVERY write path is bound by it — the GraphQL cap, the admin
# extend action, and any direct ORM edit (Codex audit 2026-08-01).
MAX_INVOICE_LIFETIME_HOURS = 24
import uuid
import secrets
import string
import secrets
import string


def generate_invoice_id():
    """Generate a unique invoice ID (Legacy - Required for Migrations)"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


def generate_payment_transaction_id():
    """Generate a unique payment transaction ID (32-char hex UUID)"""
    return uuid.uuid4().hex

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
        ('USDC', 'USD Coin'),
        # BSC dollar rails (Phase 2): what actually moved on-chain — the
        # invoice itself stays dollar-denominated ('CUSD').
        ('CUSD_PLUS', 'Confío Dollar Plus'),
        ('USDT', 'Tether USD'),
    ]

    # Unique identifier for the payment transaction
    internal_id = models.CharField(
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
    payer_address = models.CharField(max_length=66)  # Algorand addresses are 58 chars; 66 kept for legacy rows
    merchant_address = models.CharField(max_length=66)  # Algorand addresses are 58 chars; 66 kept for legacy rows

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
            models.Index(fields=['internal_id']),
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
        return f"PAY-{self.internal_id}: {self.token_type} {self.amount} from {self.payer_user} to {merchant_name}"


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
        # The charge menu after the BSC migration (2026-08-01): a merchant
        # charges in cUSD+ (the dollar) or CONFIO (a token count), both on
        # BNB Smart Chain. 'CUSD'/'USDC' are legacy Algorand-rail values kept
        # for the invoices already on file.
        ('CUSD_PLUS', 'Confío Dollar Plus'),
        ('CONFIO', 'Confío Token'),
        ('CUSD', 'Confío Dollar (legacy)'),
        ('USDC', 'USD Coin (legacy)'),
    ]

    # Unique identifier for the invoice


    # Internal safe UUID for sharing (32-char hex)
    internal_id = models.CharField(
        max_length=32,
        unique=True,
        default=generate_payment_transaction_id, # Reuse the same UUID4 hex generator
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

    # WHICH CHAIN MAY SETTLE THIS INVOICE (Codex audit 2026-08-01, [P1]).
    #
    # token_type alone cannot answer this: 'CONFIO' is the wire value BOTH
    # before and after the BSC migration, so a legacy Algorand invoice and a
    # new BSC one are indistinguishable. That left the same PENDING row
    # preparable on both rails at once — and the pay contract's on-chain
    # invoiceDone guard is per-chain, so it structurally cannot stop an
    # Algorand group that was already built. Two customers could each pay
    # once and the merchant be credited twice.
    #
    # The rail is therefore recorded at creation and enforced on BOTH sides:
    # prepare_bsc_payment refuses anything but BSC, PayInvoice (the Algorand
    # mutation) refuses anything but ALGORAND. Default ALGORAND so every row
    # that predates this column — and every invoice from an app build that
    # doesn't know to ask for BSC — keeps the rail it was actually created
    # for. Nothing infers the rail from a timer.
    SETTLEMENT_CHAINS = [
        ('BSC', 'BNB Smart Chain'),
        ('ALGORAND', 'Algorand (legacy)'),
    ]
    settlement_chain = models.CharField(
        max_length=10,
        choices=SETTLEMENT_CHAINS,
        default='ALGORAND',
        help_text='The only chain allowed to settle this invoice',
    )
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
            models.Index(fields=['internal_id']),
            models.Index(fields=['merchant_business', 'status']),
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            # The lifetime ceiling, at the one layer nothing routes around.
            # save() covers ORM writes; queryset.update(), bulk_update(),
            # raw SQL and loaddata do not (Codex audit 2026-08-01 [P2]).
            models.CheckConstraint(
                condition=models.Q(
                    expires_at__lte=models.F('created_at')
                    + timedelta(hours=MAX_INVOICE_LIFETIME_HOURS)),
                name='invoice_lifetime_within_24h',
            ),
        ]

    def __str__(self):
        merchant_name = self.merchant_business.name
        return f"INV-{self.internal_id[:8]}: {self.token_type} {self.amount} by {merchant_name}"

    def save(self, *args, **kwargs):
        """The settlement rail is IMMUTABLE once written.

        Both rails check `settlement_chain` at prepare AND at broadcast, but
        those checks only hold if the value cannot move under them. Flipping
        it on a row that already has a prepared payment is precisely how one
        invoice would become settleable on two chains — so the model refuses
        the edit outright rather than trusting every future call site
        (Codex audit 2026-08-01 [P1]). Correcting a genuinely wrong row means
        cancelling it and issuing a new invoice, which is also what the
        merchant's customer sees happen.
        """
        previous_expires_at = None
        if self.pk:
            previous = type(self).all_objects.filter(pk=self.pk).values_list(
                'settlement_chain', 'expires_at').first()
            if previous:
                previous_chain, previous_expires_at = previous
                if previous_chain and previous_chain != self.settlement_chain:
                    raise ValueError(
                        f"Invoice.settlement_chain is immutable "
                        f"({previous_chain} -> {self.settlement_chain}); cancel and reissue instead")

        # The lifetime ceiling belongs HERE, not only in the API and the
        # admin action (Codex round 4): expires_at stays directly editable in
        # the admin and by any ORM caller, so enforcing the bound at every
        # other layer left the invariant optional.
        #
        # It applies only to a CHANGED expires_at (Codex round 5). Rows
        # created while expiry was uncapped can legitimately sit past the
        # ceiling, and a blanket check would make them unsaveable — you
        # could no longer mark one EXPIRED or soft-delete it, which is
        # exactly the maintenance the old rows need. Refuse new over-long
        # expiries; never trap an existing row.
        expiry_changed = self.expires_at is not None and self.expires_at != previous_expires_at
        if expiry_changed:
            # created_at is unset until auto_now_add fires on insert; for a
            # new row "now" IS the creation moment.
            created = self.created_at or timezone.now()
            ceiling = created + timedelta(hours=MAX_INVOICE_LIFETIME_HOURS)
            if self.expires_at > ceiling:
                raise ValueError(
                    f"Invoice.expires_at {self.expires_at.isoformat()} exceeds the "
                    f"{MAX_INVOICE_LIFETIME_HOURS}h ceiling from creation "
                    f"({ceiling.isoformat()})")
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        """Check if the invoice has expired"""
        return timezone.now() > self.expires_at

    @property
    def qr_code_data(self):
        """Generate QR code data for the invoice"""
        return f"confio://pay/{self.internal_id}"
