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

    ONE pipeline for every USDT arrival at a user address (the Algorand
    USDC scanner's shape), with attribution hooks — not separate routes:

      - Arrival matching an in-flight to_savings conversion (>= 90% of the
        quote) -> bridge arrival: advance the saga (leg B done), dust gas.
      - Any other arrival at a REGISTERED savings address (an Account with
        bsc_address set) -> a CusdPlusConversion row born at DEST_ARRIVED
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
    from .models import CusdPlusConversion

    timeout = timedelta(minutes=getattr(settings, 'CUSD_PLUS_BRIDGE_TIMEOUT_MIN', 30))
    conversions = list(CusdPlusConversion.objects.filter(
        direction='to_savings',
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

    try:
        latest_block = int(_rpc('eth_blockNumber', []), 16)
    except Exception as exc:  # noqa: BLE001 — watcher must not die
        logger.warning('bsc blockNumber failed: %s', exc)
        return

    rewind = int(getattr(settings, 'CUSD_PLUS_BSC_SCAN_REWIND_BLOCKS', 100))
    from_block = cache.get('cusd_plus_bsc_scan_cursor') or max(latest_block - 1200, 0)
    from_block = max(int(from_block) - rewind, 0)

    logs: list[dict] = []
    addrs = sorted(watch_all)
    for i in range(0, len(addrs), 800):
        try:
            logs += _rpc('eth_getLogs', [{
                'fromBlock': hex(from_block),
                'toBlock': hex(latest_block),
                'address': USDT_BSC,
                'topics': [TRANSFER_TOPIC, None,
                           [_address_topic(a) for a in addrs[i:i + 800]]],
            }])
        except Exception as exc:  # noqa: BLE001
            logger.warning('bsc getLogs failed: %s', exc)
            return  # cursor untouched — next run rescans the window
    cache.set('cusd_plus_bsc_scan_cursor', latest_block, None)

    now = timezone.now()
    min_deposit = Decimal(str(getattr(settings, 'CUSD_PLUS_MIN_EXTERNAL_DEPOSIT_USD', 1)))
    arrived: dict[str, dict] = {}
    for log in logs:
        key = ('0x' + log['topics'][2][-40:]).lower()
        raw_units = int(log['data'], 16)
        conv = conv_watch.get(key)
        if conv is not None:
            floor_units = int(float(conv.quoted_receive_usd) * 0.9 * 1e18)
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


def _record_inbound_deposit(account_id, to_addr, amount_usd, tx_ref, tx_hash, source, now):
    """A chain-observed USDT inflow becomes a conversion row born at
    DEST_ARRIVED: the funds are already at the user's address, so only leg C
    (mint) remains — the existing foreground resume and gas dusting finish
    it with zero client changes. amount_usd is the EXACT floored arrival:
    the client mints exactly this, so recording more than arrived would
    revert the mint.

    Idempotent by (address, bridge_arrival_tx), which BOTH row kinds set:
    the cursor rewind makes rescans routine, and a bridge delivery re-seen
    after its conversion advanced out of the watch set must not be reborn
    as an external deposit. (Known trade-off: a single tx carrying multiple
    Transfers to the same address records only the first — wallet sends are
    one transfer per tx, and the rest stays visible on chain for support.)"""
    from users.models import Account
    from .models import CusdPlusConversion

    if CusdPlusConversion.objects.filter(
        user_bsc_address=to_addr, bridge_arrival_tx=tx_hash, is_deleted=False,
    ).exists():
        return
    account = Account.objects.filter(id=account_id).select_related('user', 'business').first()
    if account is None:
        return
    is_business = account.account_type == 'business'
    conv = CusdPlusConversion.objects.create(
        actor_user=None if is_business else account.user,
        actor_business=account.business if is_business else None,
        actor_type='business' if is_business else 'user',
        actor_display_name=account.display_name,
        direction='to_savings',
        source=source,
        amount_usd=amount_usd,
        quoted_receive_usd=amount_usd,  # already delivered — nothing left to quote
        quoted_cost_pct=0,
        user_bsc_address=to_addr,
        src_tx_id=tx_ref,
        bridge_arrival_tx=tx_hash,
        status='DEST_ARRIVED',
        dest_arrived_at=now,
    )
    logger.info(
        'inbound USDT deposit %s (%s): %s USDT at %s (%s)',
        conv.internal_id, source, amount_usd, to_addr, tx_hash,
    )
    check_gas_dust.delay(str(conv.internal_id))

    if source == 'ramp':
        return  # order comms belong to the ramp flow (koywe_sync)
    try:
        from notifications import utils as notif_utils
        from notifications.models import NotificationType as NotifType
        notif_utils.create_notification(
            user=account.user,
            account=account,
            business=account.business if is_business else None,
            notification_type=NotifType.SEND_FROM_EXTERNAL,
            title='Depósito recibido',
            message=f'Recibiste ${amount_usd:.2f} (USDT). Se sumará automáticamente a tu ahorro.',
            data={
                'transaction_type': 'deposit',
                'currency': 'USDT',
                'network': 'BSC',
                'amount': str(amount_usd),
                'tx_hash': tx_hash,
                'conversion_id': str(conv.internal_id),
                'pending_auto_mint': True,
            },
            related_object_type='CusdPlusConversion',
            related_object_id=str(conv.internal_id),
        )
    except Exception:  # noqa: BLE001 — comms failure must not lose the deposit
        logger.exception('deposit notification failed for %s', conv.internal_id)


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


def _gas_dust_target_wei() -> int:
    """BNB a user address needs for its next leg (approve + subscribeAndMint).

    Sized to ONE action, not a batch: the 21k dust-tx overhead is ~$0.001,
    so re-dusting on demand beats parking idle BNB in the user's wallet.
    Gas-price aware with a spike buffer so a rising market still clears the
    action; capped so a gas spike can never over-drain the sponsor.
    """
    action_gas = int(getattr(settings, 'CUSD_PLUS_GAS_ACTION_BUDGET', 700_000))  # ~645k measured + margin
    spike_mult = int(getattr(settings, 'CUSD_PLUS_GAS_DUST_SPIKE_MULT', 3))
    try:
        gas_price = int(_rpc('eth_gasPrice', []), 16)
    except Exception:  # noqa: BLE001
        gas_price = 1_000_000_000  # 1 gwei fallback
    gas_price = max(gas_price, int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))  # ≥0.1 gwei
    target = action_gas * gas_price * spike_mult
    cap = int(getattr(settings, 'CUSD_PLUS_GAS_DUST_MAX_WEI', 5_000_000_000_000_000))  # 0.005 BNB hard cap
    return min(target, cap)


@shared_task(name='cusd_plus.check_gas_dust')
def check_gas_dust(conversion_internal_id: str):
    """Top up user.bsc with just enough BNB for its next leg (approve +
    subscribeAndMint). Sponsorship, not custody — BSC has no protocol-level
    fee delegation (unlike Algorand group fee pooling), so the fee must sit
    at the signer's own address; we pre-fund the shortfall and no more. The
    BNB lands at the USER's address and the user signs their own tx.

    Trigger point (DEST_ARRIVED) already means a verified conversion is
    imminent, so this can't be farmed for free BNB. Gated off by default so
    it ships dark until the savings rail is live.
    """
    from django.core.cache import cache
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

    needed_wei = _gas_dust_target_wei()
    if balance_wei >= needed_wei:
        return  # already funded — most repeat users skip dusting entirely
    shortfall = needed_wei - balance_wei

    if not getattr(settings, 'CUSD_PLUS_GAS_DUST_ENABLED', False):
        logger.info('gas dust needed for %s (%s wei short) but sender disabled',
                    conv.internal_id, shortfall)
        return

    # Rate limit per address: one dust per few minutes defeats spray attacks.
    rl_key = f'cusd_plus_gasdust_{conv.user_bsc_address.lower()}'
    if cache.get(rl_key):
        logger.info('gas dust rate-limited for %s', conv.user_bsc_address)
        return

    # Daily cap per address: external deposits let anyone mint a dust
    # trigger by sending themselves $1 USDT, so cycling (receive dust, move
    # the BNB out, deposit again) must stop paying after a few rounds.
    # Legit users are unaffected — BNB stays put, so repeat actions skip
    # dusting entirely; a capped row just waits for the next day's resume.
    day_key = f'cusd_plus_gasdust_day_{conv.user_bsc_address.lower()}'
    day_count = cache.get(day_key, 0)
    if day_count >= int(getattr(settings, 'CUSD_PLUS_GAS_DUST_MAX_PER_DAY', 5)):
        logger.warning('gas dust daily cap hit for %s (%s)', conv.user_bsc_address, conv.internal_id)
        return

    try:
        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
        signer = get_bsc_sponsor_signer_from_settings()
        sender = signer.address
        nonce = int(_rpc('eth_getTransactionCount', [sender, 'pending']), 16)
        gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                        int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))
        sponsor_balance = int(_rpc('eth_getBalance', [sender, 'latest']), 16)
        if sponsor_balance < shortfall + 21_000 * gas_price:
            logger.error('sponsor BNB too low for gas dust (have %s, need %s) — refill needed',
                         sponsor_balance, shortfall)
            return
        raw, txh = signer.sign_transaction({
            'chainId': settings.BSC_CHAIN_ID, 'nonce': nonce, 'gasPrice': gas_price,
            'gas': 21000, 'to': conv.user_bsc_address, 'value': shortfall, 'data': b'',
        })
        sent = _rpc('eth_sendRawTransaction', [raw])
        cache.set(rl_key, 1, 180)  # 3-min cooldown per address
        cache.set(day_key, day_count + 1, 24 * 3600)
        logger.info('gas dust sent %s wei to %s for %s: %s',
                    shortfall, conv.user_bsc_address, conv.internal_id, sent)
    except Exception as exc:  # noqa: BLE001 — dusting must never crash the scanner
        logger.exception('gas dust send failed for %s: %s', conv.internal_id, exc)


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
