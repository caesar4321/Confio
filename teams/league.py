"""The league: team and investor tables by % return (spec #6 child #7).

Built only from proven days (inbox.PortfolioDailySnapshot), never a live
or guessed number:

- A member QUALIFIES for a UTC day when they were on the team for the
  whole day, their day is ledger-trusted with at least MIN_SLEEVE_USD
  invested at its start, and they are (now) verified with a public profile.
- A team's day is the arithmetic mean of its qualifying members' daily
  returns: equal weight, so one whale can't carry a team and a $20
  investor counts as much as a $20k one.
- A period chain-links its days. A team is in the table when its latest
  day had at least MIN_TEAM_MEMBERS qualifying members; ties go to more
  qualifying members, then the older team.
- An investor is in the table when every day of the range is proven on
  their one personal wallet (no gaps, no guessed flat days) and they had at
  least MIN_SLEEVE_USD at the start of the range's last day.
- Rankings are cached; who may appear is re-checked on every read
  (someone who hides their profile disappears at once).
- Each month's #1 team and #1 investor get a permanent "monthly champion"
  badge, decided on the 1st and never changed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

MIN_SLEEVE_USD = Decimal('10')
MIN_TEAM_MEMBERS = 5
# A team's return is shown at all only over days with at least this many
# qualifying members: fewer would be one person's return.
MIN_SHOWN_MEMBERS = 3
RANGES = ('24h', '7d', '30d', 'month')
# Warmed by the nightly task; who appears is filtered on every read anyway.
CACHE_SECONDS = 2 * 60 * 60
COMPUTE_DAYS = 31


def utc_today() -> date:
    from datetime import timezone as dt_timezone

    return timezone.now().astimezone(dt_timezone.utc).date()


def window(range_key: str, today: date | None = None) -> list[date]:
    """The complete UTC days a range covers, oldest first."""
    today = today or utc_today()
    yesterday = today - timedelta(days=1)
    if range_key == '24h':
        return [yesterday]
    if range_key in ('7d', '30d'):
        n = 7 if range_key == '7d' else 30
        return [today - timedelta(days=k) for k in range(n, 0, -1)]
    if range_key == 'month':
        # This calendar month's complete days (none yet on the 1st).
        start = today.replace(day=1)
        return [start + timedelta(days=k) for k in range((today - start).days)]
    raise ValueError(range_key)


def month_window(month_start: date) -> list[date]:
    nxt = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return [month_start + timedelta(days=k) for k in range((nxt - month_start).days)]


def _eligible_user_ids(user_ids) -> set:
    from .eligibility import eligible_user_ids

    return eligible_user_ids(user_ids)


# ── team days ────────────────────────────────────────────────────────────────

def day_end(day: date):
    from inbox.portfolio_returns import day_start

    return day_start(day + timedelta(days=1))


def _day_bounds(day: date):
    from inbox.portfolio_returns import day_start

    return day_start(day), day_start(day + timedelta(days=1))


def compute_team_day(team, day: date) -> bool:
    """Write (or refresh) the team's return for a complete day. False when
    no member qualified (no row)."""
    from inbox.models import PortfolioDailySnapshot

    from .models import TeamDailyReturn, TeamMembership

    from .eligibility import canonical_wallets

    start, end = _day_bounds(day)
    members = list(TeamMembership.objects.filter(team=team, joined_at__lte=start)
                   .exclude(left_at__lt=end).values_list('user_id', flat=True))
    wallets = canonical_wallets(_eligible_user_ids(members))
    owner = {wallet: user_id for user_id, wallet in wallets.items()}
    returns = {}
    for wallet, ret in (PortfolioDailySnapshot.objects.filter(
            wallet__in=list(wallets.values()), day=day, ledger_trusted=True, value_start_usd__gte=MIN_SLEEVE_USD)
            .exclude(daily_return__isnull=True).values_list('wallet', 'daily_return')):
        returns[wallet] = ret
    if not returns:
        TeamDailyReturn.objects.filter(team=team, day=day).delete()
        return False
    mean = sum(returns.values(), Decimal('0')) / len(returns)
    TeamDailyReturn.objects.update_or_create(team=team, day=day, defaults={
        'daily_return': mean.quantize(Decimal('0.0000000001')), 'qualifying_members': len(returns),
        'contributors': sorted(owner[w] for w in returns)})
    return True


def recompute_team(team, days: int = COMPUTE_DAYS, *, invalidate: bool = False) -> int:
    today = utc_today()
    written = sum(1 for k in range(days, 0, -1) if compute_team_day(team, today - timedelta(days=k)))
    if invalidate:
        cache.delete_many([_key('teams', window(r)) for r in RANGES])
    return written


def compute_recent_days(days: int = COMPUTE_DAYS) -> dict:
    from .models import Team

    counts = {'teams': 0, 'days': 0}
    for team in Team.objects.filter(archived_at__isnull=True):
        counts['teams'] += 1
        counts['days'] += recompute_team(team, days)
    warm()
    return counts


def _key(kind: str, days) -> str:
    """Bound to the exact days: a table never outlives the window it was
    computed for (and the read-time checks always look at the same days)."""
    return f'league:{kind}:{days[0].isoformat()}:{days[-1].isoformat()}' if days else f'league:{kind}:empty'


def warm() -> None:
    """Rebuild every cached table (nightly, after the team days)."""
    for kind in ('teams', 'investors'):
        for range_key in RANGES:
            days = window(range_key)
            rows = team_table(days) if kind == 'teams' else investor_table(days)
            cache.set(_key(kind, days), rows, CACHE_SECONDS)


# ── tables ───────────────────────────────────────────────────────────────────

@dataclass
class Row:
    rank: int
    pct: Decimal
    team_id: int | None = None
    user_id: int | None = None
    members: int = 0
    # Everyone this result is made of (a team's contributors over the days),
    # cached with it so a read always checks exactly these people.
    people: frozenset = frozenset()


def _chain(returns) -> Decimal:
    growth = Decimal('1')
    for r in returns:
        growth *= 1 + r
    return (growth - 1) * 100


def team_table(days: list[date]) -> list[Row]:
    from .models import Team, TeamDailyReturn

    if not days:
        return []
    by_team: dict = {}
    people: dict = {}
    for team_id, day, ret, qualifying, ids in TeamDailyReturn.objects.filter(
            day__in=days, team__archived_at__isnull=True).values_list(
            'team_id', 'day', 'daily_return', 'qualifying_members', 'contributors'):
        by_team.setdefault(team_id, {})[day] = (ret, qualifying)
        people.setdefault(team_id, set()).update(ids or [])
    last = days[-1]
    created = dict(Team.objects.filter(id__in=by_team).values_list('id', 'created_at'))
    rows = []
    for team_id, per_day in by_team.items():
        latest = per_day.get(last)
        if latest is None or latest[1] < MIN_TEAM_MEMBERS:
            continue
        # Never a day that is really one or two people's return.
        if any(q < MIN_SHOWN_MEMBERS for _, q in per_day.values()):
            continue
        pct = _chain(per_day[d][0] for d in days if d in per_day)
        rows.append((pct, latest[1], created.get(team_id), team_id))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2] or timezone.now()))
    return [Row(rank=i + 1, pct=pct, team_id=team_id, members=q, people=frozenset(people.get(team_id, ())))
            for i, (pct, q, _, team_id) in enumerate(rows)]


def investor_table(days: list[date]) -> list[Row]:
    from inbox.models import PortfolioDailySnapshot

    from .eligibility import canonical_wallets

    if not days:
        return []
    last_day = set(PortfolioDailySnapshot.objects.filter(day=days[-1], ledger_trusted=True)
                   .values_list('user_id', flat=True))
    wallets = canonical_wallets(_eligible_user_ids(last_day))
    by_wallet: dict = {}
    for wallet, day, ret, trusted, start in PortfolioDailySnapshot.objects.filter(
            wallet__in=list(wallets.values()), day__in=days).values_list(
            'wallet', 'day', 'daily_return', 'ledger_trusted', 'value_start_usd'):
        by_wallet.setdefault(wallet, {})[day] = (ret if trusted else None, start)
    rows = []
    for user_id, wallet in wallets.items():
        per_day = by_wallet.get(wallet, {})
        # Every day proven on the member's one wallet (no gaps, no guesses),
        # and the minimum held on that same wallet.
        if any(per_day.get(day, (None, None))[0] is None for day in days):
            continue
        if (per_day[days[-1]][1] or 0) < MIN_SLEEVE_USD:
            continue
        rows.append((_chain(per_day[day][0] for day in days), user_id))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [Row(rank=i + 1, pct=pct, user_id=user_id, people=frozenset([user_id]))
            for i, (pct, user_id) in enumerate(rows)]


def table(kind: str, range_key: str) -> list[Row]:
    """The ranking, with whoever may no longer appear removed at read time
    (an investor who hid their profile, a team archived since). Ranks are
    renumbered over what is shown."""
    from .models import Team

    days = window(range_key)
    key = _key(kind, days)
    rows = cache.get(key)
    if rows is None:
        rows = team_table(days) if kind == 'teams' else investor_table(days)
        cache.set(key, rows, CACHE_SECONDS)
    if kind == 'investors':
        allowed = _eligible_user_ids([r.user_id for r in rows])
        rows = [r for r in rows if r.user_id in allowed]
    else:
        live = set(Team.objects.filter(id__in=[r.team_id for r in rows], archived_at__isnull=True)
                   .values_list('id', flat=True))
        # The people the cached result was computed from, not today's rows.
        allowed = _eligible_user_ids(set().union(*(r.people for r in rows)) if rows else set())
        rows = [r for r in rows if r.team_id in live and r.people <= allowed]
    return [Row(rank=i + 1, pct=r.pct, team_id=r.team_id, user_id=r.user_id, members=r.members, people=r.people)
            for i, r in enumerate(rows)]


def team_return(team_id, range_key: str) -> tuple[Decimal | None, int | None]:
    """(percent, rank) for one team: percent over its proven days in range,
    rank only when it's in the table."""
    from .models import TeamDailyReturn

    days = window(range_key)
    rows = list(TeamDailyReturn.objects.filter(team_id=team_id, day__in=days).values_list(
        'daily_return', 'qualifying_members'))
    rank = next((row.rank for row in table('teams', range_key) if row.team_id == int(team_id)), None)
    if not rows or any(q < MIN_SHOWN_MEMBERS for _, q in rows) or not contributors_ok(team_id, days):
        return None, rank
    return _chain(r for r, _ in rows), rank


def contributors(team_ids, days) -> dict:
    """{team_id: set of user ids} whose returns make up these days."""
    from .models import TeamDailyReturn

    out: dict = {}
    for team_id, ids in TeamDailyReturn.objects.filter(team_id__in=list(team_ids), day__in=days).values_list(
            'team_id', 'contributors'):
        out.setdefault(team_id, set()).update(ids or [])
    return out


def contributors_ok(team_id, days) -> bool:
    """Everyone in these days is still someone who may be shown (a revoked
    verification or a ban since the last computation suppresses the team
    until it is recomputed)."""
    people = contributors([team_id], days).get(int(team_id), set())
    return people <= _eligible_user_ids(people)


# ── season awards ────────────────────────────────────────────────────────────

def award_month(month_start: date, *, force: bool = False) -> list:
    """Monthly champion for a finished month. Written once, never changed.
    Waits for every final-day snapshot, unless `force` (the last retry)."""
    from .models import LeagueAwardKind, LeagueSeasonAward

    from .models import Team

    days = month_window(month_start)
    if days[-1] >= utc_today() or not (force or month_complete(days)):
        return []
    # The whole month, recomputed now (an award may run days later), and only
    # teams whose every contributor may still be shown.
    for team in Team.objects.filter(archived_at__isnull=True):
        for day in days:
            compute_team_day(team, day)
    teams = [r for r in team_table(days) if contributors_ok(r.team_id, days)]
    written = []
    for kind, rows in ((LeagueAwardKind.TEAM, teams), (LeagueAwardKind.INVESTOR, investor_table(days))):
        if not rows:
            continue
        top = rows[0]
        with transaction.atomic():
            award, created = LeagueSeasonAward.objects.get_or_create(
                month=month_start, kind=kind,
                defaults={'team_id': top.team_id, 'user_id': top.user_id, 'return_pct': top.pct.quantize(Decimal('0.000001'))})
        if created:
            written.append(award)
    return written


def month_complete(days) -> bool:
    """Every wallet proven earlier in the month has its last day written
    (trusted or not): an award never goes out while someone's final day is
    still pending."""
    from inbox.models import PortfolioDailySnapshot

    from django.db.models.functions import Lower

    from users.models import Account

    seen = set(PortfolioDailySnapshot.objects.filter(day__in=days[:-1]).values_list('wallet', flat=True).distinct())
    # Only wallets still in use: a replaced or deleted wallet never gets its
    # final day and must not hold the award back.
    current = set(Account.objects.filter(account_type='personal', deleted_at__isnull=True)
                  .exclude(bsc_address__isnull=True).exclude(bsc_address='')
                  .annotate(addr=Lower('bsc_address')).filter(addr__in=seen).values_list('addr', flat=True))
    last = set(PortfolioDailySnapshot.objects.filter(day=days[-1]).values_list('wallet', flat=True))
    return current <= last


def badges(*, team_id=None, user_id=None) -> list[str]:
    """"2026-10" months this team or investor was champion, newest first."""
    from .models import LeagueSeasonAward

    qs = LeagueSeasonAward.objects.filter(team_id=team_id) if team_id else LeagueSeasonAward.objects.filter(
        user_id=user_id)
    return [m.strftime('%Y-%m') for m in qs.order_by('-month').values_list('month', flat=True)]
