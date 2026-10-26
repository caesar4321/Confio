"""The league: team and investor tables by dollar P&L (spec #6 child #7;
ranked by dollars since 2026-10-26, the % shown beside them).

What ranks is the member's own result in dollars over the period: realized
and unrealized (each day's gain = value at its end - value at its start -
money put in + money taken out, inbox.PortfolioDailySnapshot.gain_usd), so
a holder who never sold ranks too, and Futuros count at margin (the
member's dollars), never the leveraged size. The % stays beside it so a
large account's dollars read for what they are.

Built only from proven days (inbox.PortfolioDailySnapshot), never a live
or guessed number:

- A member QUALIFIES for a UTC day when they were on the team for the
  whole day, their day is ledger-trusted with at least MIN_SLEEVE_USD
  invested at its start, and they are (now) verified with a public profile.
- A team's day is the arithmetic mean of its qualifying members' daily
  dollar gains (and returns): an average per member, so a team never wins
  by being bigger.
- A period chain-links its days. A team is in the table when its latest
  day had at least MIN_TEAM_MEMBERS qualifying members; ties go to more
  qualifying members, then the older team.
- An investor is in the table when every day of the range is proven on
  their one personal wallet (no gaps, no guessed flat days), they held on
  average at least MIN_AVG_SLEEVE_USD over it, and held something on at
  least MIN_HOLDING_DAYS of its days: a dust trade never tops the table.
- All time ('all') is each one's current unbroken run of proven days
  ending yesterday (a missing or unproven day restarts it: nothing is ever
  guessed across a gap), ranked only from MIN_ALL_TIME_DAYS days, so two
  lucky days can't top a year of steady returns.
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
# The investor table's floor: average invested over the period, and days
# holding something (fewer when the range itself is shorter).
MIN_AVG_SLEEVE_USD = Decimal('20')
MIN_HOLDING_DAYS = 2
MIN_TEAM_MEMBERS = 5
# A team's return is shown at all only over days with at least this many
# qualifying members: fewer would be one person's return.
MIN_SHOWN_MEMBERS = 3
# '30d' stays for older app builds; current ones show 'all' instead.
RANGES = ('24h', '7d', '30d', 'month', 'all')
MIN_ALL_TIME_DAYS = 30
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
    if range_key == 'all':
        # Every day there is history for; each row then keeps only its own
        # trailing unbroken run (see _trailing_run).
        start = league_start()
        if start is None or start > yesterday:
            return []
        return [start + timedelta(days=k) for k in range((yesterday - start).days + 1)]
    raise ValueError(range_key)


def league_start() -> date | None:
    """The first day any return was recorded."""
    from django.db.models import Min

    from inbox.models import PortfolioDailySnapshot

    key = 'league:start'
    start = cache.get(key)
    if start is None:
        start = PortfolioDailySnapshot.objects.aggregate(first=Min('day'))['first']
        if start is not None:
            cache.set(key, start, CACHE_SECONDS)
    return start


def _trailing_run(days: list[date], ok) -> list[date]:
    """The days of the unbroken run that ends on the last day (oldest
    first): walking back from yesterday until a day that isn't ok."""
    run = []
    for day in reversed(days):
        if not ok(day):
            break
        run.append(day)
    return run[::-1]


# All time, in the database: each entity's islands of consecutive good days
# ("day minus row number" is constant along an island), keeping only the one
# that ends on the last day. Returns {key: (days, sum of ln(1+r), had_total_loss, first_day)}.
_RUNS_SQL = '''
WITH good AS (
    SELECT {key} AS k, day, {ret_cols},
           day - (ROW_NUMBER() OVER (PARTITION BY {key} ORDER BY day))::int AS island
    FROM {table}
    WHERE {key} = ANY(%s) AND day BETWEEN %s AND %s AND {good}
)
SELECT k, COUNT(*), COALESCE(SUM(CASE WHEN 1 + r > 0 THEN LN(1 + r) END), 0), BOOL_OR(1 + r <= 0), MIN(day),
       COALESCE(SUM(g), 0), BOOL_OR(g IS NULL), AVG(s), COUNT(*) FILTER (WHERE s >= 1)
FROM good GROUP BY k, island HAVING MAX(day) = %s
'''


@dataclass
class Run:
    days: int
    log_sum: Decimal
    total_loss: bool
    first_day: date
    gain: Decimal | None   # None: a day in the run has no dollar gain yet
    avg_start: Decimal | None
    holding_days: int = 0


def _runs(model, key: str, ret: str, good: str, ids, first: date, last: date, *, gain: str,
          start: str = 'NULL::numeric') -> dict:
    from django.db import connection

    ids = list(ids)
    if not ids:
        return {}
    sql = _RUNS_SQL.format(key=key, ret_cols=f'{ret} AS r, {gain} AS g, {start} AS s', good=good,
                           table=model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(sql, [ids, first, last, last])
        return {k: Run(n, Decimal(lg), bool(zero), first_day, None if missing else Decimal(g),
                       None if s is None else Decimal(s), int(held or 0))
                for k, n, lg, zero, first_day, g, missing, s, held in cursor.fetchall()}


def _run_pct(log_sum: Decimal, total_loss: bool) -> Decimal:
    return Decimal('-100') if total_loss else (log_sum.exp() - 1) * 100


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
    eligible = _eligible_user_ids(members)
    left_out = set(members) - eligible
    if left_out:
        # Whoever a day leaves out for eligibility is remembered, so the
        # nightly repair can put them back when they may be shown again.
        from .models import TeamHistoryExclusion

        TeamHistoryExclusion.objects.bulk_create([TeamHistoryExclusion(user_id=u) for u in left_out],
                                                 ignore_conflicts=True)
    wallets = canonical_wallets(eligible)
    owner = {wallet: user_id for user_id, wallet in wallets.items()}
    returns, gains = {}, {}
    for wallet, ret, gain in (PortfolioDailySnapshot.objects.filter(
            wallet__in=list(wallets.values()), day=day, ledger_trusted=True, value_start_usd__gte=MIN_SLEEVE_USD)
            .exclude(daily_return__isnull=True).exclude(gain_usd__isnull=True)
            .values_list('wallet', 'daily_return', 'gain_usd')):
        returns[wallet], gains[wallet] = ret, gain
    if not returns:
        TeamDailyReturn.objects.filter(team=team, day=day).delete()
        return False
    mean = sum(returns.values(), Decimal('0')) / len(returns)
    mean_gain = sum(gains.values(), Decimal('0')) / len(gains)
    TeamDailyReturn.objects.update_or_create(team=team, day=day, defaults={
        'daily_return': mean.quantize(Decimal('0.0000000001')), 'qualifying_members': len(returns),
        'mean_gain_usd': mean_gain.quantize(Decimal('0.000001')),
        'contributors': sorted(owner[w] for w in returns)})
    return True


def invalidate_team_tables() -> None:
    cache.delete_many([_key('teams', window(r), r) for r in RANGES])


def recompute_member_history(user) -> int:
    """Every day of every team this person was ever on, recomputed from
    who may be shown now: hiding drops them from past days, showing again
    puts them back (all time reaches far past the nightly window)."""
    from .models import TeamMembership

    start = league_start()
    yesterday = utc_today() - timedelta(days=1)
    if start is None:
        return 0
    written = 0
    for membership in TeamMembership.objects.filter(user=user).select_related('team'):
        first = max(membership.joined_at.date(), start)
        last = min(membership.left_at.date(), yesterday) if membership.left_at else yesterday
        day = first
        while day <= last:
            written += compute_team_day(membership.team, day)
            day += timedelta(days=1)
    # Remember who is out of history, so the nightly repair can restore them.
    from .models import TeamHistoryExclusion

    if user.id in _eligible_user_ids([user.id]):
        TeamHistoryExclusion.objects.filter(user_id=user.id).delete()
    else:
        TeamHistoryExclusion.objects.get_or_create(user_id=user.id)
    invalidate_team_tables()
    return written


def recompute_team(team, days: int = COMPUTE_DAYS, *, invalidate: bool = False) -> int:
    today = utc_today()
    written = sum(1 for k in range(days, 0, -1) if compute_team_day(team, today - timedelta(days=k)))
    if invalidate:
        cache.delete_many([_key('teams', window(r), r) for r in RANGES])
    return written


def compute_recent_days(days: int = COMPUTE_DAYS) -> dict:
    from .models import Team

    counts = {'teams': 0, 'days': 0}
    # First, while every stored day still names who it was made of.
    counts['repaired'] = repair_all_time_people()
    for team in Team.objects.filter(archived_at__isnull=True):
        counts['teams'] += 1
        counts['days'] += recompute_team(team, days)
    warm()
    return counts


def stored_contributors() -> set:
    """Everyone any stored team day is made of (ranked or not)."""
    from django.db import connection

    from .models import TeamDailyReturn

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT DISTINCT jsonb_array_elements_text(contributors::jsonb) FROM {TeamDailyReturn._meta.db_table}')
        return {int(value) for (value,) in cursor.fetchall()}


def repair_all_time_people() -> int:
    """Anyone counted in an all-time run who may no longer be shown (an
    expired or revoked verification, a ban: changes with no hook here) gets
    their past team days recomputed without them, so the team ranks on the
    members still shown instead of being left out for good."""
    from users.models import User

    from .models import TeamHistoryExclusion

    days = window('all')
    if not days:
        return 0
    people = stored_contributors()
    stale = people - _eligible_user_ids(people)
    # And the other way: people taken out earlier who may be shown again
    # (verification renewed, a temporary ban over).
    excluded = set(TeamHistoryExclusion.objects.values_list('user_id', flat=True))
    back = _eligible_user_ids(excluded)
    for user in User.all_objects.filter(id__in=stale | back):
        recompute_member_history(user)
    return len(stale | back)


def _build(kind: str, range_key: str, days) -> list:
    all_time = range_key == 'all'
    return team_table(days, all_time) if kind == 'teams' else investor_table(days, all_time)


def _key(kind: str, days, range_key: str) -> str:
    """Bound to the exact days and the range's rules: a table never outlives
    the window it was computed for, and two ranges over the same days (30 d
    and all time early on) never share an entry."""
    span = f'{days[0].isoformat()}:{days[-1].isoformat()}' if days else 'empty'
    return f'league:v2:{kind}:{range_key}:{span}'


def warm() -> None:
    """Rebuild every cached table (nightly, after the team days)."""
    for kind in ('teams', 'investors'):
        for range_key in RANGES:
            days = window(range_key)
            cache.set(_key(kind, days, range_key), _build(kind, range_key, days), CACHE_SECONDS)


# ── tables ───────────────────────────────────────────────────────────────────

@dataclass
class Row:
    rank: int
    pct: Decimal
    # Dollars over the period (a team: summed per-member averages): what ranks.
    pnl: Decimal = Decimal('0')
    # All time: the first day of the run the result is made of.
    since: date | None = None
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


def team_table(days: list[date], all_time: bool = False) -> list[Row]:
    from .models import Team, TeamDailyReturn

    if not days:
        return []
    if all_time:
        return _team_table_all_time(days)
    by_team: dict = {}
    people: dict = {}
    for team_id, day, ret, qualifying, ids, gain in TeamDailyReturn.objects.filter(
            day__in=days, team__archived_at__isnull=True).values_list(
            'team_id', 'day', 'daily_return', 'qualifying_members', 'contributors', 'mean_gain_usd'):
        by_team.setdefault(team_id, {})[day] = (ret, qualifying, gain)
        people.setdefault(team_id, set()).update(ids or [])
    last = days[-1]
    created = dict(Team.objects.filter(id__in=by_team).values_list('id', 'created_at'))
    rows = []
    for team_id, per_day in by_team.items():
        latest = per_day.get(last)
        if latest is None or latest[1] < MIN_TEAM_MEMBERS:
            continue
        # Never a day that is really one or two people's return.
        if any(q < MIN_SHOWN_MEMBERS for _, q, _g in per_day.values()):
            continue
        # A day without its dollars (computed before they existed) is never guessed.
        if any(g is None for _, _q, g in per_day.values()):
            continue
        pct = _chain(per_day[d][0] for d in days if d in per_day)
        pnl = sum((per_day[d][2] for d in days if d in per_day), Decimal('0'))
        rows.append((pnl, pct, latest[1], created.get(team_id), team_id))
    # Ties: more qualifying members, then the older team (the % never decides).
    rows.sort(key=lambda r: (-r[0], -r[2], r[3] or timezone.now()))
    return [Row(rank=i + 1, pct=pct, pnl=pnl, team_id=team_id, members=q,
                people=frozenset(people.get(team_id, ())))
            for i, (pnl, pct, q, _, team_id) in enumerate(rows)]


def _team_table_all_time(days: list[date]) -> list[Row]:
    from .models import Team, TeamDailyReturn

    last = days[-1]
    # Teams that can rank at all: five qualifying members on the last day.
    latest = dict(TeamDailyReturn.objects.filter(day=last, team__archived_at__isnull=True,
                                                 qualifying_members__gte=MIN_TEAM_MEMBERS)
                  .values_list('team_id', 'qualifying_members'))
    runs = _runs(TeamDailyReturn, 'team_id', 'daily_return', f'qualifying_members >= {MIN_SHOWN_MEMBERS}',
                 latest, days[0], last, gain='mean_gain_usd')
    created = dict(Team.objects.filter(id__in=runs).values_list('id', 'created_at'))
    rows = []
    for team_id, run in runs.items():
        if run.days < MIN_ALL_TIME_DAYS or run.gain is None:
            continue
        rows.append((run.gain, _run_pct(run.log_sum, run.total_loss), latest[team_id], created.get(team_id),
                     team_id, run.first_day))
    rows.sort(key=lambda r: (-r[0], -r[2], r[3] or timezone.now()))
    out = []
    for i, (pnl, pct, q, _, team_id, start) in enumerate(rows):
        # The people are those of the counted run only.
        people = set()
        for ids in TeamDailyReturn.objects.filter(team_id=team_id, day__gte=start, day__lte=last).values_list(
                'contributors', flat=True):
            people.update(ids or [])
        out.append(Row(rank=i + 1, pct=pct, pnl=pnl, team_id=team_id, members=q, people=frozenset(people)))
    return out


def investor_table(days: list[date], all_time: bool = False) -> list[Row]:
    from inbox.models import PortfolioDailySnapshot

    from .eligibility import canonical_wallets

    if not days:
        return []
    last_day = set(PortfolioDailySnapshot.objects.filter(day=days[-1], ledger_trusted=True)
                   .values_list('user_id', flat=True))
    wallets = canonical_wallets(_eligible_user_ids(last_day))
    if all_time:
        return _investor_table_all_time(days, wallets)
    by_wallet: dict = {}
    for wallet, day, ret, trusted, start, gain in PortfolioDailySnapshot.objects.filter(
            wallet__in=list(wallets.values()), day__in=days).values_list(
            'wallet', 'day', 'daily_return', 'ledger_trusted', 'value_start_usd', 'gain_usd'):
        by_wallet.setdefault(wallet, {})[day] = (ret if trusted else None, start, gain if trusted else None)
    rows = []
    for user_id, wallet in wallets.items():
        per_day = by_wallet.get(wallet, {})
        # Every day proven on the member's one wallet (no gaps, no guesses).
        if any(per_day.get(day, (None, None, None))[0] is None or per_day[day][2] is None for day in days):
            continue
        if not _invests_enough([per_day[day][1] for day in days]):
            continue
        pnl = sum((per_day[day][2] for day in days), Decimal('0'))
        rows.append((pnl, _chain(per_day[day][0] for day in days), user_id))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    return [Row(rank=i + 1, pct=pct, pnl=pnl, user_id=user_id, people=frozenset([user_id]))
            for i, (pnl, pct, user_id) in enumerate(rows)]


def _invests_enough(starts: list) -> bool:
    """The investor floor: on average at least MIN_AVG_SLEEVE_USD invested
    over the period, and something held on at least MIN_HOLDING_DAYS days
    (every day, when the range is shorter)."""
    values = [Decimal(v or 0) for v in starts]
    if not values:
        return False
    holding = sum(1 for v in values if v >= Decimal('1'))
    return (sum(values, Decimal('0')) / len(values) >= MIN_AVG_SLEEVE_USD
            and holding >= min(MIN_HOLDING_DAYS, len(values)))


def _investor_table_all_time(days: list[date], wallets: dict) -> list[Row]:
    from inbox.models import PortfolioDailySnapshot

    last = days[-1]
    runs = _runs(PortfolioDailySnapshot, 'wallet', 'daily_return', 'ledger_trusted AND daily_return IS NOT NULL',
                 wallets.values(), days[0], last, gain='gain_usd', start='value_start_usd')
    rows = []
    for user_id, wallet in wallets.items():
        run = runs.get(wallet)
        if (run is None or run.days < MIN_ALL_TIME_DAYS or run.gain is None
                or (run.avg_start or 0) < MIN_AVG_SLEEVE_USD or run.holding_days < MIN_HOLDING_DAYS):
            continue
        rows.append((run.gain, _run_pct(run.log_sum, run.total_loss), user_id, run.first_day))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    return [Row(rank=i + 1, pct=pct, pnl=pnl, user_id=user_id, people=frozenset([user_id]), since=since)
            for i, (pnl, pct, user_id, since) in enumerate(rows)]


def counted_days(team_id, range_key: str) -> list[date]:
    """The days a team's result in this range is made of (all time: its
    trailing run of shown days, from 30 days; else the window)."""
    from .models import TeamDailyReturn

    days = window(range_key)
    if range_key != 'all':
        return days
    quals = dict(TeamDailyReturn.objects.filter(team_id=team_id, day__in=days).values_list('day', 'qualifying_members'))
    run = _trailing_run(days, lambda d: quals.get(d, 0) >= MIN_SHOWN_MEMBERS)
    return run if len(run) >= MIN_ALL_TIME_DAYS else []


def counted_contributors(team_id, range_key: str) -> set:
    """Who a team's result in this range is made of."""
    return contributors([team_id], counted_days(team_id, range_key)).get(int(team_id), set())


def table(kind: str, range_key: str) -> list[Row]:
    """The ranking, with whoever may no longer appear removed at read time
    (an investor who hid their profile, a team archived since). Ranks are
    renumbered over what is shown."""
    from .models import Team

    days = window(range_key)
    key = _key(kind, days, range_key)
    rows = cache.get(key)
    if rows is None:
        rows = _build(kind, range_key, days)
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
    return [Row(rank=i + 1, pct=r.pct, pnl=r.pnl, team_id=r.team_id, user_id=r.user_id, members=r.members,
                people=r.people, since=getattr(r, 'since', None))
            for i, r in enumerate(rows)]


def team_return(team_id, range_key: str) -> tuple[Decimal | None, int | None]:
    """(percent, rank) for one team: percent over its proven days in range,
    rank only when it's in the table."""
    pct, _pnl, rank = team_result(team_id, range_key)
    return pct, rank


def team_result(team_id, range_key: str) -> tuple[Decimal | None, Decimal | None, int | None]:
    """(percent, dollars per member, rank) for one team over its proven days
    in range; dollars None while a day has none yet, rank only in the table."""
    from .models import TeamDailyReturn

    days = counted_days(team_id, range_key)
    rows = list(TeamDailyReturn.objects.filter(team_id=team_id, day__in=days).values_list(
        'daily_return', 'qualifying_members', 'mean_gain_usd'))
    rank = next((row.rank for row in table('teams', range_key) if row.team_id == int(team_id)), None)
    if not rows or any(q < MIN_SHOWN_MEMBERS for _, q, _g in rows) or not contributors_ok(team_id, days):
        return None, None, rank
    pnl = None if any(g is None for _, _q, g in rows) else sum((g for _, _q, g in rows), Decimal('0'))
    return _chain(r for r, _q, _g in rows), pnl, rank


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


def futures_risk_for_rows(rows, days) -> dict:
    """futures_risk over exactly the days each row's result is made of (all
    time: the investor's own run, never trades before a gap it excludes)."""
    out: dict = {}
    by_start: dict = {}
    for r in rows:
        start = getattr(r, 'since', None)
        span = [d for d in days if start is None or d >= start]
        by_start.setdefault((span[0], span[-1]) if span else None, []).append(r.user_id)
    for key, ids in by_start.items():
        if key is None:
            continue
        span = [d for d in days if key[0] <= d <= key[1]]
        out.update(futures_risk(ids, span))
    return out


def futures_risk(user_ids, days) -> dict:
    """{user_id: (average leverage or None, liquidations)} for Futuros held in
    the period: the margin-weighted leverage of positions open at any point
    in it, and how many of them Hyperliquid liquidated in it. Shown beside a
    result so a lucky leveraged bet reads for what it is."""
    from blockchain.models import PerpPosition

    ids = [u for u in user_ids if u]
    if not ids or not days:
        return {}
    start, _ = _day_bounds(days[0])
    _, end = _day_bounds(days[-1])
    out: dict = {}
    rows = (PerpPosition.objects.filter(user_id__in=ids, opened_at__isnull=False, opened_at__lt=end)
            .exclude(closed_at__lt=start).values_list('user_id', 'leverage', 'margin_usd', 'liquidation', 'closed_at'))
    weights: dict = {}
    for user_id, leverage, margin, liquidation, closed_at in rows:
        if closed_at is None or closed_at > start:
            # Exposure inside the window only (closed exactly at its start: none).
            w = Decimal(margin or 0)
            lev_sum, total = weights.get(user_id, (Decimal(0), Decimal(0)))
            weights[user_id] = (lev_sum + w * leverage, total + w)
        liquidated = 1 if liquidation and closed_at is not None and start <= closed_at < end else 0
        out[user_id] = (None, out.get(user_id, (None, 0))[1] + liquidated)
    for user_id, (lev_sum, total) in weights.items():
        out[user_id] = ((lev_sum / total) if total > 0 else None, out[user_id][1])
    return out


# ── season awards ────────────────────────────────────────────────────────────

def award_month(month_start: date, *, force: bool = False) -> list:
    """Monthly champion for a finished month. Written once, never changed.
    Waits for every final-day snapshot, unless `force` (the last retry)."""
    from .models import LeagueAwardKind, LeagueSeasonAward

    from .models import Team

    days = month_window(month_start)
    if days[-1] >= utc_today() or not (force or month_complete(days)):
        return []
    # Not even forced: a permanent champion never rests on a provisional close.
    if has_provisional_days(days):
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
    return current <= last and not has_provisional_days(days)


def has_provisional_days(days) -> bool:
    """A weekend close still provisional in these days
    (inbox/portfolio_returns.provisional_sig ends in 'p'), on a wallet that
    still counts: a replaced or deleted wallet is never synced again and
    must not hold an award back forever."""
    from django.db.models.functions import Lower

    from inbox.models import PortfolioDailySnapshot
    from users.models import Account

    wallets = set(PortfolioDailySnapshot.objects.filter(day__in=days, ledger_sig__endswith='p')
                  .values_list('wallet', flat=True))
    if not wallets:
        return False
    return Account.objects.filter(account_type='personal', deleted_at__isnull=True).annotate(
        addr=Lower('bsc_address')).filter(addr__in=wallets).exists()


def badges(*, team_id=None, user_id=None) -> list[str]:
    """"2026-10" months this team or investor was champion, newest first."""
    from .models import LeagueSeasonAward

    qs = LeagueSeasonAward.objects.filter(team_id=team_id) if team_id else LeagueSeasonAward.objects.filter(
        user_id=user_id)
    return [m.strftime('%Y-%m') for m in qs.order_by('-month').values_list('month', flat=True)]


def days_to_rank_all_time(kind: str, user) -> int | None:
    """How many more proven days the viewer (or the viewer's team) needs to
    rank all time; 0 when the run is long enough, None when there is no run."""
    from inbox.models import PortfolioDailySnapshot

    from . import rules
    from .eligibility import canonical_wallets
    from .models import TeamDailyReturn

    days = window('all')
    if not days:
        return None
    if kind == 'teams':
        membership = rules.active_membership(user)
        if membership is None:
            return None
        quals = dict(TeamDailyReturn.objects.filter(team_id=membership.team_id, day__in=days)
                     .values_list('day', 'qualifying_members'))
        run = _trailing_run(days, lambda d: quals.get(d, 0) >= MIN_SHOWN_MEMBERS)
    else:
        wallet = canonical_wallets([user.id]).get(user.id)
        if not wallet:
            return None
        proven = set(PortfolioDailySnapshot.objects.filter(
            wallet=wallet, day__in=days, ledger_trusted=True, daily_return__isnull=False).values_list('day', flat=True))
        run = _trailing_run(days, lambda d: d in proven)
    if not run:
        return None
    return max(MIN_ALL_TIME_DAYS - len(run), 0)
