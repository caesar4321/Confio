"""Relayer-originated transactions to an account (spec 7.4): collectFee,
startPaymentNotice, forcedSale, executeRule, convertUsdt, returnAsset,
latchConfioSale. A plain type-2 transaction from the KMS sponsor signer.

Same durability rule as send_sponsored_batch: the SmartAccountRelayTx row is
written with the DETERMINISTIC signed hash before eth_sendRawTransaction, so
a crash between sign and broadcast leaves a row the reconciler resolves by
hash, and a second run finds that row instead of sending again.
"""
from __future__ import annotations

import logging
import re
import threading
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, OperationalError, connection, transaction
from django.utils import timezone

from . import abi, chain
from .models import SmartAccountRelayTx

logger = logging.getLogger(__name__)

MAX_RELAY_GAS = 6_000_000
# A forced sale is the one relayer call whose gas grows with its legs.
MAX_RELAY_GAS_BY_KIND = {'smart_forced_sale': abi.RELAY_GAS_SALE_MAX}
# sponsor_7702.acquire_sponsor_nonce_lock's key. It expires by itself, so
# holding it is proven again before anything that depends on the nonce.
NONCE_LOCK = 'bsc_sponsor_nonce_lock'
STEP_HOLD_SECONDS = 15
# A broadcast may try every endpoint: the lock is renewed while it runs, so
# a killed worker leaves it for STEP_HOLD_SECONDS at most.
RENEW_SECONDS = 4
# An eth_call failure that says the call itself fails. Anything else is a
# node that did not answer.
REVERTED = re.compile(r'revert|out of gas|gas required exceeds|invalid opcode|invalid jump', re.IGNORECASE)
# The claim's row locks, each inside the nonce lock's lifetime.
CLAIM_LOCK_WAIT = '3s'


def max_relay_gas(kind: str) -> int:
    return MAX_RELAY_GAS_BY_KIND.get(kind, MAX_RELAY_GAS)


class RelayError(Exception):
    """A relayer call that was NOT broadcast. `code` is stable."""

    def __init__(self, code: str, detail: str = ''):
        self.code = code
        self.detail = detail
        super().__init__(f'{code}: {detail}' if detail else code)


def _hold(token: str, seconds: int) -> None:
    """Still this signer's nonce lock, and for `seconds` more. Read again
    after the extension: a lock that expired in between is someone else's."""
    if cache.get(NONCE_LOCK) != token or not cache.touch(NONCE_LOCK, seconds) or cache.get(NONCE_LOCK) != token:
        raise RelayError('sponsor_lock_lost')


@contextmanager
def _kept(token: str):
    """Renews the lock while the block runs, and only while it is this
    signer's."""
    stop, every = threading.Event(), RENEW_SECONDS

    def renew():
        while not stop.wait(every):
            try:
                _hold(token, STEP_HOLD_SECONDS)
            except RelayError:
                return
            except Exception:  # noqa: BLE001 — the cache: tried again before it expires
                logger.warning('sponsor nonce lock not renewed', exc_info=True)
    worker = threading.Thread(target=renew, name='sponsor-nonce-lock', daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(STEP_HOLD_SECONDS)


def live_tx(account, kind: str, source_id: str):
    return SmartAccountRelayTx.objects.filter(
        smart_account=account, kind=kind, source_id=str(source_id),
        status__in=SmartAccountRelayTx.LIVE_STATUSES).order_by('-id').first()


def simulate(sponsor: str, to: str, calldata: str, gas: int) -> None:
    """eth_call under the REAL gas budget, from the sponsor (so the
    contract's relayer check sees msg.sender == tx.origin == sponsor).
    simulation_reverted only for a call that fails; a node that did not
    answer is simulation_unreadable. Neither is sent."""
    try:
        chain.rpc('eth_call', [{'from': sponsor, 'to': to, 'data': calldata, 'gas': hex(int(gas))}, 'latest'])
    except Exception as exc:  # noqa: BLE001 — a revert or an unreadable node: do not send
        detail = str(exc)
        reverted = REVERTED.search(detail) or abi.revert_error(detail)
        raise RelayError('simulation_reverted' if reverted else 'simulation_unreadable', detail[:300]) from exc


def relay_target(account, calldata: str, kind: str) -> str:
    """The one address this relayer call may go to, after checking that the
    calldata is exactly the one function its kind allows (abi.RELAY_KIND_CALLS):
    an account function on the account itself, or a factory approval naming
    this account. Anything else is refused before signing."""
    if kind not in abi.RELAY_KIND_CALLS:
        raise RelayError('bad_kind', kind)
    target, allowed = abi.RELAY_KIND_CALLS[kind]
    try:
        name, args = abi.decode_call(calldata)
    except ValueError as exc:
        raise RelayError('bad_calldata', kind) from exc
    if name != allowed:
        raise RelayError('call_not_allowed', f'{kind}: {name}')
    account_address = (account.contract_address or '').lower()
    if target == 'account':
        return account_address
    factory = chain.factory_address()
    if not factory:
        raise RelayError('disabled')
    if str(args[0]).lower() != account_address:
        # A factory approval only ever names the account this row is for.
        raise RelayError('call_not_allowed', f'{kind}: other account')
    return factory


def send_relayer_call(account, calldata: str, kind: str, source_id, *, gas: int | None = None,
                      before_sign=None, claim=None):
    """Sign and broadcast one relayer call. Returns (row, created).

    Idempotent on (account, kind, source_id): while a transaction for that
    key is signed, sent or confirmed, the existing row is returned and
    nothing is signed. Raises RelayError when nothing was broadcast; any
    exception from the broadcast itself propagates with the row left
    'signed' for the reconciler.

    `before_sign()` runs under the sponsor nonce lock immediately before
    signing. `claim(tx_hash)` runs inside the transaction that writes the
    durable row, before it: what it locks stays locked until that row is
    visible. Either refuses with RelayError and nothing is broadcast. So
    does a nonce lock that is no longer this call's (sponsor_lock_lost; if
    that is seen after the row committed, the row stays 'signed' until the
    reconciler drops it) and a row lock not granted in time (claim_busy).

    Only the calls in abi.RELAY_KIND_CALLS are ever signed: the account's
    relayer and keeper functions, to the account, and the factory's
    designation/acceptance approvals for this account, to the factory."""
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
    from cusd_plus import sponsor_7702
    from eth_utils import to_checksum_address

    # Returning an expired account's assets is an exit: it needs only a
    # configured factory, never the feature flag (automation.return_expired).
    if not (chain.enabled() or (kind == 'smart_return' and chain.factory_address())):
        raise RelayError('disabled')
    calldata = (calldata or '').lower()
    to = relay_target(account, calldata, kind)
    source_id = str(source_id)
    existing = live_tx(account, kind, source_id)
    if existing is not None:
        return existing, False

    gas = int(gas or abi.RELAY_GAS.get(kind) or 0)
    if gas <= 0 or gas > max_relay_gas(kind):
        raise RelayError('bad_gas', str(gas))
    signer = get_bsc_sponsor_signer_from_settings()
    sponsor = signer.address
    simulate(sponsor, to, calldata, gas)

    gas_price = max(int(chain.rpc('eth_gasPrice', []), 16),
                    int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 50_000_000)))
    price_cap = int(getattr(settings, 'CUSD_PLUS_7702_MAX_GAS_PRICE_WEI', 5_000_000_000))
    if gas_price > price_cap:
        raise RelayError('gas_price_too_high')
    fee_per_gas = min((gas_price * 12) // 10, price_cap)

    lock = sponsor_7702.acquire_sponsor_nonce_lock()
    if not lock:
        raise RelayError('sponsor_busy')
    try:
        sponsor_nonce = int(chain.rpc('eth_getTransactionCount', [sponsor, 'pending']), 16)
        balance = int(chain.rpc('eth_getBalance', [sponsor, 'latest']), 16)
        if balance < (gas * fee_per_gas * 11) // 10:
            logger.error('sponsor BNB too low for smart account relay call (have %s)', balance)
            raise RelayError('sponsor_balance_low')
        tx = {
            'type': 2,
            'chainId': int(getattr(settings, 'BSC_CHAIN_ID', 56)),
            'nonce': sponsor_nonce,
            'maxPriorityFeePerGas': fee_per_gas,
            'maxFeePerGas': fee_per_gas,
            'gas': gas,
            'to': to_checksum_address(to),
            'value': 0,
            'data': calldata,
            'accessList': [],
        }
        if before_sign is not None:
            before_sign()
        _hold(lock, STEP_HOLD_SECONDS)
        raw, tx_hash = signer.sign_typed_transaction(tx)
        _hold(lock, STEP_HOLD_SECONDS)

        # DURABLE record BEFORE broadcast.
        try:
            with transaction.atomic():
                if claim is not None:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('lock_timeout', %s, true)", [CLAIM_LOCK_WAIT])
                    claim(tx_hash)
                row = SmartAccountRelayTx.objects.create(
                    smart_account=account, kind=kind, source_id=source_id, calldata=calldata,
                    signed_tx_hash=tx_hash, sponsor_nonce=sponsor_nonce, gas_limit=gas,
                    max_fee_wei=str(fee_per_gas), status='signed')
                # Lost while waiting above: nothing is recorded.
                _hold(lock, STEP_HOLD_SECONDS)
        except OperationalError as exc:
            raise RelayError('claim_busy', str(exc)[:300]) from exc
        except IntegrityError:
            # Another worker owns this (account, kind, source): never broadcast.
            existing = live_tx(account, kind, source_id)
            if existing is not None:
                return existing, False
            raise
        # Lost since the commit: another signer may hold this nonce now, and
        # there are never two on the wire.
        _hold(lock, STEP_HOLD_SECONDS)
        try:
            with _kept(lock):
                chain.rpc('eth_sendRawTransaction', [raw])
        except Exception:  # noqa: BLE001
            # Kept as 'signed' with the real hash: the reconciler reads the
            # chain and either finds it or, after the grace window, drops it.
            logger.exception('smart account relay broadcast failed (row %s kept as signed): %s',
                             row.id, tx_hash)
            raise
        # Past the point of no return: nothing below may raise.
        try:
            SmartAccountRelayTx.objects.filter(pk=row.pk, status='signed').update(
                status='sent', updated_at=timezone.now())
            row.status = 'sent'
        except Exception:  # noqa: BLE001
            logger.exception('smart account relay post-broadcast write failed for %s', tx_hash)
    finally:
        sponsor_7702.release_sponsor_nonce_lock(lock)

    try:
        from . import inflight
        if kind not in abi.RELAY_KINDS_NO_BALANCE:
            inflight.invalidate_address(account.contract_address)
        from .tasks import check_relay_tx
        check_relay_tx.apply_async(args=[row.id], countdown=3)
    except Exception:  # noqa: BLE001 — a broker outage must not fail a sent tx
        logger.exception('smart account relay receipt check could not be scheduled for %s', tx_hash)
    logger.info('smart account relay %s sent for %s: %s (gas=%s)', kind, to, tx_hash, gas)
    return row, True


def resolve_receipt(row) -> str:
    """Move one 'signed'/'sent' row toward a final status from its receipt.
    Returns the row's status afterwards. Raises on an unreadable chain so
    the caller retries (never a guessed outcome)."""
    from cusd_plus.tasks import _finality_depth, _finalized_block_number

    if row.status not in ('signed', 'sent'):
        return row.status
    receipt = chain.receipt(row.signed_tx_hash)
    if not receipt:
        return row.status
    block_number = int(receipt.get('blockNumber'), 16)
    block_hash = (receipt.get('blockHash') or '').lower()
    finalized = _finalized_block_number()
    if finalized is not None:
        if block_number > finalized:
            return row.status
    elif chain.head_block() - block_number < _finality_depth():
        return row.status
    canonical = chain.rpc('eth_getBlockByNumber', [hex(block_number), False])
    if not canonical or (canonical.get('hash') or '').lower() != block_hash:
        if not chain.receipt(row.signed_tx_hash):
            _finish(row, 'reorged', None, '')
        return row.status
    _finish(row, 'confirmed' if receipt.get('status') == '0x1' else 'reverted', block_number, block_hash)
    return row.status


def drop_if_nonce_passed(row) -> bool:
    """A 'sent' row that was never mined while the sponsor's MINED nonce has
    moved past it can never be mined: another transaction took its nonce.
    Marks it 'dropped' (freeing its idempotency slot) and returns True. The
    mined nonce is read BEFORE the receipt, so a transaction mined between
    the two reads is seen by its receipt and never dropped. Fails closed: no
    configured sponsor, no recorded nonce or an unreadable node drop nothing
    (the read raises to the caller)."""
    sponsor = (getattr(settings, 'BSC_SPONSOR_ADDRESS', None) or '').strip()
    if row.status != 'sent' or row.sponsor_nonce is None or not sponsor:
        return False
    mined_nonce = int(chain.rpc('eth_getTransactionCount', [sponsor, 'latest']), 16)
    if mined_nonce <= int(row.sponsor_nonce):
        return False
    if chain.receipt(row.signed_tx_hash):
        return False  # mined: resolve_receipt decides
    _finish(row, 'dropped', None, '')
    return row.status == 'dropped'


def _finish(row, status: str, block_number, block_hash: str) -> None:
    from . import inflight
    # Invalidate BEFORE the row turns terminal (same rule as stock batches).
    inflight.on_relay_final(row, block_number)
    won = SmartAccountRelayTx.objects.filter(pk=row.pk, status__in=('signed', 'sent')).update(
        status=status, block_number=block_number, block_hash=block_hash or '', updated_at=timezone.now())
    if won:
        row.status, row.block_number, row.block_hash = status, block_number, block_hash or ''
