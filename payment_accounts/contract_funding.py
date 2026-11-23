"""Infinia to-bank journeys funded by a Cuenta inteligente's payment rule.

The owner signs nothing per run. The account CONTRACT's executeRule exits
its dollars through CusdVault.redeemWithFee, so the USDT reaches the bridge
deposit address from the cUSD vault; Relay delivers USDC to the owner's own
Infinia Polygon account, and the ordinary journey converts and pays out.

What differs from a wallet-funded send, and only this:

- Authority is a `ContractFunding`: an object built from a rule run, whose
  terms (owner, contract, destination, amount, standing authorization) are
  re-read from the database every time it is used. No GraphQL argument can
  make one, and every owner mutation refuses the rows it creates.
- Bridge source and refund address are the contract; there are no calls to
  sign. The bridge starts 'submitted' (never 'prepared', which every app
  build reads as "waiting for your signature") and has no source hash until
  the funding is proven.
- The deposit address is asked as a one-time address (Relay `strict`), and
  an address this database has already used is never handed out again.
  Such an address fills whoever pays it FIRST, whatever the amount, so
  settlement follows only the Relay request bound to our deposit's hash.
- That request is looked up (relay_lookups' shared budget), kept on the
  order with the deposit and hash it was found by, and then followed by its
  id. A rate limit is never evidence about the transfer.
- Funding is proven only by the executeRule hash the payout path reports
  and that transaction's final receipt: never by a log scan or an amount.
- executeRule pays the rule as stored when it is mined. Money converts or
  pays only while the executed event is the rule this run was signed
  under (amount, payoutRef, authorization); otherwise it is bound for
  tracking and parked (TERMS_CHANGED). Likewise funded money never goes
  to a changed, rejected or unconfirmed signed holder (PAYEE_CHANGED).
- The rule's FX floor is a RATE, stored with the order: every quote and
  requote must give it, whatever was delivered. Under it nothing is
  converted: asked again for RATE_WAIT_SECONDS, then parked (RATE_OUTSIDE).
- A parked payment continues only through reopen(), which asks all of it
  again: executed terms, payee, owner, accounts, and then the rate.
- The processor's fixed fee cannot be in the batch (the contract pays one
  address), so it becomes the existing carry-forward fee debt. It is
  outside the rule's cost limit and never above the ceiling the owner
  signed (spec decision 36).

One order = one bridge = one journey, and a run has at most one that can
be funded: a fresh order follows only once the last is closed unfunded.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import bridge_chain as chain
from . import relay_lookups
from .allbridge_next import TOKENS, NextError, address
from .clients import InfiniaClient, ProviderAPIError
from .eligibility import EligibilityDenied, EligibilityPolicyNotConfigured
from .models import FundingInstruction, MoneyFlow, PaymentBridgeQuote, PaymentBridgeTransfer
from .relay import RelayAmountTooSmall, RelayClient, RelayError
from .services import PaymentAccountError

logger = logging.getLogger(__name__)

MODE = 'contract'
# In the bridge's and the journey's MoneyFlow.metadata, and in
# PaymentBridgeTransfer.binding (no schema change).
KEY = 'contract_funding'
SOURCE, DESTINATION = 'BSC:USDT', 'POL:USDC'
# The rails with a real unattended path. br_qr is one-off; co_breb needs a
# device location pass with every operation, which no run can give.
RAILS = ('mx_clabe', 'br_pix')
BPS = 10_000
CENT = Decimal('0.01')
# A deposit must still be open this long when the relayer call is sent.
MIN_LIFETIME_SECONDS = 180
# No call can be sent this long after the deadline (see above), so an order
# with nothing on the wire closes then and stops holding the owner's accounts.
CLOSE_AFTER_SECONDS = 300
REVIEW_AFTER_SECONDS = 3600
TERMS_CHANGED = 'contract_funding_terms_changed'
PAYEE_CHANGED = 'contract_funding_payee_changed'
# The owner or their accounts may not pay now (a ban, a closed account).
NOT_PAYABLE = 'contract_funding_not_payable'
# No quote inside the order's limits, for RATE_WAIT_SECONDS.
RATE_OUTSIDE = 'fx_quote_outside_authorization'
# A funded payment waits this long for the rate. It holds the owner's
# accounts meanwhile, so not longer.
RATE_WAIT_SECONDS = 3600
DELAYED = 'bridge_not_delivered'
FINAL = ('success', 'refund')
LOOKUPS = ('depositAddress', 'depositTxHash')
# A followed request that is not final yet is looked up again this often:
# Relay may have moved the fill or the refund to another request id.
RELOOK_SECONDS = 300
# Rate-limited lookups park nothing. Ops hear once they have held a
# transfer this long past its deadline.
THROTTLE_ALERT_SECONDS = 2 * 3600
# A bank that has not answered yet is asked again this often, not every pass.
PAYEE_RETRY_SECONDS = 300
# A leg left unanswered by a 429 whose replay the owner or the payee keeps
# refusing is parked after this long: it holds the owner's accounts meanwhile.
REPLAY_REFUSED_PARK_SECONDS = 24 * 3600
REPLAY_REFUSED = 'replay_refused'
# The operation's provider_data key: when its replay was first refused.
REPLAY_REFUSED_SINCE = 'replay_refused_since'
# A conversion refused only for an expired quote, as often as it is requoted.
REQUOTES_USED = 'fx_quote_retries_exhausted'
RECHECKABLE = (TERMS_CHANGED, PAYEE_CHANGED, NOT_PAYABLE, RATE_OUTSIDE, DELAYED, REQUOTES_USED)
# execution_problem's "the event is not mirrored yet": a wait, never a park.
EVENT_NOT_SEEN = 'event_not_found'
TX_HASH = re.compile(r'0x[0-9a-fA-F]{64}')
AMOUNT_TOO_LOW = ('AMOUNT_TOO_LOW', 'amount_too_low')
OWNER_REFUSAL = 'Este pago lo hace tu Cuenta inteligente automáticamente; no se cambia desde aquí.'

UNAVAILABLE = 'Los pagos automáticos por {rail} no están disponibles en este momento.'
BUSY = 'Hay otro envío de tu cuenta local en curso. Haremos este pago cuando termine.'
TRY_LATER = 'No pudimos cotizar este pago ahora. Lo intentaremos de nuevo en unos minutos.'
TOO_SMALL = 'El monto es muy bajo para pagar por {rail}: no alcanza para los costos del envío. Usa un monto mayor.'
FEE_RAISED = ('La comisión de {rail} subió a {now} por pago y tu regla autoriza hasta {signed}. '
              'No hicimos este pago: abre la regla y fírmala de nuevo.')
CURRENCY_NAMES = {'MXN': 'pesos mexicanos', 'BRL': 'reales'}


class Refused(PaymentAccountError):
    """Why this payment cannot run. `message` is Spanish and meant for the
    owner. `retry`: a passing condition; the same terms may work shortly."""

    def __init__(self, code: str, message: str, *, retry: bool = False):
        self.code, self.message, self.retry = code, message, retry
        super().__init__(message)


class RecoverableRelay(RelayClient):
    """Names who may withdraw a refund Relay could not send. refundTo stays
    the account contract, which cannot sign that withdrawal (no key and no
    ERC-1271); recoveryAddress is documented on /quote/v2 for deposit
    addresses and never receives a refund by itself."""

    def __init__(self, recovery='', session=None):
        super().__init__(session=session)
        self.recovery = address(recovery) if recovery else ''

    def _request(self, method, path, *, body=None, params=None):
        if path == '/quote/v2' and body is not None and self.recovery:
            body = dict(body, recoveryAddress=self.recovery)
        return super()._request(method, path, body=body, params=params)


class OneTimeDepositRelay(RecoverableRelay):
    """Every deposit quote asks for a single-use address.

    Relay's changelog of 2026-10-05: with strict=true an EXACT_INPUT deposit
    address fills its first deposit only and refunds any later one to
    refundTo. Without it the address is open and reusable, so two runs of
    one account could share it. Documented, not observed: persist() still
    refuses an address that was used before.
    """

    def _request(self, method, path, *, body=None, params=None):
        if path == '/quote/v2' and body is not None:
            body = dict(body, strict=True)
        return super()._request(method, path, body=body, params=params)


def fee_usd(fee: dict | None) -> Decimal:
    return Decimal(fee['total_usd']) if fee else Decimal(0)


def fee_text(value) -> str:
    """A fee as it is signed: to the cent, or exact when the tariff is finer."""
    value = Decimal(value)
    exact = value.quantize(CENT) if value == value.quantize(CENT) else value.normalize()
    return f'US${exact:f}'


def alert(text: str, key: str, provider: str = 'Infinia') -> None:
    """Ops, once a day per key, never while holding row locks."""
    def send():
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(f'Pago automático {provider}: {text}', dedupe_key=key, dedupe_seconds=86400)
        except Exception:  # noqa: BLE001
            logger.exception('contract funding alert failed')
    transaction.on_commit(send)


def is_contract_flow(flow) -> bool:
    return KEY in ((flow.metadata or {}) if flow is not None else {})


def refuse_owner_action(flow) -> None:
    if is_contract_flow(flow):
        raise PaymentAccountError(OWNER_REFUSAL)


# ------------------------------------------------------------- authority

_ISSUE = object()


class ContractFunding:
    """The authority for exactly one rule run. It holds the run's id and the
    terms first read for it; every use reads them again and refuses a change."""

    __slots__ = ('run_pk', '_seen')

    def __init__(self, run_pk, *, _issue=None):
        if _issue is not _ISSUE:
            raise TypeError('ContractFunding is issued by ContractFunding.for_run')
        self.run_pk, self._seen = int(run_pk), None

    @classmethod
    def for_run(cls, run_pk) -> 'ContractFunding':
        funding = cls(run_pk, _issue=_ISSUE)
        funding.terms()
        return funding

    def terms(self) -> dict:
        from smart_account.infinia_payouts import funding_terms
        current = funding_terms(self.run_pk)
        seen = record(current)
        if self._seen is not None and self._seen != seen:
            raise Refused('authorization_changed', 'La regla cambió mientras preparábamos el pago.', retry=True)
        self._seen = seen
        return current


def record(terms: dict) -> dict:
    """The terms as stored on the bridge, to bind it and to check a retry."""
    return {
        'run': int(terms['run']), 'rule': str(terms['rule']),
        'authorization': str(terms['authorization']), 'binding_hash': terms['binding_hash'],
        'payout_ref': terms['payout_ref'], 'rail': terms['rail'], 'rule_event': terms['rule_event'],
        'owner': terms['owner'].pk, 'destination': str(terms['destination'].internal_id),
        'contract': address(terms['contract']), 'vault': address(terms['vault']),
        'amount': format(Decimal(terms['amount']).quantize(CENT), 'f'),
        'fee_ceiling': format(Decimal(terms['fee_ceiling']).quantize(Decimal('0.000001')), 'f'),
        'fx_floor': format(Decimal(terms['fx_floor']), 'f'),
    }


def require_owner(owner) -> None:
    """Who may send, as a manual send's request gates decide it, with nobody
    present: what SecurityMiddleware, _active_account, _require_adult and
    require_outgoing_face refuse apart from the request itself. A ban, a
    disabled user or an identity hold may be lifted (retry: a scheduled run
    waits inside its slot, as before signing); a minor, a deleted account or
    one that is not personal is final."""
    from security.identity_reuse import outgoing_identity_restriction
    from security.minors import minor_refusal
    from security.utils import check_user_banned
    user = owner.user
    if owner.deleted_at or owner.account_type != 'personal' or getattr(user, 'deleted_at', None):
        raise Refused('account_unavailable', 'Tu cuenta no está disponible para pagos automáticos.')
    if not user.is_active:
        raise Refused('account_unavailable', 'Tu cuenta no está disponible para pagos automáticos.', retry=True)
    if check_user_banned(user)[0]:
        raise Refused('account_suspended', 'Tu cuenta está suspendida. Escríbenos por soporte.', retry=True)
    if outgoing_identity_restriction(user):
        raise Refused('identity_hold', 'Tu cuenta está en revisión. Escríbenos por soporte para continuar.',
                      retry=True)
    if minor_refusal(user):
        raise Refused('minor', 'Los pagos automáticos a cuentas bancarias son para mayores de 18 años.')


def relay_key_set() -> bool:
    """GET /requests/v3 (settlement_request) refuses a keyless caller:
    without a key no delivery could ever be recognised."""
    return bool(str(getattr(settings, 'RELAY_API_KEY', '') or '').strip())


def rail_on(rail: str) -> bool:
    """The provider switches this path needs, the same as a manual send's."""
    from . import local_money
    needed = ('INFINIA_PAYMENT_ACCOUNTS_ENABLED', 'INFINIA_JOURNEYS_ENABLED', 'PAYMENT_BRIDGE_QUOTES_ENABLED',
              'PAYMENT_BRIDGE_BSC_ENABLED', 'CUSD_PLUS_7702_ENABLED')
    return (rail in RAILS and relay_key_set() and all(getattr(settings, name, False) for name in needed)
            and rail in local_money._enabled_method_ids())


def check_route(owner, destination, rail: str, amount: Decimal):
    """Everything a manual send of this rail checks before a price exists.
    Returns (local account, crypto account, funding instruction, recipient)."""
    from . import local_money
    from .bridge import exceeds_bridge_cap, verified_destination
    from .infinia_journeys import validate_accounts
    from .schema import _verified_identity
    from .services import _require_capability

    method = local_money.METHODS.get(rail)
    name = method.title if method else rail
    unavailable = UNAVAILABLE.format(rail=name)
    if not rail_on(rail):
        raise Refused('provider_unavailable', unavailable, retry=True)      # switches come back
    require_owner(owner)

    data, details = destination.provider_data or {}, destination.details or {}
    value = str(details.get(method.field) or '')
    try:
        well_formed = bool(value) and local_money.normalize_value(method, value) == value
    except PaymentAccountError:
        well_formed = False
    if (not well_formed or destination.confio_account_id != owner.pk or destination.provider != 'infinia'
            or destination.status not in ('pending', 'active') or data.get('method_id') != rail
            or (destination.country, destination.asset, destination.kind) != (method.country, method.asset, method.kind)
            or details.get('type') != method.destination_type):
        raise Refused('destination_unusable',
                      f'Esa cuenta guardada no sirve para pagar por {name}. Guárdala de nuevo.')
    try:
        local_money.require_current_destination(destination)
    except PaymentAccountError as exc:
        raise Refused('payout_method_unverified',
                      'Revisa de nuevo a quien recibe antes de programar el pago.', retry=True) from exc

    if local_money.region_unsupported(owner):
        raise Refused('region_not_supported', local_money.REGION_UNSUPPORTED_MESSAGE)

    local, crypto = local_money.accounts_for(owner, method.country, method.asset)
    state = local_money.pair_status(local, crypto)
    currency = CURRENCY_NAMES.get(method.asset, method.asset)
    if state == 'provisioning':
        raise Refused('local_account_pending',
                      f'Tu cuenta de {currency} todavía se está abriendo. Inténtalo cuando esté activa.', retry=True)
    if state == 'none':
        raise Refused('local_account_required', f'Para pagar por {name} necesitas tu cuenta de {currency} en Confío. '
                                                f'Ábrela desde Enviar, en {name}, y vuelve a intentarlo.')
    if state != 'active':
        raise Refused('local_account_inactive',
                      f'Tu cuenta de {currency} no está activa. Escríbenos por soporte para revisarla.')
    from .activation import require_paid
    try:
        require_paid(owner, method.country, method.asset)
    except PaymentAccountError as exc:
        raise Refused('local_account_unpaid', f'Termina de abrir tu cuenta de {currency} desde Enviar, en {name}, '
                                              'y vuelve a intentarlo.') from exc
    try:
        identity = _verified_identity(owner)
    except PaymentAccountError:
        identity = None
    try:
        local_money.require_rail(owner, identity, method)   # eligibility, document, region, rail switch
    except PaymentAccountError as exc:
        raise Refused('rail_not_eligible', str(exc)) from exc

    if exceeds_bridge_cap(amount):
        raise Refused('limit_exceeded', f'Ese monto supera el máximo por envío por {name}. Usa un monto menor.')

    now = timezone.now()
    instruction = next((row for row in FundingInstruction.objects.filter(
        financial_account=crypto, kind='crypto_address', status='active').order_by('pk')
        if not row.expires_at or row.expires_at > now), None)
    if instruction is None:
        raise Refused('funding_account_unavailable',
                      'Tu cuenta local todavía no puede recibir dólares. Escríbenos por soporte.')
    try:
        validate_accounts(owner, local, crypto, destination.country)   # ownership, opening, identity, eligibility
        _require_capability(crypto, 'convert')
        _require_capability(local, 'send_third_party')
        recipient = verified_destination(instruction, owner)
    except (EligibilityDenied, EligibilityPolicyNotConfigured) as exc:
        raise Refused('rail_not_eligible', local_money.REGION_UNSUPPORTED_MESSAGE) from exc
    except (PaymentAccountError, NextError) as exc:
        logger.warning('contract funding route refused for destination %s: %s', destination.pk, exc)
        raise Refused('account_not_able', f'Tu cuenta local todavía no puede pagar por {name}. '
                                          'Escríbenos por soporte.') from exc
    return local, crypto, instruction, recipient


def require_free(owner, local, crypto, own_flow=None) -> None:
    """Never start against the owner's own send, and never make one fail.
    `own_flow`: the parked payment asking to continue, whose legs are its own.

    A journey reserves both provider accounts (live_journeys). A wallet
    bridge the owner prepared a moment ago is about to become one, so it
    goes first; it holds for at most its own short deadline. A held deposit
    would block the payout leg after conversion: wait before converting.
    """
    from .infinia_bridge import live_journeys
    from .models import InfiniaJourney, MoneyOperation
    from .payin_admission import require_source_admitted
    if live_journeys(InfiniaJourney.objects.filter(confio_account=owner)).exists():
        raise Refused('account_busy', BUSY, retry=True)
    unresolved = MoneyOperation.objects.filter(
        provider='infinia', source_account__in=[local, crypto],
        status__in=['created', 'submitted', 'processing', 'settling', 'unknown'],
    ).exclude(money_flow__infinia_journey__stage='completed')
    if own_flow is not None:
        unresolved = unresolved.exclude(money_flow_id=own_flow)
    if unresolved.exists():
        raise Refused('account_busy', BUSY, retry=True)
    if PaymentBridgeTransfer.objects.filter(
            quote__confio_account=owner, quote__source_token_id=SOURCE, funding_mode='wallet',
            quote__funding_instruction__financial_account=crypto, infinia_journey__isnull=True,
            status__in=['prepared', 'submitted'], deadline__gt=int(time.time())).exists():
        raise Refused('account_busy', BUSY, retry=True)
    for account in (local, crypto):
        try:
            require_source_admitted(account)
        except PaymentAccountError as exc:
            raise Refused('account_busy', 'Tu cuenta local tiene un depósito en revisión. '
                                          'Haremos este pago cuando se resuelva.', retry=True) from exc


# --------------------------------------------------------------- pricing

def processor_fee(local) -> dict | None:
    """The route's own invoice cost. A run collects no earlier invoice, so
    unlike a signed send it does not claim maintenance or older debt."""
    from .infinia_fee_policy import enabled
    from .infinia_fees import route_cost
    if not enabled(local.country):
        return None
    return route_cost(country=local.country, rail=local.asset, assets=[SOURCE, DESTINATION, local.asset],
                      tier=getattr(settings, 'INFINIA_PROCESSING_FEE_TIER', 0))


@dataclass
class Priced:
    local: object
    crypto: object
    instruction: object
    recipient: str
    contract: str
    units: int
    route: dict
    build: dict
    deposit: str
    recovery: str           # the owner's wallet, sent as Relay's recoveryAddress
    deadline: int
    fx_source: Decimal
    fx_target: Decimal
    fee: dict | None
    cost_usd: Decimal       # the bridge's alone; the fixed fee is `fee`
    cost_bps: int

    @property
    def rate(self) -> Decimal:
        return self.fx_target / self.fx_source

    def minimum_fx_output(self, reference_rate, tolerance_bps: int) -> Decimal:
        """The journey's floor for the conversion made after delivery: the
        manual send's tolerance on today's quote, and never under the floor
        the rule was signed with."""
        from .local_money import _tolerance
        floor = self.fx_target * (1 - _tolerance('LOCAL_MONEY_FX_TOLERANCE_BPS', 100))
        if reference_rate:
            floor = max(floor, self.fx_source * Decimal(reference_rate) * (BPS - int(tolerance_bps)) / BPS)
        return floor.quantize(CENT, rounding=ROUND_DOWN)


def fx_quote(crypto, local, minimum: Decimal, name: str) -> tuple[Decimal, Decimal]:
    """(USDC, local currency) at today's rate. A quote moves nothing."""
    from . import local_money
    from .infinia_journeys import fx_source_amount
    try:
        source = fx_source_amount(minimum)
    except PaymentAccountError as exc:
        raise Refused('amount_too_small', TOO_SMALL.format(rail=name)) from exc
    try:
        target, _ = local_money._quote(InfiniaClient(), crypto, local, source)
    except ProviderAPIError as exc:
        logger.warning('Infinia FX quote failed for %s (HTTP %s)', name, exc.status_code)
        if exc.status_code in (400, 412, 422):
            raise Refused('fx_quote_refused', f'El procesador no aceptó cotizar este pago por {name}. '
                                              'Prueba con otro monto.') from exc
        raise Refused('fx_unavailable', TRY_LATER, retry=True) from exc
    except PaymentAccountError as exc:
        raise Refused('fx_unavailable', TRY_LATER, retry=True) from exc
    return source, target


def rate_now(journey) -> Decimal:
    """Today's rate for an order reserved earlier and not funded yet."""
    bridge = journey.bridge
    minimum = Decimal(int(bridge.amount_out_min)) / Decimal(10 ** TOKENS[DESTINATION][1])
    name = ((bridge.quote.money_flow.metadata or {}).get(KEY) or {}).get('rail', '')
    source, target = fx_quote(journey.crypto_account, journey.local_account, minimum, name)
    return target / source


def require_signed_fee(fee: dict | None, ceiling, rail: str) -> None:
    """Never more than the owner signed, whatever the tariff says today."""
    if fee_usd(fee) > Decimal(ceiling):
        from . import local_money
        raise Refused('processor_fee_increased', FEE_RAISED.format(
            rail=local_money.METHODS[rail].title, now=fee_text(fee_usd(fee)), signed=fee_text(ceiling)))


def price(*, owner, destination, rail: str, contract: str, amount: Decimal, units: int,
          route=None, fee_ceiling: Decimal | None = None) -> Priced:
    """Today's one-time deposit route and FX quote for this exact exit.
    Moves nothing and writes nothing except eligibility decisions.
    `fee_ceiling`: a run's signed fee; none while a rule is being prepared."""
    from . import local_money
    from .bridge_binding import deposit_call
    from .infinia_fees import FeePricingError

    local, crypto, instruction, recipient = route or check_route(owner, destination, rail, amount)
    name = local_money.METHODS[rail].title
    contract, units = address(contract), int(units)
    try:
        fee = processor_fee(local)
    except FeePricingError as exc:
        logger.warning('Infinia fee unavailable for %s: %s', rail, exc)
        raise Refused('fee_unavailable', TRY_LATER, retry=True) from exc
    if fee_ceiling is not None:
        require_signed_fee(fee, fee_ceiling, rail)
    usdt = Decimal(units) / Decimal(10 ** TOKENS[SOURCE][1])
    if units <= 0 or (fee and usdt <= fee_usd(fee)):
        raise Refused('amount_too_small', TOO_SMALL.format(rail=name))

    try:
        recovery = address(owner.bsc_address)
        relay = OneTimeDepositRelay(recovery)
        chain.require_chain('BSC')
        quoted = relay.routes(SOURCE, DESTINATION, str(units), contract, recipient)[0]
        build = relay.build(quoted, source_address=contract, destination_address=recipient)
        deposit, _ = deposit_call(build, SOURCE, str(units))
    except RelayAmountTooSmall as exc:
        raise Refused('amount_too_small', TOO_SMALL.format(rail=name)) from exc
    except RelayError as exc:
        if exc.code in AMOUNT_TOO_LOW:
            raise Refused('amount_too_small', TOO_SMALL.format(rail=name)) from exc
        logger.warning('Relay quote failed for a contract-funded payout: %s', exc)
        raise Refused('bridge_unavailable', TRY_LATER, retry=True) from exc
    except NextError as exc:
        logger.warning('Bridge unavailable for a contract-funded payout: %s', exc)
        raise Refused('bridge_unavailable', TRY_LATER, retry=True) from exc
    if int(build['relay']['deadline']) < int(time.time()) + MIN_LIFETIME_SECONDS:
        # At prepare too: a route this short could never be funded by a run.
        raise Refused('quote_expired', TRY_LATER, retry=True)

    minimum = Decimal(int(build['amountOutMin'])) / Decimal(10 ** TOKENS[DESTINATION][1])
    expected = Decimal(int(build['amountOut'])) / Decimal(10 ** TOKENS[DESTINATION][1])
    if expected <= fee_usd(fee):
        # Outside the limit is not unlimited: the payment still covers both costs.
        raise Refused('amount_too_small', TOO_SMALL.format(rail=name))
    source, target = fx_quote(crypto, local, minimum, name)
    if target < CENT:
        raise Refused('amount_too_small', TOO_SMALL.format(rail=name))

    # What the rule's limit measures: Relay's whole cost, its fixed part
    # included, and not the processor's fixed fee (decision 36). The expected
    # output, not Relay's minimum: the minimum carries its whole slippage
    # tier (200 bps and up), which would read as cost on every run.
    cost = max(usdt - expected, Decimal(0))
    return Priced(local=local, crypto=crypto, instruction=instruction, recipient=recipient, contract=contract,
                  units=units, route=quoted, build=build, deposit=deposit, recovery=recovery,
                  deadline=int(build['relay']['deadline']),
                  fx_source=source, fx_target=target, fee=fee, cost_usd=cost,
                  cost_bps=int((cost / usdt * BPS).to_integral_value(rounding=ROUND_UP)))


def require_unused(priced: Priced) -> None:
    """As prepare_bridge does: the request must not have seen a deposit."""
    try:
        status = OneTimeDepositRelay().status(priced.build['relay']['request_id'])
    except NextError as exc:
        raise Refused('bridge_unavailable', TRY_LATER, retry=True) from exc
    if status.get('status') != 'waiting' or status.get('inTxHashes'):
        raise Refused('deposit_not_unused', TRY_LATER, retry=True)


# ----------------------------------------------------------- persistence

def persist(funding: ContractFunding, priced: Priced, *, gross_wei, minimum_fx_output: Decimal, replaces=None):
    """One order of the run (bridge and journey), or neither. Call inside
    the transaction that records the payout. `replaces`: the run's previous
    order, which must be closed unfunded."""
    from . import infinia_journeys
    from .bridge import exceeds_bridge_cap, verified_destination
    from .bridge_execution import execution_enabled

    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('persist() runs inside the payout transaction')
    terms = funding.terms()
    owner = terms['owner']
    owner = type(owner).objects.select_for_update().get(pk=owner.pk)
    stored = record(terms)
    destination = terms['destination']
    if (priced.contract != stored['contract'] or exceeds_bridge_cap(terms['amount'])
            # The exit is out of this rule's amount, never above it.
            or not 0 < priced.units <= int(Decimal(stored['amount']) * 10 ** 18)):
        raise Refused('authorization_changed', TRY_LATER, retry=True)
    require_signed_fee(priced.fee, stored['fee_ceiling'], stored['rail'])
    require_free(owner, priced.local, priced.crypto)
    execution_enabled(SOURCE)
    priced.instruction.refresh_from_db()
    if verified_destination(priced.instruction, owner) != priced.recipient:
        raise Refused('funding_account_changed', TRY_LATER, retry=True)
    if priced.deadline < int(time.time()) + MIN_LIFETIME_SECONDS:
        raise Refused('quote_expired', TRY_LATER, retry=True)
    if (priced.deposit in (stored['contract'], stored['vault'], priced.recipient)
            or PaymentBridgeTransfer.objects.filter(deposit_address__iexact=priced.deposit).exists()):
        raise Refused('deposit_address_reused', TRY_LATER, retry=True)

    attempt, linkage = 1, {}
    if replaces is not None:
        previous = PaymentBridgeTransfer.objects.select_related('quote__money_flow').get(pk=replaces.pk)
        bound = (previous.quote.money_flow.metadata or {}).get(KEY) or {}
        if (bound.get('run') != stored['run'] or previous.status != 'expired' or previous.source_tx_hash
                or ((previous.binding or {}).get(KEY) or {}).get('reported')):
            raise Refused('payout_in_progress', 'Este pago ya está en curso.', retry=True)
        attempt = int(bound.get('attempt') or 1) + 1
        linkage = {'replaces': str(previous.internal_id)}
    name = f'contract-funded-run:{stored["run"]}' + (f':{attempt}' if attempt > 1 else '')
    request_id = uuid.uuid5(uuid.UUID(stored['authorization']), name)
    if PaymentBridgeQuote.objects.filter(confio_account=owner, request_id=request_id).exists():
        raise Refused('run_already_has_a_bridge', 'Este pago ya está en curso.', retry=True)
    details = dict(
        stored, units=str(priced.units), gross_wei=str(gross_wei) if gross_wei is not None else None,
        cost_bps=priced.cost_bps, rate=str(priced.rate), fee=priced.fee, attempt=attempt, **linkage)
    flow = MoneyFlow.objects.create(
        confio_account=owner, kind='withdraw', status='processing', source_asset='USDT_BSC',
        source_amount=Decimal(stored['amount']), target_asset='USDC_POL',
        metadata={'purpose': 'provider_bridge_funding', 'stage': 'awaiting_contract_funding',
                  'local_destination_id': stored['destination'],
                  'gross_spend_units': str(int(Decimal(stored['amount']) * 10 ** 18)), KEY: details})
    quote = PaymentBridgeQuote.objects.create(
        confio_account=owner, request_id=request_id, money_flow=flow, funding_instruction=priced.instruction,
        source_address=stored['contract'], destination_address=priced.recipient,
        amount_units=str(priced.units), source_token_id=SOURCE, destination_token_id=DESTINATION,
        routes=[priced.route], expires_at=datetime.fromtimestamp(priced.deadline, tz=dt_timezone.utc))
    try:
        with transaction.atomic():
            bridge = PaymentBridgeTransfer.objects.create(
                quote=quote, funding_mode=MODE, status='submitted', deposit_address=priced.deposit,
                amount_out_min=priced.build['amountOutMin'], amount_out=priced.build['amountOut'],
                deadline=priced.deadline, calls=[],
                binding=dict(priced.build['relay'],
                             funding={'wallet_usdt_units': '0', 'fee_units': '0', 'gross_redeem_units': '0'},
                             **{KEY: {'sender': stored['vault'], 'recovery': priced.recovery, 'reported': []}}))
    except IntegrityError as exc:
        raise Refused('deposit_address_reused', TRY_LATER, retry=True) from exc
    try:
        journey = infinia_journeys.create_journey(
            owner=owner, local_account=priced.local, crypto_account=priced.crypto, request_id=request_id,
            minimum_fx_output=minimum_fx_output, direction='to_bank', bridge=bridge, destination=destination,
            funding=funding)
    except infinia_journeys.JourneyBusy as exc:
        raise Refused('account_busy', BUSY, retry=True) from exc
    return bridge, journey


def authorize_journey(funding, *, owner, destination, bridge, local_account) -> dict:
    """create_journey's gate in place of the per-journey Face grant: the live
    standing authorization, bound to this very bridge. Returns what the
    journey records."""
    if type(funding) is not ContractFunding:
        raise PaymentAccountError(OWNER_REFUSAL)
    terms = funding.terms()
    stored = record(terms)
    quote = bridge.quote
    bound = (quote.money_flow.metadata or {}).get(KEY) or {}
    if (bridge.funding_mode != MODE or bridge.batch_id or bridge.calls or bridge.source_tx_hash
            or any(bound.get(key) != value for key, value in stored.items())
            or stored['owner'] != owner.pk or quote.confio_account_id != owner.pk
            or stored['destination'] != str(destination.internal_id)
            or quote.source_address != stored['contract']
            or str(quote.amount_units) != str(bound.get('units'))
            or quote.money_flow.source_amount != Decimal(stored['amount'])
            or local_account.asset != destination.asset
            or ((bridge.binding or {}).get(KEY) or {}).get('sender') != stored['vault']):
        raise PaymentAccountError('The bridge does not match its standing authorization')
    require_owner(owner)
    return dict(bound, face_action_key=terms.get('face_action_key', ''))


def check_resume(funding: ContractFunding, bridge) -> None:
    """A retry may only send the same bridge, unchanged and still open."""
    stored = record(funding.terms())
    quote = bridge.quote
    bound = (quote.money_flow.metadata or {}).get(KEY) or {}
    data = (bridge.binding or {}).get(KEY) or {}
    if any(bound.get(key) != value for key, value in stored.items()):
        raise Refused('authorization_changed', 'La regla cambió. Lo intentaremos en la próxima fecha.')
    if (bridge.funding_mode != MODE or bridge.status != 'submitted' or bridge.source_tx_hash
            or data.get('reported') or bridge.deadline < int(time.time()) + MIN_LIFETIME_SECONDS):
        raise Refused('provider_quote_expired', 'No se pudo completar a tiempo. Lo intentaremos en la próxima fecha.')
    owner, destination = quote.confio_account, funding.terms()['destination']
    *_, recipient = check_route(owner, destination, stored['rail'], Decimal(stored['amount']))
    if recipient != quote.destination_address:
        raise Refused('funding_account_changed', 'Tu cuenta local cambió. Lo intentaremos en la próxima fecha.')


# --------------------------------------------------------- funding proof

def _locked(bridge_pk):
    """Journey first, then bridge: the order every journey worker uses."""
    from .models import InfiniaJourney
    journey = InfiniaJourney.objects.select_for_update(of=('self',)).select_related('money_flow').filter(
        bridge_id=bridge_pk).first()
    if journey is not None:
        # The join is as it was before the wait for the lock.
        journey.money_flow.refresh_from_db()
    bridge = PaymentBridgeTransfer.objects.select_for_update(of=('self',)).select_related(
        'quote__money_flow').get(pk=bridge_pk)
    if bridge.funding_mode != MODE:
        raise PaymentAccountError('Not a contract-funded bridge')
    return journey, bridge


def _set_flow(flow, status: str, stage: str) -> None:
    flow.refresh_from_db()
    flow.status = status
    flow.metadata = dict(flow.metadata, stage=stage)
    flow.save(update_fields=['status', 'metadata', 'updated_at'])


def lock_fundable(bridge_pk) -> bool:
    """The sender's half of send-or-close (smart_account.payouts.lock_sendable):
    inside the transaction that records the signed executeRule, so a closer
    waiting on these locks then sees that row and refuses."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('lock_fundable() runs inside the transaction that records the send')
    journey, bridge = _locked(bridge_pk)
    return (bridge.status == 'submitted' and not bridge.source_tx_hash
            and not ((bridge.binding or {}).get(KEY) or {}).get('reported')
            and journey is not None and journey.stage == 'awaiting_credit'
            and bridge.deadline >= int(time.time()) + MIN_LIFETIME_SECONDS)


def close_unfunded(bridge_pk) -> bool:
    """Nothing was broadcast for this bridge and nothing can be: close it and
    its journey so they stop holding the owner's accounts. Never one with a
    hash, and never while a relayer transaction of its run may land (asked
    under the bridge's lock: lock_fundable)."""
    from smart_account.infinia_payouts import funding_may_land
    from .infinia_journeys import _state
    with transaction.atomic():
        journey, bridge = _locked(bridge_pk)
        data = bridge.binding.get(KEY) or {}
        if bridge.source_tx_hash or data.get('reported') or not (
                bridge.status == 'submitted'
                or (bridge.status == 'needs_review' and bridge.failure_code == 'contract_funding_unreported')):
            return bridge.status == 'expired'
        run = ((bridge.quote.money_flow.metadata or {}).get(KEY) or {}).get('run')
        if run and funding_may_land(run, bridge.pk):
            return False
        bridge.status, bridge.failure_code = 'expired', 'payout_not_sent'
        bridge.save(update_fields=['status', 'failure_code', 'updated_at'])
        _set_flow(bridge.quote.money_flow, 'failed', 'expired')
        if journey is not None and not journey.funding_credit_id and journey.stage in ('awaiting_credit', 'needs_review'):
            _state(journey, 'failed', failure='bridge_expired')
    return True


def report_funding(bridge_pk, tx_hash) -> None:
    """The executeRule hash that funded this bridge. Only the payout path
    calls this. It proves nothing: the receipt does. On a closed bridge it
    reopens review, never the payment."""
    from .infinia_journeys import _state
    tx_hash = str(tx_hash or '').lower()
    if not TX_HASH.fullmatch(tx_hash):
        raise PaymentAccountError('Invalid funding transaction hash')
    with transaction.atomic():
        journey, bridge = _locked(bridge_pk)
        if bridge.source_tx_hash:
            if bridge.source_tx_hash.lower() != tx_hash:
                alert(f'segundo financiamiento reportado para el puente {bridge.internal_id}: {tx_hash}. '
                      'No se paga otra vez; revisar a mano.', f'contract_funding_second:{bridge.pk}:{tx_hash}')
            return
        data = dict(bridge.binding.get(KEY) or {})
        reported = list(data.get('reported') or [])
        if tx_hash not in reported:
            reported.append(tx_hash)
        data['reported'] = reported
        closed = bridge.status in ('expired', 'failed') or (journey is not None and journey.stage == 'failed')
        if closed and not data.get('late'):
            data['late'] = True
            bridge.status, bridge.failure_code = 'needs_review', 'contract_late_funding'
            _set_flow(bridge.quote.money_flow, 'needs_review', 'needs_review')
            if journey is not None:
                _state(journey, 'needs_review', failure='contract_late_funding')
            alert(f'llegó dinero para un pago ya cerrado (puente {bridge.internal_id}, tx {tx_hash}). '
                  'No se paga solo; revisar a mano.', f'contract_funding_late:{bridge.pk}')
        elif (bridge.failure_code == 'contract_funding_unreported'
                and journey is not None and journey.stage != 'needs_review'):
            bridge.status, bridge.failure_code = 'submitted', ''
        bridge.binding = dict(bridge.binding, **{KEY: data})
        bridge.save(update_fields=['binding', 'status', 'failure_code', 'updated_at'])


def _review(bridge, code: str, text: str):
    changed = PaymentBridgeTransfer.objects.filter(pk=bridge.pk, source_tx_hash='').exclude(
        status='needs_review', failure_code=code).exclude(
        failure_code='contract_late_funding').update(
            status='needs_review', failure_code=code, updated_at=timezone.now())
    if changed:
        alert(f'{text} (puente {bridge.internal_id}). Revisar a mano.', f'contract_funding:{bridge.pk}:{code}')


def signed_terms_problem(bridge, tx_hash: str, units) -> str:
    """'' while what the chain executed is what the owner signed for this
    order (smart_account.payouts.execution_problem)."""
    from smart_account import payouts
    from smart_account.models import SmartAccountRule
    bound = (bridge.quote.money_flow.metadata or {}).get(KEY) or {}
    rule = SmartAccountRule.all_objects.select_related('smart_account').filter(
        internal_id=bound.get('rule')).first() if bound.get('rule') else None
    if rule is None or address(rule.smart_account.contract_address) != bound.get('contract'):
        return 'rule_not_found'
    return payouts.execution_problem(
        rule=rule, deposit=bridge.deposit_address, tx_hash=tx_hash, funded_units=units,
        amount=bound.get('amount'), payout_refs=[bound.get('payout_ref')], setting=bound.get('rule_event') or '')


def _park(journey, code: str) -> None:
    """A parked journey is not live and has nothing half-made reserving the
    accounts, so it does not hold the owner's own sends."""
    from .infinia_journeys import _close_never_submitted, _state
    if journey is None:
        return
    if journey.stage != 'needs_review' or journey.failure_code not in (
            TERMS_CHANGED, PAYEE_CHANGED, 'contract_late_funding'):
        _state(journey, 'needs_review', failure=code)
    for operation in (journey.fx_operation, journey.payout_operation):
        if operation is not None:
            _close_never_submitted(operation)


def park_terms_changed(bridge, journey, reason: str) -> None:
    """Tracked and never paid automatically."""
    _park(journey, TERMS_CHANGED)
    alert(f'lo que ejecutó el contrato no es lo que firmó el dueño ({reason}; puente {bridge.internal_id}, '
          f'tx {bridge.source_tx_hash}). No se convierte ni se paga; revisar a mano.',
          f'contract_funding_terms:{bridge.pk}')


def park_payee_changed(journey, reason: str) -> None:
    """The money stays where it is, in the owner's own account."""
    _park(journey, PAYEE_CHANGED)
    alert(f'quien recibe ya no es quien firmó el dueño o no se pudo confirmar ({reason}; puente '
          f'{journey.bridge.internal_id}). No se paga solo; revisar a mano.',
          f'contract_funding_payee:{journey.bridge_id}')


def park_not_payable(journey, reason: str) -> None:
    _park(journey, NOT_PAYABLE)
    alert(f'el dueño o sus cuentas no pueden pagar ahora ({reason}; puente {journey.bridge.internal_id}). '
          'No se paga solo; revisar a mano.', f'contract_funding_not_payable:{journey.bridge_id}')


def owner_problem(journey_pk) -> str:
    """The owner gate of a run, asked again of funded money before it converts
    or pays. Before the journey is locked: the gate may take the user's row."""
    from .models import InfiniaJourney
    journey = InfiniaJourney.objects.select_related('confio_account__user').filter(
        pk=journey_pk, direction='to_bank', bridge__funding_mode=MODE).exclude(
        stage__in=('completed', 'failed')).first()
    return owner_refusal(journey.confio_account) if journey is not None else ''


def owner_refusal(owner) -> str:
    try:
        require_owner(owner)
    except Refused as exc:
        return exc.code
    return ''


def rate_allowed(journey, source: Decimal, target: Decimal) -> bool:
    """The signed floor is a rate: target over source, on this very quote."""
    floor = ((journey.bridge.quote.money_flow.metadata or {}).get(KEY) or {}).get('fx_floor')
    if not floor:
        return False        # an order that says nothing authorizes no rate
    return target >= source * Decimal(floor)


def rate_passed(journey) -> None:
    """A quote inside the limits: a later refusal waits its own hour."""
    flow = journey.money_flow
    if (flow.metadata or {}).get('fx_wait_since'):
        flow.metadata = {key: value for key, value in flow.metadata.items() if key != 'fx_wait_since'}
        flow.save(update_fields=['metadata', 'updated_at'])


def rate_refused(journey) -> None:
    """No quote inside the limits for money already out: asked again,
    untold, for RATE_WAIT_SECONDS; then parked, the owner told, ops alerted."""
    flow, now = journey.money_flow, timezone.now()
    since = parse_datetime(str((flow.metadata or {}).get('fx_wait_since') or ''))
    if since is None:
        flow.metadata = dict(flow.metadata or {}, fx_wait_since=now.isoformat())
        flow.save(update_fields=['metadata', 'updated_at'])
        return
    if (now - since).total_seconds() < RATE_WAIT_SECONDS:
        return
    _park(journey, RATE_OUTSIDE)
    bound = (journey.bridge.quote.money_flow.metadata or {}).get(KEY) or {}
    alert(f'no hubo una tasa dentro del límite firmado (puente {journey.bridge.internal_id}). Los dólares '
          'siguen en la cuenta Infinia del dueño y no se pagan por debajo: volver a revisar o devolver a mano.',
          f'contract_funding_rate:{journey.bridge_id}')

    def tell():
        from smart_account import notifications
        notifications.safe(notifications.payout_rate_held, bound.get('run'), bound.get('amount'))
    transaction.on_commit(tell)


def replay_refusal(operation) -> str:
    """Why a contract-funded leg may not be sent again ('' to send, and for
    every other operation). After a 429 the replay is the first request that
    arrives, so the owner and the payee are asked as before a first one.
    Refused for REPLAY_REFUSED_PARK_SECONDS, the leg and its journey are
    parked (they stop holding the owner's accounts) and ops told once."""
    from smart_account import payouts
    from .models import InfiniaJourney, MoneyOperation
    if operation.provider != 'infinia' or not operation.money_flow_id:
        return ''
    journey = InfiniaJourney.objects.select_related('confio_account__user', 'bridge__quote__money_flow').filter(
        money_flow_id=operation.money_flow_id, direction='to_bank', bridge__funding_mode=MODE).first()
    if journey is None:
        return ''
    problem, waiting = owner_refusal(journey.confio_account), False
    if not problem:
        destination, authorization = _signed_payee(journey)
        if destination is not None and authorization is not None:
            payouts.refresh_funded_payee(destination, authorization)
        problem, waiting = payee_problem(journey)
    if not problem:
        _refused_since(operation, None)     # passes: the next refusal starts a new day
        return ''
    if waiting:
        return problem      # the bank has not answered yet: a wait, not a refusal
    since = _refused_since(operation, timezone.now())
    if (timezone.now() - since).total_seconds() > REPLAY_REFUSED_PARK_SECONDS:
        with transaction.atomic():
            parked = MoneyOperation.objects.filter(pk=operation.pk, status='unknown').update(
                status='needs_review', failure_code=REPLAY_REFUSED, updated_at=timezone.now(),
                failure_detail=f'Replay refused since {since.isoformat()}: {problem}')
            if parked:
                owner_held = bool(owner_refusal(journey.confio_account))
                _park(journey, NOT_PAYABLE if owner_held else PAYEE_CHANGED)
                alert(f'una operación sin respuesta lleva más de un día sin poder reenviarse ({problem}; '
                      f'operación {operation.internal_id}, puente {journey.bridge.internal_id}). Se detiene con su '
                      'pago y no se reenvía sola; revisar a mano si se creó o si hay que devolver.',
                      f'contract_funding_replay_parked:{operation.pk}')
        return problem
    if problem:
        alert(f'una operación sin respuesta no se reenvía ({problem}; operación {operation.internal_id}). Se sigue '
              'consultando y se reenvía solo si vuelve a poder pagarse; revisar si hace falta devolver a mano.',
              f'contract_funding_replay:{operation.pk}')
    return problem


def _refused_since(operation, now):
    """When the replay of this operation was first refused: recorded at
    `now` if not yet, cleared with now=None."""
    from .models import MoneyOperation
    data = dict(MoneyOperation.objects.filter(pk=operation.pk).values_list('provider_data', flat=True).first() or {})
    if now is None:
        if REPLAY_REFUSED_SINCE in data:
            data.pop(REPLAY_REFUSED_SINCE)
            # Only while it is still unanswered: an answer in between keeps what it wrote.
            MoneyOperation.objects.filter(pk=operation.pk, status='unknown').update(provider_data=data)
        return None
    since = parse_datetime(str(data.get(REPLAY_REFUSED_SINCE) or ''))
    if since is None:
        since = now
        data[REPLAY_REFUSED_SINCE] = now.isoformat()
        MoneyOperation.objects.filter(pk=operation.pk, status='unknown').update(provider_data=data)
    return since


def payout_unsent(journey) -> bool:
    operation = journey.payout_operation
    return operation is None or (operation.status == 'created' and operation.submitted_at is None)


def _signed_payee(journey):
    """(the saved row as it is now, the authorization the order was opened under)."""
    from smart_account.models import SmartAccountStandingAuthorization
    from .models import PayoutDestination
    bound = (journey.bridge.quote.money_flow.metadata or {}).get(KEY) or {}
    return (PayoutDestination.objects.filter(internal_id=bound.get('destination')).first(),
            SmartAccountStandingAuthorization.objects.filter(internal_id=bound.get('authorization')).first())


def refresh_payee(journey_pk) -> None:
    """The journey worker's network step, before it takes any lock: funded
    money whose payout is not sent yet asks about its signed holder again."""
    from smart_account import payouts
    from .models import InfiniaJourney
    journey = InfiniaJourney.objects.select_related('bridge__quote__money_flow', 'payout_operation').filter(
        pk=journey_pk, direction='to_bank', bridge__funding_mode=MODE).exclude(
        stage__in=('completed', 'failed', 'needs_review')).first()
    if journey is None or not journey.bridge.provider_credit_id or not payout_unsent(journey):
        return
    destination, authorization = _signed_payee(journey)
    if destination is not None and authorization is not None:
        payouts.refresh_funded_payee(destination, authorization)


def payee_problem(journey) -> tuple[str, bool]:
    """(why funded money may not be paid, whether to wait for the bank
    instead of parking). Asked before converting and before paying."""
    from smart_account import payouts
    if not (journey.funding_credit_id or journey.bridge.provider_credit_id):
        return '', False        # nothing has arrived to pay
    destination, authorization = _signed_payee(journey)
    if destination is None or authorization is None:
        return 'payee_not_found', False
    problem = payouts.funded_payee_problem(destination, authorization)
    waiting = (problem == payouts.PAYEE_PENDING
               and int(time.time()) <= journey.bridge.deadline + REVIEW_AFTER_SECONDS)
    return problem, waiting


def before_paying(journey) -> str:
    """The journey worker asks before converting and before paying out."""
    bridge = journey.bridge
    if not bridge.source_tx_hash:
        return ''
    data = (bridge.binding or {}).get(KEY) or {}
    return data.get('terms_changed') or signed_terms_problem(
        bridge, bridge.source_tx_hash, data.get('funded_units'))


def signed_usd(journey) -> Decimal:
    return Decimal(journey.bridge.quote.money_flow.metadata[KEY]['amount'])


def _bind(bridge_pk, tx_hash: str, units: int):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [f'contract_funding:{tx_hash}'])
        journey, bridge = _locked(bridge_pk)
        if bridge.source_tx_hash:
            return bridge
        if PaymentBridgeTransfer.objects.filter(source_tx_hash__iexact=tx_hash).exclude(pk=bridge.pk).exists():
            _review(bridge, 'funding_hash_claimed', 'una transacción reportada ya financió otro puente')
            bridge.refresh_from_db()
            return bridge
        problem = signed_terms_problem(bridge, tx_hash, units)
        if problem == EVENT_NOT_SEEN:
            problem = ''        # asked again before anything is converted or paid
        data = dict(bridge.binding[KEY], funded_units=str(units), **({'terms_changed': problem} if problem else {}))
        bridge.binding = dict(bridge.binding, **{KEY: data})
        # Bound either way: delivery and refund are still followed.
        bridge.source_tx_hash, bridge.status, bridge.failure_code = tx_hash, 'submitted', ''
        bridge.save(update_fields=['binding', 'source_tx_hash', 'status', 'failure_code', 'updated_at'])
        if problem:
            park_terms_changed(bridge, journey, problem)
        excess = units - int(bridge.quote.amount_units)
        if excess > 0:
            alert(f'el puente {bridge.internal_id} recibió {excess} wei de USDT más de lo cotizado.',
                  f'contract_funding_excess:{bridge.pk}')
    return bridge


def prove_funding(transfer):
    """The worker's step while the bridge has no proven source hash. Returns
    the bridge as it is afterwards."""
    bridge = PaymentBridgeTransfer.objects.select_related('quote__money_flow', 'quote__confio_account').get(
        pk=transfer.pk)
    if bridge.source_tx_hash:
        return bridge
    data = bridge.binding.get(KEY) or {}
    now = int(time.time())
    reported = data.get('reported') or []
    if not reported:
        if bridge.status not in ('submitted', 'needs_review') or now <= bridge.deadline + CLOSE_AFTER_SECONDS:
            return bridge
        from smart_account.infinia_payouts import funding_may_land
        if not funding_may_land((bridge.quote.money_flow.metadata[KEY])['run'], bridge.pk):
            close_unfunded(bridge.pk)
        elif now > bridge.deadline + REVIEW_AFTER_SECONDS:
            # A call is on the wire or confirmed and its event never came:
            # stop holding the owner's accounts and let ops look.
            _review(bridge, 'contract_funding_unreported',
                    'un executeRule puede haber pagado y su hash no se reportó')
    else:
        sender, expected = data['sender'], int(bridge.quote.amount_units)
        waiting, claimed = False, False
        for tx_hash in reported:
            receipt = chain.final_receipt('BSC', tx_hash)
            if receipt is None:
                waiting = True
                continue
            # From the vault only. It pays usdtOut >= minUsdtOut, so more
            # than the quote still funds this bridge; less never does.
            units = chain.received_units(receipt, SOURCE, bridge.deposit_address, sender)
            if units < expected:
                continue
            if PaymentBridgeTransfer.objects.filter(source_tx_hash__iexact=tx_hash).exclude(pk=bridge.pk).exists():
                claimed = True
                continue
            return _bind(bridge.pk, tx_hash, units)
        if waiting:
            if now > bridge.deadline + REVIEW_AFTER_SECONDS:
                _review(bridge, 'source_confirmation_delayed', 'el financiamiento reportado sigue sin recibo final')
        elif claimed:
            _review(bridge, 'funding_hash_claimed', 'una transacción reportada ya financió otro puente')
        else:
            _review(bridge, 'source_transfer_mismatch',
                    'la transacción reportada no pagó el depósito esperado desde la bóveda')
    bridge.refresh_from_db()
    return bridge


# ------------------------------------------------------ continuing a park

def reopen(bridge_pk, codes=RECHECKABLE) -> None:
    """A parked payment goes back to the journey worker only while all of
    it passes as it is now: executed terms, payee, owner, accounts. It picks
    no amount, recipient or rate: the worker quotes inside the signed floor.
    Raises Refused and then changes nothing."""
    from smart_account import payouts
    from .infinia_journeys import _state, has_refund, validate_accounts
    from .models import InfiniaJourney
    parked = InfiniaJourney.objects.select_related(
        'confio_account__user', 'local_account', 'crypto_account', 'bridge__quote__money_flow').filter(
        bridge_id=bridge_pk, bridge__funding_mode=MODE).first()
    if parked is None or parked.stage != 'needs_review' or parked.failure_code not in codes:
        raise Refused('not_parked', 'Este pago no está detenido por algo que se pueda volver a revisar.')
    if parked.bridge.status != 'delivered' or not parked.bridge.provider_credit_id:
        raise Refused('not_delivered', 'El dinero no está acreditado en la cuenta Infinia del dueño.', retry=True)
    if ((parked.bridge.binding or {}).get(KEY) or {}).get('late'):
        raise Refused('late_funding', 'Llegó para un pago ya cerrado: solo se devuelve a mano.')
    # Before the network: two live journeys would each wait for the other.
    require_free(parked.confio_account, parked.local_account, parked.crypto_account, parked.money_flow_id)
    destination, authorization = _signed_payee(parked)
    if destination is not None and authorization is not None:
        payouts.refresh_funded_payee(destination, authorization)
    held = owner_refusal(parked.confio_account)
    with transaction.atomic():
        journey, bridge = _locked(bridge_pk)
        if journey.stage != 'needs_review' or journey.failure_code != parked.failure_code:
            raise Refused('not_parked', 'Este pago cambió. Recarga la página.', retry=True)
        owner = type(parked.confio_account).objects.select_for_update().get(pk=journey.confio_account_id)
        # A leg closed only because it was parked; rolled back on any refusal.
        legs = journey.money_flow.operations.filter(pk__in=[
            pk for pk in (journey.fx_operation_id, journey.payout_operation_id) if pk])
        legs.filter(status='failed', failure_code='never_submitted', submitted_at__isnull=True).update(
            status='created', failure_code='', updated_at=timezone.now())
        if not payout_unsent(journey) or any(has_refund(leg) for leg in legs):
            raise Refused('payout_already_sent', 'Ya salió o se devolvió un tramo: se resuelve a mano.')
        data = dict((bridge.binding or {}).get(KEY) or {})
        problem = signed_terms_problem(bridge, bridge.source_tx_hash, data.get('funded_units'))
        if problem == EVENT_NOT_SEEN:
            raise Refused(problem, 'El evento de este pago todavía no se registró.', retry=True)
        if problem:
            raise Refused(TERMS_CHANGED, problem)
        problem, _waiting = payee_problem(journey)
        if problem == payouts.PAYEE_PENDING:
            # No answer is a delay, not another payee.
            raise Refused(problem, 'El banco todavía no confirma a quien recibe.', retry=True)
        if problem:
            raise Refused(PAYEE_CHANGED, problem)
        if held:
            raise Refused(NOT_PAYABLE, held)
        require_free(owner, journey.local_account, journey.crypto_account, journey.money_flow_id)
        try:
            validate_accounts(owner, journey.local_account, journey.crypto_account,
                              journey.destination_snapshot['country'])
        except (PaymentAccountError, EligibilityDenied, EligibilityPolicyNotConfigured) as exc:
            raise Refused(NOT_PAYABLE, 'account_not_able') from exc
        if data.pop('terms_changed', None):
            bridge.binding = dict(bridge.binding, **{KEY: data})
            bridge.save(update_fields=['binding', 'updated_at'])
        if journey.failure_code == REQUOTES_USED:
            flow = journey.money_flow
            flow.metadata = dict(flow.metadata or {}, fx_requote_count=0)
            flow.save(update_fields=['metadata', 'updated_at'])
        _state(journey, 'paying_out' if journey.payout_operation_id else
               'converting' if journey.fx_operation_id else 'awaiting_credit')


def reopen_delayed(bridge_pk) -> None:
    """A delay alone parked it, and it is proven delivered and credited now
    (the payout mirror asks every minute). What fails for good is parked
    under its own reason and no longer asked."""
    from django.core.cache import cache
    from smart_account.payouts import PAYEE_PENDING
    waiting_for_bank = f'contract_funding_payee_wait:{bridge_pk}'
    if cache.get(waiting_for_bank):
        return
    try:
        reopen(bridge_pk, (DELAYED,))
    except Refused as exc:
        if exc.code == PAYEE_PENDING:
            cache.set(waiting_for_bank, True, PAYEE_RETRY_SECONDS)
            return
        park = {PAYEE_CHANGED: park_payee_changed, NOT_PAYABLE: park_not_payable,
                TERMS_CHANGED: lambda journey, reason: park_terms_changed(journey.bridge, journey, reason),
                }.get(exc.code)
        if park is None:
            return
        with transaction.atomic():
            journey, bridge = _locked(bridge_pk)
            if journey is not None and journey.stage == 'needs_review' and journey.failure_code == DELAYED:
                journey.bridge = bridge
                park(journey, exc.message)


def needs_manual_refund(status: dict) -> bool:
    """No automatic refund follows (MANUAL_REFUND_REQUIRED and the like)."""
    state = status.get('status')
    return (state in ('failure', 'refund') and status.get('refundFailReason') not in (None, '', 'N/A')
            and (state == 'failure' or not status.get('txHashes')))


def _following(transfer) -> dict:
    return (getattr(transfer, 'binding', None) or {}).get(KEY) or {}


def _remember(transfer, **values) -> None:
    """What was learned about this deposit, kept now: the pass may still
    fail, and the next one must not look it up again."""
    binding = getattr(transfer, 'binding', None) or {}
    if isinstance(transfer, PaymentBridgeTransfer):
        with transaction.atomic():
            rows = PaymentBridgeTransfer.objects.filter(pk=transfer.pk)
            stored = rows.select_for_update().values_list('binding', flat=True).first() or binding
            binding = dict(stored, **{KEY: dict(stored.get(KEY) or {}, **values)})
            rows.update(binding=binding)
        transfer.binding = binding
        return
    transfer.binding = dict(binding, **{KEY: dict(binding.get(KEY) or {}, **values)})
    keep = getattr(transfer, 'remember', None)      # an order kept elsewhere (ramps.pagoasap_send)
    if keep is not None:
        keep(values)


def _deposit_key(transfer) -> str:
    return f'{transfer.deposit_address}:{transfer.source_tx_hash}'.lower()


def follow_request(transfer, client) -> tuple[str, dict] | None:
    """(request id, its status) of OUR deposit's request. Found once by
    settlement_request, then followed by id; only an id found for this very
    deposit and funding hash is followed. While it is not final it is looked
    up again now and then (a regenerated fill, a child refund), and before
    one is called a manual refund both lookups have answered since it was
    found. Raises relay_lookups.Held when a rate limit left that unknown."""
    bound = _following(transfer).get('relay_request') or {}
    if (bound.get('deposit'), bound.get('tx')) != (transfer.deposit_address.lower(),
                                                    transfer.source_tx_hash.lower()):
        bound = {}
    request_id = bound.get('id') or settlement_request(transfer, client)
    if not request_id:
        return None
    status = client.status(request_id)
    manual = needs_manual_refund(status)
    if status.get('status') in FINAL and not manual:
        relay_lookups.done(_deposit_key(transfer))
        return request_id, status

    def asked_both() -> bool:
        data = _following(transfer)
        since = (data.get('relay_request') or {}).get('at', 0)
        return all((data.get('relay_lookup') or {}).get(query, 0) >= since for query in LOOKUPS)

    checked = not manual or asked_both()
    seen = _following(transfer).get('relay_lookup') or {}
    if checked and (not bound or time.time() - max(seen.values(), default=0) < RELOOK_SECONDS):
        return request_id, status
    try:
        found = settlement_request(transfer, client, known=request_id)
    except relay_lookups.Held:
        if not checked or (not manual and time.time() > transfer.deadline + REVIEW_AFTER_SECONDS):
            raise
        return request_id, status
    if found != request_id:
        request_id, status = found, client.status(found)
    if needs_manual_refund(status) and not asked_both():
        raise relay_lookups.Held()
    return request_id, status


def settlement_request(transfer, client, known: str = '') -> str | None:
    """The Relay request of OUR deposit: the one whose depositAddress names
    this address and the proven funding transaction (depositTxHash). Never
    the quote's own id and never an amount, so a stranger's first deposit is
    not this run's. None = Relay has not bound our deposit (yet); `known`
    stands while the answers name no other.

    The regenerated fill and a later deposit's refund each have their own id,
    so the address is listed; a child request is also asked for by the hash.
    Each GET takes a turn of the shared budget, the query asked longest ago
    first. Raises relay_lookups.Held when a rate limit, not Relay, is the
    answer."""
    deposit, source = transfer.deposit_address.lower(), transfer.source_tx_hash.lower()
    who = _deposit_key(transfer)
    seen = dict(_following(transfer).get('relay_lookup') or {})
    matches, started, held = {}, None, False
    for query in sorted(LOOKUPS, key=lambda name: seen.get(name, 0)):
        if not relay_lookups.take(who):
            held = True
            break
        value = transfer.deposit_address if query == 'depositAddress' else transfer.source_tx_hash
        try:
            body = client._request('GET', '/requests/v3',
                                   params={query: value, 'includePendingRequests': 'true', 'limit': 100})
        except RelayError as exc:
            if exc.status_code == 429:
                relay_lookups.refused(who)
                held = True
                break
            relay_lookups.done(who)
            raise
        relay_lookups.done(who)
        rows = body.get('requests')
        if not isinstance(rows, list):
            raise RelayError('Invalid Relay requests response')
        seen[query] = time.time()
        started = started or seen[query]
        for row in rows:
            bound = row.get('depositAddress') if isinstance(row, dict) else None
            if (not isinstance(bound, dict) or str(bound.get('address') or '').lower() != deposit
                    or str(bound.get('depositTxHash') or '').lower() != source):
                continue
            if not TX_HASH.fullmatch(str(row.get('id') or '')):
                raise RelayError('Invalid Relay request ID')
            matches[row['id'].lower()] = row
        if any(row.get('status') in FINAL for row in matches.values()):
            break
    if started is None:
        raise relay_lookups.Held()
    _remember(transfer, relay_lookup=seen)
    final = [row for row in matches.values() if row.get('status') in FINAL]
    if len(final) > 1:
        raise RelayError('More than one final Relay request claims this deposit')
    found = final or [row for row in matches.values()
                      if row.get('status') != 'waiting' and not row.get('supersededByRequestId')]
    if len(found) != 1:
        if known:
            return known
        if held and time.time() > transfer.deadline + REVIEW_AFTER_SECONDS:
            raise relay_lookups.Held()      # half an answer never makes it late
        return None
    request_id = found[0]['id']
    if request_id != known:
        _remember(transfer, relay_request={'id': request_id, 'deposit': deposit, 'tx': source, 'at': started})
    _note_recovery(transfer, found[0])
    return request_id


def lookup_held(transfer) -> None:
    """A rate limit held this pass. Nothing about the transfer changes."""
    if time.time() > transfer.deadline + THROTTLE_ALERT_SECONDS:
        alert(f'Relay limita las consultas y el puente {transfer.internal_id} sigue sin liquidar más de 2 horas '
              f'después de su plazo (depósito {transfer.deposit_address}). No se marca ni se devuelve solo: '
              'revisar el límite de la App de Relay.',
              f'contract_lookup_held:{transfer.pk}', getattr(transfer, 'provider_name', 'Infinia'))


def _note_recovery(transfer, row: dict) -> None:
    """The quote does not echo recoveryAddress; Relay's request of our
    deposit does, with the depositor who could sign a withdrawal."""
    binding = getattr(transfer, 'binding', None) or {}
    data = binding.get(KEY) or {}
    sent = str(data.get('recovery') or '').lower()
    if not sent:
        return
    try:
        signer = str(((row.get('protocol') or {})['deposit']['origin'])['depositor'] or '').lower()
    except (KeyError, TypeError, AttributeError):
        signer = ''
    recorded = str(row['depositAddress'].get('recoveryAddress') or '').lower()
    _remember(transfer, relay_recovery={'recorded': recorded, 'signer': signer})
    if recorded != sent:
        alert(f'Relay registró recoveryAddress {recorded or "vacío"} y se envió {sent} (puente '
              f'{transfer.internal_id}, depósito {transfer.deposit_address}). Revisar con Relay.',
              f'contract_recovery:{transfer.pk}', getattr(transfer, 'provider_name', 'Infinia'))


def refund_needs_a_human(transfer, request_id: str, reason) -> None:
    reason = re.sub(r'[^a-z0-9_]', '', str(reason).lower())[:60]
    transfer.status, transfer.failure_code = 'needs_review', f'relay_refund_failed_{reason}'
    data = (getattr(transfer, 'binding', None) or {}).get(KEY) or {}
    recovery, noted = str(data.get('recovery') or ''), data.get('relay_recovery') or {}
    signer = noted.get('signer') or ''
    if recovery and signer == recovery:
        way = (f'Solo la billetera del dueño {recovery} puede firmar el retiro, y Confío no tiene su llave: '
               'coordinar con el dueño y Relay.')
    else:
        way = (f'Firmante registrado en Relay: {signer or "desconocido"}; recoveryAddress: '
               f'{noted.get("recorded") or "sin confirmar"}. Pedirlo a soporte de Relay antes de prometer '
               'una devolución.')
    alert(f'Relay no devolverá solo el depósito del puente {transfer.internal_id} ({reason}; request {request_id}, '
          f'depósito {transfer.deposit_address}, tx {transfer.source_tx_hash}). El dinero está en el Depository '
          f'de Relay y el contrato no puede firmar su retiro. {way}',
          f'contract_refund_manual:{transfer.pk}:{reason}', getattr(transfer, 'provider_name', 'Infinia'))


def funded_units(bridge) -> int:
    quoted = int(bridge.quote.amount_units)
    value = ((bridge.binding or {}).get(KEY) or {}).get('funded_units')
    return max(quoted, int(value)) if value is not None and str(value).isdigit() else quoted


def record_fee_debt(journey) -> None:
    """A paid run's processor fee, as the unpaid invoice the owner's next
    signed local transfer already knows how to collect. Once per bridge."""
    from .models import InfiniaFeeDebt
    if journey.stage != 'completed' or not journey.bridge_id or journey.bridge.funding_mode != MODE:
        return
    flow = journey.bridge.quote.money_flow
    fee = ((flow.metadata or {}).get(KEY) or {}).get('fee')
    if fee and Decimal(fee['total_usd']) > 0:
        InfiniaFeeDebt.objects.get_or_create(source_flow=flow, defaults={'amount_usd': Decimal(fee['total_usd'])})
