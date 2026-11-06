"""Return dollars stranded on a person's own Polygon address to their balance.

Relay refunds (Koywe top-ups routed through Polygon, QR Bolivia receives,
Infinia) and mistaken deposits land as USDC on the person's EVM address on
Polygon. No screen showed that money and nobody but the person can move it.

USDC on Polygon implements EIP-3009, so the person signs ONE
ReceiveWithAuthorization that only Relay's receiver contract can execute.
Relay submits it, pays the Polygon gas and takes its cost from the USDC; the
USDT arrives in the person's BSC wallet. No sponsor, no POL, no custody: the
server only prices, verifies and forwards the person's own signature.

States: quoted -> submitted -> delivered | refunded | failed | needs_review;
a quoted row whose signature window passes unused becomes expired.
"""
import logging
import re
import time
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from eth_abi import encode
from eth_utils import keccak

from . import bridge_chain as chain
from .allbridge_next import NextError, TOKENS, address, uint
from .models import PolygonReturn

logger = logging.getLogger(__name__)

SOURCE, DESTINATION = 'POL:USDC', 'BSC:USDT'
# Below this Relay's own cost rule refuses the route; showing a card the
# person cannot act on would only confuse them.
MIN_UNITS = 500_000  # 0.50 USDC
BALANCE_CACHE_SECONDS = 600
# Relay's EIP-3009 receiver (approval proxy). Anything else in a quote is
# refused: the signature would let that contract pull the person's USDC.
DEFAULT_RECEIVERS = ('0xccc88a9d1b4ed6b0eaba998850414b24f1c315be',)
MAX_SIGNATURE_WINDOW = 3600
BRIDGE_SIGNATURE_WINDOW = 900
MIN_SIGNATURE_LEFT = 60
# A signed permit Relay never executed is dead once it is past validBefore;
# allow Relay's own lag before calling it expired.
EXPIRE_GRACE_SECONDS = 900
REVIEW_AFTER_SECONDS = 2 * 3600
# submit() owns the first hand-off; the worker takes over only after this.
FIRST_POST_GRACE_SECONDS = 120

PERMIT_TYPE = [
    {'name': 'from', 'type': 'address'}, {'name': 'to', 'type': 'address'},
    {'name': 'value', 'type': 'uint256'}, {'name': 'validAfter', 'type': 'uint256'},
    {'name': 'validBefore', 'type': 'uint256'}, {'name': 'nonce', 'type': 'bytes32'},
]
PERMIT_TYPEHASH = keccak(text='ReceiveWithAuthorization(address from,address to,uint256 value,'
                              'uint256 validAfter,uint256 validBefore,bytes32 nonce)')

BUSY = 'Ya estamos devolviendo tu dinero a tu saldo.'
NOTHING = 'No tienes dinero por recuperar.'
UNAVAILABLE = 'No pudimos preparar la devolución. Intenta de nuevo en unos minutos.'


class PolygonReturnError(NextError):
    """Message is shown to the person as-is (Spanish)."""


def enabled() -> bool:
    return bool(getattr(settings, 'POLYGON_RETURN_ENABLED', True))


def receivers() -> set[str]:
    configured = getattr(settings, 'POLYGON_RETURN_RELAY_RECEIVERS', None) or DEFAULT_RECEIVERS
    return {address(a) for a in configured}


def _cache_key(addr: str) -> str:
    return f'polygon_return:balance:{addr}'


def balance(addr: str, *, fresh: bool = False) -> int | None:
    """USDC units on the address, or None when Polygon cannot be read.

    The Home path (fresh=False) is cached, uses a short timeout, remembers a
    failing RPC for a minute and lets only one request read at a time."""
    addr = address(addr)
    key = _cache_key(addr)
    if not fresh:
        cached = cache.get(key)
        if cached is not None:
            return int(cached)
        if cache.get(key + ':down') or not cache.add(key + ':reading', 1, 10):
            return None
    try:
        units = chain.token_balance(SOURCE, addr, timeout=(5, 15) if fresh else (2, 3))
    except Exception:
        logger.warning('Polygon USDC balance read failed for %s', addr, exc_info=True)
        if not fresh:
            cache.set(key + ':down', 1, 60)
        return None
    finally:
        if not fresh:
            cache.delete(key + ':reading')
    cache.set(key, units, BALANCE_CACHE_SECONDS)
    return units


def forget_balance(addr: str):
    cache.delete(_cache_key(address(addr)))


def _owner_address(owner) -> str | None:
    raw = getattr(owner, 'bsc_address', None)
    try:
        return address(raw) if raw else None
    except Exception:
        return None


def _open(owner):
    return PolygonReturn.objects.filter(confio_account=owner, status='submitted').order_by('-created_at').first()


STRIKES_WINDOW = timedelta(hours=24)
# A return under review pauses silent retries for that account this long.
REVIEW_HOLD = timedelta(days=7)
MAX_STRIKES = 2


def provider_flow_open(owner) -> bool:
    """USDC an Infinia/Cobre journey or a Polygon-source bridge parked on the
    address on purpose: that flow moves it itself, so never sweep it."""
    from .infinia_bridge import live_journeys
    from .models import CobreJourney, InfiniaJourney, PaymentBridgeQuote
    # The same "is another journey using these funds?" predicate the journey
    # workers use: a parked needs_review journey nothing will ever advance
    # (e.g. return_bridge_refunded) must not hold the money forever. No age
    # limit on live ones.
    if live_journeys(InfiniaJourney.objects.filter(confio_account=owner, direction='to_wallet')).exists():
        return True
    if live_journeys(CobreJourney.objects.filter(confio_account=owner, direction='to_wallet'),
                     recoverable=()).exists():
        return True
    return PaymentBridgeQuote.objects.filter(
        confio_account=owner, source_token_id=SOURCE).filter(
        Q(transfer__isnull=True, expires_at__gt=timezone.now())
        | Q(transfer__status__in=['prepared', 'submitted', 'bridging'])).exists()


REFUSED_QUOTE_SECONDS = 3600


def _refused_key(addr: str, units: int) -> str:
    return f'polygon_return:refused:{addr}:{units}'


def struck_out(owner) -> bool:
    """Repeated refunds/rejections cost the person Relay's gas each time:
    stop retrying silently and tell ops."""
    reviewing = PolygonReturn.objects.filter(
        confio_account=owner, status='needs_review', purpose='sweep',
        updated_at__gte=timezone.now() - REVIEW_HOLD).order_by('-updated_at').first()
    if reviewing is not None:
        return True  # ops is looking at this money: never move it silently meanwhile
    since = timezone.now() - STRIKES_WINDOW
    strikes = PolygonReturn.objects.filter(confio_account=owner, status__in=['failed', 'refunded'], purpose='sweep',
                                          updated_at__gte=since).order_by('-updated_at')
    if strikes.count() < MAX_STRIKES:
        return False
    latest = strikes.first()
    _alert(latest, 'struck_out', f'⚠️ Devolución Polygon→BSC pausada 24h para la cuenta {owner.pk}: '
                                 f'{MAX_STRIKES} intentos fallidos o reembolsados. Revisa a mano.')
    return True


def state(owner) -> dict:
    """What the Home card shows: {'state': 'none'|'available'|'in_progress', 'amount_units', 'return_id'}."""
    none = {'state': 'none', 'amount_units': '0', 'return_id': None}
    addr = _owner_address(owner)
    if not enabled() or not addr:
        return none
    current = _open(owner)
    if current is not None:
        return {'state': 'in_progress', 'amount_units': current.amount_units, 'return_id': current.internal_id}
    if provider_flow_open(owner) or struck_out(owner):
        return none
    units = balance(addr)
    if units is None or units < MIN_UNITS or cache.get(_refused_key(addr, units)):
        return none
    return {'state': 'available', 'amount_units': str(units), 'return_id': None}


# ------------------------------------------------------------------ quote

def _permit_step(result: dict, addr: str, amount: int, now: int) -> dict:
    """The single signature step of a permit quote, checked field by field
    against our own terms. Raises on anything else."""
    try:
        steps = result['steps']
        if len(steps) != 1:
            raise NextError('Relay permit quote must have exactly one step')
        step = steps[0]
        if step.get('kind') != 'signature' or len(step.get('items') or []) != 1:
            raise NextError('Relay permit step is not a single signature')
        request_id = step['requestId']
        if not isinstance(request_id, str) or len(request_id) != 66 or result.get('requestId', request_id) != request_id:
            raise NextError('Relay permit request ID mismatch')
        data = step['items'][0]['data']
        sign, post = data['sign'], data['post']
        if sign.get('signatureKind') != 'eip712' or sign.get('primaryType') != 'ReceiveWithAuthorization':
            raise NextError('Relay permit is not ReceiveWithAuthorization')
        if sign['types'].get('ReceiveWithAuthorization') != PERMIT_TYPE:
            raise NextError('Relay permit type mismatch')
        domain = sign['domain']
        if (domain.get('name') != 'USD Coin' or str(domain.get('version')) != '2'
                or int(domain.get('chainId')) != 137 or address(domain.get('verifyingContract')) != chain.USDC):
            raise NextError('Relay permit domain mismatch')
        value = sign['value']
        receiver = address(value['to'])
        valid_before = int(value['validBefore'])
        nonce = value['nonce']
        if address(value['from']) != addr or receiver not in receivers():
            raise NextError('Relay permit parties mismatch')
        if int(value['value']) != amount or int(value['validAfter']) != 0:
            raise NextError('Relay permit amount mismatch')
        if not now + MIN_SIGNATURE_LEFT < valid_before <= now + MAX_SIGNATURE_WINDOW:
            raise NextError('Relay permit window out of bounds')
        if not isinstance(nonce, str) or len(nonce) != 66 or int(nonce, 16) < 0:
            raise NextError('Relay permit nonce invalid')
        body = post['body']
        if (post.get('endpoint') != '/execute/permits' or post.get('method') != 'POST'
                or body.get('kind') != 'eip3009' or body.get('requestId') != request_id):
            raise NextError('Relay permit post mismatch')
        post_body = {'kind': 'eip3009', 'requestId': request_id}
        if body.get('api') in {'bridge', 'swap', 'user-swap'}:
            post_body['api'] = body['api']
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise NextError('Relay permit quote is missing required data') from exc
    return {'request_id': request_id, 'receiver': receiver, 'nonce': nonce.lower(),
            'valid_before': valid_before, 'post_body': post_body}


def digest(ret: PolygonReturn) -> bytes:
    """EIP-712 digest of the person's ReceiveWithAuthorization, rebuilt from
    our stored terms (never from Relay's payload)."""
    message = keccak(encode(
        ['bytes32', 'address', 'address', 'uint256', 'uint256', 'uint256', 'bytes32'],
        [PERMIT_TYPEHASH, ret.address, ret.receiver, int(ret.amount_units), 0,
         int(ret.valid_before), bytes.fromhex(ret.nonce.removeprefix('0x'))],
    ))
    return keccak(b'\x19\x01' + chain.authorization_domain() + message)


def _lock_account(owner):
    """Serialize returns per account without locking the Account row (sends
    lock it); transaction-scoped."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [137, int(owner.pk)])


def _reusable(owner, addr, units):
    return PolygonReturn.objects.filter(
        confio_account=owner, address=addr, status='quoted', amount_units=str(units), purpose='sweep',
        valid_before__gt=int(time.time()) + 5 * 60).order_by('-created_at').first()


def prepare(owner, *, client=None) -> PolygonReturn:
    """Price returning the whole Polygon USDC balance; returns the row the
    person signs. One open return per account. Network calls happen outside
    any lock; the lock only guards the final check-and-create."""
    from .relay import RelayClient
    if not enabled():
        raise PolygonReturnError(UNAVAILABLE)
    addr = _owner_address(owner)
    if not addr:
        raise PolygonReturnError(NOTHING)
    if _open(owner) is not None or provider_flow_open(owner) or struck_out(owner):
        raise PolygonReturnError(BUSY)
    units = balance(addr, fresh=True)
    if units is None:
        raise PolygonReturnError(UNAVAILABLE)
    if units < MIN_UNITS:
        raise PolygonReturnError(NOTHING)
    existing = _reusable(owner, addr, units)
    if existing is not None:
        return existing
    client = client or RelayClient()
    try:
        result = client.quote(SOURCE, DESTINATION, str(units), source_address=addr,
                              destination_address=addr, permit=True)
        terms = _permit_step(result, addr, units, int(time.time()))
        details = result['details']['currencyOut']
        amount_out = str(uint(details['amount'], positive=True))
        amount_out_min = str(uint(details['minimumAmount'], positive=True))
    except (NextError, KeyError, TypeError) as exc:
        logger.warning('Polygon return quote refused for account %s: %s', owner.pk, exc)
        # Relay refuses small amounts on cost: do not re-quote this exact
        # balance on every foreground (a new deposit changes the amount).
        cache.set(_refused_key(addr, units), 1, REFUSED_QUOTE_SECONDS)
        raise PolygonReturnError(UNAVAILABLE) from exc
    with transaction.atomic():
        _lock_account(owner)
        if _open(owner) is not None or provider_flow_open(owner):
            raise PolygonReturnError(BUSY)
        existing = _reusable(owner, addr, units)
        if existing is not None:
            return existing
        PolygonReturn.objects.filter(confio_account=owner, status='quoted').update(
            status='expired', failure_code='superseded', updated_at=timezone.now())
        return PolygonReturn.objects.create(
            confio_account=owner, address=addr, amount_units=str(units),
            amount_out=amount_out, amount_out_min=amount_out_min, **terms)


def create_for_bridge(owner, addr: str, units: int, *, accepted_min: int, client=None) -> PolygonReturn:
    """The signature leg of a Polygon -> wallet PaymentBridgeTransfer: an
    exact amount the bridge already priced. Relay pays the gas; no sponsor."""
    from .relay import RelayClient
    addr = address(addr)
    if _owner_address(owner) != addr:
        raise NextError('Inbound bridge must return to the active wallet')
    client = client or RelayClient()
    result = client.quote(SOURCE, DESTINATION, str(units), source_address=addr,
                          destination_address=addr, permit=True)
    now = int(time.time())
    terms = _permit_step(result, addr, units, now)
    if terms['valid_before'] > now + BRIDGE_SIGNATURE_WINDOW:
        # The bridge deadline holds the whole wallet; keep it short.
        raise NextError('Bridge price changed; request a fresh quote')
    details = result['details']['currencyOut']
    amount_out = uint(details['amount'], positive=True)
    amount_out_min = uint(details['minimumAmount'], positive=True)
    if amount_out_min < accepted_min:
        raise NextError('Bridge price changed; request a fresh quote')
    with transaction.atomic():
        _lock_account(owner)
        if _open(owner) is not None:
            raise NextError('Ya tienes un envío en curso; revisa su estado primero.')
        # A sweep quote for the same USDC must never also be signed. Never
        # touch bridge permits: a concurrent rebind's may be the bound one.
        PolygonReturn.objects.filter(confio_account=owner, status='quoted', purpose='sweep').update(
            status='expired', failure_code='superseded', updated_at=timezone.now())
        return PolygonReturn.objects.create(
            confio_account=owner, address=addr, purpose='bridge', amount_units=str(units),
            amount_out=str(amount_out), amount_out_min=str(amount_out_min), **terms)


# ------------------------------------------------------------------ submit

def submit(owner, return_id, signature: str, *, client=None) -> PolygonReturn:
    """Verify the person's signature over our stored terms, persist it, then
    hand it to Relay. A failed hand-off is retried by reconcile()."""
    from cusd_plus.sponsor_7702 import recover_intent_signer
    # No switch check here: prepare() gates sweeps, and bridge returns
    # (provider journeys) must not depend on the sweep switch.
    addr = _owner_address(owner)
    with transaction.atomic():
        _lock_account(owner)
        ret = PolygonReturn.objects.select_for_update().filter(
            internal_id=return_id, confio_account=owner).first()
        if ret is None:
            raise PolygonReturnError(NOTHING)
        if ret.status == 'submitted' and ret.signature == signature:
            # Idempotent retry of the same (deterministic) signature. While the
            # first hand-off may still be in flight, never post a duplicate:
            # Relay could refuse the first as a duplicate of the second.
            if (not ret.post_accepted and ret.submitted_at
                    and (timezone.now() - ret.submitted_at).total_seconds() < FIRST_POST_GRACE_SECONDS):
                return ret
        elif ret.status != 'quoted':
            raise PolygonReturnError(BUSY if ret.status == 'submitted' else UNAVAILABLE)
        else:
            if addr != ret.address:
                raise PolygonReturnError(UNAVAILABLE)
            if int(time.time()) >= ret.valid_before - 30:
                raise PolygonReturnError('La devolución expiró. Inténtalo de nuevo.')
            if (not isinstance(signature, str) or not re.fullmatch(r'0x[0-9a-fA-F]{130}', signature)
                    or (recover_intent_signer(digest(ret), signature) or '').lower() != ret.address):
                raise PolygonReturnError('La firma no es válida. Inténtalo de nuevo.')
            if PolygonReturn.objects.filter(confio_account=owner, status='submitted').exclude(pk=ret.pk).exists():
                raise PolygonReturnError(BUSY)
            ret.signature, ret.status, ret.submitted_at = signature, 'submitted', timezone.now()
            ret.save(update_fields=['signature', 'status', 'submitted_at', 'updated_at'])
    forget_balance(ret.address)
    return _post(ret, client=client)


# Definite refusals only; 408/429 are transient and go down the retry path.
REJECTION_CODES = {400, 401, 403, 404, 409, 422}
AUTHORIZATION_STATE = '0x' + keccak(text='authorizationState(address,bytes32)')[:4].hex()


def authorization_used(ret: PolygonReturn) -> bool | None:
    """USDC's own answer: has this signature's nonce been consumed on
    Polygon? None when Polygon cannot be read."""
    try:
        data = AUTHORIZATION_STATE + encode(['address', 'bytes32'], [
            ret.address, bytes.fromhex(ret.nonce.removeprefix('0x'))]).hex()
        return int(chain.rpc('POL', 'eth_call', [{'to': chain.USDC, 'data': data}, 'latest']), 16) != 0
    except Exception:
        logger.warning('USDC authorizationState read failed for return %s', ret.pk, exc_info=True)
        return None


def _post(ret: PolygonReturn, *, client=None) -> PolygonReturn:
    from .relay import RelayClient, RelayError
    if ret.post_accepted or ret.status != 'submitted':
        return ret
    # Only a refusal of the FIRST hand-off proves Relay never took it: a
    # re-post after a lost response can be refused as a duplicate while
    # Relay still holds the first one.
    first_attempt = PolygonReturn.objects.filter(pk=ret.pk, post_attempted=False).update(
        post_attempted=True, updated_at=timezone.now()) == 1
    ret.post_attempted = True
    try:
        (client or RelayClient()).execute_permit(ret.post_body, ret.signature)
    except NextError as exc:
        status_code = getattr(exc, 'status_code', None)
        if first_attempt and isinstance(exc, RelayError) and status_code in REJECTION_CODES \
                and authorization_used(ret) is False:
            # Relay refused it outright and the USDC never moved: the person
            # can try again right away (the card shows the money again).
            logger.warning('Relay refused permit for return %s: %s', ret.internal_id, exc)
            # Never over a post Relay accepted meanwhile (a concurrent retry).
            PolygonReturn.objects.filter(pk=ret.pk, status='submitted', post_accepted=False).update(
                status='failed', failure_code=f'relay_rejected_{status_code}', updated_at=timezone.now())
            ret.refresh_from_db()
            forget_balance(ret.address)
            return ret
        # Ambiguous: Relay may have taken it. reconcile() re-reads and re-posts
        # while the signature is still valid.
        logger.warning('Relay permit post failed for return %s: %s', ret.internal_id, exc)
        return ret
    PolygonReturn.objects.filter(pk=ret.pk).update(post_accepted=True, updated_at=timezone.now())
    ret.post_accepted = True
    return ret


# ------------------------------------------------------------------ reconcile

def _alert(ret: PolygonReturn, key: str, text: str):
    if key in (ret.alerted or {}):
        return
    try:
        from config.ops_alerts import send_ops_alert
        sent = send_ops_alert(text, dedupe_key=f'polygon_return:{ret.pk}:{key}', dedupe_seconds=86400)
    except Exception:
        logger.exception('Polygon return alert failed for %s', ret.pk)
        return
    if sent is not False:
        alerted = dict(ret.alerted or {}, **{key: timezone.now().isoformat()})
        PolygonReturn.objects.filter(pk=ret.pk).update(alerted=alerted)
        ret.alerted = alerted


def _finish(ret: PolygonReturn, status: str, **fields) -> PolygonReturn:
    with transaction.atomic():
        locked = PolygonReturn.objects.select_for_update().get(pk=ret.pk)
        if locked.status != 'submitted':
            return locked
        locked.status = status
        for key, value in fields.items():
            setattr(locked, key, value)
        locked.save()
    forget_balance(locked.address)
    return locked


def _delivered(ret: PolygonReturn, status: dict) -> PolygonReturn:
    out_hashes = [h for h in (status.get('txHashes') or []) if isinstance(h, str)]
    in_hashes = [h for h in (status.get('inTxHashes') or []) if isinstance(h, str)]
    if len(out_hashes) != 1:
        return _review(ret, 'split_or_missing_delivery')
    receipt = chain.final_receipt('BSC', out_hashes[0])
    if not receipt:
        return ret  # not final yet
    received = chain.received_units(receipt, DESTINATION, ret.address)
    if received < int(ret.amount_out_min):
        return _review(ret, 'delivery_below_minimum')
    return _finish(ret, 'delivered', destination_tx_hash=out_hashes[0].lower(),
                   source_tx_hash=(in_hashes[0].lower() if in_hashes else ''),
                   actual_out_units=str(received), failure_code='')


def _review(ret: PolygonReturn, reason: str) -> PolygonReturn:
    ret = _finish(ret, 'needs_review', failure_code=reason)
    _alert(ret, f'review_{reason}',
           f'⚠️ Devolución Polygon→BSC {ret.internal_id} (cuenta {ret.confio_account_id}) requiere revisión: {reason}.')
    return ret


def _expire_or_review(ret: PolygonReturn, now: int, kind) -> PolygonReturn:
    """Time-based exits, also taken when Relay cannot be read. Expiry is
    decided by USDC itself: an unused nonce past validBefore can never move."""
    if now > ret.valid_before + EXPIRE_GRACE_SECONDS:
        if authorization_used(ret) is False:
            return _finish(ret, 'expired', failure_code='permit_unused')
    if ret.submitted_at and (timezone.now() - ret.submitted_at).total_seconds() > REVIEW_AFTER_SECONDS:
        return _review(ret, f'stalled_{kind or "unreadable"}')
    return ret


def reconcile(ret: PolygonReturn, *, client=None) -> PolygonReturn:
    """Advance one submitted return from Relay's status. Never raises."""
    from .relay import RelayClient
    if ret.status != 'submitted':
        return ret
    if not ret.post_attempted and ret.submitted_at and \
            (timezone.now() - ret.submitted_at).total_seconds() < FIRST_POST_GRACE_SECONDS:
        return ret  # submit() is making the first hand-off right now; never race it
    client = client or RelayClient()
    now = int(time.time())
    try:
        status = client.status(ret.request_id) or {}
    except Exception:
        logger.warning('Relay status unreadable for return %s', ret.pk, exc_info=True)
        try:
            return _expire_or_review(ret, now, None)
        except Exception:
            logger.exception('Polygon return reconcile failed for %s', ret.pk)
            return ret
    try:
        kind = status.get('status')
        if kind == 'success':
            return _delivered(ret, status)
        if kind == 'refund':
            # The USDC went back to the person's Polygon address: the card
            # shows it again and they can retry.
            ret = _finish(ret, 'refunded', failure_code='relay_refund')
            _alert(ret, 'refund', f'ℹ️ Devolución Polygon→BSC {ret.internal_id} reembolsada por Relay (cuenta {ret.confio_account_id}).')
            return ret
        if kind == 'failure':
            return _review(ret, 'relay_failure')
        if kind in (None, 'waiting', 'unknown') and not status.get('inTxHashes') and now < ret.valid_before - 30:
            return _post(ret, client=client)
        return _expire_or_review(ret, now, kind)
    except Exception:
        logger.exception('Polygon return reconcile failed for %s', ret.pk)
        return ret


def open_returns():
    return PolygonReturn.objects.filter(status='submitted').order_by('submitted_at')


def usd(units) -> Decimal:
    return (Decimal(int(units)) / Decimal(10) ** TOKENS[SOURCE][1]).quantize(Decimal('0.01'), ROUND_DOWN)


def usd_out(units) -> Decimal:
    return (Decimal(int(units)) / Decimal(10) ** TOKENS[DESTINATION][1]).quantize(Decimal('0.01'), ROUND_DOWN)
