"""Relay policy for batches whose calls touch a Cuenta inteligente account
(spec 7.4). Called from cusd_plus/sponsor_7702.validate_policy.

Rule: the relay executes a call to an account (or a transfer into one, or
the factory's createAccount) ONLY as part of a batch that byte-matches an
unexpired, unconsumed SmartAccountPreparedAction for the signing user. On
top of that match the shape is re-checked here independently of the stored
row, so a wrong row cannot widen what is executed.

This is also what makes the contract's sponsor gate on setBeneficiary and
acceptBeneficiary meaningful: tx.origin proves only that a sponsor started
the transaction, so the relay must never originate a designation it did not
check and prepare.
"""
from __future__ import annotations

import logging
import re

from django.conf import settings
from django.utils import timezone

from . import abi, chain

logger = logging.getLogger(__name__)

_ATTEMPT_SUFFIX = re.compile(r'_a[0-9]$')
MAX_CALLDATA_HEX = 2 + 2 * 6_000  # account.trade wrapping a stock quote


def _error(code: str):
    from cusd_plus.sponsor_7702 import PolicyError
    return PolicyError(code)


def base_request_id(request_id: str | None) -> str:
    """The app appends _a0/_a1 per attempt (sponsored7702.ts)."""
    return _ATTEMPT_SUFFIX.sub('', (request_id or '').strip())


def _selector(call: dict) -> str:
    return (call.get('data') or '')[2:10].lower()


def _transfer_recipient(call: dict) -> str | None:
    data = (call.get('data') or '')[2:].lower()
    if data[:8] != abi.SEL_TRANSFER or len(data) != 8 + 128:
        return None
    return '0x' + data[8 + 24:8 + 64]


def _own_account(user):
    from .context import own_account
    return own_account(user)


def _is_cancel_claim_to_own(call: dict, user) -> bool:
    if _selector(call) != abi.SEL_CANCEL_CLAIM or len((call.get('data') or '')) != 10:
        return False
    own = _own_account(user)
    return own is not None and call['to'] == own.contract_address.lower()


def _known_account_addresses(addresses: set) -> set:
    from .models import SmartAccount, SmartAccountPreparedAction
    addresses = {a for a in addresses if a}
    if not addresses:
        return set()
    known = set(SmartAccount.all_objects.filter(contract_address__in=addresses)
                .values_list('contract_address', flat=True))
    # A predicted address the server handed out before the account exists.
    known |= set(SmartAccountPreparedAction.objects.filter(target_address__in=addresses)
                 .values_list('target_address', flat=True))
    return {a.lower() for a in known}


def touches_account(calls: list) -> bool:
    """True when any call is to the factory, to a known account contract, or
    an ERC-20 transfer INTO a known account contract."""
    factory = chain.factory_address()
    if not factory:
        return False
    candidates = set()
    for c in calls:
        if c['to'] == factory:
            return True
        candidates.add(c['to'])
        recipient = _transfer_recipient(c)
        if recipient:
            candidates.add(recipient)
    return bool(_known_account_addresses(candidates))


def split_generic(calls: list, user, signer: str | None = None) -> tuple[list, bool]:
    """(calls for the existing personal-wallet policy, is_account_batch).

    A personal-wallet batch may END with cancelClaim() on the signer's own
    account (spec 6.4): that one call is set aside and the rest is validated
    by the unchanged existing policy. Anything else that touches an account
    makes the whole batch an account batch. With `signer`, only the owner's
    own key may carry it (a business key never owns the account)."""
    if not chain.factory_address():
        return calls, False
    if len(calls) > 1 and _is_cancel_claim_to_own(calls[-1], user) and not touches_account(calls[:-1]):
        if signer is None or own_cancel_claim_call(user, signer) is not None:
            return calls[:-1], False
    return calls, touches_account(calls)


def claim_pending(user) -> bool:
    """Mirror view (reconciled from events) of a pending claim on the
    signer's own account."""
    from .models import SmartAccountClaim
    own = _own_account(user)
    if own is None:
        return False
    return SmartAccountClaim.objects.filter(beneficiary_row__smart_account=own, state='pending').exists()


def require_cancel_claim_generic(original_calls: list, user, signer: str | None = None) -> None:
    """Spec 6.4/7.4 for personal-wallet batches. Off by default: released
    app builds do not append cancelClaim, and refusing their batches would
    lock an owner out of the app while a claim is pending. Turn on once the
    minimum supported build appends it. Only a batch signed by the owner's
    own key can carry the call: a business key never owns the account."""
    if not getattr(settings, 'SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM', False):
        return
    if not chain.factory_address() or not claim_pending(user):
        return
    if signer is not None and own_cancel_claim_call(user, signer) is None:
        return
    if not any(_is_cancel_claim_to_own(c, user) for c in original_calls):
        own = _own_account(user)
        if own is not None and chain_confirms_owner(
                own.contract_address, signer or (own.owner_account.bsc_address or '')) is True:
            raise _error('claim_cancel_required')


# ── cancelClaim on personal-wallet flows (spec 6.4, 7.4) ────────────────
#
# Every batch the owner signs from the personal wallet may end with exactly
# one account.cancelClaim() to the signer's OWN registered account. The call
# is a no-op success when nothing is pending, so it is accepted whether or
# not the mirror shows a claim (a claim cancelled between prepare and submit
# must not turn a valid batch into a refusal). Where the server builds the
# calls itself (send, pay, presale, invite create, bridge) it appends the call
# while a claim is pending; where the app builds them (the generic rail,
# Comprar actions, invite reclaim) the app appends it from
# SmartAccountClaimAlert.contractAddress.

def own_cancel_claim_call(user, signer: str) -> dict | None:
    """account.cancelClaim() on the user's own account when `signer` is that
    account's owner key, else None (a business key, no account, an account
    that was never subscribed or was inherited away)."""
    if not chain.factory_address() or not signer:
        return None
    own = _own_account(user)
    if own is None or own.status == 'none' or own.inherited_at is not None:
        return None
    if (own.owner_account.bsc_address or '').lower() != signer.lower():
        return None
    return abi.call(own.contract_address, abi.encode_call('cancelClaim'))


def signer_controls(state: dict, signer: str) -> bool | None:
    """From chain.account_control: True when `signer` is still owner() and
    the account is not inherited(), False when the chain says otherwise
    (a ClaimExecuted the mirror has not applied yet), None when unknown (a
    zero owner is never a live clone's answer)."""
    owner = str(state.get('owner') or '').lower()
    try:
        if not int(owner or '0x0', 16):
            return None
    except ValueError:
        return None
    return (not state.get('inherited')) and owner == (signer or '').lower()


def ownership_mismatch(address: str, signer: str) -> None:
    """The mirror still treats `signer` as the owner of `address`, the chain
    does not: alert ops and kick the reconciler. Never raises."""
    from django.core.cache import cache
    address = (address or '').lower()
    logger.warning('smart account %s: mirror owner %s no longer controls it on chain', address, signer)
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente {address}: el espejo sigue mostrando al dueño anterior, pero en la red '
                       f'ya no es dueño o la cuenta fue heredada. Reconciliando; revisar si persiste.',
                       dedupe_key=f'smart_owner_mirror_lag_{address}', dedupe_seconds=3600)
    except Exception:  # noqa: BLE001
        logger.exception('smart account ownership alert failed for %s', address)
    try:
        if cache.add(f'smart_owner_mirror_lag_reconcile_{address}', 1, 60):
            from .tasks import reconcile_events
            reconcile_events.apply_async(countdown=1)
    except Exception:  # noqa: BLE001
        logger.exception('smart account reconcile trigger failed for %s', address)


def chain_confirms_owner(address: str, signer: str) -> bool | None:
    """signer_controls on a fresh read (None when unreadable); a mismatch
    is alerted and reconciled."""
    try:
        state = chain.account_control(address)
    except Exception:  # noqa: BLE001
        logger.warning('owner()/inherited() unreadable for %s', address, exc_info=True)
        return None
    controls = signer_controls(state, signer)
    if controls is False:
        ownership_mismatch(address, signer)
    return controls


def pending_cancel_claim_calls(user, signer: str) -> list:
    """[cancelClaim] for a server-built personal batch while a claim is
    pending on the signer's own account, else []. Mirror first; a fresh
    chain read when the mirror could be behind (an accepted beneficiary
    exists). Either way the chain must still name the signer as owner of a
    non-inherited account: after a ClaimExecuted the mirror has not applied,
    cancelClaim reverts (NotOwner) and would fail every send and pay. An
    unreadable chain appends it: the call is a harmless no-op, a missed one
    lets a claim run on."""
    from .models import SmartAccountBeneficiary
    call = own_cancel_claim_call(user, signer)
    if call is None:
        return []
    mirror_pending = claim_pending(user)
    if not mirror_pending and not SmartAccountBeneficiary.objects.filter(
            smart_account__contract_address__iexact=call['to'],
            state__in=('pending_acceptance', 'active', 'stale_address')).exists():
        return []  # nobody can have started a claim
    try:
        state = chain.account_control(call['to'], with_claim=not mirror_pending)
    except Exception:  # noqa: BLE001 — unknown: the protective no-op rides along
        logger.warning('account control unreadable for %s; appending cancelClaim', call['to'], exc_info=True)
        return [call]
    controls = signer_controls(state, signer)
    if controls is False:
        ownership_mismatch(call['to'], signer)
        return []
    if mirror_pending or controls is None:
        return [call]
    return [call] if state['claimStartedAt'] else []


def _normalized(call: dict) -> dict:
    return {'to': (call.get('to') or '').lower(), 'value': str(int(call.get('value') or 0)),
            'data': (call.get('data') or '').lower()}


def strip_cancel_claim(calls: list, user, signer: str) -> list:
    """For domain submit paths: `calls` without its one trailing
    cancelClaim() to the signer's own account, for the flow's unchanged
    byte-exact validation. A cancelClaim anywhere else, a second one, or one
    to any other account is refused. Signature and broadcast keep ALL calls."""
    positions = [i for i, c in enumerate(calls)
                 if (c.get('data') or '')[2:10].lower() == abi.SEL_CANCEL_CLAIM]
    if not positions:
        return calls
    own = own_cancel_claim_call(user, signer)
    if positions != [len(calls) - 1] or own is None or _normalized(calls[-1]) != own:
        raise _error('claim_cancel_not_allowed')
    return calls[:-1]


def signed_variants(calls: list, user, signer: str) -> list:
    """For domain flows that rebuild the calls at submit: the calls as
    rebuilt, and (for the owner's key) the same calls with the trailing
    cancelClaim the app may have appended. The intent signature picks one."""
    variants = [calls]
    call = own_cancel_claim_call(user, signer)
    if call is not None and (not calls or _normalized(calls[-1]) != call):
        variants.append(list(calls) + [call])
    return variants


def split_personal_cancel_claim(calls: list, user, signer: str) -> tuple[list, dict | None]:
    """The generic rail: (calls without a trailing cancelClaim to the
    signer's own account, that call or None).

    A batch whose other calls do not touch any account is a personal-wallet
    batch; if it carries cancelClaim at all, it must be exactly ONE, LAST,
    to the signer's own registered account and signed by its owner key.
    Anything else is refused with 'claim_cancel_not_allowed' (a specific
    code, so the app drops only the cancel and keeps the fee-referral arm),
    never left to fail later as a simulation revert. A batch whose other
    calls touch an account is an account batch and is judged as such."""
    positions = [i for i, c in enumerate(calls)
                 if (c.get('data') or '')[2:10].lower() == abi.SEL_CANCEL_CLAIM]
    if not positions:
        return calls, None
    rest = [c for i, c in enumerate(calls) if i not in positions]
    if not rest or touches_account(rest):
        return calls, None
    own = own_cancel_claim_call(user, signer)
    if positions != [len(calls) - 1] or own is None or _normalized(calls[-1]) != own:
        raise _error('claim_cancel_not_allowed')
    return calls[:-1], calls[-1]


def early_action(user, request_id):
    """The prepared action a request id names for this user, or None. Only
    selects the signer (the personal key); validate_batch decides."""
    from .models import SmartAccountPreparedAction
    base = base_request_id(request_id)
    if not base or not base.startswith('sa-') or not chain.factory_address():
        return None
    return SmartAccountPreparedAction.objects.filter(user=user, request_id=base).first()


def find_action(calls: list, user, request_id: str | None):
    """The prepared action these calls must match, or None."""
    from .models import SmartAccountPreparedAction
    from .services import calls_hash
    base = base_request_id(request_id)
    qs = SmartAccountPreparedAction.objects.filter(user=user)
    if base:
        return qs.filter(request_id=base).first()
    return qs.filter(calls_hash=calls_hash(calls)).order_by('-id').first()


def _exact_replay(action, request_id: str | None) -> bool:
    """The same request (same client_request_id, attempt suffix included)
    as the batch that consumed the action: the sponsor's replay lookup then
    returns that batch's transaction, nothing new is broadcast."""
    batch = action.sponsored_batch
    return bool(batch is not None and request_id and (batch.client_request_id or '') == request_id)


def _consumed_allows(action, request_id: str | None) -> bool:
    """A consumed action is accepted again only as an exact replay of its
    own recorded batch (the sponsor then returns that transaction), or when
    the batch that consumed it did nothing on chain. A retry of a failed
    batch is a NEW broadcast and still needs an unexpired action
    (checked by validate_batch)."""
    batch = action.sponsored_batch
    if batch is None:
        return False
    if _exact_replay(action, request_id):
        return True
    return batch.status in ('reverted', 'noop_failed', 'dropped', 'reorged')


def _designation_target(user, signer: str, target: str, states) -> bool:
    from .models import SmartAccountBeneficiary
    return SmartAccountBeneficiary.objects.filter(
        smart_account__contract_address__iexact=target, beneficiary_user=user,
        beneficiary_address__iexact=signer, state__in=states).exists()


def _owner_target(user, signer: str, target: str, *, allow_predicted: bool) -> bool:
    own = _own_account(user)
    if own is not None:
        return (own.contract_address.lower() == target
                and (own.owner_account.bsc_address or '').lower() == signer)
    if not allow_predicted:
        return False
    # No row yet: the account is created by this very batch (or was created
    # and is not reconciled). Its address is a pure function of the signer.
    return chain.predict_address(signer) == target


def _inherited_target(user, target: str) -> bool:
    from .models import SmartAccount
    # Reached through the user's own live 'smart' row: an account inherited
    # by a wallet Confío could not map (account=None) is nobody's here.
    return SmartAccount.objects.filter(
        contract_address__iexact=target, owner_user=user, status='inherited',
        account__user=user, account__deleted_at__isnull=True).exists()


def _check_shape(action, calls: list, user, signer: str) -> None:
    """Independent of the stored row: destinations, selectors and recipients."""
    kind = action.kind
    allowed = abi.BATCH_KIND_FUNCTIONS.get(kind)
    if allowed is None:
        raise _error('smart_kind_not_allowed')
    target = action.target_address.lower()
    factory = chain.factory_address()
    own = _own_account(user)
    own_address = own.contract_address.lower() if own is not None else None

    names = []
    for c in calls:
        if int(c['value']) != 0:
            raise _error('value_not_allowed')
        data = c['data']
        if not data.startswith('0x') or len(data) > MAX_CALLDATA_HEX or (len(data) - 2) % 2 != 0:
            raise _error('bad_calldata')
        if c['to'] == factory:
            if kind != 'smart_subscribe' or data[2:] != abi.SELECTORS['createAccount']:
                raise _error('selector_not_allowed')
            names.append('createAccount')
            continue
        recipient = _transfer_recipient(c)
        if _selector(c) == abi.SEL_TRANSFER:
            # A deposit: recipient pinned to the signer's own account.
            if kind not in ('smart_subscribe', 'smart_deposit') or recipient != target:
                raise _error('deposit_recipient_not_allowed')
            if c['to'] in (target, factory, chain.usdt_address()):
                raise _error('destination_not_allowed')
            names.append('transfer')
            continue
        try:
            name, _args = abi.decode_call(data)
        except ValueError as exc:
            raise _error('bad_calldata') from exc
        if name == 'cancelClaim' and own_address and c['to'] == own_address:
            names.append('cancelClaim')
            continue
        if c['to'] != target:
            raise _error('destination_not_allowed')
        if name is None or name not in allowed:
            raise _error('selector_not_allowed')
        names.append(name)

    account_names = [n for n in names if n not in ('transfer', 'createAccount', 'cancelClaim')]
    if kind == 'smart_deposit':
        if 'transfer' not in names or account_names:
            raise _error('bad_smart_batch')
    elif kind == 'smart_subscribe':
        if names.count('subscribe') != 1 or names[-1 if 'cancelClaim' not in names else -2] != 'subscribe':
            raise _error('bad_smart_batch')
        if names.count('createAccount') > 1 or ('createAccount' in names and names[0] != 'createAccount'):
            raise _error('bad_smart_batch')
    elif kind == 'smart_claim':
        if len([n for n in names if n != 'cancelClaim']) > 1:
            raise _error('bad_smart_batch')
    elif len(account_names) != 1:
        raise _error('bad_smart_batch')

    # Whose account is it?
    beneficiary_call = next((n for n in names if n in abi.BENEFICIARY_FUNCTIONS), None)
    if beneficiary_call == 'acceptBeneficiary':
        ok = _designation_target(user, signer, target, ('pending_acceptance',))
    elif beneficiary_call in ('initiateClaim', 'executeClaim'):
        ok = _designation_target(user, signer, target, ('active',))
    elif kind == 'smart_inherited_withdraw':
        ok = _inherited_target(user, target)
    else:
        ok = _owner_target(user, signer, target, allow_predicted=kind == 'smart_subscribe')
    if not ok:
        raise _error('smart_account_not_registered')

    if kind == 'smart_inherited_withdraw':
        _check_inherited_destination(calls, user, signer, target)
    if kind == 'smart_trade':
        _check_trade(calls, target)


def _check_inherited_destination(calls: list, user, signer: str, target: str) -> None:
    own = _own_account(user)
    allowed = {signer}
    if own is not None and own.status in ('active', 'cancel_pending'):
        allowed.add(own.contract_address.lower())
    for c in calls:
        if c['to'] != target:
            continue
        name, args = abi.decode_call(c['data'])
        if name in ('withdrawTo', 'withdrawAllTo') and str(args[-1]).lower() not in allowed:
            raise _error('withdraw_destination_not_allowed')


def _check_trade(calls: list, target: str) -> None:
    """The wrapped router call gets the same live quote and slippage checks
    as a personal-wallet trade, and trade()'s own arguments must be exactly
    what that call implies."""
    from cusd_plus.sponsor_7702 import PolicyError
    from .services import trade_parameters
    for c in calls:
        if c['to'] != target:
            continue
        name, args = abi.decode_call(c['data'])
        if name != 'trade':
            continue
        venue, data, token_in, token_out, max_in, min_out = args
        try:
            params = trade_parameters({'to': str(venue).lower(), 'value': '0', 'data': '0x' + bytes(data).hex()})
        except PolicyError:
            raise
        except Exception as exc:  # noqa: BLE001 — money policy fails closed
            logger.warning('smart trade validation failed: %s', exc, exc_info=True)
            raise _error('trade_quote_unavailable') from exc
        if (str(token_in).lower() != params['token_in'] or str(token_out).lower() != params['token_out']
                or int(max_in) != params['max_in'] or int(min_out) != params['min_out']):
            raise _error('bad_smart_trade')


def trade_refusal(action, calls: list, user, meta) -> str | None:
    """Submit-time re-run of the personal rail's entry gates for an account
    trade (services.trade_gate: complex-product acknowledgement, review
    amount cap, crypto buy gates, country policy). Eligibility can change
    between prepare and submit. Fails closed."""
    if action is None or action.kind != 'smart_trade':
        return None
    from .services import trade_gate, trade_parameters
    target = action.target_address.lower()
    try:
        trades = []
        for c in calls:
            if c['to'] != target:
                continue
            name, args = abi.decode_call(c['data'])
            if name == 'trade':
                trades.append(args)
        if len(trades) != 1:
            return 'trade_not_available'
        venue, data = trades[0][0], trades[0][1]
        params = trade_parameters({'to': str(venue).lower(), 'value': '0', 'data': '0x' + bytes(data).hex()})
        return trade_gate(user, meta or {}, params)
    except Exception:  # noqa: BLE001 — money policy fails closed
        logger.warning('smart trade gate failed', exc_info=True)
        return 'trade_not_available'


def face_refusal(action, user) -> str | None:
    """Submit-time Face check for an account batch, in place of the
    personal rail's claim_external_outflow (which an account batch skips).

    Money leaving the owner's control to someone else needs the owner's
    Face, claimed at prepare and bound to the exact terms: a send rule
    (its standing authorization) and a beneficiary designation. Re-claiming
    the SAME action key is an exact retry (security.face_step_up) and costs
    no new check; a missing or foreign grant refuses the batch.

    Not asked (money stays with the owner, or the step protects them):
    subscribe/deposit (owner wallet -> own account), withdraw (account ->
    owner wallet), trade/buy rules (inside the account), cancel, plan
    change, cancelClaim, removing a beneficiary, withdrawing a designation,
    acceptance and claims (signed by the beneficiary, money moves TO the
    signer), inherited withdrawals (to the signer's own wallet or account),
    bank payment rules (Face claimed at prepare through their own standing
    authorization, checked again at every run). Fails closed."""
    if action is None:
        return None
    from security.face_step_up import FACE_STEP_UP_MESSAGE, require_face_step_up
    payload = action.payload or {}
    try:
        key, required = None, False
        if action.kind == 'smart_rule' and payload.get('rule_pk'):
            from .models import SmartAccountRule
            draft = SmartAccountRule.all_objects.select_related('standing_authorization').filter(
                pk=payload['rule_pk']).first()
            if draft is None:
                return 'smart_action_not_prepared'
            if draft.kind != 'send':
                return None
            authorization = draft.standing_authorization
            if authorization is None or authorization.revoked_at is not None or authorization.kind != 'send':
                return FACE_STEP_UP_MESSAGE
            key, required = authorization.face_action_key, authorization.face_required
        elif action.kind == 'smart_beneficiary' and any(
                (abi.decode_call(c['data'])[0] == 'setBeneficiary') for c in action.calls):
            if 'face_required' not in payload:
                return FACE_STEP_UP_MESSAGE
            key, required = payload.get('face_action_key') or '', bool(payload['face_required'])
        else:
            return None
        if not key:
            return FACE_STEP_UP_MESSAGE if required else None
        return require_face_step_up(user, 'withdrawal', action_key=key, consume=True) or None
    except Exception:  # noqa: BLE001 — money policy fails closed
        logger.warning('smart account face check failed', exc_info=True)
        return FACE_STEP_UP_MESSAGE


def validate_batch(calls: list, user, user_addr: str, request_id: str | None = None):
    """Raise PolicyError unless `calls` is exactly a batch the server
    prepared for this user. Returns the prepared action."""
    signer = user_addr.lower()
    action = find_action(calls, user, request_id)
    if action is None:
        raise _error('smart_action_not_prepared')
    if action.signer_address.lower() != signer:
        raise _error('smart_action_not_prepared')
    if list(action.calls) != [
            {'to': c['to'], 'value': str(int(c['value'])), 'data': c['data']} for c in calls]:
        raise _error('smart_action_mismatch')
    if action.consumed and not _consumed_allows(action, request_id):
        raise _error('smart_action_consumed')
    if action.expires_at <= timezone.now() and not (action.consumed and _exact_replay(action, request_id)):
        # Only the exact replay of the recorded request outlives the TTL; a
        # retry after a failed batch is a new broadcast of a stale prepare.
        raise _error('smart_action_expired')
    try:
        _check_shape(action, calls, user, signer)
    except chain.ChainError as exc:
        raise _error('smart_chain_unavailable') from exc
    if claim_pending(user) and not any(_is_cancel_claim_to_own(c, user) for c in calls):
        # Every batch this owner signs while a claim is pending carries it,
        # but only while the chain still names this signer as the owner of a
        # non-inherited account: a ClaimExecuted the mirror lags on makes the
        # call revert, and an unreadable chain never turns into a refusal.
        own = _own_account(user)
        if own is not None and chain_confirms_owner(own.contract_address, signer) is True:
            raise _error('claim_cancel_required')
    return action


def consume(action, batch) -> None:
    """Mark the action consumed by this batch. Called inside the SAME
    database transaction that writes the SponsoredBatch row, before the
    broadcast (send_sponsored_batch's persist_signed)."""
    from .models import SmartAccountPreparedAction
    SmartAccountPreparedAction.objects.filter(pk=action.pk).update(
        consumed=True, consumed_at=timezone.now(), sponsored_batch=batch)


def persist_signed_for(action):
    def _persist(batch, _raw):
        consume(action, batch)
    return _persist
