"""Local-currency sends funded from the wallet: the provider-agnostic core.

Used by Venezuelan Pago Móvil (ramps.ve_pagomovil) and QR Bolivia
(ramps.bolivia_qr). One `RampTransaction(direction='off_ramp',
destination='cusd_plus')` per send; `provider` names the adapter (from either
registry; names are unique) that does the provider-specific steps. Phases (metadata.ve_send.phase), each move
made under the row lock:

  preparing         order saved, deposit target not ready yet
  awaiting_funding  ready; the app may claim the single funding
  funding_reported  claimed: the app got the vouched target once, paid it
                    in one sponsored batch and reported the hash (or none)
  funded            the BSC chain proves the exact USDT reached the target
                    from the user's wallet
  settled           the provider holds it (after the adapter's settlement
                    step, e.g. a bridge delivery proven on the other chain);
                    `credited_usd` is what a payout may spend
  paying            one payout attempt is at the provider under a fixed key
  payout_pending    the provider accepted it; polled until final
  paid              delivered (COMPLETED)
  payout_failed     the provider definitely did not pay; ops may correct the
                    destination and retry with a NEW key
  payout_review     the outcome cannot be known automatically; ops checks

Funding is proven on chain: one USDT Transfer from the order's wallet to its
deposit target for exactly `deposit_wei`, not claimed by another order. When
the target is shared by every send (adapter.SHARED_DEPOSIT_TARGET), each of
a sender's sends carries a distinct micro-tag in its amount, so two sends of
the same person never match the same transfer.

Money that may have moved is never released and never failed: a funded send
ends paid or in review. A payout key is replayed only inside the provider's
idempotency window; every dispatch holds a lease; every answer is fenced to
the attempt that sent it.

Adapter contract (module attributes/functions):
  PROVIDER, SHARED_DEPOSIT_TARGET, PENDING_STALE, replay_window()
  COUNTRY, FIAT, LIMIT_PREFIX (settings <prefix>_{MIN,MAX,USER_DAILY,GLOBAL_DAILY}_USD)
  beneficiary_view(beneficiary) -> dict  (optional; Venezuelan fields otherwise)
  TARGET_AT_CLAIM: the deposit target is made when the funding is claimed
    (funding_target(ramp) -> dict), else at creation (deposit_target(ramp))
    funding_target may return 'deposit_wei' (<= the reserved amount): what
    the wallet pays this target, e.g. an exact-output bridge's input
  settle(ramp) -> Settlement   (optional: funded -> settled; else immediate)
  payout_terms(ramp, inflight) -> dict | None (amount + body; None = wait;
    {'review': reason} = not payable as priced; {'wait': reason} = not
    payable at this moment: asked again for RATE_WAIT, then that review)
  dispatch(ramp, claim) -> Outcome
  poll(ramp) -> Outcome
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from ramps import ve_pagomovil
from ramps.models import RampTransaction
from ramps.ve_pagomovil import VePagoMovilError

logger = logging.getLogger(__name__)

DIRECTION = ve_pagomovil.SEND
SECTION = 've_send'
OPEN_STATUSES = ('PENDING', 'PROCESSING')
CENT = Decimal('0.01')
MICRO = Decimal('0.000001')
WEI_PER_MICRO = 10 ** 12
EVM_ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
TX_HASH_RE = re.compile(r'^0x[0-9a-fA-F]{64}$')
USDT_BSC = '0x55d398326f99059ff775485246999027b3197955'
TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
RESERVE_LOCK = 've_send:reserve'
PAYOUT_LOCK = 've_send:payout'

# The app funds right after creating the order; past this the target is no
# longer vouched for and the order can only be cancelled or expire.
FUNDING_WINDOW = timedelta(hours=2)
# A claimed funding never seen on chain closes after this.
UNFUNDED_EXPIRY = timedelta(hours=6)
# Closed-unfunded orders are still scanned this long: money that arrives
# anyway is surfaced to ops, never lost.
LATE_FUNDING_WATCH = timedelta(days=3)
# Funding claimed this long ago and still not verifiable either way: ops.
UNVERIFIABLE_AFTER = timedelta(hours=12)
# A claimed funding that reported no hash may be cancelled after this long
# with a clean chain scan (a sponsored batch is mined in seconds or never).
CLAIMED_FUNDING_QUIET = timedelta(minutes=15)
# A reported hash with no receipt this long after the report was dropped.
RECEIPT_GRACE = timedelta(minutes=30)
# Every dispatch (first send or replay) holds this lease: no review or
# new-key retry can begin while an old key may still be on its way out.
DISPATCH_LEASE = timedelta(minutes=10)
LOG_CHUNK_BLOCKS = 4_000
MAX_CHUNKS_PER_SCAN = 20
MICRO_CHUNK_BLOCKS = 50  # the strictest pool endpoint's eth_getLogs cap
# Distinct amount tags per sender on a shared target (≤ 0.009999 USDT).
MAX_AMOUNT_TAG = 9999
# A send may be funded by a contract instead of the sender of record's wallet
# (the Cuenta inteligente payout: CusdVault.redeemWithFee sends the USDT to
# the deposit address claimed for the order). That address is NOT the
# order's own by itself: it is asked as a one-time address and a used one is
# refused (start_funding), but orders made before that may share a route,
# and the amount is untagged, so an earlier order of the same account can
# look identical on chain. A contract-funded order is
# therefore proven ONLY through the executeRule hash the payout path reports
# (report_funding), by the Transfer in that transaction's receipt; it is never
# matched by a log scan, nor by the late-funding watch's scan.
# reserve(funding_sender=...) records the Transfer `from` that proof expects;
# the bridge refund still returns to actor_address. smart_account.payouts
# reads this flag before offering or running that rail.
CONTRACT_FUNDING = True
# Closed without any funding having been possible to see: the late-funding
# watch keeps these (wallet sends by scan, contract-funded by reported hash).
CLOSED_UNFUNDED = ('expired_unfunded', 'cancelled_by_user', 'payout_not_sent')
# executeRule pays the rule as stored when it is mined: a contract-funded
# order is paid only while that is what the owner signed for it (amount,
# payoutRef, authorization: smart_account.payouts.ramp_funding_problem).
TERMS_CHANGED = 'contract_funding_terms_changed'
TERMS_CHANGED_DETAIL = f'needs_review:{TERMS_CHANGED}'
# The owner may not pay now, and no rate inside the rule's signed floor.
NOT_PAYABLE = 'contract_funding_not_payable'
RATE_OUTSIDE = 'fx_quote_outside_authorization'
RATE_WAIT = timedelta(hours=1)
# An Outcome reason: this request never left (no token).
NOT_SENT = 'not_sent'
# An ambiguous answer that took nothing: the provider refused the request for
# rate (429). The key's replay window does not run on it.
RATE_LIMITED = 'rate_limited'
# Replays refused only for rate end this long after the key's first dispatch.
RATE_LIMITED_REPLAY_MAX = timedelta(hours=2)
# The executeRule event of a proven hash is not in the mirror yet: no
# evidence either way, so it waits and parks nothing.
EVENT_NOT_SEEN = 'event_not_found'
LATE_FUNDING = 'needs_review:late_funding'
PARKED_DETAILS = (TERMS_CHANGED_DETAIL, f'needs_review:{NOT_PAYABLE}', f'needs_review:{RATE_OUTSIDE}')
# A contract-funded settlement in review that may still end by itself.
SETTLEMENT_FOLLOWED = ('needs_review:settlement:relay_settlement_delayed',
                       'needs_review:settlement:relay_refund_failed_')


class VeSendError(VePagoMovilError):
    """User-facing refusal (Spanish)."""


class VeSendLimitError(VeSendError):
    """A send limit refused the amount. `passing`: a rolling daily cap that
    frees up by itself (a scheduled payout may retry its slot); otherwise a
    per-send minimum or maximum that the same amount never passes."""

    def __init__(self, message: str, *, passing: bool):
        super().__init__(message)
        self.passing = passing


@dataclass(frozen=True)
class Outcome:
    """What a provider said about one payout attempt.

    kind: paid | pending | failed (definitely not paid) | retry (definitely
    not paid, try again later with a NEW key: e.g. balance not credited yet)
    | unknown (ops must check) | ambiguous (no answer: replay the same key).
    """
    kind: str
    reference: str = ''
    operation_id: str = ''
    reason: str = ''
    ves_amount: str = ''


@dataclass(frozen=True)
class Settlement:
    """Where the funded dollars are: pending | delivered (credited_usd,
    evidence) | refunded (proven back in the user's wallet) | review."""
    kind: str
    credited_usd: str = ''
    evidence: str = ''
    reason: str = ''


def _providers() -> list[str]:
    from ramps import bolivia_qr
    return list(ve_pagomovil.SEND_ADAPTERS) + list(bolivia_qr.SEND_ADAPTERS)


def adapter(ramp_or_provider):
    provider = getattr(ramp_or_provider, 'provider', ramp_or_provider)
    if provider in ve_pagomovil.SEND_ADAPTERS:
        return ve_pagomovil.send_adapter(provider)
    from ramps import bolivia_qr
    return bolivia_qr.adapter(bolivia_qr.SEND, provider)


def _country(provider) -> str:
    return getattr(adapter(provider), 'COUNTRY', 'VE')


# ------------------------------------------------------------------ amounts

def confio_amounts(gross_usd: Decimal) -> tuple[int | None, int]:
    """(gross Confío-dollar debit in wei or None, USDT for the provider in wei).

    With the conversion fee on, the user's dollars are redeemed with fee and
    the provider receives the previewed net, floored to six decimals; the
    same preview the Koywe Retiro uses.
    """
    gross_wei = int((gross_usd * Decimal(10 ** 18)).to_integral_value(rounding=ROUND_DOWN))
    if not getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False):
        net_micro = gross_usd.quantize(MICRO, rounding=ROUND_DOWN)
        return None, int(net_micro / MICRO) * WEI_PER_MICRO
    try:
        from cusd_plus.cusd_vault import preview_redeem_wei
        preview = preview_redeem_wei(gross_wei)
        net_micro = Decimal(preview.net).quantize(MICRO, rounding=ROUND_DOWN)
    except Exception as exc:  # noqa: BLE001 — RPC / vault read
        logger.warning('cUSD fee preview failed for a VE send', exc_info=True)
        raise VeSendError('No pudimos calcular la comisión de Confío.') from exc
    deposit_wei = int(net_micro / MICRO) * WEI_PER_MICRO
    if deposit_wei <= 0:
        raise VeSendError('El monto es muy bajo.')
    return gross_wei, deposit_wei


# ------------------------------------------------------------------ limits

def counted_usd(ramp: RampTransaction) -> Decimal:
    try:
        return Decimal(str(_section(ramp).get('gross_usd') or '0'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _sends():
    return RampTransaction.objects.filter(provider__in=_providers(), direction=DIRECTION)


_FUNDING_SENDER_KEY = {f'metadata__{SECTION}__has_key': 'funding_sender'}


def _own_sends():
    """Sends the person funds from their own wallet (not contract-funded)."""
    return _sends().exclude(**_FUNDING_SENDER_KEY)


def _contract_funded_sends():
    return _sends().filter(**_FUNDING_SENDER_KEY)


def check_limits(user, gross_usd: Decimal, provider: str = 'pagoasap') -> None:
    from django.db.models import Q
    # No caps by default: the quote shows what a small send delivers, the
    # bridge refuses amounts too small to cross, and the recipient's bank
    # enforces its Pago Móvil limit. The settings stay as an emergency lever.
    prefix = getattr(adapter(provider), 'LIMIT_PREFIX', 'VE_PAGOMOVIL_SEND')
    country = _country(provider)

    def limit(suffix):
        return ve_pagomovil.optional_limit(f'{prefix}_{suffix}')

    minimum, maximum = limit('MIN_USD'), limit('MAX_USD')
    if minimum is not None and gross_usd < minimum:
        raise VeSendLimitError(f'El monto mínimo es ${minimum}.', passing=False)
    if maximum is not None and gross_usd > maximum:
        raise VeSendLimitError(f'El monto máximo por envío es ${maximum}.', passing=False)
    user_cap = limit('USER_DAILY_USD')
    global_cap = limit('GLOBAL_DAILY_USD')
    if user_cap is None and global_cap is None:
        return
    since = timezone.now() - timedelta(hours=24)
    # Every send not definitely unfunded counts, by when money can move.
    recent = list(_sends().filter(country_code=country).filter(
        Q(created_at__gte=since) | Q(status__in=OPEN_STATUSES) | Q(completed_at__gte=since),
    ).exclude(status='FAILED')
        # A parked automatic payment waits for ops: its day's, not a hold on
        # the owner's own sends for ever.
        .exclude(status_detail__in=PARKED_DETAILS, created_at__lt=since))
    user_total = sum((counted_usd(r) for r in recent if r.actor_user_id == user.pk), Decimal('0'))
    if user_cap is not None and user_total + gross_usd > user_cap:
        raise VeSendLimitError('Alcanzaste tu límite diario de envíos. Intenta mañana.', passing=True)
    global_total = sum((counted_usd(r) for r in recent), Decimal('0'))
    if global_cap is not None and global_total + gross_usd > global_cap:
        raise VeSendLimitError('Los envíos alcanzaron su cupo de hoy. Intenta más tarde.', passing=True)


def _advisory_lock(name: str) -> None:
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [name])


# ------------------------------------------------------------------ state

def _section(ramp: RampTransaction) -> dict:
    return dict((ramp.metadata or {}).get(SECTION) or {})


def _phase(ramp: RampTransaction) -> str:
    return _section(ramp).get('phase') or 'preparing'


def _update(ramp_pk: int, *, require=None, status=None, detail=None, row=None, quiet=False,
            **values) -> RampTransaction | None:
    """Merge into metadata.ve_send under the row lock, never from a stale
    copy. `require(current) -> bool` gates the write; None when it refuses.
    `row` sets model fields in the same write. `quiet`: the status changes
    without the generic ramp push (ramps.signals announces a transition it
    sees on save); the ledger still follows."""
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp_pk)
        if require is not None and not require(current):
            return None
        metadata = dict(current.metadata or {})
        section = dict(metadata.get(SECTION) or {})
        section.update(values)
        metadata[SECTION] = section
        current.metadata = metadata
        fields = ['metadata', 'updated_at']
        if status is not None:
            if quiet:
                RampTransaction.objects.filter(pk=current.pk).update(status=status)
            current.status = status
            fields.append('status')
        if detail is not None:
            current.status_detail = detail[:500]
            fields.append('status_detail')
        for name, value in (row or {}).items():
            setattr(current, name, value)
            fields.append(name)
        current.save(update_fields=fields)
        return current


def _now_iso() -> str:
    return timezone.now().isoformat()


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ''))
    except ValueError:
        return None


def can_fund(ramp: RampTransaction) -> bool:
    """The single funding claim is open only while the order is fresh."""
    return (ramp.status == 'PENDING' and _phase(ramp) == 'awaiting_funding'
            and ramp.created_at >= timezone.now() - FUNDING_WINDOW)


def can_cancel(ramp: RampTransaction) -> bool:
    if ramp.status != 'PENDING':
        return False
    phase = _phase(ramp)
    if phase in ('preparing', 'awaiting_funding'):
        return True
    section = _section(ramp)
    started = _parse_time(section.get('funding_started_at'))
    return (phase == 'funding_reported' and not section.get('funding_tx_hashes')
            and started is not None and started < timezone.now() - CLAIMED_FUNDING_QUIET)


def _watched_amounts(sender: str) -> set[int]:
    """Deposit amounts of this sender's sends that may still be matched to a
    transfer (open, or closed-unfunded inside the late watch)."""
    from django.db.models import Q
    since = timezone.now() - LATE_FUNDING_WATCH - FUNDING_WINDOW
    taken = set()
    # Every open send, however old (it may still be matched), and closed
    # ones still inside the late-funding watch.
    for ramp in _sends().filter(actor_address__iexact=sender).filter(
            Q(status__in=OPEN_STATUSES) | Q(status='FAILED', created_at__gte=since)):
        value = str(_section(ramp).get('deposit_wei') or '')
        if value.isdigit():
            taken.add(int(value))
    return taken


@transaction.atomic
def reserve(*, provider: str, user, account, gross_usd: Decimal, beneficiary: dict, gross_wei: int | None,
            deposit_wei: int, created_block: int, estimate: dict,
            funding_sender: str | None = None, funding_terms: dict | None = None) -> RampTransaction:
    """Persist the send before any provider call, under the reservation lock
    the limits need and the Account lock the wallet re-enrollment gate uses.

    funding_sender: the contract whose USDT Transfer funds the order (see
    CONTRACT_FUNDING), when it is not the wallet of record. Its amount is
    exact (no tag) and its deposit address is the order's own.
    funding_terms: the rule as signed, for such an order (TERMS_CHANGED)."""
    from users.models import Account

    if funding_sender is not None:
        funding_sender = funding_sender.strip().lower()
        if (not EVM_ADDRESS_RE.fullmatch(funding_sender)
                or funding_sender in (USDT_BSC, '0x' + '0' * 40)):
            raise VeSendError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.')
    _advisory_lock(RESERVE_LOCK)
    locked = Account.objects.select_for_update().filter(pk=account.pk, deleted_at__isnull=True).first()
    address = (getattr(locked, 'bsc_address', '') or '').strip().lower()
    if not locked or not address or address != (account.bsc_address or '').strip().lower():
        raise VeSendError('Tu billetera cambió. Vuelve a intentarlo.')
    country = _country(provider)
    if funding_sender is None:
        # One open send of the person's own at a time. A contract-funded
        # order (a Cuenta inteligente payout) is not theirs to finish or
        # cancel: it neither blocks nor is blocked by their own sends. Both
        # still count toward the limits below.
        if _own_sends().filter(actor_user=user, status='PENDING', country_code=country).exists():
            raise VeSendError('Ya tienes un envío pendiente. Termínalo o cancélalo.')
    elif _contract_funded_sends().filter(
            status='PENDING', actor_address__iexact=address,
            **{f'metadata__{SECTION}__deposit_wei': str(deposit_wei)}).exists():
        # Another open contract-funded order of this account for the same
        # amount may be handed the same deposit route: never two at once.
        raise VeSendError('Ya hay un pago igual en curso. Lo intentaremos de nuevo en unos minutos.')
    check_limits(user, gross_usd, provider)
    if adapter(provider).SHARED_DEPOSIT_TARGET and not funding_sender:
        # One deposit address for every send: a per-sender tag in the last
        # micro-units keeps each send's transfer distinguishable.
        taken = _watched_amounts(address)
        for tag in range(1, MAX_AMOUNT_TAG + 1):
            candidate = deposit_wei - tag * WEI_PER_MICRO
            if candidate not in taken:
                deposit_wei = candidate
                break
        else:
            raise VeSendError('Tienes demasiados envíos recientes. Intenta más tarde.')
    if deposit_wei <= 0:
        raise VeSendError('El monto es muy bajo.')
    usdt = (Decimal(deposit_wei) / Decimal(10 ** 18)).quantize(MICRO, rounding=ROUND_DOWN)
    # What the recipient should get in local currency (VE adapters name it
    # estimated_ves; others estimated_fiat).
    estimated_ves = Decimal(str(estimate.get('estimated_fiat') or estimate.get('estimated_ves') or '0'))
    ramp = RampTransaction(
        provider=provider,
        direction=DIRECTION,
        status='PENDING',
        country_code=country,
        actor_user=user,
        actor_type='user',
        actor_display_name=account.display_name or user.get_full_name() or user.username or '',
        # The wallet the funding transfer must come from.
        actor_address=address,
        destination='cusd_plus',
        fiat_currency=getattr(adapter(provider), 'FIAT', 'VES'),
        fiat_amount=estimated_ves or None,
        crypto_currency='USDT',
        crypto_amount_estimated=usdt,
        # The ledger records what left the wallet, like the Koywe Retiro: the
        # USDT settlement, never a bolívar figure in a dollar token.
        final_currency='USDT',
        final_amount=usdt,
        status_detail='awaiting_funding',
    )
    ramp.external_id = str(ramp.internal_id)
    ramp.metadata = {SECTION: {
        'phase': 'preparing',
        'gross_usd': format(gross_usd, 'f'),
        'gross_wei': str(gross_wei) if gross_wei is not None else None,
        'deposit_wei': str(deposit_wei),
        'beneficiary': beneficiary,
        'beneficiary_revision': 0,
        'estimate': {k: str(v) for k, v in estimate.items()},
        'estimated_ves': format(estimated_ves, 'f'),
        'estimated_fiat': format(estimated_ves, 'f'),
        'created_block': created_block,
        'payout_attempt': 0,
    }}
    if funding_sender:
        ramp.metadata[SECTION]['funding_sender'] = funding_sender
        if funding_terms:
            ramp.metadata[SECTION]['funding_terms'] = dict(funding_terms)
    if funding_sender and _fresh_order(ramp):
        # A slot's fresh order is not a new withdrawal to announce: no
        # "created" push, the same ledger row.
        RampTransaction.objects.bulk_create([ramp])
        ramp.save(update_fields=['updated_at'])
    else:
        ramp.save()
    return ramp


def _funding_sender(ramp: RampTransaction) -> str:
    """The `from` of the funding Transfer: the contract named at reserve, or
    the wallet of record."""
    return (_section(ramp).get('funding_sender') or ramp.actor_address or '').lower()


def _contract_funded(ramp: RampTransaction) -> bool:
    return bool(_section(ramp).get('funding_sender'))


def _funded_by_vault(ramp: RampTransaction) -> bool:
    """The funding sender is the configured cUSD vault (the only contract
    whose exit may carry more than the order's amount: redeemWithFee pays
    usdtOut >= minUsdtOut)."""
    vault = (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').strip().lower()
    return bool(vault) and EVM_ADDRESS_RE.fullmatch(vault) is not None and _funding_sender(ramp) == vault


def _valid_target(ramp: RampTransaction, target: str) -> bool:
    return (EVM_ADDRESS_RE.fullmatch(target or '') is not None
            and target.lower() not in (USDT_BSC, '0x' + '0' * 40, (ramp.actor_address or '').lower(),
                                       _funding_sender(ramp)))


def prepare(ramp: RampTransaction) -> RampTransaction:
    """Fix the deposit target and open the funding window. Nothing can have
    been paid yet, so a failure closes the order."""
    if getattr(adapter(ramp), 'TARGET_AT_CLAIM', False):
        # The target is made when the funding is claimed (e.g. a bridge quote
        # with a short deadline).
        updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'preparing',
                          phase='awaiting_funding', prepared_at=_now_iso())
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    try:
        target = adapter(ramp).deposit_target(ramp)
    except Exception:  # noqa: BLE001
        logger.exception('Deposit target failed for VE send %s', ramp.pk)
        target = None
    target = (target or '').strip()
    if not _valid_target(ramp, target):
        fail_unfunded(ramp, 'deposit_target_unavailable')
        raise VeSendError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.')
    updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'preparing',
                      phase='awaiting_funding', deposit_address=target.lower(), prepared_at=_now_iso())
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def hide_replaced(ramp_pk: int) -> None:
    """An attempt closed unfunded that a fresh order replaced: the slot
    keeps one row in history. Shown again if money lands on it after all
    (_mark_funded); a row support retracted is never touched."""
    from users.models_unified import UnifiedTransactionTable
    with transaction.atomic():
        if UnifiedTransactionTable.objects.filter(
                ramp_transaction_id=ramp_pk, status='FAILED', deleted_at__isnull=True).update(
                    deleted_at=timezone.now()):
            _update(ramp_pk, history_replaced_at=_now_iso())


def _show_replaced(ramp: RampTransaction) -> None:
    if _section(ramp).get('history_replaced_at'):
        from users.models_unified import UnifiedTransactionTable
        UnifiedTransactionTable.objects.filter(ramp_transaction_id=ramp.pk).update(deleted_at=None)


def _fresh_order(ramp: RampTransaction) -> bool:
    """A slot's second or later order: not announced as a withdrawal."""
    return int((_section(ramp).get('funding_terms') or {}).get('attempt') or 1) > 1


def fail_unfunded(ramp: RampTransaction, detail: str) -> RampTransaction:
    """Close an order no funding can have been sent for (never claimed). A
    contract-funded one closes quietly: its run tells the owner, and may
    still pay with another order."""
    updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING'
                      and _phase(c) in ('preparing', 'awaiting_funding'),
                      status='FAILED', detail=detail, quiet=_contract_funded(ramp))
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def _may_land(ramp: RampTransaction) -> bool:
    """A relayer transaction of this contract-funded order's slot may land."""
    if not _contract_funded(ramp):
        return False
    from smart_account.payouts import ramp_may_land
    return ramp_may_land(ramp)


def lock_fundable(ramp_pk: int, deposit: str, deposit_wei) -> RampTransaction | None:
    """The sender's half of send-or-close (smart_account.payouts.lock_sendable):
    inside the transaction that records the signed executeRule, so a closer
    waiting on this lock then sees that row and refuses."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('lock_fundable() runs inside the transaction that records the send')
    ramp = RampTransaction.objects.select_for_update().get(pk=ramp_pk)
    section = _section(ramp)
    deadline = (section.get('bridge') or {}).get('deadline')
    open_ = (ramp.status == 'PENDING' and _contract_funded(ramp) and _phase(ramp) == 'funding_reported'
             and not section.get('funding_tx_hashes')
             and str(section.get('deposit_address') or '').lower() == deposit.lower()
             and str(section.get('deposit_wei')) == str(deposit_wei)
             and (not deadline or int(deadline) >= int(timezone.now().timestamp())))
    return ramp if open_ else None


def close_unsent(ramp: RampTransaction, *, quiet: bool = False) -> RampTransaction:
    """A contract-funded order whose payout run ended without broadcasting
    the executeRule that would fund it: closed now instead of lingering to
    UNFUNDED_EXPIRY. Never one with a reported hash, nor while a relayer
    transaction of its slot may land (asked under the row's lock:
    lock_fundable). `quiet`: closed to make room for the slot's fresh order.
    Should that call land
    after all, its reported hash still proves it, into ops review
    (report_funding accepts it on a closed order; sync's late watch)."""
    updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _contract_funded(c)
                      and _phase(c) in ('preparing', 'awaiting_funding', 'funding_reported')
                      and not _section(c).get('funding_tx_hashes') and not _may_land(c),
                      status='FAILED', detail='payout_not_sent', quiet=quiet)
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def funding_details(ramp: RampTransaction) -> dict | None:
    """The vouched funding target, served only in the answer of the single
    start_funding claim, never on a read."""
    section = _section(ramp)
    address = section.get('deposit_address') or ''
    if not EVM_ADDRESS_RE.fullmatch(address) or not str(section.get('deposit_wei') or '').isdigit():
        return None
    deadline = (section.get('bridge') or {}).get('deadline')
    return {
        'deposit_address': address,
        'network': 'BSC',
        'deposit_amount_wei': str(section['deposit_wei']),
        'gross_debit_amount_wei': str(section['gross_wei']) if section.get('gross_wei') else None,
        # Unix seconds after which the target must not be funded (a bridge
        # quote's deadline), or None.
        'expires_at': int(deadline) if deadline else None,
    }


CONTRACT_FUNDED_REFUSAL = 'Este pago lo hace tu Cuenta inteligente automáticamente; no se cambia desde aquí.'


def _refuse_owner_on_contract_funded(ramp: RampTransaction, by_payout: bool) -> None:
    """A contract-funded order (a Cuenta inteligente payout) is driven only
    by the payout path (smart_account.payouts, by_payout=True). Its owner
    reaches the same functions through the app's order mutations
    (ve_pagomovil.owned_order matches actor_user): there they could claim
    the funding, push the real executeRule hash out of the five kept with
    junk ones, or cancel an order the contract is about to fund."""
    if _contract_funded(ramp) and not by_payout:
        raise VeSendError(CONTRACT_FUNDED_REFUSAL)


def _deposit_used(ramp_pk: int, deposit: str) -> bool:
    from payment_accounts.models import PaymentBridgeTransfer
    return (_sends().filter(**{f'metadata__{SECTION}__deposit_address': deposit}).exclude(pk=ramp_pk).exists()
            or PaymentBridgeTransfer.objects.filter(deposit_address__iexact=deposit).exists())


def start_funding(ramp: RampTransaction, *, by_payout: bool = False) -> RampTransaction:
    """The single right to fund this order: from here it can never be funded
    again, nor cancelled while a broadcast may still land."""
    current = RampTransaction.objects.get(pk=ramp.pk)
    _refuse_owner_on_contract_funded(current, by_payout)
    one_time = _contract_funded(current)
    values, row = {}, None
    if getattr(adapter(ramp), 'TARGET_AT_CLAIM', False):
        if not can_fund(RampTransaction.objects.get(pk=ramp.pk)):
            raise VeSendError('Este envío ya se está procesando.')
        # Made now (an HTTP call, outside any lock); kept only if this claim
        # wins. A losing claim's target is never handed out or funded.
        target = adapter(ramp).funding_target(ramp)
        address = str(target.get('deposit_address') or '').strip()
        if not _valid_target(ramp, address):
            raise VeSendError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.')
        values = {'deposit_address': address.lower(), 'bridge': target.get('binding')}
        if target.get('deposit_wei') is not None:
            # A target priced at the claim (an exact-output bridge) names what
            # the wallet pays: never more than this order reserved. The proof
            # of funding then looks for that amount.
            priced, reserved = str(target['deposit_wei']), str(_section(ramp).get('deposit_wei') or '')
            if not priced.isdigit() or not reserved.isdigit() or not 0 < int(priced) <= int(reserved):
                raise VeSendError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.')
            values['deposit_wei'] = priced
            values['reserved_deposit_wei'] = reserved
            # History and the ledger record what leaves the wallet.
            usdt = (Decimal(int(priced)) / Decimal(10 ** 18)).quantize(MICRO, rounding=ROUND_DOWN)
            row = {'crypto_amount_estimated': usdt, 'final_amount': usdt}
    reused, updated = False, None
    with transaction.atomic():
        deposit = values.get('deposit_address')
        if one_time and deposit:
            # A one-time address is this order's alone, ever.
            _advisory_lock(f've_send:deposit:{deposit}')
            reused = _deposit_used(ramp.pk, deposit)
        if not reused:
            updated = _update(ramp.pk, require=can_fund, detail='confirming_funding', row=row,
                              phase='funding_reported', funding_started_at=_now_iso(), **values)
    if reused:
        _alert(current, 'deposit_address_reused')
        raise VeSendError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.')
    if updated is None:
        raise VeSendError('Este envío ya se está procesando.')
    return updated


def report_funding(ramp: RampTransaction, tx_hash: str | None, *, by_payout: bool = False) -> RampTransaction:
    """The broadcast hash of the claimed funding (or none when its outcome is
    unknown). The chain decides; this only tells the poller where to look.
    A contract-funded order takes hashes only from the payout path."""
    tx_hash = (tx_hash or '').strip().lower()
    if tx_hash and not TX_HASH_RE.fullmatch(tx_hash):
        raise VeSendError('Referencia de transacción no válida.')
    current = RampTransaction.objects.get(pk=ramp.pk)
    _refuse_owner_on_contract_funded(current, by_payout)
    hashes = list(_section(current).get('funding_tx_hashes') or [])
    if tx_hash and tx_hash not in hashes:
        hashes = (hashes + [tx_hash])[-5:]

    def accepts(c):
        if c.status == 'PENDING' and _phase(c) == 'funding_reported':
            return True
        if bool(tx_hash) and _contract_funded(c) and c.status == 'PROCESSING' and _phase(c) == 'funding_reported':
            return True     # reviewed while its call was on the wire (sync)
        # A contract-funded order closed before its funding call was seen:
        # the call's hash is its only proof, so it is still recorded (sync's
        # late watch proves it into review).
        return (bool(tx_hash) and _contract_funded(c) and c.status == 'FAILED'
                and c.status_detail in CLOSED_UNFUNDED and bool(_section(c).get('funding_started_at')))
    updated = _update(ramp.pk, require=accepts, funding_tx_hashes=hashes, funding_reported_at=_now_iso())
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def cancel(ramp: RampTransaction, rpc=None, *, by_payout: bool = False) -> RampTransaction:
    """The user backs out before funding. A last chain scan first: a
    broadcast whose report was lost must not be cancelled away. Never a
    contract-funded order from the app (the payout path closes those with
    close_unsent / fail_unfunded)."""
    _refuse_owner_on_contract_funded(RampTransaction.objects.get(pk=ramp.pk), by_payout)
    if not can_cancel(ramp):
        raise VeSendError('Este envío ya se está procesando y no se puede cancelar.')
    if _phase(ramp) == 'funding_reported':
        found = _find_funding(ramp, rpc)
        if found is _UNKNOWN:
            raise VeSendError('No pudimos confirmar si ya enviaste el dinero. Intenta en unos segundos.')
        if found:
            _mark_funded(ramp, *found)
            raise VeSendError('Este envío ya se está procesando y no se puede cancelar.')
    updated = _update(ramp.pk, require=can_cancel, status='FAILED', detail='cancelled_by_user')
    if updated is None:
        raise VeSendError('Este envío ya se está procesando y no se puede cancelar.')
    return updated


# ------------------------------------------------------------------ funding proof

_UNKNOWN = object()


def _rpc_default():
    from cusd_plus.tasks import _rpc
    return _rpc


def current_block(rpc=None) -> int | None:
    try:
        return int((rpc or _rpc_default())('eth_blockNumber', []), 16)
    except Exception:  # noqa: BLE001
        logger.warning('BSC block number unavailable for a VE send', exc_info=True)
        return None


FALLBACK_CONFIRMATIONS = 15


def _finalized_block(rpc) -> int:
    """The newest finalized BSC block: only transfers at or below it count as
    funding (a reorged-out transfer must never trigger a payout)."""
    try:
        block = rpc('eth_getBlockByNumber', ['finalized', False]) or {}
        number = block.get('number') if isinstance(block, dict) else None
        if number:
            return int(number, 16)
    except Exception:  # noqa: BLE001 — a node without the tag
        logger.info('finalized tag unavailable; using confirmations', exc_info=True)
    return int(rpc('eth_blockNumber', []), 16) - FALLBACK_CONFIRMATIONS


def _topic_address(address: str) -> str:
    return '0x' + '0' * 24 + address.lower()[2:]


def _transfer_amount(log: dict, sender: str, recipient: str) -> Decimal | None:
    topics = log.get('topics') or []
    if ((log.get('address') or '').lower() != USDT_BSC or len(topics) < 3
            or topics[0].lower() != TRANSFER_TOPIC
            or '0x' + topics[1][-40:].lower() != sender
            or '0x' + topics[2][-40:].lower() != recipient):
        return None
    return Decimal(int(log.get('data') or '0x0', 16))


def _hash_claimed_elsewhere(ramp: RampTransaction, tx_hash: str) -> bool:
    return _sends().filter(**{f'metadata__{SECTION}__funding_tx_hash': tx_hash}).exclude(pk=ramp.pk).exists()


def _check_receipt(ramp: RampTransaction, rpc, tx_hash: str):
    """(tx_hash, wei) when the receipt holds the exact transfer, None when it
    definitely does not, _UNKNOWN when it is not readable yet."""
    section = _section(ramp)
    # The finalized height FIRST: a receipt read afterwards at or below it is
    # in a block that can no longer be reorged away.
    finalized = _finalized_block(rpc)
    receipt = rpc('eth_getTransactionReceipt', [tx_hash])
    if not receipt:
        reported = _parse_time(section.get('funding_reported_at'))
        if reported is not None and reported < timezone.now() - RECEIPT_GRACE:
            return None  # dropped or wrong; the log scan still covers a late landing
        return _UNKNOWN
    if receipt.get('status') != '0x1':
        return None
    try:
        mined = int(receipt.get('blockNumber') or '0x0', 16)
    except (TypeError, ValueError):
        return _UNKNOWN
    if not mined or mined > finalized:
        return _UNKNOWN  # not final yet
    # And it is the canonical block at that height.
    canonical = rpc('eth_getBlockByNumber', [hex(mined), False]) or {}
    if not isinstance(canonical, dict) or not receipt.get('blockHash') \
            or str(canonical.get('hash') or '').lower() != str(receipt.get('blockHash')).lower():
        return None
    expected = int(section['deposit_wei'])
    sender = _funding_sender(ramp)
    recipient = section['deposit_address']
    # Only here (a reported hash), only for the vault's exit: the contract
    # takes usdtOut >= minUsdtOut, so more than the order's amount still
    # funds it; _mark_funded records the excess for ops.
    over_allowed = _contract_funded(ramp) and _funded_by_vault(ramp)
    over = None
    for log in receipt.get('logs') or []:
        amount = _transfer_amount(log, sender, recipient)
        if amount is not None and int(amount) == expected:
            return tx_hash, expected
        if over_allowed and amount is not None and int(amount) > expected and over is None:
            over = int(amount)
    if over is not None:
        return tx_hash, over
    return None


def _log_ranges(rpc, params: dict, start: int, end: int):
    """Yield (logs, last_block) per range actually read, degrading to
    micro-chunks when an endpoint refuses the size (the strategy of
    cusd_plus.tasks._get_logs_chunked). Every successful piece is yielded
    before a later one can fail, so proof and progress are never lost."""
    try:
        logs = rpc('eth_getLogs', [dict(params, fromBlock=hex(start), toBlock=hex(end))]) or []
    except Exception:  # noqa: BLE001 — degrade to micro-chunks
        block = start
        while block <= end:
            upper = min(block + MICRO_CHUNK_BLOCKS - 1, end)
            yield rpc('eth_getLogs', [dict(params, fromBlock=hex(block), toBlock=hex(upper))]) or [], upper
            block = upper + 1
        return
    yield logs, end


def _scan_logs(ramp: RampTransaction, rpc):
    """Find the funding transfer by its log when no usable hash was reported.

    Incremental: a per-order block mark advances on every poll up to the chain
    head (the watch itself is bounded by time), so a late transfer is still
    seen and each poll reads only new blocks. "Not found" only once caught up.
    """
    if _contract_funded(ramp):
        return None  # never matched by scan (see CONTRACT_FUNDING)
    section = _section(ramp)
    created = section.get('created_block')
    if not isinstance(created, int):
        return _UNKNOWN
    # Up to the newest FINALIZED block only: a transfer is funding once it
    # cannot be reorged away.
    stop = _finalized_block(rpc)
    floor = max(created - 20, 0)
    scanned_to = section.get('scanned_to')
    # Re-read a few blocks below the last mark: a log near the head may have
    # been reorged in after that read.
    cursor = max(scanned_to - 20, floor) if isinstance(scanned_to, int) else floor
    scanned = cursor - 1
    sender = _funding_sender(ramp)
    recipient = section['deposit_address']
    expected = int(section['deposit_wei'])
    params = {'address': USDT_BSC,
              'topics': [TRANSFER_TOPIC, _topic_address(sender), _topic_address(recipient)]}
    chunks = 0
    try:
        while cursor <= stop and chunks < MAX_CHUNKS_PER_SCAN:
            end = min(cursor + LOG_CHUNK_BLOCKS - 1, stop)
            for logs, upto in _log_ranges(rpc, params, cursor, end):
                for log in logs:
                    amount = _transfer_amount(log, sender, recipient)
                    tx_hash = str(log.get('transactionHash') or '').lower()
                    # A transfer another order already owns is not this one's:
                    # keep looking past it.
                    if (amount is not None and int(amount) == expected and tx_hash
                            and not _hash_claimed_elsewhere(ramp, tx_hash)):
                        return tx_hash, expected
                scanned = upto
            cursor = end + 1
            chunks += 1
    finally:
        # Keep the progress made, even when a later range failed.
        if not isinstance(scanned_to, int) or scanned > scanned_to:
            _update(ramp.pk, scanned_to=scanned)
    return None if scanned >= stop else _UNKNOWN


def _find_funding(ramp: RampTransaction, rpc=None):
    """Proof of the funding transfer: (tx_hash, wei), None, or _UNKNOWN."""
    section = _section(ramp)
    if not section.get('deposit_address') or not str(section.get('deposit_wei') or '').isdigit():
        return None
    rpc = rpc or _rpc_default()
    unknown = False
    # Each source on its own: one failing lookup never hides another's proof.
    for tx_hash in section.get('funding_tx_hashes') or []:
        try:
            found = _check_receipt(ramp, rpc, tx_hash)
        except Exception:  # noqa: BLE001 — RPC gap for this receipt
            logger.warning('Receipt unavailable for VE send %s', ramp.pk, exc_info=True)
            found = _UNKNOWN
        if found is _UNKNOWN:
            unknown = True
        elif found and not _hash_claimed_elsewhere(ramp, found[0]):
            return found
    if _contract_funded(ramp):
        # Proven by its reported executeRule hash or not at all: a scan
        # could hand it another order's identical transfer.
        return _UNKNOWN if unknown else None
    try:
        found = _scan_logs(RampTransaction.objects.get(pk=ramp.pk), rpc)
    except Exception:  # noqa: BLE001 — RPC outage: try again next poll
        logger.warning('Funding log scan unavailable for VE send %s', ramp.pk, exc_info=True)
        return _UNKNOWN
    if found is _UNKNOWN:
        return _UNKNOWN
    if found and not _hash_claimed_elsewhere(ramp, found[0]):
        return found
    return _UNKNOWN if unknown else None


def _terms_problem(ramp: RampTransaction, tx_hash, funded_wei) -> str:
    """Contract-funded: '' only while the executed rule is the signed one."""
    if not _contract_funded(ramp):
        return ''
    try:
        gross = Decimal(str(_section(ramp).get('gross_usd')))
        if int(funded_wei) > int(gross * Decimal(10 ** 18)):
            return 'amount_above_signed'
    except (InvalidOperation, TypeError, ValueError):
        return 'amount_unknown'
    from smart_account.payouts import ramp_funding_problem
    return ramp_funding_problem(ramp, str(tx_hash or ''), funded_wei)


def _mark_funded(ramp: RampTransaction, tx_hash: str, wei: int, *, late: bool = False) -> RampTransaction:
    def allowed(current):
        if late:
            return current.status == 'FAILED' and current.status_detail in CLOSED_UNFUNDED
        return (current.status in ('PENDING', 'PROCESSING')
                and _phase(current) in ('awaiting_funding', 'funding_reported'))
    detail = LATE_FUNDING if late else 'funded'
    # Late money is ops' to route, never paid out automatically: it lands
    # straight in review, in the same write.
    phase = 'payout_review' if late else 'funded'
    values = {}
    try:
        excess = int(wei) - int(_section(ramp).get('deposit_wei') or 0) if _contract_funded(ramp) else 0
    except (TypeError, ValueError):
        excess = 0
    if excess > 0:
        # Only a vault exit proven by its reported hash gets here
        # (_check_receipt): the bridge was quoted for deposit_wei.
        values['funding_excess_wei'] = str(excess)
    with transaction.atomic():
        # One transfer funds one order, decided under a lock on the hash.
        _advisory_lock(f've_send:tx:{tx_hash}')
        if _hash_claimed_elsewhere(ramp, tx_hash):
            return RampTransaction.objects.get(pk=ramp.pk)
        problem = _terms_problem(RampTransaction.objects.get(pk=ramp.pk), tx_hash, wei)
        if problem == EVENT_NOT_SEEN:
            if not late:
                return RampTransaction.objects.get(pk=ramp.pk)      # proven again next poll
            problem = ''        # late money is ops' whatever was executed
        if problem:
            # Recorded, and parked before any payout: never paid automatically.
            values['funding_terms_problem'] = problem
            phase = 'payout_review'
            if not late:
                detail = TERMS_CHANGED_DETAIL
        updated = _update(ramp.pk, require=allowed, status='PROCESSING', detail=detail, phase=phase,
                          quiet=bool(problem), funding_tx_hash=tx_hash, funded_wei=str(wei), funded_at=_now_iso(),
                          **values)
        if updated is not None:
            _show_replaced(updated)
    if updated is None:
        return RampTransaction.objects.get(pk=ramp.pk)
    if problem:
        _alert(updated, TERMS_CHANGED_DETAIL)
    if late:
        _alert(updated, detail)
    if excess > 0:
        _alert(updated, 'funding_excess')
    return updated


# ------------------------------------------------------------------ ops

def _alert(ramp: RampTransaction, reason: str) -> None:
    """Durable needs_review alert, retried by the poller until delivered."""
    try:
        from config.ops_alerts import send_ops_alert
        sent = send_ops_alert(
            f'⚠️ Envío {ramp.country_code} ({ramp.provider}) {ramp.internal_id} requiere revisión: {reason}.',
            dedupe_key=f've_send:{ramp.pk}:{reason}', dedupe_seconds=86400,
        )
    except Exception:  # noqa: BLE001
        logger.exception('VE send alert failed for ramp %s', ramp.pk)
        sent = False
    if sent:
        alerted = dict(_section(RampTransaction.objects.get(pk=ramp.pk)).get('alerted') or {})
        alerted[reason] = _now_iso()
        _update(ramp.pk, alerted=alerted)


def ensure_alerted(ramp: RampTransaction) -> None:
    detail = ramp.status_detail or ''
    if detail.startswith('needs_review') and detail not in (_section(ramp).get('alerted') or {}):
        _alert(ramp, detail)


def _lease_expired(section: dict) -> bool:
    until = _parse_time(section.get('dispatch_lease_until'))
    return until is None or until < timezone.now()


def _fresh_attempt(section: dict) -> dict:
    """Per-attempt state for a NEW key: everything of the old one cleared."""
    return dict(
        payout_attempt=int(section.get('payout_attempt') or 0) + 1,
        payout_key=None, payout_claim=None, payout_sent_at=None, last_replay_at=None,
        operation_id=None, pending_since=None, dispatch_lease_until=None, payout_ambiguous=False,
        payout_unanswered=None, payout_in_doubt=None, payout_first_sent_at=None,
    )


def retry_payout(ramp: RampTransaction, *, operator: str, reviewed_key: str, reviewed_revision: int,
                 confirmed_unpaid: bool = False) -> RampTransaction:
    """Ops: pay again under a NEW key. Only after a definite refusal, or after
    ops confirmed with the provider that a reviewed one was not paid, and only
    for the very attempt and destination ops reviewed."""
    allowed_phases = ('payout_failed', 'payout_review') if confirmed_unpaid else ('payout_failed',)
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        section = _section(current)
        if (current.status != 'PROCESSING' or _phase(current) not in allowed_phases
                or (section.get('payout_key') or '') != (reviewed_key or '')
                or int(section.get('beneficiary_revision') or 0) != int(reviewed_revision)
                or not _lease_expired(section)):
            raise VeSendError('Este envío cambió o no se puede reintentar. Recarga la página.')
        if _contract_funded(current) and current.status_detail == LATE_FUNDING:
            raise VeSendError('Llegó para un pago automático ya cerrado: solo se devuelve a mano.')
        metadata = dict(current.metadata or {})
        # Delivery never proven (e.g. reviewed during settlement): settle again
        # before any payout; otherwise pay from what was credited.
        resume = 'settled' if section.get('credited_usd') else 'funded'
        section.update(phase=resume, retried_by=operator[:80], retried_at=_now_iso(), **_fresh_attempt(section))
        metadata[SECTION] = section
        current.metadata = metadata
        current.status_detail = resume
        current.save(update_fields=['metadata', 'status_detail', 'updated_at'])
        return current


def update_beneficiary(ramp: RampTransaction, beneficiary: dict, *, operator: str, reviewed_key: str,
                       reviewed_revision: int) -> RampTransaction:
    """Ops: correct the destination after a definite refusal, before retrying;
    only from the form of the attempt and destination ops reviewed. Never a
    contract-funded payment's: that recipient is what its owner signed."""
    if _contract_funded(RampTransaction.objects.get(pk=ramp.pk)):
        raise VeSendError('El destinatario de un pago automático es el que firmó el dueño: no se cambia.')
    def allowed(current):
        section = _section(current)
        return (current.status == 'PROCESSING' and _phase(current) == 'payout_failed'
                and (section.get('payout_key') or '') == (reviewed_key or '')
                and int(section.get('beneficiary_revision') or 0) == int(reviewed_revision))
    revision = int(_section(ramp).get('beneficiary_revision') or 0) + 1
    updated = _update(ramp.pk, require=allowed, beneficiary=beneficiary, beneficiary_revision=revision,
                      beneficiary_changed_by=operator[:80])
    if updated is None:
        raise VeSendError('Este envío cambió. Recarga la página antes de corregir el destino.')
    return updated


def mark_paid_manually(ramp: RampTransaction, reference: str, *, operator: str, reviewed_key: str,
                       reviewed_revision: int) -> RampTransaction:
    """Ops: the provider shows the payout settled (reference from its portal);
    only for the attempt and destination ops reviewed, never mid-dispatch."""
    reference = (reference or '').strip()[:40]
    if not reference:
        raise VeSendError('Escribe la referencia del pago.')

    def allowed(current):
        section = _section(current)
        return (current.status == 'PROCESSING'
                and _phase(current) in ('paying', 'payout_pending', 'payout_review', 'payout_failed')
                and (section.get('payout_key') or '') == (reviewed_key or '')
                and int(section.get('beneficiary_revision') or 0) == int(reviewed_revision)
                and _lease_expired(section))
    updated = _update(ramp.pk, require=allowed, status='COMPLETED', detail='delivered', phase='paid',
                      bank_reference=reference, paid_by=operator[:80])
    if updated is None:
        raise VeSendError('Este envío cambió o tiene un pago en curso. Recarga la página.')
    RampTransaction.objects.filter(pk=ramp.pk).update(completed_at=timezone.now())
    return RampTransaction.objects.get(pk=ramp.pk)


# ------------------------------------------------------------------ payout

def _inflight(ramp: RampTransaction) -> list[RampTransaction]:
    """Other sends of the same provider (one balance) whose payout left, or
    may have, and is not settled."""
    return list(_sends().filter(
        provider=ramp.provider, status='PROCESSING',
        **{f'metadata__{SECTION}__phase__in': ['paying', 'payout_pending', 'payout_review']},
    ).exclude(pk=ramp.pk))


def _owner_problem(ramp: RampTransaction) -> str:
    """Contract-funded: why its owner may not pay now ('' to pay)."""
    if not _contract_funded(ramp):
        return ''
    from smart_account.payouts import ramp_owner_problem
    return ramp_owner_problem(ramp)


def _claim_payout(ramp: RampTransaction) -> dict | None:
    """Under the payout lock: let the adapter price the payout and check the
    provider balance net of payouts in flight, then commit the attempt (key
    and exact body) before anything leaves. None when not payable now."""
    held = _owner_problem(ramp)     # before any lock: the gate may take the user's row
    with transaction.atomic():
        _advisory_lock(PAYOUT_LOCK)
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        section = _section(current)
        if current.status != 'PROCESSING' or _phase(current) != 'settled':
            return None
        problem = _terms_problem(current, section.get('funding_tx_hash'), section.get('funded_wei'))
        if problem == EVENT_NOT_SEEN:
            return None
        if problem:
            # Also one funded before this was checked, or retried by ops.
            section['funding_terms_problem'] = problem
            terms = {'review': TERMS_CHANGED}
        elif held:
            section['owner_problem'] = held
            terms = {'review': NOT_PAYABLE}
        else:
            terms = adapter(current).payout_terms(current, _inflight(current))
        if terms and terms.get('wait'):
            now, since = timezone.now(), _parse_time(section.get('payout_wait_since'))
            if since is not None and since <= now - RATE_WAIT:
                terms = {'review': terms['wait']}
            else:
                if since is None or current.status_detail != 'waiting_rate':
                    metadata = dict(current.metadata or {})
                    section.update(payout_wait_since=section.get('payout_wait_since') or now.isoformat())
                    metadata[SECTION] = section
                    current.metadata = metadata
                    current.status_detail = 'waiting_rate'
                    current.save(update_fields=['metadata', 'status_detail', 'updated_at'])
                return None
        if terms and terms.get('review'):
            # Definitely not sent, and not payable as priced: ops decides.
            metadata = dict(current.metadata or {})
            section.update(phase='payout_review')
            metadata[SECTION] = section
            current.metadata = metadata
            current.status_detail = f"needs_review:{terms['review']}"
            current.save(update_fields=['metadata', 'status_detail', 'updated_at'])
            return {'review': True}
        if not terms:
            if current.status_detail != 'waiting_balance' or section.get('payout_wait_since'):
                # Not the rate any more: a later refusal waits its own hour.
                section.update(payout_wait_since=None)
                current.metadata = dict(current.metadata or {}, **{SECTION: section})
                current.status_detail = 'waiting_balance'
                current.save(update_fields=['metadata', 'status_detail', 'updated_at'])
            return None
        attempt = int(section.get('payout_attempt') or 0)
        claim = {'key': f'{current.external_id}:payout:{attempt}', **terms}
        metadata = dict(current.metadata or {})
        section.update(phase='paying', payout_key=claim['key'], payout_claim=claim, payout_sent_at=_now_iso(),
                       payout_wait_since=None, payout_unanswered=True, payout_in_doubt=False,
                       payout_first_sent_at=_now_iso(),
                       payout_ves=str(terms.get('ves_amount') or ''),
                       dispatch_lease_until=(timezone.now() + DISPATCH_LEASE).isoformat())
        metadata[SECTION] = section
        current.metadata = metadata
        current.status_detail = 'paying'
        current.save(update_fields=['metadata', 'status_detail', 'updated_at'])
        return claim


def _same_attempt(key: str, phases=('paying', 'payout_pending')):
    """Every answer is fenced to the attempt that sent it: a late answer of an
    older attempt never moves a newer one."""
    def check(current):
        return (current.status == 'PROCESSING' and _phase(current) in phases
                and _section(current).get('payout_key') == key)
    return check


def _set_payout(ramp: RampTransaction, key: str, phase: str, detail: str, *,
                lease_free: bool = False, **values) -> RampTransaction:
    """`lease_free`: a transition no in-flight dispatch may race (review by
    timeout), so it also waits for the dispatch lease to end."""
    def allowed(current):
        return _same_attempt(key)(current) and (not lease_free or _lease_expired(_section(current)))
    # An answer ends its dispatch: release the lease with it.
    updated = _update(ramp.pk, require=allowed, phase=phase, detail=detail, dispatch_lease_until=None, **values)
    current = updated or RampTransaction.objects.get(pk=ramp.pk)
    if updated is not None and detail.startswith('needs_review'):
        _alert(current, detail)
    return current


def _in_doubt(section: dict) -> bool:
    """Whether a request of this attempt may have been taken: an answer
    lost, or a dispatch that recorded none (a worker that died). An attempt
    from before these fields: as soon as anything was ambiguous."""
    if 'payout_in_doubt' not in section or section.get('payout_in_doubt') is None:
        return bool(section.get('payout_ambiguous'))
    return bool(section.get('payout_in_doubt'))


def _replay_closed(section: dict, now, window) -> str:
    """Why this attempt may not be replayed now ('' while it may). A key
    only ever refused for rate is replayed for RATE_LIMITED_REPLAY_MAX from
    its first dispatch, whatever the provider's window; a key whose earlier
    request may have been taken, for the provider's window from its first
    dispatch (payout_sent_at is not refreshed by replays): it may close
    early, never late."""
    first = _parse_time(section.get('payout_first_sent_at') or section.get('payout_sent_at'))
    if not _in_doubt(section) and section.get('payout_unanswered') is False:
        if first is None or first < now - RATE_LIMITED_REPLAY_MAX:
            return f'needs_review:payout_unknown:{RATE_LIMITED}'
        return ''
    if window is None:
        return ''
    sent_at = _parse_time(section.get('payout_sent_at'))
    if sent_at is None or sent_at < now - window:
        return 'needs_review:payout_unknown:replay_window'
    return ''


def apply_outcome(ramp: RampTransaction, outcome: Outcome, key: str) -> RampTransaction:
    current = RampTransaction.objects.get(pk=ramp.pk)
    section = _section(current)
    earlier_unknown = bool(section.get('payout_ambiguous'))
    if outcome.kind == 'ambiguous':
        # No answer: replayed under the same key by the next poll, inside the
        # window. From now on no refusal of this attempt proves it unpaid.
        if outcome.reason == RATE_LIMITED and not _in_doubt(section):
            # Every request of this key so far was refused for rate: the
            # provider holds nothing under it. Its replay window does not
            # run; the age of the key does (_replay_closed).
            updated = _update(ramp.pk, require=_same_attempt(key), payout_ambiguous=True,
                              payout_unanswered=False)
            closed = _replay_closed(_section(updated or current), timezone.now(), None)
            if updated is not None and closed:
                return _set_payout(ramp, key, 'payout_review', closed)
        else:
            updated = _update(ramp.pk, require=_same_attempt(key), payout_ambiguous=True,
                              payout_unanswered=False, payout_in_doubt=True)
        return updated or current
    if outcome.kind == 'paid':
        updated = _update(ramp.pk, require=_same_attempt(key), status='COMPLETED', detail='delivered', phase='paid',
                          dispatch_lease_until=None, bank_reference=outcome.reference,
                          operation_id=outcome.operation_id or section.get('operation_id'),
                          delivered_ves=outcome.ves_amount or section.get('payout_ves'))
        if updated is not None:
            delivered = outcome.ves_amount or section.get('payout_ves')
            values = {'completed_at': timezone.now(),
                      'provider_order_id': (outcome.operation_id or section.get('operation_id') or '')[:255]}
            try:
                values['fiat_amount'] = Decimal(str(delivered))
            except (InvalidOperation, TypeError, ValueError):
                pass
            RampTransaction.objects.filter(pk=ramp.pk).update(**values)
        return RampTransaction.objects.get(pk=ramp.pk)
    if outcome.kind == 'pending':
        operation_id = outcome.operation_id or section.get('operation_id')
        if not operation_id:
            return _set_payout(ramp, key, 'payout_review', 'needs_review:payout_unknown:pending_without_id')
        updated = _update(ramp.pk, require=_same_attempt(key), phase='payout_pending', detail='bank_processing',
                          dispatch_lease_until=None, operation_id=operation_id,
                          pending_since=section.get('pending_since') or _now_iso())
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    if outcome.kind == 'retry' and outcome.reason == NOT_SENT and earlier_unknown:
        # Nothing new left and nothing was refused: replayed under its key.
        return current
    if outcome.kind in ('failed', 'retry') and earlier_unknown:
        # A refusal now only says THIS request was refused; an earlier
        # dispatch of the attempt may have paid.
        return _set_payout(ramp, key, 'payout_review',
                           f'needs_review:payout_unknown:refused_after_timeout:{outcome.reason}')
    if outcome.kind == 'retry':
        # Definitely not paid and expected to work later (e.g. the deposit is
        # not credited yet): back to funded, the next try gets a NEW key.
        updated = _update(ramp.pk, require=_same_attempt(key), phase='settled', detail='waiting_balance',
                          **_fresh_attempt(section))
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    if outcome.kind == 'failed':
        return _set_payout(ramp, key, 'payout_failed', f'needs_review:payout_failed:{outcome.reason}')
    return _set_payout(ramp, key, 'payout_review', f'needs_review:payout_unknown:{outcome.reason or "no_reason"}')


def _dispatch(ramp: RampTransaction, claim: dict) -> RampTransaction:
    try:
        outcome = adapter(ramp).dispatch(ramp, claim)
    except Exception:  # noqa: BLE001 — anything unexpected is an unknown outcome
        logger.exception('VE send dispatch crashed for %s', ramp.pk)
        outcome = Outcome('ambiguous')
    return apply_outcome(ramp, outcome, claim['key'])


def pay_out(ramp: RampTransaction) -> RampTransaction:
    try:
        claim = _claim_payout(ramp)
    except Exception:  # noqa: BLE001 — provider read failed: nothing sent
        logger.warning('VE send payout terms failed for %s', ramp.pk, exc_info=True)
        return RampTransaction.objects.get(pk=ramp.pk)
    if claim is None:
        return RampTransaction.objects.get(pk=ramp.pk)
    if claim.get('review'):
        current = RampTransaction.objects.get(pk=ramp.pk)
        _alert(current, current.status_detail)
        if current.status_detail == f'needs_review:{RATE_OUTSIDE}' and _contract_funded(current):
            from smart_account.payouts import tell_rate_held
            tell_rate_held(current)
        return RampTransaction.objects.get(pk=ramp.pk)
    return _dispatch(ramp, claim)


def _resume_payout(ramp: RampTransaction) -> RampTransaction:
    """A payout whose answer was lost: replay the SAME key and body while the
    provider still remembers it, then hand it to ops."""
    section = _section(ramp)
    key = section.get('payout_key') or ''
    if not _lease_expired(section):
        return ramp  # a dispatch of this attempt may still be in flight
    window = adapter(ramp).replay_window()
    closed = _replay_closed(section, timezone.now(), window)
    if closed:
        return _set_payout(ramp, key, 'payout_review', closed, lease_free=True)
    claim = section.get('payout_claim')
    if not key or not isinstance(claim, dict) or claim.get('key') != key:
        return _set_payout(ramp, key, 'payout_review', 'needs_review:payout_unknown:no_claim', lease_free=True)
    if _owner_problem(ramp):
        # A replay may be the first that arrives: ops ask the provider instead.
        return _set_payout(ramp, key, 'payout_review', 'needs_review:payout_unknown:owner_not_payable',
                           lease_free=True)

    def replayable(current):
        now_section = _section(current)
        return (_same_attempt(key, ('paying',))(current) and _lease_expired(now_section)
                and not _replay_closed(now_section, timezone.now(), window))
    # Re-checked and leased under the row lock right before it leaves. A
    # replay exists only because an earlier answer was never recorded
    # (timeout or a worker that died): that earlier dispatch may have paid.
    # The previous dispatch recorded no answer: it may have been taken.
    doubt = _in_doubt(section) or section.get('payout_unanswered') is not False
    if _update(ramp.pk, require=replayable, last_replay_at=_now_iso(), payout_ambiguous=True,
               payout_in_doubt=doubt, payout_unanswered=True,
               dispatch_lease_until=(timezone.now() + DISPATCH_LEASE).isoformat()) is None:
        return RampTransaction.objects.get(pk=ramp.pk)
    return _dispatch(ramp, claim)


def _poll(ramp: RampTransaction) -> RampTransaction:
    section = _section(ramp)
    key = section.get('payout_key') or ''
    since = _parse_time(section.get('pending_since'))
    try:
        outcome = adapter(ramp).poll(ramp)
    except Exception:  # noqa: BLE001 — try again next poll
        logger.warning('VE send poll failed for %s', ramp.pk, exc_info=True)
        outcome = None
    if outcome is not None and outcome.kind != 'pending':
        return apply_outcome(ramp, outcome, key)
    if since is not None and since < timezone.now() - adapter(ramp).PENDING_STALE:
        return _set_payout(ramp, key, 'payout_review', 'needs_review:payout_pending_stale')
    return ramp


def _settlement_followed(ramp: RampTransaction) -> bool:
    """A delay or a stuck refund is watched to its end: a key or a service
    that comes back, or a refund made by hand, resolves it."""
    return (ramp.status == 'PROCESSING' and _phase(ramp) == 'payout_review' and _contract_funded(ramp)
            and (ramp.status_detail or '').startswith(SETTLEMENT_FOLLOWED))


def _settle(ramp: RampTransaction) -> RampTransaction:
    """funded -> settled once the provider holds the money: the adapter's
    settlement step (e.g. a bridge delivery proven on the destination chain),
    or immediately when there is none."""
    section = _section(ramp)
    step = getattr(adapter(ramp), 'settle', None)
    if step is None:
        credited = Decimal(str(section.get('funded_wei') or '0')) / Decimal(10 ** 18)
        result = Settlement('delivered', credited_usd=format(credited, 'f'))
    else:
        try:
            result = step(ramp)
        except Exception:  # noqa: BLE001 — try again next poll
            logger.warning('VE send settlement check failed for %s', ramp.pk, exc_info=True)
            return ramp
    funded = lambda c: ((c.status == 'PROCESSING' and _phase(c) == 'funded')  # noqa: E731
                        or _settlement_followed(c))
    if _settlement_followed(ramp) and result.kind in ('pending', 'review'):
        return ramp     # still with ops; only an outcome moves it
    if result.kind == 'pending':
        updated = _update(ramp.pk, require=funded, detail='bridging')
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    if result.kind == 'delivered':
        with transaction.atomic():
            if result.evidence:
                # One delivery settles one order.
                _advisory_lock(f've_send:delivery:{result.evidence}')
                if _sends().filter(**{f'metadata__{SECTION}__delivered_tx': result.evidence}).exclude(
                        pk=ramp.pk).exists():
                    result = Settlement('review', reason='delivery_claimed_elsewhere')
            if result.kind == 'delivered':
                updated = _update(ramp.pk, require=funded, phase='settled', detail='settled',
                                  credited_usd=result.credited_usd, delivered_tx=result.evidence or None)
                return updated or RampTransaction.objects.get(pk=ramp.pk)
    if result.kind == 'refunded':
        # Proven back in the user's own wallet: nothing was sent.
        updated = _update(ramp.pk, require=funded, status='FAILED', detail='refunded_to_wallet', phase='refunded')
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    updated = _update(ramp.pk, require=funded, phase='payout_review',
                      detail=f'needs_review:settlement:{result.reason or "unknown"}')
    if updated is not None:
        _alert(updated, updated.status_detail)
    return updated or RampTransaction.objects.get(pk=ramp.pk)


# ------------------------------------------------------------------ reconciliation

def sync(ramp: RampTransaction, rpc=None) -> RampTransaction:
    """One reconciliation step for a send. Idempotent."""
    ramp = RampTransaction.objects.get(pk=ramp.pk)
    phase = _phase(ramp)
    now = timezone.now()
    if ramp.status == 'PENDING':
        if phase == 'preparing':
            if ramp.created_at < now - timedelta(minutes=10):
                return fail_unfunded(ramp, 'preparation_interrupted')
            return ramp
        if phase == 'awaiting_funding':
            # No target has left the server yet: nothing to look for.
            if ramp.created_at < now - FUNDING_WINDOW:
                return fail_unfunded(ramp, 'expired_unfunded')
            return ramp
        found = _find_funding(ramp, rpc)
        if found not in (None, _UNKNOWN):
            return _mark_funded(ramp, *found)
        section = _section(ramp)
        started = _parse_time(section.get('funding_started_at')) or ramp.created_at
        deadline = (section.get('bridge') or {}).get('deadline')
        if (found is None and _contract_funded(ramp) and not section.get('funding_tx_hashes')
                and str(deadline or '').isdigit()
                and int(deadline) < int((now - CLAIMED_FUNDING_QUIET).timestamp())
                and not _may_land(ramp)):
            # The payout's quote is long dead and no executeRule hash was
            # reported: that run will not fund this order. Closed now; a
            # late reported hash still proves it into review.
            updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'funding_reported'
                              and not _section(c).get('funding_tx_hashes') and not _may_land(c),
                              status='FAILED', detail='expired_unfunded', quiet=True)
            return updated or RampTransaction.objects.get(pk=ramp.pk)
        if found is _UNKNOWN and started < now - UNVERIFIABLE_AFTER:
            updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'funding_reported',
                              status='PROCESSING', detail='needs_review:funding_unverifiable')
            if updated is not None:
                _alert(updated, updated.status_detail)
                return updated
        if found is None and started < now - UNFUNDED_EXPIRY:
            if not section.get('funding_tx_hashes') and not _may_land(ramp):
                # Claimed, never broadcast (or never mined): close it; the
                # late-funding watch keeps looking.
                updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING'
                                  and _phase(c) == 'funding_reported' and not _section(c).get('funding_tx_hashes')
                                  and not _may_land(c),
                                  status='FAILED', detail='expired_unfunded', quiet=_contract_funded(ramp))
                return updated or RampTransaction.objects.get(pk=ramp.pk)
            updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'funding_reported',
                              status='PROCESSING', detail='needs_review:funding_not_found')
            if updated is not None:
                _alert(updated, updated.status_detail)
                return updated
        return RampTransaction.objects.get(pk=ramp.pk)
    if ramp.status == 'FAILED':
        # Contract-funded: only a reported hash is checked (_find_funding).
        if ramp.status_detail in CLOSED_UNFUNDED and _section(ramp).get('funding_started_at'):
            found = _find_funding(ramp, rpc)
            if found not in (None, _UNKNOWN):
                return _mark_funded(ramp, *found, late=True)
        return ramp
    if ramp.status != 'PROCESSING':
        return ramp
    if phase == 'funding_reported':
        # Reviewed as funding not found / unverifiable: the chain may still prove it.
        found = _find_funding(ramp, rpc)
        if found not in (None, _UNKNOWN):
            return _mark_funded(ramp, *found)
        return ramp
    if phase == 'funded' or _settlement_followed(ramp):
        return _settle(ramp)
    if phase == 'settled':
        return pay_out(ramp)
    if phase == 'paying':
        return _resume_payout(ramp)
    if phase == 'payout_pending':
        return _poll(ramp)
    return ramp


def open_sends():
    """Sends the poller reconciles: open ones, and closed-unfunded claimed ones
    still inside the late-funding watch."""
    from django.db.models import Q
    now = timezone.now()
    return _sends().filter(
        Q(status__in=OPEN_STATUSES)
        | Q(status='FAILED', status_detail__in=list(CLOSED_UNFUNDED),
            created_at__gte=now - LATE_FUNDING_WATCH, **{f'metadata__{SECTION}__has_key': 'funding_started_at'})
    ).order_by('created_at')


def due_for_sync(ramp: RampTransaction) -> bool:
    """Open sends every poll; closed-unfunded ones (a chain scan) every 10 min;
    one waiting on ops costs nothing."""
    if ramp.status == 'PROCESSING' and _phase(ramp) in ('payout_failed', 'payout_review'):
        return _settlement_followed(ramp)
    if ramp.status == 'FAILED':
        return ramp.updated_at < timezone.now() - timedelta(minutes=10)
    return True


def active_order(user, provider: str) -> RampTransaction | None:
    """The person's own open send (a contract-funded Cuenta inteligente
    payout is not theirs to resume or cancel, and never blocks a new one)."""
    return RampTransaction.objects.filter(
        provider=provider, direction=DIRECTION, country_code=_country(provider), actor_user=user,
        status__in=OPEN_STATUSES,
    ).exclude(**_FUNDING_SENDER_KEY).order_by('-created_at').first()


def _beneficiary_view(ramp: RampTransaction, beneficiary: dict) -> dict:
    custom = getattr(adapter(ramp), 'beneficiary_view', None)
    if custom:
        return custom(beneficiary)
    return {
        'cedula': beneficiary.get('cedula'), 'phone': beneficiary.get('phone'),
        'bank_code': beneficiary.get('bank_code'),
        'bank_name': ve_pagomovil.BANK_NAMES.get(beneficiary.get('bank_code') or '', ''),
    }


def view(ramp: RampTransaction, *, with_funding: bool = False) -> dict:
    section = _section(ramp)
    beneficiary = section.get('beneficiary') or {}
    return {
        'phase': _phase(ramp),
        'usd_amount': section.get('gross_usd'),
        'usdt_amount': format(ramp.crypto_amount_estimated, 'f') if ramp.crypto_amount_estimated is not None else None,
        'estimated_ves': section.get('estimated_ves'),
        # Exact bolívares (Pago ASAP quote_exact): the estimate is what lands.
        'exact_ves': (section.get('estimate') or {}).get('exact_ves') or None,
        'ves_amount': section.get('delivered_ves') or section.get('payout_ves') or None,
        'rate': (section.get('estimate') or {}).get('rate'),
        'estimated_fiat': section.get('estimated_fiat') or section.get('estimated_ves'),
        'fiat_amount': section.get('delivered_fiat') or section.get('delivered_ves') or section.get('payout_ves'),
        'beneficiary': _beneficiary_view(ramp, beneficiary) if beneficiary else None,
        'funding': funding_details(ramp) if with_funding else None,
        'funding_tx_hash': section.get('funding_tx_hash'),
        'bank_reference': section.get('bank_reference'),
        'can_cancel': can_cancel(ramp),
        'can_fund': can_fund(ramp),
        'wallet': ramp.actor_address,
    }
