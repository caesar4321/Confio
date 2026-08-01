"""
Celery side of the cUSD+ conversion ledger — everything that needs NO keys
(ORCHESTRATION.md §2): watching OUR chains for bridge arrivals, BNB gas
dusting, abandoning stale quotes. The client (user keys) drives the legs.

MONITORING PRINCIPLE (Julian, 2026-07-04): the chain is the truth. Bridge
completion is observed directly on the destination chain — a USDT Transfer
to user.bsc on BNB (Ahorrar) or the USDC arrival at user.algo that the
existing blockchain-app inbound scanner already detects (Retirar). The
Allbridge indexer API is NOT in the hot path: a vendor outage must never
fake a STUCK state while the money already landed. It remains available
as a support diagnostic for genuinely stuck rows only.
"""
import logging
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

import requests
from celery import current_app, shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# RPC POOL, not a single URL (2026-07-31 incident): the public dataseed
# family stopped serving eth_getLogs entirely ('limit exceeded' on every
# range), which silently killed this scanner for weeks — cursor never set,
# zero deposit rows, zero notifications, while the beat retried twice a
# minute. No contracted provider exists, so resilience comes from breadth:
# every call rotates across public endpoints, preferring the last one that
# worked. Probed 2026-07-31: nodereal public (from the official BNB Chain
# docs) serves getLogs up to ~5k blocks; 1rpc serves it capped at 50-block
# ranges (the micro-chunk fallback); dataseed still fine for everything
# that is not getLogs.
_DEFAULT_RPC_POOL = (
    'https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3',
    'https://bsc-dataseed.bnbchain.org',
    'https://1rpc.io/bnb',
)
BSC_RPC_URLS = [
    u.strip() for u in getattr(
        settings, 'CUSD_PLUS_BSC_RPC_URLS', ','.join(_DEFAULT_RPC_POOL)
    ).split(',') if u.strip()
]
USDT_BSC = getattr(settings, 'CUSD_PLUS_USDT_BSC', '0x55d398326f99059fF775485246999027B3197955')
# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

# getLogs chunking: primary chunk fits every healthy endpoint; the micro
# chunk fits 1rpc's 50-block cap when the primaries are all down.
GETLOGS_CHUNK_BLOCKS = int(getattr(settings, 'CUSD_PLUS_BSC_GETLOGS_CHUNK', 2000))
GETLOGS_MICRO_CHUNK_BLOCKS = 50

# After this many consecutive fully-failed scans, log at ERROR (alerting
# picks ERROR up; WARNINGs every 30s proved invisible) and back off to
# attempting only every 10th beat so dead endpoints aren't hammered.
SCAN_FAILURE_ALERT_THRESHOLD = 10
_FAILURE_KEY = 'cusd_plus_bsc_scan_failures'


def _rpc_single(url, method, params, timeout=15):
    res = requests.post(
        url,
        json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
        timeout=timeout,
    )
    res.raise_for_status()
    body = res.json()
    if 'error' in body:
        raise RuntimeError(f"bsc rpc: {body['error']}")
    return body['result']


def _rpc(method, params, timeout=15):
    """Try the pool in preference order; remember the last URL that worked
    so steady state is one request, not a failover cascade."""
    from django.core.cache import cache

    preferred = cache.get('cusd_plus_bsc_rpc_preferred')
    ordered = list(BSC_RPC_URLS)
    if preferred in ordered:
        ordered.remove(preferred)
        ordered.insert(0, preferred)
    last_exc = None
    for url in ordered:
        try:
            result = _rpc_single(url, method, params, timeout)
            if url != preferred:
                cache.set('cusd_plus_bsc_rpc_preferred', url, 3600)
            return result
        except Exception as exc:  # noqa: BLE001 — try the next endpoint
            last_exc = exc
            logger.info('bsc rpc %s failed on %s: %s', method, url, exc)
    raise RuntimeError(f'all {len(ordered)} BSC RPC endpoints failed: {last_exc}')


def _get_logs_chunked(from_block: int, to_block: int, topics, address=USDT_BSC) -> list:
    """eth_getLogs over [from_block, to_block] in endpoint-friendly chunks.
    Each chunk rotates the pool; a chunk that fails everywhere is retried
    once more in 50-block micro-chunks (1rpc's cap). Raises only when a
    range is unservable by every endpoint at every granularity — the
    caller leaves the cursor untouched and rescans next beat."""
    logs: list = []
    b = from_block
    while b <= to_block:
        hi = min(b + GETLOGS_CHUNK_BLOCKS - 1, to_block)
        params = {'fromBlock': hex(b), 'toBlock': hex(hi),
                  'address': address, 'topics': topics}
        try:
            logs += _rpc('eth_getLogs', [params])
        except Exception:  # noqa: BLE001 — degrade to micro-chunks
            m = b
            while m <= hi:
                mhi = min(m + GETLOGS_MICRO_CHUNK_BLOCKS - 1, hi)
                params['fromBlock'], params['toBlock'] = hex(m), hex(mhi)
                logs += _rpc('eth_getLogs', [params])  # raises if truly dead
                m = mhi + 1
        b = hi + 1
    return logs


def _address_topic(address: str) -> str:
    return '0x' + address.lower().replace('0x', '').rjust(64, '0')


@shared_task(name='cusd_plus.monitor_bridge_arrivals')
def monitor_bridge_arrivals():
    """BSC USDT inbound scanner — the BNB sibling of blockchain.scan_inbound_deposits.

    ONE pipeline for every USDT arrival at a user address (the Algorand
    USDC scanner's shape), with attribution hooks — not separate routes:

      - Arrival matching an in-flight to_savings conversion (>= 90% of the
        quote) -> bridge arrival: advance the saga (leg B done), dust gas.
      - Any other arrival at a REGISTERED savings address (an Account with
        bsc_address set) -> a savings Conversion row born at DEST_ARRIVED
        (source='external_deposit', or 'ramp' when a pending Koywe order
        targets the address), gas-dusted, deposit notification. The client's
        foreground resume (savingsLegC) mints it exactly like a conversion:
        "send USDT (BEP-20) to your address, it becomes savings" — the
        crypto-native onramp, no USDC-ALG detour through the thin pool.
        Ramp rows skip the notification: order comms stay with koywe_sync.

    Guard rails:
      - Arrivals under $CUSD_PLUS_MIN_EXTERNAL_DEPOSIT_USD (default $1) are
        logged, never recorded — strangers can send dust to any address and
        must not be able to spam rows or notifications.
      - A below-floor arrival at an address with an in-flight conversion is
        logged only: minting it could consume USDT that a delayed bridge
        delivery still needs. Support resolves those by hand.

    Batched eth_getLogs per address chunk (topics accept an ADDRESS ARRAY,
    so cost grows with users/800, not users) over a global cursor with a
    rewind margin; idempotency comes from monotonic status transitions and
    the src_tx_id dedupe on deposit rows.
    STUCK is judged by chain silence only — never by a vendor API.
    """
    from django.core.cache import cache
    from conversion.models import Conversion

    timeout = timedelta(minutes=getattr(settings, 'CUSD_PLUS_BRIDGE_TIMEOUT_MIN', 30))
    conversions = list(Conversion.objects.filter(
        conversion_type='to_savings',
        status__in=('SRC_COMMITTED', 'STUCK'),
        is_deleted=False,
    ).exclude(user_bsc_address='')[:500])
    conv_watch = {c.user_bsc_address.lower(): c for c in conversions}

    registered = _registered_bsc_addresses()  # addr -> account_id

    ramp_addrs: set[str] = set()
    try:
        from ramps.models import RampTransaction
        ramp_addrs = {a.lower() for a in RampTransaction.objects.filter(
            destination='cusd_plus',
            direction='on_ramp',
            status__in=('PENDING', 'PROCESSING'),
        ).exclude(actor_address='').values_list('actor_address', flat=True)[:300]}
    except Exception:  # noqa: BLE001
        logger.exception('ramp watch-set union failed')

    watch_all = set(conv_watch) | set(registered) | ramp_addrs
    if not watch_all:
        return  # idle: zero RPC calls

    # Backoff: after SCAN_FAILURE_ALERT_THRESHOLD consecutive dead scans,
    # attempt only every 10th beat instead of hammering dead endpoints
    # twice a minute (which worsens per-IP rate limits).
    failures = int(cache.get(_FAILURE_KEY) or 0)
    if failures >= SCAN_FAILURE_ALERT_THRESHOLD and failures % 10 != 0:
        cache.set(_FAILURE_KEY, failures + 1, None)
        return

    def _scan_failed(stage, exc):
        n = failures + 1
        cache.set(_FAILURE_KEY, n, None)
        if n >= SCAN_FAILURE_ALERT_THRESHOLD:
            logger.error(
                'BSC deposit scanner DEAD for %s consecutive runs (%s: %s) — '
                'external USDT deposits are going undetected and unnotified',
                n, stage, exc,
            )
        else:
            logger.warning('bsc %s failed: %s', stage, exc)

    try:
        latest_block = int(_rpc('eth_blockNumber', []), 16)
    except Exception as exc:  # noqa: BLE001 — watcher must not die
        _scan_failed('blockNumber', exc)
        return

    rewind = int(getattr(settings, 'CUSD_PLUS_BSC_SCAN_REWIND_BLOCKS', 100))
    from_block = cache.get('cusd_plus_bsc_scan_cursor') or max(latest_block - 1200, 0)
    from_block = max(int(from_block) - rewind, 0)

    logs: list[dict] = []
    addrs = sorted(watch_all)
    for i in range(0, len(addrs), 800):
        try:
            logs += _get_logs_chunked(
                from_block, latest_block,
                [TRANSFER_TOPIC, None,
                 [_address_topic(a) for a in addrs[i:i + 800]]],
            )
        except Exception as exc:  # noqa: BLE001
            _scan_failed('getLogs', exc)
            return  # cursor untouched — next run rescans the window
    cache.set('cusd_plus_bsc_scan_cursor', latest_block, None)
    if failures:
        logger.info('BSC deposit scanner recovered after %s failed runs', failures)
    cache.set(_FAILURE_KEY, 0, None)

    now = timezone.now()
    min_deposit = Decimal(str(getattr(settings, 'CUSD_PLUS_MIN_EXTERNAL_DEPOSIT_USD', 1)))
    arrived: dict[str, dict] = {}
    for log in logs:
        key = ('0x' + log['topics'][2][-40:]).lower()
        raw_units = int(log['data'], 16)
        conv = conv_watch.get(key)
        if conv is not None:
            floor_units = int(float(conv.to_amount) * 0.9 * 1e18)
            if raw_units >= floor_units:
                arrived[key] = log
            else:
                logger.info(
                    'below-floor USDT arrival at conversion address %s (%s) — left for support',
                    key, log['transactionHash'],
                )
            continue
        account_id = registered.get(key)
        if account_id is None:
            logger.info(
                'USDT arrival at unregistered watched address %s (%s)',
                key, log['transactionHash'],
            )
            continue
        amount_usd = (Decimal(raw_units) / Decimal(10 ** 18)).quantize(
            Decimal('0.000001'), rounding=ROUND_DOWN)
        if amount_usd < min_deposit:
            logger.info(
                'dust USDT arrival at %s (%s USDT, %s) — below deposit minimum',
                key, amount_usd, log['transactionHash'],
            )
            continue
        _record_inbound_deposit(
            account_id=account_id,
            to_addr=key,
            amount_usd=amount_usd,
            tx_ref=f"{log['transactionHash']}:{int(log.get('logIndex', '0x0'), 16)}",
            tx_hash=log['transactionHash'],
            source='ramp' if key in ramp_addrs else 'external_deposit',
            now=now,
            from_addr='0x' + log['topics'][1][-40:],
        )

    for addr, conv in conv_watch.items():
        log = arrived.get(addr)
        if log:
            conv.status = 'DEST_ARRIVED'
            conv.dest_arrived_at = now
            conv.bridge_arrival_tx = log['transactionHash']
            conv.save(update_fields=[
                'status', 'dest_arrived_at', 'bridge_arrival_tx', 'updated_at',
            ])
            from .unified import sync_unified_from_cusd_plus_conversion
            sync_unified_from_cusd_plus_conversion(conv)
            logger.info(
                'conversion %s: USDT arrived on BNB (%s)',
                conv.internal_id, log['transactionHash'],
            )
            # TODO(cusd+): websocket event + push nudge if the app is closed.
        elif (
            conv.status == 'SRC_COMMITTED'
            and conv.src_committed_at
            and now - conv.src_committed_at > timeout
        ):
            conv.status = 'STUCK'
            conv.save(update_fields=['status', 'updated_at'])
            logger.error(
                'conversion %s STUCK: no USDT arrival on BNB after %s (src tx %s). '
                'Support diagnostic: allbridge_diagnose("%s")',
                conv.internal_id, timeout, conv.from_transaction_hash, conv.internal_id,
            )

    # ── cUSD+ (vault share) inbound pass (Phase 2) ──────────────────────
    # External cUSD+ receives (another wallet sends shares directly) get a
    # ledger row + push. Internal sends are EXCLUDED here — the send
    # confirm task records both sides — by skipping logs whose sender is
    # also a registered address. Mints (from = 0x0) never match a
    # registered `from`, and redeems burn (to = 0x0) so they never match a
    # registered `to`. Failures here must never disturb the USDT pipeline.
    try:
        _scan_cusd_plus_arrivals(registered, from_block, latest_block, min_deposit)
    except Exception:  # noqa: BLE001
        logger.exception('cUSD+ inbound scan failed (USDT pipeline unaffected)')


def _scan_cusd_plus_arrivals(registered: dict, from_block: int, latest_block: int,
                             min_deposit) -> None:
    from decimal import ROUND_DOWN as _RD

    from . import vault as cp_vault

    vault_addr = (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()
    if not vault_addr or not registered:
        return

    logs: list[dict] = []
    addrs = sorted(registered)
    for i in range(0, len(addrs), 800):
        logs += _get_logs_chunked(
            from_block, latest_block,
            [TRANSFER_TOPIC, None,
             [_address_topic(a) for a in addrs[i:i + 800]]],
            address=vault_addr,
        )
    if not logs:
        return

    pps_wad = cp_vault.p_plus_wad()
    for log in logs:
        sender = ('0x' + log['topics'][1][-40:]).lower()
        if sender in registered:
            continue  # internal send — recorded by the send confirm task
        key = ('0x' + log['topics'][2][-40:]).lower()
        account_id = registered.get(key)
        if account_id is None:
            continue
        shares = int(log['data'], 16)
        amount_usd = (Decimal(shares) * Decimal(pps_wad) / Decimal(10 ** 36)).quantize(
            Decimal('0.000001'), rounding=_RD)
        if amount_usd < min_deposit:
            continue  # dust — strangers must not spam rows/notifications
        # Externally-originated cUSD+ arriving at a registered address is a
        # RECEIVE with an external sender — that is exactly what a
        # SendTransaction models, and writing one gives this deposit the same
        # unified row, detail screen and comprobante every other receipt has.
        # Idempotency key carries the log identity so a rescan can't double it.
        from send.models import SendTransaction
        from users.models import Account
        reference = f"scan_cusdp:{log['transactionHash']}:{int(log.get('logIndex', '0x0'), 16)}"
        account = Account.objects.filter(id=account_id).select_related(
            'user', 'business').first()
        if account is None:
            continue
        _, created = SendTransaction.objects.get_or_create(
            idempotency_key=reference,
            defaults={
                'recipient_user': account.user,
                'recipient_business': account.business,
                'recipient_type': 'business' if account.business_id else 'user',
                'recipient_display_name': (
                    account.business.name if account.business_id
                    else (account.user.get_full_name() or account.user.username or '')
                ),
                'recipient_address': key,
                # No Confío row on the sending side: the money came from
                # outside, so the sender is the raw address and nothing else.
                'sender_type': 'external',
                'sender_display_name': '',
                'sender_address': sender,
                'amount': amount_usd,
                'token_type': 'CUSD_PLUS',
                'status': 'CONFIRMED',
                'transaction_hash': log['transactionHash'],
                'memo': '',
            },
        )
        if not created:
            continue  # rescan window replay
        cp_vault.invalidate_position(key)
        try:
            from users.models import Account
            from notifications import utils as notif_utils
            from notifications.models import NotificationType as NotifType
            account = Account.objects.filter(id=account_id).select_related(
                'user', 'business').first()
            if account and account.user_id:
                notif_utils.create_notification(
                    user=account.user,
                    account=account,
                    business=account.business if account.account_type == 'business' else None,
                    notification_type=NotifType.SEND_RECEIVED,
                    title='Depósito recibido',
                    message=f'Recibiste ${amount_usd:.2f} en tu Confío Dollar+.',
                    data={
                        'transaction_type': 'deposit',
                        'currency': 'CUSD_PLUS',
                        'network': 'BSC',
                        'amount': str(amount_usd),
                        'tx_hash': log['transactionHash'],
                    },
                )
        except Exception:  # noqa: BLE001 — comms failure must not lose the row
            logger.exception('cUSD+ receive notification failed for %s', reference)


def _registered_bsc_addresses() -> dict:
    """addr(lower) -> account_id for every savings-activated account.
    Having a bsc_address IS the registration — the address only exists once
    the user activates the savings rail. Cached briefly: the scanner runs
    every minute, the set changes rarely."""
    from django.core.cache import cache
    from users.models import Account

    cached = cache.get('cusd_plus_bsc_registered_v1')
    if cached is not None:
        return cached
    addr_map = {
        row['bsc_address'].lower(): row['id']
        for row in Account.objects.filter(deleted_at__isnull=True)
        .exclude(bsc_address__isnull=True).exclude(bsc_address='')
        .values('id', 'bsc_address')
    }
    cache.set('cusd_plus_bsc_registered_v1', addr_map, 600)
    return addr_map


def _record_inbound_deposit(account_id, to_addr, amount_usd, tx_ref, tx_hash, source, now,
                            from_addr=''):
    """A chain-observed USDT inflow becomes a RECEIPT — nothing more.

    The arrival is USDT at the user's own address. Whether it may become
    cUSD+ is the mint gate's call, and that needs a request context this
    task does not have, so no conversion row is opened here (see below).
    amount_usd is the EXACT floored arrival.

    Two dedupes, because the two records have different keys:
      - the Conversion check below stops a BRIDGE delivery, re-seen after its
        saga row advanced out of the watch set, from being reborn as a
        deposit; those rows carry bridge_arrival_tx.
      - rescans of a plain deposit are deduped by the receipt itself, in
        _record_deposit_receipt — a cursor rewind makes rescans routine.

    (Known trade-off: SendTransaction.transaction_hash is UNIQUE, so a single
    tx carrying transfers to several registered addresses records only the
    first — wallet sends are one transfer per tx, and the rest stays visible
    on chain for support.)"""
    from users.models import Account
    from conversion.models import Conversion

    if Conversion.objects.filter(
        user_bsc_address=to_addr, bridge_arrival_tx=tx_hash, is_deleted=False,
    ).exists():
        return
    account = Account.objects.filter(id=account_id).select_related('user', 'business').first()
    if account is None:
        return
    is_business = account.account_type == 'business'
    # NO conversion row. A chain-observed arrival is just USDT at the user's
    # own address; whether it may become cUSD+ depends on the MINT gate, which
    # needs a request (phone country AND Cloudflare IP country) that this
    # Celery task will never have. Creating the row here meant guessing with
    # half the inputs: a phone-eligible holder connecting from a blocked
    # country got a DEST_ARRIVED row the relay then refused on every retry,
    # stranding it at "pendiente" forever — the same bug as the phone-
    # ineligible case, one gate down.
    #
    # The row is now written by the relay AFTER a mint it actually allowed
    # (record_savings_mint below), so a conversion row means "this happened",
    # never "this is promised". The bridge saga is unaffected: those rows are
    # born at CREATED by prepare_leg_ab and only ADVANCE through here.
    _record_deposit_receipt(
        account=account, is_business=is_business, to_addr=to_addr,
        from_addr=from_addr, amount_usd=amount_usd, tx_ref=tx_ref,
        tx_hash=tx_hash, source=source, conv=None,
    )


def record_savings_mint(*, user, business, actor_type, display_name,
                        amount_wei, tx_hash, bsc_address):
    """History row for a mint the relay ALLOWED and broadcast.

    Written after the geo gate passed and the transaction went out, so the row
    records a completed fact. amount_wei is decoded from the validated
    calldata, never taken from the client.
    """
    from decimal import Decimal, ROUND_DOWN
    from conversion.models import Conversion

    try:
        if Conversion.objects.filter(
            conversion_type='to_savings', to_transaction_hash=tx_hash,
            is_deleted=False,
        ).exists():
            return None
        # A bridge saga already OWNS this mint: its row was born at CREATED by
        # prepare_leg_ab and is waiting at DEST_ARRIVED for exactly this leg,
        # which the client then advances. Recording here too would give every
        # bridge completion two conversions and two feed entries — the hash
        # check above cannot catch it because the client writes that hash
        # AFTER we run (audit 2026-08-01).
        if Conversion.objects.filter(
            conversion_type='to_savings',
            user_bsc_address__iexact=bsc_address or '',
            status__in=Conversion.IN_FLIGHT_STATUSES,
            is_deleted=False,
        ).exists():
            logger.info('savings mint %s belongs to an in-flight saga — not recording', tx_hash)
            return None
        amount = (Decimal(int(amount_wei)) / Decimal(10 ** 18)).quantize(
            Decimal('0.000001'), rounding=ROUND_DOWN)
        conv = Conversion.objects.create(
            actor_user=user if actor_type != 'business' else None,
            actor_business=business if actor_type == 'business' else None,
            actor_type=actor_type,
            actor_display_name=display_name or '',
            conversion_type='to_savings',
            source='external_deposit',
            from_amount=amount,
            to_amount=amount,
            quoted_cost_pct=0,
            user_bsc_address=bsc_address or '',
            to_transaction_hash=tx_hash or '',
            # SUBMITTED, not COMPLETED. Broadcast is not execution: the batch
            # receipt task can still classify this hash reverted / noop_failed
            # / reorged / dropped. Writing COMPLETED here also fired the
            # referral signal (a completed to_savings >= $19 pays a reward), so
            # a transaction that later failed could have paid one.
            # settle_savings_mint below promotes it once the receipt is final.
            status='SUBMITTED',
        )
        logger.info('savings mint recorded %s: %s USDT (%s)',
                    conv.internal_id, amount, tx_hash)
        return conv
    except Exception:  # noqa: BLE001 — history must not fail the relay
        logger.exception('savings mint history write failed for %s', tx_hash)
        return None



def _record_deposit_receipt(*, account, is_business, to_addr, from_addr,
                            amount_usd, tx_ref, tx_hash, source, conv):
    """The raw USDT receipt + deposit notification for an observed inflow.

    Shared by both deposit paths. `conv` is the conversion row when one was
    created, None when the holder is geo-ineligible and the USDT simply stays
    raw — in which case the RECEIPT is what makes the path idempotent, since
    the caller's conversion-row dedupe cannot fire on a cursor rewind.
    """
    from send.models import SendTransaction

    receipt = None
    receipt_existed = False
    if source != 'ramp':
        try:
            # idempotency_key is capped at 64 chars; 'BSC:' + full 0x-hash +
            # logIndex overflows it. 56 hex chars (224 bits) of the hash keep
            # collision-impossibility while fitting: 4 + 56 + 1 + idx <= 64.
            _h, _, _idx = tx_ref.partition(':')
            idempotency_key = f'BSC:{_h[2:58]}:{_idx or 0}'
            # transaction_hash is UNIQUE. An INTERNAL send already owns the row
            # for this hash — and already notified its recipient — so mirroring
            # it raised IntegrityError on every user-to-user transfer, logged at
            # ERROR. Matching the HASH as well as our own key both silences that
            # and gives the ineligible path (which has no conversion row) a
            # dedupe that actually holds across cursor rewinds.
            from django.db.models import Q
            receipt_existed = SendTransaction.all_objects.filter(
                Q(idempotency_key=idempotency_key) | Q(transaction_hash=tx_hash)
            ).exists()
            if not receipt_existed:
                receipt = SendTransaction.all_objects.create(
                    sender_user=None,
                    recipient_user=None if is_business else account.user,
                    sender_business=None,
                    recipient_business=account.business if is_business else None,
                    sender_type='external',
                    recipient_type='business' if is_business else 'user',
                    sender_display_name='Depósito externo',
                    recipient_display_name=account.display_name,
                    sender_phone='',
                    recipient_phone=(getattr(account.user, 'phone_number', '') or '')
                                    if not is_business else '',
                    sender_address=from_addr or '',
                    recipient_address=to_addr,
                    amount=str(amount_usd),
                    token_type='USDT',
                    memo='Depósito USDT recibido',
                    status='CONFIRMED',
                    transaction_hash=tx_hash,
                    idempotency_key=idempotency_key,
                    error_message='',
                )
        except Exception:  # noqa: BLE001 — receipt mirror must not lose the deposit
            logger.exception('send receipt mirror failed for %s', tx_ref)

    if source == 'ramp':
        return  # order comms belong to the ramp flow (koywe_sync)
    if conv is None:
        # No conversion row: the RECEIPT is both the record and the dedupe
        # marker. Notify only when one durably exists — if the write failed we
        # must stay silent so the next scan can retry, instead of re-notifying
        # every rewind while the deposit is missing from history entirely
        # (audit 2026-08-01).
        if receipt_existed:
            return  # already recorded on an earlier pass
        if receipt is None:
            logger.error(
                'inbound USDT deposit at %s (%s) has NO durable record — '
                'receipt write failed and there is no conversion row; '
                'suppressing the notification so a rescan can retry',
                to_addr, tx_hash)
            return
    try:
        from notifications import utils as notif_utils
        from notifications.models import NotificationType as NotifType
        # Copy branches on eligibility: an ineligible user's deposit stays raw
        # USDT ("Confío Dollar" in the app) — promising "se sumará a tu
        # ahorro" would be a lie, since the mint gate will refuse it. Product
        # name only; USDT stays in the data payload, never in the message.
        # Phone country only — this task has no request, so no IP. That is
        # exactly why it no longer opens a conversion row; for the COPY it is
        # still the best signal available and right for the large majority. A
        # phone-eligible holder behind a blocked IP gets a slightly optimistic
        # message rather than a stuck row, which is the milder failure.
        from .eligibility import is_ondo_eligible
        eligible = (not is_business) and is_ondo_eligible(account.user)
        if eligible:
            message = f'Recibiste ${amount_usd:.2f} (USDT). Se sumará automáticamente a tu ahorro.'
        else:
            message = f'Recibiste ${amount_usd:.2f}. Ya está disponible en tu Confío Dollar.'
        notif_utils.create_notification(
            user=account.user,
            account=account,
            business=account.business if is_business else None,
            notification_type=NotifType.SEND_FROM_EXTERNAL,
            title='Depósito recibido',
            message=message,
            data={
                'transaction_type': 'deposit',
                'currency': 'USDT',
                'network': 'BSC',
                'amount': str(amount_usd),
                'tx_hash': tx_hash,
                # No conversion for an ineligible holder: the notification
                # opens the USDT receipt instead, so tapping it lands on the
                # movement that actually exists.
                'conversion_id': str(conv.internal_id) if conv else '',
                'pending_auto_mint': eligible,
            },
            **(
                {'related_object_type': 'Conversion',
                 'related_object_id': str(conv.internal_id)}
                if conv else
                {'related_object_type': 'SendTransaction',
                 'related_object_id': str(receipt.internal_id)} if receipt else {}
            ),
        )
    except Exception:  # noqa: BLE001 — comms failure must not lose the deposit
        logger.exception('deposit notification failed for %s', tx_ref)


def settle_savings_mint(tx_hash: str, outcome: str) -> None:
    """Promote or fail the mint row once its receipt is final.

    record_savings_mint writes SUBMITTED at broadcast; only here does a row
    become COMPLETED, which is also what releases the referral signal. Called
    from the batch receipt task for every terminal batch status.
    """
    from conversion.models import Conversion
    from django.utils import timezone as _tz

    if not tx_hash:
        return
    try:
        row = Conversion.objects.filter(
            conversion_type='to_savings', to_transaction_hash=tx_hash,
            status='SUBMITTED', is_deleted=False,
        ).first()
        if row is None:
            return
        if outcome == 'confirmed':
            row.status = 'COMPLETED'
            row.completed_at = _tz.now()
            row.save(update_fields=['status', 'completed_at', 'updated_at'])
        else:
            row.status = 'FAILED'
            row.error_message = f'batch_{outcome}'
            row.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.info('savings mint %s settled %s -> %s', tx_hash, outcome, row.status)
    except Exception:  # noqa: BLE001 — settlement must not break the receipt task
        logger.exception('savings mint settlement failed for %s', tx_hash)


def mark_retirar_arrival(algo_address: str, txid: str) -> bool:
    """Hook for the existing inbound USDC scanner (blockchain app): when a
    USDC credit lands at an address with a from_savings conversion in
    flight, record the arrival. Returns True if a row advanced."""
    from conversion.models import Conversion

    conv = Conversion.objects.filter(
        conversion_type='from_savings',
        status__in=('SRC_COMMITTED', 'STUCK'),
        actor_address=algo_address,
        is_deleted=False,
    ).first()
    if conv is None:
        return False
    conv.status = 'DEST_ARRIVED'
    conv.dest_arrived_at = timezone.now()
    conv.bridge_arrival_tx = txid
    conv.save(update_fields=['status', 'dest_arrived_at', 'bridge_arrival_tx', 'updated_at'])
    logger.info('conversion %s: USDC arrived on Algorand (%s)', conv.internal_id, txid)
    return True


def allbridge_diagnose(conversion_internal_id: str) -> dict:
    """SUPPORT TOOL ONLY (not scheduled, not in the hot path): ask the
    Allbridge indexer what it thinks about a stuck transfer. The chain
    remains the source of truth."""
    from conversion.models import Conversion

    conv = Conversion.objects.get(internal_id=conversion_internal_id)
    chain = 'ALG' if conv.conversion_type == 'to_savings' else 'BSC'
    res = requests.get(
        f'https://core.api.allbridgecoreapi.net/chain/{chain}/{conv.from_transaction_hash}',
        timeout=15,
    )
    return {'status_code': res.status_code, 'body': res.json() if res.ok else res.text}


def _bnb_gas_reserve_wei() -> int:
    """BNB the auto-convert leaves at a user address for a SELF-SIGNED leg
    when 7702 sponsorship is off (legacy fallback; the user funds their own
    gas — Confío never sends BNB to user addresses. The dust rail was
    removed 2026-07-30: every savings/transfer leg rides sponsored batches).

    Gas-price aware with a spike buffer so a rising market still clears the
    action; capped so a gas spike can't demand an absurd reserve.
    """
    action_gas = int(getattr(settings, 'CUSD_PLUS_GAS_ACTION_BUDGET', 700_000))  # ~645k measured + margin
    spike_mult = int(getattr(settings, 'CUSD_PLUS_GAS_RESERVE_SPIKE_MULT', 3))
    try:
        gas_price = int(_rpc('eth_gasPrice', []), 16)
    except Exception:  # noqa: BLE001
        gas_price = 1_000_000_000  # 1 gwei fallback
    gas_price = max(gas_price, int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))  # ≥0.1 gwei
    target = action_gas * gas_price * spike_mult
    cap = int(getattr(settings, 'CUSD_PLUS_GAS_RESERVE_MAX_WEI', 5_000_000_000_000_000))  # 0.005 BNB hard cap
    return min(target, cap)


from eth_utils import keccak as _keccak
# BatchExecuted(uint256 nonce, uint256 numCalls) — the proof a 7702
# execute() actually ran (emitted by the user EOA running the delegate).
_BATCH_EXECUTED_TOPIC = '0x' + _keccak(text='BatchExecuted(uint256,uint256)').hex()


def _finality_depth() -> int:
    return int(getattr(settings, 'CUSD_PLUS_FINALITY_DEPTH', 15))


@shared_task(name='cusd_plus.check_sponsored_batch_receipt', bind=True, max_retries=40)
def check_sponsored_batch_receipt(self, batch_id: int):
    """Resolve a SponsoredBatch to a FINAL outcome (audit 2026-07-31 P1-3).

    Three failure modes this guards, that "status==1 + has logs" did not:
      1. the 7702 silent no-op — a stale authorization nonce leaves a
         codeless EOA, the tx mines status 0x1 executing NOTHING. A real
         execute() emits BatchExecuted(nonce); its ABSENCE (or a wrong
         nonce, e.g. a different delegate mined) => noop_failed.
      2. no finality — settling on the first receipt lets a reorg orphan a
         'confirmed' money row. We wait CUSD_PLUS_FINALITY_DEPTH blocks and
         re-check the block is canonical before AND the receipt still
         resolves.
      3. non-durable broadcast — a 'signed' row (broadcast may have failed)
         is resolved the same way: if it never mined, reconciliation will
         re-broadcast; here we just read the chain by the deterministic hash.
    """
    from blockchain.models import SponsoredBatch

    try:
        batch = SponsoredBatch.objects.get(id=batch_id)
    except SponsoredBatch.DoesNotExist:
        return
    if batch.status not in ('sent', 'signed'):
        return  # already resolved

    try:
        receipt = _rpc('eth_getTransactionReceipt', [batch.tx_hash])
    except Exception as exc:  # noqa: BLE001
        logger.warning('7702 receipt check failed for %s: %s', batch.tx_hash, exc)
        receipt = None
    if not receipt:
        # Not mined yet (or broadcast never landed) — back off and retry,
        # then leave for the reconciler. Never guess an outcome.
        raise self.retry(countdown=15)

    if receipt.get('status') != '0x1':
        batch.status = 'reverted'
        settle_savings_mint(batch.tx_hash, 'reverted')
        batch.save(update_fields=['status', 'updated_at'])
        logger.info('7702 batch %s reverted', batch.tx_hash)
        return

    logs = receipt.get('logs') or []
    is_7702 = batch.delegate_nonce is not None
    if is_7702:
        # Require the EXACT BatchExecuted(nonce) from the user EOA. Absent /
        # wrong nonce => the batch did not execute (no-op or a different
        # delegate ran first).
        want_nonce = '0x' + format(int(batch.delegate_nonce), 'x').rjust(64, '0')
        executed = any(
            (lg.get('address') or '').lower() == batch.user_bsc_address.lower()
            and (lg.get('topics') or [None])[0] == _BATCH_EXECUTED_TOPIC
            and len(lg.get('topics') or []) >= 2
            and lg['topics'][1].lower() == want_nonce
            for lg in logs
        )
        if not executed:
            batch.status = 'noop_failed'
            settle_savings_mint(batch.tx_hash, 'noop_failed')
            batch.save(update_fields=['status', 'updated_at'])
            logger.warning('7702 batch %s mined but did NOT execute (no BatchExecuted[nonce=%s]) for %s',
                           batch.tx_hash, batch.delegate_nonce, batch.user_bsc_address)
            return
    else:
        # Plain KMS contract call (payroll payout / reward / invite claim):
        # the contract reverts on failure, so status 0x1 with any log means
        # it executed. A zero-log success would be anomalous.
        if not logs:
            batch.status = 'noop_failed'
            batch.save(update_fields=['status', 'updated_at'])
            logger.warning('plain batch %s mined with no logs', batch.tx_hash)
            return

    # Finality: wait N confirmations, then verify the block is canonical.
    try:
        blk_num = int(receipt.get('blockNumber'), 16)
        blk_hash = (receipt.get('blockHash') or '').lower()
        head = int(_rpc('eth_blockNumber', []), 16)
    except Exception as exc:  # noqa: BLE001
        logger.warning('7702 finality read failed for %s: %s', batch.tx_hash, exc)
        raise self.retry(countdown=15)
    if head - blk_num < _finality_depth():
        raise self.retry(countdown=15)
    # The block that held the receipt must still be canonical at this height.
    canonical = _rpc('eth_getBlockByNumber', [hex(blk_num), False])
    if not canonical or (canonical.get('hash') or '').lower() != blk_hash:
        # The tx was reorged out of that block. Re-check by hash: if it has
        # no receipt now, it's orphaned; otherwise re-run to settle the new
        # block.
        recheck = None
        try:
            recheck = _rpc('eth_getTransactionReceipt', [batch.tx_hash])
        except Exception:  # noqa: BLE001
            pass
        if not recheck:
            batch.status = 'reorged'
            settle_savings_mint(batch.tx_hash, 'reorged')
            batch.save(update_fields=['status', 'updated_at'])
            logger.warning('7702 batch %s reorged out (block %s no longer canonical)',
                           batch.tx_hash, blk_num)
            return
        raise self.retry(countdown=15)

    batch.block_number = blk_num
    batch.block_hash = blk_hash
    batch.status = 'confirmed'
    batch.save(update_fields=['status', 'block_number', 'block_hash', 'updated_at'])
    settle_savings_mint(batch.tx_hash, 'confirmed')
    logger.info('7702 batch %s CONFIRMED final at block %s', batch.tx_hash, blk_num)


# Kinds that own a SEPARATE domain confirm task keyed (source_id, batch_id).
# Everything else (subscribe/redeem/payroll_fund/invite_*) settles via the
# batch-level receipt task alone, so promoting the batch is enough.
_DOMAIN_CONFIRM_TASKS = {
    'send_cusd_plus': 'send.confirm_bsc_send',
    'send_redeem': 'send.confirm_bsc_send',
    'send_usdt': 'send.confirm_bsc_send',
    'send_confio': 'send.confirm_bsc_send',
    'pay_cusd_plus': 'payments.confirm_bsc_payment',
    'pay_usdt': 'payments.confirm_bsc_payment',
    'pay_confio': 'payments.confirm_bsc_payment',
    'payroll_payout': 'payroll.confirm_bsc_payroll_payout',
    'presale_buy': 'presale.confirm_bsc_purchase',
    'invite_reclaim': 'send.confirm_bsc_invite_reclaim',
}


@shared_task(name='cusd_plus.reconcile_signed_batches')
def reconcile_signed_batches():
    """Resolve orphaned 'signed' SponsoredBatch rows (audit 2026-07-31 P1-2
    completion). A row stays 'signed' only if the process died between the
    durable pre-broadcast write and the 'sent' update — so its domain confirm
    task may never have been enqueued. After a grace window we read the chain
    by the deterministic hash:

      • any node knows the hash (mempool or mined) → the broadcast DID land;
        promote to 'sent', re-enqueue the batch receipt check AND the domain
        confirm task (which the crash may have skipped), and let the normal
        finality path settle it.
      • no node knows it after the grace window → it never broadcast and the
        KMS-signed raw is not reproducible; mark 'dropped' so the domain flow
        fails and the user retries. A retry is safe: the 7702 delegate's
        monotonic nonce rejects a replay of the same intent, and pay() is
        additionally guarded by the global invoiceDone.
    """
    from datetime import timedelta

    from django.utils import timezone

    from blockchain.models import SponsoredBatch

    grace_min = int(getattr(settings, 'CUSD_PLUS_SIGNED_GRACE_MIN', 3))
    cutoff = timezone.now() - timedelta(minutes=grace_min)
    stuck = list(SponsoredBatch.objects.filter(
        status='signed', updated_at__lt=cutoff).order_by('id')[:100])

    out = {'promoted': 0, 'dropped': 0}
    for batch in stuck:
        try:
            tx = _rpc('eth_getTransactionByHash', [batch.tx_hash])
        except Exception as exc:  # noqa: BLE001 — never guess; try next tick
            logger.warning('reconcile: getTransactionByHash failed for %s: %s',
                           batch.tx_hash, exc)
            continue

        if tx is not None:
            batch.status = 'sent'
            batch.save(update_fields=['status', 'updated_at'])
            check_sponsored_batch_receipt.apply_async(args=[batch.id], countdown=3)
            task_name = _DOMAIN_CONFIRM_TASKS.get(batch.kind)
            if task_name and batch.source_id is not None:
                # Re-enqueue the domain confirm the crash may have skipped —
                # the confirm tasks are idempotent (they no-op once the domain
                # row is resolved and verify kind/source_id/tx_hash first).
                current_app.send_task(task_name, args=[batch.source_id, batch.id],
                                      countdown=10)
            logger.info('reconcile: promoted orphaned batch %s (%s) to sent',
                        batch.id, batch.tx_hash)
            out['promoted'] += 1
        else:
            batch.status = 'dropped'
            settle_savings_mint(batch.tx_hash, 'dropped')
            batch.save(update_fields=['status', 'updated_at'])
            task_name = _DOMAIN_CONFIRM_TASKS.get(batch.kind)
            if task_name and batch.source_id is not None:
                # Let the domain flow observe the terminal 'dropped' and fail
                # its row so the user can retry.
                current_app.send_task(task_name, args=[batch.source_id, batch.id],
                                      countdown=10)
            logger.warning('reconcile: batch %s (%s) never reached the chain — dropped',
                           batch.id, batch.tx_hash)
            out['dropped'] += 1
    return out


@shared_task(name='cusd_plus.abandon_stale_quotes')
def abandon_stale_quotes():
    """CREATED rows the user never signed expire after a day — keeps the
    resume list honest."""
    from conversion.models import Conversion

    cutoff = timezone.now() - timedelta(hours=24)
    # Scoped to the savings sagas: 'CREATED' is a saga-only status, but an
    # explicit filter keeps a future Algorand status rename from sweeping
    # rows this task was never meant to touch.
    stale = Conversion.objects.filter(
        conversion_type__in=Conversion.SAVINGS_TYPES,
        status='CREATED', created_at__lt=cutoff, is_deleted=False,
    )
    updated = stale.update(status='ABANDONED', updated_at=timezone.now())
    if updated:
        logger.info('abandoned %d stale cusd+ conversion quotes', updated)


def _card_safe_logo(png_bytes: bytes) -> bytes:
    """FMP serves SOME logos as white glyphs on transparency (dark-UI
    variants) — invisible silhouettes on Confío's white cards (53 of the
    first 420, incl. AMZN/NKE/V/MELI). Detect them (transparent canvas +
    mostly-light opaque pixels) and bake a dark slate rounded chip behind
    the glyph — the locked v2 look (per-ticker colored chips were rejected:
    they read as wrong-brand). Everything else passes through untouched."""
    import io

    from PIL import Image, ImageDraw

    im = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    px = im.getdata()
    opaque = [(r, g, b) for r, g, b, a in px if a > 128]
    opaque_ratio = len(opaque) / len(px) if len(px) else 0
    light_ratio = (
        sum(1 for r, g, b in opaque if 0.299 * r + 0.587 * g + 0.114 * b > 210)
        / len(opaque) if opaque else 0
    )
    if not (opaque_ratio < 0.95 and light_ratio > 0.45):
        return png_bytes

    side = max(im.size)
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).rounded_rectangle(
        [0, 0, side - 1, side - 1], radius=int(side * 0.22), fill=(17, 24, 39, 255),
    )
    glyph = im.copy()
    glyph.thumbnail((int(side * 0.76), int(side * 0.76)), Image.LANCZOS)
    canvas.alpha_composite(glyph, ((side - glyph.width) // 2, (side - glyph.height) // 2))
    out = io.BytesIO()
    canvas.save(out, format='PNG')
    return out.getvalue()


@shared_task(name='cusd_plus.mirror_gm_logos')
def mirror_gm_logos():
    """Mirror stock logos into OUR S3 so the app never hotlinks a third
    party (privacy: user IPs stay off financialmodelingprep.com; and no
    dependency on an SLA-less CDN). Idempotent — only fetches tickers whose
    key is missing — so the weekly run costs a handful of requests once the
    universe is backfilled. TickerLogo's initial-circle fallback makes any
    residual gap cosmetic."""
    import boto3

    bucket = getattr(settings, 'AWS_PUBLICATIONS_BUCKET', None)
    if not bucket:
        return {'error': 'AWS_PUBLICATIONS_BUCKET not configured'}
    prefix = getattr(settings, 'GM_LOGOS_S3_PREFIX', 'stock-logos/v2/')

    from . import gm_api
    tickers = sorted({
        (item.get('underlyingMarket') or {}).get('ticker')
        for item in gm_api.all_market()
    } - {None, ''})

    s3 = boto3.client('s3', region_name=getattr(settings, 'AWS_S3_REGION', 'eu-central-2'))
    existing: set[str] = set()
    try:
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
            existing.update(o['Key'] for o in page.get('Contents', []))
    except Exception:  # noqa: BLE001 — no ListBucket perm → treat all as missing
        logger.warning('gm logo mirror: list failed, falling back to blind puts')

    mirrored = skipped = failed = 0
    for ticker in tickers:
        key = f'{prefix}{ticker}.png'
        if key in existing:
            skipped += 1
            continue
        try:
            resp = requests.get(
                f'https://financialmodelingprep.com/image-stock/{ticker}.png',
                timeout=10,
            )
            if resp.status_code == 200 and resp.content and \
                    'image' in resp.headers.get('Content-Type', ''):
                s3.put_object(
                    Bucket=bucket, Key=key, Body=_card_safe_logo(resp.content),
                    ContentType='image/png',
                    CacheControl='public, max-age=604800',
                )
                mirrored += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001 — one bad logo never stops the sweep
            failed += 1
    result = {'tickers': len(tickers), 'mirrored': mirrored, 'skipped': skipped, 'failed': failed}
    logger.info('gm logo mirror: %s', result)
    return result


# ── Accrual keeper ──────────────────────────────────────────────────────
# The vault accrues lazily (accrue() runs inside every mint/redeem), which
# is enough while there's traffic — but a long-idle vault accumulates
# oracle growth, and once the gap exceeds MAX_ACCRUAL_JUMP_BPS the next
# interaction trips the jump guard: accrual freezes until the Safe calls
# resetOracleBaseline(), and the frozen-window yield becomes surplus
# instead of holder yield. A periodic keeper poke makes that impossible.

# Mirrors the contract's MAX_ACCRUAL_JUMP_BPS (a compile-time constant,
# CusdPlusVault.sol) — sending accrue() past this bound would trip the
# guard on-chain, so the keeper alerts and holds instead.
MAX_ACCRUAL_JUMP_BPS = 200

SEL_ACCRUE = '0xf8ba4cff'            # accrue()
SEL_LAST_ORACLE_PRICE = '0x349f7173' # lastOraclePrice()
SEL_GUARD_TRIPPED = '0x49e7362a'     # oracleGuardTripped()
SEL_GET_PRICE = '0x98d5fdca'         # getPrice() — Ondo RWADynamicOracle


def _call_uint(to: str, data: str) -> int:
    res = _rpc('eth_call', [{'to': to, 'data': data}, 'latest'])
    return int(res, 16) if res and res != '0x' else 0


@shared_task(name='cusd_plus.accrue_vault')
def accrue_vault():
    """Keeper poke for CusdPlusVault.accrue() (permissionless), signed by
    the BSC sponsor via KMS. Reads first, sends only when the oracle has
    actually stepped since the last accrual — the oracle moves once per
    UTC day, so this lands ~1 cheap tx/day and is a pure no-op otherwise.

    Never sends into a fault: a tripped guard or a jump past the contract
    bound is logged loudly and left for the Safe (resetOracleBaseline),
    since the keeper tripping the guard itself would just convert the
    pending yield into surplus with no human in the loop."""
    from .vault import oracle_address, vault_address

    vault = vault_address()
    oracle = oracle_address()
    if not vault or not oracle:
        return {'skipped': 'unconfigured'}
    if not getattr(settings, 'CUSD_PLUS_ACCRUE_ENABLED', True):
        return {'skipped': 'disabled'}

    try:
        if _call_uint(vault, SEL_GUARD_TRIPPED):
            logger.error('cUSD+ accrue keeper: oracle guard is TRIPPED — '
                         'accrual frozen until the Safe calls resetOracleBaseline()')
            return {'skipped': 'guard_tripped'}
        last = _call_uint(vault, SEL_LAST_ORACLE_PRICE)
        p = _call_uint(oracle, SEL_GET_PRICE)
    except Exception as exc:  # noqa: BLE001 — read failure: retry next run
        logger.warning('cUSD+ accrue keeper: chain read failed: %s', exc)
        return {'skipped': 'read_failed'}

    if not last or not p:
        logger.warning('cUSD+ accrue keeper: zero read (last=%s p=%s)', last, p)
        return {'skipped': 'zero_read'}
    if p == last:
        return {'skipped': 'no_step'}  # oracle hasn't stepped yet — free no-op
    if p < last or ((p - last) * 10_000) // last > MAX_ACCRUAL_JUMP_BPS:
        logger.error('cUSD+ accrue keeper: oracle move would trip the jump '
                     'guard (last=%s new=%s) — holding for investigation', last, p)
        return {'skipped': 'would_trip_guard', 'last': last, 'price': p}

    try:
        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
        signer = get_bsc_sponsor_signer_from_settings()
    except Exception as exc:  # noqa: BLE001 — signing dark ≠ task failure
        logger.info('cUSD+ accrue keeper: signer unavailable (%s)', exc)
        return {'skipped': 'signer_unavailable'}

    try:
        sender = signer.address
        nonce = int(_rpc('eth_getTransactionCount', [sender, 'pending']), 16)
        gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                        int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))
        # accrue() is a couple of sstores plus the oracle's range walk;
        # generous limit, unused gas is not charged.
        gas_limit = int(getattr(settings, 'CUSD_PLUS_ACCRUE_GAS_LIMIT', 300_000))
        if int(_rpc('eth_getBalance', [sender, 'latest']), 16) < gas_limit * gas_price:
            logger.error('cUSD+ accrue keeper: sponsor BNB too low — refill needed')
            return {'skipped': 'sponsor_low'}
        raw, txh = signer.sign_transaction({
            'chainId': settings.BSC_CHAIN_ID, 'nonce': nonce, 'gasPrice': gas_price,
            'gas': gas_limit, 'to': vault, 'value': 0, 'data': SEL_ACCRUE,
        })
        sent = _rpc('eth_sendRawTransaction', [raw])
        logger.info('cUSD+ accrue sent (oracle %s → %s): %s', last, p, sent)
        return {'sent': sent, 'last': last, 'price': p}
    except Exception as exc:  # noqa: BLE001 — next scheduled run retries
        logger.exception('cUSD+ accrue keeper send failed: %s', exc)
        return {'skipped': 'send_failed'}
