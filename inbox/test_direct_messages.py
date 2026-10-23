import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from . import community, direct_messages as dm, dm_gate
from .dm_schema import DirectMessagesQuery, SendDirectMessage
from .models import CommunityFollow, DirectConversation, DirectMessage, DirectMessageReport
from .schema import SetCommunityPortfolioHidden
from .test_community import APPROVE, REJECT, SOL_APPROVE, UNSURE, MockInfo, make_user

CASES = [json.loads(line) for line in
         (Path(__file__).parent / 'evals' / 'dm_review_cases.jsonl').read_text().splitlines() if line.strip()]


class PrefilterTests(TestCase):
    def test_every_labeled_prefilter_case_is_caught(self):
        missed = [c['text'] for c in CASES if c.get('layer') == 'prefilter' and not dm_gate.prefilter(c['text'])]
        self.assertEqual(missed, [])

    def test_no_legitimate_message_is_caught(self):
        caught = [c['text'] for c in CASES if c['expect'] == 'deliver' and dm_gate.prefilter(c['text'])]
        self.assertEqual(caught, [])

    def test_the_eval_set_has_its_size(self):
        self.assertEqual(sum(c['expect'] == 'block' for c in CASES), 120)
        self.assertEqual(sum(c['expect'] == 'deliver' for c in CASES), 80)

    def test_amounts_and_prices_are_not_phones(self):
        for text in ('Tengo $1,250,000.50 ahorrados', 'compré a 1.234.567 bolívares', 'precio 120.50',
                     'en 2026 gané 15%', 'ref 12345'):
            self.assertIsNone(dm_gate.prefilter(text), text)


class Base(TestCase):
    def setUp(self):
        enqueue = patch('inbox.direct_messages.enqueue_review')
        self.enqueue = enqueue.start()
        self.addCleanup(enqueue.stop)
        push = patch('inbox.direct_messages.notify_recipient')
        self.push = push.start()
        self.addCleanup(push.stop)
        self.alice, self.bob = make_user(), make_user()

    def send(self, sender, body='Hola, ¿qué opinas de NVDA?', to=None, conversation=None, key=''):
        with self.captureOnCommitCallbacks(execute=True):
            return dm.send_message(sender, None, body, recipient_id=(to or self.bob).id if conversation is None else None,
                                   conversation_id=conversation.id if conversation else None, client_key=key)

    def review(self, message, *verdicts):
        with patch('inbox.dm_gate.community._call_reviewer', side_effect=list(verdicts or [APPROVE])):
            with self.captureOnCommitCallbacks(execute=True):
                return dm.run_review(message.id)

    def visible(self, user, conversation):
        return list(dm.visible_messages(conversation, user).values_list('body', flat=True))


class SendRulesTests(Base):
    def test_first_message_to_a_stranger_is_a_request(self):
        message = self.send(self.alice)
        conversation = message.conversation
        self.assertEqual((conversation.status, message.review_status), ('request', 'pending'))
        self.enqueue.assert_called_once_with(message.id)

    def test_someone_who_follows_you_gets_an_active_chat(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        self.assertEqual(self.send(self.alice).conversation.status, 'active')

    def test_only_approved_messages_reach_the_recipient(self):
        message = self.send(self.alice)
        self.assertEqual(self.visible(self.bob, message.conversation), [])
        self.assertEqual(self.visible(self.alice, message.conversation), [message.body])
        self.assertEqual(self.review(message), 'approved')
        self.assertEqual(self.visible(self.bob, message.conversation), [message.body])
        self.push.assert_called_once_with(message.id)

    def test_a_rejected_message_never_reaches_them_and_tells_the_sender_why(self):
        message = self.send(self.alice)
        self.assertEqual(self.review(message, REJECT), 'rejected')
        message.refresh_from_db()
        self.assertEqual(message.reason, 'Quita tu número de teléfono.')
        self.assertEqual(self.visible(self.bob, message.conversation), [])
        self.push.assert_not_called()

    def test_borderline_messages_escalate(self):
        self.assertEqual(self.review(self.send(self.alice), UNSURE, SOL_APPROVE), 'approved')

    def test_a_prefilter_hit_is_rejected_without_the_model(self):
        message = self.send(self.alice, 'escríbeme al wasap')
        self.assertEqual((message.review_status, message.decided_by_model), ('rejected', 'prefilter'))
        self.enqueue.assert_not_called()

    def test_no_verdict_after_the_last_attempt_fails_closed(self):
        message = self.send(self.alice)
        DirectMessage.objects.filter(id=message.id).update(attempts=dm.MAX_REVIEW_ATTEMPTS)
        self.assertEqual(dm.run_review(message.id), 'failed')
        self.assertEqual(self.visible(self.bob, message.conversation), [])

    def test_an_unavailable_reviewer_raises_for_retry(self):
        message = self.send(self.alice)
        with patch('inbox.dm_gate.community._call_reviewer', side_effect=community.ReviewUnavailable('down')):
            with self.assertRaises(community.ReviewUnavailable):
                dm.run_review(message.id)
        message.refresh_from_db()
        self.assertEqual(message.review_status, 'pending')

    def test_request_cap_until_accepted(self):
        for _ in range(dm.REQUEST_CAP):
            self.send(self.alice)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(self.alice)
        self.assertEqual(ctx.exception.code, dm.REQUEST_LIMIT)

    def test_replying_accepts_the_request(self):
        conversation = self.send(self.alice).conversation
        self.send(self.bob, 'Hola!', conversation=conversation)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, 'active')

    def test_unverified_or_rules_missing_cant_send(self):
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(make_user(verified=False))
        self.assertEqual(ctx.exception.code, dm.IDENTITY_REQUIRED)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(make_user(rules=False))
        self.assertEqual(ctx.exception.code, dm.RULES_REQUIRED)

    def test_a_hidden_profile_cant_start_but_can_reply(self):
        conversation = self.send(self.alice).conversation
        SetCommunityPortfolioHidden.mutate(None, MockInfo(self.bob), hidden=True)
        self.send(self.bob, 'Gracias', conversation=conversation)       # reply: fine
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(self.bob, to=make_user())
        self.assertEqual(ctx.exception.code, dm.PROFILE_HIDDEN)

    def test_dms_off_refuses_new_conversations_only(self):
        conversation = self.send(self.alice).conversation
        dm.set_dms_enabled(self.bob, False)
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(make_user())
        self.assertEqual(ctx.exception.code, dm.DMS_DISABLED)
        self.send(self.bob, 'sigo aquí', conversation=conversation)

    def test_blocks_stop_everything(self):
        from .models import CommunityBlock

        CommunityBlock.objects.create(blocker=self.bob, blocked=self.alice)
        with self.assertRaises(community.CommunityPostError):
            self.send(self.alice)

    def test_a_block_during_review_rejects_the_message(self):
        from .models import CommunityBlock

        message = self.send(self.alice)
        CommunityBlock.objects.create(blocker=self.bob, blocked=self.alice)
        self.assertEqual(self.review(message), 'rejected')

    def test_daily_new_conversation_limit(self):
        for _ in range(dm.NEW_CONVERSATIONS_PER_DAY):
            self.send(self.alice, to=make_user())
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(self.alice, to=make_user())
        self.assertEqual(ctx.exception.code, dm.RATE_LIMITED)

    def test_the_same_client_key_is_one_message(self):
        first = self.send(self.alice, key='k1')
        self.assertEqual(self.send(self.alice, key='k1').id, first.id)
        self.assertEqual(DirectMessage.objects.count(), 1)

    def test_too_long_and_empty(self):
        with self.assertRaises(community.CommunityPostError):
            self.send(self.alice, 'x' * (dm.MAX_CHARS + 1))
        with self.assertRaises(community.CommunityPostError):
            self.send(self.alice, '   ')

    def test_reports_from_three_verified_members_suspend_the_sender(self):
        for _ in range(dm.REPORT_SUSPEND_THRESHOLD):
            reporter = make_user()
            message = self.send(self.alice, to=reporter)
            self.review(message)
            dm.report_message(reporter, message.id, 'spam')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(self.alice, to=make_user())
        self.assertEqual(ctx.exception.code, dm.SUSPENDED)

    def test_old_reports_expire(self):
        reporters = []
        for _ in range(dm.REPORT_SUSPEND_THRESHOLD):
            reporter = make_user()
            message = self.send(self.alice, to=reporter)
            self.review(message)
            dm.report_message(reporter, message.id)
            reporters.append(reporter)
        DirectMessageReport.objects.update(created_at=timezone.now() - dm.REPORT_WINDOW - timedelta(days=1))
        self.send(self.alice, to=make_user())


class FoldersTests(Base):
    def test_requests_and_inbox(self):
        message = self.send(self.alice)
        self.assertEqual(dm.conversations(self.bob, 'requests'), [])     # nothing approved yet
        self.review(message)
        self.assertEqual([c.id for c, _ in dm.conversations(self.bob, 'requests')], [message.conversation_id])
        self.assertEqual(dm.conversations(self.bob, 'inbox'), [])
        self.assertEqual([c.id for c, _ in dm.conversations(self.alice, 'inbox')], [message.conversation_id])
        dm.accept_request(self.bob, message.conversation_id)
        self.assertEqual([c.id for c, _ in dm.conversations(self.bob, 'inbox')], [message.conversation_id])

    def test_deleting_a_request_declines_it_silently(self):
        message = self.send(self.alice)
        self.review(message)
        dm.delete_conversation(self.bob, message.conversation_id)
        follow_up = self.send(self.alice, 'sigues ahí?', conversation=message.conversation)
        self.review(follow_up)
        self.assertEqual(dm.conversations(self.bob, 'requests'), [])
        self.assertEqual(self.visible(self.bob, DirectConversation.objects.get(id=message.conversation_id)), [])
        self.push.assert_called_once_with(message.id)      # only the first, before the decline

    def test_unread_and_read(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        message = self.send(self.alice)
        self.review(message)
        self.assertEqual(dm.unread_summary(self.bob), (1, 0))
        dm.mark_read(self.bob, message.conversation_id)
        self.assertEqual(dm.unread_summary(self.bob), (0, 0))

    def test_a_deleted_chat_comes_back_with_a_new_message(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        first = self.send(self.alice)
        self.review(first)
        dm.delete_conversation(self.bob, first.conversation_id)
        second = self.send(self.alice, 'otra cosa', conversation=first.conversation)
        self.review(second)
        [(conversation, member)] = dm.conversations(self.bob, 'inbox')
        self.assertEqual(list(dm.visible_messages(conversation, self.bob, member.cleared_at)
                              .values_list('body', flat=True)), ['otra cosa'])


class GraphQLTests(Base):
    def ctx(self, user):
        return patch('inbox.schema.get_context_models', return_value=(user, None, None, {}))

    def test_send_and_list(self):
        with self.ctx(self.alice), self.captureOnCommitCallbacks(execute=True):
            result = SendDirectMessage.mutate(None, MockInfo(self.alice), body='Hola', recipient_user_id=str(self.bob.id),
                                              client_key='abc')
        self.assertTrue(result.success)
        self.assertEqual((result.message.status, result.message.from_me), ('pending', True))
        convs = DirectMessagesQuery().resolve_direct_conversations(MockInfo(self.alice))
        self.assertEqual(convs[0].other.user_id, str(self.bob.id))
        page = DirectMessagesQuery().resolve_direct_messages(MockInfo(self.bob), result.conversation_id)
        self.assertEqual(page.messages, [])

    def test_errors_carry_a_code(self):
        with self.ctx(self.alice):
            result = SendDirectMessage.mutate(None, MockInfo(self.alice), body='Hola', recipient_user_id=str(self.alice.id))
        self.assertEqual((result.success, result.code), (False, dm.NOT_AVAILABLE))

    def test_a_stranger_cant_read_the_chat(self):
        message = self.send(self.alice)
        self.review(message)
        page = DirectMessagesQuery().resolve_direct_messages(MockInfo(make_user()), str(message.conversation_id))
        self.assertEqual(page.messages, [])

    def test_profile_button_follows_the_same_rules(self):
        from .schema import Query

        with patch('inbox.community.has_visible_content', return_value=True):
            self.assertTrue(Query().resolve_investor_profile(MockInfo(self.alice), str(self.bob.id)).can_message)
            dm.set_dms_enabled(self.bob, False)
            self.assertFalse(Query().resolve_investor_profile(MockInfo(self.alice), str(self.bob.id)).can_message)


class PushTests(TestCase):
    def setUp(self):
        enqueue = patch('inbox.direct_messages.enqueue_review')
        enqueue.start()
        self.addCleanup(enqueue.stop)
        self.alice, self.bob = make_user(), make_user()

    def approved(self, follows=False):
        from notifications.models import FCMDeviceToken

        if follows:
            CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        FCMDeviceToken.objects.create(user=self.bob, token='tok', device_id='d1', device_type='android', is_active=True)
        message = dm.send_message(self.alice, None, 'Hola, ¿qué opinas de NVDA?', recipient_id=self.bob.id)
        DirectMessage.objects.filter(id=message.id).update(review_status='approved', delivered_at=timezone.now())
        return message

    def test_a_request_push_never_shows_the_text(self):
        message = self.approved()
        with patch('notifications.fcm_service.send_batch_notifications') as send:
            self.assertTrue(dm.notify_recipient(message.id))
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['title'], 'Nueva solicitud de mensaje')
        self.assertNotIn('NVDA', kwargs['body'])
        self.assertEqual(kwargs['data']['action_url'], dm.chat_link(message.conversation_id))
        self.assertEqual(kwargs['channel_id'], 'community')

    def test_an_active_chat_push_shows_the_message(self):
        message = self.approved(follows=True)
        with patch('notifications.fcm_service.send_batch_notifications') as send:
            dm.notify_recipient(message.id)
        self.assertIn('NVDA', send.call_args.kwargs['body'])

    def test_unapproved_messages_never_push(self):
        message = self.approved()
        DirectMessage.objects.filter(id=message.id).update(review_status='rejected')
        with patch('notifications.fcm_service.send_batch_notifications') as send:
            self.assertFalse(dm.notify_recipient(message.id))
        send.assert_not_called()


class PollingAndRacesTests(Base):
    def test_changed_since_returns_a_late_approval_below_newer_messages(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        late = self.send(self.alice, 'primero')
        newer = self.send(self.alice, 'segundo', conversation=late.conversation)
        self.review(newer)
        first_poll = DirectMessagesQuery().resolve_direct_messages(MockInfo(self.bob), str(late.conversation_id))
        self.assertEqual([m.body for m in first_poll.messages], ['segundo'])
        self.review(late)
        DirectMessage.objects.filter(id=late.id).update(delivered_at=timezone.now() + timedelta(seconds=10))
        changed = DirectMessagesQuery().resolve_direct_messages(
            MockInfo(self.bob), str(late.conversation_id), changed_since=first_poll.server_time)
        self.assertIn('primero', [m.body for m in changed.messages])

    def test_a_retry_under_the_request_cap_returns_the_first_message(self):
        for i in range(dm.REQUEST_CAP - 1):
            self.send(self.alice, f'm{i}')
        last = self.send(self.alice, 'último', key='same')
        self.assertEqual(self.send(self.alice, 'último', key='same').id, last.id)

    def test_a_declined_request_keeps_the_same_cap(self):
        message = self.send(self.alice)
        self.review(message)
        dm.delete_conversation(self.bob, message.conversation_id)
        for _ in range(dm.REQUEST_CAP - 1):
            self.send(self.alice, conversation=DirectConversation.objects.get(id=message.conversation_id))
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.send(self.alice, conversation=DirectConversation.objects.get(id=message.conversation_id))
        self.assertEqual(ctx.exception.code, dm.REQUEST_LIMIT)

    def test_suspension_stops_pending_messages(self):
        message = self.send(self.alice)
        with patch('inbox.direct_messages.is_suspended', return_value=True):
            self.assertEqual(self.review(message), 'rejected')

    def test_a_phone_number_username_is_never_shown(self):
        self.alice.username = '04145551234'
        self.alice.save(update_fields=['username'])
        self.assertEqual(community.author_display_name(self.alice), community.pseudonym(self.alice))

    def test_you_can_block_someone_who_wrote_to_you(self):
        message = self.send(self.alice)
        community.block_member(self.bob, self.alice.id)
        self.assertTrue(community.is_blocked_between(self.alice.id, self.bob.id))

    def test_the_decliner_writing_back_reopens_the_chat(self):
        message = self.send(self.alice)
        self.review(message)
        dm.delete_conversation(self.bob, message.conversation_id)
        self.send(self.bob, 'perdón, sí quiero hablar', to=self.alice)
        self.assertEqual(DirectConversation.objects.get(id=message.conversation_id).status, 'active')

    def test_too_many_changes_restart_from_the_latest_page(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        first = self.send(self.alice)
        since = timezone.now() - timedelta(minutes=1)
        with patch('inbox.dm_schema.CHANGES_LIMIT', 0):
            self.review(first)
            page = DirectMessagesQuery().resolve_direct_messages(MockInfo(self.bob), str(first.conversation_id),
                                                                 changed_since=since)
        self.assertEqual((page.messages, page.has_more, page.server_time), ([], True, None))

    def test_glued_app_names_and_digits_in_usernames_are_never_shown(self):
        for name in ('whatsapp_71234567', 'ig.maria', 'juan_4145551234', 'tlgrm-carlos'):
            self.alice.username = name
            self.assertEqual(community.author_display_name(self.alice), community.pseudonym(self.alice), name)
        self.alice.username = 'maria_invierte2024'
        self.assertEqual(community.author_display_name(self.alice), 'maria_invierte2024')

    def test_an_unverified_member_can_receive(self):
        carol = make_user(verified=False)
        self.assertEqual(self.send(self.alice, to=carol).review_status, 'pending')

    def test_a_message_approved_after_the_chat_was_deleted_shows(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        first = self.send(self.alice)
        self.review(first)
        late = self.send(self.alice, 'llegó tarde', conversation=first.conversation)
        dm.delete_conversation(self.bob, first.conversation_id)
        self.review(late)
        [(conversation, member)] = dm.conversations(self.bob, 'inbox')
        self.assertEqual(list(dm.visible_messages(conversation, self.bob, member.cleared_at)
                              .values_list('body', flat=True)), ['llegó tarde'])

    def test_the_requester_cant_tell_a_decline_from_silence(self):
        message = self.send(self.alice)
        self.review(message)
        SetCommunityPortfolioHidden.mutate(None, MockInfo(self.alice), hidden=True)
        before = dm.send_block(self.alice, self.bob)
        dm.delete_conversation(self.bob, message.conversation_id)
        self.assertEqual(dm.send_block(self.alice, self.bob), before)

    def test_my_message_approved_after_i_deleted_the_chat_stays_gone(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        mine = self.send(self.alice)
        dm.delete_conversation(self.alice, mine.conversation_id)
        self.review(mine)
        conversation = DirectConversation.objects.get(id=mine.conversation_id)
        member = dm.member_of(self.alice, conversation.id)
        self.assertEqual(list(dm.visible_messages(conversation, self.alice, member.cleared_at)), [])

    def test_read_receipts_stop_at_the_shown_page(self):
        CommunityFollow.objects.create(follower=self.bob, followed=self.alice)
        first = self.send(self.alice)
        self.review(first)
        shown_at = timezone.now()
        later = self.send(self.alice, 'después', conversation=first.conversation)
        self.review(later)
        DirectMessage.objects.filter(id=later.id).update(delivered_at=shown_at + timedelta(seconds=5))
        dm.mark_read(self.bob, first.conversation_id, up_to=shown_at)
        self.assertEqual(dm.unread_summary(self.bob), (1, 0))
