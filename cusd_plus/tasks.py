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

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BSC_RPC_URL = getattr(settings, 'CUSD_PLUS_BSC_RPC_URL', 'https://bsc-dataseed.bnbchain.org')
USDT_BSC = getattr(settings, 'CUSD_PLUS_USDT_BSC', '0x55d398326f99059fF775485246999027B3197955')
# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'


def _rpc(method, params, timeout=15):
    res = requests.post(
        BSC_RPC_URL,
        json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
        timeout=timeout,
    )
    res.raise_for_status()
    body = res.json()
    if 'error' in body:
        raise RuntimeError(f"bsc rpc: {body['error']}")
    return body['result']


def _address_topic(address: str) -> str:
    return '0x' + address.lower().replace('0x', '').rjust(64, '0')


@shared_task(name='cusd_plus.monitor_bridge_arrivals')
def monitor_bridge_arrivals():
    """BSC USDT inbound scanner — the BNB sibling of blockchain.scan_inbound_deposits.

    ONE batched eth_getLogs per run (topics accept an ADDRESS ARRAY, so cost
    does not grow with the watch set) over a global cursor, then classify
    each arrival at a watched user.bsc address:

      1. in-flight conversion for that address  -> bridge arrival (leg B done)
      2. TODO(ramps): pending Koywe order with destination=cusd_plus
         -> ramp delivery (watch-set source joins when the ramp param ships)
      3. TODO(external deposits — Julian, 2026-07-04): anything else is an
         EXTERNAL USDT-BSC deposit. These must become first-class: the
         crypto-native/no-Koywe onramp is "send USDT (BEP-20) to your
         address, it becomes savings" — WITHOUT this, those users would be
         forced through USDC-ALG + the thin Allbridge pool for no reason.
         Needs: user.bsc registration on Account (savings activation),
         deposit record + notification, auto-mint prompt on foreground
         (the auto-swap pattern, gas-dusted). Until then unmatched arrivals
         are logged for visibility.

    STUCK is judged by chain silence only — never by a vendor API.
    """
    from django.core.cache import cache
    from .models import CusdPlusConversion

    timeout = timedelta(minutes=getattr(settings, 'CUSD_PLUS_BRIDGE_TIMEOUT_MIN', 30))
    conversions = list(CusdPlusConversion.objects.filter(
        direction='to_savings',
        status__in=('SRC_COMMITTED', 'STUCK'),
        is_deleted=False,
    ).exclude(user_bsc_address='')[:500])

    # Watch set: in-flight conversions + pending savings-rail Koywe orders
    # (source 2 — Koywe delivers USDT-BSC to the user's own address);
    # registered savings addresses join with external deposits (source 3).
    watch = {c.user_bsc_address.lower(): c for c in conversions}
    try:
        from ramps.models import RampTransaction
        ramp_addrs = RampTransaction.objects.filter(
            destination='cusd_plus',
            direction='on_ramp',
            status__in=('PENDING', 'PROCESSING'),
        ).exclude(actor_address='').values_list('actor_address', flat=True)[:300]
        for addr in ramp_addrs:
            watch.setdefault(addr.lower(), None)  # None = ramp-only address
    except Exception:  # noqa: BLE001
        logger.exception('ramp watch-set union failed')
    if not watch:
        return  # idle: zero RPC calls

    try:
        latest_block = int(_rpc('eth_blockNumber', []), 16)
    except Exception as exc:  # noqa: BLE001 — watcher must not die
        logger.warning('bsc blockNumber failed: %s', exc)
        return

    # Global cursor with a rewind margin (the Algorand scanner pattern);
    # idempotency comes from monotonic status transitions.
    rewind = int(getattr(settings, 'CUSD_PLUS_BSC_SCAN_REWIND_BLOCKS', 100))
    from_block = cache.get('cusd_plus_bsc_scan_cursor') or max(latest_block - 1200, 0)
    from_block = max(int(from_block) - rewind, 0)

    try:
        logs = _rpc('eth_getLogs', [{
            'fromBlock': hex(from_block),
            'toBlock': hex(latest_block),
            'address': USDT_BSC,
            # ONE call for the whole watch set: topic2 as an OR-array
            'topics': [TRANSFER_TOPIC, None, [_address_topic(a) for a in watch]],
        }])
    except Exception as exc:  # noqa: BLE001
        logger.warning('bsc getLogs failed: %s', exc)
        return
    cache.set('cusd_plus_bsc_scan_cursor', latest_block, None)

    arrived: dict[str, dict] = {}
    for log in logs:
        to_addr = '0x' + log['topics'][2][-40:]
        key = to_addr.lower()
        if key not in watch:
            continue
        conv = watch[key]
        if conv is None:
            # Ramp-only address: Koywe delivery observed on-chain. Order
            # status stays koywe_sync's job; this is chain-side visibility
            # (and later the auto-mint trigger for source 3).
            logger.info(
                'USDT arrival at savings ramp address %s (%s)',
                to_addr, log['transactionHash'],
            )
            continue
        floor_units = int(float(conv.quoted_receive_usd) * 0.9 * 1e18)
        if int(log['data'], 16) >= floor_units:
            arrived[key] = log
        else:
            logger.info(
                'unmatched USDT arrival at watched address %s (%s) — external deposit path not built yet',
                to_addr, log['transactionHash'],
            )

    now = timezone.now()
    for addr, conv in watch.items():
        if conv is None:
            continue
        log = arrived.get(addr)
        if log:
            conv.status = 'DEST_ARRIVED'
            conv.dest_arrived_at = now
            conv.bridge_arrival_tx = log['transactionHash']
            conv.save(update_fields=[
                'status', 'dest_arrived_at', 'bridge_arrival_tx', 'updated_at',
            ])
            logger.info(
                'conversion %s: USDT arrived on BNB (%s)',
                conv.internal_id, log['transactionHash'],
            )
            check_gas_dust.delay(str(conv.internal_id))
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
                conv.internal_id, timeout, conv.src_tx_id, conv.internal_id,
            )


def mark_retirar_arrival(algo_address: str, txid: str) -> bool:
    """Hook for the existing inbound USDC scanner (blockchain app): when a
    USDC credit lands at an address with a from_savings conversion in
    flight, record the arrival. Returns True if a row advanced."""
    from .models import CusdPlusConversion

    conv = CusdPlusConversion.objects.filter(
        direction='from_savings',
        status__in=('SRC_COMMITTED', 'STUCK'),
        user_algo_address=algo_address,
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
    from .models import CusdPlusConversion

    conv = CusdPlusConversion.objects.get(internal_id=conversion_internal_id)
    chain = 'ALG' if conv.direction == 'to_savings' else 'BSC'
    res = requests.get(
        f'https://core.api.allbridgecoreapi.net/chain/{chain}/{conv.src_tx_id}',
        timeout=15,
    )
    return {'status_code': res.status_code, 'body': res.json() if res.ok else res.text}


@shared_task(name='cusd_plus.check_gas_dust')
def check_gas_dust(conversion_internal_id: str):
    """Ensure user.bsc holds enough BNB for its next leg (approve + mint).
    Sponsorship, not custody — mirrors Algorand fee pooling in spirit.

    The BALANCE check is live; the SEND requires an EVM signer in the
    backend (eth-account) plus the relayer key in SSM — both land with the
    BSC deploy. Gated off by default so this can ship dark.
    """
    from .models import CusdPlusConversion

    try:
        conv = CusdPlusConversion.objects.get(internal_id=conversion_internal_id)
    except CusdPlusConversion.DoesNotExist:
        return

    if not conv.user_bsc_address:
        return
    try:
        balance_wei = int(_rpc('eth_getBalance', [conv.user_bsc_address, 'latest']), 16)
    except Exception as exc:  # noqa: BLE001
        logger.warning('gas dust balance check failed for %s: %s', conv.internal_id, exc)
        return

    needed_wei = int(getattr(settings, 'CUSD_PLUS_GAS_DUST_WEI', 300_000_000_000_000))  # 0.0003 BNB
    if balance_wei >= needed_wei:
        return

    if not getattr(settings, 'CUSD_PLUS_GAS_DUST_ENABLED', False):
        logger.info(
            'gas dust needed for %s (%s wei short) but sender disabled',
            conv.internal_id, needed_wei - balance_wei,
        )
        return
    # TODO(cusd+ deploy): send (needed - balance) BNB from the relayer key
    # (SSM: /confio/cusd_plus/relayer-key) via eth-account signed legacy tx;
    # record spend in sponsorship accounting.
    logger.error('gas dust send not implemented yet (conversion %s)', conv.internal_id)


@shared_task(name='cusd_plus.abandon_stale_quotes')
def abandon_stale_quotes():
    """CREATED rows the user never signed expire after a day — keeps the
    resume list honest."""
    from .models import CusdPlusConversion

    cutoff = timezone.now() - timedelta(hours=24)
    stale = CusdPlusConversion.objects.filter(
        status='CREATED', created_at__lt=cutoff, is_deleted=False,
    )
    updated = stale.update(status='ABANDONED', updated_at=timezone.now())
    if updated:
        logger.info('abandoned %d stale cusd+ conversion quotes', updated)


def _card_safe_logo(png_bytes: bytes) -> bytes:
    """FMP serves SOME logos as white glyphs on transparency (dark-UI
    variants) — invisible silhouettes on Confío's white cards (53 of the
    first 420, incl. AMZN/NKE/V/MELI). Detect them (transparent canvas +
    mostly-light opaque pixels) and bake a dark rounded chip behind the
    glyph; everything else passes through untouched."""
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
