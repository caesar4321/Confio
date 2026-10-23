"""Teams: who can create, join and leave a team, and what captains can do.

Lock order, everywhere: the people involved (User rows, by id), then the
team, then memberships and join requests. Every check that matters is
repeated after the locks are held.

- Joining needs what seeing other investors needs (reciprocity): a verified
  identity and a PUBLIC investor profile, plus the community rules. Hiding
  your profile ends your membership (no cooldown for that).
- One team per member; MAX_MEMBERS per team. Leaving voluntarily starts a
  COOLDOWN before joining another team; being expelled doesn't.
- The captain edits the team (name/description AI-reviewed), switches
  open/approval, approves requests, expels, hands over the captaincy and
  sets the goal. A captain who leaves passes the captaincy to the
  earliest-joined member; a team with no members is archived.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from inbox import community, dm_gate
from inbox.community import CommunityPostError, ReviewUnavailable

from .models import (
    Team,
    TeamFollow,
    TeamJoinMode,
    TeamJoinRequest,
    TeamJoinRequestStatus as RequestStatus,
    TeamLeaveReason,
    TeamMembership,
    TeamRole,
)

logger = logging.getLogger(__name__)

MAX_MEMBERS = 20
COOLDOWN = timedelta(days=7)
NAME_MIN, NAME_MAX = 3, 24
DESCRIPTION_MAX = 140
EMOJIS = ['⚽', '🚀', '🦁', '🐂', '🦅', '🔥', '💎', '🌎', '📈', '🌱', '⭐', '🏆', '🐺', '🦉', '⚡', '🎯']
COLORS = ['#34D399', '#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#14B8A6', '#111827']

MESSAGES = {
    'identity_required': 'Verifica tu identidad para unirte a un equipo.',
    'portfolio_must_be_public': 'Para unirte a un equipo, tu portafolio debe ser público.',
    'rules_required': 'Acepta las normas de la comunidad para unirte a un equipo.',
    'business_context': 'Los equipos son para tu cuenta personal.',
    'not_available': 'Este equipo ya no está disponible.',
    'already_in_team': 'Ya estás en un equipo. Sal de él para unirte a otro.',
    'cooldown': 'Saliste de un equipo hace poco. Podrás unirte a otro 7 días después.',
    'team_full': 'Este equipo ya tiene 20 miembros.',
    'name_taken': 'Ya existe un equipo con ese nombre.',
    'name_length': f'El nombre va de {NAME_MIN} a {NAME_MAX} caracteres.',
    'description_length': f'La descripción tiene un máximo de {DESCRIPTION_MAX} caracteres.',
    'review_unavailable': 'No pudimos revisar el nombre ahora. Inténtalo de nuevo.',
    'not_captain': 'Solo el capitán puede hacer esto.',
    'not_member': 'Esa persona no está en tu equipo.',
    'bad_style': 'Elige un emoji y un color de la lista.',
}


def _error(code: str, message: str | None = None) -> CommunityPostError:
    return CommunityPostError(code, message or MESSAGES[code])


def name_key(name: str) -> str:
    text = unicodedata.normalize('NFKD', name or '')
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(text.lower().split())[:NAME_MAX]


# ── who can play ─────────────────────────────────────────────────────────────

def member_block(user, business=None) -> str | None:
    """Why this person can't be on a team right now (None: they can)."""
    if business is not None:
        return 'business_context'
    if community.author_block(user):
        return 'identity_required' if not community.is_verified_member(user) else 'not_available'
    if community.portfolio_hidden(user):
        return 'portfolio_must_be_public'
    if not community.has_accepted_rules(user):
        return 'rules_required'
    return None


def active_membership(user):
    return TeamMembership.objects.select_related('team').filter(user=user, left_at__isnull=True).first()


def active_members(team):
    return TeamMembership.objects.filter(team=team, left_at__isnull=True).select_related('user').order_by(
        'joined_at', 'id')


def in_cooldown(user) -> bool:
    last = (TeamMembership.objects.filter(user=user, left_reason=TeamLeaveReason.LEFT)
            .order_by('-left_at').first())
    return bool(last and last.left_at and timezone.now() - last.left_at < COOLDOWN)


def _lock(*user_ids):
    from users.models import User

    for uid in sorted({int(u) for u in user_ids if u}):
        User.objects.select_for_update().filter(pk=uid).first()


def _lock_team(team_id):
    return Team.objects.select_for_update().filter(id=team_id, archived_at__isnull=True).first()


# ── text review ──────────────────────────────────────────────────────────────

def _review_text(name: str, description: str) -> None:
    """Same prefilter as messages for contact info, then the community
    review. No verdict, no team (fails closed)."""
    for text in (name, description):
        if text and (dm_gate.prefilter(text) or (text is name and dm_gate.username_unsafe(text))):
            raise _error('rejected', dm_gate.CONTACT_REASON)
    body = f'Team name: {name}\nTeam description: {description}'
    context = ('This is the NAME and DESCRIPTION of an investing TEAM shown publicly in a league table. '
               'Apply the same policy.\n')
    try:
        verdict = community._first_pass(body, None, context)
        if community._needs_escalation(verdict):
            verdict = community._escalation(body, None, context)
    except ReviewUnavailable:
        raise _error('review_unavailable')
    if verdict['decision'] != 'approve':
        raise _error('rejected', str(verdict.get('reason') or '') or 'El nombre o la descripción no cumplen las normas.')


def _clean(name: str, description: str, emoji: str, color: str) -> tuple[str, str]:
    name = ' '.join((name or '').split())
    description = ' '.join((description or '').split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise _error('name_length')
    if len(description) > DESCRIPTION_MAX:
        raise _error('description_length')
    if emoji not in EMOJIS or color not in COLORS:
        raise _error('bad_style')
    return name, description


# ── create, edit, join, leave ────────────────────────────────────────────────

def create_team(user, business, name: str, description: str = '', emoji: str = EMOJIS[0],
                color: str = COLORS[0], join_mode: str = TeamJoinMode.OPEN) -> Team:
    block = member_block(user, business)
    if block:
        raise _error(block)
    name, description = _clean(name, description, emoji, color)
    if join_mode not in TeamJoinMode.values:
        join_mode = TeamJoinMode.OPEN
    if Team.objects.filter(name_key=name_key(name)).exists():
        raise _error('name_taken')
    if active_membership(user) is not None:
        raise _error('already_in_team')
    if in_cooldown(user):
        raise _error('cooldown')
    _review_text(name, description)
    with transaction.atomic():
        _lock(user.id)
        if active_membership(user) is not None:
            raise _error('already_in_team')
        if in_cooldown(user):
            raise _error('cooldown')
        if member_block(user, business):
            raise _error(member_block(user, business))
        try:
            with transaction.atomic():
                team = Team.objects.create(
                    name=name, name_key=name_key(name), description=description, emoji=emoji, color=color,
                    captain=user, join_mode=join_mode, country=(getattr(user, 'phone_country', '') or '')[:2])
        except IntegrityError:
            raise _error('name_taken')
        TeamMembership.objects.create(team=team, user=user, role=TeamRole.CAPTAIN)
        _cancel_requests(user)
    return team


def update_team(user, team_id, *, name=None, description=None, emoji=None, color=None, join_mode=None) -> Team:
    team = Team.objects.filter(id=team_id, archived_at__isnull=True).first()
    if team is None:
        raise _error('not_available')
    if team.captain_id != user.id:
        raise _error('not_captain')
    new_name = team.name if name is None else name
    new_description = team.description if description is None else description
    new_name, new_description = _clean(new_name, new_description, emoji or team.emoji, color or team.color)
    text_changed = new_name != team.name or new_description != team.description
    if new_name != team.name and Team.objects.filter(name_key=name_key(new_name)).exclude(id=team.id).exists():
        raise _error('name_taken')
    if text_changed:
        _review_text(new_name, new_description)
    with transaction.atomic():
        team = _lock_team(team.id)
        if team is None or team.captain_id != user.id:
            raise _error('not_captain')
        team.name, team.name_key, team.description = new_name, name_key(new_name), new_description
        team.emoji, team.color = emoji or team.emoji, color or team.color
        if join_mode in TeamJoinMode.values:
            team.join_mode = join_mode
        try:
            with transaction.atomic():
                team.save()
        except IntegrityError:
            raise _error('name_taken')
    return team


def _cancel_requests(user):
    TeamJoinRequest.objects.filter(user=user, status=RequestStatus.PENDING).update(
        status=RequestStatus.CANCELLED, decided_at=timezone.now())


def _add_member(team, user):
    if active_members(team).count() >= MAX_MEMBERS:
        raise _error('team_full')
    TeamMembership.objects.create(team=team, user=user, role=TeamRole.MEMBER)
    _cancel_requests(user)


def join_team(user, business, team_id, invite_token: str | None = None) -> str:
    """'joined', or 'requested' for a team that approves members (unless
    the person came through the captain's invite link)."""
    block = member_block(user, business)
    if block:
        raise _error(block)
    with transaction.atomic():
        _lock(user.id)
        team = _lock_team(team_id)
        if team is None:
            raise _error('not_available')
        # Again under the lock hiding also takes: a profile hidden meanwhile can't join.
        block = member_block(user, business)
        if block:
            raise _error(block)
        if active_membership(user) is not None:
            raise _error('already_in_team')
        if in_cooldown(user):
            raise _error('cooldown')
        if community.is_blocked_between(user.id, team.captain_id):
            raise _error('not_available')
        if team.join_mode == TeamJoinMode.APPROVAL and not (
                invite_token and _invite_skips(user, team.id, invite_token)):
            if active_members(team).count() >= MAX_MEMBERS:
                raise _error('team_full')
            TeamJoinRequest.objects.get_or_create(team=team, user=user, status=RequestStatus.PENDING)
            return 'requested'
        _add_member(team, user)
    return 'joined'


def _invite_skips(user, team_id, token) -> bool:
    from .invites import invite_for_join

    return invite_for_join(user, team_id, token) is not None


def cancel_request(user, team_id) -> bool:
    return bool(TeamJoinRequest.objects.filter(team_id=team_id, user=user, status=RequestStatus.PENDING)
                .update(status=RequestStatus.CANCELLED, decided_at=timezone.now()))


def decide_request(captain, request_id, approve: bool) -> str:
    peek = TeamJoinRequest.objects.filter(id=request_id).values_list('user_id', 'team_id').first()
    if peek is None:
        raise _error('not_available')
    with transaction.atomic():
        _lock(captain.id, peek[0])
        team = _lock_team(peek[1])
        if team is None or team.captain_id != captain.id:
            raise _error('not_captain')
        request = TeamJoinRequest.objects.select_for_update().select_related('user').filter(
            id=request_id, status=RequestStatus.PENDING).first()
        if request is None:
            raise _error('not_available')
        request.decided_at = timezone.now()
        if not approve:
            request.status = RequestStatus.REJECTED
            request.save(update_fields=['status', 'decided_at'])
            return 'rejected'
        candidate = request.user
        if (member_block(candidate) or active_membership(candidate) is not None or in_cooldown(candidate)
                or community.is_blocked_between(candidate.id, team.captain_id)):
            request.status = RequestStatus.CANCELLED
            request.save(update_fields=['status', 'decided_at'])
            raise _error('not_available', 'Esa persona ya no puede unirse.')
        _add_member(team, candidate)
        request.status = RequestStatus.APPROVED
        request.save(update_fields=['status', 'decided_at'])
    return 'approved'


def _end(membership, reason: str):
    """End one membership under the team lock (caller holds it): hand over
    the captaincy, or archive an empty team."""
    now = timezone.now()
    membership.left_at, membership.left_reason = now, reason
    was_captain = membership.role == TeamRole.CAPTAIN
    membership.role = TeamRole.MEMBER if was_captain else membership.role
    membership.save(update_fields=['left_at', 'left_reason', 'role'])
    team = membership.team
    if not was_captain:
        return
    successor = active_members(team).first()
    if successor is None:
        team.archived_at = now
        team.save(update_fields=['archived_at', 'updated_at'])
        TeamJoinRequest.objects.filter(team=team, status=RequestStatus.PENDING).update(
            status=RequestStatus.CANCELLED, decided_at=now)
        return
    successor.role = TeamRole.CAPTAIN
    successor.save(update_fields=['role'])
    team.captain_id = successor.user_id
    team.save(update_fields=['captain', 'updated_at'])


def leave_team(user, reason: str = TeamLeaveReason.LEFT) -> bool:
    with transaction.atomic():
        _lock(user.id)
        peek = TeamMembership.objects.filter(user=user, left_at__isnull=True).values_list('team_id', flat=True).first()
        if peek is None:
            return False
        team = Team.objects.select_for_update().get(id=peek)
        membership = TeamMembership.objects.select_for_update().filter(
            user=user, team=team, left_at__isnull=True).first()
        if membership is None:
            return False
        membership.team = team
        _end(membership, reason)
    return True


def recompute_member_teams(user) -> None:
    """Every team this person was on within the computed window: their days
    stop counting at once (they hid their profile or were removed), not at
    the next nightly run."""
    from django.db.models import Q

    from .league import COMPUTE_DAYS, recompute_team

    since = timezone.now() - timedelta(days=COMPUTE_DAYS + 1)
    team_ids = set(TeamMembership.objects.filter(user=user).filter(Q(left_at__isnull=True) | Q(left_at__gte=since))
                   .values_list('team_id', flat=True))

    def run():
        for team in Team.objects.filter(id__in=team_ids):
            recompute_team(team, invalidate=True)
        # Older days too (all time reaches past the window), in the background:
        # without them now, with them again if they show their profile later.
        _schedule_history(user)

    transaction.on_commit(run)


def archive_team(team_id, reason: str = TeamLeaveReason.ARCHIVED) -> bool:
    """Staff takedown: everyone leaves and the team is archived, in one
    transaction under the team lock (a join can't slip in between)."""
    with transaction.atomic():
        team = _lock_team(team_id)
        if team is None:
            return False
        now = timezone.now()
        for membership in TeamMembership.objects.select_for_update().filter(team=team, left_at__isnull=True):
            membership.left_at, membership.left_reason = now, reason
            membership.save(update_fields=['left_at', 'left_reason'])
        TeamJoinRequest.objects.filter(team=team, status=RequestStatus.PENDING).update(
            status=RequestStatus.CANCELLED, decided_at=now)
        team.archived_at = now
        team.save(update_fields=['archived_at', 'updated_at'])
    return True


def expel(captain, team_id, user_id) -> bool:
    with transaction.atomic():
        _lock(captain.id, user_id)
        team = _lock_team(team_id)
        if team is None or team.captain_id != captain.id:
            raise _error('not_captain')
        if int(user_id) == captain.id:
            raise _error('not_member')
        membership = TeamMembership.objects.select_for_update().filter(
            team=team, user_id=user_id, left_at__isnull=True).first()
        if membership is None:
            raise _error('not_member')
        membership.team = team
        _end(membership, TeamLeaveReason.EXPELLED)
    return True


def transfer_captain(captain, team_id, user_id) -> bool:
    with transaction.atomic():
        _lock(captain.id, user_id)
        team = _lock_team(team_id)
        if team is None or team.captain_id != captain.id:
            raise _error('not_captain')
        new = TeamMembership.objects.select_for_update().filter(team=team, user_id=user_id,
                                                                left_at__isnull=True).first()
        if new is None or new.user_id == captain.id:
            raise _error('not_member')
        TeamMembership.objects.filter(team=team, user=captain, left_at__isnull=True).update(role=TeamRole.MEMBER)
        new.role = TeamRole.CAPTAIN
        new.save(update_fields=['role'])
        team.captain_id = new.user_id
        team.save(update_fields=['captain', 'updated_at'])
    return True


def on_profile_hidden(user) -> None:
    """Portfolios are reciprocal: hiding yours takes you off your team. Runs
    inside the hide's own transaction: both happen, or neither."""
    recompute_member_teams(user)
    leave_team(user, TeamLeaveReason.PROFILE_HIDDEN)
    _cancel_requests(user)


def _schedule_history(user) -> None:
    from .tasks import recompute_member_history_task

    try:
        recompute_member_history_task.delay(user.id)
    except Exception:  # noqa: BLE001
        logger.exception('teams: could not queue the history recompute for %s', user.id)


def on_profile_shown(user) -> None:
    """Showing the profile again restores the person's past team days."""
    transaction.on_commit(lambda: _schedule_history(user))


def follow(user, team_id, on: bool) -> bool:
    team = Team.objects.filter(id=team_id, archived_at__isnull=True).first()
    if team is None:
        raise _error('not_available')
    if on:
        TeamFollow.objects.get_or_create(team=team, user=user)
    else:
        TeamFollow.objects.filter(team=team, user=user).delete()
    return on
