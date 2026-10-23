"""What a team page shows: members with their returns, the team's holdings
(who holds what, never amounts), its plays (members' trades while on the
team, never amounts) and the goal's progress.

Everything here is investment data, so it is only ever served to viewers
whose own profile is public and verified (inbox.community.portfolio_access
reciprocity); the schema checks that before calling in.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from inbox.member_portfolio import personal_wallet

from . import league
from .models import TeamGoal, TeamGoalKind, TeamMembership

logger = logging.getLogger(__name__)

STOCK_KINDS = ('stock_buy', 'stock_sell')
CRYPTO_KINDS = ('crypto_buy', 'crypto_sell')
PLAYS_LIMIT = 50
# Copy play: only recent buys can be copied.
COPY_WINDOW = timedelta(days=7)


def _members(team):
    return list(TeamMembership.objects.filter(team=team, left_at__isnull=True).select_related('user')
                .order_by('joined_at', 'id'))


def _visible(team, exclude=()):
    """Members whose investment data may be shown right now (verified,
    public, not banned), minus anyone in `exclude` (the viewer's blocks):
    nobody else contributes to plays, holdings or returns."""
    from .eligibility import eligible_user_ids

    rows = [m for m in _members(team) if m.user_id not in set(exclude)]
    allowed = eligible_user_ids([m.user_id for m in rows])
    return [m for m in rows if m.user_id in allowed]


def _visible_at(team, day):
    """Members on the team at the end of `day` (who were there then),
    still eligible to be counted now."""
    from django.db.models import Q

    from .eligibility import eligible_user_ids

    end = league.day_end(day)
    rows = list(TeamMembership.objects.filter(team=team, joined_at__lt=end)
                .filter(Q(left_at__isnull=True) | Q(left_at__gte=end)).select_related('user'))
    allowed = eligible_user_ids([m.user_id for m in rows])
    return [m for m in rows if m.user_id in allowed]


def _returns(user_ids, days) -> dict:
    """{user_id: percent} over complete proven days of each member's one
    wallet: the same numbers the league uses. Missing = unknown."""
    from inbox.models import PortfolioDailySnapshot

    from .eligibility import canonical_wallets

    wallets = canonical_wallets(user_ids)
    per: dict = {}
    for wallet, day, ret, trusted in PortfolioDailySnapshot.objects.filter(
            wallet__in=list(wallets.values()), day__in=days).values_list('wallet', 'day', 'daily_return', 'ledger_trusted'):
        per.setdefault(wallet, {})[day] = ret if trusted else None
    out = {}
    for user_id, wallet in wallets.items():
        rows = per.get(wallet, {})
        if days and all(rows.get(day) is not None for day in days):
            growth = Decimal('1')
            for day in days:
                growth *= 1 + rows[day]
            out[user_id] = (growth - 1) * 100
    return out


def members(team, range_key='7d'):
    """[(membership, pct or None)] ordered captain first, then by return.
    Returns only for members who may be shown."""
    days = league.window(range_key)
    visible = {m.user_id for m in _visible(team)}
    returns = _returns(visible, days)
    out = [(m, returns.get(m.user_id)) for m in _members(team)]
    out.sort(key=lambda pair: (pair[0].role != 'captain', -(pair[1] if pair[1] is not None else Decimal('-1e9'))))
    return out


def _names():
    from inbox.member_portfolio import _market

    try:
        return _market()
    except Exception:  # noqa: BLE001
        logger.warning('teams: market names unavailable', exc_info=True)
        return {}


def positions(team, exclude=()) -> list[dict]:
    """[{symbol, ticker, name, holders}] from the stored holdings scans:
    how many members hold each asset. Never units or values."""
    from blockchain.models import CryptoHoldings, StockHoldings
    from cusd_plus.crypto_catalog import by_symbol

    from .eligibility import canonical_wallets

    wallets = list(canonical_wallets([m.user_id for m in _visible(team, exclude)]).values())
    holders: dict = {}
    for row in StockHoldings.objects.filter(bsc_address__in=wallets):
        for symbol, units in (row.held or {}).items():
            try:
                if Decimal(str(units)) > 0:
                    holders.setdefault(('stock', symbol), set()).add(row.bsc_address)
            except Exception:  # noqa: BLE001
                continue
    for row in CryptoHoldings.objects.filter(bsc_address__in=wallets):
        for symbol, base in (row.held or {}).items():
            if str(base) not in ('', '0'):
                holders.setdefault(('crypto', symbol), set()).add(row.bsc_address)
    market = _names()
    out = []
    for (kind, symbol), owners in holders.items():
        if kind == 'stock':
            info = market.get(symbol) or {}
            ticker, name = info.get('ticker') or symbol.removesuffix('on'), info.get('name') or symbol
        else:
            token = by_symbol(symbol, include_unlisted=True)
            ticker = token.ticker if token else symbol
            name = 'Oro' if symbol == 'XAUT' else (getattr(token, 'name', '') or ticker)
        out.append({'symbol': symbol, 'asset': kind, 'ticker': ticker, 'name': name, 'holders': len(owners)})
    out.sort(key=lambda p: (-p['holders'], p['ticker']))
    return out


def plays(team, limit: int = PLAYS_LIMIT, exclude=()) -> list[dict]:
    """Members' confirmed trades made while on the team, newest first:
    who, buy/sell, what, when. Never amounts."""
    from blockchain.models import CryptoTrade, SponsoredBatch
    from cusd_plus.stock_month import _decode_trades

    from .eligibility import canonical_wallets

    visible = _visible(team, exclude)
    wallets = canonical_wallets([m.user_id for m in visible])
    by_wallet = {wallets[m.user_id]: m for m in visible if m.user_id in wallets}
    if not by_wallet:
        return []
    from django.db.models.functions import Lower

    earliest = min(m.joined_at for m in by_wallet.values())
    batches = list(SponsoredBatch.objects.annotate(addr=Lower('user_bsc_address')).filter(
        addr__in=list(by_wallet), kind__in=STOCK_KINDS + CRYPTO_KINDS, status='confirmed',
        created_at__gte=earliest).select_related('unified_transaction').order_by('-created_at')[:limit * 2])
    crypto_symbols = dict(CryptoTrade.objects.filter(batch__in=[b for b in batches if b.kind in CRYPTO_KINDS])
                          .values_list('batch_id', 'symbol'))
    market = _names()
    out = []
    for batch in batches:
        member = by_wallet.get(batch.user_bsc_address.lower())
        if member is None or batch.created_at < member.joined_at:
            continue
        if batch.kind in STOCK_KINDS:
            decoded = _decode_trades([batch])
            symbol = decoded[0].symbol if decoded else ''
            if not symbol or symbol.startswith('?'):
                continue
            info = market.get(symbol) or {}
            ticker = info.get('ticker') or symbol.removesuffix('on')
            name = info.get('name') or ticker
            asset = 'stock'
        else:
            symbol = crypto_symbols.get(batch.id) or ''
            if not symbol:
                continue
            ticker = symbol
            name = 'Oro' if symbol == 'XAUT' else symbol
            asset = 'crypto'
        out.append({
            'id': batch.id, 'user': member.user, 'side': 'buy' if batch.kind.endswith('_buy') else 'sell',
            'symbol': symbol, 'ticker': ticker, 'name': name, 'asset': asset, 'at': batch.created_at,
            'copyable': batch.kind.endswith('_buy') and timezone.now() - batch.created_at <= COPY_WINDOW,
        })
        if len(out) >= limit:
            break
    return out


# ── team goal (#9) ─────────────────────────────────────────────────────

MIN_TARGET = {TeamGoalKind.INVESTED_USD: Decimal('100'), TeamGoalKind.WEEKLY_INVESTORS: Decimal('3')}


def current_goal(team):
    return TeamGoal.objects.filter(team=team, replaced_at__isnull=True).first()


# An amount goal is only shown when this many members contribute: with
# fewer, the total would reveal one person's balance.
MIN_CONTRIBUTORS = 3


# After someone joins or leaves (or the goal is set), an amount goal stays
# hidden this long, so comparing before and after can't single anyone out.
ROSTER_QUIET = timedelta(hours=24)
COARSE_STEP = 10
AMOUNT_STEP = 100
GOAL_CHANGE_EVERY = timedelta(days=7)


def roster_changed_recently(team) -> bool:
    from django.db.models import Q

    since = timezone.now() - ROSTER_QUIET
    return (TeamMembership.objects.filter(team=team).filter(Q(joined_at__gte=since) | Q(left_at__gte=since)).exists()
            or TeamGoal.objects.filter(team=team, created_at__gte=since).exists())


def coarse_percent(percent: int) -> int:
    """Progress in steps of COARSE_STEP, rounded down (100 only when reached)."""
    return min(100, (int(percent) // COARSE_STEP) * COARSE_STEP)


def goal_contributors(team) -> int:
    """Members with money actually in the sleeve (a proven snapshot above
    zero): the people an amount total is made of."""
    from inbox.models import PortfolioDailySnapshot

    from .eligibility import canonical_wallets

    count = 0
    for wallet in canonical_wallets([m.user_id for m in _visible(team)]).values():
        latest = (PortfolioDailySnapshot.objects.filter(wallet=wallet, ledger_trusted=True)
                  .order_by('-day').values_list('value_end_usd', flat=True).first())
        if latest and latest > 0:
            count += 1
    return count


def goal_progress(team, goal, as_of=None) -> Decimal:
    from blockchain.models import SponsoredBatch
    from inbox.models import PortfolioDailySnapshot

    from .eligibility import canonical_wallets

    members_list = _visible(team) if as_of is None else _visible_at(team, as_of)
    if goal.kind == TeamGoalKind.INVESTED_USD:
        total = Decimal('0')
        for wallet in canonical_wallets([m.user_id for m in members_list]).values():
            rows = PortfolioDailySnapshot.objects.filter(wallet=wallet, ledger_trusted=True)
            if as_of is not None:
                rows = rows.filter(day__lte=as_of)
            row = rows.order_by('-day').values_list('value_end_usd', flat=True).first()
            total += row or Decimal('0')
        return total
    now = timezone.now() if as_of is None else league.day_end(as_of) - timedelta(microseconds=1)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    cutoff = None
    if as_of is not None:
        # Nothing after the day being checked (a deadline mid-week).
        cutoff = league.day_end(as_of)
        week_end = min(week_end, cutoff)
    from django.db.models.functions import Lower

    from cusd_plus.crypto_holdings import IN_FLIGHT_MAX_AGE as CRYPTO_IN_FLIGHT
    from cusd_plus.gm_holdings import IN_FLIGHT_MAX_AGE as STOCK_IN_FLIGHT

    # The longest time a buy can take to settle (crypto swaps: 35 min):
    # anything submitted that close to a boundary is placed by its block.
    IN_FLIGHT_MAX_AGE = max(STOCK_IN_FLIGHT, CRYPTO_IN_FLIGHT)
    wallets = list(canonical_wallets([m.user_id for m in members_list]).values())
    # From a few minutes before the week: a buy submitted on Sunday night
    # that landed on Monday belongs to Monday's week (by its block time).
    batches = (SponsoredBatch.objects.annotate(addr=Lower('user_bsc_address')).filter(
        addr__in=wallets, kind__in=('stock_buy', 'crypto_buy'), status='confirmed',
        created_at__gte=week_start - IN_FLIGHT_MAX_AGE, created_at__lt=week_end))
    active = set()
    times: dict = {}
    for addr, created, block in batches.values_list('addr', 'created_at', 'block_number'):
        if created < week_start:
            settled = _block_time(block, times)
            if settled is None or settled < week_start:
                continue
        if cutoff is not None and created >= cutoff - IN_FLIGHT_MAX_AGE:
            # Submitted in the last minutes before the cutoff: counts only if
            # its block landed in time (the block's own timestamp; unknown =
            # not counted).
            settled = _block_time(block, times)
            if settled is None or settled >= cutoff:
                continue
        active.add(addr)
    return Decimal(len(active))


def _block_time(block, cache: dict):
    if block is None:
        return None
    from cusd_plus.fee_ledger import block_time
    from cusd_plus.tasks import _rpc

    return block_time(_rpc, block, cache)


def refresh_goal(team, goal) -> tuple[Decimal, int]:
    """(progress, percent of target) and freeze reached_at the first time the
    target is met before the deadline."""
    progress = goal_progress(team, goal)
    pct = int(min(progress / goal.target * 100, Decimal('100'))) if goal.target > 0 else 0
    today = league.utc_today()
    if goal.reached_at is None:
        met = progress >= goal.target and (goal.deadline is None or today <= goal.deadline)
        if not met:
            # A check that came late still counts what happened in time: the
            # last day before the deadline, or (weekly) the week that just ended.
            yesterday = today - timedelta(days=1)
            day = min(yesterday, goal.deadline) if goal.deadline else yesterday
            if day >= goal.created_at.date() and goal_progress(team, goal, as_of=day) >= goal.target:
                met = True
        if met:
            TeamGoal.objects.filter(id=goal.id, reached_at__isnull=True).update(reached_at=timezone.now())
            goal.reached_at = timezone.now()
    return progress, pct


def set_goal(captain, team, kind: str, target, deadline=None):
    from django.db import transaction

    from inbox.community import CommunityPostError

    if kind not in TeamGoalKind.values:
        raise CommunityPostError('bad_goal', 'Elige un tipo de meta.')
    try:
        target = Decimal(str(target)).quantize(Decimal('0.01'))
    except Exception:  # noqa: BLE001
        raise CommunityPostError('bad_goal', 'Escribe una meta válida.')
    if not target.is_finite() or target < MIN_TARGET[kind] or target > Decimal('10000000'):
        minimum = '$100' if kind == TeamGoalKind.INVESTED_USD else '3 miembros'
        raise CommunityPostError('bad_goal', f'La meta mínima es {minimum}.')
    if kind == TeamGoalKind.WEEKLY_INVESTORS and target != target.to_integral_value():
        raise CommunityPostError('bad_goal', 'Escribe un número entero de miembros.')
    # Coarse targets, changed rarely: a total of people's balances can't be
    # narrowed down by trying target after target.
    if kind == TeamGoalKind.INVESTED_USD and target % AMOUNT_STEP != 0:
        raise CommunityPostError('bad_goal', f'La meta va en pasos de ${AMOUNT_STEP}.')
    if deadline is not None and deadline <= league.utc_today():
        raise CommunityPostError('bad_goal', 'La fecha límite debe ser futura.')
    from .models import Team

    with transaction.atomic():
        # Re-read under the team lock: a former captain's late request can't
        # replace the new captain's goal.
        locked = Team.objects.select_for_update().filter(id=team.id, archived_at__isnull=True).first()
        if locked is None or locked.captain_id != captain.id:
            raise CommunityPostError('not_captain', 'Solo el capitán puede hacer esto.')
        last = TeamGoal.objects.filter(team=locked).order_by('-created_at').values_list('created_at', flat=True).first()
        if last and timezone.now() - last < GOAL_CHANGE_EVERY:
            raise CommunityPostError('goal_recent', 'La meta se puede cambiar una vez por semana.')
        TeamGoal.objects.filter(team=locked, replaced_at__isnull=True).update(replaced_at=timezone.now())
        return TeamGoal.objects.create(team=locked, kind=kind, target=target, deadline=deadline, set_by=captain)


# ── copy play (#8) ───────────────────────────────────────────────────────

def copy_play(viewer, batch_id):
    """Record that the viewer is copying a member's recent buy and return
    what the buy screen needs. Attribution only: normal fees, nobody paid.
    Raises CommunityPostError when it can't be copied."""
    from django.db.models.functions import Lower

    from blockchain.models import CryptoTrade, SponsoredBatch
    from cusd_plus.stock_month import _decode_trades
    from inbox import community
    from inbox.community import CommunityPostError
    from users.models import Account

    from .models import CopiedPlay

    batch = SponsoredBatch.objects.filter(id=batch_id, status='confirmed',
                                          kind__in=('stock_buy', 'crypto_buy')).first()
    if batch is None or timezone.now() - batch.created_at > COPY_WINDOW:
        raise CommunityPostError('not_available', 'Esta jugada ya no se puede copiar.')
    from .eligibility import canonical_wallets, eligible_user_ids

    account = (Account.objects.annotate(addr=Lower('bsc_address'))
               .filter(addr=batch.user_bsc_address.lower(), account_type='personal', deleted_at__isnull=True)
               .select_related('user').first())
    owner = account.user if account else None
    # Only plays the member's own profile shows: their one wallet, while
    # they may be shown at all.
    if (owner is None or owner.id == viewer.id
            or canonical_wallets([owner.id]).get(owner.id) != batch.user_bsc_address.lower()
            or owner.id not in eligible_user_ids([owner.id])):
        raise CommunityPostError('not_available', 'Esta jugada ya no se puede copiar.')
    # Reciprocity: copying needs the same access as seeing the play.
    if community.portfolio_access(owner, viewer) != community.ACCESS_OPEN:
        raise CommunityPostError('portfolio_must_be_public', 'Haz público tu portafolio para copiar jugadas.')
    if community.is_blocked_between(owner.id, viewer.id):
        raise CommunityPostError('not_available', 'Esta jugada ya no se puede copiar.')
    if batch.kind == 'stock_buy':
        decoded = _decode_trades([batch])
        symbol = decoded[0].symbol if decoded else ''
        asset = 'stock'
        if not symbol or symbol.startswith('?') or symbol not in _names():
            raise CommunityPostError('not_tradable', 'No disponible')
    else:
        symbol = CryptoTrade.objects.filter(batch=batch).values_list('symbol', flat=True).first() or ''
        asset = 'crypto'
        if not symbol:
            raise CommunityPostError('not_tradable', 'No disponible')
    copy = CopiedPlay.objects.create(user=viewer, source_user=owner, source_batch_id=batch.id, symbol=symbol)
    _notify_copied(copy)
    return {'symbol': symbol, 'asset': asset, 'owner': owner, 'at': batch.created_at}


def _notify_copied(copy) -> None:
    """At most one push per play per UTC day to the member who made it: a
    durable claim, so several workers or a restart can't send twice."""
    from django.db import IntegrityError, transaction

    from inbox import community

    from .models import CopiedPlayNotice

    try:
        with transaction.atomic():
            CopiedPlayNotice.objects.create(source_batch_id=copy.source_batch_id, day=league.utc_today())
    except IntegrityError:
        return
    ticker = copy.symbol.removesuffix('on')
    community._notify(copy.source_user, 'COMMUNITY_PLAY_COPIED', 'Copiaron tu jugada',
                      f'Alguien copió tu compra de {ticker}.', action_url=community.member_link(copy.source_user_id),
                      data={'member_id': copy.source_user_id})


def link_copies(hours: int = 24) -> int:
    """Attribution: a copier's own buy of the symbol confirmed after the copy."""
    from django.db.models.functions import Lower

    from blockchain.models import CryptoTrade, SponsoredBatch
    from cusd_plus.stock_month import _decode_trades

    from .models import CopiedPlay

    linked = 0
    since = timezone.now() - timedelta(hours=hours)
    for copy in CopiedPlay.objects.filter(resulting_batch_id__isnull=True, created_at__gte=since).select_related('user'):
        wallet = personal_wallet(copy.user)
        if not wallet:
            continue
        for batch in (SponsoredBatch.objects.annotate(addr=Lower('user_bsc_address'))
                      .filter(addr=wallet, status='confirmed', kind__in=('stock_buy', 'crypto_buy'),
                              created_at__gte=copy.created_at).order_by('created_at')[:10]):
            if batch.kind == 'stock_buy':
                decoded = _decode_trades([batch])
                symbol = decoded[0].symbol if decoded else ''
            else:
                symbol = CryptoTrade.objects.filter(batch=batch).values_list('symbol', flat=True).first() or ''
            if symbol == copy.symbol and not CopiedPlay.objects.filter(resulting_batch_id=batch.id).exists():
                CopiedPlay.objects.filter(id=copy.id).update(resulting_batch_id=batch.id)
                linked += 1
                break
    return linked


def refresh_all_goals() -> int:
    """Hourly: a goal met before its deadline is recorded even if nobody
    opened the team page in time (a weekly count resets on Monday)."""
    from .models import Team

    reached = 0
    for goal in TeamGoal.objects.filter(replaced_at__isnull=True, reached_at__isnull=True,
                                        team__archived_at__isnull=True).select_related('team'):
        refresh_goal(goal.team, goal)
        if goal.reached_at is not None:
            reached += 1
    return reached
