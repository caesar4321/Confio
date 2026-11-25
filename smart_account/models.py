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
from django.db.models.signals import pre_save
from django.utils import timezone

from users.fields import EncryptedCharField
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
    # The contract's subscriptionEpoch (spec 4.4, invariant 22): bumped by
    # every subscribe, never by a renewal. A rule of an earlier epoch never
    # runs; 0 before the first subscription. Set by reconcile from the
    # Subscribed events.
    subscription_epoch = models.PositiveIntegerField(default=0)
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
    KIND_CHOICES = [('payout', 'Bank payout'), ('send', 'Send to a person'),
                    ('card', 'Card spender allowance'), ('trade', 'Hands-off trades (v2)'),
                    ('purchase', 'Hands-off purchases (v2)')]

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
    # sha256 over destination identity + amount + frequency (and the fee
    # ceiling of an Infinia payment, when there is one).
    binding_hash = models.CharField(max_length=64)
    # '' when Face did not apply to this user (never verified; business).
    face_action_key = models.CharField(max_length=160, blank=True, default='')
    face_required = models.BooleanField(default=True)
    max_bridge_cost_bps = models.PositiveIntegerField(default=150)
    # The processor's fixed fee per payment the owner signed, as a ceiling.
    # Outside max_bridge_cost_bps (spec decision 36). Empty authorizes none.
    max_processor_fee_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    fx_tolerance_bps = models.PositiveIntegerField(default=300)
    reference_fx_rate = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    # Venezuelan Pago Móvil rules (rail 've_pagomovil'): the saved beneficiary
    # the authorization is bound to (phone + bank + cédula, in binding_hash).
    pagomovil_destination = models.ForeignKey(
        'smart_account.SmartAccountPagoMovilDestination', on_delete=models.PROTECT, null=True, blank=True,
        related_name='+')
    # Pago Móvil: the beneficiary's name as the signed summary showed it, sent
    # to Pago ASAP whatever the saved row is renamed to. Empty on rows signed
    # before it was kept (payouts.signed_holder_name).
    holder_name = models.CharField(max_length=120, null=True, blank=True)
    authorized_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=40, blank=True, default='')


class SmartAccountPagoMovilDestination(SoftDeleteModel):
    """A Venezuelan Pago Móvil beneficiary saved for bank payment rules
    (ramps has no saved-beneficiary model: a VE send carries its beneficiary
    in the order). Same validation as the VE send (ramps.ve_pagomovil
    normalize_*). Phone and cédula are encrypted at rest; a removed row is
    soft-deleted, and any rule bound to it stops (payouts.authorization_problem)."""
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    # 58 + 10 digits (ve_pagomovil.normalize_phone).
    phone = EncryptedCharField(max_length=255)
    # SUDEBAN code (ve_pagomovil.normalize_bank).
    bank_code = models.CharField(max_length=4)
    # V/E/J/P/G + digits (ve_pagomovil.normalize_cedula).
    id_number = EncryptedCharField(max_length=255)
    holder_name = models.CharField(max_length=120)
    label = models.CharField(max_length=100)

    class Meta:
        indexes = [models.Index(fields=['user', 'deleted_at'], name='smart_pm_dest_user_idx')]


class SmartAccountRule(SoftDeleteModel):
    # 'card' (decision 35): pulled by an allowlisted card spender, never run
    # by the relayer (automation.due_rules leaves it out).
    KIND_CHOICES = [('send', 'Send'), ('payout', 'Bank payout'), ('buy', 'Buy'), ('card', 'Card allowance'),
                    ('trade', 'Hands-off trades (v2)'), ('purchase', 'Hands-off Comprar purchases (v2)')]
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
    # Rail 've_pagomovil': the saved Pago Móvil beneficiary (payout_method is
    # then empty; payout_ref hashes this row's identity).
    pagomovil_destination = models.ForeignKey(
        SmartAccountPagoMovilDestination, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
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
    # Card rules (decision 35): the contract's cardSpentUsd, mirrored from
    # CardPulled events: gross US dollars taken in the period that starts at
    # next_run_at (stale, in effect zero, once that period ended).
    card_spent_usd = models.DecimalField(max_digits=30, decimal_places=18, default=0)
    # The subscription epoch the rule was stored in on chain (rule(id).epoch);
    # for a draft, the account's epoch when it was prepared. A rule runs, is
    # edited or is stopped only while this is the account's current epoch.
    epoch = models.PositiveIntegerField(default=0)

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
    # Pago ASAP (rail 've_pagomovil'): the VE send order (ramps.ve_send) the
    # owner is sender of record of; its own poller pays and polls it.
    ramp = models.OneToOneField(
        'ramps.RampTransaction', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
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


class SmartAccountTargetAllocation(SoftDeleteModel):
    """The owner's target split of the account's investments (decision 34),
    kept by NEW buys only: one Buy rule per asset, amount = total x weight,
    each one owner-signed. Never kept by selling, and never set by the
    assistant on its own: the weights are the owner's own words.

    A preference record, not chain state: it moves no money. `weights` is
    a list of {"asset_key": "stock:SPYon" | "crypto:BTCB", "weight_bps": int}
    summing to 10000. One live row per account (older rows soft-deleted)."""
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='target_allocations')
    weights = models.JSONField(default=list)
    total_usd = models.DecimalField(max_digits=18, decimal_places=2)  # per period, all buy rules together
    frequency = models.CharField(max_length=10, choices=SmartAccountRule.FREQUENCY_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['smart_account'], condition=Q(deleted_at__isnull=True),
                name='smart_target_allocation_live_uniq'),
        ]


class SmartAccountWatch(SoftDeleteModel):
    """A conditional alert the owner set through Confío IA+ (decision 34):
    "avísame si TSLA baja 5%". When it triggers the owner gets a push and an
    assistant-thread note; if the owner attached an action (a buy they chose:
    asset and amount), the note carries a chip that opens it prefilled for
    the owner to review and sign. Nothing executes on its own, and the
    assistant never suggests a threshold or an asset."""
    KIND_CHOICES = [
        ('asset_price_drop_pct', 'Asset price drops by N%'),
        ('asset_price_rise_pct', 'Asset price rises by N%'),
        ('asset_price_below', 'Asset price below'),
        ('asset_price_above', 'Asset price above'),
        ('fx_rate_below', 'Local currency per USD below'),
        ('fx_rate_above', 'Local currency per USD above'),
    ]
    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='watches')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    asset_key = models.CharField(max_length=64, blank=True, default='')  # price watches
    currency = models.CharField(max_length=3, blank=True, default='')    # FX watches: local currency per 1 USD
    threshold = models.DecimalField(max_digits=24, decimal_places=8)     # a percent for *_pct, else a price/rate
    # The price when the watch was set (or last triggered): the base of the *_pct kinds.
    reference_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    # {"kind": "buy", "asset_key": ..., "amount_usd": "100.00"}: the owner's own choice, or {}.
    action = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    cooldown_hours = models.PositiveIntegerField(default=24)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    last_value = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['active', 'deleted_at'], name='smart_watch_active_idx')]


class SmartAccountCardSpender(models.Model):
    """A card issuer's spender as the factory allowlists it (decision 35),
    mirrored from CardSpenderSet by reconcile.py. `allowed` and the event
    fields are chain state; `label` (what the owner sees, e.g. the card's
    name) is the only field ops set. A Card rule may be prepared only for a
    spender that is allowed here AND on chain."""
    address = models.CharField(max_length=42, unique=True)
    allowed = models.BooleanField(default=False)
    label = models.CharField(max_length=80, blank=True, default='')
    # The CardSpenderSet that last set `allowed` (block, log index, tx).
    set_block = models.BigIntegerField(null=True, blank=True)
    set_log_index = models.PositiveIntegerField(null=True, blank=True)
    set_tx = models.CharField(max_length=66, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.label or "Card spender"} {self.address} ({"allowed" if self.allowed else "removed"})'

    @property
    def display_label(self) -> str:
        return self.label or 'Tu tarjeta'


class SmartAccountCardPause(models.Model):
    """The factory's cardPaused flag (one row, pk=1), mirrored from
    CardPausedSet by reconcile.py. Stops every card pull and Card rule
    creation on every account; nothing else."""
    paused = models.BooleanField(default=False)
    set_block = models.BigIntegerField(null=True, blank=True)
    set_log_index = models.PositiveIntegerField(null=True, blank=True)
    set_tx = models.CharField(max_length=66, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def is_paused(cls) -> bool:
        row = cls.objects.filter(pk=1).first()
        return bool(row and row.paused)


class SmartAccountCardPull(models.Model):
    """One CardPulled (decision 35): the card issuer's spender took exactly
    `usdt_out_wei` USDT from the account, `usd_spent` (gross, the 0.9% exit
    fee included) counted against its Card rule's cap for the period that
    starts at `period_start`. Append-only, one per event."""
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, related_name='card_pulls')
    # Null only when the mirror has no rule with that on-chain id (alerted).
    rule = models.ForeignKey(SmartAccountRule, on_delete=models.PROTECT, null=True, blank=True,
                             related_name='card_pulls')
    event = models.OneToOneField(SmartAccountEvent, on_delete=models.PROTECT, related_name='card_pull')
    onchain_rule_id = models.BigIntegerField()
    spender = models.CharField(max_length=42)
    usdt_out_wei = models.CharField(max_length=80)
    usd_spent = models.DecimalField(max_digits=30, decimal_places=18)
    # The rule's period this pull counted in, and the period's total after it.
    period_start = models.DateTimeField(null=True, blank=True)
    spent_in_period = models.DecimalField(max_digits=30, decimal_places=18, null=True, blank=True)
    tx_hash = models.CharField(max_length=66)
    block_number = models.BigIntegerField()
    pulled_at = models.DateTimeField()
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-block_number', '-id']
        indexes = [models.Index(fields=['smart_account', 'pulled_at'], name='smart_card_pull_acct_idx')]

    def __str__(self):
        return f'CardPulled rule {self.onchain_rule_id} {self.tx_hash}'


# PayoutDestination.provider_data: the bank's last rejection of a CLABE or
# Pix key. That row is Enviar's address book too, and a save there with the
# lookup off replaces the answer with DISABLED: the rejection is kept beside
# it, for payouts.key_rejected, until the bank verifies the key.
KEY_REJECTED = 'rule_key_rejected'
BANK_REJECTIONS = ('ERROR', 'REJECTED')


def _keep_bank_rejection(sender, instance, raw=False, update_fields=None, **kwargs):
    data = instance.provider_data
    if raw or not isinstance(data, dict) or data.get('method_id') not in ('mx_clabe', 'br_pix'):
        return
    if update_fields is not None and 'provider_data' not in update_fields:
        return
    validation = data.get('validation') or {}
    status = str(validation.get('status') or '').upper()
    if status == 'SUCCESSFUL' and validation.get('holder_name'):
        if KEY_REJECTED in data:
            instance.provider_data = {key: value for key, value in data.items() if key != KEY_REJECTED}
        return
    if status in BANK_REJECTIONS:
        kept = {'status': status, 'checked_at': validation.get('checked_at') or ''}
    elif KEY_REJECTED in data or instance.pk is None:
        return
    else:
        # What is being overwritten (the writer holds the row's lock).
        before = sender.objects.filter(pk=instance.pk).values_list('provider_data', flat=True).first()
        before = before if isinstance(before, dict) else {}
        last = before.get('validation') or {}
        kept = before.get(KEY_REJECTED)
        if str(last.get('status') or '').upper() in BANK_REJECTIONS:
            kept = {'status': str(last['status']).upper(), 'checked_at': last.get('checked_at') or ''}
        if not kept:
            return
    instance.provider_data = {**data, KEY_REJECTED: kept}


class SmartRelayTrade(models.Model):
    """One hands-off trade the person asked for in the chat (smart_account/
    relay_trades.py): their exact "sí" makes this row, a Celery task quotes,
    checks and sends relayTrade from the sponsor through relayer.send_relayer_call
    (whose SmartAccountRelayTx row is the durable record of the broadcast), and
    the result is posted in the chat after the receipt.

    `nonce` is the question's own id (assistant/trades.py): a second "sí" to
    the same question finds this row and makes nothing."""
    STATUS_CHOICES = [
        ('waiting_rule', 'Waiting for the Trade rule (cap card)'),
        ('waiting_move', 'Waiting for dollars moved in from the personal wallet'),
        ('pending', 'Asked, not sent'), ('sent', 'relayTrade broadcast, receipt pending'),
        ('done', 'Executed'), ('failed', 'Nothing executed'), ('cancelled', 'Withdrawn before sending'),
        ('unknown', 'Broadcast outcome unknown (resolved by the receipt)'),
    ]
    LIVE = ('waiting_rule', 'waiting_move', 'pending', 'sent', 'unknown')

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name='relay_trades')
    rule = models.ForeignKey(SmartAccountRule, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    nonce = models.CharField(max_length=40)
    conversation_id = models.BigIntegerField(null=True, blank=True)
    side = models.CharField(max_length=4)            # buy | sell
    asset_kind = models.CharField(max_length=6)      # stock | crypto
    ticker = models.CharField(max_length=24)         # TSLA, BTCB, XAUT
    amount_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    sell_all = models.BooleanField(default=False)
    # The request headers the gates read (platform, country), never anything else.
    meta = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default='pending')
    error_code = models.CharField(max_length=60, blank=True, default='')
    relay_tx = models.ForeignKey(SmartAccountRelayTx, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='+')
    tx_hash = models.CharField(max_length=66, blank=True, default='')
    amount_in = models.CharField(max_length=80, blank=True, default='')
    amount_out = models.CharField(max_length=80, blank=True, default='')
    usd_counted = models.CharField(max_length=80, blank=True, default='')
    attempts = models.PositiveIntegerField(default=0)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'nonce'], name='smart_relay_trade_nonce_uniq')]
        indexes = [models.Index(fields=['status', 'updated_at'], name='smart_relay_trade_status_idx')]


class SmartRelayPurchase(models.Model):
    """One hands-off Comprar purchase the person asked for in the chat
    (smart_account/relay_purchases.py): their exact "sí" makes this row; a
    Celery task creates the escrow order (marketplace.checkout.
    prepare_account_order, signed over depositFromDigest with payer = the
    account), checks it and sends relayPurchase from the sponsor through
    relayer.send_relayer_call; the result is posted in the chat after the
    receipt. `nonce` is the question's own id: a second "sí" finds this row."""
    STATUS_CHOICES = [
        ('waiting_rule', 'Waiting for the Purchase rule (cap card)'),
        ('waiting_move', 'Waiting for dollars moved in from the personal wallet'),
        ('pending', 'Asked, not sent'), ('sent', 'relayPurchase broadcast, receipt pending'),
        ('done', 'Paid into the escrow'), ('failed', 'Nothing paid'), ('cancelled', 'Withdrawn before sending'),
        ('unknown', 'Broadcast outcome unknown (resolved by the receipt)'),
    ]
    LIVE = ('waiting_rule', 'waiting_move', 'pending', 'sent', 'unknown')

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    smart_account = models.ForeignKey(SmartAccount, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name='relay_purchases')
    rule = models.ForeignKey(SmartAccountRule, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    nonce = models.CharField(max_length=40)
    conversation_id = models.BigIntegerField(null=True, blank=True)
    product = models.ForeignKey('marketplace.Product', on_delete=models.PROTECT, related_name='+')
    quantity = models.PositiveIntegerField(default=1)
    delivery_address = models.ForeignKey('marketplace.DeliveryAddress', on_delete=models.PROTECT,
                                         related_name='+')
    # The total the person said "sí" to (product + delivery, US dollars): the order must not cost more.
    amount_usd = models.DecimalField(max_digits=14, decimal_places=2)
    title = models.CharField(max_length=100)
    store_name = models.CharField(max_length=80, blank=True, default='')
    order = models.ForeignKey('marketplace.Order', on_delete=models.PROTECT, null=True, blank=True,
                              related_name='+')
    meta = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default='pending')
    error_code = models.CharField(max_length=60, blank=True, default='')
    relay_tx = models.ForeignKey(SmartAccountRelayTx, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='+')
    tx_hash = models.CharField(max_length=66, blank=True, default='')
    usd_counted = models.CharField(max_length=80, blank=True, default='')
    attempts = models.PositiveIntegerField(default=0)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'nonce'], name='smart_relay_purchase_nonce_uniq')]
        indexes = [models.Index(fields=['status', 'updated_at'], name='smart_relay_purch_status_idx')]


pre_save.connect(_keep_bank_rejection, sender='payment_accounts.PayoutDestination',
                 dispatch_uid='smart_account.keep_bank_rejection')
