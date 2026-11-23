"""Bank payment rules (spec 7.5): the standing authorization recorded with
Face when the owner creates the rule, and the run with nobody present.

What is built and tested here: the authorization record and its binding to
destination, amount and frequency; the checks before a run (authorization
live, destination unchanged and still verified, rail still enabled, the
rule's own bridge-cost and FX limits, and an Infinia rail's signed fee
ceiling); skip-and-notify outside the limits.

What is built and tested against mocked providers, and NOT yet observed
with real money (InfiniaAdapter, payment_accounts/contract_funding.py): the
bridge and the Infinia journey of a run funded by the account CONTRACT.
Execution therefore still needs both SMART_ACCOUNT_PAYOUT_RAILS and
SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED, and a rail with a real adapter
(INFINIA_RAILS): no flag turns on any other.

Providers are a registry keyed by rail (RAIL_ADAPTERS): every local_money
rail is Infinia's (with an adapter for CLABE and Pix keys only); 've_pagomovil' (Venezuelan Pago Móvil) is Pago ASAP's
(PagoAsapAdapter), switched on by SMART_ACCOUNT_PAYOUT_RAILS containing
've_pagomovil' AND SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS containing
'pagoasap' AND ramps declaring it can take a send funded by the account
contract (ramps_contract_funding_ready()), with that send's own switch, its
Polygon address and a Relay key (rail_ready).
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_UP, Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import BANK_REJECTIONS, KEY_REJECTED, SmartAccountPayout, SmartAccountStandingAuthorization

logger = logging.getLogger(__name__)

BPS = 10_000
WAD = 10 ** 18

INFINIA = 'infinia'
# The Infinia rails with a real unattended adapter. Every other one (Bre-B:
# paused, and needs a device location pass per operation; CVU; any QR) has
# none, whatever the environment lists.
INFINIA_RAILS = ('mx_clabe', 'br_pix')
# One true sentence per authorization_problem code.
AUTHORIZATION_MESSAGES = {
    'no_standing_authorization':
        'Esta regla no tiene una autorización vigente. Fírmala de nuevo para reactivarla.',
    'destination_deleted': 'La cuenta guardada de esta regla ya no existe. Elige otra y firma la regla de nuevo.',
    'destination_changed': 'La cuenta guardada o su titular cambió. Firma la regla de nuevo para reactivarla.',
    'rail_not_available': 'Los pagos automáticos a este tipo de cuenta están en pausa. No hicimos este pago.',
    'destination_unverified':
        'El banco no confirmó la cuenta de quien recibe. No hicimos este pago: revisa los datos guardados.',
    'holder_unverified': ('No pudimos confirmar de nuevo el titular con el que firmaste. No hicimos este pago: '
                          'revisa a quien recibe y firma la regla de nuevo.'),
}
RULE_CHANGED = 'La regla cambió mientras preparábamos el pago.'
# Signed before a rule had a rate floor: no money moves without one.
FLOOR_UNSIGNED = 'fx_floor_unsigned'
FLOOR_UNSIGNED_MESSAGE = 'Tu regla no tiene una tasa mínima. No hicimos este pago: fírmala de nuevo.'
IN_PROGRESS = 'Este pago ya está en curso.'
# A slot keeps getting fresh orders while it lives: the first ones right
# away, then at most one an hour.
FAST_ATTEMPTS = 3
SLOW_RETRY = timedelta(hours=1)
# Orders whose money has not been seen leaving the account.
UNSENT = ('reserving', 'prepared', 'pending')
# PayoutDestination.provider_data: the bank-verified holder each standing
# authorization was signed for (a key can be re-registered to someone else).
RULE_HOLDERS_KEY = 'rule_holders'
PAGOASAP = 'pagoasap'
VE_PAGOMOVIL = 've_pagomovil'
# Rail -> provider adapter. Every rail not named here is an Infinia rail
# (payment_accounts.local_money.METHODS).
RAIL_ADAPTERS = {VE_PAGOMOVIL: PAGOASAP}
VE_PAGOMOVIL_LABEL = 'Pago Móvil'
VE_PAGOMOVIL_HINT = 'Bolívares a cualquier banco de Venezuela, a la tasa del día.'

# authorization_problem codes that stop the rule until the owner signs again.
DEACTIVATING = ('destination_deleted', 'destination_changed', 'no_standing_authorization')


def authorization_message(code: str) -> str:
    return AUTHORIZATION_MESSAGES.get(code, AUTHORIZATION_MESSAGES['no_standing_authorization'])


class PayoutSkip(Exception):
    """This run does not happen; the owner is told why (Spanish message).
    `deactivate`: the rule also stops until the owner signs it again.
    `retry_later`: a passing refusal; the slot is retried (until it gives up)
    instead of being skipped for good.
    `wait`: so ordinary (the owner's own send holds the accounts, a provider
    hiccup) that nobody is told until the slot gives up."""

    def __init__(self, code: str, message: str, *, deactivate: str = '', retry_later: bool = False,
                 wait: bool = False):
        self.code = code
        self.message = message
        self.deactivate = deactivate
        self.retry_later = retry_later or wait
        self.wait = wait
        super().__init__(code)


def _limit_skip(exc) -> 'PayoutSkip':
    """A ramps send limit, the same answer before and under the reservation
    lock: 'limit_exceeded' either way. A per-send minimum/maximum is final
    for this slot (the amount never passes it); a rolling daily cap is
    passing (it frees up), so the slot waits for it, untold, until it gives up."""
    return PayoutSkip('limit_exceeded', str(exc) or VE_UNAVAILABLE, wait=bool(getattr(exc, 'passing', False)))


def adapter_name(rail: str) -> str:
    return RAIL_ADAPTERS.get(rail or '', INFINIA)


def verified_adapters() -> set:
    """Adapters confirmed for unattended payouts. Infinia keeps its own flag
    (SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED); every other adapter is named in
    SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS (comma list or list)."""
    raw = getattr(settings, 'SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS', '') or ''
    names = raw if isinstance(raw, (list, tuple, set, frozenset)) else str(raw).split(',')
    out = {str(n).strip().lower() for n in names if str(n).strip()}
    out.discard(INFINIA)
    if getattr(settings, 'SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED', False):
        out.add(INFINIA)
    return out


def adapter_verified(name: str = INFINIA) -> bool:
    return name in verified_adapters()


def ramps_contract_funding_ready() -> bool:
    """ramps can take a VE send funded by the account CONTRACT's exit: the
    USDT reaches the bridge deposit address from the cUSD vault (the
    contract's redeemWithFee), not from the sender of record's wallet, and
    for exactly the amount the contract exits (no amount tag). Declared by
    ramps.ve_send.CONTRACT_FUNDING (with reserve(funding_sender=...), the
    funding proof and pagoasap_send.settle honouring it). Until ramps
    declares it, the rail is neither offered nor run."""
    try:
        from ramps import ve_send
    except Exception:  # noqa: BLE001 — unknown is never "ready"
        logger.warning('ramps.ve_send unavailable', exc_info=True)
        return False
    return getattr(ve_send, 'CONTRACT_FUNDING', False) is True


def has_adapter(rail: str) -> bool:
    """A real adapter exists for `rail`. No setting can say otherwise."""
    return rail in INFINIA_RAILS or adapter_name(rail) == PAGOASAP


def rail_ready(rail: str) -> bool:
    """The provider side of `rail` may run with nobody present: a real
    adapter, confirmed by its flag, with the switches its path needs on."""
    if not has_adapter(rail):
        return False
    name = adapter_name(rail)
    if not adapter_verified(name):
        return False
    from payment_accounts import contract_funding
    if name == PAGOASAP:
        from ramps import ve_pagomovil
        return (ramps_contract_funding_ready() and ve_pagomovil.enabled(ve_pagomovil.SEND)
                and bool(str(getattr(settings, 'PAGOASAP_DEPOSIT_ADDRESS_POLYGON', '') or '').strip())
                # Settlement follows the deposit through /requests/v3 here too.
                and contract_funding.relay_key_set())
    return contract_funding.rail_on(rail)


def binding_hash(destination, amount: Decimal, frequency: str, processor_fee: Decimal | None = None) -> str:
    """What Face confirmed. With a fixed fee its ceiling is part of it, so
    the stored ceiling cannot be changed under the owner's confirmation. No
    fee and no stored ceiling are the same thing: none is authorized."""
    terms = {
        'destination': str(destination.internal_id), 'details': destination.details,
        'country': destination.country, 'kind': destination.kind,
        'amount': format(Decimal(amount).quantize(Decimal('0.01')), 'f'), 'frequency': frequency,
    }
    if processor_fee:
        terms['max_processor_fee_usd'] = format(Decimal(processor_fee).quantize(Decimal('0.000001')), 'f')
    body = json.dumps(terms, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(body.encode()).hexdigest()


# How long an authorization that never reached the chain may be reused by an
# exact retry of the same prepare (services.PREPARED_TTL_SECONDS).
AUTHORIZATION_RETRY_SECONDS = 15 * 60


def face_identifier(digest: str, row_pk: int) -> str:
    """The bound action of one Face grant: the economic terms AND the row the
    grant authorizes. Terms alone repeat (a cancelled rule recreated, a
    removed beneficiary named again) and would reuse the consumed grant
    (security.face_step_up lets an exact action retry after consumption)."""
    return f'{digest}:{int(row_pk)}'


def _retryable_authorization(user, kind: str, digest: str, reusable=None, **terms):
    """The authorization an exact retry of the same prepare reuses: same
    user, kind and terms, recent, not revoked, and not yet carried by a rule
    that reached the chain. Anything else gets a new row (and a new Face).
    `reusable(row)`: what else must be equal and is not a column."""
    from .models import SmartAccountRule
    since = timezone.now() - timedelta(seconds=AUTHORIZATION_RETRY_SECONDS)
    candidates = SmartAccountStandingAuthorization.objects.filter(
        user=user, kind=kind, binding_hash=digest, revoked_at__isnull=True, authorized_at__gte=since,
        **terms).order_by('-pk')
    for row in candidates[:5]:
        if reusable is not None and not reusable(row):
            continue
        if not SmartAccountRule.all_objects.filter(
                standing_authorization=row, state__in=('onchain', 'cancelled')).exists():
            return row
    return None


def _authorize(viewer, kind: str, digest: str, namespace: str, payload: dict, message: str,
               create: dict, terms: dict, reusable=None):
    """Get or create the authorization row FIRST, bind the Face grant to its
    id, then record the grant on it, in one transaction: a refused Face
    rolls the new row back (no authorization without Face). A Face check is
    only tied to an action when it is consumed, so the retry after the
    owner passes Face simply gets a new row; an exact retry after the grant
    was claimed finds this row (_retryable_authorization) and re-claims the
    same key at no new check."""
    from django.db import transaction
    with transaction.atomic():
        row = _retryable_authorization(viewer.user, kind, digest, reusable, **terms)
        if row is None:
            row = SmartAccountStandingAuthorization.objects.create(
                kind=kind, user=viewer.user, binding_hash=digest, face_action_key='', face_required=True,
                **terms, **create)
        action_key, face_required = claim_face(viewer, namespace, face_identifier(digest, row.pk),
                                               {**payload, 'authorization': str(row.internal_id)}, message)
        SmartAccountStandingAuthorization.objects.filter(pk=row.pk).update(
            face_action_key=action_key, face_required=face_required)
    row.face_action_key, row.face_required = action_key, face_required
    return row


def create_standing_authorization(viewer, *, destination, rail: str, amount: Decimal, frequency: str,
                                  reference_fx_rate: Decimal | None = None, verified_holder: str = '',
                                  processor_fee: Decimal = Decimal(0)):
    """Claim one Face grant bound to (destination, amount, frequency, fee
    ceiling) AND this authorization's own row, and record it. Raises
    PrepareError when Face is required and not granted: the row then
    authorizes nothing."""
    digest = binding_hash(destination, amount, frequency, processor_fee)
    pin = _holder_digest(verified_holder) if verified_holder else ''
    with transaction.atomic():
        saved = type(destination).objects.select_for_update(no_key=True).get(pk=destination.pk)
        holders = dict((saved.provider_data or {}).get(RULE_HOLDERS_KEY) or {})
        # The signed pin is exactly what this prepare showed: an earlier row
        # with another holder, or pinned when this shows none (or the other
        # way), is another authorization.
        row = _authorize(
            viewer, 'payout', digest, 'smart_account_payout_rule',
            {'destination': str(destination.internal_id), 'amount': format(amount, 'f'),
             'frequency': frequency, 'rail': rail, 'max_processor_fee_usd': format(processor_fee, 'f')},
            'Confirma con Confío Face para programar este pago.',
            create=dict(max_bridge_cost_bps=int(getattr(settings, 'SMART_ACCOUNT_PAYOUT_MAX_BRIDGE_COST_BPS', 150)),
                        fx_tolerance_bps=int(getattr(settings, 'SMART_ACCOUNT_PAYOUT_FX_TOLERANCE_BPS', 300)),
                        max_processor_fee_usd=processor_fee, reference_fx_rate=reference_fx_rate),
            terms=dict(payout_destination=destination, rail=rail, amount_usd=amount, frequency=frequency),
            reusable=lambda candidate: holders.get(str(candidate.internal_id), '') == pin)
        if pin and holders.get(str(row.internal_id)) != pin:
            holders[str(row.internal_id)] = pin
            saved.provider_data = {**(saved.provider_data or {}), RULE_HOLDERS_KEY: holders}
            saved.save(update_fields=['provider_data', 'updated_at'])
            destination.provider_data = saved.provider_data
    return row


def _holder_digest(name: str) -> str:
    return hashlib.sha256(' '.join(str(name or '').split()).casefold().encode()).hexdigest()


def _pagomovil_identity(destination) -> dict:
    """Who a Pago Móvil payment reaches: the saved row AND its payable
    identity (phone + bank + cédula). The row's random id salts the hashes."""
    return {'id': str(destination.internal_id), 'phone': destination.phone,
            'bank_code': destination.bank_code, 'id_number': destination.id_number}


def pagomovil_binding_hash(destination, amount: Decimal, frequency: str) -> str:
    body = json.dumps({
        'rail': VE_PAGOMOVIL, 'destination': _pagomovil_identity(destination),
        'amount': format(Decimal(amount).quantize(Decimal('0.01')), 'f'), 'frequency': frequency,
    }, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(body.encode()).hexdigest()


def pagomovil_ref_for(destination) -> bytes:
    """payoutRef stored on chain for a Pago Móvil rule (services.payout_ref_for
    for an Infinia destination): an edited beneficiary no longer matches."""
    from eth_utils import keccak
    body = json.dumps({'rail': VE_PAGOMOVIL, **_pagomovil_identity(destination)},
                      sort_keys=True, separators=(',', ':'))
    return keccak(text=body)


def reference_ves_rate() -> Decimal:
    """Today's USD->VES rate from Pago ASAP, the reference a rule's FX
    tolerance is measured against. Raises when unavailable."""
    from ramps.pagoasap_client import PagoAsapClient
    client = PagoAsapClient()
    if not client.is_configured:
        raise RuntimeError('Pago ASAP is not configured')
    rate = Decimal(str(client.rate('USD', 'VES')))
    if not rate.is_finite() or rate <= 0:
        raise RuntimeError('Pago ASAP rate is not positive')
    return rate


def create_pagomovil_authorization(viewer, *, destination, amount: Decimal, frequency: str,
                                   reference_fx_rate: Decimal):
    """The Face-confirmed standing authorization of a Pago Móvil rule, bound
    to the beneficiary's phone + bank + cédula, amount and frequency."""
    digest = pagomovil_binding_hash(destination, amount, frequency)
    return _authorize(
        viewer, 'payout', digest, 'smart_account_payout_rule',
        {'destination': str(destination.internal_id), 'amount': format(amount, 'f'),
         'frequency': frequency, 'rail': VE_PAGOMOVIL},
        'Confirma con Confío Face para programar este pago.',
        create=dict(max_bridge_cost_bps=int(getattr(settings, 'SMART_ACCOUNT_PAYOUT_MAX_BRIDGE_COST_BPS', 150)),
                    fx_tolerance_bps=int(getattr(settings, 'SMART_ACCOUNT_PAYOUT_FX_TOLERANCE_BPS', 300)),
                    reference_fx_rate=reference_fx_rate),
        terms=dict(payout_destination=None, pagomovil_destination=destination, rail=VE_PAGOMOVIL,
                   amount_usd=amount, frequency=frequency, holder_name=destination.holder_name))


def claim_face(viewer, namespace: str, digest: str, payload: dict,
                message: str = 'Confirma con Confío Face para continuar.') -> tuple[str, bool]:
    """(action key, face required) for one Face grant bound to `digest`.
    Raises PrepareError when Face applies and is not granted."""
    from payment_accounts.services import PaymentAccountError, require_outgoing_face
    from security.face_step_up import step_up_applies
    from .services import PrepareError

    face_required = bool(step_up_applies(viewer.user))
    try:
        action_key = require_outgoing_face(viewer.personal_account, namespace, digest, payload)
    except PaymentAccountError as exc:
        raise PrepareError('face_required', str(exc)) from exc
    if face_required and not action_key:
        raise PrepareError('face_required', message)
    return action_key or '', face_required


def send_binding_hash(account_address: str, payee_address: str, amount: Decimal, frequency: str) -> str:
    body = json.dumps({
        'account': (account_address or '').lower(), 'payee': (payee_address or '').lower(),
        'amount': format(Decimal(amount).quantize(Decimal('0.01')), 'f'), 'frequency': frequency,
    }, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(body.encode()).hexdigest()


def create_send_authorization(viewer, *, account, payee_address: str, amount: Decimal, frequency: str):
    """A send rule moves the owner's money to another person with nobody
    present: the SAME Face step-up a personal send asks
    (security.face_step_up.require_face_step_up, 'withdrawal'), claimed once
    when the rule is created or edited and bound to (account, payee wallet,
    amount, frequency). A full check: a standing order is worth more than one
    send, so no light check for a known recipient."""
    digest = send_binding_hash(account.contract_address, payee_address, amount, frequency)
    return _authorize(
        viewer, 'send', digest, 'smart_account_send_rule',
        {'account': account.contract_address.lower(), 'payee': payee_address.lower(),
         'amount': format(amount, 'f'), 'frequency': frequency},
        'Confirma con Confío Face para programar este envío.',
        create={},
        terms=dict(payout_destination=None, payee_address=payee_address.lower(), rail='',
                   amount_usd=amount, frequency=frequency))


def send_authorization_problem(rule, onchain: dict | None = None) -> str | None:
    """Why this send rule may not run, or None: its standing authorization
    must be live and match the rule AS IT IS ON CHAIN (payee, amount,
    frequency), so an on-chain rule nobody authorized with Face never runs."""
    authorization = rule.standing_authorization
    if authorization is None or authorization.revoked_at is not None or authorization.kind != 'send':
        return 'no_standing_authorization'
    if authorization.face_required and not authorization.face_action_key:
        return 'no_standing_authorization'
    if authorization.user_id != rule.smart_account.owner_user_id:
        return 'no_standing_authorization'
    if onchain is not None:
        payee = onchain['payee']
        amount = (Decimal(onchain['amount_usd_wei']) / Decimal(10 ** 18)).quantize(Decimal('0.01'))
        frequency = onchain['frequency']
        if onchain.get('kind') not in (None, 'send'):
            return 'authorization_mismatch'
    else:
        payee, amount, frequency = rule.payee_address, rule.amount, rule.frequency
    if authorization.binding_hash != send_binding_hash(rule.smart_account.contract_address, payee, amount, frequency):
        return 'authorization_mismatch'
    return None


def card_binding_hash(account_address: str, spender: str, amount: Decimal, frequency: str) -> str:
    body = json.dumps({
        'kind': 'card', 'account': (account_address or '').lower(), 'spender': (spender or '').lower(),
        'amount': format(Decimal(amount).quantize(Decimal('0.01')), 'f'), 'frequency': frequency,
    }, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(body.encode()).hexdigest()


def create_card_authorization(viewer, *, account, spender: str, amount: Decimal, frequency: str):
    """A Card rule (decision 35) lets a card issuer pull from the account
    with nobody present: the same full Face step-up as a send rule, claimed
    once when the rule is created or edited and bound to (account, spender,
    cap, period)."""
    digest = card_binding_hash(account.contract_address, spender, amount, frequency)
    return _authorize(
        viewer, 'card', digest, 'smart_account_card_rule',
        {'account': account.contract_address.lower(), 'spender': spender.lower(),
         'amount': format(amount, 'f'), 'frequency': frequency},
        'Confirma con Confío Face para autorizar tu tarjeta.',
        create={},
        terms=dict(payout_destination=None, payee_address=spender.lower(), rail='',
                   amount_usd=amount, frequency=frequency))


def card_authorization_problem(rule, onchain: dict | None = None) -> str | None:
    """Why this Card rule has no valid Face authorization through Confío
    (bound to the rule AS IT IS ON CHAIN: spender, cap, period), or None.
    The server cannot stop a pull; this only tells ops and the mirror."""
    authorization = rule.standing_authorization
    if authorization is None or authorization.revoked_at is not None or authorization.kind != 'card':
        return 'no_standing_authorization'
    if authorization.face_required and not authorization.face_action_key:
        return 'no_standing_authorization'
    if authorization.user_id != rule.smart_account.owner_user_id:
        return 'no_standing_authorization'
    if onchain is not None:
        if onchain.get('kind') not in (None, 'card'):
            return 'authorization_mismatch'
        spender = onchain['payee']
        amount = (Decimal(onchain['amount_usd_wei']) / Decimal(10 ** 18)).quantize(Decimal('0.01'))
        frequency = onchain['frequency']
    else:
        spender, amount, frequency = rule.payee_address, rule.amount, rule.frequency
    if authorization.binding_hash != card_binding_hash(rule.smart_account.contract_address, spender, amount,
                                                       frequency):
        return 'authorization_mismatch'
    return None


def authorization_problem(rule) -> str | None:
    """Why this payment rule may not run, or None. Also used by the daily
    sweep that deactivates a rule whose saved destination changed."""
    from . import offer
    from .services import HOLDER_VERIFIED, destination_rail, payout_destination_state, payout_ref_for

    authorization = rule.standing_authorization
    if authorization is None or authorization.revoked_at is not None or authorization.kind != 'payout':
        return 'no_standing_authorization'
    if rule.payout_rail == VE_PAGOMOVIL:
        return _pagomovil_problem(rule, authorization)
    destination = rule.payout_method
    if destination is None or destination.status not in ('pending', 'active'):
        return 'destination_deleted'
    account = rule.smart_account
    if authorization.user_id != account.owner_user_id or destination.confio_account_id != account.owner_account_id:
        return 'no_standing_authorization'
    if authorization.payout_destination_id != destination.pk:
        return 'destination_changed'
    if ('0x' + payout_ref_for(destination).hex()) != rule.payout_ref:
        return 'destination_changed'
    if authorization.binding_hash != binding_hash(destination, rule.amount, rule.frequency,
                                                  authorization.max_processor_fee_usd):
        return 'destination_changed'
    if destination_rail(destination) != rule.payout_rail or rule.payout_rail not in offer.payout_rails():
        return 'rail_not_available'
    if authorization.face_required and not authorization.face_action_key:
        return 'no_standing_authorization'
    # Verified by the bank, or well-formed while the bank lookup cannot run
    # (services.payout_destination_state); never a definite not-found.
    state = payout_destination_state(destination)
    if not state or key_rejected(destination):
        return 'destination_unverified'
    signed_for = pinned_holder(destination, authorization)
    if signed_for:
        # Signed for a holder the bank verified: it keeps needing one. A
        # lookup switched off since, or a check rewritten DISABLED, is not one.
        from payment_accounts import local_money
        if state != HOLDER_VERIFIED:
            return 'holder_unverified'
        # The same key with another verified holder is another payee.
        if signed_for != _holder_digest(destination.holder_name):
            return 'destination_changed'
        if (not getattr(settings, 'INFINIA_ACCOUNT_VALIDATION_ENABLED', False)
                and not local_money.checked_recently((destination.provider_data or {}).get('validation'))):
            return 'holder_unverified'      # too old, and it cannot be asked again
    return None


def pinned_holder(destination, authorization) -> str:
    """The verified holder this authorization was signed for ('' for none)."""
    holders = (destination.provider_data or {}).get(RULE_HOLDERS_KEY) or {}
    return holders.get(str(authorization.internal_id)) or ''


def _lookup_on() -> bool:
    return bool(getattr(settings, 'INFINIA_ACCOUNT_VALIDATION_ENABLED', False))


def key_rejected(destination) -> bool:
    """The bank rejected this key and has not verified it since, whatever
    was written over that answer (models._keep_bank_rejection)."""
    from payment_accounts import local_money
    data = destination.provider_data or {}
    validation = data.get('validation') or {}
    if local_money.verification_state(validation) == local_money.VERIFIED:
        return False
    return str(validation.get('status') or '').upper() in BANK_REJECTIONS or bool(data.get(KEY_REJECTED))


def payable_destination(destination, authorization):
    """The saved row as this authorization pays it. Signed unverified, an
    old bank answer that cannot be asked again is no answer: a copy says so
    for this payment and the shared address-book row keeps what the bank said."""
    from payment_accounts import local_money
    data = destination.provider_data or {}
    validation = data.get('validation') or {}
    if (_lookup_on() or pinned_holder(destination, authorization)
            or local_money.verification_state(validation) != local_money.VERIFIED
            or local_money.checked_recently(validation)):
        return destination
    payable = copy.copy(destination)        # never saved
    payable.holder_name = ''
    payable.provider_data = {**data, 'validation': {'status': 'DISABLED'}}
    return payable


def _ask_bank(destination):
    """local_money.recheck_destination for a run, which never writes "no
    answer" over the answer the bank gave before. None: no answer now."""
    from payment_accounts import local_money
    try:
        data = destination.provider_data or {}
        method = local_money.METHODS.get(data.get('method_id'))
        if method is None or local_money.verification_state(data.get('validation')) == local_money.PENDING:
            return local_money.recheck_destination(destination)     # a poll: no answer to lose
        value = local_money._destination_value(destination, method)
        check = local_money._start_check(destination)
        answer = local_money._validate(method, value, None)
        if answer.get('status') in ('TEMPORARY_FAILURE', 'DISABLED'):
            return None
        return local_money._apply_validation(destination, method, value, answer, check=check)
    except Exception:  # noqa: BLE001 — unknown holder: ask again, never pay
        logger.warning('holder check failed for destination %s', destination.pk, exc_info=True)
        return None


# A funded payment's holder is asked again: wait for the answer, for a while.
PAYEE_PENDING = 'holder_check_pending'


def refresh_funded_payee(destination, authorization) -> None:
    """Before funded money converts or pays, with no lock held: a pinned
    holder whose answer aged (or was rewritten) while it travelled."""
    from payment_accounts import local_money
    validation = (destination.provider_data or {}).get('validation') or {}
    if (not _lookup_on() or not pinned_holder(destination, authorization)
            or (local_money.verification_state(validation) == local_money.VERIFIED
                and local_money.checked_recently(validation))):
        return
    _ask_bank(destination)


def funded_payee_problem(destination, authorization) -> str:
    """Why funded money may not go to this payee ('' to pay). It is never a
    reason to close. A lookup toggle alone stops nothing signed unverified;
    a pinned holder must still be the one the bank names."""
    from payment_accounts import local_money
    if key_rejected(destination):
        return 'key_rejected'
    signed_for = pinned_holder(destination, authorization)
    if not signed_for:
        return ''
    validation = (destination.provider_data or {}).get('validation') or {}
    verified = local_money.verification_state(validation) == local_money.VERIFIED
    if verified and signed_for != _holder_digest(destination.holder_name):
        return 'holder_changed'
    if verified and local_money.checked_recently(validation):
        return ''
    return PAYEE_PENDING if _lookup_on() else 'holder_unverified'


def _pagomovil_problem(rule, authorization) -> str | None:
    """A Pago Móvil rule runs only while its Face authorization names the
    very beneficiary (phone + bank + cédula), amount and frequency the rule
    pays, for the account's owner, and the beneficiary is still saved."""
    from . import offer
    destination = rule.pagomovil_destination
    if destination is None or destination.deleted_at is not None:
        return 'destination_deleted'
    owner_id = rule.smart_account.owner_user_id
    if authorization.user_id != owner_id or destination.user_id != owner_id:
        return 'no_standing_authorization'
    if authorization.pagomovil_destination_id != destination.pk or authorization.rail != VE_PAGOMOVIL:
        return 'destination_changed'
    if ('0x' + pagomovil_ref_for(destination).hex()) != rule.payout_ref:
        return 'destination_changed'
    if authorization.binding_hash != pagomovil_binding_hash(destination, rule.amount, rule.frequency):
        return 'destination_changed'
    if authorization.face_required and not authorization.face_action_key:
        return 'no_standing_authorization'
    if VE_PAGOMOVIL not in offer.payout_rails():
        return 'rail_not_available'
    return None


# ── What an order was opened under, and what the chain executed ─────────
#
# executeRule pays what the contract stores when it is mined, not what was
# quoted: an owner's updateRule can land first (a cUSD payout exits the live
# amount, minUsdtOut is only a floor, and the bridge fills what arrives).
# So an order records the rule as it was signed, and its money may move on
# only while the executed event shows that same rule.

RULE_SETTERS = ('RuleCreated', 'RuleUpdated')


def _rule_settings(contract: str, onchain_id):
    from .models import SmartAccountEvent
    rows = SmartAccountEvent.objects.filter(address=(contract or '').lower(), name__in=RULE_SETTERS)
    return [e for e in rows.order_by('block_number', 'log_index')
            if str((e.args or {}).get('id')) == str(onchain_id)]


def rule_setting(contract: str, onchain_id) -> str:
    """The version of a rule as the mirror holds it: the RuleCreated or
    RuleUpdated it last applied ('' when it has seen none)."""
    applied = [e for e in _rule_settings(contract, onchain_id) if e.applied_at is not None]
    return f'{applied[-1].tx_hash}:{applied[-1].log_index}' if applied else ''


def setting_changed_since(rule, since) -> bool:
    """An order without a recorded version: the rule was set again after
    it was opened."""
    return any(e.applied_at is None or e.applied_at > since
               for e in _rule_settings(rule.smart_account.contract_address, rule.onchain_id)
               if e.name == 'RuleUpdated')


def execution_problem(*, rule, deposit: str, tx_hash: str, funded_units: int, amount, payout_refs,
                      setting: str | None, since=None) -> str:
    """'' when the executeRule that funded this order is the payment the
    owner signed; otherwise why not (ops read it). All from the append-only
    event log, so neither the order the mirror applied events in, nor a
    revoke after the payment, changes the answer.

    `setting` is the rule's version when the order was opened; None for an
    order made before versions were recorded (`since` is then when it was
    made). `payout_refs` None: an order whose reference is unknowable."""
    from .models import SmartAccountEvent
    try:
        if int(funded_units) > int(Decimal(str(amount)) * WAD):
            return 'amount_above_signed'
    except (InvalidOperation, TypeError, ValueError):
        return 'amount_unknown'
    contract = (rule.smart_account.contract_address or '').lower()
    seen = list(SmartAccountEvent.objects.filter(
        address=contract, name='PayoutSent', tx_hash=(tx_hash or '').lower()))
    if not seen:
        return 'event_not_found'        # the scan is behind: callers wait
    paid = [e for e in seen if str(e.args.get('id')) == str(rule.onchain_id)
            and str(e.args.get('destination') or '').lower() == (deposit or '').lower()]
    if len(paid) != 1:
        return 'event_mismatch'
    event = paid[0]
    if payout_refs is not None and str(event.args.get('payoutRef') or '').lower() not in {
            str(ref).lower() for ref in payout_refs}:
        return 'payout_ref_changed'
    position = (event.block_number, event.log_index)
    before = [e for e in _rule_settings(contract, rule.onchain_id) if (e.block_number, e.log_index) < position]
    if setting is not None:
        executed = f'{before[-1].tx_hash}:{before[-1].log_index}' if before else ''
        return '' if executed == setting else 'authorization_changed'
    if since is not None and any(e.name == 'RuleUpdated' and (e.applied_at is None or e.applied_at > since)
                                 for e in before):
        return 'authorization_changed'
    return ''


def signed_fx_floor(authorization) -> Decimal | None:
    """The lowest rate the owner signed (local currency per dollar)."""
    reference = authorization.reference_fx_rate if authorization is not None else None
    if not reference:
        return None
    return Decimal(reference) * Decimal(BPS - authorization.fx_tolerance_bps) / Decimal(BPS)


def rule_terms(rule, run, setting: str) -> dict:
    floor = signed_fx_floor(rule.standing_authorization)
    return {'run': run.pk, 'rule': str(rule.internal_id),
            'authorization': str(rule.standing_authorization.internal_id),
            'payout_ref': rule.payout_ref, 'amount': format(Decimal(rule.amount).quantize(Decimal('0.01')), 'f'),
            'fx_floor': format(floor, 'f') if floor is not None else '', 'rule_event': setting}


def _payment_identity(phone, bank_code, id_number) -> tuple:
    return str(phone or ''), str(bank_code or ''), str(id_number or '')


def ramp_run(ramp):
    """The rule run of a contract-funded VE send: the payout linked to it,
    or (an order since replaced by a fresh one) the run in its own terms."""
    from .models import SmartAccountRuleRun
    runs = SmartAccountRuleRun.objects.select_related('rule__smart_account')
    run_pk = SmartAccountPayout.objects.filter(ramp_id=ramp.pk).values_list('rule_run_id', flat=True).first()
    if run_pk is None:
        run_pk = (((ramp.metadata or {}).get('ve_send') or {}).get('funding_terms') or {}).get('run')
    return runs.filter(pk=run_pk).first() if run_pk else None


def ramp_fx_floor(ramp) -> Decimal | None:
    """The rate floor of a contract-funded VE send. One made before it was
    stored has its authorization's."""
    terms = ((ramp.metadata or {}).get('ve_send') or {}).get('funding_terms') or {}
    if 'fx_floor' in terms:
        return Decimal(terms['fx_floor']) if terms['fx_floor'] else None
    if terms.get('authorization'):
        authorization = SmartAccountStandingAuthorization.objects.filter(internal_id=terms['authorization']).first()
    else:
        run = ramp_run(ramp)
        authorization = run.rule.standing_authorization if run is not None else None
        if authorization is not None and authorization.authorized_at > ramp.created_at:
            return None     # signed after this order: not what it was made under
    return signed_fx_floor(authorization)


def ramp_owner_problem(ramp) -> str:
    """The run's own owner gate, for the person the send is made for."""
    from payment_accounts.contract_funding import owner_refusal
    from .context import personal_account
    owner = personal_account(ramp.actor_user)
    return owner_refusal(owner) if owner is not None else 'account_unavailable'


def tell_rate_held(ramp) -> None:
    from . import notifications
    run = ramp_run(ramp)
    if run is not None:
        amount = ((ramp.metadata or {}).get('ve_send') or {}).get('gross_usd')
        notifications.safe(notifications.payout_rate_held, run.pk, amount)


def ramp_may_land(ramp) -> bool:
    from . import automation
    run = ramp_run(ramp)
    return run is not None and automation.slot_may_land(run.rule, run)


def ramp_funding_problem(ramp, tx_hash: str, funded_units) -> str:
    """execution_problem for a contract-funded VE send. One made before
    terms were recorded is judged by its amount, its beneficiary's payoutRef
    and any update of the rule since it was made."""
    run = ramp_run(ramp)
    if run is None:
        return 'run_not_found'
    section = (ramp.metadata or {}).get('ve_send') or {}
    terms = section.get('funding_terms') or {}
    if terms:
        amount, refs, setting = terms.get('amount'), [terms.get('payout_ref')], terms.get('rule_event') or ''
    else:
        amount, refs, setting = section.get('gross_usd'), None, None
        if not int(section.get('beneficiary_revision') or 0):   # ops has not corrected it
            from .models import SmartAccountPagoMovilDestination
            who = section.get('beneficiary') or {}
            wanted = _payment_identity(who.get('phone'), who.get('bank_code'), who.get('cedula'))
            refs = ['0x' + pagomovil_ref_for(row).hex()
                    for row in SmartAccountPagoMovilDestination.all_objects.filter(user_id=ramp.actor_user_id)
                    if _payment_identity(row.phone, row.bank_code, row.id_number) == wanted]
    return execution_problem(rule=run.rule, deposit=section.get('deposit_address') or '', tx_hash=tx_hash,
                             funded_units=funded_units, amount=amount, payout_refs=refs, setting=setting,
                             since=ramp.created_at)


def ramp_terms_current(ramp, rule) -> bool:
    """An open VE order still is what the rule pays now."""
    section = (ramp.metadata or {}).get('ve_send') or {}
    terms = section.get('funding_terms') or {}
    authorization = rule.standing_authorization
    if terms:
        return (authorization is not None
                and terms.get('authorization') == str(authorization.internal_id)
                and str(terms.get('payout_ref') or '').lower() == (rule.payout_ref or '').lower()
                and Decimal(str(terms.get('amount'))) == rule.amount
                and (terms.get('rule_event') or '')
                == rule_setting(rule.smart_account.contract_address, rule.onchain_id))
    who, saved = section.get('beneficiary') or {}, rule.pagomovil_destination
    return (saved is not None and Decimal(str(section.get('gross_usd') or 0)) == rule.amount
            and _payment_identity(who.get('phone'), who.get('bank_code'), who.get('cedula'))
            == _payment_identity(saved.phone, saved.bank_code, saved.id_number)
            and not setting_changed_since(rule, ramp.created_at))


def follow_destination(payout, run, destination: str):
    """A slot may have had several orders, one fundable at a time. The
    event names the deposit it paid: the payout follows that order, so money
    for a closed one lands in its review and never in another's."""
    if not destination or (payout.deposit_address or '').lower() == destination:
        return payout
    values = None
    if payout.journey_id is not None:
        from payment_accounts.models import InfiniaJourney
        journey = InfiniaJourney.objects.filter(
            bridge__funding_mode='contract', bridge__deposit_address__iexact=destination,
            bridge__quote__money_flow__metadata__contract_funding__run=run.pk).order_by('-pk').first()
        if journey is not None:
            values = {'journey': journey}
    elif payout.ramp_id is not None:
        from ramps.models import RampTransaction
        ramp = RampTransaction.objects.filter(
            metadata__ve_send__funding_terms__run=run.pk,
            metadata__ve_send__deposit_address=destination).order_by('-pk').first()
        if ramp is not None:
            values = {'ramp': ramp}
    if values is None:
        return payout
    SmartAccountPayout.objects.filter(pk=payout.pk).update(
        deposit_address=destination, updated_at=timezone.now(), **values)
    return SmartAccountPayout.objects.select_related('rule_run').get(pk=payout.pk)


def lock_sendable(rule, run, calldata: str) -> bool:
    """Inside the relayer's claim (account and run locked): the order this
    call would fund is the slot's, still open and still what the rule pays.
    Locks the order, so closing it and recording the send exclude each other."""
    from eth_abi import decode as abi_decode
    from . import abi
    _name, args = abi.decode_call(calldata)
    deposit, units = abi_decode(['address', 'uint256'], bytes(args[1])[:64])
    payout = SmartAccountPayout.objects.filter(rule_run=run).first()
    if payout is None or payout.status not in UNSENT or (payout.deposit_address or '').lower() != deposit.lower():
        return False
    if payout.journey_id is not None:
        from payment_accounts import contract_funding
        bridge = payout.journey.bridge
        if bridge is None:
            return False
        bound = (bridge.quote.money_flow.metadata or {}).get(contract_funding.KEY) or {}
        authorization = rule.standing_authorization
        return (authorization is not None
                and str(bridge.quote.amount_units) == str(units)
                and bound.get('authorization') == str(authorization.internal_id)
                and bound.get('rule_event')
                == rule_setting(rule.smart_account.contract_address, rule.onchain_id)
                and contract_funding.lock_fundable(bridge.pk))
    if payout.ramp_id is not None:
        from ramps import ve_send
        ramp = ve_send.lock_fundable(payout.ramp_id, deposit, units)
        return ramp is not None and ramp_terms_current(ramp, rule)
    return True


@dataclass
class PayoutPlan:
    deposit_address: str
    min_usdt_out: int
    journey: object = None
    bridge_cost_bps: int = 0
    fx_rate: Decimal | None = None
    fiat_currency: str = ''
    provider: str = INFINIA
    ramp: object = None
    # Pago ASAP: the quote the order is reserved with (ramps estimate).
    estimate: dict | None = None
    # cUSD+ rule: the cUSD the account redeems after its fee-free unwrap
    # (executeRule's grossCusd); min_usdt_out is then the EXACT usdtOut.
    gross_wei: int | None = None


# ── The exit a payout run makes (ConfioSmartAccount._runPayout) ─────────
#
# cUSD rule:  data = abi.encode(destination, minUsdtOut); redeemWithFee(amount)
#             pays previewRedeem(amount).net, minUsdtOut is a floor.
# cUSD+ rule: data = abi.encode(destination, usdtOut, grossCusd). The account
#             unwraps ceil((gross + gross*5/10000) / pPlus) shares (capped at
#             the run's share limit) to cUSD, fee-free, then redeemWithFee(gross)
#             with usdtOut EXACT: gross - CusdVault.feeFor(gross). One wei under
#             and the account refuses, one over and the vault does. The unwrap
#             margin stays in the account as cUSD dust (decision 17 exception).

# ConfioSmartAccount.PAYOUT_UNWRAP_MARGIN_BPS.
PAYOUT_UNWRAP_MARGIN_BPS = 5
# The USDT a cUSD+ payout sends is floored to six decimals, the step ramps'
# own VE sends use (ramps.ve_send.confio_amounts).
USDT_STEP_WEI = 10 ** 12
EXIT_UNAVAILABLE = 'No pudimos preparar este pago. Lo intentaremos en la próxima fecha.'


@dataclass(frozen=True)
class PayoutExit:
    usdt_wei: int                 # cUSD: previewRedeem(amount).net; cUSD+: the exact usdtOut
    gross_wei: int | None = None  # cUSD+ only: grossCusd


def fee_for_wei(gross: int, fee_bps: int) -> int:
    """CusdVault.feeFor: mulDiv(gross, feeBps, BPS, Ceil), 0 for 0."""
    gross, fee_bps = int(gross), int(fee_bps)
    if gross <= 0 or fee_bps <= 0:
        return 0
    return -(-gross * fee_bps // BPS)


def net_for_gross(gross: int, fee_bps: int) -> int:
    """CusdVault.previewRedeem(gross).netUsdt."""
    return int(gross) - fee_for_wei(gross, fee_bps)


def gross_for_net(target: int, fee_bps: int) -> int:
    """The smallest gross whose previewRedeem net is exactly `target`.
    net(g + 1) - net(g) is 0 or 1 (the ceiling fee grows by at most one wei
    per wei of gross while fee_bps < BPS), so every positive target is hit
    exactly; a binary search over the non-decreasing net finds it."""
    target, fee_bps = int(target), int(fee_bps)
    if target <= 0 or not 0 <= fee_bps < BPS:
        raise ValueError('bad target or fee')
    lo, hi = target, (target + 1) * BPS // (BPS - fee_bps) + 2
    assert net_for_gross(hi, fee_bps) >= target
    while lo < hi:
        mid = (lo + hi) // 2
        if net_for_gross(mid, fee_bps) >= target:
            hi = mid
        else:
            lo = mid + 1
    if net_for_gross(lo, fee_bps) != target:   # unreachable by the step argument
        raise ValueError('net not reachable')
    return lo


def _unwrap_basis(gross: int) -> int:
    """The dollars the account converts to shares for a cUSD+ payout."""
    return gross + gross * PAYOUT_UNWRAP_MARGIN_BPS // BPS


def plus_gross_cap(amount_wei: int, window: tuple[int, int]) -> int:
    """The largest grossCusd a cUSD+ payout of `amount_wei` may redeem: the
    unwrap basis (gross plus the contract's 5 bps margin, floored as the
    contract does) stays within the rule's dollar amount. executeRule's
    share limit and _runPayout's unwrap are both ceil(usd / pPlus) at the
    SAME post-accrual pPlus inside one call, so basis <= amountUsd keeps the
    unwrap within the limit wherever in the pPlus window the call is mined:
    it is never capped, and the full margin covers Ondo's redemption
    rounding. Checked at both ends of the window (fail closed)."""
    from .quotes import QuoteUnavailable, shares_ceil
    amount_wei = int(amount_wei)
    gross = amount_wei * BPS // (BPS + PAYOUT_UNWRAP_MARGIN_BPS)
    while _unwrap_basis(gross + 1) <= amount_wei:
        gross += 1
    while gross > 0 and _unwrap_basis(gross) > amount_wei:
        gross -= 1
    basis = _unwrap_basis(gross)
    for p in window:
        if shares_ceil(basis, p) > shares_ceil(amount_wei, p):   # unreachable while basis <= amount
            raise QuoteUnavailable('payout_share_limit', retry_later=True)
    return gross


def plus_payout_exit(amount_wei: int, fee_bps: int, window: tuple[int, int],
                     target: int | None = None) -> PayoutExit:
    """(usdtOut, grossCusd) for a cUSD+ payout: by default the cap's net
    floored to six decimals, then the smallest gross that nets exactly that.
    `target` pins the USDT (a retry of an order already reserved for it)."""
    cap = plus_gross_cap(amount_wei, window)
    if target is None:
        target = net_for_gross(cap, fee_bps) // USDT_STEP_WEI * USDT_STEP_WEI
    if target <= 0:
        raise PayoutSkip('amount_too_small', 'El monto es muy bajo para este pago.')
    gross = gross_for_net(target, fee_bps)
    if gross > cap:
        raise PayoutSkip('exit_moved', EXIT_UNAVAILABLE)
    return PayoutExit(usdt_wei=int(target), gross_wei=int(gross))


def rule_is_plus(rule) -> bool:
    from . import chain
    plus = (chain.cusd_plus_address() or '').lower()
    return bool(plus) and (rule.token_in or '').lower() == plus


def payout_exit(rule, *, window: tuple[int, int] | None = None, target: int | None = None,
                unavailable: str = EXIT_UNAVAILABLE) -> PayoutExit:
    """The USDT this rule's run sends, from the vault's own arithmetic.
    cUSD: previewRedeem(amountUsd).net (the contract's limit is amountUsd).
    cUSD+: plus_payout_exit, checked against the vault's previewRedeem.
    Raises PayoutSkip; QuoteUnavailable (the pPlus window) propagates."""
    from cusd_plus import cusd_vault
    from . import chain, quotes
    amount_wei = int(rule.amount * WAD)
    if rule_is_plus(rule):
        window = window or quotes.plus_price_window()
        try:
            fee_bps = int(chain.conversion_fee_bps())
            exit_ = plus_payout_exit(amount_wei, fee_bps, window, target)
            preview = cusd_vault.preview_redeem_wei(exit_.gross_wei)
        except PayoutSkip:
            raise
        except Exception as exc:  # noqa: BLE001 — fail closed
            logger.warning('cUSD+ exit sizing failed for rule %s', rule.pk, exc_info=True)
            raise PayoutSkip('provider_unavailable', unavailable) from exc
        if int(preview.net_wei) != exit_.usdt_wei:
            # The fee moved between the two reads: never send a usdtOut the
            # vault would not pay exactly.
            logger.warning('cUSD+ exit preview mismatch for rule %s', rule.pk)
            raise PayoutSkip('provider_unavailable', unavailable)
        return exit_
    cusd = (chain.cusd_address() or '').lower()
    if not cusd or (rule.token_in or '').lower() != cusd:
        raise PayoutSkip('dollar_not_supported', 'Esta regla usa un dólar que no reconocemos. Crea la regla de nuevo.')
    try:
        exact = int(cusd_vault.preview_redeem_wei(amount_wei).net_wei)
    except Exception as exc:  # noqa: BLE001 — fail closed
        logger.warning('cUSD exit preview failed for rule %s', rule.pk, exc_info=True)
        raise PayoutSkip('provider_unavailable', unavailable) from exc
    if exact <= 0:
        raise PayoutSkip('amount_too_small', 'El monto es muy bajo para este pago.')
    return PayoutExit(usdt_wei=exact)


def exit_or_wait(rule, *, window: tuple[int, int] | None = None, target: int | None = None) -> PayoutExit:
    """payout_exit for a run, where an unreadable vault is a wait:
    one RPC failure must not lose a monthly payment."""
    try:
        return payout_exit(rule, window=window, target=target)
    except PayoutSkip as exc:
        if exc.code == 'provider_unavailable':
            raise PayoutSkip(exc.code, exc.message, retry_later=True, wait=True) from exc
        raise


class ProviderAdapter:
    """The provider side of one run. This base is the adapter of a rail that
    has none (Bre-B, CVU, QR): it refuses, and rail_ready never offers one."""

    def open(self, rule, run, usdt_estimate: int, exit_: PayoutExit | None = None,
             window: tuple[int, int] | None = None) -> PayoutPlan:
        """For a cUSD+ rule `exit_` is the exact exit (usdt_estimate is its
        usdt_wei): the plan's min_usdt_out must be exactly it."""
        raise PayoutSkip('provider_path_unverified',
                         'Este pago automático todavía no está habilitado para tu tipo de cuenta.')

    def after_onchain(self, payout, tx_hash: str) -> None:
        """PayoutSent was mirrored for this payout (reconcile._payout_sent)."""
        return None


class InfiniaAdapter(ProviderAdapter):
    """CLABE and Pix keys (smart_account.infinia_payouts): one run = one
    bridge = one Infinia journey, funded by the account contract and
    authorized by the rule's standing authorization alone."""

    def open(self, rule, run, usdt_estimate: int, exit_: PayoutExit | None = None,
             window: tuple[int, int] | None = None) -> PayoutPlan:
        from . import infinia_payouts
        if rule.payout_rail not in INFINIA_RAILS:
            return super().open(rule, run, usdt_estimate, exit_=exit_, window=window)
        return infinia_payouts.open_run(rule, run, exit_=exit_, window=window)

    def after_onchain(self, payout, tx_hash: str) -> None:
        from . import infinia_payouts
        infinia_payouts.after_onchain(payout, tx_hash)


# ── Pago ASAP (Venezuelan Pago Móvil) ───────────────────────────────────

VE_UNAVAILABLE = 'Los pagos por Pago Móvil no están disponibles por ahora. Lo intentaremos en la próxima fecha.'
# The bridge quote must outlive the relayer transaction comfortably.
MIN_TARGET_LIFETIME = timedelta(minutes=3)


def signed_holder_name(rule, destination) -> str:
    """The name a Pago Móvil order records and shows for its beneficiary
    (Pago ASAP is paid by phone, cédula and bank only). The same beneficiary
    saved again under another name is the same row, so a rename must never
    reach an already signed rule's orders: the name the authorization was
    signed with (holder_name); for one signed before it was kept, the name
    the first order under it carried (the saved name for that first one)."""
    from ramps import ve_send
    authorization = rule.standing_authorization
    if authorization is not None and authorization.holder_name:
        return authorization.holder_name
    earlier = SmartAccountPayout.objects.filter(rule_run__rule=rule, ramp__isnull=False)
    if authorization is not None:
        earlier = earlier.filter(created_at__gte=authorization.authorized_at)
    for metadata in earlier.order_by('pk').values_list('ramp__metadata', flat=True)[:1]:
        name = (((metadata or {}).get(ve_send.SECTION) or {}).get('beneficiary') or {}).get('name')
        if name:
            return name
    return destination.holder_name


class PagoAsapAdapter(ProviderAdapter):
    """One Pago Móvil payout = one ramps VE send (ramps.ve_send, provider
    'pagoasap') whose sender of record is the account OWNER (actor_user,
    KYC as for any send) and whose funding wallet is the account CONTRACT
    (actor_address: a bridge refund returns there, and the USDT conversion
    turns it back into the owner's dollar).

    Money path (BSC -> Polygon -> Pago ASAP -> bank):
      executeRule -> contract._runPayout -> CusdVault.redeemWithFee(amount,
      exactNet, relayDepositAddress): the vault sends exactly `exactNet`
      USDT (BSC) to the per-order Relay deposit address; Relay bridges it
      to native USDC on Polygon at Confío's Pago ASAP address
      (PAGOASAP_DEPOSIT_ADDRESS_POLYGON); ramps proves the funding on BSC
      and the delivery on Polygon, then pays the beneficiary by Pago Móvil
      in bolívares at Pago ASAP's rate and polls it to completion.

    Both dollars exit exactly: cUSD through previewRedeem(amount), cUSD+
    through the fee-free unwrapToCusd then redeemWithFee(grossCusd) with an
    exact usdtOut (payout_exit). The order's deposit amount is that USDT."""

    def open(self, rule, run, usdt_estimate: int, exit_: PayoutExit | None = None,
             window: tuple[int, int] | None = None) -> PayoutPlan:
        from payment_accounts import contract_funding
        from ramps import ve_pagomovil
        if not ramps_contract_funding_ready():
            raise PayoutSkip('provider_path_unverified', VE_UNAVAILABLE)
        if not ve_pagomovil.enabled(ve_pagomovil.SEND):
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE, wait=True)
        try:
            contract_funding.require_owner(rule.smart_account.owner_account)
        except contract_funding.Refused as exc:
            # A hold that may be lifted waits inside the slot; a minor is final.
            raise PayoutSkip(exc.code, 'Los pagos por Pago Móvil están disponibles para mayores de 18 años.'
                             if exc.code == 'minor' else exc.message, wait=exc.retry) from exc
        existing = SmartAccountPayout.objects.filter(rule_run=run).first()
        replaces = existing if existing is not None and existing.ramp_id is not None else None
        try:
            if replaces is not None:
                plan = self._resume(rule, run, replaces, window)
                if plan is not None:
                    return plan
                exit_ = None    # the closed order's
            exit_ = exit_ or payout_exit(rule, window=window, unavailable=VE_UNAVAILABLE)
            plan = self._price(rule, exit_)
            # Outside the rule's own limits: skipped before anything is reserved.
            check_rule_limits(rule.standing_authorization, plan)
            self._check_payable(rule.standing_authorization, plan.estimate, plan.fx_rate)
            ramp, payout = self._reserve(rule, run, exit_, plan, replaces)
            return self._claim_target(rule, payout, ramp, plan)
        except PayoutSkip as exc:
            if exc.code == 'provider_unavailable':
                # A hiccup, a switch or a missing key never loses the payment:
                # asked again inside the slot.
                raise PayoutSkip(exc.code, exc.message, retry_later=True, wait=True) from exc
            raise

    # -- steps --

    def _price(self, rule, exit_: PayoutExit) -> PayoutPlan:
        """Today's Pago ASAP quote (rate, bolívares, bridge estimate): the
        cost the bridge and deposit take, and the rate, for the rule's
        limits. Any provider error is a skip, never a guess."""
        from ramps import pagoasap_send
        from ramps.ve_pagomovil import VePagoMovilError
        try:
            estimate = pagoasap_send.quote(rule.amount)
            rate = Decimal(str(estimate['rate']))
            ves = Decimal(str(estimate['estimated_ves']))
            usdt = Decimal(str(estimate['usdt_amount']))
        except VePagoMovilError as exc:
            # An amount too small stays too small: final, not a wait.
            code = 'amount_too_small' if 'muy pequeño' in str(exc) else 'provider_unavailable'
            raise PayoutSkip(code, str(exc) or VE_UNAVAILABLE) from exc
        except Exception as exc:  # noqa: BLE001 — provider down or malformed
            logger.warning('Pago ASAP quote failed for rule %s', rule.pk, exc_info=True)
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE) from exc
        if not rate.is_finite() or rate <= 0 or usdt <= 0 or ves <= 0:
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE)
        delivered = ves / rate      # dollars Pago ASAP pays out after bridge and deposit fee
        cost_bps = int(((usdt - delivered) / usdt * BPS).to_integral_value(rounding=ROUND_UP))
        return PayoutPlan(deposit_address='', min_usdt_out=exit_.usdt_wei, bridge_cost_bps=max(cost_bps, 0),
                          fx_rate=rate, fiat_currency='VES', provider=PAGOASAP,
                          estimate={k: str(v) for k, v in estimate.items()}, gross_wei=exit_.gross_wei)

    def _check_payable(self, authorization, estimate, rate: Decimal) -> None:
        """The floor as settlement applies it (pagoasap_send.payout_terms):
        the provider's payout cost counts, so it counts before funding too."""
        from ramps import pagoasap_send
        floor = signed_fx_floor(authorization)
        if floor is None:
            raise PayoutSkip(FLOOR_UNSIGNED, FLOOR_UNSIGNED_MESSAGE)
        try:
            usd = Decimal(str(estimate['estimated_ves'])) / Decimal(str(estimate['rate']))
            payable = pagoasap_send.pays_at_floor(usd, rate, floor)
        except Exception as exc:  # noqa: BLE001 — unknown is never inside the floor
            logger.warning('Pago ASAP payout preview failed', exc_info=True)
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE, wait=True) from exc
        if not payable:
            # Today's rate, not the month's: asked again inside the slot.
            raise PayoutSkip('fx_rate_below_limit', 'La tasa de hoy, con el costo del pago, está por debajo del '
                                                    'límite de tu regla. Lo intentaremos de nuevo.', retry_later=True)

    def _reserve(self, rule, run, exit_: PayoutExit, plan: PayoutPlan, replaces=None):
        """The VE send for the owner, persisted with the payout row in one
        transaction (no order without its payout, no payout without its
        order). Per-user and global limits are ramps' own (check_limits,
        re-run under its reservation lock)."""
        from ramps import ve_send
        from ramps.ve_pagomovil import VePagoMovilError
        from .models import SmartAccountRule
        account = rule.smart_account
        owner = account.owner_user
        destination = rule.pagomovil_destination
        # The version first, the rule after it: an update between the two reads refuses.
        setting = rule_setting(account.contract_address, rule.onchain_id)
        fresh = SmartAccountRule.objects.filter(pk=rule.pk).first()
        if (fresh is None or (fresh.standing_authorization_id, fresh.payout_ref, fresh.amount)
                != (rule.standing_authorization_id, rule.payout_ref, rule.amount)):
            raise PayoutSkip('authorization_changed', RULE_CHANGED, retry_later=True, wait=True)
        terms = dict(rule_terms(rule, run, setting), attempt=1,
                     # Who may sign a refund Relay could not send (RecoverableRelay).
                     recovery=(account.owner_account.bsc_address or '').lower())
        if replaces is not None:
            previous = ((replaces.ramp.metadata or {}).get(ve_send.SECTION) or {}).get('funding_terms') or {}
            terms.update(attempt=int(previous.get('attempt') or 1) + 1, replaces=str(replaces.ramp.internal_id))
        try:
            ve_send.check_limits(owner, rule.amount, PAGOASAP)
        except VePagoMovilError as exc:
            raise _limit_skip(exc) from exc
        block = ve_send.current_block()
        if block is None or account.account_id is None:
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE)
        from . import chain
        beneficiary = {'cedula': destination.id_number, 'phone': destination.phone,
                       'bank_code': destination.bank_code, 'name': signed_holder_name(rule, destination)}
        try:
            with transaction.atomic():
                payout, _ = SmartAccountPayout.objects.select_for_update().get_or_create(
                    rule_run=run, defaults={'rail': rule.payout_rail, 'provider': PAGOASAP,
                                            'fiat_currency': 'VES', 'status': 'reserving'})
                if payout.ramp_id is not None and (
                        replaces is None or payout.ramp_id != replaces.ramp_id or payout.status != 'cancelled'):
                    raise _AlreadyReserved(payout)
                ramp = ve_send.reserve(
                    provider=PAGOASAP, user=owner, account=account.account, gross_usd=rule.amount,
                    beneficiary=beneficiary,
                    gross_wei=exit_.gross_wei if exit_.gross_wei is not None else int(rule.amount * WAD),
                    deposit_wei=exit_.usdt_wei,
                    created_block=block, estimate=plan.estimate,
                    funding_sender=(chain.cusd_address() or '').lower(), funding_terms=terms)
                ramp = ve_send.prepare(ramp)
                now = timezone.now()
                values = {'ramp': ramp, 'updated_at': now}
                if replaces is not None:
                    values.update(status='reserving', deposit_address='', created_at=now)
                SmartAccountPayout.objects.filter(pk=payout.pk).update(**values)
                if replaces is not None:
                    ve_send.hide_replaced(replaces.ramp_id)
                for name, value in values.items():
                    setattr(payout, name, value)
        except _AlreadyReserved as already:
            raise PayoutSkip('payout_in_progress', IN_PROGRESS, retry_later=True, wait=True) from already
        except ve_send.VeSendLimitError as exc:
            # The same limit as the pre-check, re-run under ramps' lock:
            # decided exactly like it (_limit_skip).
            raise _limit_skip(exc) from exc
        except VePagoMovilError as exc:
            # Refused before anything was reserved (a limit reached since the
            # pre-check, an identical payout still open, a changed wallet):
            # passing, so the slot waits instead of being skipped for good.
            raise PayoutSkip('send_refused', str(exc) or VE_UNAVAILABLE, wait=True) from exc
        return ramp, payout

    def _claim_target(self, rule, payout, ramp, plan: PayoutPlan) -> PayoutPlan:
        """The single funding claim: the bridge deposit address for exactly
        the USDT the contract exits. A failure closes the order (nothing can
        have been paid: the address never left the server)."""
        from ramps import ve_send
        from ramps.ve_pagomovil import VePagoMovilError
        try:
            ramp = ve_send.start_funding(ramp, by_payout=True)
        except Exception as exc:  # noqa: BLE001 — closed, never left half-open
            try:
                closed = ve_send.fail_unfunded(ramp, 'deposit_target_unavailable')
            except Exception:  # noqa: BLE001 — expires on its own (FUNDING_WINDOW)
                logger.exception('Could not close VE send %s', ramp.pk)
                closed = None
            if closed is not None and closed.status != 'FAILED':
                # Another worker claimed it first: that order is the slot's.
                raise PayoutSkip('payout_in_progress', IN_PROGRESS, retry_later=True, wait=True) from exc
            SmartAccountPayout.objects.filter(pk=payout.pk, ramp_id=ramp.pk, status__in=UNSENT).update(
                status='cancelled', updated_at=timezone.now())
            if not isinstance(exc, VePagoMovilError):
                logger.warning('Funding target failed for rule %s', rule.pk, exc_info=True)
            refused = str(exc) if isinstance(exc, VePagoMovilError) else ''
            raise PayoutSkip('amount_too_small' if 'muy pequeño' in refused else 'provider_unavailable',
                             refused or VE_UNAVAILABLE) from exc
        return self._plan_for(rule, payout, ramp, plan)

    def _plan_for(self, rule, payout, ramp, plan: PayoutPlan) -> PayoutPlan:
        from ramps import pagoasap_send, ve_send
        details = ve_send.funding_details(ramp)
        exact = plan.min_usdt_out
        if (not details or str(details.get('deposit_amount_wei')) != str(exact)
                or str(details.get('network')) != 'BSC'):
            # ramps would wait for a different amount than the contract
            # sends: never pay it. The order expires unfunded on its own.
            logger.error('VE send %s funding target does not match the exit (%s)', ramp.pk, details)
            _cancel_order(payout, ramp)
            raise PayoutSkip('provider_path_unverified', VE_UNAVAILABLE)
        expires_at = details.get('expires_at')
        if expires_at and int(expires_at) < int((timezone.now() + MIN_TARGET_LIFETIME).timestamp()):
            _cancel_order(payout, ramp, quiet=True)
            # Relay's deadline, not the payment's: a fresh route is asked for.
            raise PayoutSkip('provider_quote_expired', 'No se pudo enviar todavía. Lo intentaremos de nuevo.',
                             wait=True)
        # The signed cost limit, on the route that gets the money: the
        # estimate it was reserved with is another quote.
        route = ((ramp.metadata or {}).get(ve_send.SECTION) or {}).get('bridge') or {}
        try:
            plan.bridge_cost_bps = pagoasap_send.route_cost_bps(exact, route.get('amount_out'))
        except (TypeError, ValueError, ArithmeticError) as exc:
            _cancel_order(payout, ramp, quiet=True)
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE, wait=True) from exc
        try:
            check_rule_limits(rule.standing_authorization, plan)
        except PayoutSkip:
            _cancel_order(payout, ramp, quiet=True)
            raise
        deposit = str(details['deposit_address']).lower()
        if not SmartAccountPayout.objects.filter(pk=payout.pk, ramp_id=ramp.pk, status__in=UNSENT).update(
                deposit_address=deposit, status='prepared', updated_at=timezone.now()):
            # Sent, closed or replaced by another worker meanwhile.
            raise PayoutSkip('payout_in_progress', IN_PROGRESS, retry_later=True, wait=True)
        plan.deposit_address, plan.ramp = deposit, ramp
        return plan

    def _resume(self, rule, run, payout, window: tuple[int, int] | None = None) -> PayoutPlan | None:
        """A retry of the same slot (the relayer call failed or reverted):
        pay the SAME order and address while its quote lives and it still is
        what the rule pays. A cUSD+ retry pins the USDT the order was
        reserved for and re-derives the gross that nets exactly it.

        None: the order is closed, unfunded and unfundable, and the slot may
        get a fresh one. Never two fundable orders at once."""
        from ramps import ve_send
        from ramps.models import RampTransaction
        from . import automation
        busy = PayoutSkip('payout_in_progress', IN_PROGRESS, retry_later=True, wait=True)
        if payout.status not in UNSENT + ('cancelled',) or automation.slot_may_land(rule, run):
            raise busy
        ramp = RampTransaction.objects.get(pk=payout.ramp_id)
        payout.ramp = ramp
        section = (ramp.metadata or {}).get(ve_send.SECTION) or {}
        if section.get('funding_tx_hash') or section.get('funding_tx_hashes'):
            raise busy
        phase = section.get('phase') if ramp.status == 'PENDING' and payout.status in UNSENT else None
        fundable = phase in ('awaiting_funding', 'funding_reported') and ramp_terms_current(ramp, rule)
        deadline = (section.get('bridge') or {}).get('deadline')
        if phase == 'funding_reported' and deadline:
            fundable = fundable and int(deadline) >= int((timezone.now() + MIN_TARGET_LIFETIME).timestamp())
        elif phase == 'awaiting_funding':
            fundable = fundable and ve_send.can_fund(ramp)
        if fundable:
            try:
                deposit = int(section.get('deposit_wei'))
            except (TypeError, ValueError):
                deposit = 0
            try:
                if deposit <= 0:
                    raise PayoutSkip('exit_moved', EXIT_UNAVAILABLE)
                exit_ = payout_exit(rule, window=window, target=deposit if rule_is_plus(rule) else None,
                                    unavailable=VE_UNAVAILABLE)
                if exit_.usdt_wei != deposit:
                    raise PayoutSkip('exit_moved', EXIT_UNAVAILABLE)
            except PayoutSkip as exc:
                if exc.code != 'exit_moved':
                    raise
            else:
                try:
                    rate = reference_ves_rate()     # today's: the order's quote is not it
                except Exception as exc:  # noqa: BLE001 — unknown is never inside the floor
                    logger.warning('Pago ASAP rate unavailable for a retry of rule %s', rule.pk, exc_info=True)
                    raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE, wait=True) from exc
                plan = PayoutPlan(deposit_address='', min_usdt_out=exit_.usdt_wei, provider=PAGOASAP,
                                  fx_rate=rate, fiat_currency='VES', gross_wei=exit_.gross_wei)
                check_rule_limits(rule.standing_authorization, plan)
                self._check_payable(rule.standing_authorization, section.get('estimate'), rate)
                if phase == 'awaiting_funding':
                    return self._claim_target(rule, payout, ramp, plan)
                return self._plan_for(rule, payout, ramp, plan)
        if not _cancel_order(payout, ramp, quiet=True):
            raise busy
        payout.status = 'cancelled'
        check_fresh_order(run, (section.get('funding_terms') or {}).get('attempt'), ramp.created_at)
        return None

    def after_onchain(self, payout, tx_hash: str) -> None:
        """PayoutSent is final: tell ramps where the funding is and let its
        own reconciliation prove it on chain (and from there settle, pay and
        poll). A failure here only delays it: the payout mirror reports the
        run's hash again (a contract-funded send is never found by a scan)."""
        from ramps import ve_send
        from ramps.models import RampTransaction
        ramp = RampTransaction.objects.get(pk=payout.ramp_id)
        try:
            ramp = ve_send.report_funding(ramp, tx_hash, by_payout=True)
        except Exception:  # noqa: BLE001
            logger.exception('report_funding failed for VE send %s', ramp.pk)
        try:
            ve_send.sync(ramp)
        except Exception:  # noqa: BLE001 — the ramps poller retries within a minute
            logger.warning('Immediate funding check failed for VE send %s', ramp.pk, exc_info=True)
        mirror_ramp_payout(payout.pk)


def _close_ramp(ramp, *, quiet: bool = False) -> bool:
    """Close a contract-funded VE send no executeRule was broadcast for
    (ve_send.close_unsent refuses one with a reported hash, and one whose
    executeRule may land). Whether it is closed."""
    from ramps import ve_send
    try:
        return ve_send.close_unsent(ramp, quiet=quiet).status == 'FAILED'
    except Exception:  # noqa: BLE001 — ramps' own expiry closes it later
        logger.exception('Could not close VE send %s', getattr(ramp, 'pk', None))
        return False


def _cancel_order(payout, ramp, *, quiet: bool = False) -> bool:
    if not _close_ramp(ramp, quiet=quiet):
        return False
    SmartAccountPayout.objects.filter(pk=payout.pk, ramp_id=ramp.pk, status__in=UNSENT).update(
        status='cancelled', updated_at=timezone.now())
    return True


def check_fresh_order(run, attempt, made_at) -> None:
    """The slot's order is closed: whether it may have a fresh one now."""
    from . import automation
    now = timezone.now()
    if now > automation.retry_deadline(automation._code(run.error), run.rule.frequency, run.scheduled_for):
        raise PayoutSkip('provider_quote_expired', automation.NOT_PAID, retry_later=True)
    if int(attempt or 1) >= FAST_ATTEMPTS and made_at > now - SLOW_RETRY:
        raise PayoutSkip('retry_spaced', 'No se pudo enviar todavía. Lo intentaremos de nuevo.', wait=True)


def close_superseded_orders(rule_pk) -> None:
    """An update moved the rule to a new slot: an unsent order of the old one
    can never be sent, so it stops holding the owner's accounts now. Closing
    still refuses one whose call may land."""
    from .models import SmartAccountRule
    rule = SmartAccountRule.all_objects.filter(pk=rule_pk).first()
    if rule is None or rule.kind != 'payout':
        return
    for payout in (SmartAccountPayout.objects.filter(rule_run__rule=rule, status__in=UNSENT)
                   .exclude(rule_run__status__in=('sent', 'ok')).select_related('rule_run')):
        if payout.rule_run.scheduled_for != rule.scheduled_for:
            close_unsent_order(payout.rule_run, quiet=True)


def close_unsent_order(run, *, quiet: bool = False) -> bool:
    """The payout run ended for good without its executeRule on the wire:
    close that run's own order now so it never lingers. The caller has
    checked that no relayer transaction for the slot may still land."""
    funded_by_journey = SmartAccountPayout.objects.filter(rule_run=run, journey__isnull=False).select_related(
        'journey').first()
    if funded_by_journey is not None:
        from . import infinia_payouts
        return infinia_payouts.close_unsent(funded_by_journey)
    payout = SmartAccountPayout.objects.filter(rule_run=run, ramp__isnull=False).select_related('ramp').first()
    if payout is None or payout.status not in UNSENT + ('cancelled',):
        return False
    return _cancel_order(payout, payout.ramp, quiet=quiet)


class _AlreadyReserved(Exception):
    def __init__(self, payout):
        self.payout = payout
        super().__init__('already reserved')


ADAPTERS = {INFINIA: InfiniaAdapter, PAGOASAP: PagoAsapAdapter}


def adapter(rail: str = '') -> ProviderAdapter:
    return ADAPTERS[adapter_name(rail)]() if has_adapter(rail) else ProviderAdapter()


def refresh_holder(rule, run) -> None:
    """Before an Infinia run is judged: what a manual send does when it
    reuses a saved recipient whose holder check is old. A check with no
    answer yet waits; another holder is another payee (authorization_problem).

    By what the slot's money is doing:
    - no order, or one nothing was broadcast for: asked again. The same
      holder resumes that order; another, or a rejection, closes it empty;
    - a call that may land, or money seen out: not asked, judged or closed
      here (plan_run waits). contract_funding.payee_problem asks before that
      money converts or pays.
    With the lookup off there is nothing to ask and nothing is written."""
    from payment_accounts import local_money
    destination = rule.payout_method
    if (rule.payout_rail not in INFINIA_RAILS or destination is None or rule.standing_authorization is None
            or rule.standing_authorization.revoked_at is not None or not _lookup_on()):
        return
    validation = (destination.provider_data or {}).get('validation') or {}
    if local_money.checked_recently(validation) and local_money.verification_state(validation) == local_money.VERIFIED:
        return
    checked = _ask_bank(destination)
    if checked is None:
        raise PayoutSkip('holder_check_pending', 'No pudimos revisar a quien recibe. Lo intentaremos de nuevo.',
                         wait=True)
    rule.payout_method = checked
    validation = (checked.provider_data or {}).get('validation') or {}
    if validation.get('status') in ('TEMPORARY_FAILURE', 'IN_PROGRESS'):
        raise PayoutSkip('holder_check_pending', 'Estamos revisando a quien recibe con el banco.', wait=True)


def check_rule_limits(authorization, plan: PayoutPlan) -> None:
    """The rule's own limits, stored with its Face authorization: the most
    the bridge may cost, and the least FX rate it accepts. An Infinia
    rail's fixed fee has its own signed ceiling
    (payment_accounts.contract_funding.require_signed_fee). Today's cost or
    rate, not the month's: the slot is asked again (retry_deadline)."""
    if plan.bridge_cost_bps > authorization.max_bridge_cost_bps:
        raise PayoutSkip('bridge_cost_above_limit',
                         'El costo de envío de hoy supera el límite de tu regla. Lo intentaremos de nuevo.',
                         retry_later=True)
    floor = signed_fx_floor(authorization)
    if floor is not None and plan.fx_rate is not None:
        if plan.fx_rate < floor:
            raise PayoutSkip('fx_rate_below_limit',
                             'La tasa de hoy está por debajo del límite de tu regla. Lo intentaremos de nuevo.',
                             retry_later=True)


def plan_run(rule, run, usdt_estimate: int, window: tuple[int, int] | None = None) -> PayoutPlan:
    """Everything that must hold before executeRule is sent for a payout.
    Raises PayoutSkip (run skipped and notified, never forced). A cUSD+
    rule's plan carries gross_wei and an exact min_usdt_out, whatever the
    adapter (executeRule's three-word data)."""
    from . import offer
    if not offer.payout_rails() or not rail_ready(rule.payout_rail):
        # A switch or a key comes back: a wait inside the slot, never its loss.
        raise PayoutSkip('payouts_disabled', 'Los pagos automáticos a cuentas bancarias están en pausa.', wait=True)
    if run is not None:
        from . import automation
        if automation.slot_may_land(rule, run) or automation._left_the_account(run):
            # Money may be out: this pass asks, judges and closes nothing.
            raise PayoutSkip('payout_in_progress', IN_PROGRESS, retry_later=True, wait=True)
    refresh_holder(rule, run)
    problem = authorization_problem(rule)
    if problem:
        raise PayoutSkip(problem, authorization_message(problem), wait=problem == 'rail_not_available',
                         deactivate=problem if problem in DEACTIVATING else '')
    exit_ = None
    if rule_is_plus(rule):
        from . import quotes
        window = window or quotes.plus_price_window()
        existing = SmartAccountPayout.objects.filter(rule_run=run).first() if run is not None else None
        if existing is None or (existing.ramp_id is None and existing.journey_id is None):
            exit_ = exit_or_wait(rule, window=window)
            usdt_estimate = exit_.usdt_wei
    plan = adapter(rule.payout_rail).open(rule, run, usdt_estimate, exit_=exit_, window=window)
    if rule_is_plus(rule):
        if plan.gross_wei is None and exit_ is not None and plan.min_usdt_out == exit_.usdt_wei:
            plan.gross_wei = exit_.gross_wei
        if plan.gross_wei is None or plan.gross_wei <= 0 or plan.min_usdt_out <= 0:
            # An adapter that did not size its deposit from the exact exit.
            raise PayoutSkip('provider_path_unverified', EXIT_UNAVAILABLE)
    check_rule_limits(rule.standing_authorization, plan)
    payout, _ = SmartAccountPayout.objects.get_or_create(rule_run=run, defaults={
        'rail': rule.payout_rail, 'deposit_address': plan.deposit_address.lower(), 'provider': plan.provider,
        'journey': plan.journey, 'fiat_currency': plan.fiat_currency,
        'status': 'prepared'})
    if payout.deposit_address != plan.deposit_address.lower():
        if payout.ramp_id is not None or payout.journey_id is not None:
            # Another worker replaced the slot's order since this plan was made.
            raise PayoutSkip('payout_in_progress', IN_PROGRESS, retry_later=True, wait=True)
        # A second run of the same slot must pay the address already recorded.
        plan.deposit_address = payout.deposit_address
    return plan


def after_payout_sent(payout_pk: int, tx_hash: str) -> None:
    """After reconcile mirrored a PayoutSent (post-commit)."""
    payout = SmartAccountPayout.objects.filter(pk=payout_pk).first()
    if payout is None or (payout.ramp_id is None and payout.journey_id is None):
        return
    ADAPTERS.get(payout.provider, ProviderAdapter)().after_onchain(payout, tx_hash)


# Mirror of the VE send each Pago Móvil payout rides on.
RAMP_FINAL = ('paid', 'refunded', 'cancelled')


def mirror_ramp_payout(payout_pk: int) -> str | None:
    """Copy the ramp's outcome onto the payout; tell the owner once, with the
    bolívares delivered, when it is paid. Ops hear about one that needs
    review (the ramp also alerts on its own)."""
    from ramps.models import RampTransaction
    from . import notifications
    payout = SmartAccountPayout.objects.select_related('rule_run', 'rule_run__rule').filter(pk=payout_pk).first()
    if payout is None or payout.ramp_id is None or payout.status in RAMP_FINAL:
        return None
    ramp = RampTransaction.objects.get(pk=payout.ramp_id)
    sent = payout.status in ('onchain_sent', 'funded', 'review')
    if sent:
        try:    # after_onchain's report was lost
            ramp = _report_lost_funding(payout, ramp)
        except Exception:  # noqa: BLE001 — next pass
            logger.exception('funding report of payout %s failed', payout.pk)
    detail = ramp.status_detail or ''
    if ramp.status == 'COMPLETED':
        status = 'paid'
    elif ramp.status == 'FAILED':
        if detail == 'refunded_to_wallet':
            status = 'refunded'   # proven back in the account contract
        else:
            # Closed unfunded: fine before the contract paid, never after.
            status = 'review' if sent else 'cancelled'
    elif ramp.status == 'PROCESSING':
        status = 'review' if detail.startswith('needs_review') else 'funded'
    else:
        status = payout.status
    if status in ('onchain_sent', 'funded'):
        _alert_stalled_ramp(payout, ramp)
    if status == payout.status:
        return status
    values = {'status': status, 'updated_at': timezone.now()}
    if status == 'paid' and ramp.fiat_amount is not None:
        values['fiat_amount'] = ramp.fiat_amount
        values['fiat_currency'] = ramp.fiat_currency or 'VES'
    if not SmartAccountPayout.objects.filter(
            pk=payout.pk, status=payout.status, ramp_id=payout.ramp_id).update(**values):
        return None
    if status == 'paid':
        try:
            fiat = Decimal(str(values.get('fiat_amount')))
            amount = f'{fiat:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') if fiat.is_finite() else ''
        except (InvalidOperation, TypeError, ValueError):
            amount = ''
        notifications.safe(notifications.payout_delivered, payout.rule_run, amount, 'Bs.')
    tell_run(payout.rule_run_id, status)
    if status == 'refunded':
        notifications.safe(notifications.payout_refunded, payout.rule_run, _signed_amount(payout, ramp))
    elif status == 'review':
        from ramps import ve_send
        if detail != f'needs_review:{ve_send.RATE_OUTSIDE}':       # tell_rate_held tells that one
            notifications.safe(notifications.payout_review, payout.rule_run, _signed_amount(payout, ramp))
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(f'Cuenta inteligente: pago Pago Móvil en revisión (payout {payout.pk}, '
                           f'ramp {ramp.internal_id}, {ramp.status}/{detail}). Ver la consola envios-ve; si se '
                           'detuvo por términos, tasa o dueño: admin de pagos, "Revisar de nuevo y continuar".',
                           dedupe_key=f'smart_payout_ramp_review_{payout.pk}', dedupe_seconds=86400)
        except Exception:  # noqa: BLE001
            logger.exception('ops alert failed')
    return status


IN_TRANSIT = 'Pago en camino.'
RUN_REFUNDED = 'El pago no llegó a quien recibe: el dinero volvió a tu Cuenta inteligente.'
RUN_IN_REVIEW = 'Estamos revisando este pago: no confirmamos que haya llegado a quien recibe. No lo repitas.'


def tell_run(run_pk, status: str) -> None:
    """The run's own line where its payment ended: a refund or a review is
    not "Pago en camino." any more (a review line is not a refund's)."""
    from .models import SmartAccountRuleRun
    if status == 'refunded':
        SmartAccountRuleRun.objects.filter(pk=run_pk, message__in=(IN_TRANSIT, RUN_IN_REVIEW)).update(
            message=RUN_REFUNDED)
    elif status == 'review':
        SmartAccountRuleRun.objects.filter(pk=run_pk, message=IN_TRANSIT).update(message=RUN_IN_REVIEW)
    elif status == 'paid':      # a review that ended paid
        SmartAccountRuleRun.objects.filter(pk=run_pk, message=RUN_IN_REVIEW).update(message=IN_TRANSIT)


def _signed_amount(payout, ramp):
    return ((ramp.metadata or {}).get('ve_send') or {}).get('gross_usd') or payout.rule_run.rule.amount


def _alert_stalled_ramp(payout, ramp) -> None:
    """Money out and still on its way: the same 2 hours as an Infinia one."""
    from . import infinia_payouts
    if payout.created_at >= timezone.now() - infinia_payouts.STALLED_AFTER:
        return
    try:
        from config.ops_alerts import send_ops_alert
        phase = ((ramp.metadata or {}).get('ve_send') or {}).get('phase')
        send_ops_alert(f'Cuenta inteligente: pago Pago Móvil detenido más de 2 horas (payout {payout.pk}, ramp '
                       f'{ramp.internal_id}, {phase}/{ramp.status_detail}). Ver la consola envios-ve.',
                       dedupe_key=f'smart_payout_ramp_stalled_{payout.pk}', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('ops alert failed')


def _report_lost_funding(payout, ramp):
    from ramps import ve_send
    section = (ramp.metadata or {}).get(ve_send.SECTION) or {}
    if section.get('funding_tx_hash') or section.get('funding_tx_hashes') or not payout.rule_run.tx_hash:
        return ramp
    return ve_send.report_funding(ramp, payout.rule_run.tx_hash, by_payout=True)


class RecheckRefused(Exception):
    """Why ops cannot continue this payment as it is (Spanish)."""


def recheck(payout, *, operator: str) -> str:
    """Ops: ask a parked payment's checks again and, only if they pass, put
    it back on its own worker, which still quotes inside the signed floor.
    It takes no amount, recipient or rate, and sends nothing itself. Never
    for one already returned by hand."""
    from payment_accounts import contract_funding
    payout = SmartAccountPayout.objects.select_related('rule_run', 'journey').get(pk=payout.pk)
    if payout.journey_id is not None and payout.journey.bridge_id is not None:
        try:
            contract_funding.reopen(payout.journey.bridge_id)
        except contract_funding.Refused as exc:
            raise RecheckRefused(f'{exc.code}: {exc.message}') from exc
        logger.info('payout %s put back by %s', payout.pk, operator)
        return 'Vuelve a la cola: se paga solo si la tasa está dentro de lo firmado.'
    if payout.ramp_id is None:
        raise RecheckRefused('Este pago no tiene una orden que revisar.')
    return _recheck_ramp(payout, operator)


def _recheck_ramp(payout, operator: str) -> str:
    from ramps import ve_send
    from ramps.models import RampTransaction
    ramp = RampTransaction.objects.get(pk=payout.ramp_id)
    section, detail = (ramp.metadata or {}).get(ve_send.SECTION) or {}, ramp.status_detail or ''
    phase = section.get('phase')
    if (ramp.status in ('PENDING', 'PROCESSING') and phase == 'funding_reported' and payout.rule_run.tx_hash
            # Seen sent: a reverted attempt's hash would hold the order open.
            and payout.status in ('onchain_sent', 'funded', 'review')):
        _report_lost_funding(payout, ramp)
        return 'Transacción reportada: se revisa su recibo en la red y sigue desde ahí.'
    if (ramp.status != 'PROCESSING' or phase != 'payout_review' or section.get('payout_key')
            or not (detail in ve_send.PARKED_DETAILS or detail.startswith('needs_review:settlement:'))):
        raise RecheckRefused('Este pago no está detenido por algo que se pueda volver a revisar; '
                             'usa la consola envios-ve.')
    problem = ve_send._terms_problem(ramp, section.get('funding_tx_hash'), section.get('funded_wei'))
    if problem:
        raise RecheckRefused(f'{ve_send.TERMS_CHANGED}: {problem}')
    problem = ramp_owner_problem(ramp)
    if problem:
        raise RecheckRefused(f'{ve_send.NOT_PAYABLE}: {problem}')
    try:
        # Nothing of this attempt left (no payout key).
        ve_send.retry_payout(ramp, operator=operator, reviewed_key='', confirmed_unpaid=True,
                             reviewed_revision=int(section.get('beneficiary_revision') or 0))
    except ve_send.VeSendError as exc:
        raise RecheckRefused(str(exc)) from exc
    return 'Vuelve a la cola: se paga solo si la tasa está dentro de lo firmado.'


def mirror_ramp_payouts() -> dict:
    out = {'updated': 0, 'errors': 0}
    for pk in (SmartAccountPayout.objects.filter(ramp__isnull=False).exclude(status__in=RAMP_FINAL)
               .values_list('pk', flat=True)):
        try:
            before = SmartAccountPayout.objects.values_list('status', flat=True).get(pk=pk)
            if mirror_ramp_payout(pk) not in (None, before):
                out['updated'] += 1
        except Exception:  # noqa: BLE001 — retried next run
            logger.exception('payout %s mirror failed', pk)
            out['errors'] += 1
    return out


def deactivate_changed_rules() -> int:
    """A payout rule whose saved destination was edited or deleted is
    deactivated until the owner signs it again (spec 7.1)."""
    from . import notifications
    from .models import SmartAccountRule
    count = 0
    for rule in SmartAccountRule.objects.filter(kind='payout', active=True, state='onchain').select_related(
            'payout_method', 'pagomovil_destination', 'standing_authorization', 'smart_account'):
        problem = authorization_problem(rule)
        if problem in DEACTIVATING:
            SmartAccountRule.objects.filter(pk=rule.pk).update(
                active=False, deactivated_reason=problem, updated_at=timezone.now())
            notifications.safe(notifications.rule_deactivated, rule, problem)
            count += 1
    _alert_paused_by_older_version()
    return count


def _alert_paused_by_older_version() -> None:
    """A worker from before decision 36 reads a fee-bearing binding as a
    changed destination and stops the rule for good (a deploy or a
    rollback). Never switched back on by itself (the owner was told it
    stopped and may have paid by hand): ops hear which ones."""
    from .models import SmartAccountRule
    wrong = [rule.pk for rule in SmartAccountRule.objects.filter(
        kind='payout', active=False, state='onchain', deactivated_reason='destination_changed',
        standing_authorization__max_processor_fee_usd__gt=0,
    ).select_related('payout_method', 'pagomovil_destination', 'standing_authorization', 'smart_account')
        if authorization_problem(rule) is None]
    if not wrong:
        return
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: reglas pausadas como destino cambiado aunque su autorización está '
                       f'vigente ({wrong[:20]}): probablemente un worker con la versión anterior. No se reactivan '
                       'solas; pedir al dueño que firme de nuevo.',
                       dedupe_key='smart_rules_paused_old_version', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('ops alert failed')
