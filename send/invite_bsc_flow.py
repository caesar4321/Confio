"""
BSC invite & send — the backend half of ConfioInviteEscrow, mirroring the
Algorand invite_send flow (blockchain/invite_send_transaction_builder.py).

An inviter locks cUSD+ or CONFIO for a phone number that isn't a Confío
user yet. Three legs:

  create   inviter's 7702 batch [token.approve(escrow, amount),
           escrow.createInvitation(inviteId, token, amount)]; a PhoneInvite
           row indexes it off-chain. inviteId = keccak(phone_key); the
           escrow namespaces storage by (inviter, inviteId) so several
           people can invite the same phone and nobody can squat an id.
  claim    when the invitee joins with a verified bsc_address, the SPONSOR
           (KMS) calls escrow.claimInvitation(inviteId, inviter, recipient)
           as a plain tx — the backend is the party that knows who the
           phone belongs to.
  reclaim  after the 7-day window, the inviter's 7702 batch
           [escrow.reclaimInvitation(inviteId)] takes it back.

Only cUSD+ and CONFIO are escrowable (the escrow's allowlist). Dark behind
BSC_INVITE_ENABLED.
"""
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

logger = logging.getLogger(__name__)

WAD = 10 ** 18


def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


SEL_APPROVE = _sel('approve(address,uint256)')
SEL_CREATE = _sel('createInvitation(bytes32,address,uint256)')
SEL_CLAIM = _sel('claimInvitation(bytes32,address,address)')
SEL_RECLAIM = _sel('reclaimInvitation(bytes32)')

GAS_CLAIM = 140_000


def _escrow() -> str:
    return (getattr(settings, 'BSC_INVITE_ESCROW_ADDRESS', '') or '').lower()


def _token_address(token_type: str) -> str:
    t = (token_type or '').upper()
    if t == 'CUSD_PLUS':
        return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()
    if t == 'CONFIO':
        return (getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', '') or '').lower()
    return ''


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def invite_id_bytes32(phone_key: str) -> str:
    """Deterministic bytes32 invite id from the canonical phone key. The
    escrow namespaces by (inviter, inviteId), so this need not include the
    inviter."""
    return '0x' + keccak(text=phone_key).hex()


def _enabled() -> bool:
    return bool(getattr(settings, 'BSC_INVITE_ENABLED', False)) and bool(_escrow())


# ── Create (inviter, 7702) ───────────────────────────────────────────────

def build_create_calls(token_type: str, amount_wei: int, invite_id32: str) -> list:
    escrow = _escrow()
    token = _token_address(token_type)
    if not token:
        raise ValueError('token not escrowable')
    return [
        {'to': token, 'value': '0',
         'data': '0x' + SEL_APPROVE + _addr_word(escrow) + _uint_word(amount_wei)},
        {'to': escrow, 'value': '0',
         'data': '0x' + SEL_CREATE + invite_id32[2:] + _addr_word(token) + _uint_word(amount_wei)},
    ]


def prepare_create(user, jwt_ctx, phone_key: str, token_type: str, amount) -> dict:
    """Build + store the create batch on a PhoneInvite row."""
    from users.models import Account
    from .models import PhoneInvite, SendTransaction

    if not _enabled():
        return {'success': False, 'error': 'bsc_invite_disabled'}
    if (token_type or '').upper() not in ('CUSD_PLUS', 'CONFIO'):
        return {'success': False, 'error': 'token_not_escrowable'}
    if not phone_key or ':' not in phone_key:
        return {'success': False, 'error': 'bad_phone_key'}

    if jwt_ctx.get('account_type') == 'business' and jwt_ctx.get('business_id'):
        acct = Account.objects.filter(
            business_id=jwt_ctx['business_id'], account_type='business',
            account_index=jwt_ctx.get('account_index', 0), deleted_at__isnull=True).first()
    else:
        acct = user.accounts.filter(
            account_type='personal', account_index=jwt_ctx.get('account_index', 0),
            deleted_at__isnull=True).first()
    inviter_addr = ((getattr(acct, 'bsc_address', None) or '') or '').lower()
    if not inviter_addr:
        return {'success': False, 'error': 'no_bsc_address'}

    try:
        amount_usd = Decimal(str(amount))
    except Exception:  # noqa: BLE001
        return {'success': False, 'error': 'invalid_amount'}
    if amount_usd <= 0:
        return {'success': False, 'error': 'invalid_amount'}
    amount_wei = int(amount_usd * WAD)

    invite_id32 = invite_id_bytes32(phone_key)
    # One active invite per (inviter, phone): the escrow rejects a duplicate
    # storage key, so mirror that off-chain.
    existing = PhoneInvite.objects.filter(
        phone_key=phone_key, inviter_user=user, status='pending',
        deleted_at__isnull=True).first()
    if existing and existing.invitation_id == invite_id32[2:]:
        return {'success': False, 'error': 'invite_already_pending'}

    calls = build_create_calls(token_type, amount_wei, invite_id32)

    invite = PhoneInvite.objects.create(
        invitation_id=invite_id32[2:],  # 64-hex, fits the field
        phone_key=phone_key,
        phone_number='',
        inviter_user=user,
        amount=amount_usd,
        token_type=token_type.upper(),
        status='pending',
    )
    invite.blockchain_calls = json.dumps({'calls': calls, 'kind': 'invite_create',
                                          'inviter': inviter_addr})
    # blockchain_calls is a transient attr the mutation reads; the row's
    # authority is invitation_id + phone_key (the batch is reconstructible).
    return {
        'success': True,
        'invite_id': invite_id32,
        'calls': calls,
        'inviter': inviter_addr,
        'phone_invite_pk': invite.pk,
    }


def _validate_create_batch(calls: list, token_type: str, invite_id32: str) -> None:
    from cusd_plus.sponsor_7702 import PolicyError
    escrow = _escrow()
    token = _token_address(token_type)
    if len(calls) != 2:
        raise PolicyError('bad_batch_size')
    approve, create = calls
    if (approve.get('to') or '').lower() != token or (create.get('to') or '').lower() != escrow:
        raise PolicyError('destination_not_allowed')
    a = (approve.get('data') or '').lower()
    c = (create.get('data') or '').lower()
    if a[2:10] != SEL_APPROVE or a[10:74] != _addr_word(escrow):
        raise PolicyError('bad_calldata')
    approved = a[74:138]
    if (c[2:10] != SEL_CREATE or c[10:74] != invite_id32[2:].lower()
            or c[74:138] != _addr_word(token) or c[138:202] != approved):
        raise PolicyError('bad_calldata')


def submit_create(user, phone_invite, nonce, deadline, intent_signature, authorization=None) -> dict:
    from cusd_plus import sponsor_7702
    from .models import PhoneInvite

    if phone_invite.inviter_user_id != user.id or phone_invite.status != 'pending':
        return {'success': False, 'error': 'invite_not_pending'}

    acct = user.accounts.filter(
        account_type='personal', account_index=0, deleted_at__isnull=True).first()
    inviter_addr = ((getattr(acct, 'bsc_address', None) or '') or '').lower()
    invite_id32 = '0x' + phone_invite.invitation_id
    calls = build_create_calls(phone_invite.token_type, int(Decimal(phone_invite.amount) * WAD), invite_id32)
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    try:
        _validate_create_batch(calls, phone_invite.token_type, invite_id32)
        digest = sponsor_7702.intent_digest(calls, int(nonce), int(deadline), inviter_addr, chain_id)
        if sponsor_7702.recover_intent_signer(digest, intent_signature) != inviter_addr:
            return {'success': False, 'error': 'bad_intent_signature'}
        auth_dict = None
        if not sponsor_7702.is_delegated(inviter_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required', 'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(authorization, inviter_addr, chain_id)
        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, inviter_addr, calls, int(nonce), int(deadline), intent_signature, auth_dict, 'invite_create')
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception('[INVITE][BSC] create failed for %s', phone_invite.invitation_id)
        return {'success': False, 'error': str(exc)[:200]}

    from django.utils import timezone
    from datetime import timedelta
    phone_invite.expires_at = timezone.now() + timedelta(days=7)
    phone_invite.save(update_fields=['expires_at', 'updated_at'])
    return {'success': True, 'transaction_hash': tx_hash}


# ── Claim (sponsor, plain KMS tx) ────────────────────────────────────────

def claim_for_recipient(phone_invite, recipient_user) -> dict:
    """Called when the invitee joins (verified). The KMS sponsor releases
    the escrow to their bsc_address."""
    from cusd_plus.sponsor_7702 import (
        _rpc, acquire_sponsor_nonce_lock, release_sponsor_nonce_lock,
    )
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

    if not _enabled():
        return {'success': False, 'error': 'bsc_invite_disabled'}
    if phone_invite.status != 'pending':
        return {'success': False, 'error': 'invite_not_pending'}

    inviter_acct = phone_invite.inviter_user.accounts.filter(
        account_type='personal', account_index=0, deleted_at__isnull=True).first()
    inviter_addr = ((getattr(inviter_acct, 'bsc_address', None) or '') or '').lower()
    rec_acct = recipient_user.accounts.filter(
        account_type='personal', account_index=0, deleted_at__isnull=True).first()
    recipient_addr = ((getattr(rec_acct, 'bsc_address', None) or '') or '').lower()
    if not inviter_addr or not recipient_addr:
        return {'success': False, 'error': 'missing_bsc_address'}
    if recipient_addr == inviter_addr:
        return {'success': False, 'error': 'recipient_is_inviter'}

    escrow = _escrow()
    invite_id32 = phone_invite.invitation_id
    calldata = '0x' + SEL_CLAIM + invite_id32 + _addr_word(inviter_addr) + _addr_word(recipient_addr)
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    signer = get_bsc_sponsor_signer_from_settings()
    sponsor = signer.address
    try:
        _rpc('eth_call', [{'from': sponsor, 'to': escrow, 'data': calldata}, 'latest'])
    except Exception as exc:  # noqa: BLE001
        logger.warning('[INVITE][BSC] claim simulation reverted %s: %s', invite_id32, exc)
        return {'success': False, 'error': 'simulation_reverted'}

    gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                    int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))
    price_cap = int(getattr(settings, 'CUSD_PLUS_7702_MAX_GAS_PRICE_WEI', 5_000_000_000))
    if gas_price > price_cap:
        return {'success': False, 'error': 'gas_price_too_high'}
    fee_per_gas = min((gas_price * 12) // 10, price_cap)

    if not acquire_sponsor_nonce_lock():
        return {'success': False, 'error': 'sponsor_busy'}
    try:
        nonce = int(_rpc('eth_getTransactionCount', [sponsor, 'pending']), 16)
        tx = {'type': 2, 'chainId': chain_id, 'nonce': nonce,
              'maxPriorityFeePerGas': fee_per_gas, 'maxFeePerGas': fee_per_gas,
              'gas': GAS_CLAIM, 'to': to_checksum_address(escrow), 'value': 0,
              'data': calldata, 'accessList': []}
        raw, tx_hash = signer.sign_typed_transaction(tx)
        sent = _rpc('eth_sendRawTransaction', [raw])
    except Exception as exc:  # noqa: BLE001
        logger.exception('[INVITE][BSC] claim broadcast failed %s', invite_id32)
        return {'success': False, 'error': str(exc)[:200]}
    finally:
        release_sponsor_nonce_lock()

    from django.utils import timezone
    phone_invite.status = 'claimed'
    phone_invite.claimed_by = recipient_user
    phone_invite.claimed_txid = sent or tx_hash
    phone_invite.claimed_at = timezone.now()
    phone_invite.save(update_fields=['status', 'claimed_by', 'claimed_txid', 'claimed_at', 'updated_at'])
    return {'success': True, 'transaction_hash': sent or tx_hash}


def claim_pending_bsc_invites(recipient_user, phone_key: str) -> int:
    """Release every pending BSC-token invite addressed to `phone_key` to
    the newly-verified user. Called from the phone-verification auto-claim.
    Returns the number claimed. Best-effort — never raises into onboarding.
    """
    from .models import PhoneInvite

    if not _enabled() or not phone_key:
        return 0
    claimed = 0
    pending = PhoneInvite.objects.filter(
        phone_key=phone_key, status='pending',
        token_type__in=('CUSD_PLUS', 'CONFIO'), deleted_at__isnull=True,
    )
    for inv in pending:
        try:
            res = claim_for_recipient(inv, recipient_user)
            if res.get('success'):
                claimed += 1
            else:
                logger.info('[INVITE][BSC] auto-claim skipped %s: %s',
                            inv.invitation_id, res.get('error'))
        except Exception:  # noqa: BLE001 — onboarding must not fail on this
            logger.exception('[INVITE][BSC] auto-claim errored %s', inv.invitation_id)
    return claimed


# ── Reclaim (inviter, 7702) ──────────────────────────────────────────────

def build_reclaim_calls(invite_id32: str) -> list:
    return [{'to': _escrow(), 'value': '0', 'data': '0x' + SEL_RECLAIM + invite_id32[2:]}]


def submit_reclaim(user, phone_invite, nonce, deadline, intent_signature, authorization=None) -> dict:
    from cusd_plus import sponsor_7702

    if phone_invite.inviter_user_id != user.id or phone_invite.status != 'pending':
        return {'success': False, 'error': 'invite_not_reclaimable'}

    acct = user.accounts.filter(
        account_type='personal', account_index=0, deleted_at__isnull=True).first()
    inviter_addr = ((getattr(acct, 'bsc_address', None) or '') or '').lower()
    calls = build_reclaim_calls('0x' + phone_invite.invitation_id)
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    try:
        digest = sponsor_7702.intent_digest(calls, int(nonce), int(deadline), inviter_addr, chain_id)
        if sponsor_7702.recover_intent_signer(digest, intent_signature) != inviter_addr:
            return {'success': False, 'error': 'bad_intent_signature'}
        auth_dict = None
        if not sponsor_7702.is_delegated(inviter_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required', 'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(authorization, inviter_addr, chain_id)
        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, inviter_addr, calls, int(nonce), int(deadline), intent_signature, auth_dict, 'invite_reclaim')
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception('[INVITE][BSC] reclaim failed %s', phone_invite.invitation_id)
        return {'success': False, 'error': str(exc)[:200]}

    from django.utils import timezone
    phone_invite.status = 'reclaimed'
    phone_invite.save(update_fields=['status', 'updated_at'])
    return {'success': True, 'transaction_hash': tx_hash}
