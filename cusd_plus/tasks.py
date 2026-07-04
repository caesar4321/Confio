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
    """Chain-first bridge watcher. For Ahorrar rows in flight, scan BNB for
    a USDT Transfer to the user's own address since the row's cursor block;
    arrival (>= 90% of the quoted receive, partial-tolerant) advances to
    DEST_ARRIVED and triggers gas dusting. Prolonged silence -> STUCK (time
    against the chain, never against a vendor API).

    Retirar rows advance via the existing blockchain-app inbound USDC
    scanner (the auto-swap's own signal).
    TODO(cusd+): call mark_retirar_arrival() from that scanner when it sees
    a USDC credit for an address with a from_savings row in flight.
    """
    from .models import CusdPlusConversion

    timeout = timedelta(minutes=getattr(settings, 'CUSD_PLUS_BRIDGE_TIMEOUT_MIN', 30))
    rows = CusdPlusConversion.objects.filter(
        direction='to_savings',
        status__in=('SRC_COMMITTED', 'STUCK'),
        is_deleted=False,
    ).exclude(user_bsc_address='')[:200]
    if not rows:
        return

    try:
        latest_block = int(_rpc('eth_blockNumber', []), 16)
    except Exception as exc:  # noqa: BLE001 — watcher must not die
        logger.warning('bsc blockNumber failed: %s', exc)
        return

    for conv in rows:
        # First sighting: pin the cursor to the current tip. The source leg
        # was seconds-to-minutes ago; the bridge takes ~60s, so the arrival
        # is always at or after this cursor.
        if conv.dest_scan_from_block is None:
            conv.dest_scan_from_block = max(latest_block - 400, 0)  # ~small safety window
            conv.save(update_fields=['dest_scan_from_block', 'updated_at'])

        try:
            logs = _rpc('eth_getLogs', [{
                'fromBlock': hex(conv.dest_scan_from_block),
                'toBlock': hex(latest_block),
                'address': USDT_BSC,
                'topics': [TRANSFER_TOPIC, None, _address_topic(conv.user_bsc_address)],
            }])
        except Exception as exc:  # noqa: BLE001
            logger.warning('bsc getLogs failed for %s: %s', conv.internal_id, exc)
            continue

        floor_units = int(float(conv.quoted_receive_usd) * 0.9 * 1e18)
        arrival = next(
            (l for l in logs if int(l['data'], 16) >= floor_units),
            None,
        )

        if arrival:
            conv.status = 'DEST_ARRIVED'
            conv.dest_arrived_at = timezone.now()
            conv.bridge_arrival_tx = arrival['transactionHash']
            conv.save(update_fields=[
                'status', 'dest_arrived_at', 'bridge_arrival_tx', 'updated_at',
            ])
            logger.info(
                'conversion %s: USDT arrived on BNB (%s)',
                conv.internal_id, arrival['transactionHash'],
            )
            check_gas_dust.delay(str(conv.internal_id))
            # TODO(cusd+): websocket event + push nudge if the app is closed
            # ("te falta un paso para que tu ahorro gane rendimiento").
        else:
            # Advance the cursor so scans stay narrow (small overlap for
            # reorg safety).
            conv.dest_scan_from_block = max(latest_block - 50, conv.dest_scan_from_block)
            fields = ['dest_scan_from_block', 'updated_at']
            if (
                conv.status == 'SRC_COMMITTED'
                and conv.src_committed_at
                and timezone.now() - conv.src_committed_at > timeout
            ):
                conv.status = 'STUCK'
                fields.append('status')
                logger.error(
                    'conversion %s STUCK: no USDT arrival on BNB after %s (src tx %s). '
                    'Support diagnostic: allbridge_diagnose("%s")',
                    conv.internal_id, timeout, conv.src_tx_id, conv.internal_id,
                )
            conv.save(update_fields=fields)


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
