"""First-party member checkout over the existing signed BSC payment rail."""

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from exchange_rates.models import ExchangeRate
from payments.models import Invoice, PaymentTransaction
from users.models import Account

from .money import fee_units, minimal_gross_for_receiver_net, receiver_net_units
from .models import (
    ACTIVE_PAYMENT_INTENT_STATUSES,
    BillingInvoice,
    BillingInvoiceObligation,
    BillingInvoiceStatus,
    BillingObligation,
    BillingPaymentIntent,
    BillingPayment,
    BillingPaymentStatus,
    ObligationStatus,
    PaymentIntentStatus,
    SettlementQuote,
)

WAD = 10**18
DISPLAY_SCALE = Decimal('0.000001')


class MemberCheckoutError(ValueError):
    pass


def require_member_payments_enabled(subject):
    if subject.status != 'active' or subject.business.deleted_at is not None:
        raise MemberCheckoutError('institution_membership_unavailable')
    setting_name = ('BILLING_CIP_SANDBOX_ENABLED' if subject.mode == 'test'
                    else 'BILLING_LIVE_API_KEYS_ENABLED')
    if not getattr(settings, setting_name, False):
        raise MemberCheckoutError('billing_payments_disabled')


def _merchant_account(business_id):
    account = (
        Account.objects.select_related('user', 'business')
        .filter(business_id=business_id, account_type='business', deleted_at__isnull=True)
        .exclude(bsc_address__isnull=True).exclude(bsc_address='')
        .order_by('account_index', 'id').first()
    )
    if not account:
        raise MemberCheckoutError('institution_has_no_payment_account')
    return account


def _current_pen_rate(now):
    max_age = timedelta(hours=getattr(settings, 'BILLING_RATE_MAX_AGE_HOURS', 96))
    rate = (
        ExchangeRate.objects.filter(
            source_currency='PEN', target_currency='USD', rate_type='official',
            is_active=True)
        .order_by('-fetched_at', '-id').first()
    )
    if not rate or rate.fetched_at < now - max_age or rate.rate <= 0:
        raise MemberCheckoutError('settlement_rate_unavailable')
    return rate


def _quoted_units(amount_minor, rate, presentation_mode):
    # ExchangeRate.rate is PEN per USD. Round the legacy invoice up to its
    # six-decimal precision, then derive the exact wei used by Pay.
    usd = (Decimal(amount_minor) / Decimal(100)) / Decimal(rate)
    target_units = int((usd * WAD).to_integral_value(rounding=ROUND_CEILING))
    raw_gross = (
        minimal_gross_for_receiver_net(target_units)
        if presentation_mode == 'receiver_net_target' else target_units
    )
    display = (Decimal(raw_gross) / WAD).quantize(DISPLAY_SCALE, rounding=ROUND_CEILING)
    gross = int(display * WAD)
    fee = fee_units(gross)
    return display, gross, fee, receiver_net_units(gross)


class _CheckoutChanged(Exception):
    pass


def create_member_payment_intent(*, obligation_public_id, user, payer_account=None):
    # New intents are serialized by the obligation lock. If another checkout
    # creates an intent while we acquire locks, restart in the canonical order.
    for _ in range(3):
        try:
            with transaction.atomic():
                return _create_member_payment_intent(
                    obligation_public_id=obligation_public_id, user=user,
                    payer_account=payer_account)
        except _CheckoutChanged:
            continue
    raise MemberCheckoutError('payment_in_progress')


def _create_member_payment_intent(*, obligation_public_id, user, payer_account=None):
    """Return a fresh/reusable legacy invoice for a linked member obligation."""
    now = timezone.now()
    obligation_id = BillingObligation.objects.values_list('id', flat=True).get(
        public_id=obligation_public_id, subject__confio_user=user)
    active_query = BillingPaymentIntent.objects.filter(
        billing_invoice__obligation_links__obligation_id=obligation_id,
        status__in=ACTIVE_PAYMENT_INTENT_STATUSES)
    active_ids = list(active_query.order_by('id').values_list('id', flat=True))
    legacy_invoice_ids = list(BillingPaymentIntent.objects.filter(id__in=active_ids)
                              .values_list('legacy_invoice_id', flat=True))
    # Match receipt finalization: legacy payment, legacy invoice, billing
    # payment, intent, invoice, obligation. Never lock nullable joined tables.
    legacy_payments = list(PaymentTransaction.objects.select_for_update().filter(
        invoice_id__in=legacy_invoice_ids).order_by('id'))
    list(Invoice.objects.select_for_update().filter(id__in=legacy_invoice_ids).order_by('id'))
    if [payment.id for payment in legacy_payments] != list(
            PaymentTransaction.objects.filter(invoice_id__in=legacy_invoice_ids)
            .order_by('id').values_list('id', flat=True)):
        raise _CheckoutChanged()
    list(BillingPayment.objects.select_for_update().filter(
        payment_intent_id__in=active_ids).order_by('id'))
    active_intents = list(BillingPaymentIntent.objects.select_for_update().filter(
        id__in=active_ids).order_by('id'))
    list(BillingInvoice.objects.select_for_update().filter(
        id__in=[intent.billing_invoice_id for intent in active_intents]).order_by('id'))
    obligation = BillingObligation.objects.select_for_update().get(
        id=obligation_id, subject__confio_user=user)
    require_member_payments_enabled(obligation.subject)
    if obligation.mode != obligation.subject.mode:
        raise MemberCheckoutError('billing_mode_mismatch')
    if active_ids != list(active_query.order_by('id').values_list('id', flat=True)):
        raise _CheckoutChanged()
    active = active_intents[-1] if active_intents else None
    if active and (len(active_intents) > 1 or active.payer_user_id != user.id):
        raise MemberCheckoutError('payment_in_progress')
    if obligation.status not in (
            ObligationStatus.OPEN, ObligationStatus.PAST_DUE, ObligationStatus.PAYMENT_PENDING):
        raise MemberCheckoutError('obligation_not_payable')
    if obligation.status == ObligationStatus.PAYMENT_PENDING and not active:
        raise MemberCheckoutError('payment_in_progress')
    if active and any(payment.status == 'SUBMITTED' for payment in legacy_payments):
        raise MemberCheckoutError('payment_in_progress')
    from blockchain.models import LIVE_SPONSORED_BATCH_STATUSES, PAYMENT_BATCH_KINDS, SponsoredBatch
    if legacy_payments and SponsoredBatch.objects.filter(
            source_id__in=[payment.id for payment in legacy_payments],
            kind__in=PAYMENT_BATCH_KINDS,
            status__in=LIVE_SPONSORED_BATCH_STATUSES).exists():
        raise MemberCheckoutError('payment_in_progress')
    if obligation.amount_remaining_minor <= 0:
        raise MemberCheckoutError('obligation_not_payable')
    if obligation.currency != 'PEN':
        raise MemberCheckoutError('unsupported_commercial_currency')

    authorizations_valid = all(
        int((payment.blockchain_data or {}).get('pay_deadline') or 0) > now.timestamp()
        for payment in legacy_payments)
    if (active and active.expires_at > now and active.legacy_invoice.status == 'PENDING'
            and authorizations_valid):
        return active
    if active:
        # An issued Pay signature remains usable independently of this API.
        # Let its on-chain deadline and a receipt propagation guard elapse
        # before issuing another invoice for the same commercial obligation.
        for payment in legacy_payments:
            payment_hash = payment.transaction_hash or ''
            deadline = int((payment.blockchain_data or {}).get('pay_deadline') or 0)
            if (payment.status == 'CONFIRMED'
                    or (payment_hash and not payment_hash.startswith('pending_'))
                    or (deadline and now.timestamp() <= deadline + 120)):
                raise MemberCheckoutError('payment_in_progress')
            payment.status = 'FAILED'
            payment.error_message = 'quote_expired'
            payment.save(update_fields=('status', 'error_message', 'updated_at'))
        BillingPayment.objects.filter(payment_intent=active,
            status=BillingPaymentStatus.PROCESSING).update(status=BillingPaymentStatus.FAILED,
                                                          updated_at=now)
        active.status = PaymentIntentStatus.CANCELED
        active.last_payment_error = 'quote_expired'
        active.save(update_fields=('status', 'last_payment_error', 'updated_at'))
        if active.legacy_invoice.status == 'PENDING':
            active.legacy_invoice.status = 'EXPIRED'
            active.legacy_invoice.save(update_fields=('status', 'updated_at'))
        if active.billing_invoice.status in (BillingInvoiceStatus.OPEN, BillingInvoiceStatus.PAYMENT_PENDING):
            active.billing_invoice.status = BillingInvoiceStatus.VOID
            active.billing_invoice.voided_at = now
            active.billing_invoice.save(update_fields=('status', 'voided_at', 'updated_at'))
        if obligation.status == ObligationStatus.PAYMENT_PENDING:
            obligation.status = ObligationStatus.PAST_DUE if obligation.due_at < now else ObligationStatus.OPEN
            obligation.save(update_fields=('status', 'updated_at'))

    rate = _current_pen_rate(now)
    merchant = _merchant_account(obligation.business_id)
    mode = getattr(obligation.schedule, 'presentation_mode', 'payer_amount')
    display, gross, fee, net = _quoted_units(
        obligation.amount_remaining_minor, rate.rate, mode)
    ttl = timedelta(minutes=getattr(settings, 'BILLING_QUOTE_TTL_MINUTES', 15))
    expires_at = now + ttl

    billing_invoice = BillingInvoice.objects.create(
        business=obligation.business, subject=obligation.subject,
        number=f'MEMBER-{obligation.public_id}-{now.strftime("%Y%m%d%H%M%S%f")}',
        status=BillingInvoiceStatus.OPEN, currency=obligation.currency,
        subtotal_minor=obligation.amount_remaining_minor,
        amount_remaining_minor=obligation.amount_remaining_minor,
        period_start=obligation.period_start, period_end=obligation.period_end,
        due_at=obligation.due_at,
        description=(obligation.line_items_snapshot[0].get('description', '')
                     if obligation.line_items_snapshot else ''),
        line_items_snapshot=obligation.line_items_snapshot,
        source='dashboard',
    )
    BillingInvoiceObligation.objects.create(
        invoice=billing_invoice, obligation=obligation,
        selected_amount_minor=obligation.amount_remaining_minor, allocation_order=1)
    legacy_invoice = Invoice.objects.create(
        created_by_user=merchant.user, merchant_business=obligation.business,
        merchant_account=merchant, merchant_display_name=obligation.business.name,
        amount=display, token_type='CUSD_PLUS', settlement_chain='BSC',
        description=billing_invoice.description or f'Cuota {obligation.period_key}',
        status='PENDING', expires_at=expires_at,
    )
    payer_account = payer_account or (
        Account.objects.filter(user=user, account_type='personal', deleted_at__isnull=True)
        .order_by('account_index', 'id').first()
    )
    intent = BillingPaymentIntent.objects.create(
        billing_invoice=billing_invoice, payer_user=user, payer_account=payer_account,
        payer_business=payer_account.business if payer_account else None,
        status=PaymentIntentStatus.REQUIRES_PAYMENT_METHOD,
        amount_minor=obligation.amount_remaining_minor, currency=obligation.currency,
        expires_at=expires_at, legacy_invoice=legacy_invoice,
    )
    SettlementQuote.objects.create(
        payment_intent=intent,
        commercial_amount_minor=obligation.amount_remaining_minor,
        commercial_currency=obligation.currency, presentation_mode=mode,
        rate=rate.rate, rate_source=rate.source, rate_fetched_at=rate.fetched_at,
        settlement_asset='CUSD_PLUS', settlement_decimals=18,
        gross_units=gross, fee_units=fee, receiver_net_units=net,
        display_amount=display, expires_at=expires_at,
    )
    return intent


@transaction.atomic
def attach_prepared_bsc_payment(*, payment_intent_id, legacy_payment,
                                payer_account, payer_business, token_type,
                                gross_units, funding_kind):
    """Atomically connect an existing Pay preparation to the billing ledger."""
    legacy_payment = PaymentTransaction.objects.select_for_update().get(pk=legacy_payment.pk)
    Invoice.objects.select_for_update().get(pk=legacy_payment.invoice_id)
    payment = BillingPayment.objects.select_for_update().filter(legacy_payment=legacy_payment).first()
    intent = BillingPaymentIntent.objects.select_for_update().get(id=payment_intent_id)
    billing_invoice = BillingInvoice.objects.select_for_update().get(pk=intent.billing_invoice_id)
    actual_fee = fee_units(gross_units)
    if payment and payment.status in (BillingPaymentStatus.CONFIRMED, BillingPaymentStatus.REVERSED):
        raise MemberCheckoutError('payment_already_finalized')
    if intent.status not in ACTIVE_PAYMENT_INTENT_STATUSES:
        raise MemberCheckoutError('invoice_not_pending')
    if legacy_payment.invoice_id != intent.legacy_invoice_id:
        raise MemberCheckoutError('payment_intent_mismatch')
    values = {
            'billing_invoice_id': intent.billing_invoice_id,
            'payment_intent': intent,
            'status': BillingPaymentStatus.PROCESSING,
            'commercial_amount_minor': intent.amount_minor,
            'commercial_currency': intent.currency,
            'settlement_asset': token_type,
            'settlement_decimals': 18,
            'gross_units': gross_units,
            'fee_units': actual_fee,
            'receiver_net_units': gross_units - actual_fee,
            'chain': 'BSC',
            'settlement_snapshot': {
                'quote_id': intent.settlement_quote.public_id,
                'funding_kind': funding_kind,
            },
        }
    if payment:
        for field, value in values.items():
            setattr(payment, field, value)
        payment.save()
    else:
        payment = BillingPayment.objects.create(legacy_payment=legacy_payment, **values)
    intent.status = PaymentIntentStatus.PROCESSING
    intent.payer_account = payer_account
    intent.payer_business = payer_business
    intent.save(update_fields=(
        'status', 'payer_account', 'payer_business', 'updated_at'))
    if billing_invoice.status in (BillingInvoiceStatus.OPEN, BillingInvoiceStatus.PAST_DUE):
        billing_invoice.status = BillingInvoiceStatus.PAYMENT_PENDING
        billing_invoice.save(update_fields=('status', 'updated_at'))
    BillingObligation.objects.filter(
        invoice_links__invoice=billing_invoice,
        status__in=(ObligationStatus.OPEN, ObligationStatus.PAST_DUE),
    ).update(status=ObligationStatus.PAYMENT_PENDING, updated_at=timezone.now())
    return payment
