import uuid

from django.conf import settings
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
    payin_rail = models.CharField(max_length=50, blank=True, default='', help_text='Verified receiving rail, e.g. SPEI or PIX. Leave blank if ambiguous.')
    payin_document_country = models.CharField(max_length=2, blank=True, default='', help_text='Verified jurisdiction of sender document numbers on this rail (ISO-2). Blank disables automatic same-owner matching.')
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


class ThirdPartyPayinSwitch(models.Model):
    """All three scopes must explicitly allow; no user override of a country stop."""

    provider = models.CharField(max_length=20, choices=Provider.choices)
    country = models.CharField(max_length=2, help_text='Receiving country, ISO-2; not phone country.')
    rail = models.CharField(max_length=50, blank=True, default='', help_text='Blank for country switch; otherwise verified rail code.')
    confio_account = models.ForeignKey('users.Account', null=True, blank=True, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=False)
    evidence = models.TextField(help_text='Approval reference, including required enhanced KYC/KYB review for user grants.')
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        from .providers.common import iso_alpha2
        try:
            self.country = iso_alpha2(self.country)
        except ValueError as exc:
            raise ValidationError({'country': str(exc)})
        self.rail = self.rail.strip().upper()
        if self.confio_account_id and not self.rail:
            raise ValidationError('User switches require a country and rail.')
        if self.enabled and not self.evidence.strip():
            raise ValidationError('Enabling requires approval evidence.')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['provider', 'country', 'rail'], condition=Q(confio_account__isnull=True), name='payin_switch_global_uniq'),
            models.UniqueConstraint(fields=['provider', 'country', 'rail', 'confio_account'], condition=Q(confio_account__isnull=False), name='payin_switch_owner_uniq'),
            models.CheckConstraint(condition=Q(confio_account__isnull=True) | ~Q(rail=''), name='payin_switch_owner_rail'),
        ]


class PayinAdmission(models.Model):
    entry = models.OneToOneField('LedgerEntry', on_delete=models.PROTECT, related_name='payin_admission')
    allowed = models.BooleanField(default=False)
    reason = models.CharField(max_length=80)
    country = models.CharField(max_length=2, blank=True)
    rail = models.CharField(max_length=50, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


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
    display_value = models.TextField(blank=True, default='')
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


class PaymentBridgeQuote(models.Model):
    """Immutable pricing snapshot, not proof of a transfer or provider credit."""

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    confio_account = models.ForeignKey('users.Account', on_delete=models.PROTECT)
    request_id = models.UUIDField()
    money_flow = models.OneToOneField(
        MoneyFlow, on_delete=models.PROTECT, related_name='bridge_quote'
    )
    funding_instruction = models.ForeignKey(FundingInstruction, on_delete=models.PROTECT)
    source_address = models.CharField(max_length=42)
    destination_address = models.CharField(max_length=42)
    source_token_id = models.CharField(max_length=24, default='BSC:USDT')
    destination_token_id = models.CharField(max_length=24, default='POL:USDC')
    amount_units = models.CharField(max_length=78)
    routes = models.JSONField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['confio_account', 'request_id'], name='payment_bridge_quote_request_uniq'
        )]


class PaymentBridgeTransfer(models.Model):
    """A single authorized bridge, including durable source submission evidence."""
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    quote = models.OneToOneField(PaymentBridgeQuote, on_delete=models.PROTECT, related_name='transfer')
    funding_mode = models.CharField(max_length=24, default='wallet', choices=[
        ('wallet', 'Wallet signature'), ('infinia', 'Infinia payout'),
    ])
    status = models.CharField(max_length=24, default='prepared', choices=[
        ('prepared', 'Awaiting authorization'), ('submitted', 'Source submitted'),
        ('bridging', 'Bridging'), ('delivered', 'Delivered on chain'),
        ('refunded', 'Refunded'), ('failed', 'Source failed'),
        ('expired', 'Authorization expired'), ('needs_review', 'Needs review'),
    ])
    deposit_address = models.CharField(max_length=42, unique=True)
    amount_out_min = models.CharField(max_length=78)
    amount_out = models.CharField(max_length=78)
    deadline = models.BigIntegerField()
    calls = models.JSONField(default=list)
    binding = models.JSONField(default=dict)
    source_tx_hash = models.CharField(max_length=66, blank=True)
    destination_tx_hash = models.CharField(max_length=66, blank=True)
    batch = models.OneToOneField('blockchain.SponsoredBatch', on_delete=models.PROTECT, null=True, blank=True)
    provider_credit = models.OneToOneField('LedgerEntry', on_delete=models.PROTECT, null=True, blank=True, related_name='bridge_transfer')
    # Source sponsorship. Persist signed bytes before broadcasting;
    # a worker can re-broadcast the SAME transaction after an ambiguous result.
    signed_raw_tx = models.TextField(blank=True)
    sponsor_address = models.CharField(max_length=42, blank=True)
    sponsor_nonce = models.BigIntegerField(null=True, blank=True)
    actual_out_units = models.CharField(max_length=78, blank=True)
    failure_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['sponsor_address', 'sponsor_nonce'],
            condition=Q(sponsor_nonce__isnull=False), name='payment_bridge_polygon_nonce_uniq',
        )]
        indexes = [models.Index(fields=['status', 'updated_at'], name='pay_bridge_status_idx')]


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


class InfiniaJourney(models.Model):
    """Owner-authorized provider legs; a child success never completes the journey."""
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    money_flow = models.OneToOneField(MoneyFlow, on_delete=models.PROTECT, related_name='infinia_journey')
    request_id = models.UUIDField()
    confio_account = models.ForeignKey('users.Account', on_delete=models.PROTECT)
    direction = models.CharField(max_length=16, choices=[('to_bank', 'To bank'), ('to_wallet', 'To wallet')])
    stage = models.CharField(max_length=32, default='awaiting_credit')
    local_account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name='+')
    crypto_account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name='+')
    funding_credit = models.OneToOneField('LedgerEntry', on_delete=models.PROTECT, null=True, blank=True, related_name='funded_journey')
    bridge = models.OneToOneField(PaymentBridgeTransfer, on_delete=models.PROTECT, null=True, blank=True, related_name='infinia_journey')
    minimum_fx_output = models.DecimalField(max_digits=38, decimal_places=18)
    minimum_wallet_output = models.DecimalField(max_digits=38, decimal_places=18, null=True, blank=True)
    destination_snapshot = models.JSONField(default=dict)
    wallet_address = models.CharField(max_length=42)
    wallet_arrival_units = models.CharField(max_length=78, blank=True)
    wallet_arrival_tx_hash = models.CharField(max_length=66, blank=True)
    wallet_conversion = models.OneToOneField('conversion.Conversion', null=True, blank=True,
        on_delete=models.PROTECT, related_name='local_transfer_journey')
    fx_quote = models.JSONField(default=dict)
    fx_operation = models.OneToOneField(MoneyOperation, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    payout_operation = models.OneToOneField(MoneyOperation, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    failure_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['confio_account', 'request_id'], name='infinia_journey_request_uniq')]
        indexes = [models.Index(fields=['stage', 'updated_at'], name='infinia_journey_stage_idx')]


class LimitIncreaseRequest(models.Model):
    """Enhanced due diligence to raise a provider's monthly limit.

    The documents live in one Didit session (proof of address + source-of-funds
    uploads). Completed submissions are automatically forwarded to Infinia;
    the new limit arrives through the provider's /limits/ endpoint and is never
    set from this row.
    """
    STATUS_CHOICES = [
        ('started', 'Verification started'),
        ('submitted', 'Submitted'),
        ('in_review', 'In review'),
        ('forwarded', 'Forwarded to provider'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('needs_more_info', 'Needs more information'),
    ]
    INCOME_CHOICES = [
        ('employed', 'Employed'),
        ('self_employed', 'Self-employed'),
        ('not_employed', 'Not employed'),
        ('business', 'Business'),
    ]
    SOURCE_CHOICES = [
        ('salary', 'Salary'),
        ('business_income', 'Business income'),
        ('savings', 'Savings'),
        ('investments', 'Investments'),
        ('family_support', 'Family support'),
        ('other', 'Other'),
    ]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    confio_account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, related_name='limit_increase_requests'
    )
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.INFINIA)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='started')
    income_type = models.CharField(max_length=20, choices=INCOME_CHOICES)
    occupation = models.CharField(max_length=120, blank=True, default='')
    expected_monthly_usd = models.DecimalField(max_digits=20, decimal_places=2)
    source_of_funds = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    didit_session_id = models.CharField(max_length=80, unique=True, null=True, blank=True)
    didit_status = models.CharField(max_length=30, blank=True, default='')
    evidence = models.JSONField(default=dict, blank=True, help_text='Didit decision facts; never presigned media URLs.')
    provider_documents = models.JSONField(default=dict, blank=True, help_text='Provider document IDs after forwarding.')
    forwarded_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True, default='', help_text='Internal only.')
    user_message = models.CharField(max_length=255, blank=True, default='', help_text='Shown to the user in the app.')
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['confio_account'],
                condition=Q(status__in=['started', 'submitted', 'in_review']),
                name='limit_increase_one_open_uniq',
            )
        ]
        indexes = [models.Index(fields=['status', 'created_at'], name='limit_increase_status_idx')]


class CobreJourney(models.Model):
    """Owner-authorized provider legs; a child success never completes the journey."""
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    money_flow = models.OneToOneField(MoneyFlow, on_delete=models.PROTECT, related_name='cobre_journey')
    request_id = models.UUIDField()
    confio_account = models.ForeignKey('users.Account', on_delete=models.PROTECT)
    direction = models.CharField(max_length=16, choices=[('to_bank', 'To bank'), ('to_wallet', 'To wallet')])
    stage = models.CharField(max_length=32, default='awaiting_credit')
    local_account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name='+')
    crypto_account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name='+')
    copco_account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name='+')
    ramp_operation = models.OneToOneField(MoneyOperation, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    funding_credit = models.OneToOneField('LedgerEntry', on_delete=models.PROTECT, null=True, blank=True, related_name='cobre_funded_journey')
    bridge = models.OneToOneField(PaymentBridgeTransfer, on_delete=models.PROTECT, null=True, blank=True, related_name='cobre_journey')
    minimum_fx_output = models.DecimalField(max_digits=38, decimal_places=18)
    destination_snapshot = models.JSONField(default=dict)
    wallet_address = models.CharField(max_length=42)
    wallet_arrival_units = models.CharField(max_length=78, blank=True)
    wallet_arrival_tx_hash = models.CharField(max_length=66, blank=True)
    fx_quote = models.JSONField(default=dict)
    fx_operation = models.OneToOneField(MoneyOperation, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    payout_operation = models.OneToOneField(MoneyOperation, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    failure_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['confio_account', 'request_id'], name='cobre_journey_request_uniq')]
        indexes = [models.Index(fields=['stage', 'updated_at'], name='cobre_journey_stage_idx')]


class BrebAppAttestKey(models.Model):
    key_id = models.CharField(max_length=44, primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    public_key = models.TextField()
    receipt = models.BinaryField()
    counter = models.PositiveBigIntegerField(default=0)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class BrebLocationCheck(models.Model):
    """Compliance record of every Bre-B location verification: when, from which
    IP/country, the device reading and the result. Never the device tokens."""
    confio_account = models.ForeignKey('users.Account', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    platform = models.CharField(max_length=8, blank=True)
    passed = models.BooleanField()
    reason = models.CharField(max_length=160, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    ip_country = models.CharField(max_length=2, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    accuracy_m = models.FloatField(null=True, blank=True)
    reading_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['confio_account', '-created_at'])]


class AccountActivation(models.Model):
    """One opening entitlement per owner/country/currency, shared by all rails."""
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    confio_account = models.ForeignKey('users.Account', on_delete=models.PROTECT)
    country = models.CharField(max_length=3)
    asset = models.CharField(max_length=12)
    method_id = models.CharField(max_length=40)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default='10.00')
    status = models.CharField(max_length=24, default='provisioning', choices=[
        ('provisioning', 'Opening account'), ('awaiting_payment', 'Account ready, payment due'),
        ('payment_pending', 'Payment pending'), ('active', 'Active'),
        ('legacy', 'Existing account'), ('failed', 'Opening failed'),
    ])
    payment = models.OneToOneField('send.SendTransaction', null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='account_activation')
    collector_address = models.CharField(max_length=42, blank=True, default='')
    settlement_token_address = models.CharField(max_length=42, blank=True, default='')
    chain_id = models.PositiveIntegerField(default=56)
    accepted_at = models.DateTimeField(null=True, blank=True)
    attempt = models.PositiveIntegerField(default=0)
    opening_failures = models.PositiveIntegerField(default=0)
    opening_error = models.CharField(max_length=40, blank=True, default='')
    next_opening_retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['confio_account', 'country', 'asset'],
                                               name='activation_owner_country_asset_uniq')]
