"""Paid Infinia account opening. A signed internal send buys one entitlement.

No client-supplied amount, recipient, transaction hash or payment ID is accepted.
Unknown provider/payment outcomes retain their original records for reconciliation.
"""
import json
import logging
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AccountActivation
from .services import PaymentAccountError

FEE = Decimal('10.00')


PAID_STATES = ('active', 'legacy')
OPEN_STATES = ('provisioning', 'awaiting_payment', 'payment_pending')


class OpeningFundsError(PaymentAccountError):
    """Recoverable affordability/read failure, not a provider rejection."""


def require_paid(owner, country, asset):
    query = AccountActivation.objects.filter(confio_account=owner, status__in=PAID_STATES)
    if (country, asset) != ('XXX', 'USDC_POL'):
        query = query.filter(country=country, asset=asset)
    if not query.exists():
        raise PaymentAccountError('Paga la apertura de esta cuenta para habilitarla.')


def require_usable(account):
    if account.provider == 'infinia' and account.ownership_structure != 'platform_liquidity':
        require_paid(account.provider_profile.confio_account, account.country, account.asset)


def usable(account):
    try:
        require_usable(account)
        return True
    except PaymentAccountError:
        return False


def visible_accounts(queryset):
    from django.db.models import Exists, OuterRef, Q
    paid = AccountActivation.objects.filter(
        confio_account_id=OuterRef('provider_profile__confio_account_id'), status__in=PAID_STATES)
    return queryset.annotate(_activation_paid=Exists(paid.filter(country=OuterRef('country'), asset=OuterRef('asset'))),
                             _any_activation_paid=Exists(paid)).filter(
        ~Q(provider_profile__provider='infinia') | Q(ownership_structure='platform_liquidity') |
        Q(_activation_paid=True) | Q(country='XXX', asset='USDC_POL', _any_activation_paid=True))


def require_opening_intent(owner, country, asset):
    query = AccountActivation.objects.filter(confio_account=owner, status__in=OPEN_STATES + PAID_STATES)
    if (country, asset) != ('XXX', 'USDC_POL'):
        query = query.filter(country=country, asset=asset)
    if not query.exists():
        raise PaymentAccountError('Confirma el costo de apertura antes de solicitar la cuenta.')
    if not query.filter(status__in=PAID_STATES).exists():
        require_opening_funds(owner)


def require_opening_funds(owner):
    """Fail closed before provider costs; this is not a reservation of user funds."""
    from cusd_plus import vault
    from send.bsc_flow import EVM_ADDR_RE, WAD, activation_unwrap_plan
    if not (getattr(settings, 'CUSD_PLUS_7702_ENABLED', False)
            and getattr(settings, 'BSC_SEND_ENABLED', False)):
        raise OpeningFundsError('El pago de apertura no está disponible todavía.')
    address = (owner.bsc_address or '').lower()
    cusd = getattr(settings, 'CUSD_VAULT_ADDRESS', '').lower()
    savings = getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '').lower()
    if any(not EVM_ADDR_RE.fullmatch(value) or int(value, 16) == 0 for value in (address, cusd, savings)):
        raise OpeningFundsError('No pudimos verificar tu saldo para abrir la cuenta. Intenta de nuevo.')
    try:
        # Spending existing holdings is an exit, not an Ondo mint. Phone/IP
        # eligibility may have changed since acquisition. Use one whole balance.
        cusd_raw = vault.erc20_balance_raw(cusd, address)
        use_savings = cusd_raw < int(FEE * WAD)
        pps = vault.p_plus_wad(fresh=True) if use_savings else WAD
        oracle = vault.last_oracle_price_wad(fresh=True) if use_savings else WAD
        shares_raw = vault.erc20_balance_raw(savings, address) if use_savings else 0
        if pps <= 0 or oracle <= 0 or cusd_raw < 0 or shares_raw < 0:
            raise ValueError('Invalid activation balance or price')
        _, _, error = activation_unwrap_plan(int(FEE * WAD), cusd_raw, shares_raw, pps, oracle,
                                             use_savings=use_savings)
    except Exception as exc:
        raise OpeningFundsError('No pudimos verificar tu saldo para abrir la cuenta. Intenta de nuevo.') from exc
    if error:
        raise OpeningFundsError('Necesitas US$10.00 en tu saldo Confío. Agrega dólares y vuelve a intentarlo.')


def collector():
    from send.bsc_flow import EVM_ADDR_RE
    from cusd_plus.vault import _rpc
    from eth_utils import keccak
    address = getattr(settings, 'INFINIA_ACTIVATION_COLLECTOR_ADDRESS', '').strip().lower()
    treasury = getattr(settings, 'INFINIA_ACTIVATION_SAFE_ADDRESS', '').strip().lower()
    token = getattr(settings, 'CUSD_VAULT_ADDRESS', '').strip().lower()
    if any(not EVM_ADDR_RE.fullmatch(a) or int(a, 16) == 0 for a in (address, treasury, token)):
        raise PaymentAccountError('La activación de cuentas no está disponible todavía.')
    if _rpc('eth_getCode', [address, 'latest']) in (None, '0x', '0x0'):
        raise PaymentAccountError('La activación de cuentas no está disponible todavía.')
    for getter, expected in [('token()', token), ('treasury()', treasury)]:
        data = '0x' + keccak(text=getter)[:4].hex()
        value = _rpc('eth_call', [{'to':address, 'data':data}, 'latest'])
        if not isinstance(value, str) or value.lower() != '0x' + expected[2:].zfill(64):
            raise PaymentAccountError('La activación de cuentas no está disponible todavía.')
    return address


def _send_result(row):
    from cusd_plus.sponsor_7702 import intent_id_hex
    meta = json.loads(row.bsc_calls_json)
    return dict(success=True, send_id=str(row.internal_id), calls=meta['calls'],
                token_type=row.token_type, intent_id=intent_id_hex(meta['kind'], row.pk),
                gross_amount=str(row.amount), fee_amount='0', net_amount=str(row.amount), fee_bps=0)


def _prepare_send(owner, jwt_ctx, row):
    from send.bsc_flow import prepare_bsc_send
    from send.models import SendTransaction
    result = prepare_bsc_send(owner.user, jwt_ctx, row.amount, recipient_address=row.collector_address,
                              memo=f'Activación {row.country} / {row.asset} — pago único',
                              idempotency_key=f'account-activation:{row.internal_id}:{row.attempt}',
                              fee_capable_client=True, activation_id=row.internal_id)
    if not result.get('success'):
        code = result.get('error', '')
        if code == 'insufficient_balance':
            raise PaymentAccountError('Necesitas US$10.00 en tu saldo Confío. Agrega dólares y vuelve a intentarlo.')
        logging.getLogger(__name__).warning('Activation payment preparation rejected: %s', code)
        raise PaymentAccountError('No pudimos preparar el pago. Intenta de nuevo en unos minutos.')
    payment = SendTransaction.objects.get(internal_id=result['send_id'])
    meta = json.loads(payment.bsc_calls_json)
    if (payment.token_type != 'CUSD'
            or str(meta.get('token', '')).lower() != row.settlement_token_address.lower()
            or Decimal(str(meta.get('receipt', {}).get('fee', '0'))) != 0
            or str(meta.get('activation_id')) != str(row.internal_id)
            or payment.sender_address.lower() != owner.bsc_address.lower()
            or payment.recipient_address.lower() != row.collector_address
            or payment.amount != row.amount):
        raise PaymentAccountError('No pudimos preparar el pago de apertura para esta cuenta.')
    return payment


def _definitively_failed(payment):
    from blockchain.models import SponsoredBatch
    from send.kinds import BSC_SEND_KINDS
    return payment.status == 'FAILED' and not SponsoredBatch.objects.filter(
        source_id=payment.pk, kind__in=BSC_SEND_KINDS,
    ).exclude(status__in=['reverted', 'noop_failed']).exists()


def opening_ready(row):
    from django.db.models import Q
    from django.utils import timezone
    from .local_money import accounts_for, pair_status, METHODS, receiving_ready
    local, crypto = accounts_for(row.confio_account, row.country, row.asset)
    if pair_status(local, crypto) != 'active':
        return False
    if local.provider_profile.status != 'active' or crypto.provider_profile.status != 'active':
        return False
    receive_methods = [m for m in METHODS.values()
                       if m.country == row.country and m.asset == row.asset and m.direction == 'receive']
    unexpired = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    return (any(receiving_ready(local, method) for method in receive_methods)
            and crypto.funding_instructions.filter(unexpired, kind='crypto_address', status='active').exclude(display_value='').exists())


def require_payment_ready(row):
    if (row.chain_id != int(getattr(settings, 'BSC_CHAIN_ID', 56))
            or row.settlement_token_address.lower() != getattr(settings, 'CUSD_VAULT_ADDRESS', '').lower()):
        raise PaymentAccountError('La configuración del pago cambió. Contacta a soporte para continuar.')
    if not opening_ready(row):
        raise PaymentAccountError('La cuenta todavía no está lista. Intenta de nuevo más tarde.')


@transaction.atomic
def _opening(owner, identity, method_id, accepted_fee=None):
    """Consent -> provision -> prepare payment. Provider readiness precedes any charge."""
    from types import SimpleNamespace
    from users.models import User
    from django.utils import timezone
    from .local_money import activation_preflight
    method, _ = activation_preflight(owner, identity, method_id)
    # One unfinished opening per verified customer, across their Confío accounts.
    User.objects.select_for_update().get(pk=owner.user_id)
    row = AccountActivation.objects.select_for_update(of=('self',)).select_related('payment').filter(
        confio_account=owner, country=method.country, asset=method.asset).first()
    if row is None:
        if accepted_fee is None:
            return SimpleNamespace(status='consent_required', amount=FEE), None
        if Decimal(str(accepted_fee)) != FEE:
            raise PaymentAccountError('Confirma el costo vigente de US$10.00.')
        if AccountActivation.objects.filter(confio_account__user_id=owner.user_id, status__in=OPEN_STATES).exists():
            raise PaymentAccountError('Completa la apertura pendiente antes de solicitar otra cuenta.')
        require_opening_funds(owner)
        address = collector()  # Check collection configuration before incurring provider costs.
        row = AccountActivation.objects.create(
            confio_account=owner, country=method.country, asset=method.asset, method_id=method_id,
            amount=FEE, status='provisioning', accepted_at=timezone.now(),
            collector_address=address, settlement_token_address=getattr(settings,'CUSD_VAULT_ADDRESS','').lower(),
            chain_id=int(getattr(settings,'BSC_CHAIN_ID',56)))
    return row


def prepare(owner, identity, method_id, jwt_ctx, accepted_fee=None):
    row = _opening(owner, identity, method_id, accepted_fee)
    if isinstance(row, tuple):
        return row  # Consent-only quote: no provider request or payment.
    row = reconcile(row.pk)  # Commit external provider results BEFORE preparing a payment.
    require_opening_without_error(row)
    return _payment(owner, row.pk, jwt_ctx)


def require_opening_without_error(row):
    if not row.opening_error:
        return
    if row.next_opening_retry_at:
        message = ('No pudimos completar la apertura con el proveedor. '
                   'Volveremos a intentarlo automáticamente. Puedes salir y revisar más tarde.')
    else:
        message = ('No pudimos completar la apertura. '
                   'Contacta a soporte para revisar la solicitud antes de volver a intentarlo.')
    raise PaymentAccountError(f'{message} Referencia: {row.internal_id}')


def _clear_opening_error(row):
    row.opening_failures = 0
    row.opening_error = ''
    row.next_opening_retry_at = None


OPENING_ERROR_FIELDS = ['opening_failures', 'opening_error', 'next_opening_retry_at']


@transaction.atomic
def _payment(owner, activation_id, jwt_ctx):
    row = AccountActivation.objects.select_for_update(of=('self',)).select_related('payment').get(pk=activation_id, confio_account=owner)
    if row.status in ('active', 'legacy', 'failed', 'provisioning'):
        return row, None
    if row.payment_id:
        if row.payment.status != 'FAILED':
            if row.payment.status == 'PENDING':
                require_payment_ready(row)
            return row, _send_result(row.payment) if row.payment.status == 'PENDING' else None
        if not _definitively_failed(row.payment):
            return row, None
        row.attempt += 1
    if not getattr(settings, 'CUSD_PLUS_7702_ENABLED', False):
        raise PaymentAccountError('El pago de apertura no está disponible todavía.')
    require_payment_ready(row)
    row.payment = _prepare_send(owner, jwt_ctx, row)
    row.status = 'payment_pending'
    row.save(update_fields=['payment', 'attempt', 'status', 'updated_at'])
    return row, _send_result(row.payment)


@transaction.atomic
def reconcile(activation_id):
    """Keep opening without the app. A confirmed payment only unlocks an already-open account."""
    from . import local_money
    row = AccountActivation.objects.select_for_update(of=('self',)).select_related('payment','confio_account__user').get(pk=activation_id)
    if row.status == 'payment_pending' and row.payment_id and row.payment.status == 'CONFIRMED':
        row.status = 'active'
        _clear_opening_error(row)
        row.save(update_fields=['status', 'updated_at', *OPENING_ERROR_FIELDS])
        return row
    if row.status not in OPEN_STATES:
        return row
    payment_can_execute = bool(row.payment_id and not _definitively_failed(row.payment))
    # Submitted/unknown payments must settle against their original opening.
    if payment_can_execute and row.payment.status != 'PENDING':
        return row
    from .models import ProviderProfile
    terminal = ['rejected', 'failed', 'closed']
    local, crypto = local_money.accounts_for(row.confio_account, row.country, row.asset)
    if (ProviderProfile.objects.filter(confio_account=row.confio_account, provider='infinia', status__in=terminal).exists()
            or any(account and account.status in terminal for account in (local, crypto))):
        if not payment_can_execute:
            row.status = 'failed'
            row.save(update_fields=['status', 'updated_at'])
        return row
    if opening_ready(row):
        # A webhook may have finished provisioning during the retry delay.
        if row.status == 'provisioning':
            row.status = 'payment_pending' if row.payment_id else 'awaiting_payment'
        _clear_opening_error(row)
        row.save(update_fields=['status', 'updated_at', *OPENING_ERROR_FIELDS])
        return row
    if row.opening_error and (
        row.next_opening_retry_at is None or row.next_opening_retry_at > timezone.now()
    ):
        return row
    # Recheck on app polling and worker retries too. Keep affordability failures
    # out of provider retry/error state, so a later top-up can resume safely.
    require_opening_funds(row.confio_account)
    from .schema import _verified_identity
    try:
        identity = _verified_identity(row.confio_account)
    except PaymentAccountError:
        identity = None
    try:
        status = local_money.activate(row.confio_account, identity, row.method_id)
    except OpeningFundsError:
        # A later guard may observe spending between the crypto and local
        # requests. Commit any provider IDs already returned, without turning
        # this recoverable balance problem into a permanent provider rejection.
        return row
    except Exception as exc:
        from .clients import ProviderAPIError, ComplianceHandoffError
        from .eligibility import EligibilityDenied, EligibilityPolicyNotConfigured
        # Retain provider IDs after an ambiguous response; never recreate the request.
        logging.getLogger(__name__).exception('Activation opening remains pending: %s', row.internal_id)
        retryable = not isinstance(exc, (
            PaymentAccountError, ComplianceHandoffError, EligibilityDenied, EligibilityPolicyNotConfigured,
        ))
        if isinstance(exc, ProviderAPIError):
            retryable = exc.retryable or exc.status_code == 429
        row.opening_failures += 1
        row.opening_error = 'provider_unavailable' if retryable else 'opening_needs_review'
        # The activation lock serializes app and worker retries. Never reuse the
        # payment attempt counter or change the provider's idempotency key.
        delay = min(30 * 2 ** min(row.opening_failures - 1, 5), 900)
        row.next_opening_retry_at = timezone.now() + timedelta(seconds=delay) if retryable else None
        row.save(update_fields=[*OPENING_ERROR_FIELDS, 'updated_at'])
        return row
    _clear_opening_error(row)
    if status == 'active' and opening_ready(row):
        row.status = 'payment_pending' if row.payment_id else 'awaiting_payment'
    elif status in terminal and not payment_can_execute:
        row.status = 'failed'
    row.save(update_fields=['status', 'updated_at', *OPENING_ERROR_FIELDS])
    return row


def public_status(owner, country, asset):
    row = AccountActivation.objects.filter(confio_account=owner, country=country, asset=asset).first()
    return row.status if row else 'none'
