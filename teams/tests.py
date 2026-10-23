from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from inbox import community
from inbox.models import PortfolioDailySnapshot
from inbox.schema import SetCommunityPortfolioHidden
from inbox.test_community import APPROVE, REJECT, MockInfo, make_user

from . import data, league, rules
from .models import LeagueSeasonAward, Team, TeamDailyReturn, TeamGoal, TeamLeaveReason, TeamMembership
from .schema import TeamsQuery


def approve_reviews():
    return patch('inbox.community._first_pass', return_value=APPROVE)


class TeamTestBase(TestCase):
    def create(self, captain=None, name='Los Constantes', **kw):
        captain = captain or make_user()
        with approve_reviews():
            return rules.create_team(captain, None, name, kw.pop('description', ''), **kw), captain


class CreateTests(TeamTestBase):
    def test_a_verified_public_member_creates_a_team_and_is_captain(self):
        team, captain = self.create()
        self.assertEqual(team.captain_id, captain.id)
        self.assertEqual(rules.active_membership(captain).role, 'captain')

    def test_names_are_unique_ignoring_case_and_accents(self):
        self.create(name='Inversión Norte')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.create(name='INVERSION norte')
        self.assertEqual(ctx.exception.code, 'name_taken')

    def test_a_rejected_or_contact_name_never_saves(self):
        with patch('inbox.community._first_pass', return_value=REJECT), self.assertRaises(community.CommunityPostError):
            rules.create_team(make_user(), None, 'Escríbanme', '')
        with self.assertRaises(community.CommunityPostError):
            rules.create_team(make_user(), None, 'whatsapp_7123456', '')
        self.assertFalse(Team.objects.exists())

    def test_hidden_or_unverified_profiles_cant_create(self):
        user = make_user()
        SetCommunityPortfolioHidden.mutate(None, MockInfo(user), hidden=True)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.create(captain=user)
        self.assertEqual(ctx.exception.code, 'portfolio_must_be_public')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.create(captain=make_user(verified=False))
        self.assertEqual(ctx.exception.code, 'identity_required')

    def test_style_must_come_from_the_palette(self):
        with self.assertRaises(community.CommunityPostError):
            self.create(emoji='💩')


class MembershipTests(TeamTestBase):
    def test_join_leave_cooldown(self):
        team, _ = self.create()
        member = make_user()
        self.assertEqual(rules.join_team(member, None, team.id), 'joined')
        with self.assertRaises(community.CommunityPostError) as ctx:
            rules.join_team(member, None, team.id)
        self.assertEqual(ctx.exception.code, 'already_in_team')
        rules.leave_team(member)
        other, _ = self.create(name='Otro Equipo')
        with self.assertRaises(community.CommunityPostError) as ctx:
            rules.join_team(member, None, other.id)
        self.assertEqual(ctx.exception.code, 'cooldown')
        TeamMembership.objects.filter(user=member).update(left_at=timezone.now() - rules.COOLDOWN - timedelta(hours=1))
        self.assertEqual(rules.join_team(member, None, other.id), 'joined')

    def test_expelled_members_have_no_cooldown(self):
        team, captain = self.create()
        member = make_user()
        rules.join_team(member, None, team.id)
        rules.expel(captain, team.id, member.id)
        other, _ = self.create(name='Otro Equipo')
        self.assertEqual(rules.join_team(member, None, other.id), 'joined')

    def test_one_active_membership_is_a_database_rule(self):
        from django.db import IntegrityError, transaction

        team, captain = self.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMembership.objects.create(team=team, user=captain)

    def test_max_members(self):
        team, _ = self.create()
        for _ in range(rules.MAX_MEMBERS - 1):
            rules.join_team(make_user(), None, team.id)
        with self.assertRaises(community.CommunityPostError) as ctx:
            rules.join_team(make_user(), None, team.id)
        self.assertEqual(ctx.exception.code, 'team_full')

    def test_approval_mode(self):
        team, captain = self.create(join_mode='approval')
        member = make_user()
        self.assertEqual(rules.join_team(member, None, team.id), 'requested')
        request = team.join_requests.get()
        with self.assertRaises(community.CommunityPostError):
            rules.decide_request(member, request.id, True)          # not the captain
        self.assertEqual(rules.decide_request(captain, request.id, True), 'approved')
        self.assertEqual(rules.active_membership(member).team_id, team.id)

    def test_captain_leaving_hands_over_or_archives(self):
        team, captain = self.create()
        first, second = make_user(), make_user()
        rules.join_team(first, None, team.id)
        rules.join_team(second, None, team.id)
        rules.leave_team(captain)
        team.refresh_from_db()
        self.assertEqual(team.captain_id, first.id)
        rules.leave_team(first)
        rules.leave_team(second)
        team.refresh_from_db()
        self.assertIsNotNone(team.archived_at)

    def test_hiding_your_profile_takes_you_off_the_team_without_cooldown(self):
        team, _ = self.create()
        member = make_user()
        rules.join_team(member, None, team.id)
        with self.captureOnCommitCallbacks(execute=True):
            SetCommunityPortfolioHidden.mutate(None, MockInfo(member), hidden=True)
        self.assertIsNone(rules.active_membership(member))
        self.assertEqual(TeamMembership.objects.get(user=member).left_reason, TeamLeaveReason.PROFILE_HIDDEN)
        self.assertFalse(rules.in_cooldown(member))

    def test_transfer_captain(self):
        team, captain = self.create()
        member = make_user()
        rules.join_team(member, None, team.id)
        rules.transfer_captain(captain, team.id, member.id)
        team.refresh_from_db()
        self.assertEqual(team.captain_id, member.id)
        self.assertEqual(rules.active_membership(captain).role, 'member')


class LeagueTests(TeamTestBase):
    DAY = date(2026, 10, 21)

    def setUp(self):
        from django.core.cache import cache

        cache.clear()          # league tables are cached between requests

    def snap(self, user, day, ret, start='100', trusted=True):
        from users.models import Account

        wallet = f'0x{user.id:040x}'
        Account.objects.filter(user=user, account_type='personal').update(bsc_address=wallet)
        PortfolioDailySnapshot.objects.create(
            user=user, wallet=wallet, day=day, value_start_usd=Decimal(start),
            value_end_usd=Decimal(start), net_flow_usd=Decimal('0'), gain_usd=Decimal('0'),
            daily_return=Decimal(ret) if trusted else None, ledger_trusted=trusted)

    def team_with(self, n, name='Liga A'):
        team, captain = self.create(name=name)
        members = [captain] + [make_user() for _ in range(n - 1)]
        for m in members[1:]:
            rules.join_team(m, None, team.id)
        TeamMembership.objects.filter(team=team).update(joined_at=timezone.now() - timedelta(days=40))
        return team, members

    def test_team_day_is_the_equal_weight_mean_of_qualifying_members(self):
        team, members = self.team_with(3)
        self.snap(members[0], self.DAY, '0.10', start='10000')      # a whale counts once
        self.snap(members[1], self.DAY, '0.00', start='20')
        self.snap(members[2], self.DAY, '0.05', start='5')          # under $10: doesn't qualify
        self.assertTrue(league.compute_team_day(team, self.DAY))
        row = TeamDailyReturn.objects.get(team=team, day=self.DAY)
        self.assertEqual((row.daily_return, row.qualifying_members), (Decimal('0.05'), 2))

    def test_joining_mid_day_doesnt_count_that_day(self):
        team, members = self.team_with(2)
        TeamMembership.objects.filter(user=members[1]).update(joined_at=timezone.make_aware(
            timezone.datetime(2026, 10, 21, 12)))
        self.snap(members[0], self.DAY, '0.01')
        self.snap(members[1], self.DAY, '0.50')
        league.compute_team_day(team, self.DAY)
        self.assertEqual(TeamDailyReturn.objects.get(team=team, day=self.DAY).qualifying_members, 1)

    def test_a_team_needs_five_qualifying_members_to_rank(self):
        small, small_members = self.team_with(4, 'Chico')
        big, big_members = self.team_with(5, 'Grande')
        for m in small_members + big_members:
            self.snap(m, self.DAY, '0.02')
        league.compute_team_day(small, self.DAY)
        league.compute_team_day(big, self.DAY)
        self.assertEqual([r.team_id for r in league.team_table([self.DAY])], [big.id])

    def test_investor_table_needs_every_day_proven_and_ten_dollars(self):
        a, b, c = make_user(), make_user(), make_user()
        days = [self.DAY - timedelta(days=1), self.DAY]
        for d in days:
            self.snap(a, d, '0.01')
        self.snap(b, days[0], '0.01')
        self.snap(b, days[1], '0', trusted=False)
        for d in days:
            self.snap(c, d, '0.10', start='5')
        self.assertEqual([r.user_id for r in league.investor_table(days)], [a.id])

    def test_locked_viewers_see_only_the_top_three(self):
        viewer = make_user()
        SetCommunityPortfolioHidden.mutate(None, MockInfo(viewer), hidden=True)
        users = [make_user() for _ in range(5)]
        for i, u in enumerate(users):
            self.snap(u, self.DAY, f'0.0{i}')
        with patch('teams.league.window', return_value=[self.DAY]):
            result = TeamsQuery().resolve_league_table(MockInfo(viewer), 'investors', '24h')
        self.assertEqual((len(result.rows), result.access, result.has_more), (3, 'viewer_hidden', False))

    def test_the_month_award_is_written_once(self):
        team, members = self.team_with(5)
        month = date(2026, 9, 1)
        for d in league.month_window(month):
            for m in members:
                self.snap(m, d, '0.001')
            league.compute_team_day(team, d)
        first = league.award_month(month)
        self.assertEqual(len(first), 2)
        self.assertEqual(league.award_month(month), [])
        self.assertEqual(league.badges(team_id=team.id), ['2026-09'])
        self.assertEqual(LeagueSeasonAward.objects.count(), 2)


class ReciprocityTests(TeamTestBase):
    def test_team_investment_data_is_locked_for_hidden_viewers(self):
        team, _ = self.create()
        viewer = make_user()
        SetCommunityPortfolioHidden.mutate(None, MockInfo(viewer), hidden=True)
        q = TeamsQuery()
        self.assertEqual(q.resolve_team_members(MockInfo(viewer), str(team.id)), [])
        self.assertEqual(q.resolve_team_positions(MockInfo(viewer), str(team.id)), [])
        self.assertEqual(q.resolve_team_plays(MockInfo(viewer), str(team.id)), [])
        page = q.resolve_team(MockInfo(viewer), str(team.id))
        self.assertEqual((page.access, page.return_pct, page.goal), ('viewer_hidden', None, None))
        self.assertEqual(page.join_block, 'portfolio_must_be_public')

    def test_copying_a_play_needs_a_public_profile(self):
        viewer = make_user()
        SetCommunityPortfolioHidden.mutate(None, MockInfo(viewer), hidden=True)
        with self.assertRaises(community.CommunityPostError):
            data.copy_play(viewer, 999999)


class GoalTests(TeamTestBase):
    def test_only_the_captain_sets_a_goal_and_it_freezes_when_reached(self):
        team, captain = self.create()
        with self.assertRaises(community.CommunityPostError):
            data.set_goal(make_user(), team, 'invested_usd', '500')
        with self.assertRaises(community.CommunityPostError):
            data.set_goal(captain, team, 'invested_usd', '50')        # below the minimum
        goal = data.set_goal(captain, team, 'invested_usd', '100')
        from users.models import Account

        Account.objects.filter(user=captain, account_type='personal').update(bsc_address='0xabc')
        PortfolioDailySnapshot.objects.create(
            user=captain, wallet='0xabc', day=date(2026, 10, 21), value_start_usd=Decimal('90'),
            value_end_usd=Decimal('150'), net_flow_usd=Decimal('0'), gain_usd=Decimal('60'),
            daily_return=Decimal('0.5'), ledger_trusted=True)
        progress, pct = data.refresh_goal(team, goal)
        self.assertEqual((progress, pct), (Decimal('150'), 100))
        goal.refresh_from_db()
        self.assertIsNotNone(goal.reached_at)

    def test_a_new_goal_replaces_the_current_one(self):
        team, captain = self.create()
        data.set_goal(captain, team, 'invested_usd', '100')
        with self.assertRaises(community.CommunityPostError):
            data.set_goal(captain, team, 'weekly_investors', '3')          # once a week
        TeamGoal.objects.update(created_at=timezone.now() - data.GOAL_CHANGE_EVERY - timedelta(hours=1))
        data.set_goal(captain, team, 'weekly_investors', '3')
        self.assertEqual(TeamGoal.objects.filter(team=team, replaced_at__isnull=True).get().kind, 'weekly_investors')

    def test_amount_targets_are_coarse(self):
        team, captain = self.create()
        with self.assertRaises(community.CommunityPostError):
            data.set_goal(captain, team, 'invested_usd', '1434.56')


class ProtectionTests(LeagueTests):
    """(Also re-runs the LeagueTests cases: same helpers.)"""
    def test_blocking_leaders_never_reveals_more_than_the_top_three(self):
        from inbox.models import CommunityBlock

        viewer = make_user()
        SetCommunityPortfolioHidden.mutate(None, MockInfo(viewer), hidden=True)
        users = [make_user() for _ in range(6)]
        for i, u in enumerate(users):
            self.snap(u, self.DAY, f'0.0{9 - i}')
        for u in users[:3]:
            CommunityBlock.objects.create(blocker=viewer, blocked=u)
        with patch('teams.league.window', return_value=[self.DAY]):
            result = TeamsQuery().resolve_league_table(MockInfo(viewer), 'investors', '24h')
        self.assertEqual(result.rows, [])

    def test_a_hidden_investor_disappears_from_a_cached_table(self):
        users = [make_user() for _ in range(2)]
        for u in users:
            self.snap(u, self.DAY, '0.01')
        with patch('teams.league.window', return_value=[self.DAY]):
            self.assertEqual(len(league.table('investors', '24h')), 2)
            SetCommunityPortfolioHidden.mutate(None, MockInfo(users[0]), hidden=True)
            self.assertEqual([r.user_id for r in league.table('investors', '24h')], [users[1].id])

    def test_the_goal_is_for_members_only_and_never_with_a_block(self):
        from inbox.models import CommunityBlock

        team, members = self.team_with(3)
        data.set_goal(members[0], team, 'weekly_investors', '3')
        outsider = make_user()
        self.assertIsNone(TeamsQuery().resolve_team(MockInfo(outsider), str(team.id)).goal)
        self.assertIsNotNone(TeamsQuery().resolve_team(MockInfo(members[1]), str(team.id)).goal)
        CommunityBlock.objects.create(blocker=members[1], blocked=members[2])
        self.assertIsNone(TeamsQuery().resolve_team(MockInfo(members[1]), str(team.id)).goal)

    def test_an_amount_goal_needs_three_contributors(self):
        team, members = self.team_with(2)
        data.set_goal(members[0], team, 'invested_usd', '100')
        self.assertIsNone(TeamsQuery().resolve_team(MockInfo(members[1]), str(team.id)).goal)

    def test_archiving_ends_every_membership(self):
        team, members = self.team_with(3)
        rules.archive_team(team.id)
        self.assertFalse(TeamMembership.objects.filter(team=team, left_at__isnull=True).exists())
        self.assertEqual(rules.join_team(members[1], None, self.create(name='Nuevo')[0].id), 'joined')


class GraphQLIdTests(TeamTestBase):
    def test_expel_and_transfer_take_graphql_string_ids(self):
        team, captain = self.create()
        a, b = make_user(), make_user()
        rules.join_team(a, None, team.id)
        rules.join_team(b, None, team.id)
        self.assertTrue(rules.transfer_captain(captain, str(team.id), str(a.id)))
        self.assertTrue(rules.expel(a, str(team.id), str(b.id)))

    def test_a_block_after_requesting_stops_the_approval(self):
        from inbox.models import CommunityBlock

        team, captain = self.create(join_mode='approval')
        member = make_user()
        rules.join_team(member, None, team.id)
        CommunityBlock.objects.create(blocker=member, blocked=captain)
        with self.assertRaises(community.CommunityPostError):
            rules.decide_request(captain, team.join_requests.get().id, True)


class CanonicalWalletTests(LeagueTests):
    def test_the_minimum_is_held_on_the_canonical_wallet(self):
        user = make_user()
        self.snap(user, self.DAY, '0.05', start='5')                   # canonical wallet: $5
        PortfolioDailySnapshot.objects.create(
            user=user, wallet='0xsecond', day=self.DAY, value_start_usd=Decimal('100'),
            value_end_usd=Decimal('100'), net_flow_usd=Decimal('0'), gain_usd=Decimal('0'),
            daily_return=Decimal('0.01'), ledger_trusted=True)
        self.assertEqual(league.investor_table([self.DAY]), [])


class Pass3Tests(LeagueTests):
    def test_a_team_return_from_too_few_members_is_not_shown(self):
        team, members = self.team_with(2)
        TeamDailyReturn.objects.create(team=team, day=self.DAY, daily_return=Decimal('0.1'), qualifying_members=2)
        with patch('teams.league.window', return_value=[self.DAY]):
            self.assertEqual(league.team_return(team.id, '24h')[0], None)

    def test_hiding_after_leaving_still_clears_the_old_team_days(self):
        team, members = self.team_with(3)
        for m in members:
            self.snap(m, self.DAY, '0.03')
        league.compute_team_day(team, self.DAY)
        rules.leave_team(members[2])
        with self.captureOnCommitCallbacks(execute=True), patch('teams.league.utc_today', return_value=self.DAY + timedelta(days=1)):
            SetCommunityPortfolioHidden.mutate(None, MockInfo(members[2]), hidden=True)
        self.assertEqual(TeamDailyReturn.objects.get(team=team, day=self.DAY).qualifying_members, 2)


class ContributorTests(LeagueTests):
    def test_a_blocked_former_contributor_still_hides_the_team_return(self):
        from inbox.models import CommunityBlock

        from .schema import blocked_team

        team, members = self.team_with(4)
        for m in members:
            self.snap(m, self.DAY, '0.02')
        league.compute_team_day(team, self.DAY)
        viewer = make_user()
        CommunityBlock.objects.create(blocker=viewer, blocked=members[3])
        rules.leave_team(members[3])
        with patch('teams.league.window', return_value=[self.DAY]):
            self.assertTrue(blocked_team(viewer, team.id, '24h'))

    def test_a_contributor_who_lost_eligibility_suppresses_the_team(self):
        team, members = self.team_with(3)
        for m in members:
            self.snap(m, self.DAY, '0.02')
        league.compute_team_day(team, self.DAY)
        self.assertTrue(league.contributors_ok(team.id, [self.DAY]))
        from security.models import UserBan

        UserBan.objects.create(user=members[1], reason='fraud', ban_type='permanent')
        self.assertFalse(league.contributors_ok(team.id, [self.DAY]))


class WeeklyCutoffTests(TeamTestBase):
    def test_a_buy_that_settled_before_the_deadline_counts(self):
        from datetime import datetime, timezone as dt_timezone

        from blockchain.models import SponsoredBatch
        from users.models import Account

        team, captain = self.create()
        deadline = date(2026, 10, 21)
        cutoff = datetime(2026, 10, 22, tzinfo=dt_timezone.utc)
        Account.objects.filter(user=captain, account_type='personal').update(bsc_address='0xcap')
        TeamMembership.objects.filter(team=team).update(joined_at=cutoff - timedelta(days=10))
        goal = TeamGoal.objects.create(team=team, kind='weekly_investors', target=Decimal('1'), deadline=deadline,
                                       set_by=captain)
        batch = SponsoredBatch.objects.create(user=captain, user_bsc_address='0xcap', kind='stock_buy', num_calls=1,
                                              calls_json='[]', gas_limit=1, max_fee_wei='1', status='confirmed',
                                              block_number=7)
        SponsoredBatch.objects.filter(id=batch.id).update(created_at=cutoff - timedelta(minutes=5))
        with patch('teams.data._block_time', return_value=cutoff - timedelta(minutes=4)):
            self.assertEqual(data.goal_progress(team, goal, as_of=deadline), Decimal('1'))
        with patch('teams.data._block_time', return_value=cutoff + timedelta(minutes=1)):
            self.assertEqual(data.goal_progress(team, goal, as_of=deadline), Decimal('0'))

    def test_a_buy_crossing_into_monday_counts_for_the_new_week(self):
        from datetime import datetime, timezone as dt_timezone

        from blockchain.models import SponsoredBatch
        from users.models import Account

        team, captain = self.create()
        monday = datetime(2026, 10, 19, tzinfo=dt_timezone.utc)
        Account.objects.filter(user=captain, account_type='personal').update(bsc_address='0xcap')
        TeamMembership.objects.filter(team=team).update(joined_at=monday - timedelta(days=10))
        goal = TeamGoal.objects.create(team=team, kind='weekly_investors', target=Decimal('1'), set_by=captain)
        batch = SponsoredBatch.objects.create(user=captain, user_bsc_address='0xcap', kind='stock_buy', num_calls=1,
                                              calls_json='[]', gas_limit=1, max_fee_wei='1', status='confirmed',
                                              block_number=8)
        SponsoredBatch.objects.filter(id=batch.id).update(created_at=monday - timedelta(seconds=2))
        with patch('teams.data._block_time', return_value=monday + timedelta(seconds=2)):
            self.assertEqual(data.goal_progress(team, goal, as_of=date(2026, 10, 20)), Decimal('1'))


class CoarseGoalTests(TeamTestBase):
    def test_amount_progress_is_coarse(self):
        self.assertEqual([data.coarse_percent(p) for p in (0, 9, 10, 57, 99, 100)], [0, 0, 10, 50, 90, 100])


class TeammateReachTests(TeamTestBase):
    def test_a_teammate_without_posts_can_be_blocked_and_opened(self):
        team, captain = self.create()
        member = make_user()
        rules.join_team(member, None, team.id)
        self.assertIsNotNone(community.followable_member(member.id, viewer=captain))
        community.block_member(captain, member.id)
        self.assertTrue(community.is_blocked_between(captain.id, member.id))


class SweeperTests(TeamTestBase):
    def test_a_banned_teammate_is_found_by_the_removal_sweeper(self):
        from security.models import UserBan

        team, captain = self.create()
        member = make_user()
        rules.join_team(member, None, team.id)
        UserBan.objects.create(user=member, reason='fraud', ban_type='permanent')
        self.assertIn(member.id, dict(community.members_owed_content_removal()))


class InviteTests(TeamTestBase):
    def approval_team(self):
        team, captain = self.create(join_mode='approval')
        return team, captain

    def test_the_captains_link_skips_approval_a_members_link_does_not(self):
        from . import invites

        team, captain = self.approval_team()
        member = make_user()
        rules.join_team(member, None, team.id)  # a request
        rules.decide_request(captain, team.join_requests.get(user=member).id, True)
        member_link = invites.invite_link(member, None, team.id)
        captain_link = invites.invite_link(captain, None, team.id)
        self.assertEqual(rules.join_team(make_user(), None, team.id, invite_token=member_link.token), 'requested')
        self.assertEqual(rules.join_team(make_user(), None, team.id, invite_token=captain_link.token), 'joined')
        # The same link until it nears expiry.
        self.assertEqual(invites.invite_link(captain, None, team.id).token, captain_link.token)

    def test_a_link_still_needs_a_public_verified_profile_and_a_live_inviter(self):
        from . import invites

        team, captain = self.approval_team()
        link = invites.invite_link(captain, None, team.id)
        hidden = make_user()
        SetCommunityPortfolioHidden.mutate(None, MockInfo(hidden), hidden=True)
        with self.assertRaises(community.CommunityPostError):
            rules.join_team(hidden, None, team.id, invite_token=link.token)
        # Expired, or for another team: an ordinary request.
        other, _ = self.create(name='Otro Equipo', join_mode='approval')
        self.assertEqual(rules.join_team(make_user(), None, other.id, invite_token=link.token), 'requested')
        link.expires_at = timezone.now() - timedelta(minutes=1)
        link.save()
        self.assertEqual(rules.join_team(make_user(), None, team.id, invite_token=link.token), 'requested')
        self.assertIsNone(invites.resolve(make_user(), link.token))

    def test_only_members_invite(self):
        from . import invites

        team, _ = self.create()
        with self.assertRaises(community.CommunityPostError) as ctx:
            invites.invite_link(make_user(), None, team.id)
        self.assertEqual(ctx.exception.code, 'not_member')

    def phone_user(self, number):
        from users.models import User
        from users.phone_utils import phone_lookup_key

        user = make_user()
        User.objects.filter(id=user.id).update(phone_key=phone_lookup_key(number))
        return user

    def test_contact_pushes_go_by_phone_and_are_silent_about_who_got_one(self):
        from . import invites
        from .models import TeamInviteNotice

        team, captain = self.create()
        member = self.phone_user('+573001110000')
        rules.join_team(member, None, team.id)
        numbers = ['+573001110001', '+573001110002', '+573001110003']
        for n in numbers:
            self.phone_user(n)
        with patch('inbox.community._notify') as notify:
            # Already in the team, and a number nobody has: tried, not said.
            self.assertEqual(invites.invite_contacts(captain, None, team.id, numbers + ['+573001110000', '+573009999999']), 5)
            self.assertEqual(notify.call_count, 3)
            # Once a week per team per person.
            invites.invite_contacts(captain, None, team.id, [numbers[0]])
            self.assertEqual(notify.call_count, 3)
        # Every attempt counts toward the cap, sent or not.
        self.assertEqual(TeamInviteNotice.objects.filter(inviter=captain).count(), 6)
        with patch.object(invites, 'DAILY_PUSHES', 7), self.assertRaises(community.CommunityPostError) as ctx:
            invites.invite_contacts(captain, None, team.id, ['+573001110004', '+573001110005'])
        self.assertEqual(ctx.exception.code, 'invite_limit')

    def test_blocked_contacts_get_nothing_and_cant_see_the_invite(self):
        from . import invites

        team, captain = self.create()
        friend = self.phone_user('+573001110009')
        community.block_member(friend, captain.id)
        with patch('inbox.community._notify') as notify:
            invites.invite_contacts(captain, None, team.id, ['+573001110009'])
        notify.assert_not_called()
        self.assertIsNone(invites.resolve(friend, invites.invite_link(captain, None, team.id).token))

    def test_tokens_ignore_case(self):
        from . import invites

        team, captain = self.create()
        token = invites.invite_link(captain, None, team.id).token
        self.assertEqual(invites.resolve(make_user(), token.upper()).team_id, team.id)


class AllTimeTests(LeagueTests):
    TODAY = date(2026, 12, 1)

    def setUp(self):
        super().setUp()
        from .tasks import recompute_member_history_task

        eager = patch.object(recompute_member_history_task, 'delay',
                             side_effect=lambda user_id: recompute_member_history_task.run(user_id))
        eager.start()
        self.addCleanup(eager.stop)

    def days_back(self, n):
        return [self.TODAY - timedelta(days=k) for k in range(n, 0, -1)]

    def test_investors_rank_on_their_unbroken_run_from_thirty_days(self):
        steady, newcomer, broken = make_user(), make_user(), make_user()
        for day in self.days_back(40):
            self.snap(steady, day, '0.001')
        for day in self.days_back(20):
            self.snap(newcomer, day, '0.05')                 # lucky, but too new to rank
        for i, day in enumerate(self.days_back(45)):
            # A gap 10 days ago restarts the run: only the last 9 count.
            self.snap(broken, day, '0.002', trusted=(i != 35))
        with patch('teams.league.utc_today', return_value=self.TODAY):
            rows = league.table('investors', 'all')
            self.assertEqual([r.user_id for r in rows], [steady.id])
            self.assertAlmostEqual(float(rows[0].pct), (1.001 ** 40 - 1) * 100, places=4)
            self.assertEqual(league.days_to_rank_all_time('investors', newcomer), 10)
            self.assertEqual(league.days_to_rank_all_time('investors', broken), 21)
            self.assertEqual(league.days_to_rank_all_time('investors', steady), 0)
            # Thirty days and all time never share a cached table.
            self.assertNotEqual(league._key('investors', league.window('30d'), '30d'),
                                league._key('investors', league.window('all'), 'all'))

    def test_teams_need_thirty_shown_days_and_five_members_now(self):
        team, members = self.team_with(5)
        other, _ = self.team_with(5, name='Liga B')
        for i, day in enumerate(self.days_back(35)):
            TeamDailyReturn.objects.create(team=team, day=day, daily_return=Decimal('0.001'), qualifying_members=5,
                                           contributors=[m.id for m in members])
            # Two-member days 20 days ago: the other team's run is too short.
            TeamDailyReturn.objects.create(team=other, day=day, daily_return=Decimal('0.01'),
                                           qualifying_members=2 if i == 15 else 5, contributors=[])
        for m in members:
            for day in self.days_back(35):
                self.snap(m, day, '0.001')
        with patch('teams.league.utc_today', return_value=self.TODAY):
            rows = league.table('teams', 'all')
            self.assertEqual([r.team_id for r in rows], [team.id])
            pct, rank = league.team_return(team.id, 'all')
            self.assertEqual(rank, 1)
            self.assertIsNone(league.team_return(other.id, 'all')[0])

    def test_hiding_recomputes_old_days_they_counted_in(self):
        team, members = self.team_with(5)
        old = self.TODAY - timedelta(days=60)
        TeamMembership.objects.filter(team=team).update(joined_at=timezone.now() - timedelta(days=400))
        for m in members:
            self.snap(m, old, '0.01')
        self.assertTrue(league.compute_team_day(team, old))
        leaver = members[-1]
        self.assertIn(leaver.id, TeamDailyReturn.objects.get(team=team, day=old).contributors)
        with self.captureOnCommitCallbacks(execute=True):
            SetCommunityPortfolioHidden.mutate(None, MockInfo(leaver), hidden=True)
        row = TeamDailyReturn.objects.get(team=team, day=old)
        self.assertNotIn(leaver.id, row.contributors)
        self.assertEqual(row.qualifying_members, 4)

    def test_showing_again_restores_old_days(self):
        team, members = self.team_with(5)
        old = self.TODAY - timedelta(days=60)
        TeamMembership.objects.filter(team=team).update(joined_at=timezone.now() - timedelta(days=400))
        for m in members:
            self.snap(m, old, '0.01')
        league.compute_team_day(team, old)
        leaver = members[-1]
        with self.captureOnCommitCallbacks(execute=True):
            SetCommunityPortfolioHidden.mutate(None, MockInfo(leaver), hidden=True)
        self.assertEqual(TeamDailyReturn.objects.get(team=team, day=old).qualifying_members, 4)
        with self.captureOnCommitCallbacks(execute=True):
            SetCommunityPortfolioHidden.mutate(None, MockInfo(leaver), hidden=False)
        row = TeamDailyReturn.objects.get(team=team, day=old)
        self.assertEqual(row.qualifying_members, 5)
        self.assertIn(leaver.id, row.contributors)

    def test_nightly_repair_recomputes_people_no_longer_shown(self):
        team, members = self.team_with(5)
        old = self.TODAY - timedelta(days=60)
        TeamMembership.objects.filter(team=team).update(joined_at=timezone.now() - timedelta(days=400))
        for m in members:
            self.snap(m, old, '0.01')
        league.compute_team_day(team, old)
        gone = members[-1]
        with patch('teams.league._eligible_user_ids', side_effect=lambda ids: set(ids) - {gone.id}):
            self.assertEqual(league.repair_all_time_people(), 1)
        self.assertNotIn(gone.id, TeamDailyReturn.objects.get(team=team, day=old).contributors)
        # Shown again later: the next repair puts them back.
        self.assertEqual(league.repair_all_time_people(), 1)
        self.assertIn(gone.id, TeamDailyReturn.objects.get(team=team, day=old).contributors)
        from .models import TeamHistoryExclusion
        self.assertFalse(TeamHistoryExclusion.objects.exists())


    def test_any_member_left_out_of_a_day_is_remembered(self):
        from .models import TeamHistoryExclusion

        team, members = self.team_with(5)
        old = self.TODAY - timedelta(days=60)
        TeamMembership.objects.filter(team=team).update(joined_at=timezone.now() - timedelta(days=400))
        for m in members:
            self.snap(m, old, '0.01')
        banned = members[2]
        with patch('teams.league._eligible_user_ids', side_effect=lambda ids: set(ids) - {banned.id}):
            league.compute_team_day(team, old)
        self.assertTrue(TeamHistoryExclusion.objects.filter(user_id=banned.id).exists())
        league.repair_all_time_people()      # eligible again: restored
        self.assertIn(banned.id, TeamDailyReturn.objects.get(team=team, day=old).contributors)
