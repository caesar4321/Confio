"""
BSC invite & send — the backend half of ConfioInviteEscrow, mirroring the
Algorand invite_send flow (blockchain/invite_send_transaction_builder.py).

An inviter locks cUSD+, cUSD or CONFIO for a phone number that isn't a Confío
user yet. Three legs:

  create   inviter's 7702 batch [token.approve(escrow, amount),
           escrow.createInvitation(inviteId, token, amount)]; a PhoneInvite
           row indexes it off-chain. inviteId = keccak(phone_key); the
           escrow namespaces storage by (inviter, inviteId) so several
           people can invite the same phone and nobody can squat an id.
  claim    when the invitee joins with a verified bsc_address, the SPONSOR
           (KMS) calls the eligibility-aware claimInvitation; the escrow
           converts cUSD+ <-> cUSD internally when required.
           as a plain tx — the backend is the party that knows who the
           phone belongs to.
  reclaim  after the 7-day window, the inviter's 7702 batch
           [escrow.reclaimInvitation(inviteId)] takes it back.

Only cUSD+, cUSD and CONFIO are escrowable (the escrow's allowlist). Dark behind
BSC_INVITE_ENABLED.
"""
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

logger = logging.getLogger(__name__)

WAD = 10 ** 18
INTERNAL_CONVERSION_MIN_OUT_BPS = 9_950


def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


SEL_APPROVE = _sel('approve(address,uint256)')
SEL_CREATE = _sel('createInvitation(bytes32,address,uint256)')
SEL_CLAIM = _sel('claimInvitation(bytes32,address,address,bool,uint256)')
SEL_RECLAIM = _sel('reclaimInvitation(bytes32)')

# A cross-eligibility claim can unwrap cUSD+ through Ondo and mint cUSD, or
# perform the inverse wrapper conversion. 140k only covered the old plain
# ERC-20 transfer claim and would make the new atomic claim under-gassed.
GAS_CLAIM = 750_000


def _escrow() -> str:
    return (getattr(settings, 'BSC_INVITE_ESCROW_ADDRESS', '') or '').lower()


def _token_address(token_type: str) -> str:
    t = (token_type or '').upper()
    if t == 'CUSD_PLUS':
        return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()
    if t == 'CUSD':
        return (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()
    if t == 'CONFIO':
        return (getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', '') or '').lower()
    return ''


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def invite_id_bytes32(phone_key: str, inviter_addr: str) -> str:
    """Deterministic bytes32 invite id from the canonical phone key AND the
    inviter.

    The escrow namespaces storage by (inviter, inviteId), so on-chain the
    inviter is redundant here. Off-chain it is not: PhoneInvite.invitation_id
    is unique, so a phone-only id makes the SECOND person to invite the same
    number collide on insert. Bind the inviter and both rows coexist, which is
    the behaviour the escrow was designed for.

    Nothing looks an invite up by phone alone — the invitee's auto-claim scans
    PhoneInvite rows by phone_key and reads the id off the row.
    """
    return '0x' + keccak(text=f'{phone_key}:{inviter_addr.lower()}').hex()


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


def _stored_create_calls(phone_invite) -> list:
    """Return the exact token units prepared for this invite.

    cUSD+ is an accumulating share, so its escrow units cannot be rebuilt
    later from the displayed dollar amount.  New prepares persist the exact
    batch on SendTransaction; funded legacy rows also have it from submit.
    """
    raw = getattr(getattr(phone_invite, 'send_transaction', None),
                  'bsc_calls_json', '') or ''
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        calls = payload.get('calls') or []
        return calls if isinstance(calls, list) else []
    except (TypeError, ValueError):
        return []


def _locked_units(phone_invite) -> int:
    calls = _stored_create_calls(phone_invite)
    if len(calls) == 2:
        data = (calls[1].get('data') or '').lower()
        if data[2:10] == SEL_CREATE and len(data) >= 202:
            return int(data[138:202], 16)
    # Compatibility for old draft rows that predate exact-batch persistence.
    return int(Decimal(phone_invite.amount) * WAD)


def _token_units_for_dollars(token_type: str, amount_wei: int) -> int:
    if token_type != 'CUSD_PLUS':
        return amount_wei
    from cusd_plus.vault import p_plus_wad
    pps = p_plus_wad(fresh=True)
    if pps <= 0:
        raise ValueError('invalid share price')
    return -(-amount_wei * WAD // pps)


def _claim_min_amount_out(phone_invite, recipient_eligible: bool) -> int:
    locked_units = _locked_units(phone_invite)
    if phone_invite.token_type == 'CUSD' and recipient_eligible:
        from cusd_plus.vault import current_oracle_price_wad
        oracle_price = current_oracle_price_wad(fresh=True)
        if oracle_price <= 0:
            raise ValueError('invalid oracle price')
        expected_usdy = locked_units * WAD // oracle_price
        return expected_usdy * INTERNAL_CONVERSION_MIN_OUT_BPS // 10_000
    if phone_invite.token_type == 'CUSD_PLUS' and not recipient_eligible:
        from cusd_plus.vault import (
            last_oracle_price_wad, p_plus_wad, redeem_gross_usdt_out,
        )
        predicted = redeem_gross_usdt_out(
            locked_units,
            p_plus_wad(fresh=True),
            last_oracle_price_wad(fresh=True),
        )
        return predicted * INTERNAL_CONVERSION_MIN_OUT_BPS // 10_000
    return 0


def prepare_create(user, jwt_ctx, phone_key: str, token_type: str, amount,
                   phone_display: str = '') -> dict:
    """Build + store the create batch on a PhoneInvite row."""
    from cusd_plus import sponsor_7702
    from users.models import Account
    from .models import PhoneInvite, SendTransaction

    if not _enabled():
        return {'success': False, 'error': 'bsc_invite_disabled'}
    requested_token = (token_type or '').upper()
    if requested_token not in ('CUSD_PLUS', 'CUSD', 'CONFIO'):
        return {'success': False, 'error': 'token_not_escrowable'}
    if not phone_key or ':' not in phone_key:
        return {'success': False, 'error': 'bad_phone_key'}

    sender_business = None
    if jwt_ctx.get('account_type') == 'business' and jwt_ctx.get('business_id'):
        acct = Account.objects.filter(
            business_id=jwt_ctx['business_id'], account_type='business',
            account_index=jwt_ctx.get('account_index', 0), deleted_at__isnull=True).first()
        sender_business = getattr(acct, 'business', None)
    else:
        acct = user.accounts.filter(
            account_type='personal', account_index=jwt_ctx.get('account_index', 0),
            deleted_at__isnull=True).first()
    inviter_addr = ((getattr(acct, 'bsc_address', None) or '') or '').lower()
    if not inviter_addr:
        return {'success': False, 'error': 'no_bsc_address'}

    # "Dollars" are one product in the app, but the sender's actual BSC
    # representation is jurisdiction-dependent. Legacy builds always submit
    # CUSD_PLUS here, so trusting the client label would try to lock shares an
    # ineligible sender does not own. Select the canonical asset server-side;
    # the claim converts it fee-free if the eventual recipient belongs on the
    # other side of the cUSD/cUSD+ boundary.
    if requested_token in ('CUSD_PLUS', 'CUSD'):
        from cusd_plus.eligibility import is_ondo_eligible
        token_type = 'CUSD_PLUS' if is_ondo_eligible(user) else 'CUSD'
    else:
        token_type = 'CONFIO'

    try:
        amount_usd = Decimal(str(amount))
    except Exception:  # noqa: BLE001
        return {'success': False, 'error': 'invalid_amount'}
    if amount_usd <= 0:
        return {'success': False, 'error': 'invalid_amount'}
    amount_wei = int(amount_usd * WAD)
    try:
        token_units = _token_units_for_dollars(token_type, amount_wei)
    except ValueError:
        return {'success': False, 'error': 'invalid_share_price'}

    invite_id32 = invite_id_bytes32(phone_key, inviter_addr)
    digits = ''.join(ch for ch in (phone_display or '') if ch.isdigit())

    # The invite id is deterministic in (phone, inviter) and the escrow never
    # deletes a settled slot, so this row is the ONE row that id will ever
    # have. What happens on a repeat prepare depends on where the last attempt
    # got to (Codex audit 2026-08-02 P1/P2):
    #
    #   draft            nothing was ever broadcast → recycle it, new terms.
    #   failed           the create never executed, so the escrow's mapping
    #                    slot is EMPTY and this id is still usable → recycle.
    #   creating         a batch is in flight; recycling would let a second
    #                    batch fund the same slot and strand the first.
    #   funded/settled   the escrow holds (or held) money under this id. A
    #                    fresh create would revert on-chain with 'invite
    #                    exists', so refuse honestly rather than take a
    #                    signature for a transaction that cannot succeed.
    existing = PhoneInvite.objects.filter(
        rail='bsc', invitation_id=invite_id32[2:],
        deleted_at__isnull=True).select_related('send_transaction').first()
    if existing is not None and existing.status not in ('draft', 'failed'):
        if existing.status in ('claimed', 'reclaimed'):
            # The slot is spent on-chain and the id cannot be reused. Say so
            # in its own terms — 'already pending' would be a lie.
            return {'success': False, 'error': 'invite_id_spent'}
        return {'success': False, 'error': 'invite_already_pending'}

    calls = build_create_calls(token_type, token_units, invite_id32)
    stored_batch = json.dumps({
        'calls': calls, 'kind': 'invite_create', 'inviter': inviter_addr,
    })

    # The history row, created BEFORE the batch is signed (bsc_flow.py does the
    # same for sends). Without it the money leaves for the escrow and the
    # sender sees nothing in their history — and the reclaim button, which the
    # app renders off this row's is_invitation/invitation_expires_at, could
    # never appear, so an unclaimed invite would be unrecoverable.
    if existing is not None:
        invite = existing
        send_tx = invite.send_transaction
        send_tx.amount = amount_usd
        send_tx.token_type = token_type.upper()
        send_tx.recipient_display_name = phone_display or phone_key
        send_tx.recipient_phone = phone_display or ''
        send_tx.sender_address = inviter_addr
        send_tx.recipient_address = _escrow()
        send_tx.sender_business = sender_business
        send_tx.sender_type = 'business' if sender_business else 'user'
        send_tx.bsc_calls_json = stored_batch
        send_tx.sender_display_name = (
            sender_business.name if sender_business else (user.get_full_name() or user.username))
        send_tx.save(update_fields=[
            'amount', 'token_type', 'recipient_display_name', 'recipient_phone',
            'sender_address', 'recipient_address', 'sender_business',
            'sender_type', 'sender_display_name', 'bsc_calls_json', 'updated_at'])
        invite.amount = amount_usd
        invite.token_type = token_type.upper()
        invite.phone_number = digits
        invite.inviter_address = inviter_addr
        # A recycled 'failed' row starts a fresh attempt from 'draft', and its
        # history row goes back to PENDING (save(), so the unified row follows).
        invite.status = 'draft'
        invite.save(update_fields=['amount', 'token_type', 'phone_number',
                                   'inviter_address', 'status', 'updated_at'])
        if send_tx.status == 'FAILED':
            send_tx.status = 'PENDING'
            send_tx.error_message = ''
            send_tx.transaction_hash = None
            send_tx.save(update_fields=['status', 'error_message',
                                        'transaction_hash', 'updated_at'])
    else:
        # Attribution follows the account that SIGNS, exactly as bsc_flow.py
        # does for sends. A business invite filed under the personal account
        # disappears from business history — and the reclaim button with it,
        # which is the inviter's only way to get the money back.
        send_tx = SendTransaction.objects.create(
            sender_user=user,
            sender_business=sender_business,
            sender_type='business' if sender_business else 'user',
            sender_display_name=(
                sender_business.name if sender_business
                else (user.get_full_name() or user.username)),
            sender_phone=user.phone_number or '',
            recipient_type='external',
            recipient_display_name=phone_display or phone_key,
            recipient_phone=phone_display or '',
            sender_address=inviter_addr,
            recipient_address=_escrow(),
            amount=amount_usd,
            token_type=token_type.upper(),
            status='PENDING',
            is_invitation=True,
            invitation_claimed=False,
            invitation_reverted=False,
            idempotency_key=invite_id32[2:],
            bsc_calls_json=stored_batch,
        )
        invite = PhoneInvite.objects.create(
            rail='bsc',
            invitation_id=invite_id32[2:],  # 64-hex, fits the field
            phone_key=phone_key,
            phone_number=digits,
            inviter_user=user,
            inviter_address=inviter_addr,
            send_transaction=send_tx,
            amount=amount_usd,
            token_type=token_type.upper(),
            status='draft',
        )
    invite.blockchain_calls = stored_batch
    # blockchain_calls is a transient attr the mutation reads; the row's
    # authority is invitation_id + phone_key (the batch is reconstructible).
    return {
        'success': True,
        'invite_id': invite_id32,
        'calls': calls,
        'inviter': inviter_addr,
        'phone_invite_pk': invite.pk,
        'intent_id': sponsor_7702.intent_id_hex('invite_create', invite.pk),
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

    if phone_invite.inviter_user_id != user.id or phone_invite.status != 'draft':
        return {'success': False, 'error': 'invite_not_pending'}

    # The address prepare escrowed FROM, not a re-derived one: prepare honours
    # the JWT's business context, so re-resolving personal/0 here would check
    # the signature against the wrong account and reject every business invite.
    inviter_addr = (phone_invite.inviter_address or '').lower()
    if not inviter_addr:
        return {'success': False, 'error': 'no_bsc_address'}
    invite_id32 = '0x' + phone_invite.invitation_id
    calls = _stored_create_calls(phone_invite)
    if not calls:
        return {'success': False, 'error': 'invite_requires_reprepare'}
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    # EVERYTHING that can reject without side effects happens BEFORE the row is
    # taken (Codex follow-up audit 2026-08-02 P1). Validating after the CAS left
    # a dead end on the most ordinary path there is: a first-ever invite always
    # returns 'authorization_required' so the client can attach its 7702
    # authorization, and that return abandoned the row in 'creating' — the
    # retry then found no 'draft' row and first-use invites failed outright.
    try:
        _validate_create_batch(calls, phone_invite.token_type, invite_id32)
        intent_id = sponsor_7702.intent_id_for('invite_create', phone_invite.pk)
        digest = sponsor_7702.intent_digest(calls, int(nonce), int(deadline), inviter_addr, chain_id, intent_id)
        if sponsor_7702.recover_intent_signer(digest, intent_signature) != inviter_addr:
            return {'success': False, 'error': 'bad_intent_signature'}
        auth_dict = None
        if not sponsor_7702.is_delegated(inviter_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required', 'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(authorization, inviter_addr, chain_id)
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}

    # Now take the row. Two concurrent submits both used to pass the status
    # read above and both broadcast; one funded the escrow, the other reverted
    # on the consumed delegate nonce, and whichever confirmer ran last decided
    # the row's fate — leaving the funded slot with no way back. The UPDATE is
    # the lock: exactly one caller can move draft → creating, and only that
    # caller broadcasts.
    won = PhoneInvite.objects.filter(pk=phone_invite.pk, status='draft').update(
        status='creating')
    if not won:
        return {'success': False, 'error': 'invite_not_pending'}
    phone_invite.status = 'creating'

    send_tx = phone_invite.send_transaction
    # SUBMITTED before the broadcast, not after. send_sponsored_batch writes
    # its durable SponsoredBatch row before eth_sendRawTransaction, so a crash
    # anywhere past this point leaves state the reconciler can resolve; a
    # crash BETWEEN broadcast and this write used to leave the rows looking
    # untouched and reusable while the batch was still on its way to the chain.
    #
    # No expiry yet: the contract starts the 7-day window when the create
    # MINES, so dating it from here would show the inviter a reclaim button
    # that the escrow rejects as 'not expired'. confirm_bsc_invite_create sets
    # it from the confirmation.
    if send_tx is not None:
        send_tx.status = 'SUBMITTED'
        # The marker that keeps the Algorand recovery scanner off this row
        # (blockchain/tasks.py): it asks an algod node about the hash, and a
        # BSC hash no algod node has heard of reads as "missing from the pool"
        # — it would mark a perfectly good invite FAILED after two minutes.
        send_tx.bsc_calls_json = json.dumps({
            'calls': calls, 'kind': 'invite_create', 'inviter': inviter_addr})
        send_tx.save(update_fields=['status', 'bsc_calls_json', 'updated_at'])

    try:
        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, inviter_addr, calls, int(nonce), int(deadline), intent_signature, auth_dict, 'invite_create', source_id=phone_invite.pk)
    except sponsor_7702.PolicyError as exc:
        # Every PolicyError is raised before the batch row is written (bad
        # calldata, failed simulation, gas price cap), so nothing can be in
        # flight — hand the row back for a retry.
        _release_create(phone_invite)
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception('[INVITE][BSC] create failed for %s', phone_invite.invitation_id)
        # Only release when no batch was ever written. If one exists, it was
        # written before broadcast and may be on the chain right now — the
        # reconciler owns it, and rolling back here is exactly how the slot
        # would get funded twice.
        _release_create(phone_invite, only_if_no_batch=True)
        return {'success': False, 'error': str(exc)[:200]}

    if send_tx is not None:
        send_tx.transaction_hash = tx_hash
        send_tx.save(update_fields=['transaction_hash', 'updated_at'])
    from .invite_tasks import confirm_bsc_invite_create
    # Keyed by the INVITE pk, matching the batch's source_id — that is what
    # cusd_plus.reconcile_signed_batches passes when it re-enqueues a domain
    # confirm the crash skipped.
    confirm_bsc_invite_create.apply_async(args=[phone_invite.pk, batch.id], countdown=5)
    return {'success': True, 'transaction_hash': tx_hash}


def _release_create(phone_invite, only_if_no_batch: bool = False) -> None:
    """Hand a 'creating' row back to 'draft' after an attempt that provably
    never reached the chain. CAS-guarded: if a confirmer already advanced the
    row, its verdict stands."""
    from blockchain.models import SponsoredBatch

    from .models import PhoneInvite, SendTransaction

    # A LIVE batch, not any historical one. A terminal batch (confirmed /
    # reverted / dropped) is already settled and cannot fund anything, so
    # treating it as "in flight" would refuse to release a row forever after a
    # single earlier attempt (Codex follow-up audit 2026-08-02 P1).
    if only_if_no_batch and SponsoredBatch.objects.filter(
            kind='invite_create', source_id=phone_invite.pk,
            status__in=('signed', 'sent')).exists():
        logger.warning('[INVITE][BSC] invite %s left in-flight — a live batch exists',
                       phone_invite.pk)
        return
    released = PhoneInvite.objects.filter(
        pk=phone_invite.pk, status='creating').update(status='draft')
    if released:
        phone_invite.status = 'draft'
        # transaction_hash is null=True, so a row that never broadcast holds
        # NULL, not '' — matching only '' left the history row (and the unified
        # row behind it) stuck on SUBMITTED after a pre-batch rejection.
        stx = SendTransaction.objects.filter(
            pk=phone_invite.send_transaction_id, status='SUBMITTED').filter(
                Q(transaction_hash__isnull=True) | Q(transaction_hash='')).first()
        if stx is not None:
            # save(), not update(): the unified history row is maintained by a
            # post_save signal that a queryset update does not fire.
            stx.status = 'PENDING'
            stx.save(update_fields=['status', 'updated_at'])


# ── Claim (sponsor, plain KMS tx) ────────────────────────────────────────

def claim_for_recipient(phone_invite, recipient_user) -> dict:
    """Called when the invitee joins (verified). The KMS sponsor releases
    the escrow to their bsc_address."""
    from cusd_plus.sponsor_7702 import (
        _rpc, acquire_sponsor_nonce_lock, release_sponsor_nonce_lock,
    )
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

    from .models import PhoneInvite

    if not _enabled():
        return {'success': False, 'error': 'bsc_invite_disabled'}
    if phone_invite.status != 'pending':
        return {'success': False, 'error': 'invite_not_pending'}

    # The escrow keys funds by (inviter, inviteId). Re-deriving the inviter
    # from their personal account would look up a slot that was never funded
    # when the invite came from a business account — the claim would revert and
    # the money would sit in escrow until expiry. Use the address we recorded.
    inviter_addr = (phone_invite.inviter_address or '').lower()
    # Revalidate ownership at SIGNING time, not at scheduling time. This runs
    # asynchronously (post-create auto-claim, retry task), and a phone can move
    # between accounts in the meantime — releasing to whoever was resolved
    # minutes ago would pay the wrong person (Codex follow-up audit P1).
    if (getattr(recipient_user, 'phone_key', None) or '') != phone_invite.phone_key:
        return {'success': False, 'error': 'recipient_phone_changed'}

    rec_acct = recipient_user.accounts.filter(
        account_type='personal', account_index=0, deleted_at__isnull=True).first()
    recipient_addr = ((getattr(rec_acct, 'bsc_address', None) or '') or '').lower()
    if not inviter_addr or not recipient_addr:
        return {'success': False, 'error': 'missing_bsc_address'}
    if recipient_addr == inviter_addr:
        return {'success': False, 'error': 'recipient_is_inviter'}

    from cusd_plus.eligibility import is_ondo_eligible

    escrow = _escrow()
    invite_id32 = phone_invite.invitation_id
    recipient_eligible = is_ondo_eligible(recipient_user)
    try:
        min_amount_out = _claim_min_amount_out(phone_invite, recipient_eligible)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[INVITE][BSC] claim quote failed %s: %s', invite_id32, exc)
        return {'success': False, 'error': 'quote_unavailable'}
    calldata = (
        '0x' + SEL_CLAIM + invite_id32 + _addr_word(inviter_addr)
        + _addr_word(recipient_addr) + _uint_word(1 if recipient_eligible else 0)
        + _uint_word(min_amount_out)
    )
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    signer = get_bsc_sponsor_signer_from_settings()
    sponsor = signer.address
    try:
        _rpc('eth_call', [{'from': sponsor, 'to': escrow, 'data': calldata}, 'latest'])
    except Exception as exc:  # noqa: BLE001
        logger.warning('[INVITE][BSC] claim simulation reverted %s: %s', invite_id32, exc)
        return {'success': False, 'error': 'simulation_reverted'}

    gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                    int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 50_000_000)))
    price_cap = int(getattr(settings, 'CUSD_PLUS_7702_MAX_GAS_PRICE_WEI', 5_000_000_000))
    if gas_price > price_cap:
        return {'success': False, 'error': 'gas_price_too_high'}
    fee_per_gas = min((gas_price * 12) // 10, price_cap)

    # Take the invite before broadcasting, same reasoning as create: 'claiming'
    # is what stops a reclaim from being prepared against a slot whose claim is
    # already on its way, and what stops a second auto-claim double-broadcast.
    with transaction.atomic():
        from users.models import Account

        locked_recipient = Account.objects.select_for_update().filter(
            pk=getattr(rec_acct, 'pk', None),
            deleted_at__isnull=True,
        ).first()
        current_recipient = (
            getattr(locked_recipient, 'bsc_address', None) or ''
        ).lower()
        if current_recipient != recipient_addr:
            return {'success': False, 'error': 'recipient_address_changed'}
        won = PhoneInvite.objects.filter(pk=phone_invite.pk, status='pending').update(
            status='claiming', claimed_by=recipient_user)
    if not won:
        return {'success': False, 'error': 'invite_not_pending'}
    phone_invite.status = 'claiming'

    # Keep the ownership token. Releasing without it is the legacy
    # unconditional delete, which a holder whose 15s TTL lapsed can use to drop
    # a NEWER holder's lock — letting two sponsor transactions sign the same
    # nonce (sponsor_7702.py documents this; the invite claim was still on the
    # legacy path).
    lock_token = acquire_sponsor_nonce_lock()
    if not lock_token:
        _revert_claiming(phone_invite)
        return {'success': False, 'error': 'sponsor_busy'}
    # Bound before the try: the except below branches on whether signing got
    # far enough to produce a hash, and an unbound name there would raise
    # inside the handler and strand the invite in 'claiming' forever.
    tx_hash = ''
    try:
        nonce = int(_rpc('eth_getTransactionCount', [sponsor, 'pending']), 16)
        tx = {'type': 2, 'chainId': chain_id, 'nonce': nonce,
              'maxPriorityFeePerGas': fee_per_gas, 'maxFeePerGas': fee_per_gas,
              'gas': GAS_CLAIM, 'to': to_checksum_address(escrow), 'value': 0,
              'data': calldata, 'accessList': []}
        raw, tx_hash = signer.sign_typed_transaction(tx)
        # Record the hash BEFORE broadcasting. The hash of a signed tx is
        # deterministic, so writing it first means a crash mid-broadcast still
        # leaves the confirmer something to look up — the same durability rule
        # sponsor_7702.send_sponsored_batch follows for batches.
        PhoneInvite.objects.filter(pk=phone_invite.pk, status='claiming').update(
            claimed_txid=tx_hash)
        sent = _rpc('eth_sendRawTransaction', [raw])
    except Exception as exc:  # noqa: BLE001
        logger.exception('[INVITE][BSC] claim broadcast failed %s', invite_id32)
        if tx_hash:
            # Signed, so it may already be in a mempool — settle it from the
            # receipt rather than reverting to 'pending' and inviting a second
            # claim of the same escrow slot.
            confirm_bsc_invite_claim_later(phone_invite.pk, tx_hash)
        else:
            # Never signed: nothing can be in flight, so give the slot back.
            _revert_claiming(phone_invite)
        return {'success': False, 'error': str(exc)[:200]}
    finally:
        release_sponsor_nonce_lock(lock_token)

    # NOT 'claimed' — that is the receipt's word. A dropped or reverted claim
    # booked as final here is money the invitee never got and the inviter can
    # no longer reclaim (Codex audit 2026-08-02 P1).
    confirm_bsc_invite_claim_later(phone_invite.pk, sent or tx_hash)
    return {'success': True, 'transaction_hash': sent or tx_hash}


def _revert_claiming(phone_invite) -> None:
    """Undo the 'claiming' take when nothing was signed or broadcast."""
    from .models import PhoneInvite
    if PhoneInvite.objects.filter(pk=phone_invite.pk, status='claiming').update(
            status='pending', claimed_by=None):
        phone_invite.status = 'pending'


def confirm_bsc_invite_claim_later(invite_pk: int, tx_hash: str) -> None:
    from .invite_tasks import confirm_bsc_invite_claim
    confirm_bsc_invite_claim.apply_async(args=[invite_pk, tx_hash], countdown=5)


def claim_pending_bsc_invites(recipient_user, phone_key: str) -> int:
    """Release every pending BSC-token invite addressed to `phone_key` to
    the newly-verified user. Called from the phone-verification auto-claim.
    Returns the number claimed. Best-effort — never raises into onboarding.
    """
    from .models import PhoneInvite

    if not _enabled() or not phone_key:
        return 0
    claimed = 0
    # rail, stated on the row, is the discriminator — token_type cannot be one
    # (CONFIO exists on both rails). inviter_address stays in the filter as a
    # second, independent condition: a row has to satisfy both to be handed to
    # the BSC sponsor, so a single mislabelled field cannot misroute money.
    pending = PhoneInvite.objects.filter(
        rail='bsc', phone_key=phone_key, status='pending',
        token_type__in=('CUSD_PLUS', 'CUSD', 'CONFIO'), deleted_at__isnull=True,
    ).exclude(inviter_address='')
    for inv in pending:
        try:
            res = claim_for_recipient(inv, recipient_user)
            if res.get('success'):
                claimed += 1
            else:
                logger.info('[INVITE][BSC] auto-claim skipped %s: %s',
                            inv.invitation_id, res.get('error'))
                _retry_claim_later(inv, recipient_user, res.get('error'))
        except Exception:  # noqa: BLE001 — onboarding must not fail on this
            logger.exception('[INVITE][BSC] auto-claim errored %s', inv.invitation_id)
            _retry_claim_later(inv, recipient_user, 'exception')
    return claimed


# Conditions that will pass on their own later. Anything else (the recipient is
# the inviter, the escrow says no) will fail identically forever, so retrying
# just burns sponsor RPC.
_RETRYABLE_CLAIM_ERRORS = frozenset({
    'sponsor_busy', 'gas_price_too_high', 'simulation_reverted', 'exception',
})


def _retry_claim_later(phone_invite, recipient_user, error) -> None:
    """Re-attempt a claim that failed on something transient.

    Without this the auto-claim is one-shot: a sponsor that happened to be busy
    at the moment the invitee verified their phone left the money escrowed
    until the inviter reclaimed it a week later, and nothing in the system was
    ever going to try again (Codex audit 2026-08-02 P2).

    'simulation_reverted' is in the retryable set on purpose — the usual cause
    is a create that has not mined yet, which is exactly the case that fixes
    itself.
    """
    if error not in _RETRYABLE_CLAIM_ERRORS:
        return
    try:
        from .invite_tasks import retry_bsc_invite_claim
        retry_bsc_invite_claim.apply_async(
            args=[phone_invite.pk, recipient_user.pk], countdown=60)
    except Exception:  # noqa: BLE001 — onboarding must not fail on this
        logger.exception('[INVITE][BSC] could not schedule claim retry %s',
                         phone_invite.invitation_id)


# ── Reclaim (inviter, 7702) ──────────────────────────────────────────────

def build_reclaim_calls(invite_id32: str) -> list:
    return [{'to': _escrow(), 'value': '0', 'data': '0x' + SEL_RECLAIM + invite_id32[2:]}]


def submit_reclaim(user, phone_invite, nonce, deadline, intent_signature, authorization=None) -> dict:
    from cusd_plus import sponsor_7702

    from .models import PhoneInvite

    if phone_invite.inviter_user_id != user.id or phone_invite.status != 'pending':
        return {'success': False, 'error': 'invite_not_reclaimable'}

    inviter_addr = (phone_invite.inviter_address or '').lower()
    if not inviter_addr:
        return {'success': False, 'error': 'no_bsc_address'}
    calls = build_reclaim_calls('0x' + phone_invite.invitation_id)
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    # Validate before taking the row — same dead end as create, but worse here
    # because the stranded escrow is FUNDED: an 'authorization_required' return
    # (the normal first-use path) left the invite in 'reclaiming' with no batch
    # and no confirmer, so neither claim nor reclaim could ever run again and
    # the money was unreachable (Codex follow-up audit 2026-08-02 P1).
    try:
        intent_id = sponsor_7702.intent_id_for('invite_reclaim', phone_invite.pk)
        digest = sponsor_7702.intent_digest(calls, int(nonce), int(deadline), inviter_addr, chain_id, intent_id)
        if sponsor_7702.recover_intent_signer(digest, intent_signature) != inviter_addr:
            return {'success': False, 'error': 'bad_intent_signature'}
        auth_dict = None
        if not sponsor_7702.is_delegated(inviter_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required', 'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(authorization, inviter_addr, chain_id)
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}

    # Now take the row. Previously the status only flipped AFTER a successful
    # broadcast, so a claim landing in between (or a second reclaim) raced
    # against it; now 'pending' is consumed once and the loser is told so.
    won = PhoneInvite.objects.filter(pk=phone_invite.pk, status='pending').update(
        status='reclaiming')
    if not won:
        return {'success': False, 'error': 'invite_not_reclaimable'}
    phone_invite.status = 'reclaiming'

    try:
        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, inviter_addr, calls, int(nonce), int(deadline), intent_signature, auth_dict, 'invite_reclaim', source_id=phone_invite.pk)
    except sponsor_7702.PolicyError as exc:
        # Pre-batch failure — nothing in flight, so the escrow is still
        # claimable and the row goes back.
        _release_reclaim(phone_invite)
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception('[INVITE][BSC] reclaim failed %s', phone_invite.invitation_id)
        _release_reclaim(phone_invite, only_if_no_batch=True)
        return {'success': False, 'error': str(exc)[:200]}

    # Still 'reclaiming', NOT 'reclaimed' (audit P3): the confirm task
    # finalizes only once the batch mines; a reverted reclaim goes back to
    # 'pending' so the escrow stays claimable / retryable.
    from .invite_tasks import confirm_bsc_invite_reclaim
    confirm_bsc_invite_reclaim.apply_async(args=[phone_invite.pk, batch.id], countdown=8)
    return {'success': True, 'transaction_hash': tx_hash}


def _release_reclaim(phone_invite, only_if_no_batch: bool = False) -> None:
    """Hand a 'reclaiming' row back to 'pending' after an attempt that provably
    never reached the chain."""
    from blockchain.models import SponsoredBatch

    from .models import PhoneInvite

    if only_if_no_batch and SponsoredBatch.objects.filter(
            kind='invite_reclaim', source_id=phone_invite.pk,
            status__in=('signed', 'sent')).exists():
        logger.warning('[INVITE][BSC] invite %s reclaim left in-flight — a live batch exists',
                       phone_invite.pk)
        return
    if PhoneInvite.objects.filter(pk=phone_invite.pk, status='reclaiming').update(
            status='pending'):
        phone_invite.status = 'pending'
