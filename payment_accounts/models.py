import uuid

from django.db import models
from django.db.models import Q


class Provider(models.TextChoices):
    COBRE = 'cobre', 'Cobre'
    INFINIA = 'infinia', 'Infinia'


class ResourceStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACTIVE = 'active', 'Active'
    SUSPENDED = 'suspended', 'Suspended'
    REJECTED = 'rejected', 'Rejected'
    CLOSED = 'closed', 'Closed'
    FAILED = 'failed', 'Failed'


class ProviderProfile(models.Model):
    """Provider-side representation of one isolated Confío account holder."""

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    confio_account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, related_name='payment_provider_profiles'
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    provider_owner_id = models.CharField(max_length=160, null=True, blank=True)
    owner_type = models.CharField(
        max_length=20,
        choices=[('individual', 'Individual'), ('business', 'Business')],
    )
    status = models.CharField(
        max_length=20, choices=ResourceStatus.choices, default=ResourceStatus.PENDING
    )
    kyc_mode = models.CharField(max_length=40, blank=True, default='')
    identity_verification = models.ForeignKey(
        'security.IdentityVerification',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='payment_provider_profiles',
    )
    identity_snapshot = models.JSONField(default=dict, blank=True)
    provider_status = models.CharField(max_length=80, blank=True, default='')
    provider_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['confio_account', 'provider'],
                name='payment_profile_account_provider_uniq',
            ),
            models.UniqueConstraint(
                fields=['provider', 'provider_owner_id'],
                condition=Q(provider_owner_id__isnull=False) & ~Q(provider_owner_id=''),
                name='payment_profile_provider_owner_uniq',
            ),
        ]
        indexes = [models.Index(fields=['provider', 'status'])]


class FinancialAccount(models.Model):
    """Persistent provider balance; legal ownership is recorded explicitly."""

    OWNERSHIP_CHOICES = [
        ('provider_named', 'Provider named account'),
        ('omnibus_subledger', 'Omnibus subledger'),
        ('platform_liquidity', 'Platform liquidity account'),
    ]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    provider_profile = models.ForeignKey(
        ProviderProfile, on_delete=models.PROTECT, related_name='financial_accounts'
    )
    provider_account_id = models.CharField(max_length=160, null=True, blank=True)
    ownership_structure = models.CharField(max_length=30, choices=OWNERSHIP_CHOICES)
    country = models.CharField(max_length=3)
    asset = models.CharField(max_length=24)
    status = models.CharField(
        max_length=20, choices=ResourceStatus.choices, default=ResourceStatus.PENDING
    )
    provider_status = models.CharField(max_length=80, blank=True, default='')
    available_balance = models.DecimalField(max_digits=38, decimal_places=18, default=0)
    current_balance = models.DecimalField(max_digits=38, decimal_places=18, default=0)
    balance_updated_at = models.DateTimeField(null=True, blank=True)
    provider_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['provider_profile', 'country', 'asset', 'ownership_structure'],
                name='payment_account_profile_asset_scope_uniq',
            ),
            models.UniqueConstraint(
                fields=['provider_account_id'],
                condition=Q(provider_account_id__isnull=False) & ~Q(provider_account_id=''),
                name='payment_account_provider_id_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['country', 'asset', 'status']),
            models.Index(fields=['provider_profile', 'status']),
        ]

    @property
    def provider(self):
        return self.provider_profile.provider


class FundingInstruction(models.Model):
    KIND_CHOICES = [
        ('breb_key', 'Bre-B key'),
        ('bank_details', 'Bank details'),
        ('pix_key', 'PIX key'),
        ('qr', 'QR'),
        ('crypto_address', 'Crypto address'),
    ]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    financial_account = models.ForeignKey(
        FinancialAccount, on_delete=models.PROTECT, related_name='funding_instructions'
    )
    provider_resource_id = models.CharField(max_length=160, null=True, blank=True)
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    status = models.CharField(
        max_length=20, choices=ResourceStatus.choices, default=ResourceStatus.PENDING
    )
    reusable = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    display_value = models.CharField(max_length=255, blank=True, default='')
    holder_display_name = models.CharField(max_length=255, blank=True, default='')
    ownership_evidence_available = models.BooleanField(default=False)
    instruction_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['financial_account', 'kind'],
                condition=Q(status__in=['pending', 'active']),
                name='payment_instruction_one_open_kind_uniq',
            ),
            models.UniqueConstraint(
                fields=['financial_account', 'provider_resource_id'],
                condition=Q(provider_resource_id__isnull=False) & ~Q(provider_resource_id=''),
                name='payment_instruction_provider_resource_uniq',
            )
        ]
        indexes = [models.Index(fields=['financial_account', 'kind', 'status'])]


class AccountCapability(models.Model):
    CAPABILITY_CHOICES = [
        ('receive_same_name', 'Receive — same name'),
        ('receive_third_party', 'Receive — third party'),
        ('send_same_name', 'Send — same name'),
        ('send_third_party', 'Send — third party'),
        ('send_qr', 'Send — QR'),
        ('convert', 'Convert'),
        ('crypto_payout', 'Crypto payout'),
    ]
    STATUS_CHOICES = [
        ('enabled', 'Enabled'),
        ('pending', 'Pending approval'),
        ('disabled', 'Disabled'),
        ('not_applicable', 'Not applicable'),
    ]

    financial_account = models.ForeignKey(
        FinancialAccount, on_delete=models.CASCADE, related_name='capabilities'
    )
    capability = models.CharField(max_length=40, choices=CAPABILITY_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    reason = models.CharField(max_length=255, blank=True, default='')
    provider_value = models.JSONField(default=dict, blank=True)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['financial_account', 'capability'],
                name='payment_account_capability_uniq',
            )
        ]


class PayoutDestination(models.Model):
    KIND_CHOICES = [
        ('breb_key', 'Bre-B key'),
        ('bank_account', 'Bank account'),
        ('crypto_wallet', 'Crypto wallet'),
        ('qr', 'QR'),
    ]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    confio_account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, related_name='payment_payout_destinations'
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    country = models.CharField(max_length=3)
    asset = models.CharField(max_length=24)
    label = models.CharField(max_length=100)
    holder_name = models.CharField(max_length=255)
    holder_id_type = models.CharField(max_length=30, blank=True, default='')
    holder_id_number = models.CharField(max_length=100, blank=True, default='')
    provider_destination_id = models.CharField(max_length=160, null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=ResourceStatus.choices, default=ResourceStatus.PENDING
    )
    details = models.JSONField(default=dict)
    provider_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_destination_id'],
                condition=Q(provider_destination_id__isnull=False)
                & ~Q(provider_destination_id=''),
                name='payment_destination_provider_id_uniq',
            )
        ]
        indexes = [models.Index(fields=['confio_account', 'provider', 'status'])]


class MoneyFlow(models.Model):
    KIND_CHOICES = [
        ('fund', 'Fund'),
        ('withdraw', 'Withdraw'),
        ('transfer', 'Transfer'),
        ('convert', 'Convert'),
    ]
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('processing', 'Processing'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
        ('needs_review', 'Needs review'),
    ]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    confio_account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, related_name='money_flows'
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    source_asset = models.CharField(max_length=24)
    source_amount = models.DecimalField(max_digits=38, decimal_places=18)
    target_asset = models.CharField(max_length=24)
    target_amount = models.DecimalField(max_digits=38, decimal_places=18, null=True, blank=True)
    gross_amount = models.DecimalField(max_digits=38, decimal_places=18, null=True, blank=True)
    net_amount = models.DecimalField(max_digits=38, decimal_places=18, null=True, blank=True)
    confio_fee = models.DecimalField(max_digits=38, decimal_places=18, default=0)
    provider_cost = models.DecimalField(max_digits=38, decimal_places=18, default=0)
    fee_asset = models.CharField(max_length=24, blank=True, default='')
    legacy_ramp_transaction = models.ForeignKey(
        'ramps.RampTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='money_flows',
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['confio_account', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]


class MoneyOperation(models.Model):
    TYPE_CHOICES = [
        ('deposit', 'Deposit'),
        ('payin', 'Pay-in'),
        ('payout', 'Payout'),
        ('internal_transfer', 'Internal transfer'),
        ('conversion', 'Conversion'),
        ('refund', 'Refund'),
        ('reversal', 'Reversal'),
    ]
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('submitted', 'Submitted'),
        ('processing', 'Processing'),
        ('settling', 'Settling'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
        ('needs_review', 'Needs review'),
        ('unknown', 'Unknown'),
    ]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    money_flow = models.ForeignKey(
        MoneyFlow, on_delete=models.PROTECT, null=True, blank=True, related_name='operations'
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    operation_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    source_account = models.ForeignKey(
        FinancialAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='outgoing_operations',
    )
    destination_account = models.ForeignKey(
        FinancialAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='incoming_operations',
    )
    external_destination = models.JSONField(default=dict, blank=True)
    provider_operation_id = models.CharField(max_length=160, null=True, blank=True)
    idempotency_key = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    provider_status = models.CharField(max_length=80, blank=True, default='')
    source_asset = models.CharField(max_length=24)
    source_amount = models.DecimalField(max_digits=38, decimal_places=18)
    target_asset = models.CharField(max_length=24, blank=True, default='')
    target_amount = models.DecimalField(max_digits=38, decimal_places=18, null=True, blank=True)
    provider_fee = models.DecimalField(max_digits=38, decimal_places=18, default=0)
    confio_fee = models.DecimalField(max_digits=38, decimal_places=18, default=0)
    fee_asset = models.CharField(max_length=24, blank=True, default='')
    failure_code = models.CharField(max_length=100, blank=True, default='')
    failure_detail = models.TextField(blank=True, default='')
    provider_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'idempotency_key'],
                name='payment_operation_idempotency_uniq',
            ),
            models.UniqueConstraint(
                fields=['provider', 'provider_operation_id'],
                condition=Q(provider_operation_id__isnull=False) & ~Q(provider_operation_id=''),
                name='payment_operation_provider_id_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['provider', 'status']),
            models.Index(fields=['money_flow', 'created_at']),
        ]


class LedgerEntry(models.Model):
    DIRECTION_CHOICES = [('credit', 'Credit'), ('debit', 'Debit')]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    provider = models.CharField(max_length=20, choices=Provider.choices)
    financial_account = models.ForeignKey(
        FinancialAccount, on_delete=models.PROTECT, related_name='ledger_entries'
    )
    operation = models.ForeignKey(
        MoneyOperation, on_delete=models.PROTECT, null=True, blank=True, related_name='ledger_entries'
    )
    provider_entry_id = models.CharField(max_length=160)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    asset = models.CharField(max_length=24)
    amount = models.DecimalField(max_digits=38, decimal_places=18)
    balance_after = models.DecimalField(max_digits=38, decimal_places=18, null=True, blank=True)
    occurred_at = models.DateTimeField()
    provider_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['occurred_at', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_entry_id'],
                name='payment_ledger_provider_entry_uniq',
            )
        ]
        indexes = [models.Index(fields=['financial_account', '-occurred_at'])]


class ProviderWebhookEvent(models.Model):
    STATUS_CHOICES = [
        ('received', 'Received'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
        ('ignored', 'Ignored'),
    ]

    provider = models.CharField(max_length=20, choices=Provider.choices)
    event_id = models.CharField(max_length=160)
    event_type = models.CharField(max_length=160, blank=True, default='')
    raw_body = models.TextField(blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    signature = models.CharField(max_length=512, blank=True, default='')
    event_timestamp = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'event_id'], name='payment_webhook_provider_event_uniq'
            )
        ]
        indexes = [
            models.Index(fields=['provider', 'status', 'received_at']),
            models.Index(fields=['event_type', 'received_at']),
        ]


class EligibilityPolicy(models.Model):
    SCOPE_CHOICES = [
        ('account_opening', 'Account opening'),
        ('funding_instruction', 'Funding instruction'),
        ('deposit', 'Deposit'),
        ('payin', 'Pay-in'),
        ('payout', 'Payout'),
        ('conversion', 'Conversion'),
    ]
    DECISION_CHOICES = [
        ('allow', 'Allow'),
        ('block', 'Block'),
        ('review', 'Manual review'),
    ]

    provider = models.CharField(max_length=20, choices=Provider.choices)
    scope = models.CharField(max_length=40, choices=SCOPE_CHOICES)
    version = models.PositiveIntegerField()
    is_active = models.BooleanField(default=False)
    default_decision = models.CharField(
        max_length=10, choices=DECISION_CHOICES, default='block'
    )
    default_reason_code = models.CharField(max_length=100, default='no_matching_eligibility_rule')
    description = models.TextField(blank=True, default='')
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'scope', 'version'],
                name='payment_eligibility_policy_version_uniq',
            ),
            models.UniqueConstraint(
                fields=['provider', 'scope'],
                condition=Q(is_active=True),
                name='payment_eligibility_one_active_policy_uniq',
            ),
        ]
        ordering = ['provider', 'scope', '-version']


class EligibilityRule(models.Model):
    """First matching rule wins; empty selector lists mean any value."""

    policy = models.ForeignKey(
        EligibilityPolicy, on_delete=models.CASCADE, related_name='rules'
    )
    priority = models.PositiveIntegerField()
    decision = models.CharField(max_length=10, choices=EligibilityPolicy.DECISION_CHOICES)
    reason_code = models.CharField(max_length=100)
    message = models.TextField(blank=True, default='')
    nationalities = models.JSONField(default=list, blank=True)
    residence_countries = models.JSONField(default=list, blank=True)
    account_countries = models.JSONField(default=list, blank=True)
    document_types = models.JSONField(default=list, blank=True)
    document_issuing_countries = models.JSONField(default=list, blank=True)
    destination_countries = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['policy', 'priority'], name='payment_eligibility_rule_priority_uniq'
            )
        ]
        ordering = ['priority', 'id']


class EligibilityDecision(models.Model):
    """Audit record containing the exact policy version and evaluated context."""

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    confio_account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, related_name='payment_eligibility_decisions'
    )
    policy = models.ForeignKey(
        EligibilityPolicy, on_delete=models.PROTECT, related_name='decisions'
    )
    matched_rule = models.ForeignKey(
        EligibilityRule,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='decisions',
    )
    money_flow = models.ForeignKey(
        MoneyFlow, on_delete=models.PROTECT, null=True, blank=True, related_name='eligibility_decisions'
    )
    decision = models.CharField(max_length=10, choices=EligibilityPolicy.DECISION_CHOICES)
    reason_code = models.CharField(max_length=100)
    policy_version = models.PositiveIntegerField()
    rule_snapshot = models.JSONField(default=dict, blank=True)
    context = models.JSONField(default=dict)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-decided_at']
        indexes = [
            models.Index(fields=['confio_account', '-decided_at']),
            models.Index(fields=['decision', '-decided_at']),
        ]
