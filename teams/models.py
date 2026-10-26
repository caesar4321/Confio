"""Investor teams and the monthly league.

Spec: caesar4321/Confio#6, children #6 (teams), #7 (league), #9 (goal).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


class TeamJoinMode(models.TextChoices):
    OPEN = 'open', 'Open'
    # Joining asks the captain first.
    APPROVAL = 'approval', 'Approval'


class Team(models.Model):
    """A team of investors. Its name and description are AI-reviewed before
    they are saved; its image is an emoji on a color (no uploads in v1)."""
    name = models.CharField(max_length=24)
    # Lowercased, accents stripped: names are unique ignoring case.
    name_key = models.CharField(max_length=24, unique=True)
    description = models.CharField(max_length=140, blank=True, default='')
    emoji = models.CharField(max_length=8, default='⚽')
    color = models.CharField(max_length=7, default='#34D399')
    captain = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='captained_teams')
    join_mode = models.CharField(max_length=10, choices=TeamJoinMode.choices, default=TeamJoinMode.OPEN)
    # The captain's phone country when created: "same country first".
    country = models.CharField(max_length=2, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # A team with no members left (or taken down) is archived, never deleted.
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['archived_at', 'country'], name='teams_team_active_idx')]

    def __str__(self):
        return f'{self.name} ({self.id})'


class TeamRole(models.TextChoices):
    CAPTAIN = 'captain', 'Captain'
    MEMBER = 'member', 'Member'


class TeamLeaveReason(models.TextChoices):
    # Voluntary: starts the cooldown before joining another team.
    LEFT = 'left', 'Left'
    EXPELLED = 'expelled', 'Expelled'
    # The member hid their investor profile (portfolios are reciprocal).
    PROFILE_HIDDEN = 'profile_hidden', 'Profile hidden'
    ARCHIVED = 'archived', 'Team archived'
    REMOVED = 'removed', 'Removed by moderation'


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_memberships')
    role = models.CharField(max_length=10, choices=TeamRole.choices, default=TeamRole.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    left_reason = models.CharField(max_length=16, choices=TeamLeaveReason.choices, blank=True, default='')

    class Meta:
        constraints = [
            # One team per member at a time.
            models.UniqueConstraint(fields=['user'], condition=Q(left_at__isnull=True),
                                    name='teams_one_active_membership'),
        ]
        indexes = [models.Index(fields=['team', 'left_at'], name='teams_membership_team_idx')]

    def __str__(self):
        return f'{self.user_id} in {self.team_id} ({self.role})'


class TeamJoinRequestStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'
    CANCELLED = 'cancelled', 'Cancelled'


class TeamJoinRequest(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='join_requests')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_join_requests')
    status = models.CharField(max_length=10, choices=TeamJoinRequestStatus.choices,
                              default=TeamJoinRequestStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['team', 'user'], condition=Q(status='pending'),
                                    name='teams_one_pending_request'),
        ]


class TeamFollow(models.Model):
    """Following a team (its page shows "Siguiendo")."""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='follows')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_follows')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['team', 'user'], name='teams_follow_uniq')]


class TeamGoalKind(models.TextChoices):
    # Sum of active members' investment sleeve value at the last snapshot.
    INVESTED_USD = 'invested_usd', 'Invested together (USD)'
    # Members with at least one buy in the current ISO week.
    WEEKLY_INVESTORS = 'weekly_investors', 'Members investing this week'


class TeamGoal(models.Model):
    """Team goal: a shared target with aggregate progress. No money is
    ever pooled, escrowed or moved by a goal."""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='goals')
    kind = models.CharField(max_length=20, choices=TeamGoalKind.choices)
    target = models.DecimalField(max_digits=14, decimal_places=2)
    deadline = models.DateField(null=True, blank=True)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    # Frozen the first time progress reaches the target before the deadline.
    reached_at = models.DateTimeField(null=True, blank=True)
    # The highest milestone already announced to the team (0, 50, 100).
    notified_pct = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    # A new goal replaces the current one.
    replaced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['team'], condition=Q(replaced_at__isnull=True),
                                    name='teams_one_current_goal'),
        ]


class TeamDailyReturn(models.Model):
    """One UTC day of a team (league): the equal-weight mean of its qualifying
    members' daily returns (inbox.PortfolioDailySnapshot)."""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='daily_returns')
    day = models.DateField()
    daily_return = models.DecimalField(max_digits=16, decimal_places=10)
    # The equal-weight mean of the same members' dollar gains that day
    # (realized and unrealized, their own money): what the league ranks by.
    # Null on days computed before it existed, until recomputed.
    mean_gain_usd = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    qualifying_members = models.PositiveSmallIntegerField()
    # Who the day is made of (user ids): read paths re-check each one is still
    # eligible and not in a block with the viewer.
    contributors = models.JSONField(default=list, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['team', 'day'], name='teams_daily_return_uniq')]
        indexes = [models.Index(fields=['day'], name='teams_daily_return_day_idx')]


class LeagueAwardKind(models.TextChoices):
    TEAM = 'team', 'Team'
    INVESTOR = 'investor', 'Investor'


class LeagueSeasonAward(models.Model):
    """Monthly champion: final once written (a badge, never money)."""
    month = models.DateField(help_text='First day of the month')
    kind = models.CharField(max_length=10, choices=LeagueAwardKind.choices)
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='awards')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='league_awards')
    return_pct = models.DecimalField(max_digits=16, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['month', 'kind'], name='teams_award_month_kind_uniq')]


class CopiedPlay(models.Model):
    """Copy play: someone opened a buy from a member's play. Attribution
    only; the copier pays the normal fees and nobody is paid for it."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='copied_plays')
    source_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plays_copied')
    # The member's confirmed buy batch (blockchain.SponsoredBatch).
    source_batch_id = models.BigIntegerField()
    symbol = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set once the copier's own buy of the symbol confirms after this.
    resulting_batch_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['source_batch_id', 'created_at'], name='teams_copied_source_idx'),
            models.Index(fields=['user', 'symbol', 'created_at'], name='teams_copied_user_idx'),
        ]


class CopiedPlayNotice(models.Model):
    """The once-per-play-per-day claim for the "copiaron tu jugada" push."""
    source_batch_id = models.BigIntegerField()
    day = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source_batch_id', 'day'], name='teams_copied_notice_uniq')]


class TeamInvite(models.Model):
    """Friend invites: one shareable link per member per team. Joining
    through the captain's link (or any member's link to an open team) skips
    the approval step; nothing else about joining changes."""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invites')
    inviter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_invites')
    token = models.CharField(max_length=32, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=['team', 'inviter', 'expires_at'], name='teams_invite_member_idx')]


class TeamInviteNotice(models.Model):
    """One contact invite attempt. Every attempt counts toward the daily cap
    (sent or not, so the cap says nothing about who got a push); `invitee`
    is set only when a push went out, and the once-a-week-per-team rule
    reads those."""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invite_notices')
    inviter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    invitee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['inviter', 'created_at'], name='teams_notice_inviter_idx'),
            models.Index(fields=['team', 'invitee', 'created_at'], name='teams_notice_invitee_idx'),
        ]


class TeamHistoryExclusion(models.Model):
    """Someone whose past team days were recomputed without them (hidden,
    unverified, banned, deleted). The nightly repair puts them back once they
    may be shown again, so all-time returns never stay wrong."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
