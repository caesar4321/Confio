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

Providers are a registry keyed by rail (RAIL_ADAPTERS): every local_money
rail is Infinia's; 've_pagomovil' (Venezuelan Pago Móvil) is Pago ASAP's
(PagoAsapAdapter), switched on by SMART_ACCOUNT_PAYOUT_RAILS containing
've_pagomovil' AND SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS containing
'pagoasap' AND ramps declaring it can take a send funded by the account
contract (ramps_contract_funding_ready()).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_UP, Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import SmartAccountPayout, SmartAccountStandingAuthorization

logger = logging.getLogger(__name__)

BPS = 10_000
WAD = 10 ** 18

INFINIA = 'infinia'
PAGOASAP = 'pagoasap'
VE_PAGOMOVIL = 've_pagomovil'
# Rail -> provider adapter. Every rail not named here is an Infinia rail
# (payment_accounts.local_money.METHODS).
RAIL_ADAPTERS = {VE_PAGOMOVIL: PAGOASAP}
VE_PAGOMOVIL_LABEL = 'Pago Móvil'
VE_PAGOMOVIL_HINT = 'Bolívares a cualquier banco de Venezuela, a la tasa del día.'

# authorization_problem codes that stop the rule until the owner signs again.
DEACTIVATING = ('destination_deleted', 'destination_changed', 'no_standing_authorization')


class PayoutSkip(Exception):
    """This run does not happen; the owner is told why (Spanish message).
    `deactivate`: the rule also stops until the owner signs it again.
    `retry_later`: a passing refusal; the slot is retried (until it gives up)
    instead of being skipped for good."""

    def __init__(self, code: str, message: str, *, deactivate: str = '', retry_later: bool = False):
        self.code = code
        self.message = message
        self.deactivate = deactivate
        self.retry_later = retry_later
        super().__init__(code)


def _limit_skip(exc) -> 'PayoutSkip':
    """A ramps send limit, the same answer before and under the reservation
    lock: 'limit_exceeded' either way. A per-send minimum/maximum is final
    for this slot (the amount never passes it); a rolling daily cap is
    passing (it frees up), so the slot retries until it gives up."""
    return PayoutSkip('limit_exceeded', str(exc) or VE_UNAVAILABLE, retry_later=bool(getattr(exc, 'passing', False)))


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


def rail_ready(rail: str) -> bool:
    """The provider side of `rail` may run with nobody present."""
    name = adapter_name(rail)
    if not adapter_verified(name):
        return False
    if name == PAGOASAP:
        return ramps_contract_funding_ready()
    return True


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
                   amount_usd=amount, frequency=frequency))


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
    if authorization is None or authorization.revoked_at is not None or authorization.kind != 'payout':
        return 'no_standing_authorization'
    if rule.payout_rail == VE_PAGOMOVIL:
        return _pagomovil_problem(rule, authorization)
    destination = rule.payout_method
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


class ProviderAdapter:
    """The provider side of one run. UNVERIFIED against Infinia and Relay.

    The existing outgoing path (payment_accounts/bridge.py quote_provider_funding,
    bridge_execution.prepare_bridge / submit_bridge, infinia_journeys.create_journey)
    assumes the USDT leaves the owner's wallet in a user-signed batch, claims a
    Face grant per journey, and for Bre-B needs a device location check with the
    request's META. None of those hold for a relayer-originated executeRule
    paying from the account contract. `open` below is the seam where that path
    must be adapted and verified; until then it refuses."""

    def open(self, rule, run, usdt_estimate: int, exit_: PayoutExit | None = None,
             window: tuple[int, int] | None = None) -> PayoutPlan:
        """For a cUSD+ rule `exit_` is the exact exit (usdt_estimate is its
        usdt_wei): the plan's min_usdt_out must be exactly it."""
        raise PayoutSkip('provider_path_unverified',
                         'Este pago automático todavía no está habilitado para tu tipo de cuenta.')

    def after_onchain(self, payout, tx_hash: str) -> None:
        """PayoutSent was mirrored for this payout (reconcile._payout_sent)."""
        return None


# ── Pago ASAP (Venezuelan Pago Móvil) ───────────────────────────────────

VE_UNAVAILABLE = 'Los pagos por Pago Móvil no están disponibles por ahora. Lo intentaremos en la próxima fecha.'
# The bridge quote must outlive the relayer transaction comfortably.
MIN_TARGET_LIFETIME = timedelta(minutes=3)


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
        from ramps import ve_pagomovil
        from security.minors import minor_refusal
        if not ramps_contract_funding_ready():
            raise PayoutSkip('provider_path_unverified', VE_UNAVAILABLE)
        if not ve_pagomovil.enabled(ve_pagomovil.SEND):
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE)
        if minor_refusal(rule.smart_account.owner_user):
            raise PayoutSkip('minor', 'Los pagos por Pago Móvil están disponibles para mayores de 18 años.')
        existing = SmartAccountPayout.objects.filter(rule_run=run).first()
        if existing is not None and existing.ramp_id is not None:
            return self._resume(rule, existing, window)
        exit_ = exit_ or payout_exit(rule, window=window, unavailable=VE_UNAVAILABLE)
        plan = self._price(rule, exit_)
        # Outside the rule's own limits: skipped before anything is reserved.
        check_rule_limits(rule.standing_authorization, plan)
        ramp, payout = self._reserve(rule, run, exit_, plan)
        return self._claim_target(rule, payout, ramp, plan)

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
            raise PayoutSkip('provider_unavailable', str(exc) or VE_UNAVAILABLE) from exc
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

    def _reserve(self, rule, run, exit_: PayoutExit, plan: PayoutPlan):
        """The VE send for the owner, persisted with the payout row in one
        transaction (no order without its payout, no payout without its
        order). Per-user and global limits are ramps' own (check_limits,
        re-run under its reservation lock)."""
        from ramps import ve_send
        from ramps.ve_pagomovil import VePagoMovilError
        account = rule.smart_account
        owner = account.owner_user
        destination = rule.pagomovil_destination
        try:
            ve_send.check_limits(owner, rule.amount, PAGOASAP)
        except VePagoMovilError as exc:
            raise _limit_skip(exc) from exc
        block = ve_send.current_block()
        if block is None or account.account_id is None:
            raise PayoutSkip('provider_unavailable', VE_UNAVAILABLE)
        from . import chain
        beneficiary = {'cedula': destination.id_number, 'phone': destination.phone,
                       'bank_code': destination.bank_code, 'name': destination.holder_name}
        try:
            with transaction.atomic():
                payout, _ = SmartAccountPayout.objects.select_for_update().get_or_create(
                    rule_run=run, defaults={'rail': rule.payout_rail, 'provider': PAGOASAP,
                                            'fiat_currency': 'VES', 'status': 'reserving'})
                if payout.ramp_id is not None:
                    raise _AlreadyReserved(payout)
                ramp = ve_send.reserve(
                    provider=PAGOASAP, user=owner, account=account.account, gross_usd=rule.amount,
                    beneficiary=beneficiary,
                    gross_wei=exit_.gross_wei if exit_.gross_wei is not None else int(rule.amount * WAD),
                    deposit_wei=exit_.usdt_wei,
                    created_block=block, estimate=plan.estimate,
                    funding_sender=(chain.cusd_address() or '').lower())
                ramp = ve_send.prepare(ramp)
                SmartAccountPayout.objects.filter(pk=payout.pk).update(ramp=ramp, updated_at=timezone.now())
                payout.ramp = ramp
        except _AlreadyReserved as already:
            raise PayoutSkip('payout_in_progress', 'Este pago ya está en curso.') from already
        except ve_send.VeSendLimitError as exc:
            # The same limit as the pre-check, re-run under ramps' lock:
            # decided exactly like it (_limit_skip).
            raise _limit_skip(exc) from exc
        except VePagoMovilError as exc:
            # Refused before anything was reserved (a limit reached since the
            # pre-check, an identical payout still open, a changed wallet):
            # passing, so the slot retries instead of being skipped for good.
            raise PayoutSkip('send_refused', str(exc) or VE_UNAVAILABLE, retry_later=True) from exc
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
                ve_send.fail_unfunded(ramp, 'deposit_target_unavailable')
            except Exception:  # noqa: BLE001 — expires on its own (FUNDING_WINDOW)
                logger.exception('Could not close VE send %s', ramp.pk)
            SmartAccountPayout.objects.filter(pk=payout.pk).update(status='cancelled', updated_at=timezone.now())
            if not isinstance(exc, VePagoMovilError):
                logger.warning('Funding target failed for rule %s', rule.pk, exc_info=True)
            raise PayoutSkip('provider_unavailable',
                             str(exc) if isinstance(exc, VePagoMovilError) else VE_UNAVAILABLE) from exc
        return self._plan_for(rule, payout, ramp, plan)

    def _plan_for(self, rule, payout, ramp, plan: PayoutPlan) -> PayoutPlan:
        from ramps import ve_send
        details = ve_send.funding_details(ramp)
        exact = plan.min_usdt_out
        if (not details or str(details.get('deposit_amount_wei')) != str(exact)
                or str(details.get('network')) != 'BSC'):
            # ramps would wait for a different amount than the contract
            # sends: never pay it. The order expires unfunded on its own.
            logger.error('VE send %s funding target does not match the exit (%s)', ramp.pk, details)
            _close_ramp(ramp)
            SmartAccountPayout.objects.filter(pk=payout.pk).update(status='cancelled', updated_at=timezone.now())
            raise PayoutSkip('provider_path_unverified', VE_UNAVAILABLE)
        expires_at = details.get('expires_at')
        if expires_at and int(expires_at) < int((timezone.now() + MIN_TARGET_LIFETIME).timestamp()):
            _close_ramp(ramp)
            SmartAccountPayout.objects.filter(pk=payout.pk).update(status='cancelled', updated_at=timezone.now())
            raise PayoutSkip('provider_quote_expired', 'No se pudo completar a tiempo. Lo intentaremos en la próxima fecha.')
        deposit = str(details['deposit_address']).lower()
        SmartAccountPayout.objects.filter(pk=payout.pk).update(
            deposit_address=deposit, status='prepared', updated_at=timezone.now())
        plan.deposit_address, plan.ramp = deposit, ramp
        return plan

    def _resume(self, rule, payout, window: tuple[int, int] | None = None) -> PayoutPlan:
        """A retry of the same slot (the relayer call failed or reverted):
        pay the SAME order and address while its quote lives, never a second
        order. A cUSD+ retry pins the USDT the order was reserved for and
        re-derives the gross that nets exactly it."""
        from ramps import ve_send
        from ramps.models import RampTransaction
        if payout.status == 'cancelled':
            raise PayoutSkip('provider_quote_expired',
                             'No se pudo completar a tiempo. Lo intentaremos en la próxima fecha.')
        if payout.status not in ('reserving', 'prepared'):
            raise PayoutSkip('payout_in_progress', 'Este pago ya está en curso.')
        ramp = RampTransaction.objects.get(pk=payout.ramp_id)
        target = None
        if rule_is_plus(rule):
            try:
                target = int((ramp.metadata or {}).get(ve_send.SECTION, {}).get('deposit_wei'))
            except (TypeError, ValueError):
                target = None
            if not target:
                raise PayoutSkip('provider_quote_expired',
                                 'No se pudo completar a tiempo. Lo intentaremos en la próxima fecha.')
        exit_ = payout_exit(rule, window=window, target=target, unavailable=VE_UNAVAILABLE)
        plan = PayoutPlan(deposit_address='', min_usdt_out=exit_.usdt_wei, provider=PAGOASAP, fiat_currency='VES',
                          gross_wei=exit_.gross_wei)
        phase = ve_send.view(ramp).get('phase') if ramp.status == 'PENDING' else None
        if phase == 'awaiting_funding':
            return self._claim_target(rule, payout, ramp, plan)
        if phase == 'funding_reported':
            return self._plan_for(rule, payout, ramp, plan)
        _close_ramp(ramp)
        SmartAccountPayout.objects.filter(pk=payout.pk, status__in=('reserving', 'prepared')).update(
            status='cancelled', updated_at=timezone.now())
        raise PayoutSkip('provider_quote_expired', 'No se pudo completar a tiempo. Lo intentaremos en la próxima fecha.')

    def after_onchain(self, payout, tx_hash: str) -> None:
        """PayoutSent is final: tell ramps where the funding is and let its
        own reconciliation prove it on chain (and from there settle, pay and
        poll). A failure here only delays it: the poller's chain scan from
        the order's created block finds the transfer by itself."""
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


def _close_ramp(ramp) -> None:
    """Close a contract-funded VE send no executeRule was broadcast for
    (ve_send.close_unsent refuses one with a reported hash)."""
    from ramps import ve_send
    try:
        ve_send.close_unsent(ramp)
    except Exception:  # noqa: BLE001 — ramps' own expiry closes it later
        logger.exception('Could not close VE send %s', getattr(ramp, 'pk', None))


def close_unsent_order(run) -> bool:
    """The payout run ended for good without its executeRule on the wire:
    close that run's own order now so it never lingers. The caller has
    checked that no relayer transaction for the slot may still land."""
    payout = SmartAccountPayout.objects.filter(rule_run=run, ramp__isnull=False).select_related('ramp').first()
    if payout is None or payout.status not in ('reserving', 'prepared', 'pending', 'cancelled'):
        return False
    _close_ramp(payout.ramp)
    SmartAccountPayout.objects.filter(pk=payout.pk, status__in=('reserving', 'prepared', 'pending')).update(
        status='cancelled', updated_at=timezone.now())
    return True


class _AlreadyReserved(Exception):
    def __init__(self, payout):
        self.payout = payout
        super().__init__('already reserved')


ADAPTERS = {INFINIA: ProviderAdapter, PAGOASAP: PagoAsapAdapter}


def adapter(rail: str = '') -> ProviderAdapter:
    return ADAPTERS[adapter_name(rail)]()


def check_rule_limits(authorization, plan: PayoutPlan) -> None:
    """The rule's own limits, stored with its Face authorization: the most
    the bridge/provider may cost, and the least FX rate it accepts."""
    if plan.bridge_cost_bps > authorization.max_bridge_cost_bps:
        raise PayoutSkip('bridge_cost_above_limit',
                         'El costo de envío de hoy supera el límite de tu regla. Lo intentaremos en la próxima fecha.')
    reference = authorization.reference_fx_rate
    if reference and plan.fx_rate is not None:
        floor = reference * Decimal(BPS - authorization.fx_tolerance_bps) / Decimal(BPS)
        if plan.fx_rate < floor:
            raise PayoutSkip('fx_rate_below_limit',
                             'La tasa de hoy está por debajo del límite de tu regla. Lo intentaremos en la próxima fecha.')


def plan_run(rule, run, usdt_estimate: int, window: tuple[int, int] | None = None) -> PayoutPlan:
    """Everything that must hold before executeRule is sent for a payout.
    Raises PayoutSkip (run skipped and notified, never forced). A cUSD+
    rule's plan carries gross_wei and an exact min_usdt_out, whatever the
    adapter (executeRule's three-word data)."""
    from . import offer
    if not offer.payout_rails() or not rail_ready(rule.payout_rail):
        raise PayoutSkip('payouts_disabled', 'Los pagos automáticos a cuentas bancarias están en pausa.')
    problem = authorization_problem(rule)
    if problem:
        raise PayoutSkip(problem, 'El destino guardado cambió. Firma la regla de nuevo para reactivarla.',
                         deactivate=problem if problem in DEACTIVATING else '')
    exit_ = None
    if rule_is_plus(rule):
        from . import quotes
        window = window or quotes.plus_price_window()
        existing = SmartAccountPayout.objects.filter(rule_run=run).first() if run is not None else None
        if existing is None or existing.ramp_id is None:
            exit_ = payout_exit(rule, window=window)
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
        # A second run of the same slot must pay the address already recorded.
        plan.deposit_address = payout.deposit_address
    return plan


def after_payout_sent(payout_pk: int, tx_hash: str) -> None:
    """After reconcile mirrored a PayoutSent (post-commit)."""
    payout = SmartAccountPayout.objects.filter(pk=payout_pk).first()
    if payout is None or payout.ramp_id is None:
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
    detail = ramp.status_detail or ''
    sent = payout.status in ('onchain_sent', 'funded', 'review')
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
        return payout.status
    if status == payout.status:
        return status
    values = {'status': status, 'updated_at': timezone.now()}
    if status == 'paid' and ramp.fiat_amount is not None:
        values['fiat_amount'] = ramp.fiat_amount
        values['fiat_currency'] = ramp.fiat_currency or 'VES'
    if not SmartAccountPayout.objects.filter(pk=payout.pk, status=payout.status).update(**values):
        return None
    if status == 'paid':
        try:
            fiat = Decimal(str(values.get('fiat_amount')))
            amount = f'{fiat:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') if fiat.is_finite() else ''
        except (InvalidOperation, TypeError, ValueError):
            amount = ''
        notifications.safe(notifications.payout_delivered, payout.rule_run, amount, 'Bs.')
    elif status == 'review':
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(f'Cuenta inteligente: pago Pago Móvil en revisión (payout {payout.pk}, '
                           f'ramp {ramp.internal_id}, {ramp.status}/{detail})',
                           dedupe_key=f'smart_payout_ramp_review_{payout.pk}', dedupe_seconds=86400)
        except Exception:  # noqa: BLE001
            logger.exception('ops alert failed')
    return status


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
        if problem in ('destination_deleted', 'destination_changed', 'no_standing_authorization'):
            SmartAccountRule.objects.filter(pk=rule.pk).update(
                active=False, deactivated_reason=problem, updated_at=timezone.now())
            notifications.safe(notifications.rule_deactivated, rule, problem)
            count += 1
    return count
