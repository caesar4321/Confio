"""Venezuelan off-ramp through VEXPay: Confío dollars out, bolívares in a
Pago Móvil account (the user's own or a third party's).

One `RampTransaction(provider='vexpay', direction='off_ramp',
destination='cusd_plus')` per send. VEXPay has no USDT → VES API yet, so the
conversion is done by VEXPay by hand and released here by ops:

  preparing         order saved, Face claimed, no deposit address yet
  awaiting_funding  the server vouches for the order's own deposit address;
                    the app redeems and pays it in one sponsored batch
  funding_reported  the app says it broadcast (or may have broadcast) it
  funded            the BSC chain proves the exact USDT reached that address
                    from the user's wallet; ops asks VEXPay to convert it
  converted         ops entered the bolívares VEXPay credited for it
  paying            one crédito inmediato is at VEXPay under a fixed key
  credit_pending    the bank accepted it as pending (AC00); polled
  credit_failed     the bank definitely refused it; ops fixes and retries
  credit_review     the outcome cannot be known automatically; ops checks

Each order has its own deposit address (customerRef = the order), so two
sends of the same amount can never be confused. The bolívares themselves are
fungible in Confío's VEXPay balance: a payout needs ops' release AND enough
free balance after every payout still in flight, never a match by amount.

Money that may have moved is never released and never failed: a send that
was funded ends paid or in review. Funding is proven on chain, not by
VEXPay's single-attempt webhook.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from ramps import vexpay
from ramps.models import RampTransaction
from ramps.vexpay_client import VexPayAmbiguousError, VexPayClient, VexPayError

logger = logging.getLogger(__name__)

DIRECTION = 'off_ramp'
MICRO = Decimal('0.000001')
WEI_PER_MICRO = 10 ** 12
EVM_ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
TX_HASH_RE = re.compile(r'^0x[0-9a-fA-F]{64}$')
USDT_BSC = '0x55d398326f99059ff775485246999027b3197955'
TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
RESERVE_LOCK = 'vexpay:offramp:reserve'
PAYOUT_LOCK = 'vexpay:offramp:payout'

# The app funds right after creating the order; past this the address is no
# longer vouched for and the order can only be cancelled or expire.
FUNDING_WINDOW = timedelta(hours=2)
# An unfunded order closes after this, once a last chain scan finds nothing.
UNFUNDED_EXPIRY = timedelta(hours=6)
# Closed-unfunded orders are still scanned this long: money that arrives
# anyway is surfaced to ops, never lost.
LATE_FUNDING_WATCH = timedelta(days=3)
# One eth_getLogs request covers at most this many blocks.
LOG_CHUNK_BLOCKS = 4_000
# A crédito inmediato is replayed under its own key only inside VEXPay's
# 24 h idempotency window (with margin); after it the same key pays again.
CREDIT_REPLAY_WINDOW = timedelta(hours=20)
CREDIT_PENDING_STALE = timedelta(hours=24)
# Every dispatch (first send or replay) holds this lease: no review or
# new-key retry can begin while an old key may still be on its way out.
DISPATCH_LEASE = timedelta(minutes=10)
# A reported hash with no receipt this long after the report was dropped.
RECEIPT_GRACE = timedelta(minutes=30)
CREDIT_ACCEPTED = {'ACCP'}
CREDIT_PENDING = {'AC00', '202'}
# docs.pay.vexwallet.co reject codes: the bank refused, nothing was paid.
CREDIT_REJECTED = {
    'AB01', 'AB07', 'AC01', 'AC04', 'AC06', 'AC09', 'AG01', 'AG09', 'AG10', 'AM02', 'AM04', 'AM05',
    'BE01', 'BE20', 'CH20', 'CUST', 'DS02', 'DT03', 'DU01', 'ED05', 'FF05', 'FF07', 'MD01', 'MD09',
    'MD15', 'MD22', 'RC08', 'RJCT', 'TKCM', 'VE01', 'TM01',
}
# A duplicate is the bank saying this very operation already exists: never
# a definite "not paid".
CREDIT_DUPLICATE = {'AM05', 'DU01'}
OPS_SANITY_BAND = Decimal('0.25')  # ops' bolívares within ±25% of the quote


class VexPayOffRampError(vexpay.VexPayRampError):
    """User-facing refusal (Spanish)."""


def enabled() -> bool:
    return vexpay.enabled() and bool(getattr(settings, 'VEXPAY_OFFRAMP_ENABLED', False))


def client_supports(meta) -> bool:
    """Only builds with the VE send screen get the row; '' = nobody."""
    floor = vexpay._version(getattr(settings, 'VEXPAY_SEND_MIN_APP_VERSION', ''))
    version = vexpay._version((meta or {}).get('HTTP_X_CONFIO_VERSION', ''))
    return floor is not None and version is not None and version >= floor


# ------------------------------------------------------------------ pricing

def _setting(name: str, default: str) -> Decimal:
    return vexpay._setting_decimal(name, default)


def confio_amounts(gross_usd: Decimal) -> tuple[int | None, int]:
    """(gross Confío-dollar debit in wei or None, USDT sent to VEXPay in wei).

    With the conversion fee on, the user's dollars are redeemed with fee and
    the provider receives the previewed net, floored to six decimals so the
    deposit is an exact USDT amount; the same preview the Koywe Retiro uses.
    """
    gross_wei = int((gross_usd * Decimal(10 ** 18)).to_integral_value(rounding=ROUND_DOWN))
    if not getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False):
        return None, gross_wei
    try:
        from cusd_plus.cusd_vault import preview_redeem_wei
        preview = preview_redeem_wei(gross_wei)
        net_micro = Decimal(preview.net).quantize(MICRO, rounding=ROUND_DOWN)
    except Exception as exc:  # noqa: BLE001 — RPC / vault read
        logger.warning('cUSD fee preview failed for a VEXPay send', exc_info=True)
        raise VexPayOffRampError('No pudimos calcular la comisión de Confío.') from exc
    deposit_wei = int(net_micro / MICRO) * WEI_PER_MICRO
    if deposit_wei <= 0:
        raise VexPayOffRampError('El monto es muy bajo.')
    return gross_wei, deposit_wei


def estimate_ves(usdt: Decimal, rate: Decimal) -> Decimal:
    """Bolívares the beneficiary should receive: VEXPay's USDT deposit fee,
    its conversion spread, at today's market rate. An estimate; the real
    amount is what VEXPay credits for this deposit."""
    fee_pct = _setting('VEXPAY_OFFRAMP_USDT_FEE_PERCENT', '2.5') / 100
    fee_fixed = _setting('VEXPAY_OFFRAMP_USDT_FEE_FIXED', '0.50')
    spread = _setting('VEXPAY_OFFRAMP_SPREAD_PERCENT', '1.5') / 100
    usdt_after_fee = usdt * (1 - fee_pct) - fee_fixed
    ves = usdt_after_fee * rate / (1 + spread)
    return max(ves, Decimal('0')).quantize(vexpay.CENT, rounding=ROUND_DOWN)


def market_rate(client: VexPayClient) -> Decimal:
    quote = client.quote_usd(Decimal('1')) or {}
    if str(quote.get('rateSource') or '').upper() != 'MARKET':
        raise VexPayOffRampError('Los envíos en bolívares no están disponibles por ahora.')
    try:
        rate = Decimal(str(quote.get('rate')))
    except (InvalidOperation, TypeError, ValueError):
        rate = Decimal('0')
    if not rate.is_finite() or rate <= 0:
        raise VexPayError('VEXPay returned no rate', status=503)
    return rate


# ------------------------------------------------------------------ limits

def counted_usd(ramp: RampTransaction) -> Decimal:
    try:
        return Decimal(str(vexpay._section(ramp).get('gross_usd') or '0'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def check_limits(user, gross_usd: Decimal) -> None:
    from django.db.models import Q
    minimum = _setting('VEXPAY_OFFRAMP_MIN_USD', '5')
    maximum = _setting('VEXPAY_OFFRAMP_MAX_USD', '100')
    if gross_usd < minimum:
        raise VexPayOffRampError(f'El monto mínimo es ${minimum}.')
    if gross_usd > maximum:
        raise VexPayOffRampError(f'El monto máximo por envío es ${maximum}.')
    since = timezone.now() - timedelta(hours=24)
    # Every send not definitely unfunded counts, by when money can move.
    recent = list(RampTransaction.objects.filter(provider=vexpay.PROVIDER, direction=DIRECTION).filter(
        Q(created_at__gte=since) | Q(status__in=vexpay.OPEN_STATUSES) | Q(completed_at__gte=since),
    ).exclude(status='FAILED'))
    user_total = sum((counted_usd(r) for r in recent if r.actor_user_id == user.pk), Decimal('0'))
    if user_total + gross_usd > _setting('VEXPAY_OFFRAMP_USER_DAILY_USD', '200'):
        raise VexPayOffRampError('Alcanzaste el límite diario de envíos en bolívares. Intenta mañana.')
    global_total = sum((counted_usd(r) for r in recent), Decimal('0'))
    if global_total + gross_usd > _setting('VEXPAY_OFFRAMP_GLOBAL_DAILY_USD', '1000'):
        raise VexPayOffRampError('Los envíos en bolívares alcanzaron su cupo de hoy. Intenta más tarde.')


def _advisory_lock(name: str) -> None:
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [name])


# ------------------------------------------------------------------ state

def _section(ramp: RampTransaction) -> dict:
    return vexpay._section(ramp)


def _phase(ramp: RampTransaction) -> str:
    return _section(ramp).get('phase') or 'preparing'


def _update(ramp_pk: int, **kwargs) -> RampTransaction | None:
    return vexpay._update(ramp_pk, **kwargs)


def _now_iso() -> str:
    return timezone.now().isoformat()


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ''))
    except ValueError:
        return None


def can_fund(ramp: RampTransaction) -> bool:
    """The vouched address is offered only while the order is fresh and
    nothing has been reported for it."""
    return (ramp.status == 'PENDING' and _phase(ramp) == 'awaiting_funding'
            and ramp.created_at >= timezone.now() - FUNDING_WINDOW)


# A claimed funding that reported no hash may be cancelled after this long
# with a clean chain scan (a sponsored batch is mined in seconds or never);
# the late-funding watch still covers it.
CLAIMED_FUNDING_QUIET = timedelta(minutes=15)


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


@transaction.atomic
def reserve_off_ramp(*, user, account, gross_usd: Decimal, beneficiary: dict, rate: Decimal,
                     gross_wei: int | None, deposit_wei: int, created_block: int | None) -> RampTransaction:
    from users.models import Account

    _advisory_lock(RESERVE_LOCK)
    locked = Account.objects.select_for_update().filter(pk=account.pk, deleted_at__isnull=True).first()
    address = (getattr(locked, 'bsc_address', '') or '').strip().lower()
    if not locked or not address or address != (account.bsc_address or '').strip().lower():
        raise VexPayOffRampError('Tu billetera cambió. Vuelve a intentarlo.')
    if RampTransaction.objects.filter(
        provider=vexpay.PROVIDER, direction=DIRECTION, actor_user=user, status='PENDING',
    ).exists():
        raise VexPayOffRampError('Ya tienes un envío en bolívares pendiente. Termínalo o cancélalo.')
    check_limits(user, gross_usd)
    usdt = Decimal(deposit_wei) / Decimal(10 ** 18)
    ves = estimate_ves(usdt, rate)
    if ves <= 0:
        raise VexPayOffRampError('El monto es muy bajo para enviar bolívares.')
    ramp = RampTransaction(
        provider=vexpay.PROVIDER,
        direction=DIRECTION,
        status='PENDING',
        country_code='VE',
        actor_user=user,
        actor_type='user',
        actor_display_name=account.display_name or user.get_full_name() or user.username or '',
        # The wallet the funding transfer must come from.
        actor_address=address,
        destination='cusd_plus',
        fiat_currency='VES',
        fiat_amount=ves,
        crypto_currency='USDT',
        crypto_amount_estimated=usdt.quantize(MICRO, rounding=ROUND_DOWN),
        # The ledger records what left the wallet, like the Koywe Retiro: the
        # USDT settlement, never a bolívar figure in a dollar token.
        final_currency='USDT',
        final_amount=usdt.quantize(MICRO, rounding=ROUND_DOWN),
        status_detail='awaiting_funding',
    )
    ramp.external_id = str(ramp.internal_id)
    ramp.metadata = {'vexpay': {
        'phase': 'preparing',
        'gross_usd': format(gross_usd, 'f'),
        'gross_wei': str(gross_wei) if gross_wei is not None else None,
        'deposit_wei': str(deposit_wei),
        'beneficiary': beneficiary,
        'quoted_rate': format(rate, 'f'),
        'estimated_ves': format(ves, 'f'),
        'created_block': created_block,
        'network': vexpay.NETWORK,
        'credit_attempt': 0,
    }}
    ramp.save()
    return ramp


def customer_ref(ramp: RampTransaction) -> str:
    return f'cfo-{ramp.external_id}'


def prepare_deposit(ramp: RampTransaction, client: VexPayClient) -> RampTransaction:
    """Fetch the order's own deposit address and start the funding window.
    Nothing can have been paid yet, so any failure closes the order."""
    try:
        payload = client.deposit_address(customer_ref=customer_ref(ramp), network=vexpay.NETWORK,
                                         idempotency_key=f'{ramp.external_id}:deposit')
    except VexPayError:
        logger.exception('VEXPay deposit address failed for ramp %s', ramp.pk)
        fail_unfunded(ramp, 'deposit_address_failed')
        raise VexPayOffRampError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.')
    address = str(payload.get('address') or '').strip()
    user_wallet = (ramp.actor_address or '').lower()
    valid = (EVM_ADDRESS_RE.fullmatch(address) is not None
             and address.lower() not in (USDT_BSC, '0x' + '0' * 40, user_wallet)
             and str(payload.get('network') or '').upper() == vexpay.NETWORK
             and str(payload.get('currency') or 'USDT').upper() == 'USDT'
             and str(payload.get('customerRef') or '') == customer_ref(ramp)
             and not payload.get('tagRequired'))
    if not valid:
        logger.error('VEXPay returned an unusable deposit address for ramp %s', ramp.pk)
        fail_unfunded(ramp, 'deposit_address_invalid')
        raise VexPayOffRampError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.')
    updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'preparing',
                      phase='awaiting_funding', deposit_address=address.lower(), prepared_at=_now_iso())
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def fail_unfunded(ramp: RampTransaction, detail: str) -> RampTransaction:
    """Close an order no funding can have been sent for (never vouched, or
    the user cancelled before reporting one and the chain shows none)."""
    updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING'
                      and _phase(c) in ('preparing', 'awaiting_funding'),
                      status='FAILED', detail=detail)
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def funding_details(ramp: RampTransaction) -> dict | None:
    """The vouched funding target in the shape the app's audited funding
    path reads (ramps.schema CONFIO_* keys). Served only in the response of
    the one start_funding claim, never on a read."""
    from ramps.schema import (
        CONFIO_DEPOSIT_ADDRESS_KEY,
        CONFIO_DEPOSIT_AMOUNT_WEI_KEY,
        CONFIO_DEPOSIT_NETWORK_KEY,
        CONFIO_GROSS_DEBIT_AMOUNT_WEI_KEY,
    )
    section = _section(ramp)
    address = section.get('deposit_address') or ''
    if not EVM_ADDRESS_RE.fullmatch(address) or not str(section.get('deposit_wei') or '').isdigit():
        return None
    details = {
        CONFIO_DEPOSIT_ADDRESS_KEY: address,
        CONFIO_DEPOSIT_NETWORK_KEY: 'BSC',
        CONFIO_DEPOSIT_AMOUNT_WEI_KEY: str(section['deposit_wei']),
    }
    if section.get('gross_wei'):
        details[CONFIO_GROSS_DEBIT_AMOUNT_WEI_KEY] = str(section['gross_wei'])
    return details


def start_funding(ramp: RampTransaction) -> RampTransaction:
    """The single right to fund this order. From here the order can never
    be funded again or cancelled while a broadcast may still land: the app
    gets the vouched address once, in this claim's answer."""
    updated = _update(ramp.pk, require=can_fund, detail='confirming_funding',
                      phase='funding_reported', funding_started_at=_now_iso())
    if updated is None:
        raise VexPayOffRampError('Este envío ya se está procesando.')
    return updated


def report_funding(ramp: RampTransaction, tx_hash: str | None) -> RampTransaction:
    """The broadcast hash of the claimed funding (or none when its outcome
    is unknown). The chain decides; this only tells the poller where to look."""
    tx_hash = (tx_hash or '').strip().lower()
    if tx_hash and not TX_HASH_RE.fullmatch(tx_hash):
        raise VexPayOffRampError('Referencia de transacción no válida.')
    current = RampTransaction.objects.get(pk=ramp.pk)
    hashes = list(_section(current).get('funding_tx_hashes') or [])
    if tx_hash and tx_hash not in hashes:
        hashes = (hashes + [tx_hash])[-5:]
    updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'funding_reported',
                      funding_tx_hashes=hashes, funding_reported_at=_now_iso())
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def cancel_off_ramp(ramp: RampTransaction, rpc=None) -> RampTransaction:
    """The user backs out before funding. A last chain scan first: a
    broadcast whose report was lost must not be cancelled away."""
    if not can_cancel(ramp):
        raise VexPayOffRampError('Este envío ya se está procesando y no se puede cancelar.')
    if _phase(ramp) == 'funding_reported':
        found = _find_funding(ramp, rpc)
        if found is _UNKNOWN:
            raise VexPayOffRampError('No pudimos confirmar si ya enviaste el dinero. Intenta en unos segundos.')
        if found:
            _mark_funded(ramp, *found)
            raise VexPayOffRampError('Este envío ya se está procesando y no se puede cancelar.')
    updated = _update(ramp.pk, require=can_cancel, status='FAILED', detail='cancelled_by_user')
    if updated is None:
        raise VexPayOffRampError('Este envío ya se está procesando y no se puede cancelar.')
    return updated


# ------------------------------------------------------------------ funding proof

_UNKNOWN = object()


def _rpc_default():
    from cusd_plus.tasks import _rpc
    return _rpc


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
    return RampTransaction.objects.filter(
        provider=vexpay.PROVIDER, direction=DIRECTION, metadata__vexpay__funding_tx_hash=tx_hash,
    ).exclude(pk=ramp.pk).exists()


def _check_receipt(ramp: RampTransaction, rpc, tx_hash: str):
    """(tx_hash, wei) when the receipt holds the exact transfer, None when it
    definitely does not, _UNKNOWN when it is not readable yet."""
    section = _section(ramp)
    receipt = rpc('eth_getTransactionReceipt', [tx_hash])
    if not receipt:
        reported = _parse_time(section.get('funding_reported_at'))
        if reported is not None and reported < timezone.now() - RECEIPT_GRACE:
            return None  # dropped or wrong; the log scan still covers a late landing
        return _UNKNOWN
    if receipt.get('status') != '0x1':
        return None
    expected = int(section['deposit_wei'])
    sender = (ramp.actor_address or '').lower()
    recipient = section['deposit_address']
    for log in receipt.get('logs') or []:
        amount = _transfer_amount(log, sender, recipient)
        if amount is not None and int(amount) == expected:
            return tx_hash, expected
    return None


MAX_CHUNKS_PER_SCAN = 20
MICRO_CHUNK_BLOCKS = 50  # the strictest pool endpoint's eth_getLogs cap
# Funding claimed this long ago and still not verifiable either way: ops.
UNVERIFIABLE_AFTER = timedelta(hours=12)


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

    Incremental: a per-order block cursor advances on every poll through the
    whole late-funding watch, so a transfer that lands late is still seen,
    and each poll reads only new blocks. "Not found" only once the cursor has
    caught up with the chain head; before that the answer is unknown.
    """
    section = _section(ramp)
    created = section.get('created_block')
    if not isinstance(created, int):
        return _UNKNOWN
    # Up to the head: the watch itself is bounded by time (open_off_ramps),
    # never by an assumed block rate.
    stop = int(rpc('eth_blockNumber', []), 16)
    floor = max(created - 20, 0)
    scanned_to = section.get('scanned_to')
    # Re-read a few blocks below the last mark: a log near the head may have
    # been reorged in after that read.
    cursor = max(scanned_to - 20, floor) if isinstance(scanned_to, int) else floor
    scanned = cursor - 1
    sender = (ramp.actor_address or '').lower()
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
                    if amount is not None and int(amount) == expected and log.get('transactionHash'):
                        return str(log['transactionHash']).lower(), expected
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
            logger.warning('Receipt unavailable for VEXPay send %s', ramp.pk, exc_info=True)
            found = _UNKNOWN
        if found is _UNKNOWN:
            unknown = True
        elif found and not _hash_claimed_elsewhere(ramp, found[0]):
            return found
    try:
        found = _scan_logs(RampTransaction.objects.get(pk=ramp.pk), rpc)
    except Exception:  # noqa: BLE001 — RPC outage: try again next poll
        logger.warning('Funding log scan unavailable for VEXPay send %s', ramp.pk, exc_info=True)
        return _UNKNOWN
    if found is _UNKNOWN:
        return _UNKNOWN
    if found and not _hash_claimed_elsewhere(ramp, found[0]):
        return found
    return _UNKNOWN if unknown else None


def _mark_funded(ramp: RampTransaction, tx_hash: str, wei: int, *, late: bool = False) -> RampTransaction:
    def allowed(current):
        if late:
            return current.status == 'FAILED' and current.status_detail in ('expired_unfunded', 'cancelled_by_user')
        return (current.status in ('PENDING', 'PROCESSING')
                and _phase(current) in ('awaiting_funding', 'funding_reported'))
    detail = 'needs_review:late_funding' if late else 'awaiting_conversion'
    updated = _update(ramp.pk, require=allowed, status='PROCESSING', detail=detail, phase='funded',
                      funding_tx_hash=tx_hash, funded_wei=str(wei), funded_at=_now_iso())
    if updated is None:
        return RampTransaction.objects.get(pk=ramp.pk)
    _ops_note(updated, 'convertir')
    if late:
        _alert(updated, detail)
    return updated


# ------------------------------------------------------------------ ops

def _alert(ramp: RampTransaction, reason: str) -> None:
    """Durable needs_review alert, retried by the poller until delivered."""
    try:
        from config.ops_alerts import send_ops_alert
        sent = send_ops_alert(
            f'⚠️ VEXPay envío {ramp.internal_id} requiere revisión: {reason}.',
            dedupe_key=f'vexpay:{ramp.pk}:{reason}', dedupe_seconds=86400,
        )
    except Exception:  # noqa: BLE001
        logger.exception('VEXPay send alert failed for ramp %s', ramp.pk)
        sent = False
    if sent:
        alerted = dict(_section(RampTransaction.objects.get(pk=ramp.pk)).get('alerted') or {})
        alerted[reason] = _now_iso()
        _update(ramp.pk, alerted=alerted)


def ensure_alerted(ramp: RampTransaction) -> None:
    """Re-send an undelivered review alert, or the conversion request of a
    funded send (nothing else would ever tell ops about it)."""
    detail = ramp.status_detail or ''
    alerted = _section(ramp).get('alerted') or {}
    if detail.startswith('needs_review') and detail not in alerted:
        _alert(ramp, detail)
    if ramp.status == 'PROCESSING' and _phase(ramp) == 'funded' and 'note:convertir' not in alerted:
        _ops_note(ramp, 'convertir')


def _ops_note(ramp: RampTransaction, action: str) -> None:
    """A funded send waiting on VEXPay's manual conversion."""
    section = _section(ramp)
    usdt = Decimal(str(section.get('funded_wei') or section.get('deposit_wei') or '0')) / Decimal(10 ** 18)
    try:
        from config.ops_alerts import send_ops_alert
        sent = send_ops_alert(
            f'💱 VEXPay envío {ramp.internal_id}: {action} {usdt.quantize(MICRO)} USDT '
            f'(depósito {section.get("deposit_address")}, ref {customer_ref(ramp)}, tx {section.get("funding_tx_hash")}). '
            f'Estimado Bs {section.get("estimated_ves")}. Márcalo convertido en el admin.',
            dedupe_key=f'vexpay:{ramp.pk}:{action}', dedupe_seconds=86400,
        )
    except Exception:  # noqa: BLE001
        logger.exception('VEXPay conversion note failed for ramp %s', ramp.pk)
        sent = False
    if sent:
        alerted = dict(_section(RampTransaction.objects.get(pk=ramp.pk)).get('alerted') or {})
        alerted[f'note:{action}'] = _now_iso()
        _update(ramp.pk, alerted=alerted)


def mark_converted(ramp: RampTransaction, ves_amount: Decimal, *, operator: str) -> RampTransaction:
    """Ops: VEXPay converted this deposit and credited `ves_amount`."""
    section = _section(ramp)
    try:
        ves_amount = Decimal(str(ves_amount)).quantize(vexpay.CENT, rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError):
        raise VexPayOffRampError('Monto en bolívares no válido.')
    estimated = Decimal(str(section.get('estimated_ves') or '0'))
    if not ves_amount.is_finite() or ves_amount <= 0:
        raise VexPayOffRampError('Monto en bolívares no válido.')
    if estimated > 0 and abs(ves_amount - estimated) > estimated * OPS_SANITY_BAND:
        raise VexPayOffRampError(
            f'Bs {ves_amount} se aleja más de 25% del estimado (Bs {estimated}). Revisa la cifra.')
    updated = _update(ramp.pk, require=lambda c: c.status == 'PROCESSING' and _phase(c) == 'funded',
                      detail='paying', phase='converted', ves_amount=format(ves_amount, 'f'),
                      converted_by=operator[:80], converted_at=_now_iso())
    if updated is None:
        raise VexPayOffRampError('Este envío no está esperando conversión.')
    RampTransaction.objects.filter(pk=ramp.pk).update(fiat_amount=ves_amount)
    return RampTransaction.objects.get(pk=ramp.pk)


def _lease_expired(section: dict) -> bool:
    until = _parse_time(section.get('dispatch_lease_until'))
    return until is None or until < timezone.now()


def retry_payout(ramp: RampTransaction, *, operator: str, reviewed_key: str, reviewed_revision: int,
                 confirmed_unpaid: bool = False) -> RampTransaction:
    """Ops: send the payout again under a NEW key. Only after a definite bank
    refusal, or after ops confirmed in VEXPay that a reviewed one was not
    paid, and only for the very attempt ops reviewed (`reviewed_key`)."""
    allowed_phases = ('credit_failed', 'credit_review') if confirmed_unpaid else ('credit_failed',)
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        section = _section(current)
        if (current.status != 'PROCESSING' or _phase(current) not in allowed_phases
                or (section.get('credit_key') or '') != (reviewed_key or '')
                # ...and the destination ops saw: a correction since then
                # needs a fresh look before money goes to it.
                or int(section.get('beneficiary_revision') or 0) != int(reviewed_revision)
                or not _lease_expired(section)):
            raise VexPayOffRampError('Este envío cambió o no se puede reintentar. Recarga la página.')
        metadata = dict(current.metadata or {})
        section.update(
            phase='converted', credit_attempt=int(section.get('credit_attempt') or 0) + 1,
            retried_by=operator[:80], retried_at=_now_iso(),
            # Per-attempt state: a new attempt starts clean.
            credit_key=None, credit_body=None, credit_sent_at=None, last_replay_at=None,
            operation_id=None, pending_since=None, dispatch_lease_until=None, credit_ambiguous=False,
        )
        metadata['vexpay'] = section
        current.metadata = metadata
        current.status_detail = 'paying'
        current.save(update_fields=['metadata', 'status_detail', 'updated_at'])
        return current


def update_beneficiary(ramp: RampTransaction, beneficiary: dict, *, operator: str, reviewed_key: str,
                       reviewed_revision: int) -> RampTransaction:
    """Ops: correct the destination after a definite refusal (wrong bank or
    phone), before retrying; only from the form of the attempt and the
    destination revision ops actually reviewed."""
    def allowed(current):
        section = _section(current)
        return (current.status == 'PROCESSING' and _phase(current) == 'credit_failed'
                and (section.get('credit_key') or '') == (reviewed_key or '')
                and int(section.get('beneficiary_revision') or 0) == int(reviewed_revision))
    revision = int(_section(ramp).get('beneficiary_revision') or 0) + 1
    updated = _update(ramp.pk, require=allowed, beneficiary=beneficiary, beneficiary_revision=revision,
                      beneficiary_changed_by=operator[:80])
    if updated is None:
        raise VexPayOffRampError('Este envío cambió. Recarga la página antes de corregir el destino.')
    return updated


def mark_paid_manually(ramp: RampTransaction, reference: str, *, operator: str) -> RampTransaction:
    """Ops: VEXPay shows the payout settled (reference from its portal)."""
    reference = (reference or '').strip()[:40]
    if not reference:
        raise VexPayOffRampError('Escribe la referencia del pago.')
    updated = _update(ramp.pk, require=lambda c: c.status == 'PROCESSING'
                      and _phase(c) in ('paying', 'credit_pending', 'credit_review', 'credit_failed'),
                      status='COMPLETED', detail='delivered', phase='paid', bank_reference=reference,
                      paid_by=operator[:80])
    if updated is None:
        raise VexPayOffRampError('Este envío no está en pago.')
    RampTransaction.objects.filter(pk=ramp.pk).update(completed_at=timezone.now())
    return RampTransaction.objects.get(pk=ramp.pk)


# ------------------------------------------------------------------ payout

def _credit_key(ramp: RampTransaction) -> str:
    return f"{ramp.external_id}:credit:{int(_section(ramp).get('credit_attempt') or 0)}"


def _inflight_ves(exclude_pk: int) -> Decimal:
    """Bolívares of other payouts sent but not settled (they may not be
    deducted from VEXPay's available balance yet)."""
    total = Decimal('0')
    for other in RampTransaction.objects.filter(
        provider=vexpay.PROVIDER, direction=DIRECTION, status='PROCESSING',
        metadata__vexpay__phase__in=['paying', 'credit_pending', 'credit_review'],
    ).exclude(pk=exclude_pk):
        try:
            total += Decimal(str(_section(other).get('ves_amount') or '0'))
        except (InvalidOperation, TypeError, ValueError):
            pass
    return total


def _claim_payout(ramp: RampTransaction, client: VexPayClient) -> dict | None:
    """Under the payout lock: check the free balance and commit the attempt
    (key and exact body) before anything leaves. None when not payable now."""
    with transaction.atomic():
        _advisory_lock(PAYOUT_LOCK)
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        section = _section(current)
        if current.status != 'PROCESSING' or _phase(current) != 'converted':
            return None
        ves = Decimal(str(section.get('ves_amount') or '0'))
        balance = client.balance() or {}
        try:
            available = Decimal(str(balance.get('availableVes') or '0'))
        except (InvalidOperation, TypeError, ValueError):
            available = Decimal('0')
        if ves <= 0 or available - _inflight_ves(current.pk) < ves:
            if current.status_detail != 'waiting_balance':
                current.status_detail = 'waiting_balance'
                current.save(update_fields=['status_detail', 'updated_at'])
            return None
        beneficiary = section.get('beneficiary') or {}
        body = {
            'bank_code': str(beneficiary.get('bank_code') or ''),
            'cedula': str(beneficiary.get('cedula') or ''),
            'phone': str(beneficiary.get('phone') or ''),
            'ves_amount': format(ves, 'f'),
            'concept': f'Confio {str(current.internal_id)[:8]}',
        }
        metadata = dict(current.metadata or {})
        section.update(phase='paying', credit_key=_credit_key(current), credit_body=body,
                       credit_sent_at=_now_iso(),
                       dispatch_lease_until=(timezone.now() + DISPATCH_LEASE).isoformat())
        metadata['vexpay'] = section
        current.metadata = metadata
        current.status_detail = 'paying'
        current.save(update_fields=['metadata', 'status_detail', 'updated_at'])
        return {'key': section['credit_key'], 'body': body}


def _send_credit(ramp: RampTransaction, claim: dict, client: VexPayClient) -> RampTransaction:
    body = claim['body']
    try:
        answer = client.credit(bank_code=body['bank_code'], cedula=body['cedula'], phone=body['phone'],
                               ves_amount=Decimal(body['ves_amount']), concept=body['concept'],
                               idempotency_key=claim['key'])
    except VexPayAmbiguousError:
        # Unknown: replayed under the same key by the next poll, inside the
        # window. From now on no refusal of this attempt is proof it unpaid.
        updated = _update(ramp.pk, require=_same_attempt(claim['key']), credit_ambiguous=True)
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    except VexPayError as exc:
        return _credit_refused(ramp, exc, claim['key'])
    return apply_credit_answer(ramp, answer, claim['key'])


def _same_attempt(key: str, phases=('paying', 'credit_pending')):
    """Every answer is fenced to the attempt that sent it: a late answer of an
    older attempt never moves a newer one."""
    def check(current):
        return (current.status == 'PROCESSING' and _phase(current) in phases
                and _section(current).get('credit_key') == key)
    return check


def _earlier_dispatch_unknown(ramp: RampTransaction) -> bool:
    """An earlier dispatch of this attempt may have paid: a refusal now only
    says THIS request was refused."""
    return bool(_section(RampTransaction.objects.get(pk=ramp.pk)).get('credit_ambiguous'))


def _credit_refused(ramp: RampTransaction, exc: VexPayError, key: str) -> RampTransaction:
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    bank_code = str(payload.get('bankCode') or payload.get('code') or '').upper()
    if _earlier_dispatch_unknown(ramp):
        return _set_payout(ramp, key, 'credit_review',
                           f'needs_review:credit_unknown:refused_after_timeout:{exc.status}:{bank_code or exc.code}')
    if exc.status == 403:
        # Crédito inmediato not enabled on the account: no bank call was made.
        return _set_payout(ramp, key, 'credit_failed', 'needs_review:credit_unavailable')
    if exc.status == 422 and bank_code in CREDIT_REJECTED and bank_code not in CREDIT_DUPLICATE:
        return _set_payout(ramp, key, 'credit_failed', f'needs_review:credit_rejected:{bank_code}')
    if exc.status == 400 and str(exc.code).lower() == 'insufficient_balance':
        # Definitely not sent; go back to waiting for the balance.
        # VEXPay would replay this cached refusal for 24 h under the same
        # key: the next try gets a fresh attempt.
        current = RampTransaction.objects.get(pk=ramp.pk)
        updated = _update(ramp.pk, require=_same_attempt(key, ('paying',)),
                          phase='converted', detail='waiting_balance', dispatch_lease_until=None,
                          credit_attempt=int(_section(current).get('credit_attempt') or 0) + 1,
                          credit_key=None, credit_body=None, credit_sent_at=None, last_replay_at=None,
                          operation_id=None, pending_since=None, credit_ambiguous=False)
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    # Anything else (duplicate, key conflict, validation) cannot prove the
    # money did not leave: ops checks VEXPay.
    return _set_payout(ramp, key, 'credit_review',
                       f'needs_review:credit_unknown:{exc.status}:{bank_code or exc.code}')


def _set_payout(ramp: RampTransaction, key: str, phase: str, detail: str, *,
                lease_free: bool = False) -> RampTransaction:
    """`lease_free`: a transition no in-flight dispatch may race (review by
    timeout), so it also waits for the dispatch lease to end."""
    def allowed(current):
        return _same_attempt(key)(current) and (not lease_free or _lease_expired(_section(current)))
    # An answer ends its dispatch: release the lease with it.
    updated = _update(ramp.pk, require=allowed, phase=phase, detail=detail, dispatch_lease_until=None)
    current = updated or RampTransaction.objects.get(pk=ramp.pk)
    if updated is not None and detail.startswith('needs_review'):
        _alert(current, detail)
    return current


def apply_credit_answer(ramp: RampTransaction, answer: dict, key: str) -> RampTransaction:
    """Only ACCP is delivery. A pending code wins over any success flag, and
    anything unrecognised is ops' to check, never a delivery."""
    answer = answer if isinstance(answer, dict) else {}
    code = str(answer.get('code') or '').upper()
    operation_id = str(answer.get('id') or answer.get('Id') or '')
    reference = str(answer.get('reference') or '')
    if code in CREDIT_PENDING:
        if not operation_id and not _section(ramp).get('operation_id'):
            return _set_payout(ramp, key, 'credit_review', 'needs_review:credit_unknown:pending_without_id')
        updated = _update(ramp.pk, require=_same_attempt(key),
                          phase='credit_pending', detail='bank_processing', dispatch_lease_until=None,
                          operation_id=operation_id or _section(ramp).get('operation_id'),
                          pending_since=_section(ramp).get('pending_since') or _now_iso())
        return updated or RampTransaction.objects.get(pk=ramp.pk)
    if code in CREDIT_ACCEPTED:
        updated = _update(ramp.pk, require=_same_attempt(key),
                          status='COMPLETED', detail='delivered', phase='paid', dispatch_lease_until=None,
                          bank_reference=reference, operation_id=operation_id)
        if updated is not None:
            RampTransaction.objects.filter(pk=ramp.pk).update(completed_at=timezone.now(),
                                                              provider_order_id=operation_id[:255])
        return RampTransaction.objects.get(pk=ramp.pk)
    if code in CREDIT_REJECTED and code not in CREDIT_DUPLICATE and not _earlier_dispatch_unknown(ramp):
        return _set_payout(ramp, key, 'credit_failed', f'needs_review:credit_rejected:{code}')
    return _set_payout(ramp, key, 'credit_review', f'needs_review:credit_unknown:{code or "no_code"}')


def pay_out(ramp: RampTransaction, client: VexPayClient | None = None) -> RampTransaction:
    client = client or VexPayClient()
    try:
        claim = _claim_payout(ramp, client)
    except VexPayError:
        logger.warning('VEXPay balance read failed for send %s', ramp.pk, exc_info=True)
        return RampTransaction.objects.get(pk=ramp.pk)
    if claim is None:
        return RampTransaction.objects.get(pk=ramp.pk)
    return _send_credit(ramp, claim, client)


def _resume_payout(ramp: RampTransaction, client: VexPayClient) -> RampTransaction:
    """A payout whose answer was lost: replay the SAME key and body while
    VEXPay still remembers it, then hand it to ops."""
    section = _section(ramp)
    key = section.get('credit_key') or ''
    if not _lease_expired(section):
        return ramp  # a dispatch of this attempt may still be in flight
    sent_at = _parse_time(section.get('credit_sent_at'))
    if sent_at is None or sent_at < timezone.now() - CREDIT_REPLAY_WINDOW:
        return _set_payout(ramp, key, 'credit_review', 'needs_review:credit_unknown:replay_window',
                           lease_free=True)
    claim = {'key': key, 'body': section.get('credit_body')}
    if not claim['key'] or not isinstance(claim['body'], dict):
        return _set_payout(ramp, key, 'credit_review', 'needs_review:credit_unknown:no_claim',
                           lease_free=True)

    def replayable(current):
        now_section = _section(current)
        sent = _parse_time(now_section.get('credit_sent_at'))
        return (_same_attempt(key, ('paying',))(current) and _lease_expired(now_section)
                and sent is not None and sent >= timezone.now() - CREDIT_REPLAY_WINDOW)
    # Re-checked and leased under the row lock right before it leaves.
    # A replay exists only because an earlier answer was never recorded
    # (timeout or a worker that died): that earlier dispatch may have paid.
    if _update(ramp.pk, require=replayable, last_replay_at=_now_iso(), credit_ambiguous=True,
               dispatch_lease_until=(timezone.now() + DISPATCH_LEASE).isoformat()) is None:
        return RampTransaction.objects.get(pk=ramp.pk)
    return _send_credit(ramp, claim, client)


def _poll_operation(ramp: RampTransaction, client: VexPayClient) -> RampTransaction:
    section = _section(ramp)
    since = _parse_time(section.get('pending_since'))
    try:
        answer = client.operation(section['operation_id'])
    except VexPayError:
        answer = None
    if answer is not None:
        ramp = apply_credit_answer(ramp, answer, section.get('credit_key') or '')
        if ramp.status == 'COMPLETED' or _phase(ramp) != 'credit_pending':
            return ramp
    if since is not None and since < timezone.now() - CREDIT_PENDING_STALE:
        return _set_payout(ramp, section.get('credit_key') or '', 'credit_review',
                           'needs_review:credit_pending_stale')
    return ramp


# ------------------------------------------------------------------ reconciliation

def sync_off_ramp(ramp: RampTransaction, client: VexPayClient | None = None, rpc=None) -> RampTransaction:
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
            # No address has left the server yet: nothing to look for.
            if ramp.created_at < now - FUNDING_WINDOW:
                return fail_unfunded(ramp, 'expired_unfunded')
            return ramp
        found = _find_funding(ramp, rpc)
        if found not in (None, _UNKNOWN):
            return _mark_funded(ramp, *found)
        section = _section(ramp)
        started = _parse_time(section.get('funding_started_at')) or ramp.created_at
        if found is _UNKNOWN and started < now - UNVERIFIABLE_AFTER:
            # Neither proven nor disproven for half a day: ops looks, and the
            # chain watch continues (PROCESSING funding_reported is reconciled).
            updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING'
                              and _phase(c) == 'funding_reported',
                              status='PROCESSING', detail='needs_review:funding_unverifiable')
            if updated is not None:
                _alert(updated, updated.status_detail)
                return updated
        if found is None and started < now - UNFUNDED_EXPIRY:
            if not section.get('funding_tx_hashes'):
                # Claimed, never broadcast (or never mined): close it; the
                # late-funding watch keeps looking.
                updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING'
                                  and _phase(c) == 'funding_reported' and not _section(c).get('funding_tx_hashes'),
                                  status='FAILED', detail='expired_unfunded')
                return updated or RampTransaction.objects.get(pk=ramp.pk)
            # A hash was reported but never proven: ops decides.
            updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING'
                              and _phase(c) == 'funding_reported',
                              status='PROCESSING', detail='needs_review:funding_not_found')
            if updated is not None:
                _alert(updated, updated.status_detail)
                return updated
        return RampTransaction.objects.get(pk=ramp.pk)
    if ramp.status == 'FAILED':
        if (ramp.status_detail in ('expired_unfunded', 'cancelled_by_user')
                and _section(ramp).get('funding_started_at')):
            found = _find_funding(ramp, rpc)
            if found not in (None, _UNKNOWN):
                return _mark_funded(ramp, *found, late=True)
        return ramp
    if ramp.status != 'PROCESSING':
        return ramp
    if phase == 'funding_reported':
        # Reviewed as "funding not found": the chain may still prove it.
        found = _find_funding(ramp, rpc)
        if found not in (None, _UNKNOWN):
            return _mark_funded(ramp, *found)
        return ramp
    client = client or VexPayClient()
    if phase == 'converted':
        return pay_out(ramp, client)
    if phase == 'paying':
        return _resume_payout(ramp, client)
    if phase == 'credit_pending':
        return _poll_operation(ramp, client)
    return ramp


def open_off_ramps():
    """Sends the poller reconciles: open ones, and closed-unfunded ones still
    inside the late-funding watch."""
    from django.db.models import Q
    now = timezone.now()
    return RampTransaction.objects.filter(provider=vexpay.PROVIDER, direction=DIRECTION).filter(
        Q(status__in=vexpay.OPEN_STATUSES)
        | Q(status='FAILED', status_detail__in=['expired_unfunded', 'cancelled_by_user'],
            created_at__gte=now - LATE_FUNDING_WATCH, metadata__vexpay__has_key='funding_started_at')
    ).order_by('created_at')


def due_for_sync(ramp: RampTransaction) -> bool:
    """Open sends every poll; closed-unfunded ones (a chain scan) every 10 min;
    a funded send waiting on ops costs nothing."""
    if ramp.status == 'PROCESSING' and _phase(ramp) in ('funded', 'credit_failed', 'credit_review'):
        return False
    if ramp.status == 'FAILED':
        return ramp.updated_at < timezone.now() - timedelta(minutes=10)
    return True


def active_order(user) -> RampTransaction | None:
    """The send the app resumes: not yet delivered nor closed."""
    return RampTransaction.objects.filter(
        provider=vexpay.PROVIDER, direction=DIRECTION, actor_user=user, status__in=vexpay.OPEN_STATUSES,
    ).order_by('-created_at').first()


def current_block(rpc=None) -> int | None:
    try:
        return int((rpc or _rpc_default())('eth_blockNumber', []), 16)
    except Exception:  # noqa: BLE001
        logger.warning('BSC block number unavailable for a VEXPay send', exc_info=True)
        return None
