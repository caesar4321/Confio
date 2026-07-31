"""
BSC send flow — sponsored EIP-7702 batches moving the BSC dollar between
Confío users or to external addresses. Phase 2 of the cUSD phase-out: the
transactional sibling of the savings rail (presale/bsc_flow.py shape).

Two-step, server-authoritative:

  prepare_bsc_send   resolve the recipient (user id → phone → raw 0x, the
                     same priority as the Algorand rail), pick the funding
                     source and call shape (A/B/C below), store the EXACT
                     call batch on the SendTransaction row. The client only
                     ever signs what the server stored.
  submit_bsc_send    recompute the EIP-712 digest from the STORED calls,
                     verify the sender's signature, byte-exact-revalidate
                     the batch, then broadcast via send_sponsored_batch.
                     A Celery task resolves the receipt into
                     CONFIRMED/FAILED, writes ledger movements and fires
                     SEND_SENT / SEND_RECEIVED.

Call shapes (server decides at prepare; A–C are the dollar-value send where
the CLIENT names no token, D–E honor an explicit token request from the
"Enviar con dirección" sheet):
  A  sender holds cUSD+, recipient ELIGIBLE Confío user
        [vault.transfer(recipient, shares)]                 kind=send_cusd_plus
  B  sender holds cUSD+, recipient ineligible OR external
        [vault.redeemToUsdt(shares, minOut, recipient)]     kind=send_redeem
  C  sender holds raw USDT
        [USDT.transfer(recipient, wei)]                     kind=send_usdt
  D  token='CUSD_PLUS': the sender chose the TOKEN, not just the value —
     the recipient gets cUSD+ itself at any address, no eligibility fork
     (a transfer of the sender's position is an exit; the geo gate covers
     only the MINT). Shares-funded only.
        [vault.transfer(recipient, shares)]                 kind=send_cusd_plus
  E  token='CONFIO': plain BEP-20 transfer. `amount` is a CONFIO count,
     not USD.
        [CONFIO.transfer(recipient, wei)]                   kind=send_confio

No geo gate anywhere in this module: sends are EXITS from the sender's
position and never gated (house rule). An eligible recipient receiving
USDT auto-mints via the existing savings resume; an ineligible recipient
simply keeps what arrives.

Recipient coverage: bsc_address is client-registered (the server cannot
derive it), so a recipient who hasn't opened a post-EVM app version has no
on-chain destination. Locked decision (Julian, 2026-07-30): BLOCK the send
and notify BOTH sides — the recipient push is what drives registration.
"""
import json
import logging
import re
import time
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

WAD = 10 ** 18
# minOut tolerance for redeem sends: pPlus only rises, but the prepared
# share count meets a slightly newer price at execution — 0.5% absorbs any
# realistic drift while still bounding what the recipient could lose.
REDEEM_MIN_OUT_BPS = 9_950
EVM_ADDR_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def _vault_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()


def _confio_token_address() -> str:
    return (getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', '') or '').lower()


def _display_name(user) -> str:
    return (user.get_full_name() or user.username or user.email or 'Contacto')


def _notify_recipient_needs_app(recipient_user, sender_user) -> None:
    """The adoption loop for the coverage cold-start: opening the app IS the
    registration (ensureBscAddressRegistered fires on every authenticated
    entry), so the push is the fix, not just an apology."""
    try:
        from notifications import utils as notif_utils
        from notifications.models import NotificationType as NotifType
        notif_utils.create_notification(
            user=recipient_user,
            account=None,
            business=None,
            notification_type=NotifType.SEND_RECEIVED,
            title='Alguien quiere enviarte dólares',
            message=(
                f'{_display_name(sender_user)} intentó enviarte dinero. '
                'Abre Confío para activar tu cuenta y poder recibirlo.'
            ),
            data={'transaction_type': 'send_blocked', 'reason': 'no_bsc_address'},
        )
    except Exception:  # noqa: BLE001 — the nudge must not mask the error
        logger.exception('recipient-needs-app notification failed')


def _resolve_recipient(recipient_user_id, recipient_phone, recipient_address):
    """Mirror of the Algorand rail's priority (blockchain/mutations.py):
    user id → phone (digits-only exact) → raw 0x address. Returns
    (recipient_user|None, recipient_business|None, bsc_address|None, error|None).
    recipient_user is set for internal recipients even when their address is
    missing — the caller needs it to send the activation nudge."""
    from django.contrib.auth import get_user_model
    from users.models import Account
    User = get_user_model()

    if recipient_user_id:
        try:
            recipient_user = User.objects.get(id=recipient_user_id)
        except User.DoesNotExist:
            return None, None, None, 'recipient_not_found'
        account = recipient_user.accounts.filter(
            account_type='personal', account_index=0).first()
        addr = (getattr(account, 'bsc_address', None) or '').lower() if account else ''
        return recipient_user, None, (addr or None), None

    if recipient_phone:
        cleaned = ''.join(filter(str.isdigit, recipient_phone))
        found = User.objects.filter(phone_number=cleaned).first()
        if not found:
            # Non-Confío phone: the invite flow is a separate product
            # (Algorand invite-send today; BSC invites are a follow-up).
            return None, None, None, 'recipient_not_on_confio'
        account = found.accounts.filter(account_type='personal', account_index=0).first()
        addr = (getattr(account, 'bsc_address', None) or '').lower() if account else ''
        return found, None, (addr or None), None

    if recipient_address:
        if not EVM_ADDR_RE.match(recipient_address):
            return None, None, None, 'invalid_recipient_address'
        addr = recipient_address.lower()
        # Reverse lookup for display + internal-recipient notifications.
        match = Account.objects.filter(bsc_address__iexact=addr).select_related(
            'user', 'business').first()
        if match:
            return match.user, match.business, addr, None
        return None, None, addr, None

    return None, None, None, 'recipient_required'


def prepare_bsc_send(user, jwt_ctx, amount, recipient_user_id=None,
                     recipient_phone=None, recipient_address=None,
                     memo: str = '', idempotency_key: str = '',
                     token: str = '') -> dict:
    """Build and store the send. `jwt_ctx` is the validated JWT business
    context (send_funds already enforced by the mutation). `token` empty =
    dollar-value send (shapes A–C); 'CUSD_PLUS'/'CONFIO' = the explicit
    token shapes D/E."""
    from cusd_plus import vault as cp_vault
    from cusd_plus.eligibility import is_ondo_eligible
    from cusd_plus.sponsor_7702 import (
        SEL_REDEEM_TO_USDT,
        SEL_TRANSFER,
        USDT_BSC,
    )
    from users.models import Account
    from .models import SendTransaction

    vault_addr = _vault_address()
    if not vault_addr:
        return {'success': False, 'error': 'vault_not_configured'}
    if not getattr(settings, 'BSC_SEND_ENABLED', False):
        return {'success': False, 'error': 'bsc_send_disabled'}

    # Sender account from the JWT context only (house rule).
    if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
        sender_account = Account.objects.filter(
            business_id=jwt_ctx['business_id'], account_type='business',
            account_index=jwt_ctx.get('account_index', 0)).first()
        sender_business = sender_account.business if sender_account else None
    else:
        sender_account = user.accounts.filter(
            account_type='personal', account_index=jwt_ctx.get('account_index', 0)).first()
        sender_business = None
    sender_addr = (getattr(sender_account, 'bsc_address', None) or '').lower()
    if not sender_addr:
        return {'success': False, 'error': 'no_bsc_address'}

    # Idempotent replay: same sender + key returns the prepared row.
    if idempotency_key:
        existing = SendTransaction.objects.filter(
            sender_user=user, idempotency_key=idempotency_key,
            deleted_at__isnull=True,
        ).first()
        if existing and existing.bsc_calls_json:
            return {
                'success': True,
                'send_id': existing.internal_id,
                'calls': json.loads(existing.bsc_calls_json),
                'token_type': existing.token_type,
            }

    try:
        amount_usd = Decimal(str(amount))
    except Exception:  # noqa: BLE001
        return {'success': False, 'error': 'invalid_amount'}
    if amount_usd <= 0:
        return {'success': False, 'error': 'invalid_amount'}

    recipient_user, recipient_business, recipient_addr, err = _resolve_recipient(
        recipient_user_id, recipient_phone, recipient_address)
    if err:
        return {'success': False, 'error': err}
    if recipient_user is not None and recipient_user.id == user.id and not recipient_business:
        return {'success': False, 'error': 'self_send_not_allowed'}
    if not recipient_addr:
        # Internal recipient without a registered address: BLOCK + nudge
        # (locked decision — no dual-rail, no escrow).
        if recipient_user is not None:
            _notify_recipient_needs_app(recipient_user, user)
        return {'success': False, 'error': 'recipient_no_bsc_address'}

    amount_wei = int(amount_usd * WAD)

    requested = (token or '').upper()
    if requested and requested not in ('CUSD_PLUS', 'CONFIO'):
        return {'success': False, 'error': 'unsupported_token'}

    if requested == 'CONFIO':
        # E: plain BEP-20 transfer of the governance/utility token.
        confio_addr = _confio_token_address()
        if not confio_addr:
            return {'success': False, 'error': 'confio_not_configured'}
        try:
            confio_raw = cp_vault.erc20_balance_raw(confio_addr, sender_addr)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[SEND][BSC] balance rpc failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}
        if confio_raw < amount_wei:
            return {'success': False, 'error': 'insufficient_balance'}
        kind = 'send_confio'
        token_type = 'CONFIO'
        calls = [{
            'to': confio_addr, 'value': '0',
            'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr) + _uint_word(amount_wei),
        }]
    else:
        # Funding source: prefer the yield position; raw USDT is the fallback.
        try:
            pps_wad = cp_vault.p_plus_wad()
            shares_raw = cp_vault.erc20_balance_raw(vault_addr, sender_addr)
            shares_value_wei = (shares_raw * pps_wad) // WAD
            usdt_raw = cp_vault.usdt_balance_raw(sender_addr, fresh=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[SEND][BSC] balance rpc failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}

        if requested == 'CUSD_PLUS':
            # D: explicit cUSD+ token send — shares-funded only, delivered
            # as-is to ANY recipient (no eligibility fork; exits and
            # transfers of an existing position are never gated).
            if shares_value_wei < amount_wei:
                return {'success': False, 'error': 'insufficient_balance'}
            shares = (amount_wei * WAD) // pps_wad
            if shares <= 0:
                return {'success': False, 'error': 'invalid_amount'}
            kind = 'send_cusd_plus'
            token_type = 'CUSD_PLUS'
            calls = [{
                'to': vault_addr, 'value': '0',
                'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr) + _uint_word(shares),
            }]
        elif shares_value_wei >= amount_wei:
            # Value → shares at the live price; floor favors the sender's
            # remaining balance (never over-burn).
            shares = (amount_wei * WAD) // pps_wad
            if shares <= 0:
                return {'success': False, 'error': 'invalid_amount'}
            recipient_eligible = (
                recipient_user is not None
                and recipient_business is None
                and is_ondo_eligible(recipient_user)
            )
            if recipient_eligible:
                kind = 'send_cusd_plus'
                token_type = 'CUSD_PLUS'
                calls = [{
                    'to': vault_addr, 'value': '0',
                    'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr) + _uint_word(shares),
                }]
            else:
                # Ineligible or external: deliver USDT atomically (burn + IM
                # redeem + transfer in one vault call). An exit — never gated.
                kind = 'send_redeem'
                token_type = 'USDT'
                min_out = (amount_wei * REDEEM_MIN_OUT_BPS) // 10_000
                calls = [{
                    'to': vault_addr, 'value': '0',
                    'data': '0x' + SEL_REDEEM_TO_USDT + _uint_word(shares)
                            + _uint_word(min_out) + _addr_word(recipient_addr),
                }]
        elif usdt_raw >= amount_wei:
            kind = 'send_usdt'
            token_type = 'USDT'
            calls = [{
                'to': USDT_BSC, 'value': '0',
                'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr) + _uint_word(amount_wei),
            }]
        else:
            return {'success': False, 'error': 'insufficient_balance'}

    recipient_display = ''
    recipient_phone_val = ''
    if recipient_business is not None:
        recipient_display = recipient_business.name
    elif recipient_user is not None:
        recipient_display = _display_name(recipient_user)
        recipient_phone_val = recipient_user.phone_number or ''

    send_tx = SendTransaction.objects.create(
        sender_user=user,
        sender_business=sender_business,
        sender_type='business' if sender_business else 'user',
        sender_display_name=(
            sender_business.name if sender_business else _display_name(user)),
        sender_phone=user.phone_number or '',
        recipient_user=recipient_user,
        recipient_business=recipient_business,
        recipient_type=(
            'business' if recipient_business else
            'user' if recipient_user else 'external'),
        recipient_display_name=recipient_display,
        recipient_phone=recipient_phone_val,
        sender_address=sender_addr,
        recipient_address=recipient_addr,
        amount=amount_usd,
        token_type=token_type,
        memo=(memo or '')[:500],
        status='PENDING',
        idempotency_key=idempotency_key or None,
        bsc_calls_json=json.dumps({'calls': calls, 'kind': kind}),
    )
    # Unified row arrives via the existing post_save signal
    # (users/signals.py create_unified_transaction_from_send).

    return {
        'success': True,
        'send_id': send_tx.internal_id,
        'calls': calls,
        'token_type': token_type,
    }


def _validate_send_batch(calls: list, send_tx) -> None:
    """Defense in depth on the STORED batch (the client never resends calls
    — it can only sign what prepare stored): a single zero-value call to
    the vault or USDT whose recipient word matches the stored recipient."""
    from cusd_plus.sponsor_7702 import (
        PolicyError,
        SEL_REDEEM_TO_USDT,
        SEL_TRANSFER,
        USDT_BSC,
    )

    vault = _vault_address()
    if len(calls) != 1:
        raise PolicyError('bad_batch_size')
    call = calls[0]
    to = (call.get('to') or '').lower()
    if send_tx.token_type == 'CONFIO':
        # Shape E rows may ONLY move the CONFIO token.
        confio = _confio_token_address()
        if not confio or to != confio:
            raise PolicyError('destination_not_allowed')
    elif to not in (vault, USDT_BSC):
        raise PolicyError('destination_not_allowed')
    if int(call.get('value') or 0) != 0:
        raise PolicyError('value_not_allowed')
    data = (call.get('data') or '').lower()
    if not data.startswith('0x'):
        raise PolicyError('bad_calldata')
    selector = data[2:10]
    recipient_word = _addr_word(send_tx.recipient_address)
    if selector == SEL_TRANSFER:
        if len(data) != 2 + 8 + 128 or data[10:74] != recipient_word:
            raise PolicyError('bad_calldata')
    elif selector == SEL_REDEEM_TO_USDT:
        if to != vault or len(data) != 2 + 8 + 192 or data[138:202] != recipient_word:
            raise PolicyError('bad_calldata')
    else:
        raise PolicyError('selector_not_allowed')


def submit_bsc_send(user, send_tx, nonce, deadline, intent_signature,
                    authorization=None) -> dict:
    from cusd_plus import sponsor_7702

    if send_tx.sender_user_id != user.id:
        return {'success': False, 'error': 'not_your_send'}
    if send_tx.status != 'PENDING' or not send_tx.bsc_calls_json:
        return {'success': False, 'error': 'send_not_pending'}

    sender_addr = (send_tx.sender_address or '').lower()
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    meta = json.loads(send_tx.bsc_calls_json or '{}')
    kind = meta.get('kind') or 'send_usdt'
    calls = meta.get('calls') or []

    try:
        _validate_send_batch(calls, send_tx)

        digest = sponsor_7702.intent_digest(
            calls, int(nonce), int(deadline), sender_addr, chain_id)
        signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
        if signer != sender_addr:
            return {'success': False, 'error': 'bad_intent_signature'}

        auth_dict = None
        if not sponsor_7702.is_delegated(sender_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required',
                        'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(
                authorization, sender_addr, chain_id)

        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, sender_addr, calls, int(nonce), int(deadline),
            intent_signature, auth_dict, kind, source_id=send_tx.id)
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
        logger.exception('[SEND][BSC] sponsored send failed for %s', send_tx.internal_id)
        return {'success': False, 'error': str(exc)[:200]}

    send_tx.transaction_hash = tx_hash
    send_tx.status = 'SUBMITTED'
    send_tx.save(update_fields=['transaction_hash', 'status', 'updated_at'])

    # Balance caches just changed for the sender (and the recipient, for
    # internal sends) — drop the fresh-read keys.
    try:
        from cusd_plus.vault import invalidate_position
        invalidate_position(sender_addr)
        invalidate_position(send_tx.recipient_address or '')
    except Exception:  # noqa: BLE001
        pass

    from .tasks import confirm_bsc_send
    confirm_bsc_send.apply_async(args=[send_tx.id, batch.id], countdown=8)

    return {'success': True, 'transaction_hash': tx_hash}
