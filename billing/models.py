from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Ceil
from django.utils import timezone
from users.fields import EncryptedCharField

from . import ids
from .money import FEE_DENOMINATOR, FEE_NUMERATOR


def default_reminder_offsets():
    return [3, 0, -3]


class SubjectStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    ARCHIVED = 'archived', 'Archived'
    BLOCKED = 'blocked', 'Blocked'


class ObligationStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    OPEN = 'open', 'Open'
    HELD = 'held', 'Held'
    DISPUTED = 'disputed', 'Disputed'
    PAYMENT_PENDING = 'payment_pending', 'Payment pending'
    PAID = 'paid', 'Paid'
    PAST_DUE = 'past_due', 'Past due'
    VOID = 'void', 'Void'
    UNCOLLECTIBLE = 'uncollectible', 'Uncollectible'


class BillingInvoiceStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    OPEN = 'open', 'Open'
    PAYMENT_PENDING = 'payment_pending', 'Payment pending'
    PAID = 'paid', 'Paid'
    PAST_DUE = 'past_due', 'Past due'
    VOID = 'void', 'Void'
    UNCOLLECTIBLE = 'uncollectible', 'Uncollectible'


class PaymentIntentStatus(models.TextChoices):
    REQUIRES_PAYMENT_METHOD = 'requires_payment_method', 'Requires payment method'
    REQUIRES_CONFIRMATION = 'requires_confirmation', 'Requires confirmation'
    PROCESSING = 'processing', 'Processing'
    SUCCEEDED = 'succeeded', 'Succeeded'
    FAILED = 'failed', 'Failed'
    CANCELED = 'canceled', 'Canceled'


ACTIVE_PAYMENT_INTENT_STATUSES = (
    PaymentIntentStatus.REQUIRES_PAYMENT_METHOD,
    PaymentIntentStatus.REQUIRES_CONFIRMATION,
    PaymentIntentStatus.PROCESSING,
)


class BillingPaymentStatus(models.TextChoices):
    PROCESSING = 'processing', 'Processing'
    CONFIRMED = 'confirmed', 'Confirmed'
    FAILED = 'failed', 'Failed'
    REVERSED = 'reversed', 'Reversed'


class ApplicationStatus(models.TextChoices):
    PAYMENT_CONFIRMED = 'payment_confirmed', 'Payment confirmed'
    APPLICATION_PENDING = 'application_pending', 'Application pending'
    ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
    REJECTED = 'rejected', 'Rejected'
    MISMATCH = 'mismatch', 'Mismatch'
    MANUAL_REVIEW = 'manual_review', 'Manual review'


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ImmutableJournalModel(models.Model):
    """Application guard; the migration adds the authoritative DB trigger."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError(f'{type(self).__name__} rows are append-only')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError(f'{type(self).__name__} rows are append-only')


class ObligationSubject(TimestampedModel):
    mode = models.CharField(max_length=8, choices=[('test', 'Test'), ('live', 'Live')], default='live')
    SUBJECT_TYPES = [
        ('person', 'Person'),
        ('business', 'Business'),
        ('membership', 'Membership'),
        ('other', 'Other'),
    ]

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_subjects')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.subject_id, editable=False)
    external_id = models.CharField(max_length=255)
    confio_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='billing_subjects')
    subject_type = models.CharField(max_length=20, choices=SUBJECT_TYPES, default='person')
    display_label = models.CharField(max_length=160, blank=True)
    masked_reference = models.CharField(max_length=80, blank=True)
    status = models.CharField(
        max_length=16, choices=SubjectStatus.choices, default=SubjectStatus.ACTIVE)
    locale = models.CharField(max_length=16, default='es-PE')
    timezone = models.CharField(max_length=64, default='America/Lima')
    metadata = models.JSONField(default=dict, blank=True)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('business', 'mode', 'external_id'), name='billing_subject_business_external_uniq'),
        ]
        indexes = [
            models.Index(fields=('business', 'status', 'id'), name='bill_subj_tenant_status_idx'),
        ]


class BillingSchedule(TimestampedModel):
    """A recurring bill schedule. Collection always requires payer signature."""

    mode = models.CharField(max_length=8, choices=[('test', 'Test'), ('live', 'Live')], default='live')

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_schedules')
    subject = models.ForeignKey(
        ObligationSubject, on_delete=models.PROTECT, related_name='billing_schedules')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.schedule_id, editable=False)
    external_reference = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=[('active', 'Active'), ('paused', 'Paused'),
                               ('canceled', 'Canceled'), ('completed', 'Completed')],
        default='active')
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default='PEN')
    presentation_mode = models.CharField(
        max_length=24, choices=[('payer_amount', 'Payer amount'),
                               ('receiver_net_target', 'Receiver net target')],
        default='payer_amount')
    interval_months = models.PositiveSmallIntegerField(default=1)
    anchor_day = models.PositiveSmallIntegerField(default=1)
    days_until_due = models.PositiveSmallIntegerField(default=10)
    next_period_start = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    max_periods = models.PositiveIntegerField(null=True, blank=True)
    generated_periods = models.PositiveIntegerField(default=0)
    timezone = models.CharField(max_length=64, default='America/Lima')
    reminder_offsets_days = models.JSONField(default=default_reminder_offsets)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('business', 'mode', 'external_reference'),
                                    name='billing_schedule_business_external_uniq'),
            models.CheckConstraint(condition=Q(amount_minor__gt=0),
                                   name='billing_schedule_amount_positive'),
            models.CheckConstraint(condition=Q(anchor_day__gte=1, anchor_day__lte=28),
                                   name='billing_schedule_anchor_valid'),
            models.CheckConstraint(condition=Q(interval_months__gte=1),
                                   name='billing_schedule_interval_positive'),
        ]
        indexes = [
            models.Index(fields=('status', 'next_period_start', 'id'),
                         name='bill_sch_due_idx'),
        ]


class BillingObligation(TimestampedModel):
    mode = models.CharField(max_length=8, choices=[('test', 'Test'), ('live', 'Live')], default='live')
    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_obligations')
    subject = models.ForeignKey(
        ObligationSubject, on_delete=models.PROTECT, related_name='obligations')
    schedule = models.ForeignKey(
        BillingSchedule, null=True, blank=True, on_delete=models.PROTECT,
        related_name='obligations')
    period_key = models.CharField(max_length=32, blank=True)
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.obligation_id, editable=False)
    external_reference = models.CharField(max_length=255)
    currency = models.CharField(max_length=3, default='PEN')
    original_amount_minor = models.PositiveBigIntegerField()
    amount_paid_minor = models.PositiveBigIntegerField(default=0)
    amount_remaining_minor = models.PositiveBigIntegerField()
    line_items_snapshot = models.JSONField(default=list)
    period_start = models.DateField()
    period_end = models.DateField()
    issued_at = models.DateTimeField()
    due_at = models.DateTimeField()
    status = models.CharField(
        max_length=24, choices=ObligationStatus.choices, default=ObligationStatus.DRAFT)
    source_version = models.CharField(max_length=80, blank=True)
    allocation_policy = models.CharField(max_length=32, default='oldest_first')
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('business', 'mode', 'external_reference'),
                name='billing_obligation_business_external_uniq'),
            models.UniqueConstraint(
                fields=('schedule', 'period_key'), condition=Q(schedule__isnull=False),
                name='billing_obligation_schedule_period_uniq'),
            models.CheckConstraint(
                condition=Q(original_amount_minor__gt=0),
                name='billing_obligation_original_positive'),
            models.CheckConstraint(
                condition=Q(
                    original_amount_minor=F('amount_paid_minor') + F('amount_remaining_minor')),
                name='billing_obligation_projection_balances'),
            models.CheckConstraint(
                condition=Q(period_end__gte=F('period_start')),
                name='billing_obligation_period_order'),
        ]
        indexes = [
            models.Index(
                fields=('business', 'status', 'due_at', 'id'),
                name='bill_obl_tenant_due_idx'),
            models.Index(fields=('subject', 'period_start', 'id'), name='bill_obl_subject_period_idx'),
        ]


class BillingInvoice(TimestampedModel):
    SOURCES = [
        ('api', 'API'),
        ('dashboard', 'Dashboard'),
        ('schedule', 'Schedule'),
        ('import', 'Import'),
    ]

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_invoices')
    subject = models.ForeignKey(
        ObligationSubject, on_delete=models.PROTECT, related_name='billing_invoices')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.invoice_id, editable=False)
    number = models.CharField(max_length=80)
    status = models.CharField(
        max_length=24, choices=BillingInvoiceStatus.choices,
        default=BillingInvoiceStatus.DRAFT)
    currency = models.CharField(max_length=3, default='PEN')
    subtotal_minor = models.PositiveBigIntegerField()
    amount_paid_minor = models.PositiveBigIntegerField(default=0)
    amount_remaining_minor = models.PositiveBigIntegerField()
    period_start = models.DateField()
    period_end = models.DateField()
    due_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    description = models.CharField(max_length=500, blank=True)
    line_items_snapshot = models.JSONField(default=list)
    metadata = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=16, choices=SOURCES)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('business', 'number'), name='billing_invoice_business_number_uniq'),
            models.CheckConstraint(
                condition=Q(subtotal_minor__gt=0), name='billing_invoice_subtotal_positive'),
            models.CheckConstraint(
                condition=Q(
                    subtotal_minor=F('amount_paid_minor') + F('amount_remaining_minor')),
                name='billing_invoice_projection_balances'),
            models.CheckConstraint(
                condition=Q(period_end__gte=F('period_start')),
                name='billing_invoice_period_order'),
        ]
        indexes = [
            models.Index(
                fields=('business', 'status', 'due_at', 'id'),
                name='bill_inv_tenant_due_idx'),
        ]


class BillingInvoiceObligation(models.Model):
    invoice = models.ForeignKey(
        BillingInvoice, on_delete=models.PROTECT, related_name='obligation_links')
    obligation = models.ForeignKey(
        BillingObligation, on_delete=models.PROTECT, related_name='invoice_links')
    selected_amount_minor = models.PositiveBigIntegerField()
    allocation_order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('invoice', 'obligation'), name='billing_invoice_obligation_uniq'),
            models.UniqueConstraint(
                fields=('invoice', 'allocation_order'), name='billing_invoice_allocation_order_uniq'),
            models.CheckConstraint(
                condition=Q(selected_amount_minor__gt=0),
                name='billing_invoice_selected_positive'),
        ]
        ordering = ('allocation_order', 'id')


class BillingPaymentIntent(TimestampedModel):
    billing_invoice = models.ForeignKey(
        BillingInvoice, on_delete=models.PROTECT, related_name='payment_intents')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.payment_intent_id, editable=False)
    payer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='billing_payment_intents')
    payer_business = models.ForeignKey(
        'users.Business', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='billing_payment_intents_as_payer')
    payer_account = models.ForeignKey(
        'users.Account', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='billing_payment_intents')
    status = models.CharField(
        max_length=32, choices=PaymentIntentStatus.choices,
        default=PaymentIntentStatus.REQUIRES_PAYMENT_METHOD)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default='PEN')
    expires_at = models.DateTimeField()
    last_payment_error = models.CharField(max_length=255, blank=True)
    legacy_invoice = models.OneToOneField(
        'payments.Invoice', null=True, blank=True, on_delete=models.PROTECT,
        related_name='billing_payment_intent')
    idempotency_key = models.CharField(max_length=255, blank=True)
    client_secret_hash = models.CharField(max_length=128, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('billing_invoice',),
                condition=Q(status__in=ACTIVE_PAYMENT_INTENT_STATUSES),
                name='billing_one_active_intent_per_invoice'),
            models.UniqueConstraint(
                fields=('billing_invoice', 'idempotency_key'),
                condition=~Q(idempotency_key=''),
                name='billing_intent_idempotency_uniq'),
            models.CheckConstraint(
                condition=Q(amount_minor__gt=0), name='billing_intent_amount_positive'),
        ]
        indexes = [
            models.Index(fields=('billing_invoice', 'status', 'id'), name='bill_pi_invoice_status_idx'),
        ]


class SettlementQuote(TimestampedModel):
    """Immutable-at-acceptance commercial-to-settlement conversion snapshot."""

    payment_intent = models.OneToOneField(
        BillingPaymentIntent, on_delete=models.PROTECT, related_name='settlement_quote')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.quote_id, editable=False)
    commercial_amount_minor = models.PositiveBigIntegerField()
    commercial_currency = models.CharField(max_length=3, default='PEN')
    presentation_mode = models.CharField(
        max_length=24, choices=[('payer_amount', 'Payer amount'),
                               ('receiver_net_target', 'Receiver net target')])
    rate = models.DecimalField(max_digits=24, decimal_places=12)
    rate_source = models.CharField(max_length=50)
    rate_fetched_at = models.DateTimeField()
    settlement_asset = models.CharField(max_length=16, default='CUSD_PLUS')
    settlement_decimals = models.PositiveSmallIntegerField(default=18)
    gross_units = models.DecimalField(max_digits=78, decimal_places=0)
    fee_units = models.DecimalField(max_digits=78, decimal_places=0)
    receiver_net_units = models.DecimalField(max_digits=78, decimal_places=0)
    display_amount = models.DecimalField(max_digits=19, decimal_places=6)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(commercial_amount_minor__gt=0),
                name='billing_quote_commercial_positive'),
            models.CheckConstraint(condition=Q(rate__gt=0), name='billing_quote_rate_positive'),
            models.CheckConstraint(condition=Q(gross_units__gt=0), name='billing_quote_gross_positive'),
            models.CheckConstraint(
                condition=Q(gross_units=F('fee_units') + F('receiver_net_units')),
                name='billing_quote_settlement_balances'),
            models.CheckConstraint(
                condition=Q(
                    fee_units=Ceil(F('gross_units') * FEE_NUMERATOR / FEE_DENOMINATOR)),
                name='billing_quote_fee_exact'),
        ]


class BillingPayment(TimestampedModel):
    billing_invoice = models.ForeignKey(
        BillingInvoice, on_delete=models.PROTECT, related_name='payments')
    payment_intent = models.ForeignKey(
        BillingPaymentIntent, on_delete=models.PROTECT, related_name='payments')
    legacy_payment = models.OneToOneField(
        'payments.PaymentTransaction', on_delete=models.PROTECT,
        related_name='billing_payment')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.payment_id, editable=False)
    status = models.CharField(
        max_length=16, choices=BillingPaymentStatus.choices,
        default=BillingPaymentStatus.PROCESSING)
    commercial_amount_minor = models.PositiveBigIntegerField()
    commercial_currency = models.CharField(max_length=3, default='PEN')
    settlement_asset = models.CharField(max_length=16)
    settlement_decimals = models.PositiveSmallIntegerField()
    gross_units = models.DecimalField(max_digits=78, decimal_places=0)
    fee_units = models.DecimalField(max_digits=78, decimal_places=0)
    receiver_net_units = models.DecimalField(max_digits=78, decimal_places=0)
    chain = models.CharField(max_length=16, default='BSC')
    transaction_hash = models.CharField(max_length=66, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    settlement_snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(commercial_amount_minor__gt=0),
                name='billing_payment_commercial_positive'),
            models.CheckConstraint(
                condition=Q(gross_units__gt=0), name='billing_payment_gross_positive'),
            models.CheckConstraint(
                condition=Q(fee_units__gte=0, receiver_net_units__gte=0),
                name='billing_payment_parts_nonnegative'),
            models.CheckConstraint(
                condition=Q(gross_units=F('fee_units') + F('receiver_net_units')),
                name='billing_payment_settlement_balances'),
            models.CheckConstraint(
                condition=Q(
                    fee_units=Ceil(
                        F('gross_units') * FEE_NUMERATOR / FEE_DENOMINATOR)),
                name='billing_payment_fee_exact'),
        ]
        indexes = [
            models.Index(
                fields=('billing_invoice', 'status', 'id'),
                name='bill_pay_invoice_status_idx'),
            models.Index(fields=('transaction_hash',), name='bill_pay_tx_hash_idx'),
        ]


class PaymentEffect(ImmutableJournalModel):
    EFFECT_TYPES = [
        ('payment', 'Payment'),
        ('reversal', 'Reversal'),
        ('reallocation', 'Reallocation'),
        ('refund', 'Refund'),
    ]

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_payment_effects')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.effect_id, editable=False)
    semantic_key = models.CharField(max_length=255)
    effect_type = models.CharField(max_length=16, choices=EFFECT_TYPES)
    billing_payment = models.ForeignKey(
        BillingPayment, null=True, blank=True, on_delete=models.PROTECT,
        related_name='effects')
    parent_effect = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='compensating_effects')
    commercial_currency = models.CharField(max_length=3)
    commercial_delta_minor = models.BigIntegerField()
    provenance = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('business', 'semantic_key'), name='billing_effect_semantic_uniq'),
            models.CheckConstraint(
                condition=~Q(commercial_delta_minor=0), name='billing_effect_delta_nonzero'),
        ]
        indexes = [
            models.Index(fields=('business', 'created_at', 'id'), name='bill_effect_tenant_time_idx'),
        ]


class PaymentAllocationEntry(ImmutableJournalModel):
    effect = models.ForeignKey(
        PaymentEffect, on_delete=models.PROTECT, related_name='allocations')
    obligation = models.ForeignKey(
        BillingObligation, on_delete=models.PROTECT, related_name='allocation_entries')
    commercial_delta_minor = models.BigIntegerField()
    allocation_order = models.PositiveIntegerField()
    allocation_revision = models.PositiveIntegerField(default=1)
    quote_reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('effect', 'allocation_order'), name='billing_effect_allocation_order_uniq'),
            models.UniqueConstraint(
                fields=('effect', 'obligation', 'allocation_revision'),
                name='billing_effect_obligation_revision_uniq'),
            models.CheckConstraint(
                condition=~Q(commercial_delta_minor=0),
                name='billing_allocation_delta_nonzero'),
        ]
        ordering = ('allocation_order', 'id')


class SettlementLeg(ImmutableJournalModel):
    billing_payment = models.ForeignKey(
        BillingPayment, on_delete=models.PROTECT, related_name='settlement_legs')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.settlement_id, editable=False)
    chain_id = models.PositiveBigIntegerField()
    contract_version = models.CharField(max_length=32)
    contract_address = models.CharField(max_length=66, default='')
    invoice_id_bytes32 = models.CharField(max_length=66, default='')
    payer_address = models.CharField(max_length=66, default='')
    receiver_address = models.CharField(max_length=66)
    input_token_address = models.CharField(max_length=66)
    input_token_symbol = models.CharField(max_length=16)
    input_token_decimals = models.PositiveSmallIntegerField()
    gross_units = models.DecimalField(max_digits=78, decimal_places=0)
    fee_token_address = models.CharField(max_length=66)
    fee_units = models.DecimalField(max_digits=78, decimal_places=0)
    output_token_address = models.CharField(max_length=66)
    output_token_symbol = models.CharField(max_length=16, default='')
    output_token_decimals = models.PositiveSmallIntegerField(default=18)
    output_units = models.DecimalField(max_digits=78, decimal_places=0, default=0)
    routed = models.BooleanField(default=False)
    # This is the input-token net consumed for the merchant leg. For a
    # routed payment output_units is the independently denominated amount
    # actually delivered by the contract event.
    receiver_net_units = models.DecimalField(max_digits=78, decimal_places=0)
    transaction_hash = models.CharField(max_length=66)
    block_number = models.PositiveBigIntegerField()
    block_hash = models.CharField(max_length=66)
    transaction_index = models.PositiveIntegerField()
    log_index = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('chain_id', 'transaction_hash', 'log_index'),
                name='billing_settlement_chain_event_uniq'),
            models.CheckConstraint(
                condition=Q(gross_units=F('fee_units') + F('receiver_net_units')),
                name='billing_settlement_leg_balances'),
            models.CheckConstraint(
                condition=Q(gross_units__gt=0, fee_units__gte=0,
                            receiver_net_units__gte=0, output_units__gt=0),
                name='billing_settlement_units_valid'),
            models.CheckConstraint(
                condition=Q(
                    fee_units=Ceil(
                        F('gross_units') * FEE_NUMERATOR / FEE_DENOMINATOR)),
                name='billing_settlement_fee_exact'),
        ]
        indexes = [
            models.Index(fields=('billing_payment', 'id'), name='bill_set_payment_idx'),
        ]


class InstitutionApplication(TimestampedModel):
    connection = models.ForeignKey(
        'InstitutionConnection', null=True, blank=True, on_delete=models.PROTECT,
        related_name='applications')
    billing_payment = models.ForeignKey(
        BillingPayment, on_delete=models.PROTECT, related_name='institution_applications')
    allocation = models.OneToOneField(
        PaymentAllocationEntry, on_delete=models.PROTECT,
        related_name='institution_application')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.application_id, editable=False)
    opaque_subject_reference = models.CharField(max_length=255)
    status = models.CharField(
        max_length=24, choices=ApplicationStatus.choices,
        default=ApplicationStatus.PAYMENT_CONFIRMED)
    idempotency_key = models.CharField(max_length=255, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    acknowledgement_reference = models.CharField(max_length=255, blank=True)
    returned_status = models.CharField(max_length=80, blank=True)
    returned_version = models.CharField(max_length=80, blank=True)
    payload_snapshot = models.JSONField(default=dict)
    available_at = models.DateTimeField(default=timezone.now)
    leased_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=64, blank=True)
    payment_confirmed_at = models.DateTimeField()
    institution_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=('status', 'updated_at', 'id'), name='bill_app_status_age_idx'),
        ]


class BillingEvent(ImmutableJournalModel):
    """Immutable, tenant-safe event snapshot written with a domain transition."""

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_events')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.event_id, editable=False)
    event_type = models.CharField(max_length=80)
    aggregate_type = models.CharField(max_length=40)
    aggregate_id = models.CharField(max_length=40)
    aggregate_version = models.PositiveBigIntegerField()
    transition_key = models.CharField(max_length=255)
    correlation_id = models.CharField(max_length=80, blank=True)
    causation_id = models.CharField(max_length=80, blank=True)
    api_version = models.CharField(max_length=16, default='2026-09-01')
    mode = models.CharField(
        max_length=8, choices=[('test', 'Test'), ('live', 'Live')], default='live')
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('business', 'transition_key'),
                name='billing_event_transition_uniq'),
            models.UniqueConstraint(
                fields=('business', 'aggregate_type', 'aggregate_id',
                        'aggregate_version', 'event_type'),
                name='billing_event_aggregate_version_uniq'),
        ]
        indexes = [
            models.Index(fields=('business', 'created_at', 'id'), name='bill_evt_tenant_time_idx'),
        ]


class BillingOutboxMessage(TimestampedModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('leased', 'Leased'),
        ('dispatched', 'Dispatched'),
        ('failed', 'Failed'),
    ]

    event = models.OneToOneField(
        BillingEvent, on_delete=models.PROTECT, related_name='outbox_message')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.outbox_id, editable=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    available_at = models.DateTimeField()
    lease_token = models.CharField(max_length=64, blank=True)
    leased_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=('status', 'available_at', 'id'),
                name='bill_outbox_claim_idx'),
        ]


class BusinessApiKey(TimestampedModel):
    MODE_CHOICES = [('test', 'Test'), ('live', 'Live')]

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_api_keys')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.api_key_id, editable=False)
    name = models.CharField(max_length=120)
    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default='test')
    prefix = models.CharField(max_length=32, unique=True)
    secret_hmac = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=('business', 'mode', 'revoked_at', 'id'),
                name='bill_key_tenant_mode_idx'),
        ]


class IdempotencyRecord(TimestampedModel):
    STATUS_CHOICES = [
        ('in_progress', 'In progress'),
        ('completed', 'Completed'),
    ]

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT,
        related_name='billing_idempotency_records')
    api_key = models.ForeignKey(
        BusinessApiKey, on_delete=models.PROTECT,
        related_name='idempotency_records')
    mode = models.CharField(max_length=8, choices=BusinessApiKey.MODE_CHOICES)
    key = models.CharField(max_length=255)
    method = models.CharField(max_length=8)
    route = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default='in_progress')
    lease_expires_at = models.DateTimeField()
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('api_key', 'mode', 'method', 'route', 'key'),
                name='billing_idempotency_namespace_uniq'),
        ]
        indexes = [
            models.Index(
                fields=('status', 'lease_expires_at', 'id'),
                name='bill_idem_lease_idx'),
            models.Index(
                fields=('expires_at', 'id'), name='bill_idem_expiry_idx'),
        ]


class WebhookEndpoint(TimestampedModel):
    STATUS_CHOICES = [('active', 'Active'), ('disabled', 'Disabled')]

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_webhook_endpoints')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.webhook_endpoint_id, editable=False)
    mode = models.CharField(max_length=8, choices=BusinessApiKey.MODE_CHOICES)
    url = models.URLField(max_length=500)
    secret = EncryptedCharField(max_length=512)
    event_types = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='active')
    description = models.CharField(max_length=160, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=('business', 'mode', 'status', 'id'),
                         name='bill_wep_tenant_status_idx'),
        ]


class WebhookDelivery(TimestampedModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('leased', 'Leased'), ('delivered', 'Delivered'),
        ('retrying', 'Retrying'), ('failed', 'Failed'),
    ]

    event = models.ForeignKey(
        BillingEvent, on_delete=models.PROTECT, related_name='webhook_deliveries')
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.PROTECT, related_name='deliveries')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.webhook_delivery_id, editable=False)
    replay_number = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    endpoint_url = models.URLField(max_length=500)
    signing_secret = EncryptedCharField(max_length=512)
    event_body = models.JSONField()
    available_at = models.DateTimeField()
    leased_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=64, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('event', 'endpoint', 'replay_number'),
                                    name='billing_webhook_delivery_replay_uniq'),
        ]
        indexes = [
            models.Index(fields=('status', 'available_at', 'id'),
                         name='bill_wdl_claim_idx'),
        ]


class InstitutionConnection(TimestampedModel):
    """Fail-closed adapter configuration; credentials are never exposed by API."""

    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT,
        related_name='billing_institution_connections')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.institution_connection_id, editable=False)
    provider = models.SlugField(max_length=64)
    mode = models.CharField(max_length=8, choices=BusinessApiKey.MODE_CHOICES)
    verification_url = models.URLField(max_length=500, blank=True)
    application_url = models.URLField(max_length=500, blank=True)
    # Shown to members while choosing their institution. Blank is the normal
    # case: the app falls back to a monogram rather than a broken image.
    logo_url = models.URLField(max_length=500, blank=True)
    bearer_token = EncryptedCharField(max_length=1024, blank=True)
    status = models.CharField(
        max_length=16, choices=[('sandbox', 'Sandbox'), ('active', 'Active'),
                               ('disabled', 'Disabled')], default='sandbox')
    live_approved = models.BooleanField(default=False)
    settlement_authority = models.CharField(max_length=80, blank=True)
    refund_authority = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('business', 'provider', 'mode'),
                                    name='billing_institution_connection_uniq'),
        ]


class InstitutionDataRequirement(TimestampedModel):
    connection = models.ForeignKey(
        InstitutionConnection, on_delete=models.CASCADE, related_name='data_requirements')
    field_name = models.CharField(max_length=40)
    purpose = models.CharField(max_length=255)
    required = models.BooleanField(default=True)
    retention_days = models.PositiveIntegerField(default=365)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('connection', 'field_name'),
                                    name='billing_institution_requirement_uniq'),
        ]


class SubjectIdentityValue(TimestampedModel):
    subject = models.ForeignKey(
        ObligationSubject, on_delete=models.PROTECT, related_name='identity_values')
    field_name = models.CharField(max_length=40)
    encrypted_value = EncryptedCharField(max_length=1024)
    verified_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=80, default='user')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('subject', 'field_name'),
                                    name='billing_subject_identity_field_uniq'),
        ]


class InstitutionDataGrant(TimestampedModel):
    connection = models.ForeignKey(
        InstitutionConnection, on_delete=models.PROTECT, related_name='data_grants')
    subject = models.ForeignKey(
        ObligationSubject, on_delete=models.PROTECT, related_name='institution_data_grants')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.identity_grant_id, editable=False)
    field_names = models.JSONField(default=list)
    purpose_snapshot = models.JSONField(default=dict)
    consent_version = models.CharField(max_length=40)
    granted_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=('connection', 'subject', 'revoked_at', 'id'),
                         name='bill_igr_active_idx'),
        ]


class InstitutionIdentitySession(TimestampedModel):
    connection = models.ForeignKey(
        InstitutionConnection, on_delete=models.PROTECT, related_name='identity_sessions')
    subject = models.ForeignKey(
        ObligationSubject, on_delete=models.PROTECT, related_name='identity_sessions')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.identity_session_id, editable=False)
    status = models.CharField(
        max_length=16, choices=[('pending', 'Pending'), ('authorized', 'Authorized'),
                               ('submitted', 'Submitted'), ('expired', 'Expired')],
        default='pending')
    requested_fields = models.JSONField(default=list)
    obligation_references = models.JSONField(default=list)
    nonce = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    token_used_at = models.DateTimeField(null=True, blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=('connection', 'status', 'expires_at', 'id'),
                         name='bill_ise_status_exp_idx'),
        ]


class BillingImportBatch(TimestampedModel):
    mode = models.CharField(max_length=8, choices=[('test', 'Test'), ('live', 'Live')], default='live')
    business = models.ForeignKey(
        'users.Business', on_delete=models.PROTECT, related_name='billing_import_batches')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.import_id, editable=False)
    schema_version = models.CharField(max_length=32)
    source_sha256 = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=[('staged', 'Staged'), ('validating', 'Validating'),
                               ('valid', 'Valid'), ('invalid', 'Invalid'),
                               ('promoting', 'Promoting'), ('completed', 'Completed')],
        default='staged')
    row_count = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    invalid_count = models.PositiveIntegerField(default=0)
    promoted_count = models.PositiveIntegerField(default=0)
    generated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('business', 'mode', 'source_sha256'),
                                    name='billing_import_source_uniq'),
        ]


class BillingImportRow(TimestampedModel):
    batch = models.ForeignKey(
        BillingImportBatch, on_delete=models.PROTECT, related_name='rows')
    row_number = models.PositiveIntegerField()
    payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=[('staged', 'Staged'), ('valid', 'Valid'),
                               ('invalid', 'Invalid'), ('promoted', 'Promoted')],
        default='staged')
    error_code = models.CharField(max_length=80, blank=True)
    error_detail = models.CharField(max_length=255, blank=True)
    promoted_subject = models.ForeignKey(
        ObligationSubject, null=True, blank=True, on_delete=models.PROTECT,
        related_name='import_rows')
    promoted_obligation = models.ForeignKey(
        BillingObligation, null=True, blank=True, on_delete=models.PROTECT,
        related_name='import_rows')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('batch', 'row_number'),
                                    name='billing_import_row_number_uniq'),
        ]
        indexes = [
            models.Index(fields=('batch', 'status', 'row_number'),
                         name='bill_imp_row_status_idx'),
        ]


class BillingReminder(TimestampedModel):
    obligation = models.ForeignKey(
        BillingObligation, on_delete=models.PROTECT, related_name='reminders')
    offset_days = models.SmallIntegerField()
    status = models.CharField(
        max_length=16, choices=[('pending', 'Pending'), ('emitted', 'Emitted'),
                               ('suppressed', 'Suppressed')], default='pending')
    scheduled_for = models.DateTimeField()
    emitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('obligation', 'offset_days'),
                                    name='billing_reminder_obligation_offset_uniq'),
        ]
        indexes = [
            models.Index(fields=('status', 'scheduled_for', 'id'),
                         name='bill_reminder_claim_idx'),
        ]


class CipSandboxMember(TimestampedModel):
    """Durable fake CIP record, reachable only when sandbox is enabled."""

    connection = models.ForeignKey(
        InstitutionConnection, on_delete=models.PROTECT,
        related_name='cip_sandbox_members')
    subject = models.OneToOneField(
        ObligationSubject, on_delete=models.PROTECT,
        related_name='cip_sandbox_member')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.cip_sandbox_member_id,
        editable=False)
    member_number = models.CharField(max_length=80)
    habilidad = models.CharField(
        max_length=16, choices=[('active', 'Active'), ('inactive', 'Inactive')],
        default='inactive')
    paid_through = models.DateField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('connection', 'member_number'),
                name='billing_cip_sandbox_member_number_uniq'),
        ]
        indexes = [
            models.Index(fields=('connection', 'habilidad', 'id'),
                         name='bill_cipsm_status_idx'),
        ]


class CipSandboxApplicationReceipt(TimestampedModel):
    connection = models.ForeignKey(
        InstitutionConnection, on_delete=models.PROTECT,
        related_name='cip_sandbox_receipts')
    member = models.ForeignKey(
        CipSandboxMember, null=True, blank=True, on_delete=models.PROTECT,
        related_name='application_receipts')
    public_id = models.CharField(
        max_length=40, unique=True, default=ids.cip_sandbox_receipt_id,
        editable=False)
    idempotency_key = models.CharField(max_length=255)
    request_sha256 = models.CharField(max_length=64)
    outcome = models.CharField(
        max_length=24, choices=[('acknowledged', 'Acknowledged'),
                               ('mismatch', 'Mismatch'),
                               ('rejected', 'Rejected')])
    response_snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('connection', 'idempotency_key'),
                name='billing_cip_sandbox_receipt_idem_uniq'),
        ]
