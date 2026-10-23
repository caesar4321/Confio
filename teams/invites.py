"""Friend invites: a member shares their team link (WhatsApp, the share
sheet) or pings contacts already on Confío. An invite only opens the door:
joining still needs a verified, public profile, a free spot and no block.

What it changes: someone who arrives through the captain's link joins
without waiting for approval (any member's link already does that for an
open team; in an approval team a member's link still sends a request)."""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from inbox import community
from inbox.community import CommunityPostError

from . import rules
from .models import Team, TeamInvite, TeamInviteNotice, TeamJoinMode

INVITE_TTL = timedelta(days=14)
# A link about to expire is replaced rather than handed out again.
REUSE_MARGIN = timedelta(days=1)
PER_CALL = 10
DAILY_PUSHES = 20
# One push per team per person per week, whoever sends it.
RENOTIFY_AFTER = timedelta(days=7)

MESSAGES = {
    'not_member': 'Solo los miembros del equipo pueden invitar.',
    'invite_limit': 'Ya enviaste muchas invitaciones hoy. Inténtalo mañana.',
}


def _member_team(user, business, team_id) -> Team:
    block = rules.member_block(user, business)
    if block:
        raise CommunityPostError(block, rules.MESSAGES[block])
    membership = rules.active_membership(user)
    if membership is None or str(membership.team_id) != str(team_id):
        raise CommunityPostError('not_member', MESSAGES['not_member'])
    return membership.team


def invite_link(user, business, team_id) -> TeamInvite:
    """The member's link for this team (the same one until it nears expiry)."""
    team = _member_team(user, business, team_id)
    now = timezone.now()
    current = (TeamInvite.objects.filter(team=team, inviter=user, expires_at__gt=now + REUSE_MARGIN)
               .order_by('-expires_at').first())
    if current is not None:
        return current
    return TeamInvite.objects.create(team=team, inviter=user, token=new_token(), expires_at=now + INVITE_TTL)


# Lowercase letters and digits only (~103 bits): the link may come back
# upper-cased (a store referrer, a typed code), so lookups ignore case.
_TOKEN_ALPHABET = 'abcdefghijkmnpqrstuvwxyz23456789'


def new_token() -> str:
    return ''.join(secrets.choice(_TOKEN_ALPHABET) for _ in range(21))


def _valid(token: str):
    """The invite behind a token while it still means something: not expired,
    the team active and its inviter still in it."""
    if not token or len(token) > 32:
        return None
    invite = (TeamInvite.objects.select_related('team', 'inviter')
              .filter(token=token.lower(), expires_at__gt=timezone.now(), team__archived_at__isnull=True).first())
    if invite is None:
        return None
    membership = rules.active_membership(invite.inviter)
    if membership is None or membership.team_id != invite.team_id or rules.member_block(invite.inviter):
        return None
    return invite


def skips_approval(invite) -> bool:
    return invite.team.join_mode == TeamJoinMode.OPEN or invite.inviter_id == invite.team.captain_id


def resolve(viewer, token: str):
    """What the invite page shows, or None (expired, gone, or the viewer is in
    a block with the inviter or the captain: indistinguishable on purpose)."""
    invite = _valid(token)
    if invite is None:
        return None
    if (community.is_blocked_between(viewer.id, invite.inviter_id)
            or community.is_blocked_between(viewer.id, invite.team.captain_id)):
        return None
    return invite


def invite_for_join(user, team_id, token: str):
    """The invite that lets this person skip approval for this team, or None."""
    invite = resolve(user, token)
    if invite is None or str(invite.team_id) != str(team_id) or not skips_approval(invite):
        return None
    return invite


def invite_contacts(user, business, team_id, phones) -> int:
    """Pushes to contacts on Confío, by phone number (knowing the number is
    what makes them a contact; account ids are never taken). The answer and
    the daily cap never say who got one: who is on Confío, already in the
    team, in a block with you or invited this week stays private. Returns
    how many numbers were tried."""
    from users.models import User
    from users.phone_utils import phone_lookup_key

    team = _member_team(user, business, team_id)
    keys = []
    for phone in phones or []:
        key = phone_lookup_key(phone) if isinstance(phone, str) else None
        if key and key not in keys:
            keys.append(key)
    keys = keys[:PER_CALL]
    if not keys:
        return 0
    invite = invite_link(user, business, team.id)
    now = timezone.now()
    sent = []
    with transaction.atomic():
        # The inviter (the cap), then the team (the weekly rule across members): join_team's order.
        rules._lock(user.id)
        rules._lock_team(team.id)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        used = TeamInviteNotice.objects.filter(inviter=user, created_at__gte=today).count()
        if used + len(keys) > DAILY_PUSHES:
            raise CommunityPostError('invite_limit', MESSAGES['invite_limit'])
        # One account per number; a number shared by several accounts reaches none.
        by_key = {}
        for uid, key in User.objects.filter(phone_key__in=keys, is_active=True, deleted_at__isnull=True).values_list('id', 'phone_key'):
            by_key[key] = None if key in by_key else uid
        members = set(rules.active_members(team).values_list('user_id', flat=True))
        targets = [uid for uid in by_key.values() if uid]
        recent = set(TeamInviteNotice.objects.filter(team=team, invitee_id__in=targets, created_at__gte=now - RENOTIFY_AFTER)
                     .values_list('invitee_id', flat=True))
        for key in keys:
            uid = by_key.get(key)
            ok = (uid and uid != user.id and uid not in members and uid not in recent
                  and not community.is_blocked_between(user.id, uid)
                  and not community.is_blocked_between(team.captain_id, uid))
            TeamInviteNotice.objects.create(team=team, inviter=user, invitee_id=uid if ok else None)
            if ok:
                sent.append(uid)
                recent.add(uid)
    if sent:
        handle = community.author_handle(user)
        for invitee in User.objects.filter(id__in=sent):
            community._notify(invitee, 'COMMUNITY_TEAM_INVITE', f'{handle} te invita a su equipo',
                              f'Únete a {team.emoji} {team.name} en la Liga Confío.',
                              action_url=f'confio://community/team-invite/{invite.token}',
                              data={'team_id': team.id})
    return len(keys)
