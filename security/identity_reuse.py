"""An identity match is a review hold, not a finding that someone committed fraud.

Use live bans and verified document namespaces, not names, IPs or devices.
Historical verified documents remain evidence even if soft deleted. A dismissed
case releases only its exact document/ban combination, never future bans.

A verified phone number that a live ban recorded (UserBan.phone_hash) holds
the same way: a banned account's number moves to any account that verifies
it, and carriers also hand inactive numbers to new people, so a match is a
review hold, never a refusal to sign up.
"""
import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import IdentityVerification, SuspiciousActivity, UserBan, banned_phone_hash

TRIGGER = 'identity_reuse_active_ban'
PHONE_TRIGGER = 'phone_reuse_active_ban'
DUPLICATED_FACE_TRIGGER = 'didit_duplicated_face'
ACTIONS = {
    TRIGGER: 'New outgoing activity restricted pending identity review.',
    PHONE_TRIGGER: ('New outgoing activity restricted pending review: this verified phone '
                    'number belonged to a banned account.'),
    DUPLICATED_FACE_TRIGGER: ('New outgoing activity restricted pending review: Didit found this face '
                              "in another user's approved verification."),
}
MESSAGE = 'Las salidas de tu cuenta están temporalmente restringidas. Contacta con soporte para revisar tu cuenta.'


def require_outgoing_identity(user):
    from graphql import GraphQLError
    restriction = outgoing_identity_restriction(user)
    if restriction:
        raise GraphQLError(restriction, extensions={'code': 'IDENTITY_REVIEW_REQUIRED'})


def require_identity_for_signed_algorand(user, signed_blob):
    """Raw submit supports opt-ins too; only zero-value self opt-ins are exempt.

    Decode all concatenated signed transactions, including solo submissions.
    Malformed payloads fail closed for an account under review.
    """
    restriction = outgoing_identity_restriction(user)
    if not restriction:
        return
    import base64
    import msgpack
    from graphql import GraphQLError
    try:
        raw = base64.b64decode(signed_blob, validate=True)
        unpacker = msgpack.Unpacker(raw=False)
        unpacker.feed(raw)
        count = 0
        while unpacker.tell() < len(raw):
            txn = unpacker.unpack()['txn']
            count += 1
            safe_asset = (txn.get('type') == 'axfer' and not txn.get('aamt', 0)
                          and txn.get('arcv') == txn.get('snd'))
            safe_app = txn.get('type') == 'appl' and txn.get('apan') == 1
            if not (safe_asset or safe_app) or any(txn.get(k) for k in ('rekey', 'close', 'aclose', 'asnd')):
                raise ValueError('not a self opt-in')
        if not count:
            raise ValueError('empty group')
    except Exception:
        raise GraphQLError(restriction, extensions={'code': 'IDENTITY_REVIEW_REQUIRED'}) from None


class IdentityReviewMiddleware:
    """Persist review evidence after JWT auth but before resolver transactions.

    This does not reject reads, support, or incoming payments. Actual outgoing
    boundaries enforce the hold, including callers outside GraphQL.
    """
    def resolve(self, next, root, info, **args):
        if info.parent_type == info.schema.mutation_type:
            outgoing_identity_restriction(getattr(info.context, 'user', None))
        return next(root, info, **args)


def require_identity_for_autoswap(user, ordered_bytes, actor_address):
    """Allow the canonical internal cUSD mint/burn, not appended sends.

    Only the user's own address and the configured cUSD app may receive user
    value. Unknown app calls, close/rekey, and external transfers fail closed.
    """
    restriction = outgoing_identity_restriction(user)
    if not restriction:
        return
    import msgpack
    from algosdk.encoding import decode_address
    from algosdk.logic import get_application_address
    from django.conf import settings
    from graphql import GraphQLError
    try:
        actor = decode_address(actor_address)
        app_id = int(settings.ALGORAND_CUSD_APP_ID)
        internal = {actor, decode_address(get_application_address(app_id))}
        txns = [msgpack.unpackb(raw, raw=False)['txn'] for raw in ordered_bytes]
        # Preserve the existing ALGO -> USDC -> cUSD auto-deposit path.
        # Derive the one canonical pool locally; never trust a caller address.
        from tinyman.v2.constants import MAINNET_VALIDATOR_APP_ID, TESTNET_VALIDATOR_APP_ID
        from tinyman.v2.contracts import get_pool_logicsig
        validator = (MAINNET_VALIDATOR_APP_ID if settings.ALGORAND_NETWORK == 'mainnet'
                     else TESTNET_VALIDATOR_APP_ID)
        usdc = int(settings.ALGORAND_USDC_ASSET_ID)
        pool = decode_address(get_pool_logicsig(validator, 0, usdc).address())
        canonical_swap_indexes = set()
        for index in range(len(txns) - 1):
            pay, swap = txns[index:index + 2]
            if (pay.get('snd') == actor and pay.get('type') == 'pay' and pay.get('rcv') == pool
                    and swap.get('snd') == actor and swap.get('type') == 'appl'
                    and swap.get('apid') == validator and not swap.get('apan', 0)
                    and swap.get('apaa', [])[:2] == [b'swap', b'fixed-input']
                    and len(swap.get('apaa', [])) == 3
                    and swap.get('apat') == [pool]
                    and set(swap.get('apas', [])) == {0, usdc}
                    and any(t.get('snd') == actor and t.get('type') == 'axfer'
                            and t.get('xaid') == usdc and t.get('arcv') == decode_address(get_application_address(app_id))
                            for t in txns[index + 2:])):
                canonical_swap_indexes.update((index, index + 1))
        for index, txn in enumerate(txns):
            if txn.get('snd') != actor:
                continue
            if any(txn.get(k) for k in ('rekey', 'close', 'aclose', 'asnd')):
                raise ValueError('authority change')
            if index in canonical_swap_indexes:
                continue
            if txn.get('type') == 'axfer':
                if txn.get('aamt', 0) and txn.get('arcv') not in internal:
                    raise ValueError('external asset transfer')
            elif txn.get('type') == 'pay':
                if txn.get('amt', 0) and txn.get('rcv') not in internal:
                    raise ValueError('external payment')
            elif txn.get('type') == 'appl':
                if txn.get('apid') != app_id:
                    raise ValueError('non-conversion app')
            else:
                raise ValueError('unsupported transaction')
    except Exception:
        raise GraphQLError(restriction, extensions={'code': 'IDENTITY_REVIEW_REQUIRED'}) from None


def _personal_documents():
    return IdentityVerification.all_objects.filter(status='verified').filter(
        Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business')
    ).exclude(document_number_normalized='').exclude(document_issuing_country__in=['', 'UNK'])


def _live_bans():
    return UserBan.objects.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))


def _ban_binding(ban):
    return [ban.pk, ban.banned_at.isoformat(), ban.ban_type, ban.reason,
            ban.expires_at.isoformat() if ban.expires_at else None]


def outgoing_identity_restriction(user):
    """Return a safe user message, or ''. Independent of Face rollout/exemptions.

    SecurityMiddleware also calls this before the view's transaction so review
    cases survive a rejected mutation's rollback. Enforcement never relies on
    those precomputed cases: bans are re-read at each outgoing boundary.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return ''
    documents = _personal_documents()
    identities = list(documents.filter(user_id=user.pk).values_list(
        'document_issuing_country', 'document_type', 'document_number_normalized').distinct())
    matches = {}
    for country, kind, number in identities:
        if not kind:
            continue
        others = documents.filter(document_issuing_country=country, document_type=kind,
                                  document_number_normalized=number).exclude(user_id=user.pk)
        for ban in _live_bans().filter(user_id__in=others.values('user_id')):
            binding = [country, kind, number, *_ban_binding(ban)]
            fingerprint = hashlib.sha256(json.dumps(binding).encode()).hexdigest()
            matches[fingerprint] = (TRIGGER, ban)
    phone_hash = banned_phone_hash(getattr(user, 'phone_key', None))
    if phone_hash:
        for ban in _live_bans().filter(phone_hash=phone_hash).exclude(user_id=user.pk):
            binding = ['phone', phone_hash, *_ban_binding(ban)]
            fingerprint = hashlib.sha256(json.dumps(binding).encode()).hexdigest()
            matches[fingerprint] = (PHONE_TRIGGER, ban)
    # A face Didit already approved for another user, on any of this user's
    # verified personal documents, whichever was verified first. No ban
    # needed: one person behind two accounts is itself the review.
    flagged = IdentityVerification.all_objects.filter(
        user_id=user.pk, status='verified', risk_factors__has_key='duplicated_face',
    ).filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
    for verification_id in flagged.values_list('pk', flat=True):
        fingerprint = hashlib.sha256(json.dumps(['duplicated_face', verification_id]).encode()).hexdigest()
        matches[fingerprint] = (DUPLICATED_FACE_TRIGGER, None)
    if not matches:
        return ''
    held = False
    with transaction.atomic():
        # All automatic case creation takes this same lock; simultaneous
        # requests cannot create conflicting review decisions for one match.
        get_user_model().objects.select_for_update().get(pk=user.pk)
        for fingerprint, (trigger, ban) in matches.items():
            case = SuspiciousActivity.objects.filter(
                user=user, detection_data__trigger=trigger,
                detection_data__match_key=fingerprint).order_by('-pk').first()
            if case is None:
                case = SuspiciousActivity.objects.create(
                    user=user, activity_type='multiple_accounts', status='pending',
                    severity_score=9,
                    detection_data={'trigger': trigger, 'match_key': fingerprint,
                                    'matched_user_id': ban.user_id if ban else None,
                                    'ban_id': ban.pk if ban else None},
                    action_taken=ACTIONS[trigger])
                if ban is not None:
                    case.related_users.add(ban.user_id)
            released = (case.status == 'dismissed' and case.investigated_by_id is not None
                        and bool(case.investigation_notes.strip()))
            held = held or not released
    return MESSAGE if held else ''
