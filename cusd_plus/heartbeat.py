"""
ConfioHeartbeat keeper and monitor (contracts/cusd_plus/ConfioHeartbeat.sol).

Emergency Exit opens for every user once the heartbeat has been silent for
`silenceRequired` (14 days at launch) — frozen accounts included. So a beat
must mean "Confío is operating", and a missed beat must be noticed long
before the window runs out:

- `post_confio_heartbeat` (daily): checks that the system actually works
  (database + BSC RPC pool), signs `beat()` with the KMS beater, and only
  calls it done when the receipt succeeded AND carries a `Beat(uint64)` log
  from the heartbeat contract.
- `check_confio_heartbeat` (hourly): reads `lastBeat()` from chain — never
  "did the task run" — and alerts when chain time minus the last beat
  exceeds CONFIO_HEARTBEAT_STALE_ALERT_SECONDS, and when the beater's BNB
  falls under CONFIO_HEARTBEAT_BEATER_MIN_BALANCE_WEI.

Alerts are ERROR/CRITICAL log lines, the same channel as the sponsor-balance
and accrue keepers in cusd_plus/tasks.py.

Both tasks are no-ops while CONFIO_HEARTBEAT_ADDRESS is unset.
"""
import logging
import re
import time

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, connection
from eth_utils import keccak

from config.ops_alerts import send_ops_alert

from .tasks import _rpc

logger = logging.getLogger(__name__)

# Set while the heartbeat is stale, so the first healthy check sends "recovered".
STALE_FLAG_KEY = 'confio_heartbeat:stale_alerted'


_MESES = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')


def _fecha_utc(ts: int) -> str:
    """'19 oct 2026, 14:40 UTC' — chain time is UTC; the team spans timezones."""
    import datetime
    d = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
    return f'{d.day} {_MESES[d.month - 1]} {d.year}, {d:%H:%M} UTC'


def daily_report(result: dict) -> bool:
    """Post the daily 'all normal' status to the ops group (Spanish).

    Sent after a confirmed beat (or when the chain already had a fresh one),
    so the team sees the heartbeat every day — silence in the group is itself
    a signal. Deduped per day so retries and a second scheduler don't repeat it.
    """
    heartbeat = heartbeat_address()
    try:
        last = _call_uint(heartbeat, SEL_LAST_BEAT)
        silence = _call_uint(heartbeat, SEL_SILENCE_REQUIRED)
        now = _chain_time()
        beater = _call_address(heartbeat, SEL_BEATER)
        balance = int(_rpc('eth_getBalance', [beater, 'latest']), 16) if beater else None
    except Exception as exc:  # noqa: BLE001 — the beat itself already succeeded
        logger.warning('Confío heartbeat daily report: chain read failed: %s', exc)
        return False
    min_balance = int(getattr(settings, 'CONFIO_HEARTBEAT_BEATER_MIN_BALANCE_WEI',
                              10_000_000_000_000_000))
    low = balance is None or balance < min_balance
    headline = ('⚠️ Latido diario de Confío: latido OK, pero al emisor le queda poco BNB. '
                'Recárgalo antes de que fallen los latidos.' if low
                else '💚 Latido diario de Confío: todo normal.')
    tx = result.get('beat')
    linea_tx = (f'Transacción: https://bscscan.com/tx/{tx}' if tx
                else f'Ya había un latido reciente (hace {(now - last) / 3600:.1f} h).')
    saldo = 'desconocido' if balance is None else f'{balance / 1e18:.4f} BNB'
    return send_ops_alert(
        f'{headline}\n'
        f'{linea_tx}\n'
        'Salida de emergencia: cerrada. Solo se abriría el '
        f'{_fecha_utc(last + silence)} si Confío dejara de publicar su latido.\n'
        f'Saldo del emisor del latido: {saldo}.',
        dedupe_key=f'heartbeat_daily:{now // 86400}', dedupe_seconds=36 * 3600)


def _chat_safe(exc) -> str:
    """Exception text for the team chat: URLs reduced to their host, since
    RPC errors embed full endpoint URLs and a paid endpoint's key lives in its
    path. Logs keep the full text."""
    text = re.sub(r'https?://([^/\s]+)\S*', r'\1', str(exc))
    # requests' connection errors print the path without a scheme:
    # "...port=443): Max retries exceeded with url: /v1/<KEY> (...)".
    text = re.sub(r'(url:)\s*/\S*', r'\1 <redacted>', text)
    return text[:400]


def _sel(sig: str) -> str:
    return '0x' + keccak(text=sig)[:4].hex()


SEL_BEAT = _sel('beat()')
SEL_LAST_BEAT = _sel('lastBeat()')
SEL_BEATER = _sel('beater()')
SEL_SILENCE_REQUIRED = _sel('silenceRequired()')
BEAT_TOPIC = '0x' + keccak(text='Beat(uint64)').hex()

RECEIPT_POLL_S = 3.0
# A failed beat retries every 10 minutes for about an hour; after that the
# next daily run and the hourly stale monitor take over.
BEAT_RETRY_COUNTDOWN_S = 600
BEAT_MAX_RETRIES = 6


class HeartbeatError(Exception):
    """The beat did not provably land. The message is for the logs."""


def heartbeat_address() -> str:
    return (getattr(settings, 'CONFIO_HEARTBEAT_ADDRESS', '') or '').strip().lower()


def _call(to: str, data: str) -> str:
    return _rpc('eth_call', [{'to': to, 'data': data}, 'latest'])


def _call_uint(to: str, data: str) -> int:
    res = _call(to, data)
    return int(res, 16) if res and res != '0x' else 0


def _call_address(to: str, data: str) -> str:
    res = _call(to, data) or ''
    word = res[2:] if res.startswith('0x') else res
    return ('0x' + word[-40:]).lower() if len(word) >= 40 else ''


def _chain_time() -> int:
    block = _rpc('eth_getBlockByNumber', ['latest', False])
    return int(block['timestamp'], 16)


def _beater_signer():
    """(signer, shares_sponsor_key).

    CONFIO_HEARTBEAT_KMS_KEY_ALIAS empty = the existing BSC sponsor KMS key
    (it then shares the sponsor's nonce lock with every other sponsor rail).
    A dedicated alias uses its own key and needs no lock: this task is its
    only sender."""
    from blockchain.evm_kms_signer import EVMKMSSigner, get_bsc_sponsor_signer_from_settings

    alias = (getattr(settings, 'CONFIO_HEARTBEAT_KMS_KEY_ALIAS', '') or '').strip()
    if not alias:
        return get_bsc_sponsor_signer_from_settings(), True
    region = getattr(settings, 'BSC_KMS_REGION', None) or 'eu-central-2'
    return EVMKMSSigner(alias, region_name=region), False


def system_health() -> str:
    """'' when the system is operating, else the failing component.

    Deliberately cheap: a beat says "Confío is operating", so it must not be
    sent by a worker whose database or chain access is gone."""
    try:
        close_old_connections()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 — any DB failure means unhealthy
        logger.error('Confío heartbeat health gate: database unreachable: %s', exc)
        return 'database'
    try:
        if int(_rpc('eth_blockNumber', []), 16) <= 0:
            return 'bsc_rpc'
    except Exception as exc:  # noqa: BLE001 — the whole RPC pool failed
        logger.error('Confío heartbeat health gate: BSC RPC pool unreachable: %s', exc)
        return 'bsc_rpc'
    return ''


def receipt_has_beat(receipt: dict, heartbeat: str) -> bool:
    """Success status AND a Beat(uint64) log emitted by the heartbeat."""
    if not receipt or receipt.get('status') != '0x1':
        return False
    for log in receipt.get('logs') or []:
        topics = log.get('topics') or []
        if ((log.get('address') or '').lower() == heartbeat
                and topics and (topics[0] or '').lower() == BEAT_TOPIC):
            return True
    return False


def _wait_for_receipt(tx_hash: str, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            receipt = _rpc('eth_getTransactionReceipt', [tx_hash])
        except Exception as exc:  # noqa: BLE001 — keep polling until the deadline
            logger.info('Confío heartbeat receipt poll failed for %s: %s', tx_hash, exc)
            receipt = None
        if receipt:
            return receipt
        if time.monotonic() + RECEIPT_POLL_S > deadline:
            return None
        time.sleep(RECEIPT_POLL_S)


def post_heartbeat() -> dict:
    """Send one beat and prove it landed. Raises HeartbeatError otherwise."""
    heartbeat = heartbeat_address()
    if not heartbeat:
        logger.info('Confío heartbeat: CONFIO_HEARTBEAT_ADDRESS unset — skipping')
        return {'skipped': 'unconfigured'}

    unhealthy = system_health()
    if unhealthy:
        raise HeartbeatError(f'health gate failed ({unhealthy}); no beat sent')

    try:
        last = _call_uint(heartbeat, SEL_LAST_BEAT)
        now = _chain_time()
    except Exception as exc:  # noqa: BLE001
        raise HeartbeatError(f'chain read failed: {exc}') from exc
    min_interval = int(getattr(settings, 'CONFIO_HEARTBEAT_MIN_INTERVAL_SECONDS', 6 * 3600))
    if last and now - last < min_interval:
        # A retry after a slow receipt, or a second scheduler: the chain
        # already has a fresh beat.
        logger.info('Confío heartbeat: last beat %ss ago — not beating again', now - last)
        return {'skipped': 'recent', 'last_beat': last}

    try:
        signer, shares_sponsor = _beater_signer()
        sender = signer.address
    except Exception as exc:  # noqa: BLE001
        raise HeartbeatError(f'beater signer unavailable: {exc}') from exc

    lock = None
    if shares_sponsor:
        from .sponsor_7702 import acquire_sponsor_nonce_lock
        lock = acquire_sponsor_nonce_lock()
        if not lock:
            raise HeartbeatError('sponsor nonce lock busy')
    try:
        on_chain_beater = _call_address(heartbeat, SEL_BEATER)
        if on_chain_beater != sender.lower():
            raise HeartbeatError(
                f'signer {sender} is not the contract beater {on_chain_beater or "?"} '
                '(the Safe must call setBeater)')
        gas_limit = int(getattr(settings, 'CONFIO_HEARTBEAT_GAS_LIMIT', 80_000))
        # Pre-flight under the real budget: an uninitialized proxy or a
        # reverting beat costs nothing here and real gas on chain.
        _rpc('eth_call', [{'from': sender, 'to': heartbeat, 'data': SEL_BEAT,
                           'gas': hex(gas_limit)}, 'latest'])
        nonce = int(_rpc('eth_getTransactionCount', [sender, 'pending']), 16)
        gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                        int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 50_000_000)))
        gas_price = (gas_price * 12) // 10
        balance = int(_rpc('eth_getBalance', [sender, 'latest']), 16)
        if balance < gas_limit * gas_price:
            raise HeartbeatError(f'beater {sender} BNB too low ({balance} wei) — refill needed')
        raw, tx_hash = signer.sign_transaction({
            'chainId': settings.BSC_CHAIN_ID, 'nonce': nonce, 'gasPrice': gas_price,
            'gas': gas_limit, 'to': heartbeat, 'value': 0, 'data': SEL_BEAT,
        })
        try:
            _rpc('eth_sendRawTransaction', [raw])
        except Exception as exc:  # noqa: BLE001
            # An endpoint may have accepted it before the failover reported
            # an error ("already known"); the receipt below decides.
            logger.warning('Confío heartbeat broadcast reported an error for %s: %s', tx_hash, exc)
    except HeartbeatError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HeartbeatError(f'beat send failed: {exc}') from exc
    finally:
        if lock:
            from .sponsor_7702 import release_sponsor_nonce_lock
            release_sponsor_nonce_lock(lock)

    timeout_s = float(getattr(settings, 'CONFIO_HEARTBEAT_RECEIPT_TIMEOUT_SECONDS', 90))
    receipt = _wait_for_receipt(tx_hash, timeout_s)
    if not receipt:
        raise HeartbeatError(f'no receipt for beat {tx_hash} within {timeout_s:.0f}s')
    if not receipt_has_beat(receipt, heartbeat):
        raise HeartbeatError(
            f'beat {tx_hash} mined without a Beat event (status={receipt.get("status")})')
    logger.info('Confío heartbeat beat confirmed on chain: %s (block %s)',
                tx_hash, receipt.get('blockNumber'))
    return {'beat': tx_hash, 'block': receipt.get('blockNumber')}


@shared_task(name='cusd_plus.post_confio_heartbeat', bind=True, max_retries=BEAT_MAX_RETRIES)
def post_confio_heartbeat(self):
    try:
        result = post_heartbeat()
    except HeartbeatError as exc:
        logger.error('Confío heartbeat beat FAILED (attempt %s/%s): %s — Emergency Exit '
                     'opens for every user if beats stay missing for silenceRequired',
                     self.request.retries + 1, BEAT_MAX_RETRIES + 1, exc)
        if self.request.retries >= BEAT_MAX_RETRIES:
            send_ops_alert(
                '🔴 Latido de Confío: el latido de hoy FALLÓ tras todos los reintentos.\n'
                f'Último error: {_chat_safe(exc)}\n'
                'Si faltan latidos durante 14 días, la Salida de emergencia se abre para '
                'TODOS los usuarios, incluidas las cuentas congeladas.',
                dedupe_key='heartbeat_beat_failed', dedupe_seconds=6 * 3600)
        raise self.retry(exc=exc, countdown=BEAT_RETRY_COUNTDOWN_S)
    if 'beat' in result or result.get('skipped') == 'recent':
        # The beat already succeeded; the report must never turn it into a
        # task failure.
        try:
            daily_report(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning('Confío heartbeat daily report failed: %s', exc)
    return result


def check_heartbeat() -> dict:
    heartbeat = heartbeat_address()
    if not heartbeat:
        return {'skipped': 'unconfigured'}

    try:
        last = _call_uint(heartbeat, SEL_LAST_BEAT)
        silence = _call_uint(heartbeat, SEL_SILENCE_REQUIRED)
        now = _chain_time()
        beater = _call_address(heartbeat, SEL_BEATER)
        balance = int(_rpc('eth_getBalance', [beater, 'latest']), 16) if beater else None
    except Exception as exc:  # noqa: BLE001 — a blind monitor is itself an alert
        logger.error('Confío heartbeat monitor: chain read failed: %s', exc)
        send_ops_alert(
            f'🟠 El monitor del latido de Confío no puede leer la blockchain: {_chat_safe(exc)}\n'
            'No puede confirmar si los latidos están llegando. Revisa los RPC de BSC.',
            dedupe_key='heartbeat_read_failed', dedupe_seconds=3 * 3600)
        return {'skipped': 'read_failed'}

    result = {'last_beat': last, 'chain_time': now, 'beater': beater,
              'beater_balance_wei': balance, 'stale': False, 'low_balance': False}

    stale_after = int(getattr(settings, 'CONFIO_HEARTBEAT_STALE_ALERT_SECONDS', 26 * 3600))
    age = now - last
    result['age_seconds'] = age
    if not last or not silence or age > stale_after:
        result['stale'] = True
        opens_in_h = ((last + silence) - now) / 3600 if last and silence else 0.0
        logger.critical(
            'Confío heartbeat STALE: no beat on chain for %.1fh (alert after %.1fh). '
            'Emergency Exit opens for EVERY user, frozen accounts included, in %.1fh '
            'unless beat() lands. Contract %s, beater %s.',
            age / 3600, stale_after / 3600, opens_in_h, heartbeat, beater or '?')
        # Hourly while stale (the monitor runs hourly; the dedupe only stops
        # two workers double-posting the same run).
        send_ops_alert(
            f'🚨 Latido de Confío ATRASADO: {age / 3600:.1f} h sin latido en la blockchain.\n'
            'La Salida de emergencia se abrirá para TODOS los usuarios (incluidas las cuentas '
            f'congeladas) en {opens_in_h:.1f} h si no llega un latido.\n'
            f'Contrato {heartbeat}\nEmisor {beater or "?"}',
            dedupe_key='heartbeat_stale', dedupe_seconds=50 * 60)
        try:
            cache.set(STALE_FLAG_KEY, 1, timeout=30 * 24 * 3600)
        except Exception:  # noqa: BLE001 — only affects the recovery message
            pass
    else:
        try:
            was_stale = cache.get(STALE_FLAG_KEY)
            if was_stale:
                cache.delete(STALE_FLAG_KEY)
        except Exception:  # noqa: BLE001
            was_stale = None
        if was_stale:
            send_ops_alert(f'✅ Latido de Confío recuperado: último latido hace {age / 3600:.1f} h.')

    min_balance = int(getattr(settings, 'CONFIO_HEARTBEAT_BEATER_MIN_BALANCE_WEI',
                              10_000_000_000_000_000))
    if balance is None or balance < min_balance:
        result['low_balance'] = True
        logger.error('Confío heartbeat beater %s low on BNB: %s BNB (alert under %s BNB) — '
                     'refill before beats start failing',
                     beater or '?', 'unknown' if balance is None else f'{balance / 1e18:.6f}',
                     f'{min_balance / 1e18:.6f}')
        send_ops_alert(
            f'🟠 Al emisor del latido {beater or "?"} le queda poco BNB: '
            f'{"desconocido" if balance is None else f"{balance / 1e18:.6f} BNB"} '
            f'(alerta bajo {min_balance / 1e18:.6f}). Recárgalo antes de que fallen los latidos.',
            dedupe_key='heartbeat_low_balance', dedupe_seconds=12 * 3600)

    if not result['stale'] and not result['low_balance']:
        logger.info('Confío heartbeat OK: last beat %.1fh ago, beater %.6f BNB',
                    age / 3600, balance / 1e18)
    return result


@shared_task(name='cusd_plus.check_confio_heartbeat')
def check_confio_heartbeat():
    return check_heartbeat()
