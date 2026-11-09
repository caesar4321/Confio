"""Fee referral: the referrer gets half of the 0.9% cUSD perimeter fee.

How it works end to end:

- CusdVault.armReferral(referrer, shareBps) is the first call of a sponsored
  7702 batch. Every perimeter fee charged later in that transaction (direct
  mint/redeem, swap and stock routers, cUSD+ entry/exit) mints `shareBps` of
  the fee to the referrer as cUSD and emits ReferralPaid. The arm lives in
  transient storage, so it ends with the transaction.
- The server decides WHO and HOW MUCH (this module). A batch may carry the
  arm only as its first call and only exactly as `arm_call(eligible_arm(..))`
  builds it; anything else is refused before sponsoring. The contract only
  bounds the share (owner cap <= 50%) and requires our sponsor as tx.origin,
  so a self-built transaction never pays a referrer.
- Commission is paid only while BOTH people are Didit-verified, neither is
  banned, and the referral is younger than FEE_REFERRAL_DAYS (default 365,
  adjustable). Transactions outside that keep the whole fee: nothing is owed
  or paid later.
- The finalized fee scanner records each ReferralPaid as a
  conversion.FeeReferralPayout and pushes the referrer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

WAD = Decimal(10) ** 18
ARM_SIGNATURE = 'armReferral(address,uint256)'
REFERRAL_PAID_SIGNATURE = 'ReferralPaid(address,address,uint256,uint256,uint256)'


def _topic(sig: str) -> str:
    from eth_utils import keccak

    return '0x' + keccak(text=sig).hex()


from .sponsor_7702 import SEL_ARM_REFERRAL  # noqa: E402  (no import cycle: sponsor_7702 never imports this module at load)
REFERRAL_PAID_TOPIC = _topic(REFERRAL_PAID_SIGNATURE)


@dataclass(frozen=True)
class ReferralArm:
    referrer_user_id: int
    referrer_address: str  # lower-case 0x…
    share_bps: int


def _setting_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def enabled() -> bool:
    """Off until the CusdVault upgrade (armReferral) is live on this chain:
    an arm call against the old implementation would revert the batch.

    Requires a valid FEE_REFERRAL_LAUNCH_AT too: switching it on without a
    launch date would pay both the commission and the US$5 bonus, and count
    old referrals' year from sign-up. That misconfiguration stays OFF, loudly."""
    if not _setting_bool(getattr(settings, 'FEE_REFERRAL_ENABLED', False)):
        return False
    launched = launch_at()
    if launched is None:
        logger.error('FEE_REFERRAL_ENABLED is on but FEE_REFERRAL_LAUNCH_AT is missing or invalid: '
                     'fee referral stays off')
        return False
    # Scheduled launch: nothing pays (and the US$5 bonus keeps running) until
    # the instant itself, so the two programs never overlap.
    return timezone.now() >= launched


# CusdVault.MAX_REFERRAL_SHARE_BPS: the immutable ceiling (half the fee).
MAX_SHARE_BPS = 5_000


def share_bps() -> int:
    # The contract hard-caps at 5,000 (and at the owner-set cap below that).
    return max(0, min(int(getattr(settings, 'FEE_REFERRAL_SHARE_BPS', MAX_SHARE_BPS)), MAX_SHARE_BPS))


def commission_share_percent() -> str:
    """'50%' from the share setting, for copy."""
    pct = Decimal(share_bps()) / 100
    return f"{pct.normalize():f}%"


def window_days() -> int:
    return int(getattr(settings, 'FEE_REFERRAL_DAYS', 365))


def launch_at():
    """When the commission program went live (FEE_REFERRAL_LAUNCH_AT, ISO
    datetime), or None. Two rules hang on it: referrals made before it get
    their full year counted from launch, and the US$5 $CONFIO bonus stops
    being granted from it (bonuses already earned are kept)."""
    from django.utils.dateparse import parse_datetime

    raw = getattr(settings, 'FEE_REFERRAL_LAUNCH_AT', None)
    if not raw:
        return None
    when = raw if hasattr(raw, 'tzinfo') else parse_datetime(str(raw))
    if when is not None and timezone.is_naive(when):
        from datetime import timezone as dt_timezone
        when = timezone.make_aware(when, dt_timezone.utc)
    return when


def confio_bonus_ended(at=None) -> bool:
    """The US$5 $CONFIO referral bonus is replaced by the commission: no new
    bonus is granted once the program is live (enabled and past launch)."""
    launched = launch_at()
    return bool(enabled() and launched is not None and (at or timezone.now()) >= launched)


def window_start(referral):
    """A referral's commission year starts when it was made, or at launch
    for relationships that already existed then."""
    launched = launch_at()
    if launched is not None and referral.created_at < launched:
        return launched
    return referral.created_at


def window_ends_at(referral):
    return window_start(referral) + timedelta(days=window_days())


def _cusd_address() -> str:
    return (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()


def _payout_address(user) -> Optional[str]:
    from users.models import Account

    address = (Account.objects.filter(
        user=user, account_type='personal', account_index=0, deleted_at__isnull=True,
    ).values_list('bsc_address', flat=True).first() or '').lower()
    if len(address) != 42 or not address.startswith('0x'):
        return None
    return address


def account_owner(address: str):
    """The person who owns the Confío account at `address`, personal or
    business (a business account's `user` is its owner; employees act on it
    through BusinessEmployee rows and are never its owner), or None."""
    from users.models import Account

    if not address:
        return None
    account = (Account.objects.filter(bsc_address__iexact=address, deleted_at__isnull=True)
               .select_related('user').first())
    return account.user if account else None


def same_person(a, b) -> bool:
    """Evidence that two accounts are one person: a shared KYC'd document
    (issuer, type, number) or Didit's duplicated-face flag on either side
    naming the other. Both directions; expired documents still count."""
    from django.db.models import Q

    from security.models import IdentityVerification

    personal = Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business')
    docs = (IdentityVerification.all_objects.filter(personal)
            .filter(Q(status='verified') | Q(verified_at__isnull=False))
            .exclude(document_number_normalized='')
            .exclude(document_issuing_country__in=['', 'UNK']))
    keys_a = set(docs.filter(user_id=a.pk).values_list(
        'document_issuing_country', 'document_type', 'document_number_normalized'))
    keys_b = set(docs.filter(user_id=b.pk).values_list(
        'document_issuing_country', 'document_type', 'document_number_normalized'))
    if keys_a & keys_b:
        return True
    flagged = IdentityVerification.all_objects.filter(
        user_id__in=[a.pk, b.pk], risk_factors__has_key='duplicated_face',
    ).values_list('user_id', 'risk_factors__duplicated_face')
    for owner, flag in flagged:
        other = b.pk if owner == a.pk else a.pk
        matched = (flag or {}).get('matched_user_ids') if isinstance(flag, dict) else None
        if other in {int(uid) for uid in matched or [] if str(uid).isdigit()}:
            return True
    return False


def _is_banned(user) -> bool:
    from security.utils import check_user_banned

    try:
        return bool(check_user_banned(user)[0])
    except Exception:  # noqa: BLE001 — unknown ban state pays nobody
        logger.warning('fee referral: ban check failed for user %s', user.pk, exc_info=True)
        return True


def live_referral(user):
    """The referee's live referral row with a registered referrer, or None."""
    from achievements.models import UserReferral

    return (UserReferral.objects
            .filter(referred_user=user, deleted_at__isnull=True, referrer_user__isnull=False)
            .select_related('referrer_user')
            .order_by('-created_at')
            .first())


def referral_window_open(referral) -> bool:
    now = timezone.now()
    return window_start(referral) <= now < window_ends_at(referral)


def eligible_arm(user, user_addr: str) -> Optional[ReferralArm]:
    """The arm a fee-bearing batch from `user_addr` should carry now, or None.

    The invitee is whoever OWNS the account moving the money: a person's own
    personal accounts, and the businesses they own (whichever employee acts
    on it). None means "keep the whole fee": no referral, window closed,
    either side unverified or banned, no payout address, or the feature is
    off. `user` is the authenticated actor; it must be the owner or someone
    acting on the owner's business account (the sponsor already bound the
    batch to `user_addr` through its signature)."""
    from security.identity_status import is_identity_verified

    if not enabled() or not _cusd_address() or share_bps() <= 0 or user is None:
        return None
    owner = account_owner(user_addr)
    if owner is None:
        return None
    actor = user
    user = owner  # the invitee is the account's owner
    # (Arms are issued only while CusdVault is ready: callers check
    # onchain_ready(); kept out of here so statuses never need an RPC.)
    referral = live_referral(user)
    if referral is None or not referral_window_open(referral):
        return None
    referrer = referral.referrer_user
    if referrer.pk == user.pk or not referrer.is_active or not user.is_active:
        return None
    if getattr(referrer, 'deleted_at', None) is not None:
        return None
    if not is_identity_verified(user) or not is_identity_verified(referrer):
        return None
    if _is_banned(user) or _is_banned(referrer):
        return None
    if same_person(user, referrer):
        return None  # one person behind both accounts: no self-commission
    if actor is not None and (actor.pk == referrer.pk or same_person(actor, referrer)):
        # The referrer (or another account of the same person) acting as an
        # employee on their invitee's business: they would be steering the
        # business's money to earn the fee themselves.
        return None
    address = _payout_address(referrer)
    if address is None or address == (user_addr or '').lower():
        return None
    return ReferralArm(referrer_user_id=referrer.pk, referrer_address=address, share_bps=share_bps())


def arm_call(arm: ReferralArm) -> dict:
    """The exact normalized call ({'to','value','data'}, lower-case)."""
    data = ('0x' + SEL_ARM_REFERRAL
            + arm.referrer_address[2:].rjust(64, '0')
            + format(arm.share_bps, 'x').rjust(64, '0'))
    return {'to': _cusd_address(), 'value': '0', 'data': data.lower()}


def arm_calls_for(user, user_addr: str) -> list:
    """[arm_call] to prepend to a server-built fee-bearing batch, or []
    (never for an account that is not yet delegated to our batch delegate,
    nor while the vault is not ready: see strip_arm / onchain_ready)."""
    from .sponsor_7702 import is_delegated

    arm = eligible_arm(user, user_addr)
    if arm is None or not onchain_ready():
        return []
    try:
        if not is_delegated(user_addr):
            return []
    except Exception:  # noqa: BLE001 — unknown delegation = no arm
        return []
    return [arm_call(arm)]


def _is_arm(call: dict) -> bool:
    return (call.get('data') or '').lower()[2:10] == SEL_ARM_REFERRAL


READINESS_CACHE_SECONDS = 60


def onchain_ready() -> bool:
    """CusdVault can take an arm right now: the upgrade is live with OUR batch
    delegate set, a cap that covers the share, and the vault not paused. Any
    of those missing would revert every armed batch, so arms are only issued
    (and only accepted) when this is true. Cached briefly; fails closed (no
    arm keeps the whole fee and never blocks anyone)."""
    from django.core.cache import cache

    from .cusd_vault import SEL_PAUSED, _sel, _uint_call
    from .sponsor_7702 import delegate_address

    key = 'fee_referral:onchain_ready'
    cached = cache.get(key)
    if cached is not None:
        return bool(cached)
    try:
        delegate = int(_uint_call(_sel('batchDelegate()'))[0])
        cap = int(_uint_call(_sel('referralShareCapBps()'))[0])
        paused = bool(_uint_call(SEL_PAUSED)[0])
        expected = int((delegate_address() or '0x0'), 16)
        ready = bool(expected) and delegate == expected and cap >= share_bps() and not paused
    except Exception:  # noqa: BLE001 — unknown readiness = not ready
        logger.warning('fee referral readiness check failed', exc_info=True)
        ready = False
    cache.set(key, ready, READINESS_CACHE_SECONDS)
    return ready


def strip_arm(calls: list, user, user_addr: str, *, delegating: bool = False) -> list:
    """Validate an optional leading arm and return the calls without it.

    Every per-flow policy then checks the remaining calls exactly as before.
    The arm is refused anywhere but first, more than once, or with any
    referrer/share other than what eligible_arm says right now."""
    from .sponsor_7702 import PolicyError

    positions = [i for i, c in enumerate(calls) if _is_arm(c)]
    if not positions:
        return calls
    if positions != [0]:
        raise PolicyError('referral_arm_not_first')
    if delegating:
        # First use (or re-delegation): the pre-flight simulates the account
        # with the delegate's runtime code, not the 7702 designator CusdVault
        # checks, so an arm would fail the member's batch. That one batch
        # keeps the whole fee; the app resends it without the arm.
        raise PolicyError('referral_not_delegated')
    if not has_fee_bearing_call(calls[1:]):
        raise PolicyError('referral_not_needed')
    expected = eligible_arm(user, user_addr)
    if expected is None or not onchain_ready():
        raise PolicyError('referral_not_allowed')
    first = calls[0]
    normalized = {
        'to': (first.get('to') or '').lower(),
        'value': str(int(first.get('value') or 0)),
        'data': (first.get('data') or '').lower(),
    }
    if normalized != arm_call(expected):
        raise PolicyError('referral_not_allowed')
    return calls[1:]


# Calls whose execution charges a cUSD perimeter fee on the user's behalf:
# direct mint/redeem, cUSD+ entry/exit, and the swap and stock routers (they
# cross the perimeter inside). An arm on any other batch earns nothing.
def _fee_bearing_selectors() -> set:
    from .crypto_policy import SEL_CRYPTO_BUY, SEL_CRYPTO_SELL
    from .sponsor_7702 import (SEL_CUSD_MINT, SEL_CUSD_REDEEM, SEL_REDEEM_TO_USDT,
                               SEL_STOCK_BUY, SEL_STOCK_SELL, SEL_SUBSCRIBE_AND_MINT)

    return {SEL_CUSD_MINT, SEL_CUSD_REDEEM, SEL_REDEEM_TO_USDT, SEL_SUBSCRIBE_AND_MINT,
            SEL_STOCK_BUY, SEL_STOCK_SELL, SEL_CRYPTO_BUY, SEL_CRYPTO_SELL}


def has_fee_bearing_call(calls: list) -> bool:
    selectors = _fee_bearing_selectors()
    return any((c.get('data') or '').lower()[2:10] in selectors for c in calls)


def strip_stored_arm(calls: list) -> list:
    """For batches the SERVER already decided: calls stored by send's
    prepare, or an exact replay of a batch already recorded. Neither is
    re-decided against today's eligibility or share setting: a replay must
    get its transaction back, and a prepared send must not strand PENDING.
    Only the shape is checked: first, to the cUSD vault, share within the
    contract's fixed 50% ceiling (the contract no-ops anything above its
    live cap). Residual: a send prepared while eligible and submitted much
    later can still pay that one commission; the member paid the full fee,
    so nobody profits from holding one."""
    from .sponsor_7702 import PolicyError

    positions = [i for i, c in enumerate(calls) if _is_arm(c)]
    if not positions:
        return calls
    if positions != [0]:
        raise PolicyError('referral_arm_not_first')
    first = calls[0]
    data = (first.get('data') or '').lower()
    if ((first.get('to') or '').lower() != _cusd_address() or int(first.get('value') or 0) != 0
            or len(data) != 2 + 8 + 128 or data[10:34] != '0' * 24
            or not 0 < int(data[74:138], 16) <= MAX_SHARE_BPS):
        raise PolicyError('referral_not_allowed')
    return calls[1:]


# ── recording (finalized scanner) ────────────────────────────────────────

def _addr_from_topic(topic) -> str:
    word = str(topic or '').lower()
    return '0x' + word[-40:] if len(word) == 66 else ''


def referral_paid_events(logs: list) -> list:
    cusd = _cusd_address()
    out = []
    for log in logs or []:
        if (log.get('address') or '').lower() != cusd:
            continue
        topics = log.get('topics') or []
        if len(topics) < 3 or str(topics[0]).lower() != REFERRAL_PAID_TOPIC:
            continue
        body = (log.get('data') or '').removeprefix('0x')
        if len(body) < 192:
            continue
        fee, share, bps = (int(body[i:i + 64], 16) for i in range(0, 192, 64))
        if share <= 0 or share > fee or bps > 5_000:
            continue
        try:
            index = int(log.get('logIndex', '0x0'), 16)
            block = int(log.get('blockNumber', '0x0'), 16)
        except (TypeError, ValueError):
            continue
        out.append({
            'log_index': index, 'block_number': block,
            'referee_address': _addr_from_topic(topics[1]),
            'referrer_address': _addr_from_topic(topics[2]),
            'fee_wei': fee, 'share_wei': share, 'share_bps': bps,
        })
    return out


def _user_for_address(address: str):
    from users.models import Account

    account = (Account.objects.filter(bsc_address__iexact=address, deleted_at__isnull=True)
               .select_related('user').first())
    return account.user if account else None


def record_referral_payouts(tx_hash: str, logs: list, block_times: dict) -> list:
    """Store each ReferralPaid in `logs` (one tx) once; push each new one.
    Returns the newly created payout rows."""
    from django.db import transaction

    from conversion.models import FeeReferralPayout

    created_rows = []
    for event in referral_paid_events(logs):
        referee = _user_for_address(event['referee_address'])
        referrer = _user_for_address(event['referrer_address'])
        # The ledger row and the referrer's history card commit together, and
        # a failure RAISES: the fee scanner then retries without advancing its
        # cursor. A replay re-applies the (idempotent) history card too, so a
        # card can never be lost behind an existing ledger row.
        with transaction.atomic():
            row, created = FeeReferralPayout.objects.get_or_create(
            tx_hash=tx_hash.lower(), log_index=event['log_index'],
                defaults={
                    'block_number': event['block_number'],
                    'block_time': block_times.get(event['block_number']),
                    'referee_address': event['referee_address'],
                    'referrer_address': event['referrer_address'],
                    'referee_user': referee,
                    'referrer_user': referrer,
                    'fee_wei': event['fee_wei'],
                    'share_wei': event['share_wei'],
                    'share_bps': event['share_bps'],
                },
            )
            record_history(row)
        if created:
            created_rows.append(row)
    for row in created_rows:
        try:
            notify_payout(row)
        except Exception:  # noqa: BLE001 — a push never blocks the ledger
            logger.warning('fee referral push failed for %s#%s', row.tx_hash, row.log_index, exc_info=True)
    return created_rows


# ── history ─────────────────────────────────────────────────────────────

def referrer_timezone(user):
    """The referrer's own time zone, as "Tu mes" resolves it (country first:
    User.country already falls back to the phone country)."""
    from users.cashflow import resolve_timezone

    return resolve_timezone(None, getattr(user, 'country', None) or getattr(user, 'phone_country', None))


def payout_day(row, tz=None):
    """The referrer's local calendar day a payout belongs to."""
    tz = tz or referrer_timezone(row.referrer_user)
    return timezone.localtime(row.block_time or row.created_at, tz).date()


def history_reference(user_id, day) -> str:
    # payment_reference_id is varchar(32): 'feeref:<user>:<yyyymmdd>'.
    return f'feeref:{user_id}:{day:%Y%m%d}'


def record_history(row) -> None:
    """The referrer's wallet history shows ONE row per day for all of that
    day's commissions ("Comisiones por invitar · 3 pagos"), opening Tus
    comisiones; each payout is listed there, not in the wallet. Recomputed
    from the ledger, so replays and repairs converge. No friend is named."""
    from datetime import datetime, time

    from django.db.models import Max, Sum
    from django.db.models.functions import Coalesce

    from conversion.models import FeeReferralPayout
    from users.models_unified import UnifiedTransactionTable

    user = row.referrer_user
    if user is None:
        return
    tz = referrer_timezone(user)
    day = payout_day(row, tz)
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = start + timedelta(days=1)
    rows = (FeeReferralPayout.objects.filter(referrer_user=user)
            .annotate(paid_at=Coalesce('block_time', 'created_at'))
            .filter(paid_at__gte=start, paid_at__lt=end))
    agg = rows.aggregate(total=Sum('share_wei'), last=Max('paid_at'))
    count = rows.count()
    # amount is varchar(32): 18 decimals of a wei total always fit.
    total = (Decimal(agg['total'] or 0) / WAD).quantize(Decimal('0.000000000000000001')).normalize()
    label = 'Comisiones por invitar' if count != 1 else 'Comisión por invitar'
    UnifiedTransactionTable.objects.update_or_create(
        transaction_type='commission',
        payment_reference_id=history_reference(user.pk, day),
        defaults={
            'amount': format(total, 'f'),  # never '9E+1
            'token_type': 'CUSD_BSC',
            'status': 'CONFIRMED',
            'transaction_hash': '',
            'sender_type': 'external',
            'sender_display_name': label,
            'sender_address': _cusd_address(),
            'counterparty_user': user,
            'counterparty_type': 'user',
            'counterparty_display_name': user.get_full_name() or user.username or 'Tú',
            'counterparty_address': row.referrer_address,
            'description': f'{label} · {count} {"pago" if count == 1 else "pagos"}',
            'from_address': _cusd_address(),
            'to_address': row.referrer_address,
            'transaction_date': agg['last'] or row.created_at,
        },
    )


# ── push ────────────────────────────────────────────────────────────────

def format_usd(amount: Decimal) -> str:
    """App amount grammar (savingsFormat.ts): >= 1 cent 2dp, under a cent
    3dp (US$0.004), never a misleading US$0.00 for a real payout."""
    if amount >= Decimal('0.01'):
        return f"US${amount.quantize(Decimal('0.01')):,}"
    if amount <= 0:
        return 'US$0.00'
    if amount < Decimal('0.0005'):
        return 'menos de US$0.001'
    return f"US${amount.quantize(Decimal('0.001')):f}"


def total_earned(user) -> Decimal:
    from django.db.models import Sum

    from conversion.models import FeeReferralPayout

    total = (FeeReferralPayout.objects.filter(referrer_user=user)
             .aggregate(total=Sum('share_wei'))['total'] or 0)
    return Decimal(total) / WAD


# ── the referrer's view (invite screens) ────────────────────────────────

# The dashboard lists at most this many invitations (newest first); totals
# and counts always cover all of them.
FRIENDS_LIST_MAX = 200

FRIEND_EARNING = 'earning'
FRIEND_NEEDS_FRIEND_VERIFICATION = 'needs_friend_verification'
FRIEND_NEEDS_YOUR_VERIFICATION = 'needs_your_verification'
FRIEND_ENDED = 'ended'
FRIEND_UNAVAILABLE = 'unavailable'


def _live_banned_ids(user_ids) -> set:
    """security.utils.check_user_banned, in bulk."""
    from security.models import UserBan

    return set(UserBan.objects.filter(user_id__in=user_ids, deleted_at__isnull=True)
               .exclude(ban_type='temporary', expires_at__lt=timezone.now())
               .values_list('user_id', flat=True))


def _same_person_ids(referrer, friend_ids) -> set:
    """same_person(referrer, friend) for many friends in three queries."""
    from django.db.models import Q

    from security.models import IdentityVerification

    personal = Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business')
    docs = (IdentityVerification.all_objects.filter(personal)
            .filter(Q(status='verified') | Q(verified_at__isnull=False))
            .exclude(document_number_normalized='')
            .exclude(document_issuing_country__in=['', 'UNK']))
    key = ('document_issuing_country', 'document_type', 'document_number_normalized')
    mine = set(docs.filter(user_id=referrer.pk).values_list(*key))
    out = set()
    if mine:
        for uid, *k in docs.filter(user_id__in=friend_ids).values_list('user_id', *key):
            if tuple(k) in mine:
                out.add(uid)
    friend_set = set(friend_ids)
    flagged = IdentityVerification.all_objects.filter(
        user_id__in=[referrer.pk, *friend_ids], risk_factors__has_key='duplicated_face',
    ).values_list('user_id', 'risk_factors__duplicated_face')
    for owner, flag in flagged:
        matched = (flag or {}).get('matched_user_ids') if isinstance(flag, dict) else None
        ids = {int(uid) for uid in matched or [] if str(uid).isdigit()}
        if owner == referrer.pk:
            out |= ids & friend_set
        elif referrer.pk in ids:
            out.add(owner)
    return out


def friend_statuses(referrer, referrals=None) -> list:
    """Every live referral this member made, with why it does or doesn't
    earn commission right now (eligible_arm's rules, bulk-loaded: a fixed
    handful of queries however many friends). Friends appear by their
    public @usuario and WITHOUT per-friend earnings: a named amount would
    reveal that friend's transaction volume (the totals stay aggregate)."""
    from achievements.models import UserReferral
    from security.identity_status import is_identity_verified, verified_user_ids

    if referrals is None:
        referrals = (UserReferral.objects
                     .filter(referrer_user=referrer, deleted_at__isnull=True)
                     .select_related('referred_user').order_by('-created_at', '-pk'))
    referrals = [r for r in referrals if r.referred_user is not None and r.referred_user.is_active]
    friend_ids = [r.referred_user_id for r in referrals]
    if not friend_ids:
        return []
    verified = set(verified_user_ids(friend_ids))
    banned = _live_banned_ids(friend_ids)
    same = _same_person_ids(referrer, friend_ids)
    referrer_verified = is_identity_verified(referrer)
    referrer_blocked = _is_banned(referrer)
    out = []
    for referral in referrals:
        friend = referral.referred_user
        if not referral_window_open(referral):
            status = FRIEND_ENDED
        elif referrer_blocked or friend.pk in banned or friend.pk in same:
            status = FRIEND_UNAVAILABLE
        elif not referrer_verified:
            status = FRIEND_NEEDS_YOUR_VERIFICATION
        elif friend.pk not in verified:
            status = FRIEND_NEEDS_FRIEND_VERIFICATION
        else:
            status = FRIEND_EARNING
        out.append({
            'user_id': friend.pk,
            'referral_id': referral.pk,
            'display_name': f'@{friend.username}',
            'status': status,
            'ends_at': window_ends_at(referral),
            'can_remind': status == FRIEND_NEEDS_FRIEND_VERIFICATION and reminder_allowed(referral),
        })
    return out


# ── "Recordarle": a referrer nudges an unverified friend ────────────────

REMINDER_EVERY = timedelta(days=7)
REMINDER_KEY = 'fee_referral_reminded_at'


def reminder_allowed(referral) -> bool:
    from django.utils.dateparse import parse_datetime

    last = parse_datetime(str((referral.attribution_data or {}).get(REMINDER_KEY) or ''))
    return last is None or timezone.now() - last >= REMINDER_EVERY


class ReminderError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def remind_friend(referrer, referral_id) -> None:
    """Push the invited friend a verification reminder from their inviter,
    at most once a week per friend. The friend already knows who invited
    them, so naming the inviter reveals nothing; nothing about the inviter's
    earnings is sent."""
    from django.db import transaction

    from achievements.models import UserReferral
    from notifications.models import NotificationType
    from notifications.utils import create_notification
    from security.identity_status import is_identity_verified

    with transaction.atomic():
        referral = (UserReferral.objects.select_for_update()
                    .select_related('referred_user')
                    .filter(pk=referral_id, referrer_user=referrer, deleted_at__isnull=True).first())
        if referral is None or referral.referred_user is None or not referral.referred_user.is_active:
            raise ReminderError('not_found')
        if is_identity_verified(referral.referred_user):
            raise ReminderError('already_verified')
        status = next((f['status'] for f in friend_statuses(referrer, [referral])), None)
        if status != FRIEND_NEEDS_FRIEND_VERIFICATION:
            # Same rule as can_remind: no nudges for ended windows, banned or
            # same-person pairs, or from a referrer who must verify first.
            raise ReminderError('not_allowed')
        if not reminder_allowed(referral):
            raise ReminderError('too_soon')
        data = dict(referral.attribution_data or {})
        data[REMINDER_KEY] = timezone.now().isoformat()
        referral.attribution_data = data
        referral.save(update_fields=['attribution_data'])
    forget_friend_statuses(referrer)  # can_remind changed
    handle = f'@{referrer.username}' if referrer.username else 'Quien te invitó'
    create_notification(
        user=referral.referred_user,
        notification_type=NotificationType.REFERRAL_ACTION_REMINDER,
        title='Verifica tu identidad',
        message=f'{handle} te recuerda verificar tu identidad en Confío. Toma unos minutos y desbloquea todo en la app.',
        data={'referral_id': referral.pk},
        action_url='confio://verification',
    )


# ── dashboard: the invitee list (searchable, paginated) and monthly totals ─

# Status groups the dashboard filters by.
FRIEND_GROUPS = {
    'earning': {FRIEND_EARNING},
    'waiting': {FRIEND_NEEDS_FRIEND_VERIFICATION},
    'you': {FRIEND_NEEDS_YOUR_VERIFICATION},
    'none': {FRIEND_ENDED, FRIEND_UNAVAILABLE},
}


def group_counts(statuses: list) -> dict:
    counts = {group: 0 for group in FRIEND_GROUPS}
    for friend in statuses:
        for group, members in FRIEND_GROUPS.items():
            if friend['status'] in members:
                counts[group] += 1
    return counts


STATUSES_CACHE_SECONDS = 45


def cached_friend_statuses(referrer) -> list:
    """friend_statuses for the dashboard, cached briefly per referrer: paging,
    search keystrokes and the summary would otherwise recompute it for every
    invitation on each request (thousands for a creator)."""
    from django.core.cache import cache

    key = f'fee_referral:statuses:{referrer.pk}'
    cached = cache.get(key)
    if cached is None:
        cached = friend_statuses(referrer)
        cache.set(key, cached, STATUSES_CACHE_SECONDS)
    return cached


def forget_friend_statuses(referrer) -> None:
    from django.core.cache import cache

    cache.delete(f'fee_referral:statuses:{referrer.pk}')


def friends_page(referrer, *, group: str = '', search: str = '', limit: int = 30, offset: int = 0):
    """(total, page) of this member's invitations, newest first, optionally
    one status group and an @usuario search. Every invitation is reachable
    however many there are (statuses are bulk-computed in a fixed number of
    queries, cached briefly; filtering and paging happen in memory)."""
    statuses = cached_friend_statuses(referrer)
    if group in FRIEND_GROUPS:
        statuses = [f for f in statuses if f['status'] in FRIEND_GROUPS[group]]
    needle = (search or '').strip().lstrip('@').lower()
    if needle:
        statuses = [f for f in statuses if needle in f['display_name'].lstrip('@').lower()]
    limit = max(1, min(int(limit or 30), 100))
    offset = max(0, int(offset or 0))
    return len(statuses), statuses[offset:offset + limit]


def monthly_totals(user, months: int = 6) -> list:
    """[(YYYY-MM, Decimal)] for the last `months` calendar months in the
    referrer's own time zone, oldest first, zero months included. Summed in
    the database (one row per month)."""
    from datetime import datetime, time

    from django.db.models import Sum
    from django.db.models.functions import Coalesce, TruncMonth

    from conversion.models import FeeReferralPayout

    tz = referrer_timezone(user)
    now = timezone.localtime(timezone.now(), tz)
    keys = []
    year, month = now.year, now.month
    for _ in range(months):
        keys.append(f'{year:04d}-{month:02d}')
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    keys.reverse()
    first_year, first_month = (int(part) for part in keys[0].split('-'))
    start = timezone.make_aware(datetime.combine(now.date().replace(year=first_year, month=first_month, day=1),
                                                 time.min), tz)
    totals = {key: 0 for key in keys}
    rows = (FeeReferralPayout.objects.filter(referrer_user=user)
            .annotate(paid_at=Coalesce('block_time', 'created_at'))
            .filter(paid_at__gte=start)
            .annotate(month=TruncMonth('paid_at', tzinfo=tz))
            .values('month').annotate(total=Sum('share_wei')))
    for row in rows:
        key = timezone.localtime(row['month'], tz).strftime('%Y-%m')
        if key in totals:
            totals[key] += int(row['total'] or 0)
    return [(key, Decimal(totals[key]) / WAD) for key in keys]


def month_bounds(user, month: str):
    """(start, end) of a 'YYYY-MM' calendar month in the referrer's own time
    zone (the same buckets as monthly_totals), or None if malformed."""
    import re
    from datetime import datetime, time

    match = re.fullmatch(r'(\d{4})-(\d{2})', (month or '').strip())
    if not match:
        return None
    year, mon = int(match.group(1)), int(match.group(2))
    if not 1 <= mon <= 12:
        return None
    tz = referrer_timezone(user)
    next_year, next_month = (year + 1, 1) if mon == 12 else (year, mon + 1)
    try:
        start = timezone.make_aware(datetime(year, mon, 1), tz)
        end = timezone.make_aware(datetime.combine(datetime(next_year, next_month, 1).date(), time.min), tz)
    except (ValueError, OverflowError):  # year 0000, 9999-12 and the like
        return None
    return start, end


def payouts_page(user, limit: int, offset: int, month: str = '') -> list:
    """This member's own commissions, newest first, optionally one calendar
    month ('YYYY-MM', referrer's time zone): amount and time only (no friend,
    no transaction, no hash). A malformed month returns nothing."""
    from django.db.models.functions import Coalesce

    from conversion.models import FeeReferralPayout

    limit = max(1, min(int(limit or 30), 100))
    offset = max(0, int(offset or 0))
    rows = (FeeReferralPayout.objects.filter(referrer_user=user)
            .annotate(paid_at=Coalesce('block_time', 'created_at')))
    if month:
        bounds = month_bounds(user, month)
        if bounds is None:
            return []
        rows = rows.filter(paid_at__gte=bounds[0], paid_at__lt=bounds[1])
    rows = rows.order_by('-paid_at', '-pk')[offset:offset + limit]
    # Local date/time in the referrer's own time zone (the same zone as the
    # month buckets), so the app's day headers never disagree with them.
    tz = referrer_timezone(user)
    out = []
    for r in rows:
        local = timezone.localtime(r.paid_at, tz)
        out.append({'id': r.pk, 'amount': Decimal(r.share_wei) / WAD, 'paid_at': r.paid_at,
                    'local_date': local.strftime('%Y-%m-%d'), 'local_time': local.strftime('%H:%M')})
    return out


def month_total(user) -> Decimal:
    """This calendar month's commission by when it was PAID on-chain
    (block_time; scan time only when the block time is unknown)."""
    from django.db.models import Sum
    from django.db.models.functions import Coalesce

    from conversion.models import FeeReferralPayout

    now = timezone.localtime(timezone.now(), referrer_timezone(user))
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (FeeReferralPayout.objects
             .filter(referrer_user=user)
             .annotate(paid_at=Coalesce('block_time', 'created_at'))
             .filter(paid_at__gte=start)
             .aggregate(total=Sum('share_wei'))['total'] or 0)
    return Decimal(total) / WAD


def notify_payout(row) -> None:
    """One push per commission: this one and the month so far. The friend is
    not named: the share reveals the size of their transaction."""
    from notifications.models import NotificationType
    from notifications.utils import create_notification

    user = row.referrer_user
    if user is None or row.notified_at is not None:
        return
    share = Decimal(row.share_wei) / WAD
    total = month_total(user)
    create_notification(
        user=user,
        notification_type=NotificationType.REFERRAL_COMMISSION_EARNED,
        title='Ganaste una comisión',
        message=f'+{format_usd(share)} por la actividad de un amigo invitado · Este mes: {format_usd(total)}',
        # No tx hash: it would hand the inviter the friend's transaction (and
        # with it the operation type), which the app never shows.
        data={
            'share_usd': str(share),
            'month_total_usd': str(total),
        },
        related_object_type='FeeReferralPayout',
        related_object_id=str(row.pk),
        # Opens the referral program (its commission card) from a push on
        # every build: messagingService routes confio://achievements.
        action_url='confio://achievements',
    )
    type(row).objects.filter(pk=row.pk, notified_at__isnull=True).update(notified_at=timezone.now())
