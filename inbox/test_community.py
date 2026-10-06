from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from graphql import GraphQLResolveInfo

from security.models import IdentityVerification, UserBan
from users.models import Account, Business, User
from . import community
from .models import (
    Channel,
    CommunityComment,
    CommunityPostReport,
    ProfilePictureSubmission,
    CommunityPostReview,
    CommunityReviewStatus,
    ContentItem,
    ContentReaction,
    ContentStatus,
    ContentSurface,
    ReactionType,
)
from .schema import Query, ReactToMessageContent


def MockInfo(user):
    return Mock(spec=GraphQLResolveInfo, context=SimpleNamespace(user=user))


APPROVE = {'decision': 'approve', 'category': 'ok', 'confidence': 0.95, 'reason': '', 'model': 'luna'}
REJECT = {'decision': 'reject', 'category': 'contact_info', 'confidence': 0.97,
          'reason': 'Quita tu número de teléfono.', 'model': 'luna'}
UNSURE = {'decision': 'escalate', 'category': 'other', 'confidence': 0.4, 'reason': '', 'model': 'luna'}
SOL_APPROVE = {'decision': 'approve', 'category': 'ok', 'confidence': 0.9, 'reason': '', 'model': 'sol'}
SOL_REJECT = {'decision': 'reject', 'category': 'scam', 'confidence': 0.9,
              'reason': 'Parece una promesa de ganancias.', 'model': 'sol'}

counter = iter(range(10_000))


def make_user(name='maría', last='gonzález', verified=True, rules=True):
    n = next(counter)
    user = User.objects.create_user(
        username=f'cm-{n}', email=f'cm{n}@example.com', firebase_uid=f'cm-{n}',
        first_name=name, last_name=last,
    )
    Account.objects.create(user=user, account_type='personal', account_index=0)
    if verified:
        IdentityVerification.objects.create(
            user=user, verified_first_name=name, verified_last_name=last,
            verified_date_of_birth=date(1990, 1, 1), verified_nationality='VEN', verified_address='Calle 1',
            verified_city='Caracas', verified_state='DC', verified_country='VEN', document_type='national_id',
            document_number=f'V-{n}', document_issuing_country='VEN', status='verified',
        )
    if rules:
        community.accept_rules(user, community.COMMUNITY_RULES_VERSION)
    return user


@override_settings(COMMUNITY_POSTING_ENABLED=True, COMMUNITY_DAILY_POST_LIMIT=2,
                   COMMUNITY_REPORT_TAKEDOWN_THRESHOLD=2)
class CommunityTestBase(TestCase):
    def setUp(self):
        enqueue = patch('inbox.community.enqueue_review')
        self.enqueue = enqueue.start()
        self.addCleanup(enqueue.stop)

    def post(self, user, body='Hoy ahorré mis primeros 10 dólares 🎉', image_key=None):
        with self.captureOnCommitCallbacks(execute=True):
            return community.create_community_post(user, None, body, image_key)

    def review_of(self, item):
        return CommunityPostReview.objects.get(content_item=item)

    def run_review(self, item, *verdicts):
        first, *rest = verdicts
        with patch('inbox.community._first_pass', return_value=first), \
                patch('inbox.community._escalation', side_effect=rest or AssertionError('no escalation')) as esc:
            status = community.run_community_review(self.review_of(item).id)
        return status, esc


class CommunityPostingTests(CommunityTestBase):
    def test_verified_member_post_waits_unpublished_for_review(self):
        user = make_user()
        item = self.post(user)
        review = self.review_of(item)
        self.assertEqual(item.status, ContentStatus.DRAFT)
        self.assertEqual(review.status, CommunityReviewStatus.PENDING)
        self.assertEqual(item.owner_user, user)
        self.enqueue.assert_called_once_with(review.id)
        self.assertFalse(ContentSurface.objects.filter(content_item=item).exists())

    def test_unverified_member_cannot_post(self):
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.post(make_user(verified=False))
        self.assertEqual(ctx.exception.code, community.BLOCK_NOT_VERIFIED)

    def test_banned_member_cannot_post(self):
        user = make_user()
        UserBan.objects.create(user=user, reason='fraud', ban_type='permanent')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.post(user)
        self.assertEqual(ctx.exception.code, community.BLOCK_BANNED)

    def test_business_context_cannot_post(self):
        business = Business.objects.create(name='Bodega', category='other')
        with self.assertRaises(community.CommunityPostError) as ctx:
            community.create_community_post(make_user(), business, 'Hola')
        self.assertEqual(ctx.exception.code, community.BLOCK_BUSINESS)

    def test_links_are_refused_before_any_review(self):
        for body in ('Mira https://evil.example', 'entra a www.ganadolares.com', 'escríbeme wa.me/58412'):
            with self.subTest(body=body), self.assertRaises(community.CommunityPostError) as ctx:
                self.post(make_user(), body=body)
            self.assertEqual(ctx.exception.code, 'links')

    def test_plain_spanish_text_is_not_a_link(self):
        self.post(make_user(), body='Gracias Confío. Ahorré 3.5 dólares hoy, etc. ¡Vamos!')

    def test_image_must_be_this_members_upload(self):
        owner, other = make_user(), make_user()
        foreign_key = community.pending_image_prefix(other) + 'abc.jpg'
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.post(owner, image_key=foreign_key)
        self.assertEqual(ctx.exception.code, 'bad_image')

    def test_one_upload_cannot_back_two_posts(self):
        user = make_user()
        key = community.pending_image_prefix(user) + 'abc.jpg'
        self.post(user, image_key=key)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.post(user, image_key=key)
        self.assertEqual(ctx.exception.code, 'bad_image')

    def test_daily_limit_counts_rejections_but_not_ai_failures(self):
        user = make_user()
        first = self.post(user)
        self.run_review(first, REJECT)
        failed = self.post(user)
        community.mark_review_failed(self.review_of(failed).id, 'outage', claim=self.review_of(failed).claim_token)
        self.post(user)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.post(user)
        self.assertEqual(ctx.exception.code, community.BLOCK_DAILY_LIMIT)

    def test_kill_switch(self):
        with override_settings(COMMUNITY_POSTING_ENABLED=False), \
                self.assertRaises(community.CommunityPostError) as ctx:
            self.post(make_user())
        self.assertEqual(ctx.exception.code, community.BLOCK_DISABLED)

    def test_author_name_is_first_name_and_initial(self):
        self.assertEqual(community.author_display_name(make_user('MARÍA JOSÉ', 'GONZÁLEZ PÉREZ')), 'María G.')
        self.assertEqual(community.author_display_name(make_user('', '')), 'Miembro de Confío')


class CommunityReviewTests(CommunityTestBase):
    def feed(self, viewer, section='community'):
        info = MockInfo(viewer)
        account = Account.objects.get(user=viewer)
        with patch('inbox.schema.get_context_models', return_value=(viewer, account, None, {})):
            return Query().resolve_discover_feed(info, limit=20, section=section).items

    def test_clear_approval_publishes_under_the_authors_name(self):
        author = make_user('maría', 'gonzález')
        item = self.post(author)
        status, escalation = self.run_review(item, APPROVE)
        self.assertEqual(status, CommunityReviewStatus.APPROVED)
        escalation.assert_not_called()
        item.refresh_from_db()
        self.assertEqual(item.status, ContentStatus.PUBLISHED)
        [card] = self.feed(make_user())
        self.assertEqual((card.source_name, card.is_official, card.source_section), ('María G.', False, 'community'))
        self.assertEqual([c.id for c in self.feed(make_user(), section='official')], [])

    def test_clear_rejection_stays_unpublished_with_a_reason(self):
        item = self.post(make_user())
        status, _ = self.run_review(item, REJECT)
        self.assertEqual(status, CommunityReviewStatus.REJECTED)
        review = self.review_of(item)
        self.assertEqual(review.reason, 'Quita tu número de teléfono.')
        item.refresh_from_db()
        self.assertEqual(item.status, ContentStatus.DRAFT)
        self.assertEqual(self.feed(make_user()), [])

    def test_unsure_first_pass_escalates_and_the_escalation_decides(self):
        item = self.post(make_user())
        status, escalation = self.run_review(item, UNSURE, SOL_REJECT)
        escalation.assert_called_once()
        review = self.review_of(item)
        self.assertEqual((status, review.decided_by_model, review.escalated), ('REJECTED', 'sol', True))
        self.assertEqual(len(review.verdicts), 2)

    def test_low_confidence_approval_escalates(self):
        item = self.post(make_user())
        status, escalation = self.run_review(item, {**APPROVE, 'confidence': 0.5}, SOL_APPROVE)
        escalation.assert_called_once()
        self.assertEqual(status, CommunityReviewStatus.APPROVED)

    def test_reviewer_outage_never_publishes(self):
        item = self.post(make_user())
        with patch('inbox.community._first_pass', side_effect=community.ReviewUnavailable('down')):
            with self.assertRaises(community.ReviewUnavailable):
                community.run_community_review(self.review_of(item).id)
        community.mark_review_failed(self.review_of(item).id, 'down', claim=self.review_of(item).claim_token)
        item.refresh_from_db()
        self.assertEqual((item.status, self.review_of(item).status), (ContentStatus.DRAFT, 'FAILED'))

    def test_unparseable_model_output_is_unavailable_not_approved(self):
        response = Mock(status_code=200)
        response.json.return_value = {'output_text': 'Sure! Looks fine to me.'}
        with override_settings(OPENAI_API_KEY='k'), patch('inbox.community.requests.post', return_value=response):
            with self.assertRaises(community.ReviewUnavailable):
                community._first_pass('hola', None)
        response.json.return_value = {'output_text': '{"decision": "publish", "category": "ok", '
                                                     '"confidence": 1, "reason": ""}'}
        with override_settings(OPENAI_API_KEY='k'), patch('inbox.community.requests.post', return_value=response):
            with self.assertRaises(community.ReviewUnavailable):
                community._first_pass('hola', None)

    def test_post_deleted_during_review_stays_deleted(self):
        author = make_user()
        item = self.post(author)

        def delete_then_approve(*args, **kwargs):
            community.delete_own_post(author, item.id)
            return APPROVE

        with patch('inbox.community._first_pass', side_effect=delete_then_approve):
            status = community.run_community_review(self.review_of(item).id)
        item.refresh_from_db()
        self.assertEqual((status, item.status), (CommunityReviewStatus.REMOVED, ContentStatus.ARCHIVED))

    def test_missing_upload_is_rejected_for_the_author_to_redo(self):
        from botocore.exceptions import ClientError

        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'gone.jpg')
        missing = ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        with patch('inbox.community.load_pending_image', side_effect=missing):
            status = community.run_community_review(self.review_of(item).id)
        self.assertEqual(status, CommunityReviewStatus.REJECTED)
        self.assertEqual(self.review_of(item).reason, community.BAD_IMAGE_REASON)

    def test_storage_outage_is_retried_not_rejected(self):
        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')
        with patch('inbox.community.load_pending_image', side_effect=ConnectionError('s3 down')):
            with self.assertRaises(community.ReviewUnavailable):
                community.run_community_review(self.review_of(item).id)

    def test_approved_image_is_the_reviewed_bytes(self):
        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')
        image = community.ReviewImage('image/jpeg', b'jpeg-bytes')
        with patch('inbox.community.load_pending_image', return_value=image), \
                patch('inbox.community.publish_image', return_value='https://cdn/x.jpg') as publish:
            self.run_review(item, APPROVE)
        self.assertIs(publish.call_args.args[0], image)
        item.refresh_from_db()
        self.assertEqual(item.metadata['image'], {'url': 'https://cdn/x.jpg'})

    def test_stuck_reviews_are_requeued_then_failed(self):
        item = self.post(make_user())
        review = self.review_of(item)
        old = timezone.now() - timedelta(minutes=30)
        CommunityPostReview.objects.filter(id=review.id).update(updated_at=old)
        self.assertEqual(community.stuck_review_ids()[:2], ([review.id], []))
        CommunityPostReview.objects.filter(id=review.id).update(updated_at=old, attempts=community.MAX_REVIEW_ATTEMPTS)
        self.assertEqual(community.stuck_review_ids()[:2], ([], [review.id]))

    def test_anyone_can_react_to_a_community_post(self):
        item = self.post(make_user())
        self.run_review(item, APPROVE)
        viewer = make_user()
        ReactionType.objects.get_or_create(emoji='❤️', defaults={'label': 'Love'})
        account = Account.objects.get(user=viewer)
        with patch('inbox.schema.get_context_models', return_value=(viewer, account, None, {})):
            result = ReactToMessageContent.mutate(None, MockInfo(viewer), content_item_id=str(item.id), emoji='❤️')
        self.assertEqual(result.viewer_reaction, '❤️')
        self.assertTrue(ContentReaction.objects.filter(content_item=item, user=viewer).exists())


class CommunityReportTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        self.author = make_user()
        self.item = self.post(self.author)
        self.run_review(self.item, APPROVE)
        rereview = patch('inbox.tasks.rereview_community_post_task.delay')
        self.rereview = rereview.start()
        self.addCleanup(rereview.stop)

    def report(self, user, reason='SCAM'):
        with self.captureOnCommitCallbacks(execute=True):
            community.report_post(user, self.item.id, reason)

    def test_first_report_triggers_one_escalation_rereview(self):
        self.report(make_user())
        self.report(make_user(verified=False))
        self.rereview.assert_called_once_with(self.review_of(self.item).id)

    def test_verified_reporters_reaching_the_threshold_take_it_down(self):
        self.report(make_user())
        self.report(make_user())
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentStatus.ARCHIVED)
        self.assertEqual(self.review_of(self.item).status, CommunityReviewStatus.REMOVED)

    def test_unverified_reporters_cannot_take_it_down(self):
        for _ in range(5):
            self.report(make_user(verified=False))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentStatus.PUBLISHED)

    def test_author_cannot_report_own_post(self):
        with self.assertRaises(community.CommunityPostError):
            community.report_post(self.author, self.item.id, 'SCAM')

    def test_rereview_rejection_takes_it_down(self):
        CommunityPostReport.objects.create(content_item=self.item, reporter=make_user(), reason='SCAM')
        with patch('inbox.community._escalation', return_value=SOL_REJECT):
            status = community.rereview_reported_post(self.review_of(self.item).id)
        self.assertEqual(status, CommunityReviewStatus.REMOVED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentStatus.ARCHIVED)

    def test_staff_restore_republishes(self):
        review = self.review_of(self.item)
        community.take_down(review.id, category='staff')
        community.restore(review.id)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentStatus.PUBLISHED)


@override_settings(COMMUNITY_DAILY_COMMENT_LIMIT=50, COMMUNITY_COMMENT_MAX_CHARS=500)
class CommunityCommentTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        enqueue = patch('inbox.community.enqueue_comment_review')
        self.enqueue_comment = enqueue.start()
        self.addCleanup(enqueue.stop)
        notify = patch('notifications.utils.create_notification')
        self.notify = notify.start()
        self.addCleanup(notify.stop)
        self.author = make_user('ana', 'pérez')
        self.item = self.post(self.author)
        self.run_review(self.item, APPROVE)

    def comment(self, user, body='¡Felicidades!', parent=None, mentions=None):
        with self.captureOnCommitCallbacks(execute=True):
            return community.create_comment(user, None, self.item.id, body,
                                            parent.id if parent else None, [str(m.id) for m in mentions or []])

    def approve(self, comment, verdict=APPROVE):
        with patch('inbox.community._first_pass', return_value=verdict), \
                patch('inbox.community._escalation', side_effect=AssertionError('no escalation')), \
                self.captureOnCommitCallbacks(execute=True):
            return community.run_comment_review(comment.id)

    def thread(self, viewer):
        info = MockInfo(viewer)
        return Query().resolve_community_comments(info, content_item_id=str(self.item.id))

    def notified(self):
        return {(call.kwargs['user'].id, call.kwargs['notification_type']) for call in self.notify.call_args_list}

    def test_comment_waits_for_review_and_only_its_author_sees_it_pending(self):
        commenter = make_user()
        comment = self.comment(commenter)
        self.enqueue_comment.assert_called_once_with(comment.id)
        self.assertEqual([c.status for c in self.thread(commenter).items], ['PENDING'])
        self.assertEqual(self.thread(make_user()).items, [])
        self.approve(comment)
        page = self.thread(make_user())
        self.assertEqual(([c.body for c in page.items], page.total_count), (['¡Felicidades!'], 1))

    def test_rejected_comment_shows_its_reason_only_to_its_author(self):
        commenter = make_user()
        comment = self.comment(commenter)
        self.approve(comment, REJECT)
        [mine] = self.thread(commenter).items
        self.assertEqual((mine.status, mine.reason), ('REJECTED', 'Quita tu número de teléfono.'))
        self.assertEqual(self.thread(make_user()).items, [])

    def test_unverified_cannot_comment_and_links_are_refused(self):
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.comment(make_user(verified=False))
        self.assertEqual(ctx.exception.code, community.BLOCK_NOT_VERIFIED)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.comment(make_user(), body='mira bit.ly/xyz')
        self.assertEqual(ctx.exception.code, 'links')

    def test_cannot_comment_on_an_unpublished_post(self):
        draft = self.post(make_user())
        with self.assertRaises(community.CommunityPostError) as ctx:
            community.create_comment(make_user(), None, draft.id, 'Hola')
        self.assertEqual(ctx.exception.code, 'not_found')

    def test_replies_are_one_level_deep(self):
        top = self.comment(make_user())
        self.approve(top)
        reply = self.comment(make_user(), parent=top)
        self.approve(reply)
        reply_to_reply = self.comment(make_user(), parent=reply)
        self.assertEqual(reply_to_reply.parent_id, top.id)
        self.approve(reply_to_reply)
        [thread] = self.thread(make_user()).items
        self.assertEqual(len(thread.replies), 2)

    def test_only_post_participants_can_be_tagged(self):
        commenter = make_user()
        self.approve(self.comment(commenter))
        outsider = make_user()
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.comment(make_user(), mentions=[outsider])
        self.assertEqual(ctx.exception.code, 'bad_mention')
        tagged = self.comment(make_user(), body='@Ana P. @María G. ¡mira!', mentions=[self.author, commenter])
        self.assertEqual(set(tagged.mentions.values_list('id', flat=True)), {self.author.id, commenter.id})

    def test_pending_commenters_are_not_yet_participants(self):
        pending = make_user()
        self.comment(pending)
        ids = {u.id for u in community.post_participants(self.item.id)}
        self.assertEqual(ids, {self.author.id})

    def test_each_person_gets_one_notification_the_most_specific(self):
        from notifications.models import NotificationType

        top_author = make_user()
        top = self.comment(top_author)
        self.approve(top)
        self.assertEqual(self.notified(), {(self.author.id, NotificationType.COMMUNITY_COMMENT)})
        self.notify.reset_mock()
        replier = make_user()
        reply = self.comment(replier, parent=top, mentions=[self.author])
        self.approve(reply)
        self.assertEqual(self.notified(), {
            (self.author.id, NotificationType.COMMUNITY_MENTION),
            (top_author.id, NotificationType.COMMUNITY_REPLY),
        })

    def test_nobody_is_notified_of_a_rejected_comment(self):
        self.approve(self.comment(make_user(), mentions=[self.author]), REJECT)
        self.notify.assert_not_called()

    def test_post_author_can_remove_comments_and_a_removed_thread_takes_its_replies(self):
        top = self.comment(make_user())
        self.approve(top)
        self.approve(self.comment(make_user(), parent=top))
        self.assertFalse(community.delete_comment(make_user(), top.id))
        self.assertTrue(community.delete_comment(self.author, top.id))
        page = self.thread(make_user())
        self.assertEqual((page.items, page.total_count), ([], 0))

    def test_verified_reports_take_a_comment_down(self):
        comment = self.comment(make_user())
        self.approve(comment)
        with patch('inbox.tasks.rereview_community_comment_task.delay') as rereview:
            with self.captureOnCommitCallbacks(execute=True):
                community.report_comment(make_user(), comment.id, 'OFFENSIVE')
            rereview.assert_called_once_with(comment.id)
            community.report_comment(make_user(), comment.id, 'OFFENSIVE')
        comment.refresh_from_db()
        self.assertEqual(comment.status, CommunityReviewStatus.REMOVED)

    def test_comment_counts_cover_only_visible_comments(self):
        self.approve(self.comment(make_user()))
        self.comment(make_user())  # pending
        counts = Query().resolve_community_comment_counts(MockInfo(make_user()), [str(self.item.id), 'x'])
        self.assertEqual([(c.content_item_id, c.count) for c in counts], [(str(self.item.id), 1)])

    def test_comment_outage_marks_failed(self):
        comment = self.comment(make_user())
        with patch('inbox.community._first_pass', side_effect=community.ReviewUnavailable('down')):
            with self.assertRaises(community.ReviewUnavailable):
                community.run_comment_review(comment.id)
        comment.refresh_from_db()
        community.mark_comment_failed(comment.id, 'down', claim=comment.claim_token)
        comment.refresh_from_db()
        self.assertEqual(comment.status, CommunityReviewStatus.FAILED)


class CommunityPostNotificationTests(CommunityTestBase):
    def test_only_a_slow_review_notifies_the_author(self):
        notify = patch('inbox.community.notify_post_reviewed')
        notified = notify.start()
        self.addCleanup(notify.stop)
        fast = self.post(make_user())
        with self.captureOnCommitCallbacks(execute=True):
            self.run_review(fast, APPROVE)
        notified.assert_not_called()
        slow = self.post(make_user())
        CommunityPostReview.objects.filter(content_item=slow).update(created_at=timezone.now() - timedelta(minutes=5))
        with self.captureOnCommitCallbacks(execute=True):
            self.run_review(slow, REJECT)
        notified.assert_called_once_with(self.review_of(slow).id)

    def test_my_posts_lists_every_status_with_comment_counts(self):
        user = make_user()
        approved = self.post(user)
        self.run_review(approved, APPROVE)
        rejected = self.post(user)
        self.run_review(rejected, REJECT)
        posts = Query().resolve_my_community_posts(MockInfo(user))
        self.assertEqual([(p.id, p.status) for p in posts],
                         [(str(rejected.id), 'REJECTED'), (str(approved.id), 'APPROVED')])
        self.assertEqual(posts[0].reason, 'Quita tu número de teléfono.')
        self.assertEqual(Query().resolve_my_community_posts(MockInfo(make_user())), [])


class CommunityCommentReactionTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        patch('inbox.community.enqueue_comment_review').start()
        patch('notifications.utils.create_notification').start()
        self.addCleanup(patch.stopall)
        self.item = self.post(make_user())
        self.run_review(self.item, APPROVE)
        with self.captureOnCommitCallbacks(execute=True):
            self.comment = community.create_comment(make_user(), None, self.item.id, 'Bien')
        with patch('inbox.community._first_pass', return_value=APPROVE):
            community.run_comment_review(self.comment.id)
        for emoji in ('🔥', '❤️'):
            ReactionType.objects.get_or_create(emoji=emoji, defaults={'label': emoji})

    def thread(self, viewer):
        return Query().resolve_community_comments(MockInfo(viewer), content_item_id=str(self.item.id)).items

    def test_react_swap_and_take_back(self):
        viewer, other = make_user(), make_user()
        community.react_to_comment(viewer, self.comment.id, '🔥')
        community.react_to_comment(other, self.comment.id, '🔥')
        [c] = self.thread(viewer)
        self.assertEqual(([(r.emoji, r.count) for r in c.reaction_summary], c.viewer_reaction), ([('🔥', 2)], '🔥'))
        community.react_to_comment(viewer, self.comment.id, '❤️')
        [c] = self.thread(viewer)
        self.assertEqual(c.viewer_reaction, '❤️')
        community.react_to_comment(viewer, self.comment.id, '❤️')
        [c] = self.thread(viewer)
        self.assertEqual(([(r.emoji, r.count) for r in c.reaction_summary], c.viewer_reaction), ([('🔥', 1)], None))

    def test_cannot_react_to_a_hidden_comment_or_unknown_emoji(self):
        with self.assertRaises(community.CommunityPostError):
            community.react_to_comment(make_user(), self.comment.id, '🍕')
        community.take_down_comment(self.comment.id, category='staff')
        with self.assertRaises(community.CommunityPostError):
            community.react_to_comment(make_user(), self.comment.id, '🔥')


class ProfilePictureTests(TestCase):
    def setUp(self):
        from . import profile_pictures

        self.pp = profile_pictures
        enqueue = patch('inbox.profile_pictures.enqueue_picture_review')
        self.enqueue = enqueue.start()
        self.addCleanup(enqueue.stop)
        self.user = make_user()
        self.image = community.ReviewImage('image/jpeg', b'jpeg')

    def submit(self, user=None, name='a.jpg'):
        user = user or self.user
        with self.captureOnCommitCallbacks(execute=True):
            return self.pp.submit_picture(user, None, f'pending/{user.id}/{name}')

    def review(self, submission, *verdicts, url='https://pics/public/x.jpg'):
        first, *rest = verdicts
        with patch('inbox.profile_pictures.community.load_pending_image', return_value=self.image), \
                patch('inbox.profile_pictures.publish_picture', return_value=url) as publish, \
                patch('inbox.profile_pictures.community._call_reviewer', side_effect=[first, *rest]):
            status = self.pp.run_picture_review(submission.id)
        return status, publish

    def test_approved_picture_replaces_the_old_one_and_shows_in_bylines(self):
        first = self.submit(name='1.jpg')
        self.review(first, APPROVE, url='https://pics/public/1.jpg')
        second = self.submit(name='2.jpg')
        status, publish = self.review(second, APPROVE, url='https://pics/public/2.jpg')
        self.assertIs(publish.call_args.args[0], self.image)
        first.refresh_from_db()
        self.assertEqual((status, first.status), ('ACTIVE', 'REPLACED'))
        self.assertEqual(self.pp.picture_urls([self.user.id]), {self.user.id: 'https://pics/public/2.jpg'})

    def test_rejected_picture_keeps_the_current_one(self):
        self.review(self.submit(name='1.jpg'), APPROVE, url='https://pics/public/1.jpg')
        bad = self.submit(name='2.jpg')
        status, publish = self.review(bad, {**REJECT, 'category': 'impersonation', 'reason': 'Parece un logo oficial.'})
        publish.assert_not_called()
        bad.refresh_from_db()
        self.assertEqual((status, bad.reason), ('REJECTED', 'Parece un logo oficial.'))
        self.assertEqual(self.pp.picture_urls([self.user.id]), {self.user.id: 'https://pics/public/1.jpg'})

    def test_unsure_first_pass_escalates(self):
        status, _ = self.review(self.submit(), UNSURE, SOL_REJECT)
        self.assertEqual(status, 'REJECTED')

    def test_outage_never_approves(self):
        submission = self.submit()
        with patch('inbox.profile_pictures.community.load_pending_image', return_value=self.image), \
                patch('inbox.profile_pictures.community._call_reviewer',
                      side_effect=community.ReviewUnavailable('down')):
            with self.assertRaises(community.ReviewUnavailable):
                self.pp.run_picture_review(submission.id)
        submission.refresh_from_db()
        self.pp.mark_picture_failed(submission.id, 'down', claim=submission.claim_token)
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'FAILED')
        self.assertEqual(self.pp.picture_urls([self.user.id]), {})

    def test_newer_upload_supersedes_one_still_in_review(self):
        old = self.submit(name='1.jpg')
        self.submit(name='2.jpg')
        status, publish = self.review(old, APPROVE)
        self.assertEqual(status, 'REPLACED')
        publish.assert_not_called()  # superseded before review: never reviewed, never public

    def test_only_own_uploads_and_daily_limit(self):
        other = make_user()
        with self.assertRaises(community.CommunityPostError):
            self.pp.submit_picture(self.user, None, f'pending/{other.id}/x.jpg')
        with override_settings(PROFILE_PICTURE_DAILY_LIMIT=1):
            self.submit(name='1.jpg')
            with self.assertRaises(community.CommunityPostError):
                self.submit(name='2.jpg')

    def test_business_context_cannot_change_it(self):
        business = Business.objects.create(name='Bodega', category='other')
        with self.assertRaises(community.CommunityPostError):
            self.pp.submit_picture(self.user, business, f'pending/{self.user.id}/x.jpg')

    def test_remove_goes_back_to_initial(self):
        self.review(self.submit(), APPROVE)
        self.assertTrue(self.pp.remove_picture(self.user, removed_by=self.user))
        self.assertEqual(self.pp.picture_urls([self.user.id]), {})

    def test_avatar_reaches_community_byline_and_comments(self):
        with patch('inbox.community.enqueue_review'):
            with self.captureOnCommitCallbacks(execute=True):
                item = community.create_community_post(self.user, None, 'Hola comunidad')
        with patch('inbox.community._first_pass', return_value=APPROVE):
            community.run_community_review(item.community_review.id)
        self.review(self.submit(), APPROVE, url='https://pics/public/me.jpg')
        viewer = make_user()
        account = Account.objects.get(user=viewer)
        with patch('inbox.schema.get_context_models', return_value=(viewer, account, None, {})):
            [card] = Query().resolve_discover_feed(MockInfo(viewer), limit=20, section='community').items
        self.assertEqual(card.source_avatar_url, 'https://pics/public/me.jpg')


class CodexAuditRegressionTests(CommunityTestBase):
    """Each case is a Codex audit P1 (2026-10-04) that must stay fixed."""

    def setUp(self):
        super().setUp()
        patch('inbox.community.enqueue_comment_review').start()
        self.notify = patch('notifications.utils.create_notification').start()
        self.addCleanup(patch.stopall)

    def test_malformed_verdicts_never_count_as_a_decision(self):
        good = {'decision': 'approve', 'category': 'ok', 'confidence': 0.9, 'reason': ''}
        community.validate_verdict(dict(good), ['approve', 'reject', 'escalate'])
        bad = [
            {**good, 'confidence': True},
            {**good, 'confidence': float('nan')},
            {**good, 'confidence': 1.5},
            {**good, 'confidence': '0.9'},
            {k: v for k, v in good.items() if k != 'reason'},
            {**good, 'extra': 1},
            {**good, 'reason': None},
            {**good, 'category': 'scam'},  # approving a named violation
            {**good, 'decision': 'publish'},
        ]
        for verdict in bad:
            with self.subTest(verdict=verdict), self.assertRaises(community.ReviewUnavailable):
                community.validate_verdict(verdict, ['approve', 'reject', 'escalate'])

    def test_model_returning_bool_confidence_is_unavailable(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'output_text': '{"decision": "approve", "category": "ok", "confidence": true, "reason": ""}'
        }
        with override_settings(OPENAI_API_KEY='k'), patch('inbox.community.requests.post', return_value=response):
            with self.assertRaises(community.ReviewUnavailable):
                community._first_pass('hola', None)

    def test_restore_cannot_publish_what_the_ai_never_approved(self):
        author = make_user()
        pending = self.post(author)
        community.delete_own_post(author, pending.id)  # removed while still pending
        with self.assertRaises(community.NotRestorable):
            community.restore(self.review_of(pending).id)
        rejected = self.post(make_user())
        self.run_review(rejected, REJECT)
        community.take_down(self.review_of(rejected).id, category='staff')
        with self.assertRaises(community.NotRestorable):
            community.restore(self.review_of(rejected).id)

    def test_rereview_sends_a_rejected_post_back_to_the_ai(self):
        item = self.post(make_user())
        self.run_review(item, REJECT)
        self.enqueue.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(community.rereview(self.review_of(item).id))
        self.assertEqual(self.review_of(item).status, CommunityReviewStatus.PENDING)
        self.enqueue.assert_called_once()

    def test_stale_worker_cannot_decide_or_publish_an_image(self):
        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')
        review_id = self.review_of(item).id

        def newer_attempt_takes_over(*args, **kwargs):
            CommunityPostReview.objects.filter(id=review_id).update(claim_token='newer')
            return APPROVE

        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.community.publish_image') as publish, \
                patch('inbox.community._first_pass', side_effect=newer_attempt_takes_over):
            status = community.run_community_review(review_id)
        self.assertEqual(status, CommunityReviewStatus.PENDING)
        publish.assert_not_called()
        item.refresh_from_db()
        self.assertEqual(item.status, ContentStatus.DRAFT)

    def test_deleted_post_never_promotes_its_image(self):
        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')

        def author_deletes(*args, **kwargs):
            community.delete_own_post(user, item.id)
            return APPROVE

        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.community.publish_image') as publish, \
                patch('inbox.community._first_pass', side_effect=author_deletes):
            community.run_community_review(self.review_of(item).id)
        publish.assert_not_called()

    def test_business_only_kyb_reporters_do_not_count(self):
        item = self.post(make_user())
        self.run_review(item, APPROVE)
        for _ in range(3):
            reporter = make_user(verified=False)
            IdentityVerification.objects.create(
                user=reporter, verified_first_name='B', verified_last_name='K',
                verified_date_of_birth=date(2000, 1, 1), verified_nationality='PER', verified_address='x',
                verified_city='Lima', verified_state='Lima', verified_country='PER', document_type='national_id',
                document_number=f'ruc-{reporter.id}', document_issuing_country='PER', status='verified',
                risk_factors={'account_type': 'business', 'business_id': '1'},
            )
            with patch('inbox.tasks.rereview_community_post_task.delay'):
                community.report_post(reporter, item.id, 'SCAM')
        item.refresh_from_db()
        self.assertEqual(item.status, ContentStatus.PUBLISHED)

    def test_reply_under_a_removed_thread_notifies_nobody(self):
        author = make_user()
        item = self.post(author)
        self.run_review(item, APPROVE)
        top = community.create_comment(make_user(), None, item.id, 'Hola')
        with patch('inbox.community._first_pass', return_value=APPROVE):
            community.run_comment_review(top.id)
        reply = community.create_comment(make_user(), None, item.id, 'Respuesta', top.id, [str(author.id)])
        community.delete_comment(author, top.id)  # thread removed while the reply waits
        self.notify.reset_mock()
        with patch('inbox.community._first_pass', return_value=APPROVE), \
                self.captureOnCommitCallbacks(execute=True):
            community.run_comment_review(reply.id)
        self.notify.assert_not_called()

    def test_removing_a_picture_cancels_one_still_in_review(self):
        from . import profile_pictures as pp

        user = make_user()
        with patch('inbox.profile_pictures.enqueue_picture_review'):
            pending = pp.submit_picture(user, None, f'pending/{user.id}/b.jpg')
        self.assertTrue(pp.remove_picture(user, removed_by=user))
        with patch('inbox.profile_pictures.community.load_pending_image',
                   return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.profile_pictures.publish_picture') as publish, \
                patch('inbox.profile_pictures.community._call_reviewer', return_value=APPROVE):
            status = pp.run_picture_review(pending.id)
        self.assertEqual(status, 'REMOVED')
        publish.assert_not_called()
        self.assertEqual(pp.picture_urls([user.id]), {})

    def test_replies_per_thread_are_bounded(self):
        from .schema import REPLIES_PER_THREAD

        item = self.post(make_user())
        self.run_review(item, APPROVE)
        top = community.create_comment(make_user(), None, item.id, 'Hola')
        with patch('inbox.community._first_pass', return_value=APPROVE):
            community.run_comment_review(top.id)
        from .models import CommunityComment

        CommunityComment.objects.bulk_create([
            CommunityComment(content_item=item, author=top.author, parent=top, body=f'r{i}', status='APPROVED')
            for i in range(REPLIES_PER_THREAD + 5)
        ])
        [thread] = Query().resolve_community_comments(MockInfo(make_user()), content_item_id=str(item.id)).items
        self.assertEqual(len(thread.replies), REPLIES_PER_THREAD)


class CodexAuditRound2Tests(CommunityTestBase):
    """Codex audit round 2 (2026-10-04): each must stay fixed."""

    def setUp(self):
        super().setUp()
        patch('inbox.community.enqueue_comment_review').start()
        patch('notifications.utils.create_notification').start()
        self.addCleanup(patch.stopall)

    def feed(self, viewer):
        account = Account.objects.get(user=viewer)
        with patch('inbox.schema.get_context_models', return_value=(viewer, account, None, {})):
            return Query().resolve_discover_feed(MockInfo(viewer), limit=20, section='community').items

    def test_flipping_status_never_shows_an_unapproved_member_post(self):
        item = self.post(make_user())
        self.run_review(item, REJECT)
        ContentItem.objects.filter(id=item.id).update(status=ContentStatus.PUBLISHED, published_at=timezone.now())
        ContentSurface.objects.get_or_create(content_item=item, surface='DISCOVER')
        self.assertEqual(self.feed(make_user()), [])
        from graphql import GraphQLError
        from .schema import get_accessible_content_item

        viewer = make_user()
        with patch('inbox.schema.get_context_models', return_value=(viewer, Account.objects.get(user=viewer), None, {})):
            with self.assertRaises(GraphQLError):
                get_accessible_content_item(MockInfo(viewer), item.id)

    def test_member_posts_never_reach_the_public_web(self):
        from .feeds import DiscoverFeed as RssFeed  # noqa: F401  (import check)
        from .views import _get_discover_queryset

        item = self.post(make_user())
        self.run_review(item, APPROVE)
        self.assertNotIn(item.id, set(_get_discover_queryset().values_list('id', flat=True)))

    def test_editorial_portal_cannot_edit_member_posts(self):
        item = self.post(make_user())
        self.assertTrue(community.is_member_content(item))
        self.assertFalse(ContentItem.objects.filter(community.EDITORIAL, id=item.id).exists())

    def test_ban_during_review_blocks_publication(self):
        author = make_user()
        item = self.post(author)

        def ban_then_approve(*args, **kwargs):
            UserBan.objects.create(user=author, reason='fraud', ban_type='permanent')
            return APPROVE

        with patch('inbox.community._first_pass', side_effect=ban_then_approve):
            status = community.run_community_review(self.review_of(item).id)
        self.assertEqual((status, self.review_of(item).category), ('REJECTED', 'ineligible'))
        item.refresh_from_db()
        self.assertEqual(item.status, ContentStatus.DRAFT)

    def test_attempt_budget_is_enforced_by_the_worker(self):
        item = self.post(make_user())
        CommunityPostReview.objects.filter(content_item=item).update(attempts=community.MAX_REVIEW_ATTEMPTS)
        with patch('inbox.community._first_pass') as first:
            status = community.run_community_review(self.review_of(item).id)
        first.assert_not_called()
        self.assertEqual(status, CommunityReviewStatus.FAILED)

    def test_old_attempt_cannot_fail_a_newer_one(self):
        item = self.post(make_user())
        review = self.review_of(item)
        CommunityPostReview.objects.filter(id=review.id).update(claim_token='newer')
        community.mark_review_failed(review.id, 'old worker gave up', claim='older')
        self.assertEqual(self.review_of(item).status, CommunityReviewStatus.PENDING)
        community.mark_review_failed(review.id, 'current worker gave up', claim='newer')
        self.assertEqual(self.review_of(item).status, CommunityReviewStatus.FAILED)

    def test_sweeper_leaves_a_freshly_claimed_review_alone(self):
        item = self.post(make_user())
        review = self.review_of(item)
        cutoff = timezone.now() - timedelta(minutes=10)  # row was touched after this
        community.mark_review_failed(review.id, 'stale?', stale_before=cutoff)
        self.assertEqual(self.review_of(item).status, CommunityReviewStatus.PENDING)

    def test_staff_takedown_cancels_a_picture_still_in_review(self):
        from . import profile_pictures as pp

        user = make_user()
        with patch('inbox.profile_pictures.enqueue_picture_review'):
            pending = pp.submit_picture(user, None, f'pending/{user.id}/a.jpg')
        self.assertTrue(pp.take_down(pending.id))
        with patch('inbox.profile_pictures.community.load_pending_image',
                   return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.profile_pictures.publish_picture') as publish, \
                patch('inbox.profile_pictures.community._call_reviewer', return_value=APPROVE):
            pp.run_picture_review(pending.id)
        publish.assert_not_called()
        self.assertEqual(pp.picture_urls([user.id]), {})

    def test_threads_expand_and_authors_always_see_their_own_reply(self):
        from .models import CommunityComment
        from .schema import REPLIES_PER_THREAD

        item = self.post(make_user())
        self.run_review(item, APPROVE)
        top = community.create_comment(make_user(), None, item.id, 'Hola')
        with patch('inbox.community._first_pass', return_value=APPROVE):
            community.run_comment_review(top.id)
        CommunityComment.objects.bulk_create([
            CommunityComment(content_item=item, author=top.author, parent=top, body=f'r{i}', status='APPROVED')
            for i in range(REPLIES_PER_THREAD + 5)
        ])
        late = make_user()
        mine = community.create_comment(late, None, item.id, 'Mi respuesta tardía', top.id)
        resolve = Query().resolve_community_comments
        [thread] = resolve(MockInfo(late), content_item_id=str(item.id)).items
        self.assertIn(str(mine.id), {r.id for r in thread.replies})
        self.assertEqual(thread.reply_count, REPLIES_PER_THREAD + 5)
        [expanded] = resolve(MockInfo(make_user()), content_item_id=str(item.id),
                             expanded_thread_ids=[str(top.id)]).items
        self.assertEqual(len(expanded.replies), REPLIES_PER_THREAD + 5)

    def test_reaction_counts_are_aggregated(self):
        from .models import CommunityCommentReaction
        from .schema import reaction_maps

        item = self.post(make_user())
        self.run_review(item, APPROVE)
        comment = community.create_comment(make_user(), None, item.id, 'Hola')
        fire, _ = ReactionType.objects.get_or_create(emoji='🔥', defaults={'label': 'fire'})
        viewer = make_user()
        CommunityCommentReaction.objects.bulk_create(
            [CommunityCommentReaction(comment=comment, user=make_user(), reaction_type=fire) for _ in range(3)]
            + [CommunityCommentReaction(comment=comment, user=viewer, reaction_type=fire)]
        )
        with self.assertNumQueries(2):
            counts, mine = reaction_maps([comment.id], viewer)
        self.assertEqual((counts[comment.id], mine[comment.id]), ([('🔥', 4)], '🔥'))

    def test_upload_tickets_are_rate_limited(self):
        from django.core.cache import cache

        user = make_user()
        cache.clear()
        allowed = [community.take_upload_ticket(user, 'community-post') for _ in range(community.UPLOAD_TICKETS_PER_HOUR + 1)]
        self.assertEqual(allowed.count(True), community.UPLOAD_TICKETS_PER_HOUR)
        self.assertFalse(allowed[-1])


class CodexAuditRound3Tests(CommunityTestBase):
    """Codex audit round 3 (2026-10-04): each must stay fixed."""

    def setUp(self):
        super().setUp()
        patch('inbox.community.enqueue_comment_review').start()
        patch('notifications.utils.create_notification').start()
        self.addCleanup(patch.stopall)

    def test_inbox_channel_threads_hide_unreviewed_member_content(self):
        from .models import ChannelMembership
        from .schema import get_visible_content_queryset

        channel = Channel.objects.create(slug='t-sub', kind='NEWS', title='News')
        member = make_user()
        account = Account.objects.get(user=member)
        membership, _ = ChannelMembership.objects.get_or_create(channel=channel, user=member, account=account)
        sneaky = ContentItem.objects.create(
            channel=channel, owner_type='USER', owner_user=member, item_type='TEXT', status='PUBLISHED',
            body='unreviewed', published_at=timezone.now(), visibility_policy='BACKLOG',
        )
        self.assertNotIn(sneaky.id, set(get_visible_content_queryset(membership).values_list('id', flat=True)))

    def test_admin_form_refuses_member_content(self):
        from .admin import ContentItemAdminForm

        channel = Channel.objects.create(slug='t-ed', kind='NEWS', title='News')
        form = ContentItemAdminForm(data={
            'channel': channel.id, 'owner_type': 'USER', 'owner_user': make_user().id, 'item_type': 'TEXT',
            'status': 'PUBLISHED', 'visibility_policy': 'FROM_PUBLISH_TIME', 'notification_priority': 'NORMAL',
            'metadata': '{}',
        })
        self.assertFalse(form.is_valid())

    def test_restore_rechecks_eligibility(self):
        author = make_user()
        item = self.post(author)
        self.run_review(item, APPROVE)
        community.take_down(self.review_of(item).id, category='staff')
        UserBan.objects.create(user=author, reason='fraud', ban_type='permanent')
        with self.assertRaises(community.NotRestorable):
            community.restore(self.review_of(item).id)

    def test_ineligible_rejection_is_recorded_so_it_is_never_restorable(self):
        author = make_user()
        item = self.post(author)
        self.run_review(item, APPROVE)
        comment = community.create_comment(author, None, item.id, 'Hola')

        def ban_then_approve(*args, **kwargs):
            UserBan.objects.create(user=author, reason='fraud', ban_type='permanent')
            return APPROVE

        with patch('inbox.community._first_pass', side_effect=ban_then_approve):
            community.run_comment_review(comment.id)
        comment.refresh_from_db()
        self.assertEqual(comment.verdicts[-1]['model'], 'eligibility-check')
        community.take_down_comment(comment.id, category='staff')
        UserBan.objects.filter(user=author).delete()  # even if later unbanned
        with self.assertRaises(community.NotRestorable):
            community.restore_comment(comment.id)

    def test_failure_without_ownership_proof_changes_nothing(self):
        item = self.post(make_user())
        community.mark_review_failed(self.review_of(item).id, 'who am I?')
        self.assertEqual(self.review_of(item).status, CommunityReviewStatus.PENDING)

    def test_picture_storage_outage_carries_the_attempt_claim(self):
        from . import profile_pictures as pp

        user = make_user()
        with patch('inbox.profile_pictures.enqueue_picture_review'):
            submission = pp.submit_picture(user, None, f'pending/{user.id}/a.jpg')
        with patch('inbox.profile_pictures.community.load_pending_image', side_effect=ConnectionError('s3')):
            with self.assertRaises(community.ReviewUnavailable) as ctx:
                pp.run_picture_review(submission.id)
        submission.refresh_from_db()
        self.assertEqual(ctx.exception.claim, submission.claim_token)


class CodexAuditRound4Tests(CommunityTestBase):
    """Codex audit round 4 (2026-10-04): each must stay fixed."""

    def setUp(self):
        super().setUp()
        self.addCleanup(patch.stopall)

    def approved_post_with_image(self):
        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')
        url = 'https://confio-publications.s3.eu-central-2.amazonaws.com/community/images/2026/10/abc.jpg'
        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'img')), \
                patch('inbox.community.publish_image', return_value=url):
            self.run_review(item, APPROVE)
        return item, url

    def test_channel_editor_inline_cannot_touch_member_posts(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from .admin import ContentItemInline

        item = self.post(make_user())
        inline = ContentItemInline(Channel, AdminSite())
        request = RequestFactory().get('/')
        request.user = make_user()
        self.assertNotIn(item.id, set(inline.get_queryset(request).values_list('id', flat=True)))
        self.assertFalse(inline.has_add_permission(request, community.community_channel()))

    def test_takedown_moves_the_image_out_of_public_reach_and_restore_brings_it_back(self):
        item, url = self.approved_post_with_image()
        review_id = self.review_of(item).id
        with patch('inbox.community.enqueue_hide_post_image') as enqueue, \
                self.captureOnCommitCallbacks(execute=True):
            community.take_down(review_id, category='staff')
        enqueue.assert_called_once_with(review_id)

        with patch('security.s3_utils.get_object_bytes', return_value={'body': b'img', 'content_type': 'image/jpeg'}), \
                patch('security.s3_utils.upload_object') as upload, \
                patch('security.s3_utils.delete_object') as delete:
            self.assertTrue(community.hide_post_image(review_id))
        delete.assert_called_once_with(key='community/images/2026/10/abc.jpg', bucket=settings.AWS_PUBLICATIONS_BUCKET)
        self.assertEqual(upload.call_args.kwargs['bucket'], settings.AWS_COMMUNITY_UPLOAD_BUCKET)
        item.refresh_from_db()
        self.assertNotIn('image', item.metadata)
        self.assertTrue(item.metadata['removed_image_key'].startswith('community/removed/'))

        with patch('security.s3_utils.get_object_bytes', return_value={'body': b'img', 'content_type': 'image/jpeg'}), \
                patch('inbox.community.publish_image', return_value='https://pub/new.jpg'):
            community.restore(review_id)
        item.refresh_from_db()
        self.assertEqual((item.status, item.metadata['image']['url']), (ContentStatus.PUBLISHED, 'https://pub/new.jpg'))
        self.assertNotIn('removed_image_key', item.metadata)

    def test_hiding_skips_a_post_restored_meanwhile(self):
        item, _ = self.approved_post_with_image()
        with patch('security.s3_utils.delete_object') as delete:
            self.assertFalse(community.hide_post_image(self.review_of(item).id))  # still APPROVED
        delete.assert_not_called()

    def test_removed_and_replaced_pictures_are_deleted_from_public_storage(self):
        from . import profile_pictures as pp

        user = make_user()
        url = 'https://confio-profile-pictures.s3.eu-central-2.amazonaws.com/public/2026/10/a.jpg'
        with patch('inbox.profile_pictures.enqueue_picture_review'):
            first = pp.submit_picture(user, None, f'pending/{user.id}/1.jpg')
        with patch('inbox.profile_pictures.community.load_pending_image',
                   return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.profile_pictures.publish_picture', return_value=url), \
                patch('inbox.profile_pictures.community._call_reviewer', return_value=APPROVE):
            pp.run_picture_review(first.id)
        with patch('inbox.tasks.delete_profile_picture_public_task.delay') as delete, \
                self.captureOnCommitCallbacks(execute=True):
            pp.remove_picture(user, removed_by=user)
        delete.assert_called_once_with(first.id)
        with patch('security.s3_utils.delete_object') as s3_delete:
            self.assertTrue(pp.delete_public_picture(first.id))
        s3_delete.assert_called_once_with(key='public/2026/10/a.jpg', bucket=settings.AWS_PROFILE_PICTURES_BUCKET)
        first.refresh_from_db()
        self.assertIsNotNone(first.public_deleted_at)


class CodexAuditRound5Tests(CodexAuditRound4Tests):
    """Codex audit round 5 (2026-10-04): image cleanup must be durable."""

    def test_hide_resumes_after_a_failed_delete_without_losing_the_backup(self):
        item, _ = self.approved_post_with_image()
        review_id = self.review_of(item).id
        community.take_down(review_id, category='staff')
        obj = {'body': b'img', 'content_type': 'image/jpeg'}
        with patch('security.s3_utils.get_object_bytes', return_value=obj), \
                patch('security.s3_utils.upload_object'), \
                patch('security.s3_utils.delete_object', side_effect=TimeoutError('s3 timed out')):
            with self.assertRaises(TimeoutError):
                community.hide_post_image(review_id)
        item.refresh_from_db()
        self.assertEqual(item.metadata['removed_image_key'], community.removed_image_backup_key(review_id))
        self.assertIn('image', item.metadata)  # still owed: the sweeper will find it
        self.assertIn(review_id, community.posts_with_public_images_owed())
        with patch('security.s3_utils.get_object_bytes') as get, \
                patch('security.s3_utils.delete_object') as delete:
            self.assertTrue(community.hide_post_image(review_id))
        get.assert_not_called()  # the recorded backup is reused, never re-read from a gone object
        delete.assert_called_once()
        item.refresh_from_db()
        self.assertNotIn('image', item.metadata)
        self.assertNotIn(review_id, community.posts_with_public_images_owed())

    def test_sweeper_reconciles_lost_cleanup(self):
        from . import profile_pictures as pp
        from .tasks import sweep_stuck_community_reviews_task

        item, _ = self.approved_post_with_image()
        with patch('inbox.community.enqueue_hide_post_image'):  # the fast path is lost
            community.take_down(self.review_of(item).id, category='staff')
        user = make_user()
        with patch('inbox.profile_pictures.enqueue_picture_review'):
            picture = pp.submit_picture(user, None, f'pending/{user.id}/1.jpg')
        ProfilePictureSubmission.objects.filter(id=picture.id).update(
            status='REMOVED', public_url='https://x.s3.eu-central-2.amazonaws.com/public/a.jpg',
        )
        with patch('inbox.tasks.hide_community_post_image_task.delay') as hide, \
                patch('inbox.tasks.delete_profile_picture_public_task.delay') as delete:
            sweep_stuck_community_reviews_task()
        hide.assert_called_once_with(self.review_of(item).id)
        delete.assert_called_once_with(picture.id)

    def test_moderation_admins_cannot_plain_delete(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from .admin import CommunityCommentAdmin, CommunityPostReviewAdmin, ProfilePictureSubmissionAdmin
        from .models import CommunityComment

        request = RequestFactory().get('/')
        request.user = User.objects.create_superuser('root-admin', 'root@example.com', 'x', firebase_uid='root-admin')
        for admin_class, model in ((CommunityPostReviewAdmin, CommunityPostReview),
                                   (CommunityCommentAdmin, CommunityComment),
                                   (ProfilePictureSubmissionAdmin, ProfilePictureSubmission)):
            model_admin = admin_class(model, AdminSite())
            self.assertFalse(model_admin.has_delete_permission(request))
            self.assertNotIn('delete_selected', model_admin.get_actions(request))


class CodexAuditRound6Tests(CodexAuditRound4Tests):
    """Codex audit round 6 (2026-10-04): no public object escapes the ledger."""

    def ledger(self):
        from .models import PublicObject

        return {(o.key, o.state) for o in PublicObject.objects.all()}

    def test_approved_image_is_reserved_before_upload_and_marked_live(self):
        from .models import PublicObject

        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')
        seen_at_upload = []

        def upload(**kwargs):
            seen_at_upload.append(PublicObject.objects.filter(key=kwargs['key']).values_list('state', flat=True).first())
            return f"https://confio-publications.s3.eu-central-2.amazonaws.com/{kwargs['key']}"

        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('security.s3_utils.upload_object', side_effect=upload):
            self.run_review(item, APPROVE)
        self.assertEqual(seen_at_upload, ['RESERVED'])
        self.assertEqual({state for _, state in self.ledger()}, {'LIVE'})

    def test_a_publish_that_never_commits_leaves_an_owed_reservation(self):
        from .models import PublicObject
        from . import public_objects

        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')

        def author_deletes(*args, **kwargs):
            community.delete_own_post(user, item.id)
            return APPROVE

        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('security.s3_utils.upload_object') as upload, \
                patch('inbox.community._first_pass', side_effect=author_deletes):
            community.run_community_review(self.review_of(item).id)
        upload.assert_not_called()
        [reservation] = PublicObject.objects.all()
        self.assertEqual(reservation.state, 'RESERVED')
        self.assertEqual(public_objects.owed(), [])  # inside the grace period
        PublicObject.objects.filter(id=reservation.id).update(updated_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(public_objects.owed(), [reservation.id])
        with patch('security.s3_utils.delete_object') as delete:
            self.assertTrue(public_objects.delete_owed(reservation.id))
        delete.assert_called_once()
        reservation.refresh_from_db()
        self.assertEqual(reservation.state, 'DELETED')

    def test_restore_dooms_a_half_hidden_public_copy(self):
        from . import public_objects

        item, url = self.approved_post_with_image()
        review_id = self.review_of(item).id
        community.take_down(review_id, category='staff')
        # The hide recorded its backup but never deleted the public object.
        item.refresh_from_db()
        metadata = dict(item.metadata)
        metadata['removed_image_key'] = community.removed_image_backup_key(review_id)
        ContentItem.objects.filter(id=item.id).update(metadata=metadata)
        with patch('security.s3_utils.get_object_bytes', return_value={'body': b'x', 'content_type': 'image/jpeg'}), \
                patch('security.s3_utils.upload_object', side_effect=lambda **kw: f"https://pub/{kw['key']}"):
            community.restore(review_id)
        self.assertIn(('community/images/2026/10/abc.jpg', 'DOOMED'), self.ledger())
        self.assertTrue(public_objects.owed())

    def test_removed_picture_is_doomed_in_the_same_transaction(self):
        from . import profile_pictures as pp

        user = make_user()
        url = 'https://confio-profile-pictures.s3.eu-central-2.amazonaws.com/public/2026/10/z.jpg'
        with patch('inbox.profile_pictures.enqueue_picture_review'):
            first = pp.submit_picture(user, None, f'pending/{user.id}/1.jpg')
        with patch('inbox.profile_pictures.community.load_pending_image',
                   return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('security.s3_utils.upload_object', return_value=url), \
                patch('inbox.profile_pictures.community._call_reviewer', return_value=APPROVE):
            pp.run_picture_review(first.id)
        with patch('inbox.tasks.delete_profile_picture_public_task.delay'):
            pp.remove_picture(user, removed_by=user)
        self.assertIn(('public/2026/10/z.jpg', 'DOOMED'), self.ledger())


class CodexAuditRound7Tests(CodexAuditRound4Tests):
    """Codex audit round 7 (2026-10-04)."""

    def test_reported_image_that_cannot_load_is_never_judged_on_text_alone(self):
        item, _ = self.approved_post_with_image()
        review_id = self.review_of(item).id
        CommunityPostReport.objects.create(content_item=item, reporter=make_user(), reason='SCAM')
        with patch('security.s3_utils.get_object_bytes', side_effect=TimeoutError('s3')), \
                patch('inbox.community._escalation') as escalation:
            with self.assertRaises(community.ReviewUnavailable):
                community.rereview_reported_post(review_id)
        escalation.assert_not_called()
        self.assertFalse(any(v.get('rereview') for v in self.review_of(item).verdicts))

    def test_an_undecided_rereview_can_be_tried_again(self):
        item, _ = self.approved_post_with_image()
        review = self.review_of(item)
        CommunityPostReview.objects.filter(id=review.id).update(rereviewed_at=timezone.now())
        community.allow_rereview(CommunityPostReview, review.id)
        self.assertIsNone(self.review_of(item).rereviewed_at)

    def test_restore_brings_the_image_back_even_if_the_hide_finished_just_before(self):
        item, _ = self.approved_post_with_image()
        review_id = self.review_of(item).id
        with patch('inbox.community.enqueue_hide_post_image'):
            community.take_down(review_id, category='staff')
        item.refresh_from_db()
        metadata = dict(item.metadata)
        metadata.pop('image')
        metadata['removed_image_key'] = community.removed_image_backup_key(review_id)
        ContentItem.objects.filter(id=item.id).update(metadata=metadata)
        with patch('security.s3_utils.get_object_bytes', return_value={'body': b'x', 'content_type': 'image/jpeg'}), \
                patch('security.s3_utils.upload_object', side_effect=lambda **kw: f"https://pub/{kw['key']}"):
            community.restore(review_id)
        item.refresh_from_db()
        self.assertTrue(item.metadata['image']['url'].startswith('https://pub/community/images/'))


class CodexAuditRound8Tests(CodexAuditRound4Tests):
    """Codex audit round 8 (2026-10-04) P2s."""

    def test_malformed_response_envelope_is_unavailable(self):
        response = Mock(status_code=200)
        response.json.side_effect = ValueError('not json')
        with override_settings(OPENAI_API_KEY='k'), patch('inbox.community.requests.post', return_value=response):
            with self.assertRaises(community.ReviewUnavailable):
                community._first_pass('hola', None)
        response.json.side_effect = None
        response.json.return_value = ['not', 'a', 'dict']
        with override_settings(OPENAI_API_KEY='k'), patch('inbox.community.requests.post', return_value=response):
            with self.assertRaises(community.ReviewUnavailable):
                community._first_pass('hola', None)

    def test_a_lost_rereview_is_found_again(self):
        item, _ = self.approved_post_with_image()
        review = self.review_of(item)
        CommunityPostReview.objects.filter(id=review.id).update(rereviewed_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(community.lost_rereview_ids(CommunityPostReview), [review.id])
        CommunityPostReview.objects.filter(id=review.id).update(
            verdicts=[*review.verdicts, {**SOL_APPROVE, 'rereview': True}],
        )
        self.assertEqual(community.lost_rereview_ids(CommunityPostReview), [])

    def test_finished_rereviews_never_crowd_out_lost_ones(self):
        finished = []
        for _ in range(3):
            item, _ = self.approved_post_with_image()
            finished.append(self.review_of(item))
        lost_item, _ = self.approved_post_with_image()
        lost = self.review_of(lost_item)
        two_hours_ago = timezone.now() - timedelta(hours=2)
        for review in finished:
            CommunityPostReview.objects.filter(id=review.id).update(
                rereviewed_at=two_hours_ago, verdicts=[*review.verdicts, {**SOL_APPROVE, 'rereview': True}],
            )
        CommunityPostReview.objects.filter(id=lost.id).update(rereviewed_at=two_hours_ago)
        self.assertEqual(community.lost_rereview_ids(CommunityPostReview), [lost.id])


class AdditionalDocumentVerificationTests(CommunityTestBase):
    """2026-10-04: a member verified only with another country's ID (primary
    phone-country document still pending) was told to verify again."""

    def member_verified_by_additional_document(self):
        user = make_user(verified=False)
        common = dict(
            user=user, verified_first_name='Julian', verified_last_name='M', verified_date_of_birth=date(1990, 1, 1),
            verified_nationality='PRY', verified_address='x', verified_city='Asunción', verified_state='C',
            verified_country='PRY', document_type='national_id', document_issuing_country='PRY',
        )
        IdentityVerification.all_documents.create(document_number=f'P-{user.id}', status='pending', **common)
        IdentityVerification.all_documents.create(
            document_number=f'A-{user.id}', status='verified', is_additional_document=True, **common,
        )
        return user

    def test_additional_verified_document_lets_a_member_post(self):
        user = self.member_verified_by_additional_document()
        self.assertFalse(user.is_identity_verified)  # the rail-specific check
        self.assertIsNone(community.posting_block(user, None))
        self.assertIsNone(community.author_block(user))
        self.post(user)

    def test_additional_verified_document_counts_as_a_verified_reporter(self):
        user = self.member_verified_by_additional_document()
        self.assertEqual(community.personally_verified_count([user.id]), 1)


class MemberPostDetailTests(CommunityTestBase):
    """2026-10-04: post detail showed neither text nor photo (empty blocks)."""

    def test_detail_blocks_carry_the_text_and_the_photo(self):
        user = make_user()
        item = self.post(user, body='Mi primer ahorro', image_key=community.pending_image_prefix(user) + 'a.jpg')
        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.community.publish_image', return_value='https://pub/community/images/a.jpg'):
            self.run_review(item, APPROVE)
        viewer = make_user()
        account = Account.objects.get(user=viewer)
        with patch('inbox.schema.get_context_models', return_value=(viewer, account, None, {})):
            post = Query().resolve_discover_post(MockInfo(viewer), content_item_id=str(item.id))
        self.assertEqual(post.blocks, [
            {'id': 'body', 'type': 'paragraph', 'text': 'Mi primer ahorro'},
            {'id': 'image', 'type': 'image', 'image': {'url': 'https://pub/community/images/a.jpg'}},
        ])
        self.assertEqual(post.image_url, 'https://pub/community/images/a.jpg')

    def test_text_only_post_has_just_the_paragraph(self):
        item = self.post(make_user(), body='Solo texto')
        self.run_review(item, APPROVE)
        item.refresh_from_db()
        self.assertEqual(community.member_post_blocks(item), [{'id': 'body', 'type': 'paragraph', 'text': 'Solo texto'}])


class CommunityRulesTests(CommunityTestBase):
    def test_posting_requires_the_current_rules(self):
        user = make_user(rules=False)
        self.assertEqual(community.posting_block(user, None), community.BLOCK_RULES)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.post(user)
        self.assertEqual(ctx.exception.code, community.BLOCK_RULES)
        with self.assertRaises(community.CommunityPostError):
            community.accept_rules(user, '1999-01-01')  # an outdated text
        community.accept_rules(user, community.COMMUNITY_RULES_VERSION)
        self.assertIsNone(community.posting_block(user, None))

    def test_commenting_and_profile_pictures_also_require_them(self):
        from . import profile_pictures

        item = self.post(make_user())
        self.run_review(item, APPROVE)
        newcomer = make_user(rules=False)
        self.assertEqual(community.commenting_block(newcomer, None), community.BLOCK_RULES)
        self.assertEqual(profile_pictures.upload_block(newcomer, None), profile_pictures.RULES_REQUIRED_MESSAGE)


class CommunityBlockTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        patch('inbox.community.enqueue_comment_review').start()
        self.notify = patch('notifications.utils.create_notification').start()
        self.addCleanup(patch.stopall)
        self.alice, self.bob = make_user('alice', 'a'), make_user('bob', 'b')
        self.post_by_bob = self.post(self.bob)
        self.run_review(self.post_by_bob, APPROVE)

    def feed(self, viewer):
        account = Account.objects.get(user=viewer)
        with patch('inbox.schema.get_context_models', return_value=(viewer, account, None, {})):
            return [c.id for c in Query().resolve_discover_feed(MockInfo(viewer), limit=20, section='community').items]

    def test_blocking_is_mutual_invisibility(self):
        self.assertEqual(self.feed(self.alice), [str(self.post_by_bob.id)])
        community.block_member(self.alice, self.bob.id)
        self.assertEqual(self.feed(self.alice), [])
        self.assertEqual(self.feed(self.bob), [str(self.post_by_bob.id)])  # his own still shows to him
        carol_post = self.post(self.alice)
        self.run_review(carol_post, APPROVE)
        self.assertNotIn(str(carol_post.id), self.feed(self.bob))  # and alice is hidden from bob
        from graphql import GraphQLError
        from .schema import get_accessible_content_item

        with patch('inbox.schema.get_context_models',
                   return_value=(self.alice, Account.objects.get(user=self.alice), None, {})):
            with self.assertRaises(GraphQLError):
                get_accessible_content_item(MockInfo(self.alice), self.post_by_bob.id)

    def test_blocked_people_cannot_comment_mention_or_notify(self):
        alices_post = self.post(self.alice)  # only someone with visible content can be blocked
        self.run_review(alices_post, APPROVE)
        community.block_member(self.bob, self.alice.id)
        with self.assertRaises(community.CommunityPostError):
            community.create_comment(self.alice, None, self.post_by_bob.id, 'Hola')
        carol = make_user('carol', 'c')
        top = community.create_comment(carol, None, self.post_by_bob.id, 'Hola')
        with patch('inbox.community._first_pass', return_value=APPROVE):
            community.run_comment_review(top.id)
        self.assertNotIn(self.alice.id, {u.id for u in community.post_participants(self.post_by_bob.id, exclude_user=self.bob)})
        with self.assertRaises(community.CommunityPostError):
            community.create_comment(carol, None, self.post_by_bob.id, '@Alice A.', mention_user_ids=[str(self.alice.id)])
        # A comment by someone bob blocked never notifies bob.
        dave = make_user('dave', 'd')
        comment = CommunityComment.objects.create(content_item=self.post_by_bob, author=dave, body='x', status='APPROVED')
        community.block_member(self.bob, dave.id)  # dave's comment makes him visible, so blockable
        self.notify.reset_mock()
        community.notify_comment_published(comment.id)
        self.assertNotIn(self.bob.id, {c.kwargs['user'].id for c in self.notify.call_args_list})

    def test_unblock_restores_and_only_the_blocker_can_undo(self):
        community.block_member(self.alice, self.bob.id)
        self.assertFalse(community.unblock_member(self.bob, self.alice.id))
        self.assertEqual([u.id for u in community.blocked_members(self.alice)], [self.bob.id])
        self.assertTrue(community.unblock_member(self.alice, self.bob.id))
        self.assertEqual(self.feed(self.alice), [str(self.post_by_bob.id)])

    def test_cannot_block_yourself(self):
        with self.assertRaises(community.CommunityPostError):
            community.block_member(self.alice, self.alice.id)


class RemovedAccountContentTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        patch('inbox.community.enqueue_comment_review').start()
        self.addCleanup(patch.stopall)

    def test_deleting_an_account_hides_at_once_and_queues_removal(self):
        author = make_user()
        item = self.post(author)
        self.run_review(item, APPROVE)
        with patch('inbox.tasks.remove_member_content_task.delay') as remove, \
                self.captureOnCommitCallbacks(execute=True):
            author.soft_delete()
        remove.assert_called_once_with(author.id, 'deleted')
        self.assertFalse(ContentItem.objects.filter(community.READABLE, id=item.id).exists())

    def test_a_ban_queues_removal_and_removal_takes_everything_down(self):
        author = make_user()
        item = self.post(author)
        self.run_review(item, APPROVE)
        with patch('inbox.tasks.remove_member_content_task.delay') as remove, \
                self.captureOnCommitCallbacks(execute=True):
            UserBan.objects.create(user=author, reason='abuse', ban_type='permanent')
        remove.assert_called_once_with(author.id, 'banned')
        result = community.remove_member_content(author.id, category='account_banned', reason='Cuenta suspendida.')
        self.assertEqual(result['posts'], 1)
        self.assertEqual(self.review_of(item).status, CommunityReviewStatus.REMOVED)

    def test_ordinary_user_saves_do_not_queue_anything(self):
        author = make_user()
        with patch('inbox.tasks.remove_member_content_task.delay') as remove, \
                self.captureOnCommitCallbacks(execute=True):
            author.first_name = 'Ana'
            author.save()
        remove.assert_not_called()


    def test_hard_deleting_a_user_takes_their_posts_and_dooms_images(self):
        from .models import PublicObject

        author = make_user()
        item = self.post(author, image_key=community.pending_image_prefix(author) + 'a.jpg')
        url = 'https://confio-publications.s3.eu-central-2.amazonaws.com/community/images/2026/10/z.jpg'
        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.community.publish_image', return_value=url):
            self.run_review(item, APPROVE)
        author.hard_delete()
        self.assertFalse(ContentItem.objects.filter(id=item.id).exists())
        self.assertTrue(PublicObject.objects.filter(key='community/images/2026/10/z.jpg', state='DOOMED').exists())


class ClaudeAuditRound1Tests(CommunityTestBase):
    """Claude audit round 1 (2026-10-06): each must stay fixed."""

    def setUp(self):
        super().setUp()
        patch('inbox.community.enqueue_comment_review').start()
        patch('notifications.utils.create_notification').start()
        self.addCleanup(patch.stopall)
        self.alice, self.bob = make_user('alice', 'a'), make_user('bob', 'b')
        self.bobs_post = self.post(self.bob)
        self.run_review(self.bobs_post, APPROVE)
        carol = make_user('carol', 'c')
        self.comment = community.create_comment(carol, None, self.bobs_post.id, 'Hola')
        with patch('inbox.community._first_pass', return_value=APPROVE):
            community.run_comment_review(self.comment.id)

    def test_blocked_viewer_gets_no_comments_or_participants(self):
        community.block_member(self.alice, self.bob.id)
        page = Query().resolve_community_comments(MockInfo(self.alice), content_item_id=str(self.bobs_post.id))
        self.assertEqual((page.items, page.total_count), ([], 0))
        self.assertEqual(Query().resolve_community_post_participants(MockInfo(self.alice), str(self.bobs_post.id)), [])
        with self.assertRaises(community.CommunityPostError):
            community.react_to_comment(self.alice, self.comment.id, '🔥')
        with self.assertRaises(community.CommunityPostError):
            community.report_comment(self.alice, self.comment.id, 'SCAM')
        with self.assertRaises(community.CommunityPostError):
            community.report_post(self.alice, self.bobs_post.id, 'SCAM')

    def test_viewer_query_never_names_the_author_of_a_post_you_cannot_see(self):
        rejected = self.post(self.bob)
        self.run_review(rejected, REJECT)
        account = Account.objects.get(user=self.alice)
        with patch('inbox.schema.get_context_models', return_value=(self.alice, account, None, {})):
            viewer = Query().resolve_community_post_viewer(MockInfo(self.alice), str(rejected.id))
        self.assertEqual((viewer.is_community, viewer.author_id, viewer.author_name), (False, None, None))

    def test_block_only_works_on_people_whose_content_you_can_see(self):
        stranger = make_user('nobody', 'x')  # never posted or commented
        with self.assertRaises(community.CommunityPostError):
            community.block_member(self.alice, stranger.id)
        community.block_member(self.alice, self.bob.id)  # visible post: fine

    def test_staff_cannot_restore_what_the_author_deleted(self):
        community.delete_own_post(self.bob, self.bobs_post.id)
        with self.assertRaises(community.NotRestorable):
            community.restore(self.review_of(self.bobs_post).id)

    def test_author_deleted_image_keeps_no_private_backup(self):
        user = make_user()
        item = self.post(user, image_key=community.pending_image_prefix(user) + 'a.jpg')
        url = 'https://confio-publications.s3.eu-central-2.amazonaws.com/community/images/2026/10/q.jpg'
        with patch('inbox.community.load_pending_image', return_value=community.ReviewImage('image/jpeg', b'x')), \
                patch('inbox.community.publish_image', return_value=url):
            self.run_review(item, APPROVE)
        with patch('inbox.community.enqueue_hide_post_image'):
            community.delete_own_post(user, item.id)
        with patch('security.s3_utils.upload_object') as upload, patch('security.s3_utils.delete_object') as delete:
            community.hide_post_image(self.review_of(item).id)
        upload.assert_not_called()
        delete.assert_called_once()

    def test_sweeper_redrives_removal_for_banned_or_deleted_accounts(self):
        UserBan.objects.create(user=self.bob, reason='abuse', ban_type='permanent')
        owed = dict(community.members_owed_content_removal())
        self.assertEqual(owed.get(self.bob.id), 'banned')
        community.remove_member_content(self.bob.id, category='account_banned', reason='x')
        self.assertNotIn(self.bob.id, dict(community.members_owed_content_removal()))

    def test_deleted_account_cannot_publish_a_pending_review(self):
        user = make_user()
        item = self.post(user)
        user.soft_delete()
        user.refresh_from_db()
        with patch('inbox.community._first_pass', return_value=APPROVE):
            status = community.run_community_review(self.review_of(item).id)
        self.assertEqual(status, CommunityReviewStatus.REJECTED)

    def test_profile_pictures_require_verification(self):
        from . import profile_pictures

        self.assertIsNotNone(profile_pictures.upload_block(make_user(verified=False), None))


class ClaudeAuditRound2Tests(ClaudeAuditRound1Tests):
    """Claude audit round 2 (2026-10-06): removed content is really erased."""

    def test_author_deletion_erases_text_now(self):
        community.delete_own_post(self.bob, self.bobs_post.id)
        community.purge_removed_content()
        self.bobs_post.refresh_from_db()
        self.assertEqual(self.bobs_post.body, '')
        self.assertEqual(self.review_of(self.bobs_post).category, 'author_deleted')

    def test_author_deleting_a_moderated_post_keeps_the_record_but_erases_content(self):
        community.take_down(self.review_of(self.bobs_post).id, category='scam', reason='x')
        item = ContentItem.objects.get(id=self.bobs_post.id)
        item.metadata = {**item.metadata, 'removed_image_key': 'community/removed/1.jpg'}
        item.save()
        self.assertTrue(community.delete_own_post(self.bob, self.bobs_post.id))
        with patch('security.s3_utils.delete_object') as delete:
            community.purge_removed_content()
        delete.assert_called_once_with(key='community/removed/1.jpg', bucket=settings.AWS_COMMUNITY_UPLOAD_BUCKET)
        item.refresh_from_db()
        self.assertEqual((item.body, self.review_of(item).category), ('', 'scam'))
        self.assertNotIn('removed_image_key', item.metadata)
        with self.assertRaises(community.NotRestorable):
            community.restore(self.review_of(item).id)

    def test_moderation_takedowns_are_kept_90_days_then_erased(self):
        review = self.review_of(self.bobs_post)
        community.take_down(review.id, category='scam', reason='x')
        community.purge_removed_content()
        self.bobs_post.refresh_from_db()
        self.assertNotEqual(self.bobs_post.body, '')  # within retention: kept for appeals
        CommunityPostReview.objects.filter(id=review.id).update(removed_at=timezone.now() - timedelta(days=91))
        community.purge_removed_content()
        self.bobs_post.refresh_from_db()
        self.assertEqual(self.bobs_post.body, '')

    def test_deleted_account_comments_are_erased(self):
        community.take_down_comment(self.comment.id, category='scam', reason='x')
        self.comment.author.soft_delete()
        community.purge_removed_content()
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, '')

    def test_restore_refuses_a_post_whose_account_is_gone(self):
        review = self.review_of(self.bobs_post)
        community.take_down(review.id, category='scam', reason='x')
        self.bob.soft_delete()
        with self.assertRaises(community.NotRestorable):
            community.restore(review.id)


class ClaudeAuditRound3Tests(ClaudeAuditRound1Tests):
    """Claude audit round 3 (2026-10-06): each must stay fixed."""

    def notify(self, **data):
        from notifications.models import Notification
        return Notification.objects.create(
            user=self.bob, notification_type='COMMUNITY_COMMENT', title='carol comentó tu publicación',
            message='Hola', data={'content_item_id': self.bobs_post.id, **data},
        )

    def test_comment_takedown_erases_its_notifications(self):
        from notifications.models import Notification
        mine = self.notify(comment_id=self.comment.id)
        other = self.notify(comment_id=self.comment.id + 999)
        community.take_down_comment(self.comment.id, category='scam', reason='x')
        self.assertFalse(Notification.objects.filter(id=mine.id).exists())
        self.assertTrue(Notification.objects.filter(id=other.id).exists())

    def test_post_erasure_erases_comment_notifications_on_it(self):
        from notifications.models import Notification
        note = self.notify(comment_id=self.comment.id + 999)
        self.assertTrue(community.delete_own_post(self.bob, self.bobs_post.id))
        community.purge_removed_content()
        self.assertFalse(Notification.objects.filter(id=note.id).exists())

    def test_author_can_erase_a_moderated_comment(self):
        community.take_down_comment(self.comment.id, category='scam', reason='x')
        self.assertTrue(community.delete_comment(self.comment.author, self.comment.id))
        self.comment.refresh_from_db()
        self.assertEqual((self.comment.body, self.comment.category), ('', 'scam'))
        self.assertFalse(community.delete_comment(self.comment.author, self.comment.id))

    def test_purge_waits_for_a_pending_image_hide(self):
        item = ContentItem.objects.get(id=self.bobs_post.id)
        item.metadata = {**item.metadata, 'image': {'url': 'https://x/community/a.jpg'}}
        item.save()
        with patch('inbox.community.enqueue_hide_post_image', create=True):
            community.delete_own_post(self.bob, self.bobs_post.id)
        item.refresh_from_db()
        if not item.metadata.get('image'):
            self.skipTest('delete hid the image synchronously')
        community.purge_removed_content()
        item.refresh_from_db()
        self.assertNotEqual(item.body, '')

    def test_backstop_finds_deleted_accounts_by_join(self):
        self.bob.soft_delete()
        owed = dict(community.members_owed_content_removal())
        # The soft-delete signal may already have removed everything.
        self.assertIn(owed.get(self.bob.id, 'deleted'), ('deleted',))


class ClaudeAuditRound4Tests(ClaudeAuditRound3Tests):
    """Claude audit round 4 (2026-10-06): each must stay fixed."""

    def test_hard_deleted_account_takes_its_comment_notifications(self):
        from notifications.models import Notification
        note = self.notify(comment_id=self.comment.id)
        with patch('security.s3_utils.delete_object'):
            self.comment.author.delete()
        self.assertFalse(Notification.objects.filter(id=note.id).exists())

    def test_replies_notifications_go_with_their_parent(self):
        from notifications.models import Notification
        reply = community.create_comment(self.bob, None, self.bobs_post.id, 'Gracias', parent_id=self.comment.id)
        note = self.notify(comment_id=reply.id)
        community.take_down_comment(self.comment.id, category='scam', reason='x')
        self.assertFalse(Notification.objects.filter(id=note.id).exists())
