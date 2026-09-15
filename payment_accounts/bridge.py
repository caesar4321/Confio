"""Owner-bound durable NEXT quotes. Quoting never moves money."""
from datetime import timedelta
from decimal import Decimal
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .allbridge_next import NextClient, NextError, address, to_units, uint
from .eligibility import context_from_identity, enforce_and_record
from .models import FundingInstruction, MoneyFlow, PaymentBridgeQuote
from .services import PaymentAccountError, _require_provider_enabled


def bridge_cap():
    """Optional emergency brake on one bridge transfer, or None (the default).

    NEXT quotes every size at the same rate (2026-09-14: 0.998768 USDC per
    USDT from 10 to 100,000), so there is no size risk to cap. A configured
    value that is not a positive number still refuses every transfer.
    """
    raw = str(getattr(settings, 'PAYMENT_BRIDGE_MAX_USDT', '') or '').strip()
    return Decimal(raw) if raw else None


def exceeds_bridge_cap(amount):
    cap = bridge_cap()
    return cap is not None and (not cap.is_finite() or cap <= 0 or Decimal(str(amount)) > cap)


def executable_bridge_routes(routes):
    supported = [route for route in routes if route.get('messenger') == 'near-intents']
    if not supported:
        raise NextError('No executable bridge route is available')
    return supported


def bridge_route_minimum(route):
    return uint(route.get('amountOutMin', str(uint(route['amountOut'], positive=True) * 99 // 100)),
                positive=True)


def net_funding_units(owner, gross_units):
    """USDT bridge input within a total USD spend, using the cUSD perimeter.

    Existing wallet USDT has already crossed that perimeter. Only the cUSD
    portion needs a redemption fee, just as Koywe prices its net provider leg.
    """
    from . import bridge_chain as chain
    from cusd_plus import cusd_vault, vault
    wallet = max(0, chain.token_balance('BSC:USDT', owner.bsc_address)
                 - vault.reserved_usdt_wei(owner.user, owner.bsc_address))
    wallet_used = min(wallet, gross_units)
    redeem = gross_units - wallet_used
    if not redeem:
        return str(gross_units)
    cusd_vault.require_operational()
    preview = cusd_vault.preview_redeem_wei(redeem)
    if (not 0 <= preview.fee_bps <= 90 or preview.net_wei <= 0
            or preview.net_wei + preview.fee_wei != redeem or preview.fee_wei < 0):
        raise NextError('Invalid conversion fee preview')
    return str(wallet_used + preview.net_wei)


def verified_destination(instruction, confio_account):
    account = instruction.financial_account
    from .activation import require_usable
    require_usable(account)
    if account.provider_profile.confio_account_id != confio_account.pk:
        raise PaymentAccountError('Funding instruction does not belong to the active account')
    if account.provider not in {'cobre', 'infinia'}:
        raise PaymentAccountError('Unsupported bridge settlement provider')
    _require_provider_enabled(account.provider)
    if (account.status != 'active' or account.provider_profile.status != 'active'
            or instruction.status != 'active' or instruction.kind != 'crypto_address'
            or not instruction.reusable):
        raise PaymentAccountError('An active reusable crypto funding instruction is required')
    if instruction.expires_at and instruction.expires_at <= timezone.now():
        raise PaymentAccountError('Funding instruction has expired')
    # Operator-confirmed contract acceptance, bound to the exact instruction AND
    # address. Never infer chain from USDC symbol or treat webhook metadata as
    # permission to fund a provider from a bridge contract.
    verified = getattr(settings, 'PAYMENT_BRIDGE_VERIFIED_INSTRUCTIONS', {}).get(
        str(instruction.internal_id), {}
    )
    if not isinstance(verified, dict) or verified.get('token_id') != 'POL:USDC':
        raise PaymentAccountError('Polygon USDC bridge settlement is not verified for this instruction')
    destination = address(instruction.display_value)
    if address(verified.get('address')) != destination:
        raise PaymentAccountError('Provider funding address changed; settlement must be reverified')
    return destination


def quote_provider_funding(*, confio_account, funding_instruction_id, amount, request_id, client=None,
                           direction='to_provider'):
    if not getattr(settings, 'PAYMENT_BRIDGE_QUOTES_ENABLED', False):
        raise PaymentAccountError('Payment bridge quotes are not enabled')
    try:
        request_id = uuid.UUID(str(request_id))
        instruction_id = uuid.UUID(str(funding_instruction_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PaymentAccountError('Valid request and instruction UUIDs are required') from exc
    if direction not in {'to_provider', 'to_wallet'}:
        raise PaymentAccountError('Invalid bridge direction')
    source_token, destination_token = (
        ('BSC:USDT', 'POL:USDC') if direction == 'to_provider' else ('POL:USDC', 'BSC:USDT')
    )
    gross_units = to_units(amount, source_token)
    units = gross_units
    # An optional brake on the source leg, not a promise of an exact provider credit.
    if exceeds_bridge_cap(amount):
        raise PaymentAccountError('Amount exceeds the configured bridge limit')
    instruction = FundingInstruction.objects.select_related(
        'financial_account__provider_profile__identity_verification'
    ).filter(
        internal_id=instruction_id,
        financial_account__provider_profile__confio_account=confio_account,
    ).first()
    if not instruction:
        raise PaymentAccountError('Funding instruction not found')
    source = address(confio_account.bsc_address)
    if direction == 'to_provider':
        destination = verified_destination(instruction, confio_account)
    else:
        _require_provider_enabled(instruction.financial_account.provider)
        if (instruction.financial_account.provider not in {'infinia', 'cobre'}
                or instruction.financial_account.status != 'active'
                or instruction.financial_account.provider_profile.status != 'active'
                or instruction.status != 'active'):
            raise PaymentAccountError('Provider account is not active')
        destination = source

    def existing():
        row = PaymentBridgeQuote.objects.filter(
            confio_account=confio_account, request_id=request_id,
        ).first()
        if not row:
            return None
        # Compare the user's original amount, not a freshly priced net amount.
        # This also keeps pre-inclusive prepared transfers recoverable unchanged.
        original_units = row.money_flow.metadata.get('gross_spend_units', row.amount_units)
        if (row.funding_instruction_id, original_units, row.source_address, row.destination_address,
                row.source_token_id) != (
            instruction.pk, gross_units, source, destination, source_token,
        ):
            raise PaymentAccountError('Request id was already used for different bridge details')
        # A lost prepare response must recover the same transfer, whose
        # authorization lifetime is independent of the short pricing lifetime.
        from .models import PaymentBridgeTransfer
        if PaymentBridgeTransfer.objects.filter(quote=row).exists():
            return row
        if row.expires_at <= timezone.now():
            raise PaymentAccountError('Bridge quote expired; request a new quote with a new request id')
        return row

    identity = instruction.financial_account.provider_profile.identity_verification
    if not identity or identity.status != 'verified':
        raise PaymentAccountError('Verified identity required')
    enforce_and_record(
        confio_account=confio_account, provider=instruction.financial_account.provider,
        scope='conversion', context=context_from_identity(
            identity, account_country=instruction.financial_account.country,
        ),
    )
    previous = existing()
    if previous:
        return previous
    if direction == 'to_provider':
        units = net_funding_units(confio_account, int(gross_units))
    # Timestamp before pricing; API latency must not extend the quote's lifetime.
    started = timezone.now()
    expires = started + timedelta(seconds=60)
    if instruction.expires_at:
        expires = min(expires, instruction.expires_at)
    routes = executable_bridge_routes((client or NextClient()).quote(source_token, destination_token, units))
    if expires <= timezone.now():
        raise NextError('Bridge quote expired while pricing; try again')
    with transaction.atomic():
        # Serialize concurrent request IDs for this owner; HTTP is outside the
        # transaction. A retry cannot leave behind a duplicate MoneyFlow.
        locked_account = type(confio_account).objects.select_for_update().get(pk=confio_account.pk)
        if locked_account.deleted_at or address(locked_account.bsc_address) != source:
            raise PaymentAccountError('Active wallet changed while pricing; try again')
        previous = existing()
        if previous:
            return previous
        instruction.refresh_from_db()
        if direction == 'to_provider' and verified_destination(instruction, confio_account) != destination:
            raise PaymentAccountError('Funding instruction changed while pricing; try again')
        if instruction.expires_at:
            expires = min(expires, instruction.expires_at)
        if expires <= timezone.now():
            raise PaymentAccountError('Bridge quote expired while saving; try again')
        flow = MoneyFlow.objects.create(
            confio_account=confio_account, kind='withdraw' if direction == 'to_provider' else 'fund', status='created',
            source_asset='USDT_BSC' if direction == 'to_provider' else 'USDC_POL', source_amount=Decimal(str(amount)),
            target_asset='USDC_POL' if direction == 'to_provider' else 'USDT_BSC',
            metadata={'purpose': 'provider_bridge_funding', 'stage': 'quoted',
                      **({'gross_spend_units': gross_units} if direction == 'to_provider' else {})},
        )
        return PaymentBridgeQuote.objects.create(
            confio_account=confio_account, request_id=request_id, money_flow=flow,
            funding_instruction=instruction, source_address=source,
            destination_address=destination, amount_units=units,
            source_token_id=source_token, destination_token_id=destination_token,
            routes=routes, expires_at=expires,
        )
