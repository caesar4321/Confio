"""Factory approvals for designations and acceptances (audit fix to
decision 26; IConfioSmartAccountFactory.approveDesignation / approveAcceptance).

The account's tx.origin gate proves only that a sponsor STARTED the
transaction. The account therefore also requires a live factory approval for
the exact designation (account, beneficiary, window) or acceptance (account,
beneficiary), recorded by the relayer for one hour. The server records it
only after every check of spec 6.1 passed, and returns the batch for the
user to sign only once the approval is on chain. If the approval cannot be
put on chain, the prepare fails and no batch is returned (fail closed).
"""
from __future__ import annotations

import logging
import time

from django.conf import settings

from . import abi, chain, relayer

logger = logging.getLogger(__name__)

APPROVAL_TTL_SECONDS = 3600
# A new approval is sent at most once per bucket for the same designation,
# so a reused one has at least TTL - BUCKET (30 min) left: more than the
# prepared batch's own 15-minute window.
BUCKET_SECONDS = 1800
POLL_SECONDS = 1.0

MESSAGES = {
    'approval_failed': 'No pudimos registrar esta autorización. Inténtalo de nuevo en unos minutos.',
    'approval_pending': 'Estamos registrando la autorización. Inténtalo de nuevo en unos segundos.',
}


def _error(code: str):
    from .services import PrepareError
    return PrepareError(code, MESSAGES[code])


def _min_remaining() -> int:
    from .services import PREPARED_TTL_SECONDS
    return PREPARED_TTL_SECONDS + 300


def _wait_seconds() -> float:
    return float(getattr(settings, 'SMART_ACCOUNT_APPROVAL_WAIT_SECONDS', 20))


def _read(fn, *args) -> int:
    from .services import PrepareError
    try:
        return int(fn(*args))
    except Exception as exc:  # noqa: BLE001 — unreadable is an error, never "approved"
        logger.warning('smart account approval read failed: %s', exc, exc_info=True)
        raise PrepareError('chain_unavailable') from exc


def _mined(row) -> str:
    """'ok', 'reverted' or 'pending' after waiting up to the configured time
    for the approval's receipt. An unreadable node counts as pending."""
    deadline = time.monotonic() + _wait_seconds()
    while True:
        try:
            receipt = chain.receipt(row.signed_tx_hash)
        except Exception:  # noqa: BLE001 — not an outcome; keep waiting, then pending
            logger.warning('approval receipt read failed for %s', row.signed_tx_hash, exc_info=True)
            receipt = None
        if receipt:
            return 'ok' if receipt.get('status') == '0x1' else 'reverted'
        if time.monotonic() >= deadline:
            return 'pending'
        time.sleep(POLL_SECONDS)


def _ensure(account, *, kind: str, calldata: str, source_key: str, read) -> str:
    """Make sure a live approval exists on chain. Returns 'existing' or the
    approval's transaction hash. Raises PrepareError otherwise."""
    from .services import PrepareError
    now = int(time.time())
    if _read(*read) >= now + _min_remaining():
        return 'existing'
    source_id = f'{source_key}:{now // BUCKET_SECONDS}'
    try:
        row, _created = relayer.send_relayer_call(account, calldata, kind, source_id)
    except relayer.RelayError as exc:
        logger.warning('smart account %s not sent for %s: %s', kind, account.contract_address, exc)
        raise _error('approval_failed') from exc
    except PrepareError:
        raise
    except Exception as exc:  # noqa: BLE001 — the broadcast raised: its row stays 'signed'
        logger.exception('smart account %s broadcast failed for %s', kind, account.contract_address)
        raise _error('approval_pending') from exc
    outcome = _mined(row)
    if outcome == 'reverted':
        logger.error('smart account %s reverted for %s: %s', kind, account.contract_address, row.signed_tx_hash)
        raise _error('approval_failed')
    if outcome != 'ok':
        raise _error('approval_pending')
    # The receipt says it ran; the factory's own view must agree before a
    # batch that depends on it is handed out.
    if _read(*read) < now + _min_remaining():
        logger.error('smart account %s mined but not visible for %s', kind, account.contract_address)
        raise _error('approval_failed')
    return row.signed_tx_hash


def ensure_designation(account, beneficiary_address: str, window_seconds: int) -> str:
    """Approve setBeneficiary(beneficiary, window) on this account."""
    beneficiary_address = beneficiary_address.lower()
    return _ensure(
        account, kind='smart_designation_approval',
        calldata=abi.encode_call('approveDesignation', account.contract_address, beneficiary_address,
                                 int(window_seconds)),
        source_key=f'designation:{beneficiary_address}:{int(window_seconds)}',
        read=(chain.designation_approved_until, account.contract_address, beneficiary_address,
              int(window_seconds)))


def ensure_acceptance(account, beneficiary_address: str) -> str:
    """Approve acceptBeneficiary() by this beneficiary on this account."""
    beneficiary_address = beneficiary_address.lower()
    return _ensure(
        account, kind='smart_acceptance_approval',
        calldata=abi.encode_call('approveAcceptance', account.contract_address, beneficiary_address),
        source_key=f'acceptance:{beneficiary_address}',
        read=(chain.acceptance_approved_until, account.contract_address, beneficiary_address))
