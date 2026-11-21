"""Bank payment rules (spec 7.5): the standing authorization recorded with
Face when the owner creates the rule, and the run with nobody present.

What is built and tested here: the authorization record and its binding to
destination, amount and frequency; the checks before a run (authorization
live, destination unchanged and still verified, rail still enabled, the
rule's own bridge-cost and FX limits); skip-and-notify outside the limits.

What is NOT verified against the provider (see ProviderAdapter): opening the
bridge and the Infinia journey for funds that come from the account
CONTRACT instead of a user-signed wallet transfer. Execution therefore needs
both SMART_ACCOUNT_PAYOUT_RAILS and SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import SmartAccountPayout, SmartAccountStandingAuthorization

logger = logging.getLogger(__name__)

BPS = 10_000


class PayoutSkip(Exception):
    """This run does not happen; the owner is told why (Spanish message)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(code)


def adapter_verified() -> bool:
    return bool(getattr(settings, 'SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED', False))


def binding_hash(destination, amount: Decimal, frequency: str) -> str:
    body = json.dumps({
        'destination': str(destination.internal_id), 'details': destination.details,
        'country': destination.country, 'kind': destination.kind,
        'amount': format(Decimal(amount).quantize(Decimal('0.01')), 'f'), 'frequency': frequency,
    }, sort_keys=True, separators=(',', ':'))
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


def _retryable_authorization(user, kind: str, digest: str, **terms):
    """The authorization an exact retry of the same prepare reuses: same
    user, kind and terms, recent, not revoked, and not yet carried by a rule
    that reached the chain. Anything else gets a new row (and a new Face)."""
    from .models import SmartAccountRule
    since = timezone.now() - timedelta(seconds=AUTHORIZATION_RETRY_SECONDS)
    candidates = SmartAccountStandingAuthorization.objects.filter(
        user=user, kind=kind, binding_hash=digest, revoked_at__isnull=True, authorized_at__gte=since,
        **terms).order_by('-pk')
    for row in candidates[:5]:
        if not SmartAccountRule.all_objects.filter(
                standing_authorization=row, state__in=('onchain', 'cancelled')).exists():
            return row
    return None


def _authorize(viewer, kind: str, digest: str, namespace: str, payload: dict, message: str,
               create: dict, terms: dict):
    """Get or create the authorization row FIRST, bind the Face grant to its
    id, then record the grant on it, in one transaction: a refused Face
    rolls the new row back (no authorization without Face). A Face check is
    only tied to an action when it is consumed, so the retry after the
    owner passes Face simply gets a new row; an exact retry after the grant
    was claimed finds this row (_retryable_authorization) and re-claims the
    same key at no new check."""
    from django.db import transaction
    with transaction.atomic():
        row = _retryable_authorization(viewer.user, kind, digest, **terms)
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


def create_standing_authorization(viewer, *, destination, rail: str, amount: Decimal, frequency: str):
    """Claim one Face grant bound to (destination, amount, frequency) AND
    this authorization's own row, and record it. Raises PrepareError when
    Face is required and not granted: the row then authorizes nothing."""
    digest = binding_hash(destination, amount, frequency)
    return _authorize(
        viewer, 'payout', digest, 'smart_account_payout_rule',
        {'destination': str(destination.internal_id), 'amount': format(amount, 'f'),
         'frequency': frequency, 'rail': rail},
        'Confirma con Confío Face para programar este pago.',
        create=dict(max_bridge_cost_bps=int(getattr(settings, 'SMART_ACCOUNT_PAYOUT_MAX_BRIDGE_COST_BPS', 150)),
                    fx_tolerance_bps=int(getattr(settings, 'SMART_ACCOUNT_PAYOUT_FX_TOLERANCE_BPS', 300))),
        terms=dict(payout_destination=destination, rail=rail, amount_usd=amount, frequency=frequency))


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


def authorization_problem(rule) -> str | None:
    """Why this payment rule may not run, or None. Also used by the daily
    sweep that deactivates a rule whose saved destination changed."""
    from payment_accounts import local_money
    from . import offer
    from .services import destination_rail, payout_ref_for

    authorization = rule.standing_authorization
    destination = rule.payout_method
    if authorization is None or authorization.revoked_at is not None or authorization.kind != 'payout':
        return 'no_standing_authorization'
    if destination is None or destination.status not in ('pending', 'active'):
        return 'destination_deleted'
    if authorization.payout_destination_id != destination.pk:
        return 'destination_changed'
    if ('0x' + payout_ref_for(destination).hex()) != rule.payout_ref:
        return 'destination_changed'
    if authorization.binding_hash != binding_hash(destination, rule.amount, rule.frequency):
        return 'destination_changed'
    if destination_rail(destination) != rule.payout_rail or rule.payout_rail not in offer.payout_rails():
        return 'rail_not_available'
    if authorization.face_required and not authorization.face_action_key:
        return 'no_standing_authorization'
    validation = (destination.provider_data or {}).get('validation')
    if local_money.verification_state(validation) != local_money.VERIFIED:
        return 'destination_unverified'
    return None


@dataclass
class PayoutPlan:
    deposit_address: str
    min_usdt_out: int
    journey: object = None
    bridge_cost_bps: int = 0
    fx_rate: Decimal | None = None
    fiat_currency: str = ''


class ProviderAdapter:
    """The provider side of one run. UNVERIFIED against Infinia and Relay.

    The existing outgoing path (payment_accounts/bridge.py quote_provider_funding,
    bridge_execution.prepare_bridge / submit_bridge, infinia_journeys.create_journey)
    assumes the USDT leaves the owner's wallet in a user-signed batch, claims a
    Face grant per journey, and for Bre-B needs a device location check with the
    request's META. None of those hold for a relayer-originated executeRule
    paying from the account contract. `open` below is the seam where that path
    must be adapted and verified; until then it refuses."""

    def open(self, rule, run, usdt_estimate: int) -> PayoutPlan:
        raise PayoutSkip('provider_path_unverified',
                         'Este pago automático todavía no está habilitado para tu tipo de cuenta.')

    def after_broadcast(self, payout, tx_hash: str) -> None:
        return None


def adapter() -> ProviderAdapter:
    return ProviderAdapter()


def plan_run(rule, run, usdt_estimate: int) -> PayoutPlan:
    """Everything that must hold before executeRule is sent for a payout.
    Raises PayoutSkip (run skipped and notified, never forced)."""
    from . import offer
    if not offer.payout_rails() or not adapter_verified():
        raise PayoutSkip('payouts_disabled', 'Los pagos automáticos a cuentas bancarias están en pausa.')
    problem = authorization_problem(rule)
    if problem:
        raise PayoutSkip(problem, 'El destino guardado cambió. Firma la regla de nuevo para reactivarla.')
    plan = adapter().open(rule, run, usdt_estimate)
    authorization = rule.standing_authorization
    if plan.bridge_cost_bps > authorization.max_bridge_cost_bps:
        raise PayoutSkip('bridge_cost_above_limit',
                         'El costo de envío de hoy supera el límite de tu regla. Lo intentaremos en la próxima fecha.')
    reference = authorization.reference_fx_rate
    if reference and plan.fx_rate is not None:
        floor = reference * Decimal(BPS - authorization.fx_tolerance_bps) / Decimal(BPS)
        if plan.fx_rate < floor:
            raise PayoutSkip('fx_rate_below_limit',
                             'La tasa de hoy está por debajo del límite de tu regla. Lo intentaremos en la próxima fecha.')
    payout, _ = SmartAccountPayout.objects.get_or_create(rule_run=run, defaults={
        'rail': rule.payout_rail, 'deposit_address': plan.deposit_address.lower(),
        'journey': plan.journey, 'fiat_currency': plan.fiat_currency, 'status': 'prepared'})
    if payout.deposit_address != plan.deposit_address.lower():
        # A second run of the same slot must pay the address already recorded.
        plan.deposit_address = payout.deposit_address
    return plan


def deactivate_changed_rules() -> int:
    """A payout rule whose saved destination was edited or deleted is
    deactivated until the owner signs it again (spec 7.1)."""
    from . import notifications
    from .models import SmartAccountRule
    count = 0
    for rule in SmartAccountRule.objects.filter(kind='payout', active=True, state='onchain').select_related(
            'payout_method', 'standing_authorization', 'smart_account'):
        problem = authorization_problem(rule)
        if problem in ('destination_deleted', 'destination_changed', 'no_standing_authorization'):
            SmartAccountRule.objects.filter(pk=rule.pk).update(
                active=False, deactivated_reason=problem, updated_at=timezone.now())
            notifications.safe(notifications.rule_deactivated, rule, problem)
            count += 1
    return count
