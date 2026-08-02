import re
import unicodedata
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from achievements.models import (
    ConfioRewardTransaction,
    ReferralRewardEvent,
    ReferralWithdrawalLog,
    UserAchievement,
    UserReferral,
)
from blockchain.constants import REFERRAL_ACHIEVEMENT_SLUGS

DUPLICATE_REFEREE_REWARD_ERROR = (
    "Este documento ya fue utilizado para una recompensa de referido en otra cuenta. "
    "Solo se permite un bono de referido por identidad verificada."
)
DUPLICATE_REFERRER_REWARD_ERROR = (
    "Este referido fue bloqueado por identidad duplicada. No se otorga bono al referidor "
    "cuando la misma identidad verificada intenta reclamar más de una recompensa."
)
# Distinct from the duplicate errors on purpose. Telling someone their document
# was already used, when the real problem is that their verification came back
# without usable data, sends them to support with the wrong story — and it is a
# hold they can clear by verifying again, not a permanent refusal.
INCOMPLETE_IDENTITY_REWARD_ERROR = (
    "No pudimos confirmar los datos de tu verificación de identidad. "
    "Vuelve a verificarte para liberar este bono."
)


def get_referral_reward_transactions(user=None):
    """Return reward ledger rows that represent referral-earned CONFIO."""
    achievement_qs = UserAchievement.objects.filter(
        achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS,
        deleted_at__isnull=True,
    )
    if user is not None:
        achievement_qs = achievement_qs.filter(user=user)

    referral_achievement_ids = [str(pk) for pk in achievement_qs.values_list('id', flat=True)]

    tx_qs = ConfioRewardTransaction.objects.all()
    if user is not None:
        tx_qs = tx_qs.filter(user=user)

    referral_claim_filter = Q(
        transaction_type__in=['earned', 'unlocked'],
        reference_type='referral_claim',
    )
    if not referral_achievement_ids:
        return tx_qs.filter(referral_claim_filter)

    return tx_qs.filter(
        referral_claim_filter
        | Q(
            transaction_type='earned',
            reference_type='achievement',
            reference_id__in=referral_achievement_ids,
        )
    )


def get_referral_reward_summary(user=None):
    """Aggregate referral-earned CONFIO and logged referral withdrawals."""
    earned = (
        get_referral_reward_transactions(user=user).aggregate(
            total=Coalesce(Sum('amount'), Decimal('0'))
        )['total']
        or Decimal('0')
    )

    withdrawal_qs = ReferralWithdrawalLog.objects.all()
    if user is not None:
        withdrawal_qs = withdrawal_qs.filter(user=user)
    spent = withdrawal_qs.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total'] or Decimal('0')

    available = earned - spent
    if available < Decimal('0'):
        available = Decimal('0')

    return {
        'earned': earned,
        'spent': spent,
        'available': available,
    }


def normalize_person_name(value: str | None) -> str:
    """Accent-folded, letters-only, uppercase. 'José Ramírez' -> 'JOSERAMIREZ'."""
    folded = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z]', '', folded).upper()


# Values Didit leaves behind when a session has not produced real data. They
# are non-empty, which is precisely why they slipped past "is this field set?"
# checks: a didit:<session> document is unique per session, so it looked like a
# perfectly good — and never-colliding — identity key.
_PLACEHOLDER_DOCUMENT_PREFIXES = ('DIDIT:', 'SESSION:')
_SENTINEL_NAMES = {'PENDING', 'PENDINGVERIFICATION', 'UNKNOWN', 'NA', 'NONE', 'TEST'}
_SENTINEL_DOB_ISO = {'1900-01-01', '1000-01-01', '0001-01-01'}


def has_usable_document_key(verification) -> bool:
    """True when the document tuple identifies a real document.

    An 'UNK' country, an empty number, or a Didit session placeholder are all
    unusable — the placeholder especially, because it is unique per session and
    therefore can never collide with anything.
    """
    if verification is None:
        return False
    country = (getattr(verification, 'document_issuing_country', '') or '').strip().upper()
    number = (getattr(verification, 'document_number_normalized', '') or '').strip().upper()
    if not country or country == 'UNK' or not number:
        return False
    if number.startswith(_PLACEHOLDER_DOCUMENT_PREFIXES):
        return False
    return True


def person_key_for(verification) -> tuple[str, str, object] | None:
    """(first, last, dob) for a verification, or None when unusable.

    The person layer of the identity key. A document tuple identifies a
    DOCUMENT; the same human holding a national ID and a passport produces two
    of them and passed uniqueness twice. Name plus date of birth is the same
    person across both.

    Not infallible — people share names, and two strangers can share a birthday
    — so this widens the net rather than replacing the document match. Both
    layers must be present for a key to count.
    """
    if verification is None:
        return None
    first = normalize_person_name(getattr(verification, 'verified_first_name', ''))
    last = normalize_person_name(getattr(verification, 'verified_last_name', ''))
    dob = getattr(verification, 'verified_date_of_birth', None)
    if not first or not last or not dob:
        return None
    # 'Pending' is what the Didit parser writes when a name is missing, and
    # 1900-01-01 is the usual placeholder birthday. Treating either as a real
    # person key would group unrelated people together AND satisfy the
    # fail-closed check with data that identifies nobody.
    if first in _SENTINEL_NAMES or last in _SENTINEL_NAMES:
        return None
    if str(dob) in _SENTINEL_DOB_ISO:
        return None
    return (first, last, dob)


def _personal_context_filter(qs):
    return qs.filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))


def _get_verified_identity_user_ids(
    document_issuing_country: str,
    document_number_normalized: str,
    person_key: tuple | None = None,
):
    """Users who are the same person as this identity, by EITHER layer.

    Matching on either the document tuple or the person key is deliberate: one
    human with two documents is caught by the person layer, and one document
    reused under a different spelling of a name is caught by the document
    layer.
    """
    from security.models import IdentityVerification

    base = _personal_context_filter(IdentityVerification.objects.filter(status='verified'))

    user_ids: set = set()

    if document_issuing_country and document_number_normalized:
        user_ids.update(
            base.filter(
                document_issuing_country=document_issuing_country,
                document_number_normalized=document_number_normalized,
            ).values_list('user_id', flat=True)
        )

    if person_key:
        first, last, dob = person_key
        # Name normalization happens in Python, so the DOB narrows the scan and
        # the names are compared after folding.
        for candidate in base.filter(verified_date_of_birth=dob).only(
            'user_id', 'verified_first_name', 'verified_last_name'
        ):
            if (
                normalize_person_name(candidate.verified_first_name) == first
                and normalize_person_name(candidate.verified_last_name) == last
            ):
                user_ids.add(candidate.user_id)

    return list(user_ids)


def _get_identity_referrals(
    document_issuing_country: str,
    document_number_normalized: str,
    person_key: tuple | None = None,
):
    user_ids = _get_verified_identity_user_ids(
        document_issuing_country, document_number_normalized, person_key
    )
    if not user_ids:
        return []

    return list(
        UserReferral.objects.filter(
            referred_user_id__in=user_ids,
            deleted_at__isnull=True,
        ).order_by('created_at', 'id')
    )


def enforce_referee_reward_uniqueness_for_identity(
    document_issuing_country: str,
    document_number_normalized: str,
    person_key: tuple | None = None,
):
    referrals = _get_identity_referrals(
        document_issuing_country, document_number_normalized, person_key
    )
    if len(referrals) <= 1:
        return {'winner_referral_id': referrals[0].id if referrals else None, 'blocked_referral_ids': []}

    winner = referrals[0]
    blocked_referrals = referrals[1:]
    now = timezone.now()

    with transaction.atomic():
        for referral in blocked_referrals:
            reward_metadata = dict(referral.reward_metadata or {})
            reward_metadata['duplicate_identity_referee_block'] = {
                'document_issuing_country': document_issuing_country,
                'document_number_normalized': document_number_normalized,
                # Which layer caught it, so a support review can tell a
                # reused document from a second document for one person.
                'matched_person_key': bool(person_key),
                'winner_referral_id': winner.id,
                'blocked_at': now.isoformat(),
            }

            referral.reward_metadata = reward_metadata
            referral.reward_error = DUPLICATE_REFEREE_REWARD_ERROR
            referral.reward_last_attempt_at = now

            update_fields = ['reward_metadata', 'reward_error', 'reward_last_attempt_at', 'updated_at']

            if referral.referee_reward_status != 'claimed':
                referral.referee_reward_status = 'failed'
                update_fields.append('referee_reward_status')
            if referral.referrer_reward_status != 'claimed':
                referral.referrer_reward_status = 'failed'
                update_fields.append('referrer_reward_status')

            if referral.reward_status in {'pending', 'eligible', 'skipped'}:
                referral.reward_status = 'failed'
                update_fields.append('reward_status')

            referral.save(update_fields=update_fields)

            ReferralRewardEvent.objects.filter(
                referral=referral,
            ).exclude(reward_status='claimed').update(
                reward_status='failed',
                updated_at=now,
            )
            ReferralRewardEvent.objects.filter(
                referral=referral,
                actor_role='referee',
            ).exclude(reward_status='claimed').update(
                error=DUPLICATE_REFEREE_REWARD_ERROR,
                updated_at=now,
            )
            ReferralRewardEvent.objects.filter(
                referral=referral,
                actor_role='referrer',
            ).exclude(reward_status='claimed').update(
                error=DUPLICATE_REFERRER_REWARD_ERROR,
                updated_at=now,
            )

    return {
        'winner_referral_id': winner.id,
        'blocked_referral_ids': [referral.id for referral in blocked_referrals],
    }


def get_duplicate_referee_reward_error(referral: UserReferral | None):
    if not referral or not referral.referred_user_id:
        return None

    from security.models import IdentityVerification

    # Select the latest verified row WITHOUT filtering on its key. The previous
    # .exclude(document_number_normalized='') dropped the malformed row before
    # the fail-closed check could see it, so the function concluded "no verified
    # identity" and returned no error — failing open in exactly the case the
    # check exists for.
    verification = (
        IdentityVerification.objects.filter(
            user_id=referral.referred_user_id,
            status='verified',
        )
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .order_by('-verified_at', '-updated_at', '-created_at')
        .first()
    )
    if not verification:
        # No verified identity yet. Not a duplicate question — the payout gate
        # is what requires verification, and this must not block accrual.
        return None

    person_key = person_key_for(verification)
    has_document_key = has_usable_document_key(verification)

    # Fail CLOSED: a verified row carrying neither a usable document tuple nor
    # a usable person key cannot be deduplicated, so it must not be answered
    # with "no duplicate".
    if not has_document_key and not person_key:
        return INCOMPLETE_IDENTITY_REWARD_ERROR

    result = enforce_referee_reward_uniqueness_for_identity(
        verification.document_issuing_country,
        verification.document_number_normalized,
        person_key,
    )
    if result['winner_referral_id'] and result['winner_referral_id'] != referral.id:
        return DUPLICATE_REFEREE_REWARD_ERROR
    return None


def get_duplicate_referral_reward_error(referral: UserReferral | None, actor_role: str = 'referee'):
    referee_error = get_duplicate_referee_reward_error(referral)
    if not referee_error:
        return None
    if (actor_role or '').lower() == 'referrer':
        return DUPLICATE_REFERRER_REWARD_ERROR
    return referee_error


def get_referrer_claim_verification_error(referral: UserReferral | None):
    if not referral or not referral.referred_user:
        return "No encontramos al referido para esta recompensa."

    referred_user = referral.referred_user
    if referred_user.is_identity_verified:
        return None

    verification_status = (getattr(referred_user, 'verification_status', None) or 'unverified').lower()
    if verification_status == 'pending':
        return (
            "Tu referido ya activó este bono, pero todavía debe terminar su verificación de identidad en Didit "
            "para que puedas reclamar la recompensa."
        )
    return (
        "Tu referido ya activó este bono, pero debe completar su verificación de identidad en Didit "
        "para liberar esta recompensa."
    )


def get_referral_reward_policy_stats():
    """Return verification and review metrics for referral-earned CONFIO."""
    from security.models import IdentityVerification

    earned_by_user = {
        row['user']: row['total']
        for row in get_referral_reward_transactions()
        .values('user')
        .annotate(total=Coalesce(Sum('amount'), Decimal('0')))
    }
    spent_by_user = {
        row['user']: row['total']
        for row in ReferralWithdrawalLog.objects.values('user')
        .annotate(total=Coalesce(Sum('amount'), Decimal('0')))
    }

    available_by_user = {}
    for user_id, earned in earned_by_user.items():
        spent = spent_by_user.get(user_id, Decimal('0')) or Decimal('0')
        available = earned - spent
        if available < Decimal('0'):
            available = Decimal('0')
        available_by_user[user_id] = available

    rewarded_user_ids = set(earned_by_user.keys())
    verified_user_ids = set(
        IdentityVerification.objects.filter(
            status='verified',
            user_id__in=rewarded_user_ids,
        )
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .values_list('user_id', flat=True)
        .distinct()
    )

    verified_available_total = sum(
        available_by_user.get(user_id, Decimal('0'))
        for user_id in rewarded_user_ids
        if user_id in verified_user_ids
    )
    kyc_hold_total = sum(
        available_by_user.get(user_id, Decimal('0'))
        for user_id in rewarded_user_ids
        if user_id not in verified_user_ids
    )

    duplicate_identity_review_users = set(
        IdentityVerification.objects.filter(
            risk_factors__duplicate_identity__isnull=False,
        )
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .values_list('user_id', flat=True)
        .distinct()
    )

    return {
        'rewarded_users': len(rewarded_user_ids),
        'verified_reward_users': len(verified_user_ids),
        'unverified_reward_users': len(rewarded_user_ids - verified_user_ids),
        'verified_available_total': verified_available_total,
        'kyc_hold_total': kyc_hold_total,
        'duplicate_identity_review_users': len(duplicate_identity_review_users),
    }
