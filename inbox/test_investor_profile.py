from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from . import community, profile_pictures as pp
from .models import CommunityFollow, CommunityProfileSettings, ProfilePictureSubmission
from .schema import Query, SetCommunityPortfolioHidden, UpdateInvestorBio
from .test_community import APPROVE, REJECT, SOL_APPROVE, UNSURE, MockInfo, make_user


def hide(user, hidden=True):
    return SetCommunityPortfolioHidden.mutate(None, MockInfo(user), hidden=hidden)


def update_bio(user, bio):
    with patch('inbox.schema.get_context_models', return_value=(user, None, None, {})):
        return UpdateInvestorBio.mutate(None, MockInfo(user), bio=bio)


class ProfileTestBase(TestCase):
    """Every member here can be shown (the real rule needs visible Comunidad
    content or a follow of the viewer; see community.followable_member)."""

    def setUp(self):
        visible = patch('inbox.community.has_visible_content', return_value=True)
        visible.start()
        self.addCleanup(visible.stop)


class ReciprocityTests(ProfileTestBase):
    def setUp(self):
        super().setUp()
        self.target, self.viewer = make_user(), make_user()

    def access(self, viewer=None):
        return Query().resolve_investor_profile(MockInfo(viewer or self.viewer), str(self.target.id)).access

    def test_open_between_two_public_verified_members(self):
        self.assertEqual(self.access(), community.ACCESS_OPEN)
        self.assertEqual(self.access(self.target), community.ACCESS_SELF)

    def test_a_hidden_viewer_sees_no_one_elses_investments(self):
        hide(self.viewer)
        self.assertEqual(self.access(), community.ACCESS_VIEWER_HIDDEN)
        self.assertFalse(community.portfolio_visible_to(self.target, self.viewer))
        with patch('inbox.member_portfolio.build_portfolio') as build:
            self.assertIsNone(Query().resolve_community_member_portfolio(MockInfo(self.viewer), str(self.target.id)))
        build.assert_not_called()

    def test_an_unverified_viewer_is_locked(self):
        viewer = make_user(verified=False)
        self.assertEqual(self.access(viewer), community.ACCESS_VIEWER_UNVERIFIED)
        self.assertFalse(community.portfolio_visible_to(self.target, viewer))

    def test_a_hidden_target_says_so_before_the_viewers_own_state(self):
        hide(self.target)
        hide(self.viewer)
        self.assertEqual(self.access(), community.ACCESS_TARGET_HIDDEN)

    def test_returns_follow_the_same_lock(self):
        hide(self.viewer)
        with patch('inbox.portfolio_returns.period_return') as period:
            self.assertIsNone(Query().resolve_investor_returns(MockInfo(self.viewer), str(self.target.id), '7d'))
        period.assert_not_called()


class RepublishLockTests(TestCase):
    def test_hiding_right_after_publishing_is_refused_for_a_day(self):
        user = make_user()
        self.assertTrue(hide(user).success)            # never published: hiding is free
        self.assertTrue(hide(user, False).success)     # publish
        refused = hide(user)
        self.assertFalse(refused.success)
        self.assertFalse(refused.hidden)
        self.assertIn('24 horas', refused.error)
        CommunityProfileSettings.objects.filter(user=user).update(
            portfolio_published_at=timezone.now() - timedelta(hours=25))
        self.assertTrue(hide(user).success)

    def test_setting_the_same_value_is_a_no_op(self):
        user = make_user()
        hide(user, False)
        self.assertTrue(hide(user, False).success)
        self.assertIsNone(CommunityProfileSettings.objects.get(user=user).portfolio_published_at)


class BioTests(ProfileTestBase):
    def save(self, user, bio, *verdicts):
        first, *rest = verdicts or (APPROVE,)
        with patch('inbox.community._first_pass', return_value=first), \
                patch('inbox.community._escalation', side_effect=rest or AssertionError('no escalation')):
            return update_bio(user, bio)

    def bio(self, user):
        return Query().resolve_investor_profile(MockInfo(make_user()), str(user.id)).bio

    def test_an_approved_bio_shows_on_the_profile(self):
        user = make_user()
        result = self.save(user, '  Invierto  en acciones  de EE.UU. a largo plazo ')
        self.assertTrue(result.success)
        self.assertEqual(self.bio(user), 'Invierto en acciones de EE.UU. a largo plazo')

    def test_a_rejected_bio_keeps_the_old_one_and_says_why(self):
        user = make_user()
        self.save(user, 'Largo plazo')
        result = self.save(user, 'Escríbeme al 0414 555 1234', REJECT)
        self.assertEqual((result.success, result.error), (False, 'Quita tu número de teléfono.'))
        self.assertEqual(self.bio(user), 'Largo plazo')

    def test_borderline_bios_escalate(self):
        user = make_user()
        self.assertTrue(self.save(user, 'Opino de cripto', UNSURE, SOL_APPROVE).success)

    def test_links_never_reach_the_reviewer(self):
        with patch('inbox.community._first_pass') as first:
            result = update_bio(make_user(), 'mira www.ejemplo.com')
        self.assertFalse(result.success)
        first.assert_not_called()

    def test_no_verdict_no_change(self):
        user = make_user()
        with patch('inbox.community._first_pass', side_effect=community.ReviewUnavailable('down')):
            result = update_bio(user, 'Hola')
        self.assertEqual((result.success, result.error), (False, community.BIO_FAILED_MESSAGE))
        self.assertEqual(self.bio(user), '')

    def test_rules_not_accepted_says_so(self):
        user = make_user(rules=False)
        result = self.save(user, 'Hola')
        self.assertEqual((result.success, result.rules_required), (False, True))

    def test_too_long_and_unverified_are_refused(self):
        self.assertFalse(self.save(make_user(), 'x' * 141).success)
        self.assertFalse(self.save(make_user(verified=False), 'Hola').success)

    def test_empty_clears_without_review(self):
        user = make_user()
        self.save(user, 'Hola')
        with patch('inbox.community._first_pass') as first:
            self.assertTrue(update_bio(user, '   ').success)
        first.assert_not_called()
        self.assertEqual(self.bio(user), '')

    def test_a_ban_during_review_wins(self):
        from security.models import UserBan

        user = make_user()

        def ban_then_approve(*args, **kwargs):
            UserBan.objects.create(user=user, reason='fraud', ban_type='permanent')
            return APPROVE

        with patch('inbox.community._first_pass', side_effect=ban_then_approve):
            result = update_bio(user, 'Hola')
        self.assertFalse(result.success)
        self.assertFalse(CommunityProfileSettings.objects.filter(user=user).exclude(bio='').exists())

    def test_the_sweeper_finds_a_banned_members_bio(self):
        from security.models import UserBan

        user = make_user()
        self.save(user, 'Hola')
        UserBan.objects.create(user=user, reason='fraud', ban_type='permanent')
        self.assertIn(user.id, dict(community.members_owed_content_removal()))

    def test_moderation_removal_clears_the_bio(self):
        user = make_user()
        self.save(user, 'Hola')
        community.remove_member_content(user.id, category='scam', reason='x')
        self.assertEqual(CommunityProfileSettings.objects.get(user=user).bio, '')


class CoverPictureTests(TestCase):
    def setUp(self):
        enqueue = patch('inbox.profile_pictures.enqueue_picture_review')
        enqueue.start()
        self.addCleanup(enqueue.stop)
        self.user = make_user()
        self.image = community.ReviewImage('image/jpeg', b'jpeg')

    def submit(self, kind, name):
        prefix = pp._pending_prefix(self.user, kind)
        with self.captureOnCommitCallbacks(execute=True):
            return pp.submit_picture(self.user, None, f'{prefix}{name}', kind)

    def approve(self, submission, url):
        with patch('inbox.profile_pictures.community.load_pending_image', return_value=self.image) as load, \
                patch('inbox.profile_pictures.publish_picture', return_value=url), \
                patch('inbox.profile_pictures.community._call_reviewer', return_value=APPROVE) as reviewer:
            pp.run_picture_review(submission.id)
        return load, reviewer

    def test_a_cover_and_an_avatar_live_side_by_side(self):
        self.approve(self.submit(pp.AVATAR, 'a.jpg'), 'https://pics/public/avatar.jpg')
        load, reviewer = self.approve(self.submit(pp.COVER, 'c.jpg'), 'https://pics/public/cover.jpg')
        self.assertEqual(load.call_args.kwargs['size'], pp.COVER_SIZE)
        self.assertIn('COVER', reviewer.call_args.kwargs['policy'])
        self.assertEqual(pp.picture_urls([self.user.id]), {self.user.id: 'https://pics/public/avatar.jpg'})
        self.assertEqual(pp.cover_url(self.user), 'https://pics/public/cover.jpg')

    def test_removing_the_avatar_keeps_the_cover(self):
        self.approve(self.submit(pp.AVATAR, 'a.jpg'), 'https://pics/public/avatar.jpg')
        self.approve(self.submit(pp.COVER, 'c.jpg'), 'https://pics/public/cover.jpg')
        with self.captureOnCommitCallbacks(execute=True), patch('inbox.tasks.delete_profile_picture_public_task'):
            pp.remove_picture(self.user, removed_by=self.user, kind=pp.AVATAR)
        self.assertEqual(pp.picture_urls([self.user.id]), {})
        self.assertEqual(pp.cover_url(self.user), 'https://pics/public/cover.jpg')

    def test_an_avatar_key_from_the_cover_folder_is_refused(self):
        key = f'{pp._pending_prefix(self.user, pp.COVER)}x.jpg'
        with self.assertRaises(community.CommunityPostError):
            pp.submit_picture(self.user, None, key, pp.AVATAR)
        with self.assertRaises(community.CommunityPostError):
            pp.submit_picture(self.user, None, f'pending/{self.user.id}/x.jpg', pp.COVER)

    def test_unknown_kinds_are_refused(self):
        with self.assertRaises(community.CommunityPostError):
            pp.parse_kind('banner')
        self.assertEqual(pp.parse_kind(None), pp.AVATAR)


class MutualFollowersTests(ProfileTestBase):
    def test_people_i_follow_who_also_follow_them(self):
        target, viewer, both, only_target = make_user(), make_user(), make_user(), make_user()
        CommunityFollow.objects.create(follower=viewer, followed=both)
        CommunityFollow.objects.create(follower=both, followed=target)
        CommunityFollow.objects.create(follower=only_target, followed=target)
        profile = Query().resolve_investor_profile(MockInfo(viewer), str(target.id))
        self.assertEqual(profile.mutual_count, 1)
        self.assertEqual([m.user_id for m in profile.mutuals], [str(both.id)])
        self.assertTrue(profile.can_message)     # Mensajes is live
        self.assertFalse(profile.can_tip)        # Propinas not yet

    def test_a_blocked_member_has_no_profile(self):
        target, viewer = make_user(), make_user()
        community.block_member(viewer, target.id)
        self.assertIsNone(Query().resolve_investor_profile(MockInfo(viewer), str(target.id)))
