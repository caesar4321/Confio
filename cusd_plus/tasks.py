"""
Celery side of the cUSD+ conversion saga — everything that needs NO keys
(ORCHESTRATION.md §2): polling Allbridge transfer status, BNB gas dusting,
abandoning stale quotes. The client (user keys) drives the actual legs.
"""
import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

ALLBRIDGE_CORE_API = 'https://core.api.allbridgecoreapi.net'
BSC_RPC_URL = getattr(settings, 'CUSD_PLUS_BSC_RPC_URL', 'https://bsc-dataseed.bnbchain.org')


def _bridge_source_chain(direction: str) -> str:
    return 'ALG' if direction == 'to_savings' else 'BSC'


@shared_task(name='cusd_plus.poll_bridge_transfers')
def poll_bridge_transfers():
    """Advance SRC_COMMITTED/STUCK rows by asking Allbridge about the source
    tx. Delivery -> DEST_ARRIVED (+ gas dust for the BSC leg); silence past
    the timeout -> STUCK + ops log. Idempotent; safe on overlap."""
    from .models import CusdPlusConversion

    timeout = timedelta(minutes=getattr(settings, 'CUSD_PLUS_BRIDGE_TIMEOUT_MIN', 30))
    rows = CusdPlusConversion.objects.filter(
        status__in=('SRC_COMMITTED', 'STUCK'), is_deleted=False,
    ).exclude(src_tx_id='')[:200]

    for conv in rows:
        try:
            res = requests.get(
                f'{ALLBRIDGE_CORE_API}/chain/{_bridge_source_chain(conv.direction)}/{conv.src_tx_id}',
                timeout=15,
            )
            if res.status_code == 404:
                # not indexed yet — normal for the first minutes
                delivered = False
            else:
                res.raise_for_status()
                data = res.json()
                # Delivered when the receive side carries a tx id.
                delivered = bool((data.get('receive') or {}).get('txId'))
        except Exception as exc:  # noqa: BLE001 — poller must not die
            logger.warning('allbridge poll failed for %s: %s', conv.internal_id, exc)
            continue

        if delivered:
            conv.status = 'DEST_ARRIVED'
            conv.dest_arrived_at = timezone.now()
            conv.save(update_fields=['status', 'dest_arrived_at', 'updated_at'])
            logger.info('conversion %s: bridge delivered', conv.internal_id)
            if conv.direction == 'to_savings' and conv.user_bsc_address:
                check_gas_dust.delay(str(conv.internal_id))
            # TODO(cusd+): websocket event + push nudge if the app is closed
            # ("te falta un paso para que tu ahorro gane rendimiento").
        elif (
            conv.status == 'SRC_COMMITTED'
            and conv.src_committed_at
            and timezone.now() - conv.src_committed_at > timeout
        ):
            conv.status = 'STUCK'
            conv.save(update_fields=['status', 'updated_at'])
            logger.error(
                'conversion %s STUCK: bridge silent past %s (src tx %s)',
                conv.internal_id, timeout, conv.src_tx_id,
            )


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
        res = requests.post(
            BSC_RPC_URL,
            json={
                'jsonrpc': '2.0', 'id': 1,
                'method': 'eth_getBalance',
                'params': [conv.user_bsc_address, 'latest'],
            },
            timeout=15,
        )
        res.raise_for_status()
        balance_wei = int(res.json()['result'], 16)
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
