"""Cuenta inteligente mirrors (docs/designs/cuenta-inteligente-spec.md 7.1).

The contract is the source of truth. Every mirror field that reflects chain
state is written by smart_account/reconcile.py from SmartAccountEvent rows,
never from a mutation's optimistic result. Rows created at prepare time
(a draft rule, a draft designation) stay inert drafts until their event.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from users.models import SoftDeleteModel


class SmartAccount(SoftDeleteModel):
    STATUS_CHOICES = [
        ('none', 'Created, never subscribed'),
        ('active', 'Active'),
        ('cancel_pending', 'Cancelled, period running'),
        ('expired', 'Expired (assets returning)'),
        ('inherited', 'Inherited (withdraw-only)'),
    ]
    BILLING_CHOICES = [
        ('current', 'Current'),
        ('payment_due', 'Payment due'),
        ('notice', 'Notice running'),
        ('sale_allowed', 'Sale allowed'),
    ]
    PLAN_CHOICES = [('', 'None'), ('monthly', 'Monthly'), ('annual', 'Annual')]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='smart_accounts')
    # The personal users.Account whose key signs for this account.
    owner_account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, related_name='owned_smart_accounts')
    # The users.Account row of type 'smart' (its bsc_address is the contract).
    account = models.ForeignKey(
        'users.Account', on_delete=models.PROTECT, null=True, blank=True,
        related_name='smart_account_rows')
    contract_address = models.CharField(max_length=42, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='none')
    billing_status = models.CharField(max_length=16, choices=BILLING_CHOICES, default='current')
    plan = models.CharField(max_length=8, choices=PLAN_CHOICES, blank=True, default='')
    next_plan = models.CharField(max_length=8, choices=PLAN_CHOICES, blank=True, default='')
    paid_until = models.DateTimeField(null=True, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    notice_started_at = models.DateTimeField(null=True, blank=True)
    sale_allowed_at = models.DateTimeField(null=True, blank=True)
    forced_sale_for_period = models.DateTimeField(null=True, blank=True)
    confio_sale_latched = models.BooleanField(default=False)
    inherited_from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='smart_accounts_passed_on')
    inherited_at = models.DateTimeField(null=True, blank=True)
    created_tx = models.CharField(max_length=66, blank=True, default='')
    created_block = models.BigIntegerField(null=True, blank=True)
    # Last block whose events were applied to this row (reconcile cursor).
    synced_block = models.BigIntegerField(null=True, blank=True)
    # Notification bookkeeping (7.7): one message per day / per event.
    last_due_notice_at = models.DateTimeField(null=True, blank=True)
    sale_eve_notified_for = models.DateTimeField(null=True, blank=True)
    returned_notified_at = models.DateTimeField(null=True, blank=True)
    renewal_price_notified_for = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One own account per user; any number of inherited ones.
            models.UniqueConstraint(
                fields=['owner_user'],
                condition=~Q(status='inherited') & Q(deleted_at__isnull=True),
                name='smart_account_one_own_per_user'),
        ]
        indexes = [models.Index(fields=['status', 'billing_status'], name='smart_acct_status_idx')]

    def __str__(self):
        return f'SmartAccount {self.contract_address} ({self.status})'

    @property
    def is_inherited(self):
        return self.status == 'inherited'

    def subscription_current(self, now=None):
        """A paid period is running (the IA+ entitlement rule)."""
        now = now or timezone.now()
        return (self.status in ('active', 'cancel_pending') and self.paid_until is not None
                and self.paid_until > now)


class SmartAccountEvent(models.Model):
    """Append-only mirror of contract events: the audit trail."""
    smart_account = models.ForeignKey(
        SmartAccount, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
    address = models.CharField(max_length=42)
    tx_hash = models.CharField(max_length=66)
    log_index = models.PositiveIntegerField()
    name = models.CharField(max_length=40)
    args = models.JSONField(default=dict)
    block_number = models.BigIntegerField()
    block_hash = models.CharField(max_length=66, blank=True, default='')
    block_time = models.DateTimeField()
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tx_hash', 'log_index'], name='smart_event_log_uniq')]
        indexes = [
            models.Index(fields=['smart_account', 'block_number', 'log_index'], name='smart_event_order_idx'),
            models.Index(fields=['applied_at'], name='smart_event_applied_idx'),
        ]
        ordering = ['block_number', 'log_index']

    def __str__(self):
        return f'{self.name} {self.tx_hash}#{self.log_index}'


class SmartAccountCharge(models.Model):
    """One per collected fee (Subscribed or FeeCollected)."""
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='charges')
    event = models.OneToOneField(SmartAccountEvent, on_delete=models.PROTECT, related_name='charge')
    plan = models.CharField(max_length=8)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    fee_usd = models.DecimalField(max_digits=24, decimal_places=18)
    cusd_amount = models.CharField(max_length=80, default='0')
    cusd_plus_shares = models.CharField(max_length=80, default='0')
    p_plus = models.CharField(max_length=80, default='0')
    paid_with = models.CharField(max_length=10, default='cusd')  # cusd | cusd_plus | mixed | sale
    tx_hash = models.CharField(max_length=66)
    status = models.CharField(max_length=12, default='collected')
    charged_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-charged_at', '-id']


class SmartAccountForcedSale(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('sent', 'Sent'), ('succeeded', 'Succeeded'),
        ('failed', 'Failed, will retry'),
    ]
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='forced_sales')
    # The unpaid period (the paid_until that lapsed).
    period_end = models.DateTimeField()
    notice_started_at = models.DateTimeField(null=True, blank=True)
    dollars_out = models.CharField(max_length=80, blank=True, default='')
    fee_collected = models.CharField(max_length=80, blank=True, default='')
    tx_hash = models.CharField(max_length=66, blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['smart_account', 'period_end'], name='smart_forced_sale_period_uniq'),
        ]


class SmartAccountForcedSaleLeg(models.Model):
    forced_sale = models.ForeignKey(SmartAccountForcedSale, on_delete=models.CASCADE, related_name='legs')
    attempt = models.PositiveIntegerField(default=1)
    position = models.PositiveSmallIntegerField()
    asset = models.CharField(max_length=42)
    asset_key = models.CharField(max_length=64, blank=True, default='')
    amount_in = models.CharField(max_length=80, default='0')
    dollars_out = models.CharField(max_length=80, blank=True, default='')
    quote_ref = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        ordering = ['forced_sale_id', 'attempt', 'position']


class SmartAccountStandingAuthorization(models.Model):
    """The owner's Face-confirmed consent for one payment rule (7.5): a bank
    payment rule bound to destination, amount and frequency (with the
    rule's own limits for a run with nobody present), or a send rule bound
    to payee wallet, amount and frequency."""
    KIND_CHOICES = [('payout', 'Bank payout'), ('send', 'Send to a person')]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default='payout')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    payout_destination = models.ForeignKey(
        'payment_accounts.PayoutDestination', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    # Send rules: the payee wallet the authorization is bound to.
    payee_address = models.CharField(max_length=42, blank=True, default='')
    rail = models.CharField(max_length=24)
    amount_usd = models.DecimalField(max_digits=18, decimal_places=2)
    frequency = models.CharField(max_length=10)
    # sha256 over destination identity + amount + frequency.
    binding_hash = models.CharField(max_length=64)
    # '' when Face did not apply to this user (never verified; business).
    face_action_key = models.CharField(max_length=160, blank=True, default='')
    face_required = models.BooleanField(default=True)
    max_bridge_cost_bps = models.PositiveIntegerField(default=150)
    fx_tolerance_bps = models.PositiveIntegerField(default=300)
    reference_fx_rate = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    authorized_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=40, blank=True, default='')


class SmartAccountRule(SoftDeleteModel):
    KIND_CHOICES = [('send', 'Send'), ('payout', 'Bank payout'), ('buy', 'Buy')]
    FREQUENCY_CHOICES = [('daily', 'Daily'), ('weekly', 'Weekly'), ('biweekly', 'Every two weeks'),
                         ('monthly', 'Monthly')]
    STATE_CHOICES = [('draft', 'Prepared, not on chain'), ('onchain', 'On chain'), ('cancelled', 'Cancelled')]

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='rules')
    onchain_id = models.BigIntegerField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default='draft')
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    token_in = models.CharField(max_length=42)
    token_out = models.CharField(max_length=42, blank=True, default='')
    asset_key = models.CharField(max_length=64, blank=True, default='')
    payee_address = models.CharField(max_length=42, blank=True, default='')
    payee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    payout_method = models.ForeignKey(
        'payment_accounts.PayoutDestination', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    payout_ref = models.CharField(max_length=66, blank=True, default='')
    payout_rail = models.CharField(max_length=24, blank=True, default='')
    standing_authorization = models.ForeignKey(
        SmartAccountStandingAuthorization, on_delete=models.PROTECT, null=True, blank=True, related_name='rules')
    amount = models.DecimalField(max_digits=18, decimal_places=2)  # US dollars
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    next_run_at = models.DateTimeField(null=True, blank=True)
    # Calendar schedule kept by the backend inside the contract's minimum gap.
    scheduled_for = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=False)
    deactivated_reason = models.CharField(max_length=40, blank=True, default='')
    # A draft that edits an existing on-chain rule (updateRule).
    replaces = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='+')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['smart_account', 'onchain_id'], condition=Q(onchain_id__isnull=False),
                name='smart_rule_onchain_id_uniq'),
        ]
        indexes = [models.Index(fields=['active', 'next_run_at'], name='smart_rule_due_idx')]


class SmartAccountRuleRun(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('sent', 'Sent'), ('ok', 'Executed'),
                      ('skipped', 'Skipped'), ('failed', 'Failed')]
    rule = models.ForeignKey(SmartAccountRule, on_delete=models.PROTECT, related_name='runs')
    scheduled_for = models.DateTimeField()
    tx_hash = models.CharField(max_length=66, blank=True, default='')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    amount_in = models.CharField(max_length=80, blank=True, default='')
    amount_out = models.CharField(max_length=80, blank=True, default='')
    error = models.TextField(blank=True, default='')
    message = models.CharField(max_length=200, blank=True, default='')  # Spanish, user-facing
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['rule', 'scheduled_for'], name='smart_rule_run_slot_uniq')]
        ordering = ['-scheduled_for']


class SmartAccountPayout(models.Model):
    """Links an executed payment rule's on-chain PayoutSent to the provider order."""
    rule_run = models.OneToOneField(SmartAccountRuleRun, on_delete=models.PROTECT, related_name='payout')
    journey = models.ForeignKey(
        'payment_accounts.InfiniaJourney', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    provider = models.CharField(max_length=20, default='infinia')
    rail = models.CharField(max_length=24)
    deposit_address = models.CharField(max_length=42, blank=True, default='')
    usdt_amount = models.CharField(max_length=80, blank=True, default='')
    fiat_amount = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    fiat_currency = models.CharField(max_length=3, blank=True, default='')
    status = models.CharField(max_length=16, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SmartAccountBeneficiary(models.Model):
    """Never deleted; replaced rows are closed."""
    STATE_CHOICES = [
        ('draft', 'Prepared, not on chain'),
        ('pending_acceptance', 'Named, awaiting acceptance'),
        ('active', 'Accepted'),
        ('declined', 'Declined'),
        ('lapsed', 'Acceptance window lapsed'),
        ('stale_address', 'Beneficiary wallet changed'),
        ('removed', 'Removed or replaced'),
    ]
    designation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='beneficiaries')
    beneficiary_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='smart_account_designations')
    beneficiary_address = models.CharField(max_length=42)
    challenge_window_seconds = models.BigIntegerField()
    verified_at_designation = models.BooleanField(default=False)
    residence_check = models.CharField(max_length=40, blank=True, default='')
    disclosure_accepted_at = models.DateTimeField(null=True, blank=True)
    designated_at = models.DateTimeField(null=True, blank=True)
    designated_tx = models.CharField(max_length=66, blank=True, default='')
    expires_at = models.DateTimeField(null=True, blank=True)
    acceptance_checked_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_tx = models.CharField(max_length=66, blank=True, default='')
    declined_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    stale_notified_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['beneficiary_user', 'state'], name='smart_benef_user_idx')]


class SmartAccountClaim(models.Model):
    STATE_CHOICES = [('pending', 'Pending'), ('cancelled', 'Cancelled'), ('executed', 'Executed')]
    beneficiary_row = models.ForeignKey(SmartAccountBeneficiary, on_delete=models.PROTECT, related_name='claims')
    initiated_at = models.DateTimeField()
    executable_at = models.DateTimeField()
    initiated_tx = models.CharField(max_length=66)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_tx = models.CharField(max_length=66, blank=True, default='')
    executed_at = models.DateTimeField(null=True, blank=True)
    executed_tx = models.CharField(max_length=66, blank=True, default='')
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default='pending')
    last_owner_notice_at = models.DateTimeField(null=True, blank=True)
    owner_notices_sent = models.PositiveIntegerField(default=0)
    executable_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['initiated_tx'], name='smart_claim_initiated_tx_uniq')]

    def display_state(self, now=None):
        if self.state == 'pending' and (now or timezone.now()) >= self.executable_at:
            return 'executable'
        return self.state


class SmartAccountRelayTx(models.Model):
    """Durability row for relayer-originated transactions (7.4): written with
    the deterministic signed hash BEFORE broadcast."""
    STATUS_CHOICES = [
        ('signed', 'Signed, broadcast unconfirmed'), ('sent', 'Broadcast, receipt pending'),
        ('confirmed', 'Mined and final'), ('reverted', 'Mined but reverted'),
        ('reorged', 'Orphaned by a reorg'), ('dropped', 'Never reached the chain'),
    ]
    LIVE_STATUSES = ('signed', 'sent', 'confirmed')

    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='relay_txs')
    kind = models.CharField(max_length=32)
    # Idempotency key within (account, kind): the period, the rule run, the token.
    source_id = models.CharField(max_length=120)
    calldata = models.TextField()
    signed_tx_hash = models.CharField(max_length=66, unique=True)
    sponsor_nonce = models.BigIntegerField(null=True, blank=True)
    gas_limit = models.PositiveIntegerField(default=0)
    max_fee_wei = models.CharField(max_length=32, blank=True, default='')
    block_number = models.BigIntegerField(null=True, blank=True)
    block_hash = models.CharField(max_length=66, blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='signed')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # At most one live transaction per (account, kind, source).
            models.UniqueConstraint(
                fields=['smart_account', 'kind', 'source_id'],
                condition=Q(status__in=('signed', 'sent', 'confirmed')),
                name='smart_relay_tx_live_uniq'),
        ]
        indexes = [models.Index(fields=['status', 'updated_at'], name='smart_relay_status_idx')]


class SmartAccountPreparedAction(models.Model):
    """A call batch the server prepared for one user to sign. The relay
    policy accepts an account batch only if it byte-matches one of these,
    unexpired and unconsumed (7.4)."""
    request_id = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    signer_address = models.CharField(max_length=42)
    # The account contract the calls act on ('' until created: predicted).
    target_address = models.CharField(max_length=42)
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    kind = models.CharField(max_length=32)
    calls = models.JSONField()
    calls_hash = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    not_after = models.BigIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField()
    consumed = models.BooleanField(default=False)
    consumed_at = models.DateTimeField(null=True, blank=True)
    sponsored_batch = models.ForeignKey(
        'blockchain.SponsoredBatch', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'consumed', 'expires_at'], name='smart_prepared_user_idx'),
                   models.Index(fields=['target_address', 'consumed'], name='smart_prepared_target_idx')]


class SmartAccountScanCursor(models.Model):
    """Last block scanned for factory + account events."""
    key = models.CharField(max_length=40, unique=True)
    block_number = models.BigIntegerField()
    updated_at = models.DateTimeField(auto_now=True)
