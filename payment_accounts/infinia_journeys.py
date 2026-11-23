"""Durable Infinia conversion/payout orchestration using authenticated ledger facts."""
import uuid
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal, ROUND_DOWN

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .allbridge_next import address
from .clients import InfiniaClient
from .eligibility import context_from_identity, enforce_and_record
from .models import InfiniaJourney, MoneyFlow, MoneyOperation, LedgerEntry
from .services import (PaymentAccountError, _require_provider_enabled,
                       _require_capability, submit_money_operation,
                       require_unreserved_source, require_outgoing_face,
                       face_amount)
from .infinia_bridge import SETTLED_BRIDGE_FAILURES, live_journeys


class JourneyBusy(PaymentAccountError):
    """The owner's accounts are held by another payment for now."""


def contract_funded(j):
    return bool(j.direction == 'to_bank' and j.bridge_id and j.bridge.funding_mode == 'contract')


def enabled():
    if not getattr(settings, 'INFINIA_JOURNEYS_ENABLED', False):
        raise PaymentAccountError('Infinia payment journeys are not enabled')
    _require_provider_enabled('infinia')


def positive(value):
    value = Decimal(str(value))
    if not value.is_finite() or value <= 0 or value >= Decimal('1e9') or value != value.quantize(Decimal('1e-18')):
        raise PaymentAccountError('Invalid journey amount')
    return value


def provider_number(value):
    value = positive(value)
    result = float(value)
    if Decimal(str(result)) != value:
        raise PaymentAccountError('Amount exceeds provider numeric precision')
    return result


FX_SOURCE_QUANTUM = Decimal('0.01')


def fx_source_amount(value):
    """Infinia FX sources accept cents, including USDC. Never round up funds."""
    amount = positive(value).quantize(FX_SOURCE_QUANTUM, rounding=ROUND_DOWN)
    if amount <= 0:
        raise PaymentAccountError('El monto disponible para convertir debe ser al menos 0.01.')
    return amount


def validate_accounts(owner, local, crypto, destination_country):
    if owner.deleted_at:
        raise PaymentAccountError('Account is unavailable')
    from .activation import require_usable
    for account in (local, crypto):
        require_usable(account)
        profile = account.provider_profile
        if (profile.confio_account_id != owner.pk or profile.provider != 'infinia'
                or profile.status != 'active' or account.status != 'active'):
            raise PaymentAccountError('An active owned Infinia account is required')
    if local.pk == crypto.pk or crypto.asset != 'USDC_POL' or local.country == 'XXX':
        raise PaymentAccountError('A local fiat account and native Polygon USDC account are required')
    identity = crypto.provider_profile.identity_verification
    if not identity or identity.status != 'verified':
        raise PaymentAccountError('Verified identity required')
    for scope in ('conversion', 'payout'):
        enforce_and_record(confio_account=owner, provider='infinia', scope=scope,
            context=context_from_identity(identity, account_country=local.country, destination_country=destination_country))


@transaction.atomic
def create_journey(*, owner, local_account, crypto_account, request_id, minimum_fx_output,
                   direction, bridge=None, credit=None, destination=None, minimum_wallet_output=None,
                   funding=None):
    """`funding` is a contract_funding.ContractFunding, built server-side from
    a rule run; no GraphQL argument reaches it. With it the bridge is funded
    by the account contract and the standing authorization replaces this
    journey's Face grant. A contract-funded bridge accepts nothing else."""
    enabled()
    request_id = uuid.UUID(str(request_id))
    minimum = positive(minimum_fx_output)
    wallet_minimum = positive(minimum_wallet_output) if minimum_wallet_output is not None else None
    owner = type(owner).objects.select_for_update().get(pk=owner.pk)
    from .models import FinancialAccount
    list(FinancialAccount.objects.select_for_update().filter(pk__in=[local_account.pk, crypto_account.pk]).order_by('pk'))
    if direction not in {'to_bank', 'to_wallet'}:
        raise PaymentAccountError('Invalid journey direction')
    wallet = address(owner.bsc_address)
    snapshot = {'destination_account': {'type': 'POLYGON', 'address': wallet}, 'country': 'XXX'}
    if direction == 'to_bank':
        if (not destination or destination.confio_account_id != owner.pk or destination.provider != 'infinia'
                or destination.asset != local_account.asset or destination.country != local_account.country
                or destination.kind == 'crypto_wallet' or destination.status not in {'pending', 'active'}):
            raise PaymentAccountError('An owned matching local payout destination is required')
        snapshot = {'destination_account': destination.details, 'country': destination.country,
                    'destination_internal_id': str(destination.internal_id),
                    'display_label': f'{destination.label} · {destination.holder_name}'}
        from .local_money import charge_snapshot
        charge = charge_snapshot(destination)
        if charge is not None:
            snapshot['pix_charge'] = charge
        if (not bridge or bridge.quote.confio_account_id != owner.pk
                or bridge.quote.source_token_id != 'BSC:USDT'
                or bridge.quote.funding_instruction.financial_account_id != crypto_account.pk):
            raise PaymentAccountError('An owned bridge to this crypto account is required')
        if credit:
            raise PaymentAccountError('Outbound credit is resolved from bridge evidence')
        from .contract_funding import MODE, OWNER_REFUSAL, authorize_journey
        authority = None
        if funding is not None or bridge.funding_mode == MODE:
            if funding is None or charge is not None:
                raise PaymentAccountError(OWNER_REFUSAL)
            authority = authorize_journey(funding, owner=owner, destination=destination, bridge=bridge,
                                          local_account=local_account)
            # Where a refund returns: the account contract, not the wallet.
            wallet = bridge.quote.source_address
    else:
        authority = None
        if funding is not None:
            raise PaymentAccountError('Invalid journey funding')
        if (bridge or not credit or credit.financial_account_id != local_account.pk or credit.provider != 'infinia'
                or credit.direction != 'credit' or credit.asset != local_account.asset or positive(credit.amount) <= 0
                or (credit.provider_data.get('operation') or {}).get('type') not in {None, 'PAYIN', 'CREDIT'}):
            raise PaymentAccountError('An unspent local deposit credit is required')
        from .payin_admission import require_admitted
        require_admitted(credit)
        # Held pay-ins (Confío Face) and pay-ins being returned convert by no path.
        from .payin_hold import require_conversion_allowed
        require_conversion_allowed(owner, credit)
    if direction == 'to_bank':
        # Refused before it starts; a deposit already received still converts
        # to the person's balance (to_wallet), so nothing is left behind.
        from .local_money import require_region
        require_region(owner)
    validate_accounts(owner, local_account, crypto_account, snapshot['country'])
    source, target = (crypto_account, local_account) if direction == 'to_bank' else (local_account, crypto_account)
    _require_capability(source, 'convert')
    _require_capability(target, 'send_third_party')
    existing = InfiniaJourney.objects.filter(confio_account=owner, request_id=request_id).first()
    expected = (direction, local_account.pk, crypto_account.pk, minimum, snapshot, wallet, wallet_minimum)
    if existing:
        actual = (existing.direction, existing.local_account_id, existing.crypto_account_id,
                  existing.minimum_fx_output, existing.destination_snapshot, existing.wallet_address, existing.minimum_wallet_output)
        if actual != expected or (direction == 'to_bank' and existing.bridge_id != bridge.pk) or (
                direction == 'to_wallet' and existing.funding_credit_id != credit.pk):
            raise PaymentAccountError('Request id already used for different journey details')
        return existing
    if direction == 'to_bank' and snapshot.get('pix_charge'):
        # Serialize every account paying this charge (personal, business,
        # someone else's) for the rest of this transaction: two confirmations
        # at once must not both pass the paid-once check.
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [snapshot['pix_charge']['key']])
        from .local_money import require_payable_charge
        payable = require_payable_charge(owner, destination, exclude_request_id=request_id)
        if minimum != payable['amount'] or Decimal(snapshot['pix_charge']['amount']) != payable['amount']:
            raise PaymentAccountError('El monto autorizado no coincide con el cobro. Revisa el pago de nuevo.')
    from .infinia_fee_policy import enabled as fee_enabled, freeze as freeze_fee
    fee = None
    if direction == 'to_bank':
        fee = bridge.quote.money_flow.metadata.get('infinia_fee')
        from .infinia_legacy_fees import predates_rollout
        # A contract-funded run collects nothing in a batch: its fee is the
        # carry-forward debt recorded when it is paid (contract_funding).
        if authority is None and (
                fee or (fee_enabled(local_account.country) and not predates_rollout(bridge.quote))):
            if (not fee or fee['local_account_id'] != str(local_account.internal_id)
                    or bridge.quote.money_flow.metadata.get('local_destination_id') != str(destination.internal_id)):
                raise PaymentAccountError('Solicita una nueva cotización para incluir los costos del envío.')
    else:
        fee = freeze_fee(local_account, direction)
        if fee:
            from cusd_plus import cusd_vault
            if wallet_minimum is None:
                raise PaymentAccountError('A minimum wallet receipt is required')
            preview = cusd_vault.preview_mint_wei(int(wallet_minimum * 10**18))
            minimum_net = max(0, preview.net_wei - int(fee['units']))
            if not 0 <= preview.fee_bps <= 90 or preview.net_wei <= 0:
                raise PaymentAccountError('El monto no alcanza para cubrir los costos de conversión.')
            fee = dict(fee, minimum_net_units=str(minimum_net), cap_on_arrival=True)
    if direction == 'to_wallet' and wallet_minimum is None:
        raise PaymentAccountError('A minimum BSC USDT receipt is required')
    if direction == 'to_bank' and wallet_minimum is not None:
        raise PaymentAccountError('A wallet minimum applies only to inbound payments')
    if MoneyOperation.objects.filter(provider='infinia', source_account__in=[local_account, crypto_account],
            status__in=['created', 'submitted', 'processing', 'settling', 'unknown']).exclude(
                money_flow__infinia_journey__stage='completed').exists():
        raise JourneyBusy('An existing provider operation is still pending')
    # One provider journey per owner while unsettled, to avoid concurrent
    # conversion/payout balance races. Only journeys the worker will still
    # advance can race: a needs_review row nothing will ever touch again must
    # not deny the owner every future payment (production lockout 2026-09-15).
    if live_journeys(InfiniaJourney.objects.filter(confio_account=owner)).exists():
        raise JourneyBusy('Ya tienes un pago local en curso.')
    if credit and InfiniaJourney.objects.filter(funding_credit=credit).exists():
        raise PaymentAccountError('Deposit already used by a journey')
    face_action_key = ''
    if direction == 'to_bank' and authority is None:
        quote = bridge.quote
        face_action_key = require_outgoing_face(
            owner,
            'payment_accounts.infinia_journey',
            request_id,
            {
                'confio_account_id': str(owner.pk),
                'user_id': str(owner.user_id),
                'provider': 'infinia',
                'direction': direction,
                'local_account_id': str(local_account.internal_id),
                'crypto_account_id': str(crypto_account.internal_id),
                'minimum_fx_output': face_amount(minimum),
                'minimum_wallet_output': None,
                'destination': snapshot,
                'wallet_address': wallet,
                'bridge': {
                    'id': str(bridge.internal_id),
                    'quote_id': str(quote.internal_id),
                    'source_token_id': quote.source_token_id,
                    'destination_token_id': quote.destination_token_id,
                    'amount_units': quote.amount_units,
                    'source_amount': face_amount(quote.money_flow.source_amount),
                    'source_address': quote.source_address,
                    'destination_address': quote.destination_address,
                },
                'fee': fee,
            },
        )
    flow = MoneyFlow.objects.create(confio_account=owner, kind='withdraw' if direction == 'to_bank' else 'fund',
        source_asset='USDT_BSC' if direction == 'to_bank' else local_account.asset,
        source_amount=bridge.quote.money_flow.source_amount if bridge else credit.amount,
        target_asset=local_account.asset if direction == 'to_bank' else 'USDT_BSC',
        metadata={'orchestrator': 'infinia', 'minimum_fx_output': str(minimum),
                  **({'infinia_fee': fee} if fee else {}),
                  **({'contract_funding': authority} if authority else {}),
                  **({'face_action_key': face_action_key} if face_action_key else {})})
    if direction == 'to_wallet':
        from .infinia_maintenance import reserve
        reserve(fee, flow)
    return InfiniaJourney.objects.create(money_flow=flow, confio_account=owner, request_id=request_id,
        direction=direction, local_account=local_account, crypto_account=crypto_account,
        bridge=bridge, funding_credit=credit, minimum_fx_output=minimum,
        destination_snapshot=snapshot, wallet_address=wallet, minimum_wallet_output=wallet_minimum)


def _state(j, stage, *, failure=''):
    j.stage, j.failure_code = stage, failure
    j.save(update_fields=['stage', 'failure_code', 'updated_at'])
    flow = j.money_flow
    flow.status = {'completed': 'succeeded', 'failed': 'failed', 'needs_review': 'needs_review'}.get(stage, 'processing')
    flow.metadata = dict(flow.metadata, stage=stage)
    unwind = (flow.metadata or {}).get('pix_charge_unwind') or {}
    if stage == 'needs_review' and unwind.get('state') == 'active':
        # A parked unwind is a human's now: never live (and blocking) forever,
        # and no leg it never sent keeps reserving the person's accounts.
        flow.metadata = dict(flow.metadata, pix_charge_unwind=dict(unwind, state='stopped', stopped_for=failure))
        for leg in (_unwind_operation(j), _return_operation(j)):
            if leg is not None:
                _close_never_submitted(leg)
    if stage in {'completed', 'failed'}:
        flow.completed_at = timezone.now()
    flow.save(update_fields=['status', 'metadata', 'completed_at', 'updated_at'])


def _credit_for_operation(operation, account, *, voucher_entry=None, why=None):
    """The proven proceeds, or 0. A caller passing `why` (a dict) learns when
    a 0 will never resolve by waiting: why['reason'] is then set."""
    # COMPLETED means sent. Require actual destination movement(s), related by
    # the provider operation ID, not by amount. Refunds/fees are not proceeds.
    if not operation.provider_operation_id:
        return Decimal(0)
    entries = LedgerEntry.objects.filter(financial_account=account, provider='infinia',
        direction='credit', asset=account.asset, amount__gt=0,
        provider_data__operation__operation_id=operation.provider_operation_id)
    accepted = [e for e in entries if (e.provider_data.get('operation') or {}).get('type') in {'INTERNAL_TRANSFER', 'CREDIT'}]
    if accepted and voucher_entry is None:
        return sum((e.amount for e in accepted), Decimal(0))
    # Some legs arrive without operation_id. Infinia's completed transfer
    # supplies voucher_ids: bank vouchers, or Polygon transaction hashes.
    # Never infer this relationship from amounts/descriptions or mutate the
    # original webhook evidence to manufacture an operation_id.
    data = operation.provider_data or {}
    vouchers = data.get('voucher_ids')
    if (operation.operation_type not in {'conversion', 'internal_transfer'}
            or operation.status not in {'settling', 'succeeded'}
            or data.get('status') != 'COMPLETED' or data.get('compliance_hold') is not False
            or str(data.get('id')) != operation.provider_operation_id
            or str(data.get('idempotency_key')) != operation.idempotency_key
            or not operation.source_account_id or operation.destination_account_id != account.pk
            or str(data.get('source_account_id')) != operation.source_account.provider_account_id
            or str(data.get('target_account_id')) != account.provider_account_id
            or not isinstance(vouchers, list) or not vouchers
            or any(not isinstance(v, str) or not v.strip() for v in vouchers)
            or len(set(vouchers)) != len(vouchers)):
        return Decimal(0)
    try:
        if positive(data.get('source_amount')) != operation.source_amount:
            return Decimal(0)
        expected = positive(data.get('destination_amount'))
    except (ValueError, TypeError, ArithmeticError, PaymentAccountError):
        return Decimal(0)
    from django.db.models import Q
    from .providers.common import same_country
    import re
    polygon = account.asset == 'USDC_POL' and same_country(account.country, 'XX')
    narrowed = False
    if polygon:
        # A COP→USDC conversion can list the Polygon transaction hash next to
        # the provider's own leg references (e.g. 'mm_…' and a UUID, journey
        # 25, 11-15). Only the hashes are credits to this account; each must
        # still match exactly one credit and the total must equal the amount.
        hashes = [v for v in vouchers if re.fullmatch(r'0x[0-9a-fA-F]{64}', v)]
        if hashes and len(hashes) != len(vouchers):
            vouchers, narrowed = hashes, True
    # Nothing marks a voucher credit as spent, so a voucher another of our
    # conversions also lists proves neither: count it for none.
    if voucher_claimed_elsewhere(operation, account, vouchers):
        # On Polygon, provider references alone (no hash yet) are not credit
        # vouchers and may be shared across conversions: wait, don't review.
        if why is not None and not (polygon and not hashes):
            why['reason'] = 'conversion_voucher_claimed'
        return Decimal(0)
    matching = Q(provider_data__third_party__voucher_id__in=vouchers)
    if polygon:
        matching |= Q(provider_data__third_party__transaction_hash__in=vouchers)
    candidates = list(LedgerEntry.objects.filter(matching, financial_account=account, provider='infinia',
        direction='credit', asset=account.asset, amount__gt=0,
        ).select_related('operation'))
    def voucher_for(entry):
        sender = entry.provider_data.get('third_party') or {}
        voucher, tx_hash = sender.get('voucher_id'), sender.get('transaction_hash')
        if polygon and tx_hash:
            if (sender.get('type') != 'CRYPTO' or sender.get('crypto_network') != 'POLYGON'
                    or not isinstance(tx_hash, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', tx_hash)
                    or (voucher and voucher != tx_hash)):
                return None
            return tx_hash
        return voucher
    if (len(candidates) != len(vouchers)
            or (voucher_entry is not None and voucher_entry.pk not in {e.pk for e in candidates})
            or {voucher_for(e) for e in candidates} != set(vouchers)
            or any(e.provider_data.get('operation') for e in candidates)
            or any(e.operation_id and e.operation_id != operation.pk
                   and e.operation.operation_type not in {'deposit', 'payin'} for e in candidates)):
        return Decimal(0)
    total = sum((e.amount for e in candidates), Decimal(0))
    if total == expected:
        return total
    if narrowed and why is not None and _provider_quiet(data, hours=1):
        # Every hash arrived and bound cleanly, yet they don't add up, and the
        # provider has not touched the transfer for an hour (a later leg would
        # add its hash and update it): the rest came under a reference we set
        # aside, and waiting will not resolve it.
        why['reason'] = 'conversion_credit_mismatch'
    return Decimal(0)


def _provider_quiet(data, *, hours):
    """The provider's own last update is older than `hours` (unknown = not quiet)."""
    from datetime import timedelta
    try:
        stamp = parse_datetime(str(data.get('updated_at') or ''))
    except ValueError:
        return False
    if stamp is None:
        return False
    if timezone.is_naive(stamp):
        stamp = stamp.replace(tzinfo=dt_timezone.utc)
    return timezone.now() - stamp > timedelta(hours=hours)


def voucher_claimed_elsewhere(operation, account, vouchers):
    """Another of our conversions into this account lists one of these vouchers."""
    others = MoneyOperation.objects.filter(provider='infinia', destination_account=account,
        operation_type__in=['conversion', 'internal_transfer']).exclude(pk=operation.pk)
    return any(others.filter(provider_data__voucher_ids__contains=[v]).exists() for v in vouchers)


def has_refund(operation):
    if not operation.provider_operation_id:
        return False
    kind = 'PAYOUT_REFUND' if operation.operation_type == 'payout' else 'INTERNAL_TRANSFER_REFUND'
    return LedgerEntry.objects.filter(provider='infinia', financial_account=operation.source_account,
        direction='credit', amount__gt=0, provider_data__operation__type=kind,
        provider_data__operation__operation_id=operation.provider_operation_id).exists()


def _authorized_fx_quote(j, source, target, amount, client=None):
    """A fresh provider quote, or None when it falls outside the authorization.

    Always the provider's default expiry; explicit durations require separate
    LONGER_QUOTE_TIME terms. Quotes don't move money, so obtaining another after
    a crash cannot cause a second debit. The returned expiry is validated here.
    """
    quote = (client or InfiniaClient()).create_transfer_quote({
        'external_id': str(j.internal_id), 'source_account_id': source.provider_account_id,
        'target_account_id': target.provider_account_id, 'source_amount': provider_number(amount)})
    try:
        expires = parse_datetime(str(quote.get('expire_at', '')))
        if expires and timezone.is_naive(expires):
            expires = expires.replace(tzinfo=dt_timezone.utc)
        valid = (quote.get('id') and quote.get('status') == 'ACTIVE' and expires
            and expires > timezone.now() and str(quote.get('source_account_id')) == source.provider_account_id
            and str(quote.get('target_account_id')) == target.provider_account_id
            and positive(quote.get('source_amount')) == amount
            and positive(quote.get('target_amount')) >= j.minimum_fx_output)
        if valid and contract_funded(j):
            # An amount floor lets a fuller delivery hide a lower rate.
            from .contract_funding import rate_allowed, rate_passed
            valid = rate_allowed(j, amount, positive(quote.get('target_amount')))
            if valid:
                rate_passed(j)
    except (AttributeError, TypeError, ValueError, ArithmeticError, PaymentAccountError):
        valid = False
    return quote if valid else None


# A provider that rejects a submission before creating anything has not moved
# money, so the leg is re-quotable rather than a case for a human. Bounded so an
# endlessly expiring quote cannot spin.
FX_REQUOTE_LIMIT = 3


def expired_fx_rejection(op, quote_id):
    """Only an explicit rejection of this exact expired quote can be retried.

    Absence of an operation ID (or a refund) is not proof of non-execution.
    A fresh provider lookup is additionally required before changing terms.
    """
    data = op.provider_data if op and isinstance(op.provider_data, dict) else {}
    return bool(op and quote_id and op.operation_type == 'conversion'
        and op.status == 'failed' and not op.provider_operation_id
        and op.failure_code in {'400', '409'} and data.get('status') == 'fail'
        and data.get('message') == f'Quote: {quote_id} is expired')


def _explicitly_empty_lookup(payload):
    if isinstance(payload, list):
        return payload == []
    # Accept only an unambiguous paginated empty collection, not arbitrary
    # error objects containing an empty data/results field.
    return (isinstance(payload, dict)
        and set(payload).issubset({'results', 'count', 'next', 'previous'})
        and payload.get('results') == [] and type(payload.get('count')) is int
        and payload['count'] == 0 and not payload.get('next'))


def stale_unsubmitted_quote(j):
    op = j.fx_operation
    if not (op and op.status == 'created' and op.submitted_at is None
            and not op.provider_operation_id and op.operation_type == 'conversion'):
        return False
    try:
        expires = parse_datetime(str(j.fx_quote.get('expire_at', '')))
        if expires and timezone.is_naive(expires):
            expires = timezone.make_aware(expires, dt_timezone.utc)
        return expires is None or expires <= timezone.now()
    except (TypeError, ValueError):
        return True


def _requotable(j):
    """A journey parked for review solely because its conversion never ran."""
    return (j.failure_code == 'provider_leg_requires_review'
            and not j.payout_operation_id
            and expired_fx_rejection(j.fx_operation, j.fx_quote.get('id')))


def _new_operation(j, leg, source, target, amount):
    return MoneyOperation.objects.create(money_flow=j.money_flow, provider='infinia',
        operation_type='conversion' if leg == 'fx' else 'payout', source_account=source,
        destination_account=target, source_asset=source.asset, source_amount=amount,
        target_asset=target.asset if target else source.asset,
        idempotency_key=str(uuid.uuid5(j.internal_id, leg)),
        external_destination={} if leg == 'fx' else j.destination_snapshot,
        provider_data={'quote_id': j.fx_quote['id']} if leg == 'fx' else {})


# ------------------------------------------------------------- Pix charges
# A to-bank journey whose destination snapshot carries `pix_charge` pays a
# merchant's Pix code at its exact amount: the conversion names the reais to
# land (target_amount), the payout is that amount, and any dollars the
# conversion does not use go back to the person's own wallet (return leg).
RETURN_LEG = 'return'
USDC_QUANTUM = Decimal('0.000001')


def _charge(j):
    return (j.destination_snapshot or {}).get('pix_charge') if j.direction == 'to_bank' else None


def _return_operation(j):
    return MoneyOperation.objects.filter(money_flow=j.money_flow, provider='infinia', operation_type='payout',
        idempotency_key=str(uuid.uuid5(j.internal_id, RETURN_LEG))).first()


def _start_return(j, amount, stage, reason, *, cap=None):
    """Pay dollars of this journey back to the wallet pinned at authorization:
    the whole funding when the charge can no longer be paid, what the
    conversion did not use, or everything an unwind brought back. Never
    anywhere else, never more than this journey holds (`cap`: what arrived,
    or for an unwind what arrived less the conversion plus its reversal)."""
    amount = Decimal(amount).quantize(USDC_QUANTUM, rounding=ROUND_DOWN)
    arrived = positive(j.funding_credit.amount) if cap is None else Decimal(cap)
    if amount <= 0 or amount > arrived:
        _state(j, 'needs_review', failure='pix_charge_return_amount_invalid')
        return None
    operation = MoneyOperation.objects.create(money_flow=j.money_flow, provider='infinia',
        operation_type='payout', source_account=j.crypto_account, destination_account=None,
        source_asset=j.crypto_account.asset, source_amount=amount, target_asset=j.crypto_account.asset,
        idempotency_key=str(uuid.uuid5(j.internal_id, RETURN_LEG)),
        external_destination={'destination_account': {'type': 'POLYGON', 'address': j.wallet_address},
                              'country': 'XXX'})
    j.money_flow.metadata = dict(j.money_flow.metadata, pix_charge_return={
        'amount': str(amount), 'asset': j.crypto_account.asset, 'reason': reason,
        'operation_id': str(operation.internal_id)})
    j.money_flow.save(update_fields=['metadata', 'updated_at'])
    _state(j, stage, failure=reason if stage == 'refunding' else '')
    return operation


def _finish_return(j):
    # By reason, not by stage: a failed leg elsewhere in the flow can have
    # flipped the stage to needs_review (services._sync_flow_status) meanwhile.
    reason = ((j.money_flow.metadata or {}).get('pix_charge_return') or {}).get('reason', '')
    if (j.money_flow.metadata or {}).get('pix_charge_unwind'):
        _unwind_mark(j, 'done')
    if reason == 'pix_charge_remainder':
        _state(j, 'completed')
    else:
        _state(j, 'failed', failure=reason or 'pix_charge_refunded')


# --------------------------------------------------------------- unwind
# A charge whose payout failed cleanly (or that expired after conversion) is
# not left for a human: the reais converted for it go back to dollars at the
# current rate and everything this journey holds returns to the person's
# pinned wallet. State lives in money_flow.metadata.pix_charge_unwind, because
# a failed leg flips the stage to needs_review (services._sync_flow_status):
#   active          the worker keeps advancing it (live_journeys)
#   done/stopped    finished, or parked for a human
#   not_applicable  checked once and not unwindable: never live again
UNWIND_LEG = 'unwind'
UNWIND_TRIGGERS = frozenset({'payout_failed', 'provider_leg_requires_review', 'pix_charge_expired_after_conversion'})


def _unwind_operation(j):
    return MoneyOperation.objects.filter(money_flow=j.money_flow, provider='infinia',
        operation_type='conversion', idempotency_key=str(uuid.uuid5(j.internal_id, UNWIND_LEG))).first()


def _unwind_mark(j, state, **extra):
    meta = j.money_flow.metadata or {}
    j.money_flow.metadata = dict(meta, pix_charge_unwind=dict(meta.get('pix_charge_unwind') or {},
                                                              state=state, **extra))
    j.money_flow.save(update_fields=['metadata', 'updated_at'])
    if state == 'stopped':
        # Whatever stops it, no leg it never sent keeps reserving accounts.
        for leg in (_unwind_operation(j), _return_operation(j)):
            if leg is not None:
                _close_never_submitted(leg)


# Refusals that are final: the provider's own FAILED status (no HTTP code), or
# a request it rejected as invalid. Anything else (auth, rate limits, not
# found, an unknown code) may still be payable: a human decides.
DEFINITIVE_REJECTIONS = frozenset({'', '400', '422'})


def _payout_cleanly_failed(j):
    """The payout was refused for good, with no money leaving the account. A
    rate limit or timeout is not a refusal: that charge may still be payable."""
    op = j.payout_operation
    if op is None or op.status != 'failed' or has_refund(op):
        return False
    if str(op.failure_code or '') not in DEFINITIVE_REJECTIONS:
        return False
    if op.provider_operation_id and LedgerEntry.objects.filter(
            financial_account=j.local_account, provider='infinia', direction='debit',
            provider_data__operation__operation_id=op.provider_operation_id).exists():
        return False
    return True


BAD_LEG = frozenset({'failed', 'reversed', 'needs_review'})


def _unwind_legs_clear(j):
    """The conversion and the unwind (if any) are not failed, reversed,
    disputed or refunded: only then may an unwind move money again."""
    for op in (j.fx_operation, _unwind_operation(j)):
        if op is not None and (op.status in BAD_LEG or has_refund(op)):
            return False
    # The payout that started it must still be a clean refusal.
    return not j.payout_operation_id or _payout_cleanly_failed(j)


def _close_never_submitted(operation):
    """A leg parked without ever reaching the provider stops reserving its
    account (create_journey, require_unreserved_source): it never existed there."""
    from django.db.models import Q
    MoneyOperation.objects.filter(pk=operation.pk, status='created', submitted_at__isnull=True).filter(
        Q(provider_operation_id__isnull=True) | Q(provider_operation_id='')).update(
        status='failed', failure_code='never_submitted', updated_at=timezone.now())


def _leg_stuck(operation):
    hours = int(getattr(settings, 'LOCAL_MONEY_PIX_UNWIND_MAX_HOURS', 6))
    return operation.created_at < timezone.now() - timedelta(hours=hours)


def unwind_candidates(queryset):
    """Parked charge journeys not yet checked for an unwind. The worker visits
    them; they are NOT live: they hold no operation in flight, so they never
    reserve an account or block the owner's next payment (live_journeys)."""
    from django.db.models import Q
    return queryset.filter(
        stage='needs_review', direction='to_bank', destination_snapshot__has_key='pix_charge',
        failure_code__in=sorted(UNWIND_TRIGGERS), fx_operation__isnull=False,
    ).exclude(money_flow__metadata__has_key='pix_charge_unwind')


def _unwind_started(j):
    return ((j.money_flow.metadata or {}).get('pix_charge_unwind') or {}).get('state') == 'active'


def prefetch_payout_lookup(journey_id, client=None):
    """Ask the provider about a failed charge payout before deciding to
    unwind, with no lock held: 'clean' (never created, or the provider's own
    failed record), 'live' (it exists and did not fail: never unwind) or None
    (no answer: wait). A local 'failed' without an id is not proof."""
    row = InfiniaJourney.objects.filter(pk=journey_id).values(
        'stage', 'failure_code', 'destination_snapshot', 'payout_operation__status',
        'payout_operation__idempotency_key', 'money_flow__metadata').first()
    if (not row or row['stage'] != 'needs_review' or row['failure_code'] not in UNWIND_TRIGGERS
            or not (row['destination_snapshot'] or {}).get('pix_charge')
            or row['payout_operation__status'] != 'failed'
            or (row['money_flow__metadata'] or {}).get('pix_charge_unwind')):
        return None
    try:
        rows = (client or InfiniaClient()).find_operation('payout', row['payout_operation__idempotency_key'])
    except Exception:
        return None
    if _explicitly_empty_lookup(rows):
        return 'clean'
    statuses = {str((r or {}).get('status') or '').upper() for r in rows} if isinstance(rows, list) else {'?'}
    return 'clean' if statuses and statuses <= {'FAILED', 'ERROR', 'REJECTED'} else 'live'


def _unwindable(j):
    """True: a parked charge journey whose reais can go back (conversion
    proceeds credited and exactly the charge, payout never made, nothing
    refunded, and the provider confirms it). False: never. None: not known
    yet (the provider did not answer): ask again next pass."""
    if not _charge(j) or not j.fx_operation_id or j.stage != 'needs_review':
        return False
    if (j.money_flow.metadata or {}).get('pix_charge_unwind') or j.failure_code not in UNWIND_TRIGGERS:
        return False
    if _return_operation(j) is not None or has_refund(j.fx_operation) or j.fx_operation.status in BAD_LEG:
        return False
    if j.fx_operation.status not in {'succeeded', 'settling'}:
        return None  # the conversion's own status has not landed yet: wait (bounded)
    if j.payout_operation_id:
        if not _payout_cleanly_failed(j):
            return False
        lookup = getattr(j, '_payout_lookup', None)
        if lookup is None:
            return None
        if lookup != 'clean':
            return False
    elif j.failure_code != 'pix_charge_expired_after_conversion':
        return False
    return _credit_for_operation(j.fx_operation, j.local_account) == positive(_charge(j)['amount'])


def _advance_unwind(j):
    """The next operation of an unwind, or None (waiting, or parked)."""
    unwind = _unwind_operation(j)
    if unwind is None:
        reais = positive(_charge(j)['amount'])
        reason = 'pix_charge_payout_failed' if j.payout_operation_id else 'pix_charge_expired'
        unwind = MoneyOperation.objects.create(money_flow=j.money_flow, provider='infinia',
            operation_type='conversion', source_account=j.local_account, destination_account=j.crypto_account,
            source_asset=j.local_account.asset, source_amount=reais, target_asset=j.crypto_account.asset,
            idempotency_key=str(uuid.uuid5(j.internal_id, UNWIND_LEG)), external_destination={},
            provider_data={})
        _unwind_mark(j, 'active', reason=reason, operation_id=str(unwind.internal_id), reais=str(reais),
                     payout_pk=j.payout_operation_id)
        _state(j, 'unwinding', failure=reason)
        return unwind
    if has_refund(unwind) or unwind.status in {'failed', 'reversed', 'needs_review'}:
        _unwind_mark(j, 'stopped')
        _state(j, 'needs_review', failure='pix_charge_unwind_' + ('refunded' if has_refund(unwind) else unwind.status))
        return None
    if unwind.status == 'created':
        if _leg_stuck(unwind):
            _close_never_submitted(unwind)
            _state(j, 'needs_review', failure='pix_charge_unwind_stuck')
            return None
        if j.stage != 'unwinding':
            _state(j, 'unwinding', failure=j.failure_code)
        return unwind
    why = {}
    proceeds = _credit_for_operation(unwind, j.crypto_account, why=why)
    if not proceeds:
        if why.get('reason'):
            _unwind_mark(j, 'stopped')
            _state(j, 'needs_review', failure=why['reason'])
        elif j.stage != 'unwinding':
            _state(j, 'unwinding', failure=j.failure_code)
        return None
    if j.payout_operation_id and not _payout_cleanly_failed(j):
        # The payout's record changed after the unwind began (a debit, a
        # refund, a status): never send the reais' dollars on top of it.
        _state(j, 'needs_review', failure='pix_charge_unwind_payout_changed')
        return None
    # Everything this journey holds in dollars: the buffer the conversion did
    # not use plus what the reversal brought back.
    holds = positive(j.funding_credit.amount) - j.fx_operation.source_amount + proceeds
    reason = ((j.money_flow.metadata or {}).get('pix_charge_unwind') or {}).get('reason') or 'pix_charge_payout_failed'
    return _start_return(j, holds, 'refunding', reason, cap=holds)


def _charge_still_payable(j, charge, client=None):
    """True; None while the network's answer is not known yet; or why the
    charge can no longer be paid (then the funding goes back to the person).

    Asked again after the dollars arrive and before any conversion: the
    charge may have been paid elsewhere, cancelled, changed or be about to
    expire while the bridge ran.
    """
    from . import local_money
    left = local_money._seconds_left(local_money._aware(charge.get('expires_at')))
    if left is not None and left < int(getattr(settings, 'LOCAL_MONEY_PIX_SETTLE_SECONDS', 180)):
        return 'pix_charge_expiring'
    from .models import PayoutDestination
    destination = PayoutDestination.objects.filter(
        confio_account=j.confio_account, internal_id=j.destination_snapshot.get('destination_internal_id')).first()
    value = (destination.details or {}).get('brCode', '') if destination else ''
    if not value or value != (j.destination_snapshot.get('destination_account') or {}).get('brCode'):
        return 'pix_charge_destination_changed'
    answer = _charge_recheck(j, value, client)
    status = answer.get('status')
    if status == 'ERROR' and answer.get('gone'):
        # The Pix network says it is gone (paid, removed, 404/410).
        return 'pix_charge_unpayable'
    if status != 'SUCCESSFUL':
        # Temporary failure or still running: ask again on the next pass,
        # but not forever for a charge with no expiry of its own.
        since = parse_datetime(str(((j.money_flow.metadata or {}).get('pix_charge_recheck') or {})
                                   .get('first_unanswered_at') or '')) or timezone.now()
        waited = (timezone.now() - since).total_seconds()
        if waited > int(getattr(settings, 'LOCAL_MONEY_PIX_RECHECK_MAX_SECONDS', 1800)):
            return 'pix_charge_unconfirmed'
        return None
    fresh = answer.get('charge') or {}
    try:
        same_amount = Decimal(str(fresh.get('amount'))) == Decimal(charge['amount'])
    except (ArithmeticError, ValueError, TypeError):
        same_amount = False
    # Names compare only when they come from the same place: a journey
    # authorized on a provider (DICT) name is not "changed" by a QR name.
    same_source = (charge.get('holder_source') or 'dict') == (answer.get('holder_source') or 'dict')
    if not same_amount or (same_source and charge.get('holder') and answer.get('holder_name') != charge['holder']):
        return 'pix_charge_changed'
    return True


def _charge_recheck(j, value, client=None):
    """The Pix network's answer for this charge, read by advance_journey
    BEFORE it locks the journey (prefetch_charge_answer): a slow or hostile
    QR site must never hold the row lock or a worker. Without a prefetched
    answer the check is simply not done this pass (temporary)."""
    answer = getattr(j, '_charge_answer', None)
    if answer is None or answer.get('_value') != value:
        answer = {'id': '', 'status': 'TEMPORARY_FAILURE'}
    meta = j.money_flow.metadata or {}
    previous = meta.get('pix_charge_recheck') or {}
    now = timezone.now().isoformat()
    unanswered = answer.get('status') != 'SUCCESSFUL' and not answer.get('gone')
    j.money_flow.metadata = dict(meta, pix_charge_recheck={
        'status': answer.get('status', ''), 'checked_at': now,
        # The wait for an answer counts from the first unanswered check.
        'first_unanswered_at': (previous.get('first_unanswered_at') or now) if unanswered else ''})
    j.money_flow.save(update_fields=['metadata', 'updated_at'])
    return answer


def prefetch_charge_answer(journey_id):
    """Read a Pix charge from the network for a journey about to convert, with
    no lock held. None when the journey will not need it this pass."""
    row = InfiniaJourney.objects.filter(pk=journey_id).values(
        'internal_id', 'direction', 'stage', 'destination_snapshot', 'funding_credit_id', 'fx_operation_id',
        'fx_operation__status', 'payout_operation_id', 'bridge__provider_credit_id', 'money_flow_id').first()
    if (not row or row['direction'] != 'to_bank' or row['stage'] in {'completed', 'failed', 'refunding'}
            or not (row['destination_snapshot'] or {}).get('pix_charge') or row['payout_operation_id']
            or not (row['funding_credit_id'] or row['bridge__provider_credit_id'])):
        return None
    # Only the passes that read the answer: before the conversion, or when a
    # conversion that never ran is about to be quoted again.
    if row['fx_operation_id'] and row['fx_operation__status'] not in {'created', 'failed'}:
        return None
    if MoneyOperation.objects.filter(money_flow_id=row['money_flow_id'], provider='infinia',
                                     idempotency_key=str(uuid.uuid5(row['internal_id'], RETURN_LEG))).exists():
        return None
    value = ((row['destination_snapshot'] or {}).get('destination_account') or {}).get('brCode', '')
    if not value:
        return None
    from . import local_money
    charge = row['destination_snapshot']['pix_charge']
    left = local_money._seconds_left(local_money._aware(charge.get('expires_at')))
    if left is not None and left < int(getattr(settings, 'LOCAL_MONEY_PIX_SETTLE_SECONDS', 180)):
        return None  # it is refunded without asking
    answer = local_money._validate(local_money.METHODS['br_qr'], value, None)
    return dict(answer, _value=value)


def _authorized_exact_quote(j, source, target, available, client=None):
    """(quote, '') for exactly the charge amount within the dollars that
    arrived; (None, 'short') when they no longer cover it; (None, 'invalid')."""
    from .local_money import usdc_for_target
    try:
        exact = positive(_charge(j)['amount'])
        amount, quote = usdc_for_target(client or InfiniaClient(), source, target, exact,
                                        external_id=str(j.internal_id))
        expires = parse_datetime(str(quote.get('expire_at', '')))
        if expires and timezone.is_naive(expires):
            expires = expires.replace(tzinfo=dt_timezone.utc)
        valid = (quote.get('id') and expires and expires > timezone.now()
                 and str(quote.get('source_account_id')) == source.provider_account_id
                 and str(quote.get('target_account_id')) == target.provider_account_id)
    except (AttributeError, TypeError, ValueError, ArithmeticError, PaymentAccountError):
        return None, 'invalid'
    if not valid:
        return None, 'invalid'
    if amount > available:
        return None, 'short'
    return quote, ''


def _start_exact_conversion(j, source, target, credit_amount, client=None):
    """The operation to submit for a Pix charge's conversion, a full refund
    when it cannot be paid, or None (waiting, or parked for review)."""
    charge = _charge(j)
    payable = _charge_still_payable(j, charge, client)
    if payable is None:
        return None
    if payable is not True:
        return _start_return(j, credit_amount, 'refunding', payable)
    quote, problem = _authorized_exact_quote(j, source, target, credit_amount, client)
    if problem == 'short':
        return _start_return(j, credit_amount, 'refunding', 'pix_charge_fx_short')
    if quote is None:
        _state(j, 'needs_review', failure='fx_quote_outside_authorization')
        return None
    amount = positive(quote['source_amount'])
    j.fx_quote = quote
    j.fx_operation = _new_operation(j, 'fx', source, target, amount)
    j.money_flow.metadata = dict(j.money_flow.metadata, fx_source_remainder={
        'amount': str(credit_amount - amount), 'asset': source.asset,
        'financial_account_id': str(source.internal_id), 'funding_credit_id': str(j.funding_credit_id),
    })
    j.save(update_fields=['fx_quote', 'fx_operation', 'updated_at'])
    _state(j, 'converting')
    return j.fx_operation


def _quote_refused(j):
    if contract_funded(j):
        # The money is already out: wait for the rate, for a bounded while.
        from .contract_funding import rate_refused
        rate_refused(j)
    else:
        _state(j, 'needs_review', failure='fx_quote_outside_authorization')


def advance_journey(journey_id, *, client=None, bridge_client=None, intents=None):
    """Persist each leg under a row lock, submit only after COMMIT.

    Provider retry/reconciliation owns unknown submissions under the original
    idempotency key. A worker never creates a replacement economic leg.
    """
    operation = None
    # Network reads for a Pix charge happen here, before any lock is taken.
    charge_answer = prefetch_charge_answer(journey_id)
    payout_lookup = prefetch_payout_lookup(journey_id, client)
    from .contract_funding import owner_problem, refresh_payee
    refresh_payee(journey_id)
    owner_held = owner_problem(journey_id)
    with transaction.atomic():
        j = InfiniaJourney.objects.select_for_update(of=('self',)).select_related(
            'money_flow', 'confio_account', 'local_account__provider_profile',
            'crypto_account__provider_profile', 'funding_credit', 'bridge__quote',
            'fx_operation', 'payout_operation').get(pk=journey_id)
        # The flow row may have changed since the join was read (another pass
        # just committed): its metadata carries the unwind state.
        j.money_flow.refresh_from_db()
        j._charge_answer = charge_answer
        j._payout_lookup = payout_lookup
        if j.stage in {'completed', 'failed'}:
            return j
        unwinding = _unwind_started(j)
        if (not unwinding and j.stage == 'needs_review' and _charge(j) and not _requotable(j)
                and not (j.money_flow.metadata or {}).get('pix_charge_unwind')
                and j.failure_code in UNWIND_TRIGGERS):
            verdict = _unwindable(j)
            if verdict is None:
                # The provider did not answer: ask again next pass, for a while.
                meta = j.money_flow.metadata or {}
                since = parse_datetime(str(meta.get('pix_charge_unwind_wait') or ''))
                if since is None:
                    j.money_flow.metadata = dict(meta, pix_charge_unwind_wait=timezone.now().isoformat())
                    j.money_flow.save(update_fields=['metadata', 'updated_at'])
                    return j
                hours = int(getattr(settings, 'LOCAL_MONEY_PIX_UNWIND_MAX_HOURS', 6))
                if timezone.now() - since < timedelta(hours=hours):
                    return j
                verdict = False  # no answer for hours: a human decides
            if not verdict:
                # Checked once: never live again, so it cannot block the owner.
                _unwind_mark(j, 'not_applicable')
                return j
            unwinding = True
        if j.stage == 'needs_review' and not _requotable(j) and not unwinding:
            # Only a delayed deposit can recover automatically, using receipts
            # alone. Never resume money-moving legs or override another review.
            from .infinia_bridge import RECOVERABLE_DELAYS
            if (j.failure_code not in RECOVERABLE_DELAYS or not j.bridge_id
                    or j.bridge.funding_mode != 'infinia'):
                return j
            for op in (j.fx_operation, j.payout_operation):
                if op and (has_refund(op) or op.status in {'failed', 'reversed', 'needs_review'}):
                    _state(j, 'needs_review', failure='provider_leg_requires_review')
                    return j
            from .bridge_execution import reconcile_bridge
            j.bridge = reconcile_bridge(j.bridge, intents=intents)
            if j.bridge.status == 'delivered':
                _complete_wallet(j)
            elif j.bridge.failure_code and j.bridge.failure_code not in RECOVERABLE_DELAYS:
                _state(j, 'needs_review', failure=j.bridge.failure_code)
            return j
        for op in (j.fx_operation, j.payout_operation):
            if op and has_refund(op):
                if unwinding:
                    _unwind_mark(j, 'stopped')
                _state(j, 'needs_review', failure='provider_refund_posted'); return j
        if contract_funded(j):
            # Before any conversion or payout leaves: what the contract
            # executed must be what the owner signed for this run, and the
            # payee still the one signed for.
            from . import contract_funding
            if contract_funding.payout_unsent(j):
                problem = contract_funding.before_paying(j)
                if problem == contract_funding.EVENT_NOT_SEEN:
                    return j    # the event scan is behind
                if problem:
                    contract_funding.park_terms_changed(j.bridge, j, problem)
                    return j
                problem, waiting = contract_funding.payee_problem(j)
                if problem:
                    if not waiting:
                        contract_funding.park_payee_changed(j, problem)
                    return j
                if owner_held and (j.funding_credit_id or j.bridge.provider_credit_id):
                    contract_funding.park_not_payable(j, owner_held)
                    return j
        enabled()
        if j.direction == 'to_wallet':
            from .payin_admission import assess
            admission = assess(j.funding_credit)
            if admission and not admission.allowed:
                _state(j, 'needs_review', failure=f'payin_{admission.reason}')
                return j
        validate_accounts(j.confio_account, j.local_account, j.crypto_account, j.destination_snapshot['country'])
        # A contract-funded journey pins the immutable account contract.
        pinned = j.bridge.quote.source_address if contract_funded(j) else j.confio_account.bsc_address
        if address(pinned) != j.wallet_address:
            _state(j, 'needs_review', failure='wallet_changed'); return j
        source, target = (j.crypto_account, j.local_account) if j.direction == 'to_bank' else (j.local_account, j.crypto_account)
        if not j.funding_credit_id:
            if j.bridge.status in SETTLED_BRIDGE_FAILURES:
                # Resolved: nothing moved, or the refund is back in the user's
                # own wallet. Terminal for the journey, and nothing to review.
                _state(j, 'failed', failure='bridge_' + j.bridge.status); return j
            if j.bridge.status == 'needs_review':
                _state(j, 'needs_review', failure='bridge_not_delivered'); return j
            if not j.bridge.provider_credit_id:
                return j
            credit = j.bridge.provider_credit
            if credit.financial_account_id != source.pk or credit.asset != source.asset or credit.direction != 'credit':
                _state(j, 'needs_review', failure='funding_credit_mismatch'); return j
            j.funding_credit = credit
            j.save(update_fields=['funding_credit', 'updated_at'])
        returning = _return_operation(j) if _charge(j) else None
        if returning is not None:
            if has_refund(returning) or returning.status in {'failed', 'reversed', 'needs_review'}:
                if unwinding:
                    _unwind_mark(j, 'stopped')
                _state(j, 'needs_review', failure='pix_charge_return_' + (
                    'refunded' if has_refund(returning) else returning.status))
            elif unwinding and not _unwind_legs_clear(j):
                _state(j, 'needs_review', failure='pix_charge_unwind_leg_problem')
            elif unwinding and j.stage == 'needs_review' and returning.status in {
                    'created', 'submitted', 'processing', 'settling', 'unknown'} and not _leg_stuck(returning):
                # Parked while its refund is still in flight: submissions are
                # refused in needs_review, and this one is the person's money.
                _state(j, 'refunding', failure=j.failure_code)
                if returning.status == 'created':
                    operation = returning
            elif returning.status == 'succeeded':
                _finish_return(j)
            elif returning.status == 'created' and unwinding and _leg_stuck(returning):
                _close_never_submitted(returning)
                _state(j, 'needs_review', failure='pix_charge_return_stuck')
            elif returning.status == 'created':
                operation = returning
        elif unwinding and not _unwind_legs_clear(j):
            # Parked by a problem on the conversion or the unwind itself: no
            # more money moves; a human looks.
            _state(j, 'needs_review', failure='pix_charge_unwind_leg_problem')
        elif unwinding:
            # Serialized with create_journey on the owner row, so starting an
            # unwind and a new payment can never both pass the gate.
            type(j.confio_account).objects.select_for_update().filter(pk=j.confio_account_id).first()
            pending = _unwind_operation(j)
            if pending is not None and pending.status == 'created' and _leg_stuck(pending):
                # Checked before any wait: a leg that cannot go out for hours
                # always ends (closed, parked), whatever keeps it waiting.
                _close_never_submitted(pending)
                _state(j, 'needs_review', failure='pix_charge_unwind_stuck')
                return j
            if pending is None:
                # Only before the first leg exists: the same gate create_journey
                # uses, plus both accounts the unwind debits. Once it has
                # started it only moves forward; each submission is still
                # checked by submit_money_operation, and refused legs end at
                # the 6 h stuck exits.
                if live_journeys(InfiniaJourney.objects.filter(confio_account=j.confio_account)).exclude(
                        money_flow_id=j.money_flow_id).exists():
                    return j
                try:
                    require_unreserved_source('infinia', j.local_account, j.money_flow_id)
                    require_unreserved_source('infinia', j.crypto_account, j.money_flow_id)
                except PaymentAccountError:
                    return j  # reserved by something else for now: a candidate, not live
            operation = _advance_unwind(j)
        elif not j.fx_operation_id and _charge(j):
            # Waiting is not a failure. Do not start a quote's expiry clock
            # while another operation still reserves this source account.
            require_unreserved_source('infinia', source, j.money_flow_id)
            _require_capability(source, 'convert')
            operation = _start_exact_conversion(j, source, target, positive(j.funding_credit.amount), client)
        elif not j.fx_operation_id:
            # Waiting is not a failure. Do not start a quote's expiry clock
            # while another operation still reserves this source account.
            require_unreserved_source('infinia', source, j.money_flow_id)
            _require_capability(source, 'convert')
            credit_amount = positive(j.funding_credit.amount)
            if credit_amount < FX_SOURCE_QUANTUM:
                _state(j, 'needs_review', failure='fx_source_below_precision')
                return j
            amount = fx_source_amount(credit_amount)
            if contract_funded(j):
                # A sweep can bring a stranger's dust (or more) along: never
                # convert over what was signed; the rest stays in the owner's
                # account, recorded as the remainder below.
                from .contract_funding import signed_usd
                amount = min(amount, fx_source_amount(signed_usd(j)))
            quote = _authorized_fx_quote(j, source, target, amount, client)
            if quote is None:
                _quote_refused(j); return j
            if j.direction == 'to_wallet' and j.minimum_wallet_output is not None:
                from .infinia_bridge import preflight, InfiniaBridgeReview
                try:
                    preflight(j, positive(quote['target_amount']))
                except InfiniaBridgeReview:
                    _state(j, 'needs_review', failure='direct_bridge_unavailable'); return j
            j.fx_quote = quote
            j.fx_operation = _new_operation(j, 'fx', source, target, amount)
            # The original credit stays intact. This unconverted fraction is
            # still the user's money in their source account, NOT a fee or a
            # new credit. Persist attribution with the operation atomically;
            # retries reuse that operation and cannot count it twice.
            j.money_flow.metadata = dict(j.money_flow.metadata, fx_source_remainder={
                'amount': str(credit_amount - amount), 'asset': source.asset,
                'financial_account_id': str(source.internal_id),
                'funding_credit_id': str(j.funding_credit_id),
            })
            j.save(update_fields=['fx_quote', 'fx_operation', 'updated_at'])
            _state(j, 'converting')
            operation = j.fx_operation
        elif expired_fx_rejection(j.fx_operation, j.fx_quote.get('id')) or stale_unsubmitted_quote(j):
            # A never-submitted quote can expire during a reservation race.
            # Otherwise require explicit rejection AND an empty provider lookup;
            # idempotency alone never authorizes changing an ambiguous request.
            require_unreserved_source('infinia', source, j.money_flow_id)
            unsubmitted = stale_unsubmitted_quote(j)
            tries = int((j.money_flow.metadata or {}).get('fx_requote_count', 0))
            if tries >= FX_REQUOTE_LIMIT:
                _state(j, 'needs_review', failure='fx_quote_retries_exhausted'); return j
            lookup = [] if unsubmitted else (client or InfiniaClient()).find_operation('conversion', j.fx_operation.idempotency_key)
            if not _explicitly_empty_lookup(lookup):
                _state(j, 'needs_review', failure='fx_requote_provider_unresolved'); return j
            # Reject contradictory ledger evidence even if a lookup returns []:
            # a missing provider operation ID must never bypass a known debit.
            if LedgerEntry.objects.filter(operation=j.fx_operation, direction='debit').exists():
                _state(j, 'needs_review', failure='fx_requote_debit_exists'); return j
            amount = positive(j.fx_operation.source_amount)
            if _charge(j):
                # Same reais again; the dollars it takes may differ, within
                # what arrived. A charge no longer payable or no longer
                # covered parks the journey: the rejected conversion cannot
                # be retired cleanly here, so a human returns the dollars.
                payable = _charge_still_payable(j, _charge(j), client)
                if payable is None:
                    return j
                if payable is not True:
                    _state(j, 'needs_review', failure=payable); return j
                quote, problem = _authorized_exact_quote(j, source, target, positive(j.funding_credit.amount), client)
                if problem == 'short':
                    _state(j, 'needs_review', failure='pix_charge_fx_short'); return j
                if quote is not None:
                    amount = positive(quote['source_amount'])
            else:
                quote = _authorized_fx_quote(j, source, target, amount, client)
            if quote is None:
                _quote_refused(j); return j
            if j.direction == 'to_wallet' and j.minimum_wallet_output is not None:
                from .infinia_bridge import preflight, InfiniaBridgeReview
                try:
                    preflight(j, positive(quote['target_amount']))
                except InfiniaBridgeReview:
                    _state(j, 'needs_review', failure='direct_bridge_unavailable'); return j
            operation = j.fx_operation
            previous = dict(operation.provider_data)
            changed = MoneyOperation.objects.filter(pk=operation.pk, status=operation.status,
                submitted_at=operation.submitted_at,
                provider_operation_id=operation.provider_operation_id,
                updated_at=operation.updated_at, provider_data=previous).update(
                    status='created', failure_code='', failure_detail='', source_amount=amount,
                    provider_data={'quote_id': quote['id']}, updated_at=timezone.now())
            if not changed:
                return j
            operation.refresh_from_db()
            history = list((j.money_flow.metadata or {}).get('fx_requote_history', []))
            history.append({'previous_quote_id': j.fx_quote['id'], 'quote_id': quote['id'],
                            'rejection': previous,
                            'provider_lookup': 'never_submitted' if unsubmitted else 'empty'})
            j.money_flow.metadata = dict(j.money_flow.metadata or {}, fx_requote_count=tries + 1,
                                        fx_requote_history=history)
            j.money_flow.save(update_fields=['metadata'])
            j.fx_quote = quote
            j.save(update_fields=['fx_quote', 'updated_at'])
            _state(j, 'converting')
        elif j.fx_operation.status in {'failed', 'reversed', 'needs_review'}:
            _state(j, 'needs_review', failure='conversion_' + j.fx_operation.status)
        elif not j.payout_operation_id:
            why = {}
            proceeds = _credit_for_operation(j.fx_operation, target, why=why)
            if not proceeds and why.get('reason'):
                _state(j, 'needs_review', failure=why['reason'])
            elif not proceeds:
                operation = j.fx_operation if j.fx_operation.status == 'created' else None
            elif proceeds < j.minimum_fx_output or proceeds != positive(j.fx_quote['target_amount']):
                _state(j, 'needs_review', failure='conversion_credit_mismatch')
            elif _charge(j) and proceeds != positive(_charge(j)['amount']):
                _state(j, 'needs_review', failure='conversion_credit_mismatch')
            elif _charge(j) and _charge_expired(j):
                # The reais are in the person's own local account; paying an
                # expired charge would only bounce. A human returns them.
                _state(j, 'needs_review', failure='pix_charge_expired_after_conversion')
            else:
                _require_capability(target, 'send_third_party')
                quantum = Decimal('0.01') if j.direction == 'to_bank' else Decimal('0.000001')
                payout_amount = proceeds.quantize(quantum, rounding=ROUND_DOWN)
                positive(payout_amount)
                direct = j.direction == 'to_wallet' and j.minimum_wallet_output is not None
                if direct:
                    from .infinia_bridge import prepare_infinia_bridge, payout_destination, InfiniaBridgeReview
                    try:
                        j.bridge = prepare_infinia_bridge(j, payout_amount, client=bridge_client, intents=intents)
                    except InfiniaBridgeReview:
                        _state(j, 'needs_review', failure='direct_bridge_outside_authorization'); return j
                    j.save(update_fields=['bridge', 'updated_at'])
                j.payout_operation = _new_operation(j, 'payout', target, None, payout_amount)
                if direct:
                    # Keep the original authorization snapshot stable for request
                    # retries; only the persisted payout funds the generated address.
                    j.payout_operation.external_destination = {
                        'destination_account': payout_destination(j.bridge.deposit_address),
                        'country': 'XXX',
                    }
                    j.payout_operation.save(update_fields=['external_destination', 'updated_at'])
                j.save(update_fields=['payout_operation', 'updated_at'])
                _state(j, 'paying_out')
                operation = j.payout_operation
        elif j.payout_operation.status in {'failed', 'reversed', 'needs_review'}:
            _state(j, 'needs_review', failure='payout_' + j.payout_operation.status)
        elif j.direction == 'to_wallet' and j.bridge_id and j.bridge.funding_mode == 'infinia':
            from .bridge_execution import reconcile_bridge
            j.bridge = reconcile_bridge(j.bridge, intents=intents)
            if j.bridge.status == 'delivered':
                _complete_wallet(j)
            elif j.bridge.status in {'failed', 'expired', 'needs_review', 'refunded'}:
                _state(j, 'needs_review', failure=j.bridge.failure_code or 'return_bridge_' + j.bridge.status)
            else:
                _state(j, 'bridging')
                if j.payout_operation.status == 'created':
                    operation = j.payout_operation
        elif j.payout_operation.status == 'succeeded':
            if j.direction == 'to_wallet' and j.bridge_id and j.bridge.status in {'failed', 'expired', 'needs_review', 'refunded'}:
                _state(j, 'needs_review', failure='return_bridge_' + j.bridge.status)
                return j
            if j.direction == 'to_bank':
                # A payout face amount is not proof of net bank proceeds.
                j.money_flow.target_amount = j.payout_operation.target_amount
                j.money_flow.metadata = dict(j.money_flow.metadata,
                    payout_face_amount=str(j.payout_operation.source_amount), payout_asset=j.local_account.asset)
                j.money_flow.save(update_fields=['target_amount', 'updated_at'])
                remainder = Decimal(0)
                if _charge(j):
                    remainder = (positive(j.funding_credit.amount) - j.fx_operation.source_amount).quantize(
                        USDC_QUANTUM, rounding=ROUND_DOWN)
                minimum_return = Decimal(str(getattr(settings, 'LOCAL_MONEY_PIX_MIN_RETURN_USD', '0.01')))
                if remainder > 0 and remainder >= minimum_return:
                    operation = _start_return(j, remainder, 'returning_remainder', 'pix_charge_remainder')
                else:
                    _state(j, 'completed')
            elif j.bridge_id and j.bridge.status == 'delivered':
                j.money_flow.target_amount = Decimal(j.bridge.actual_out_units) / Decimal(10**18)
                j.money_flow.save(update_fields=['target_amount', 'updated_at'])
                _state(j, 'completed')
            elif j.bridge_id:
                _state(j, 'bridging')
            else:
                arrived = _prove_wallet_arrival(j)
                if j.stage != 'needs_review':
                    _state(j, 'awaiting_wallet_authorization' if arrived else 'awaiting_wallet_delivery')
        elif j.payout_operation.status == 'created':
            operation = j.payout_operation
    if operation:
        # Never hold the journey transaction over a money-moving HTTP request.
        submit_money_operation(operation)
    return j


def _charge_expired(j):
    """Too late to pay: the payout must have time to settle before the charge expires."""
    from . import local_money
    left = local_money._seconds_left(local_money._aware((_charge(j) or {}).get('expires_at')))
    return left is not None and left < int(getattr(settings, 'LOCAL_MONEY_PIX_PAYOUT_SECONDS', 60))


def _complete_wallet(j):
    j.money_flow.target_amount = Decimal(j.bridge.actual_out_units) / Decimal(10**18)
    j.money_flow.save(update_fields=['target_amount', 'updated_at'])
    _state(j, 'completed')


@transaction.atomic
def attach_return_bridge(*, owner, journey_id, bridge):
    j = InfiniaJourney.objects.select_for_update().get(internal_id=journey_id, confio_account=owner)
    from .contract_funding import refuse_owner_action
    refuse_owner_action(j.money_flow)
    refuse_owner_action(bridge.quote.money_flow)
    if j.bridge_id:
        if j.bridge_id != bridge.pk:
            raise PaymentAccountError('Journey already has a return bridge')
        return j
    if (j.direction != 'to_wallet' or j.stage != 'awaiting_wallet_authorization'
            or bridge.quote.confio_account_id != owner.pk or bridge.quote.source_token_id != 'POL:USDC'
            or bridge.quote.destination_address != j.wallet_address
            or bridge.quote.funding_instruction.financial_account_id != j.crypto_account_id
            or bridge.quote.amount_units != j.wallet_arrival_units):
        raise PaymentAccountError('Return bridge does not match this journey')
    j.bridge = bridge
    j.save(update_fields=['bridge', 'updated_at'])
    _state(j, 'bridging')
    return j


def _prove_wallet_arrival(j):
    if j.wallet_arrival_units:
        return True
    from . import bridge_chain as chain
    operation = j.payout_operation
    if not operation.provider_operation_id:
        return False
    entries = LedgerEntry.objects.filter(provider='infinia', financial_account=j.crypto_account,
        direction='debit', asset='USDC_POL', provider_data__operation__operation_id=operation.provider_operation_id,
        provider_data__operation__type='PAYOUT')
    hashes = {str((e.provider_data.get('third_party') or {}).get('transaction_hash', '')).lower()
              for e in entries if (e.provider_data.get('third_party') or {}).get('type') == 'CRYPTO'
              and str((e.provider_data.get('third_party') or {}).get('crypto_network', '')).upper() == 'POLYGON'}
    if len(hashes) != 1 or not next(iter(hashes)):
        return False
    tx_hash = next(iter(hashes))
    receipt = chain.final_receipt('POL', tx_hash)
    if not receipt:
        return False
    received = chain.received_units(receipt, 'POL:USDC', j.wallet_address)
    if received <= 0 or Decimal(received) / Decimal(10**6) > operation.source_amount:
        _state(j, 'needs_review', failure='wallet_receipt_mismatch')
        return False
    j.wallet_arrival_units, j.wallet_arrival_tx_hash = str(received), tx_hash
    j.save(update_fields=['wallet_arrival_units', 'wallet_arrival_tx_hash', 'updated_at'])
    return True


def observe_refund(entry):
    """React only to a posted refund for a known operation and source account."""
    if entry.direction != 'credit' or Decimal(str(entry.amount)) <= 0:
        return
    operation = entry.provider_data.get('operation') or {}
    field = {'INTERNAL_TRANSFER_REFUND': 'fx_operation', 'PAYOUT_REFUND': 'payout_operation'}.get(operation.get('type'))
    if not field or not operation.get('operation_id'):
        return
    for j in InfiniaJourney.objects.filter(**{
        field + '__provider_operation_id': str(operation['operation_id']),
        field + '__source_account_id': entry.financial_account_id,
    }).select_related('money_flow'):
        _state(j, 'needs_review', failure='provider_refund_posted')
