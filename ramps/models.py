import uuid

from django.db import models

from users.models import SoftDeleteModel


class RampPaymentMethod(SoftDeleteModel):
    PROVIDER_TYPES = [
        ('bank', 'Traditional Bank'),
        ('fintech', 'Fintech/Digital Wallet'),
        ('cash', 'Cash/Physical'),
        ('other', 'Other'),
    ]

    code = models.CharField(max_length=50, help_text="Provider code, e.g. WIREPE or QRI-PE")
    country_code = models.CharField(max_length=2, help_text="ISO country code")
    display_name = models.CharField(max_length=100)
    provider_type = models.CharField(max_length=10, choices=PROVIDER_TYPES, default='other')
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)

    country = models.ForeignKey(
        'users.Country',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ramp_payment_methods',
    )
    bank = models.ForeignKey(
        'users.Bank',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ramp_payment_methods',
    )
    legacy_payment_method = models.ForeignKey(
        'p2p_exchange.P2PPaymentMethod',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ramp_payment_methods',
    )

    requires_phone = models.BooleanField(default=False)
    requires_email = models.BooleanField(default=False)
    requires_account_number = models.BooleanField(default=True)
    requires_identification = models.BooleanField(default=False)
    supports_on_ramp = models.BooleanField(default=False)
    supports_off_ramp = models.BooleanField(default=False)

    field_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="Server-owned field schema for AddBankInfo and payout destination capture.",
    )

    class Meta:
        unique_together = [('code', 'country_code')]
        ordering = ['country_code', 'display_order', 'display_name']

    def __str__(self):
        return f'{self.display_name} ({self.country_code})'


class KoyweBankInfo(models.Model):
    """
    Cache of banks available per country from Koywe's /rest/bank-info/{countryCode} endpoint.
    Synced periodically via management command or Celery task.
    """
    bank_code = models.CharField(max_length=100, help_text="Koywe bankCode value")
    name = models.CharField(max_length=200)
    institution_name = models.CharField(max_length=200, blank=True)
    country_code = models.CharField(max_length=3, help_text="ISO 3166-1 alpha-3 country code used by Koywe")
    is_active = models.BooleanField(default=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('bank_code', 'country_code')]
        ordering = ['country_code', 'name']
        indexes = [
            models.Index(fields=['country_code', 'is_active']),
        ]

    def __str__(self):
        return f'{self.name} ({self.bank_code}) [{self.country_code}]'


class RampUserAddress(models.Model):
    user = models.OneToOneField(
        'users.User',
        on_delete=models.CASCADE,
        related_name='ramp_user_address',
    )
    address_street = models.TextField()
    address_city = models.CharField(max_length=100)
    address_state = models.CharField(max_length=100)
    address_zip_code = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'Ramp address for {self.user_id}'


class RampTransaction(models.Model):
    PROVIDER_CHOICES = [
        ('guardarian', 'Guardarian'),
        ('koywe', 'Koywe'),
    ]

    DIRECTION_CHOICES = [
        ('on_ramp', 'On Ramp'),
        ('off_ramp', 'Off Ramp'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('AML_REVIEW', 'AML Review'),
    ]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    provider_order_id = models.CharField(max_length=100, blank=True)
    external_id = models.CharField(max_length=100, blank=True)
    country_code = models.CharField(max_length=2, blank=True)

    actor_user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ramp_transactions',
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ramp_transactions',
    )
    actor_type = models.CharField(
        max_length=10,
        choices=[('user', 'Personal'), ('business', 'Business')],
        default='user',
    )
    actor_display_name = models.CharField(max_length=255, blank=True)
    actor_address = models.CharField(max_length=66, blank=True, default='')

    fiat_currency = models.CharField(max_length=20, blank=True)
    fiat_amount = models.DecimalField(max_digits=19, decimal_places=6, null=True, blank=True)
    crypto_currency = models.CharField(max_length=20, blank=True)
    crypto_amount_estimated = models.DecimalField(max_digits=19, decimal_places=6, null=True, blank=True)
    crypto_amount_actual = models.DecimalField(max_digits=19, decimal_places=6, null=True, blank=True)
    final_currency = models.CharField(max_length=20, default='CUSD')
    final_amount = models.DecimalField(max_digits=19, decimal_places=6, null=True, blank=True)
    status_detail = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    guardarian_transaction = models.OneToOneField(
        'usdc_transactions.GuardarianTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ramp_transaction',
    )
    usdc_deposit = models.OneToOneField(
        'usdc_transactions.USDCDeposit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ramp_transaction',
    )
    usdc_withdrawal = models.OneToOneField(
        'usdc_transactions.USDCWithdrawal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ramp_transaction',
    )
    conversion = models.OneToOneField(
        'conversion.Conversion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ramp_transaction',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['provider', 'direction', '-created_at']),
            models.Index(fields=['actor_user', '-created_at']),
            models.Index(fields=['actor_business', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['provider_order_id']),
            models.Index(fields=['external_id']),
        ]

    def __str__(self):
        return f'{self.provider}:{self.direction}:{self.provider_order_id or self.internal_id}'


class RampWebhookEvent(models.Model):
    PROVIDER_CHOICES = [
        ('koywe', 'Koywe'),
        ('guardarian', 'Guardarian'),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    event_id = models.CharField(max_length=120, unique=True)
    event_type = models.CharField(max_length=120, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-processed_at']
        indexes = [
            models.Index(fields=['provider', 'processed_at']),
            models.Index(fields=['event_type', 'processed_at']),
        ]

    def __str__(self):
        return f'{self.provider}:{self.event_type or "event"}:{self.event_id}'
