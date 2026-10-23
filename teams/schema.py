"""GraphQL for teams, the league, copy play and the team goal. All
new operations: an older server only loses these screens.

Reciprocity is enforced here: team members, holdings, plays, member
returns and the league tables are investment data, served only to a viewer
whose own profile is public and verified. Everyone else gets the team's
name, size and their lock reason (and the top 3 of the league).
"""
from decimal import Decimal

import graphene
from graphql_jwt.decorators import login_required

from inbox import community, profile_pictures
from inbox.community import CommunityPostError

from . import data, invites, league, rules
from .models import Team, TeamFollow, TeamJoinRequest, TeamJoinRequestStatus


def _context(info):
    from inbox.schema import get_context_models

    return get_context_models(info)


def viewer_access(viewer) -> str:
    """open | viewer_hidden | viewer_unverified (same words as investorProfile)."""
    if viewer is None or not community.is_verified_member(viewer):
        return community.ACCESS_VIEWER_UNVERIFIED
    if community.portfolio_hidden(viewer):
        return community.ACCESS_VIEWER_HIDDEN
    return community.ACCESS_OPEN


def _pct(value):
    return None if value is None else format(Decimal(value).quantize(Decimal('0.01')), 'f')


class TeamMemberType(graphene.ObjectType):
    user_id = graphene.ID(required=True)
    username = graphene.String(required=True)
    avatar_url = graphene.String()
    role = graphene.String(required=True)
    return_pct = graphene.String()


class TeamPositionType(graphene.ObjectType):
    symbol = graphene.String(required=True)
    asset = graphene.String(required=True)
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    holders = graphene.Int(required=True)


class TeamPlayType(graphene.ObjectType):
    id = graphene.ID(required=True)
    user_id = graphene.ID(required=True)
    username = graphene.String(required=True)
    avatar_url = graphene.String()
    side = graphene.String(required=True)          # buy | sell
    symbol = graphene.String(required=True)
    asset = graphene.String(required=True)         # stock | crypto
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    at = graphene.DateTime(required=True)
    copyable = graphene.Boolean(required=True)


class TeamGoalType(graphene.ObjectType):
    kind = graphene.String(required=True)
    target = graphene.String(required=True)
    progress = graphene.String(required=True)
    percent = graphene.Int(required=True)
    deadline = graphene.Date()
    reached = graphene.Boolean(required=True)


class TeamType(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String(required=True)
    description = graphene.String(required=True)
    emoji = graphene.String(required=True)
    color = graphene.String(required=True)
    join_mode = graphene.String(required=True)
    country = graphene.String()
    member_count = graphene.Int(required=True)
    captain_id = graphene.ID(required=True)
    is_member = graphene.Boolean(required=True)
    is_captain = graphene.Boolean(required=True)
    is_following = graphene.Boolean(required=True)
    # pending | null: the viewer's request to join.
    join_request = graphene.String()
    # Why the viewer can't join right now (code), if so.
    join_block = graphene.String()
    join_block_message = graphene.String()
    # Investment data below: null/empty unless access is 'open'.
    access = graphene.String(required=True)
    return_pct = graphene.String()
    league_rank = graphene.Int()
    champion_months = graphene.List(graphene.NonNull(graphene.String), required=True)
    goal = graphene.Field(TeamGoalType)
    pending_requests = graphene.Int()


class LeagueRowType(graphene.ObjectType):
    rank = graphene.Int(required=True)
    pct = graphene.String(required=True)
    team = graphene.Field(TeamType)
    user_id = graphene.ID()
    username = graphene.String()
    avatar_url = graphene.String()
    members = graphene.Int()


class LeagueTableType(graphene.ObjectType):
    rows = graphene.List(graphene.NonNull(LeagueRowType), required=True)
    has_more = graphene.Boolean(required=True)
    # Locked viewers see only the top 3.
    access = graphene.String(required=True)
    my_rank = graphene.Int()
    my_pct = graphene.String()


class TeamJoinRequestType(graphene.ObjectType):
    id = graphene.ID(required=True)
    user_id = graphene.ID(required=True)
    username = graphene.String(required=True)
    avatar_url = graphene.String()
    created_at = graphene.DateTime(required=True)


def team_type(team, viewer, *, range_key='7d', with_stats=True) -> TeamType:
    access = viewer_access(viewer)
    membership = rules.active_membership(viewer)
    is_member = membership is not None and membership.team_id == team.id
    is_captain = team.captain_id == viewer.id
    pending = TeamJoinRequest.objects.filter(team=team, user=viewer, status=TeamJoinRequestStatus.PENDING).exists()
    block = None
    if not is_member:
        block = rules.member_block(viewer)
        if not block and membership is not None:
            block = 'already_in_team'
        if not block and rules.in_cooldown(viewer):
            block = 'cooldown'
        if not block and rules.active_members(team).count() >= rules.MAX_MEMBERS:
            block = 'team_full'
    pct = rank = None
    goal = None
    if with_stats and access == community.ACCESS_OPEN:
        pct, rank = league.team_return(team.id, range_key)
        # Someone the viewer is in a block with may be part of that aggregate
        # (now, or among those who made up the period).
        blocked = community.block_relation_ids(viewer)
        period = league.counted_contributors(team.id, range_key)
        if blocked & ({m.user_id for m in rules.active_members(team)} | period):
            pct = None
        current = data.current_goal(team)
        # The goal is the team's own: members only, and never when the viewer
        # is in a block with someone on it (an aggregate can reveal a balance).
        member_ids = {m.user_id for m in rules.active_members(team)}
        if current is not None and (not is_member or community.block_relation_ids(viewer) & member_ids):
            current = None
        if current is not None and current.kind == 'invested_usd' and (
                data.goal_contributors(team) < data.MIN_CONTRIBUTORS or data.roster_changed_recently(team)):
            current = None
        if current is not None:
            progress, percent = data.refresh_goal(team, current)
            shown = format(progress, 'f')
            if current.kind == 'invested_usd':
                # A total of people's balances: only ever a coarse step, so no
                # before/after difference pins down one person's money.
                percent = data.coarse_percent(percent)
                shown = format((current.target * percent / 100).quantize(Decimal('0.01')), 'f')
            goal = TeamGoalType(kind=current.kind, target=format(current.target, 'f'), progress=shown,
                                percent=percent, deadline=current.deadline, reached=current.reached_at is not None)
    return TeamType(
        id=str(team.id), name=team.name, description=team.description, emoji=team.emoji, color=team.color,
        join_mode=team.join_mode, country=team.country or None,
        member_count=rules.active_members(team).count(), captain_id=str(team.captain_id),
        is_member=is_member, is_captain=is_captain,
        is_following=TeamFollow.objects.filter(team=team, user=viewer).exists(),
        join_request='pending' if pending else None,
        join_block=block, join_block_message=rules.MESSAGES.get(block) if block else None,
        access=access, return_pct=_pct(pct), league_rank=rank,
        champion_months=league.badges(team_id=team.id),
        goal=goal,
        pending_requests=(TeamJoinRequest.objects.filter(team=team, status=TeamJoinRequestStatus.PENDING).count()
                          if is_captain else None),
    )


def blocked_team(viewer, team_id, range_key='7d') -> bool:
    """The viewer is in a block with someone on this team now, or with
    someone whose returns make up the period."""
    from .models import TeamMembership

    blocked = community.block_relation_ids(viewer)
    if not blocked:
        return False
    if TeamMembership.objects.filter(team_id=team_id, user_id__in=blocked, left_at__isnull=True).exists():
        return True
    period = league.counted_contributors(team_id, range_key)
    return bool(blocked & period)


def _member(user, avatars) -> dict:
    return {'user_id': str(user.id), 'username': community.author_display_name(user), 'avatar_url': avatars.get(user.id)}


class TeamsQuery(graphene.ObjectType):
    team = graphene.Field(TeamType, team_id=graphene.ID(required=True), range=graphene.String(required=False))
    my_team = graphene.Field(TeamType)
    # Open teams with room, sorted by 30d return, same country first.
    teams_looking = graphene.List(graphene.NonNull(TeamType), required=True,
                                  offset=graphene.Int(required=False), limit=graphene.Int(required=False))
    team_members = graphene.List(graphene.NonNull(TeamMemberType), required=True,
                                 team_id=graphene.ID(required=True), range=graphene.String(required=False))
    team_positions = graphene.List(graphene.NonNull(TeamPositionType), required=True, team_id=graphene.ID(required=True))
    team_plays = graphene.List(graphene.NonNull(TeamPlayType), required=True, team_id=graphene.ID(required=True))
    team_join_requests = graphene.List(graphene.NonNull(TeamJoinRequestType), required=True,
                                       team_id=graphene.ID(required=True))
    # kind: teams | investors; range: 24h | 7d | 30d | month | all.
    league_table = graphene.Field(LeagueTableType, required=True, kind=graphene.String(required=True),
                                  range=graphene.String(required=True), offset=graphene.Int(required=False),
                                  limit=graphene.Int(required=False))
    # "2026-10" months a member was monthly champion.
    league_badges = graphene.List(graphene.NonNull(graphene.String), required=True, user_id=graphene.ID(required=True))
    team_invite = graphene.Field(lambda: TeamInviteType, token=graphene.String(required=True))
    # All time: days the viewer (kind investors) or their team (kind teams) still needs to rank.
    league_days_to_rank = graphene.Int(kind=graphene.String(required=True))

    @staticmethod
    def _team(team_id):
        try:
            return Team.objects.filter(id=int(team_id), archived_at__isnull=True).first()
        except (TypeError, ValueError):
            return None

    @login_required
    def resolve_team(self, info, team_id, range='7d'):  # noqa: A002
        team = TeamsQuery._team(team_id)
        if team is None or community.is_blocked_between(info.context.user.id, team.captain_id):
            return None
        return team_type(team, info.context.user, range_key=range if range in league.RANGES else '7d')

    @login_required
    def resolve_my_team(self, info):
        membership = rules.active_membership(info.context.user)
        return team_type(membership.team, info.context.user) if membership else None

    @login_required
    def resolve_teams_looking(self, info, offset=0, limit=20):
        from django.db.models import Case, Count, IntegerField, Q, Value, When

        viewer = info.context.user
        offset, limit = max(offset or 0, 0), min(max(limit or 20, 1), 50)
        blocked = community.block_relation_ids(viewer)
        country = (getattr(viewer, 'phone_country', '') or '')[:2]
        ranked = {row.team_id: row.rank for row in league.table('teams', '30d')}
        # Bounded in the database: open seats only, same country first, then
        # newest; the league rank orders that bounded set.
        pool = list(Team.objects.filter(archived_at__isnull=True).exclude(captain_id__in=blocked)
                    .annotate(active=Count('memberships', filter=Q(memberships__left_at__isnull=True)))
                    .filter(active__lt=rules.MAX_MEMBERS)
                    .annotate(here=Case(When(country=country, then=Value(0)), default=Value(1),
                                        output_field=IntegerField()))
                    .order_by('here', '-created_at')[:300])
        pool.sort(key=lambda t: (t.here, ranked.get(t.id, 10 ** 6), -t.created_at.timestamp()))
        return [team_type(t, viewer, with_stats=False) for t in pool[offset:offset + limit]]

    @login_required
    def resolve_team_members(self, info, team_id, range='7d'):  # noqa: A002
        viewer = info.context.user
        team = TeamsQuery._team(team_id)
        if team is None or viewer_access(viewer) != community.ACCESS_OPEN:
            return []
        rows = data.members(team, range if range in league.RANGES else '7d')
        avatars = profile_pictures.picture_urls([m.user_id for m, _ in rows])
        blocked = community.block_relation_ids(viewer)
        return [TeamMemberType(**_member(m.user, avatars), role=m.role, return_pct=_pct(pct))
                for m, pct in rows if m.user_id not in blocked]

    @login_required
    def resolve_team_positions(self, info, team_id):
        team = TeamsQuery._team(team_id)
        if team is None or viewer_access(info.context.user) != community.ACCESS_OPEN:
            return []
        exclude = community.block_relation_ids(info.context.user)
        return [TeamPositionType(**p) for p in data.positions(team, exclude=exclude)]

    @login_required
    def resolve_team_plays(self, info, team_id):
        viewer = info.context.user
        team = TeamsQuery._team(team_id)
        if team is None or viewer_access(viewer) != community.ACCESS_OPEN:
            return []
        blocked = community.block_relation_ids(viewer)
        rows = data.plays(team, exclude=blocked)
        avatars = profile_pictures.picture_urls([p['user'].id for p in rows])
        return [TeamPlayType(id=str(p['id']), **_member(p['user'], avatars), side=p['side'], symbol=p['symbol'],
                             asset=p['asset'], ticker=p['ticker'], name=p['name'], at=p['at'],
                             copyable=p['copyable'] and p['user'].id != viewer.id)
                for p in rows if p['user'].id not in blocked]

    @login_required
    def resolve_team_join_requests(self, info, team_id):
        team = TeamsQuery._team(team_id)
        if team is None or team.captain_id != info.context.user.id:
            return []
        blocked = community.block_relation_ids(info.context.user)
        requests = [r for r in TeamJoinRequest.objects.filter(team=team, status=TeamJoinRequestStatus.PENDING)
                    .select_related('user').order_by('created_at') if r.user_id not in blocked]
        avatars = profile_pictures.picture_urls([r.user_id for r in requests])
        return [TeamJoinRequestType(id=str(r.id), **_member(r.user, avatars), created_at=r.created_at)
                for r in requests]

    @login_required
    def resolve_league_table(self, info, kind, range, offset=0, limit=30):  # noqa: A002
        viewer = info.context.user
        kind = 'investors' if kind == 'investors' else 'teams'
        range_key = range if range in league.RANGES else '7d'
        access = viewer_access(viewer)
        rows = league.table(kind, range_key)
        offset, limit = max(offset or 0, 0), min(max(limit or 30, 1), 50)
        if access != community.ACCESS_OPEN:
            offset, limit = 0, 3                  # a teaser: the global top 3, never more
        page = rows[offset:offset + limit]
        # Blocked people (and teams with someone the viewer is in a block
        # with) are left out of what is shown, never replaced by the next ones.
        blocked = community.block_relation_ids(viewer)
        if kind == 'investors':
            page = [r for r in page if r.user_id not in blocked]
        elif blocked:
            # Current members, and the people the shown result is made of.
            page = [r for r in page if not (blocked & r.people) and not blocked_team(viewer, r.team_id, range_key)]
        my_rank = my_pct = None
        if access == community.ACCESS_OPEN:
            if kind == 'investors':
                mine = next((r for r in rows if r.user_id == viewer.id), None)
            else:
                membership = rules.active_membership(viewer)
                mine = next((r for r in rows if membership and r.team_id == membership.team_id), None)
                if mine and (blocked & mine.people or blocked_team(viewer, mine.team_id, range_key)):
                    mine = None
            if mine:
                my_rank, my_pct = mine.rank, _pct(mine.pct)
        out = []
        if kind == 'teams':
            teams = {t.id: t for t in Team.objects.filter(id__in=[r.team_id for r in page])}
            for r in page:
                if r.team_id in teams:
                    out.append(LeagueRowType(rank=r.rank, pct=_pct(r.pct), members=r.members,
                                             team=team_type(teams[r.team_id], viewer, with_stats=False)))
        else:
            from users.models import User

            users = {u.id: u for u in User.objects.filter(id__in=[r.user_id for r in page])}
            avatars = profile_pictures.picture_urls(list(users))
            for r in page:
                user = users.get(r.user_id)
                if user is not None:
                    out.append(LeagueRowType(rank=r.rank, pct=_pct(r.pct), user_id=str(user.id),
                                             username=community.author_display_name(user),
                                             avatar_url=avatars.get(user.id)))
        return LeagueTableType(rows=out, has_more=access == community.ACCESS_OPEN and len(rows) > offset + limit,
                               access=access, my_rank=my_rank, my_pct=my_pct)

    @login_required
    def resolve_league_days_to_rank(self, info, kind):
        viewer = info.context.user
        if viewer_access(viewer) != community.ACCESS_OPEN:
            return None
        return league.days_to_rank_all_time('teams' if kind == 'teams' else 'investors', viewer)

    @login_required
    def resolve_team_invite(self, info, token):
        invite = invites.resolve(info.context.user, token)
        if invite is None:
            return None
        team = invite.team
        return TeamInviteType(team_id=str(team.id), team_name=team.name, emoji=team.emoji, color=team.color,
                              inviter_username=community.author_display_name(invite.inviter),
                              skips_approval=invites.skips_approval(invite))

    @login_required
    def resolve_league_badges(self, info, user_id):
        try:
            return league.badges(user_id=int(user_id))
        except (TypeError, ValueError):
            return []


# ── mutations ────────────────────────────────────────────────────────────────

class TeamResult(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error = graphene.String()
    code = graphene.String()
    team = graphene.Field(TeamType)
    # joined | requested (joinTeam)
    outcome = graphene.String()


def _run(info, fn):
    user, account, business, _ = _context(info)
    try:
        team, outcome = fn(user, business)
    except CommunityPostError as error:
        return TeamResult(success=False, error=error.message, code=error.code)
    return TeamResult(success=True, team=team_type(team, user) if team else None, outcome=outcome)


class CreateTeam(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        description = graphene.String(required=False)
        emoji = graphene.String(required=False)
        color = graphene.String(required=False)
        join_mode = graphene.String(required=False)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, name, description='', emoji=None, color=None, join_mode='open'):
        return _run(info, lambda user, business: (rules.create_team(
            user, business, name, description or '', emoji or rules.EMOJIS[0], color or rules.COLORS[0],
            join_mode or 'open'), 'created'))


class UpdateTeam(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)
        name = graphene.String(required=False)
        description = graphene.String(required=False)
        emoji = graphene.String(required=False)
        color = graphene.String(required=False)
        join_mode = graphene.String(required=False)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id, **fields):
        return _run(info, lambda user, business: (rules.update_team(user, team_id, **fields), 'updated'))


class JoinTeam(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id):
        def run(user, business):
            outcome = rules.join_team(user, business, team_id)
            return Team.objects.get(id=team_id), outcome
        return _run(info, run)


class LeaveTeam(graphene.Mutation):
    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info):
        return _run(info, lambda user, business: (None, 'left' if rules.leave_team(user) else 'none'))


class CancelTeamJoinRequest(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id):
        return _run(info, lambda user, business: (None, 'cancelled' if rules.cancel_request(user, team_id) else 'none'))


class DecideTeamJoinRequest(graphene.Mutation):
    class Arguments:
        request_id = graphene.ID(required=True)
        approve = graphene.Boolean(required=True)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, request_id, approve):
        return _run(info, lambda user, business: (None, rules.decide_request(user, request_id, approve)))


class ExpelTeamMember(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)
        user_id = graphene.ID(required=True)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id, user_id):
        return _run(info, lambda user, business: (None, 'expelled' if rules.expel(user, team_id, user_id) else 'none'))


class TransferTeamCaptain(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)
        user_id = graphene.ID(required=True)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id, user_id):
        return _run(info, lambda user, business: (
            Team.objects.get(id=team_id) if rules.transfer_captain(user, team_id, user_id) else None, 'transferred'))


class FollowTeam(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)
        follow = graphene.Boolean(required=True)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id, follow):
        return _run(info, lambda user, business: (None, 'following' if rules.follow(user, team_id, follow) else 'not_following'))


class SetTeamGoal(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)
        kind = graphene.String(required=True)
        target = graphene.String(required=True)
        deadline = graphene.Date(required=False)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id, kind, target, deadline=None):
        def run(user, business):
            team = Team.objects.filter(id=team_id, archived_at__isnull=True).first()
            if team is None:
                raise CommunityPostError('not_available', rules.MESSAGES['not_available'])
            data.set_goal(user, team, kind, target, deadline)
            return team, 'set'
        return _run(info, run)


class CopiedPlayType(graphene.ObjectType):
    symbol = graphene.String(required=True)
    asset = graphene.String(required=True)
    # "Esto no es una recomendación de Confío. @user compró NVDA el 21 oct."
    disclosure = graphene.String(required=True)


class CopyPlay(graphene.Mutation):
    """Copy play: returns what the buy screen needs; the copier enters
    their own amount and pays the normal fees."""
    class Arguments:
        play_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    code = graphene.String()
    play = graphene.Field(CopiedPlayType)

    @classmethod
    @login_required
    def mutate(cls, root, info, play_id):
        user = info.context.user
        try:
            result = data.copy_play(user, int(play_id))
        except (TypeError, ValueError):
            return CopyPlay(success=False, error='Esta jugada ya no se puede copiar.', code='not_available')
        except CommunityPostError as error:
            return CopyPlay(success=False, error=error.message, code=error.code)
        months = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
        when = result['at']
        ticker = result['symbol'].removesuffix('on')
        disclosure = (f'Esto no es una recomendación de Confío. {community.author_handle(result["owner"])} '
                      f'compró {ticker} el {when.day} {months[when.month - 1]}.')
        return CopyPlay(success=True, play=CopiedPlayType(symbol=result['symbol'], asset=result['asset'],
                                                          disclosure=disclosure))


class TeamInviteType(graphene.ObjectType):
    team_id = graphene.ID(required=True)
    team_name = graphene.String(required=True)
    emoji = graphene.String(required=True)
    color = graphene.String(required=True)
    inviter_username = graphene.String(required=True)
    # Joining through this link skips the captain's approval.
    skips_approval = graphene.Boolean(required=True)


class TeamInviteLinkResult(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error = graphene.String()
    code = graphene.String()
    token = graphene.String()


class CreateTeamInvite(graphene.Mutation):
    """Friend invites: the member's shareable token for their team."""
    class Arguments:
        team_id = graphene.ID(required=True)

    Output = TeamInviteLinkResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id):
        user, account, business, _ = _context(info)
        try:
            invite = invites.invite_link(user, business, team_id)
        except CommunityPostError as error:
            return TeamInviteLinkResult(success=False, error=error.message, code=error.code)
        return TeamInviteLinkResult(success=True, token=invite.token)


class InviteContactsResult(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error = graphene.String()
    code = graphene.String()
    # How many were asked for, never who was actually notified.
    sent = graphene.Int()


class InviteContactsToTeam(graphene.Mutation):
    class Arguments:
        team_id = graphene.ID(required=True)
        # Phone numbers from the sender's contacts (never account ids: knowing
        # the number is the point).
        phones = graphene.List(graphene.NonNull(graphene.String), required=True)

    Output = InviteContactsResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id, phones):
        user, account, business, _ = _context(info)
        try:
            sent = invites.invite_contacts(user, business, team_id, phones)
        except CommunityPostError as error:
            return InviteContactsResult(success=False, error=error.message, code=error.code)
        return InviteContactsResult(success=True, sent=sent)


class JoinTeamWithInvite(graphene.Mutation):
    """joinTeam through an invite link (its own mutation: an older server has none)."""
    class Arguments:
        team_id = graphene.ID(required=True)
        invite_token = graphene.String(required=True)

    Output = TeamResult

    @classmethod
    @login_required
    def mutate(cls, root, info, team_id, invite_token):
        def run(user, business):
            outcome = rules.join_team(user, business, team_id, invite_token=invite_token)
            return Team.objects.get(id=team_id), outcome
        return _run(info, run)


class TeamsMutation(graphene.ObjectType):
    create_team = CreateTeam.Field()
    update_team = UpdateTeam.Field()
    join_team = JoinTeam.Field()
    leave_team = LeaveTeam.Field()
    cancel_team_join_request = CancelTeamJoinRequest.Field()
    decide_team_join_request = DecideTeamJoinRequest.Field()
    expel_team_member = ExpelTeamMember.Field()
    transfer_team_captain = TransferTeamCaptain.Field()
    follow_team = FollowTeam.Field()
    set_team_goal = SetTeamGoal.Field()
    copy_play = CopyPlay.Field()
    create_team_invite = CreateTeamInvite.Field()
    invite_contacts_to_team = InviteContactsToTeam.Field()
    join_team_with_invite = JoinTeamWithInvite.Field()

