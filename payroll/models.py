import uuid
import secrets
import string
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from users.models import SoftDeleteModel


def generate_run_id():
    """Generate a unique payroll run ID"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))


def generate_payroll_item_id():
    """Generate a unique payroll item ID (32-char hex UUID)"""
    return uuid.uuid4().hex


class PayrollRun(SoftDeleteModel):
    """Represents a payroll batch for a business"""

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('READY', 'Ready'),
        ('PARTIAL', 'Partial'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    TOKEN_TYPES = [
        ('CUSD', 'Confío Dollar'),
        ('CONFIO', 'Confío Token'),
        ('USDC', 'USD Coin'),
    ]

    run_id = models.CharField(max_length=32, unique=True, default=generate_run_id, editable=False)
    business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='payroll_runs',
        help_text="Business owning this payroll run",
    )
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payroll_runs_created',
        help_text="User who created the payroll run",
    )
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES, default='CUSD')
    period_seconds = models.BigIntegerField(null=True, blank=True, help_text="Cap window length in seconds")
    cap_amount = models.DecimalField(
        max_digits=19,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Optional gross cap per window (same decimals as token)",
    )
    gross_total = models.DecimalField(max_digits=19, decimal_places=6, default=Decimal('0'))
    net_total = models.DecimalField(max_digits=19, decimal_places=6, default=Decimal('0'))
    fee_total = models.DecimalField(max_digits=19, decimal_places=6, default=Decimal('0'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    scheduled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run_id']),
            models.Index(fields=['business', 'status']),
            models.Index(fields=['created_by_user']),
        ]

    def __str__(self):
        return f"PAYROLL-{self.run_id} ({self.business.name})"


class PayrollItem(SoftDeleteModel):
    """Single payroll payout to a Confío user/account"""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PREPARED', 'Prepared'),
        ('SUBMITTED', 'Submitted'),
        ('CONFIRMED', 'Confirmed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    internal_id = models.CharField(max_length=32, unique=True, default=generate_payroll_item_id, editable=False)
    run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name='items',
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payroll_items_received',
    )
    recipient_account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='payroll_items_received',
    )
    token_type = models.CharField(max_length=10, choices=PayrollRun.TOKEN_TYPES, default='CUSD')
    net_amount = models.DecimalField(max_digits=19, decimal_places=6)
    gross_amount = models.DecimalField(max_digits=19, decimal_places=6)
    fee_amount = models.DecimalField(max_digits=19, decimal_places=6)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    transaction_hash = models.CharField(max_length=66, blank=True, help_text="Blockchain transaction hash")
    blockchain_data = models.JSONField(null=True, blank=True, help_text="Unsigned transactions and metadata")
    error_message = models.TextField(blank=True)
    executed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_items_executed',
        help_text="Delegate who executed the payout",
    )
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['internal_id']),
            models.Index(fields=['run', 'status']),
            models.Index(fields=['recipient_user']),
            models.Index(fields=['recipient_account']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['run', 'recipient_account'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_recipient_per_run_if_not_deleted_v2'
            )
        ]

    def __str__(self):
        return f"{self.internal_id} -> {self.recipient_account.algorand_address}"

    @property
    def payroll_item_box_id(self):
        """Box key to use on-chain"""
        return self.internal_id


class PayrollRecipient(SoftDeleteModel):
    """
    Saved payroll recipient for a business (no business permissions).
    Used to quickly add payees to payroll runs without granting employee access.
    """
    business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='payroll_recipients',
        help_text="Business that will pay this recipient"
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payroll_recipients_for_businesses'
    )
    recipient_account = models.ForeignKey(
        'users.Account',
        on_delete=models.CASCADE,
        related_name='payroll_recipients_accounts'
    )
    display_name = models.CharField(max_length=255, blank=True, help_text="Friendly name for the recipient")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['business', 'recipient_user']),
            models.Index(fields=['business', 'recipient_account']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['business', 'recipient_user', 'recipient_account'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_payroll_recipient_per_business'
            )
        ]

    def __str__(self):
        return f"{self.display_name or self.recipient_user_id} for {self.business_id}"
