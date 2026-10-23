from django.contrib import admin

from .models import (
    CopiedPlay, LeagueSeasonAward, Team, TeamDailyReturn, TeamGoal, TeamInvite, TeamInviteNotice, TeamJoinRequest,
    TeamHistoryExclusion, TeamMembership,
)


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    fields = ('user', 'role', 'joined_at', 'left_at', 'left_reason')
    readonly_fields = fields
    can_delete = False


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """Teams. Staff can archive a team (takedown); members leave with it."""
    list_display = ('id', 'emoji', 'name', 'captain', 'join_mode', 'country', 'created_at', 'archived_at')
    list_filter = ('join_mode', 'country', 'archived_at')
    search_fields = ('name', 'captain__username')
    # Archiving only through the action (everyone leaves with it).
    readonly_fields = ('name_key', 'captain', 'created_at', 'updated_at', 'archived_at')
    inlines = [TeamMembershipInline]
    actions = ('archive_teams',)

    @admin.action(description='Archivar (los miembros salen del equipo)')
    def archive_teams(self, request, queryset):
        from .rules import archive_team

        for team_id in queryset.filter(archived_at__isnull=True).values_list('id', flat=True):
            archive_team(team_id)


class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TeamJoinRequest)
class TeamJoinRequestAdmin(ReadOnly):
    list_display = ('id', 'team', 'user', 'status', 'created_at', 'decided_at')
    list_filter = ('status',)


@admin.register(TeamGoal)
class TeamGoalAdmin(ReadOnly):
    list_display = ('id', 'team', 'kind', 'target', 'deadline', 'reached_at', 'replaced_at')


@admin.register(TeamDailyReturn)
class TeamDailyReturnAdmin(ReadOnly):
    list_display = ('team', 'day', 'daily_return', 'qualifying_members')
    list_filter = ('day',)


@admin.register(LeagueSeasonAward)
class LeagueSeasonAwardAdmin(ReadOnly):
    list_display = ('month', 'kind', 'team', 'user', 'return_pct')


@admin.register(CopiedPlay)
class CopiedPlayAdmin(ReadOnly):
    list_display = ('id', 'user', 'source_user', 'symbol', 'source_batch_id', 'resulting_batch_id', 'created_at')
    search_fields = ('symbol', 'user__username', 'source_user__username')


@admin.register(TeamInvite)
class TeamInviteAdmin(ReadOnly):
    list_display = ('id', 'team', 'inviter', 'created_at', 'expires_at')
    exclude = ('token',)


@admin.register(TeamInviteNotice)
class TeamInviteNoticeAdmin(ReadOnly):
    list_display = ('id', 'team', 'inviter', 'invitee', 'created_at')


@admin.register(TeamHistoryExclusion)
class TeamHistoryExclusionAdmin(ReadOnly):
    list_display = ('user', 'created_at')
