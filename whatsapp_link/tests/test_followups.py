"""Follow-ups for what Confío IA told about WhatsApp and is still open, until the next day (2026-11-26)."""
from datetime import datetime, timedelta, timezone as tz
from unittest import mock

from django.utils import timezone

from inbox.models import SupportMessage
from whatsapp_link import chat, followups, service
from whatsapp_link.models import WhatsAppDraft, WhatsAppInbox, WhatsAppNotice

from .test_service import LinkTestBase

JID = '59170000001@s.whatsapp.net'
TOLD = datetime(2026, 11, 26, 10, tzinfo=tz.utc)  # the person's clock is UTC in these tests, but for the zone test


class FollowupTests(LinkTestBase):
    def setUp(self):
        super().setUp()
        from users.models import Account
        Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.zone = self.patch('whatsapp_link.followups.zone_of', return_value=tz.utc)
        self.link = self.linked()

    def notice(self, kind='reply', jid=JID, told=TOLD, name='Ana', told_in_chat=True, phone='59170000001'):
        notice = WhatsAppNotice.objects.create(
            link=self.link, source_key=f'k{WhatsAppNotice.objects.count()}', kind=kind, notified_at=told,
            told_at=told if told_in_chat else None,
            sealed=service._seal({'chat': name, 'jid': jid, 'phone': phone, 'preview': '¿Vienes el sábado?',
                                  'at': int(told.timestamp()) - 60}))
        WhatsAppNotice.objects.filter(pk=notice.pk).update(created_at=told)
        notice.refresh_from_db()
        return notice

    def posts(self):
        return list(SupportMessage.objects.filter(conversation__user=self.user, metadata__notice__startswith='whatsapp-followup:')
                    .order_by('pk'))

    def test_four_hours_later_then_the_next_morning_then_never(self):
        self.notice()
        self.assertEqual(followups.run(TOLD + timedelta(hours=3)), 0)
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)
        self.assertEqual(followups.run(TOLD + timedelta(hours=5)), 0)  # once that day
        self.assertEqual(followups.run(TOLD + timedelta(hours=22)), 1)  # 08:00 the next day
        self.assertEqual(followups.run(TOLD + timedelta(hours=23)), 0)
        first, second = self.posts()
        self.assertIn('«Ana» sigue esperando tu respuesta (te escribió hace 4 h):', first.body)
        self.assertIn('(te escribió ayer)', second.body)
        self.assertEqual(self.pushes.call_count, 2)
        # The push reads as a reminder, never as a new message.
        self.assertEqual(self.pushes.call_args.kwargs['title'], 'Pendiente · WhatsApp')
        self.assertEqual(self.pushes.call_args.args[1], 'Ana sigue esperando tu respuesta')

    def test_only_buttons_that_draw_the_text_never_the_original_card(self):
        notice = self.notice()
        followups.run(TOLD + timedelta(hours=4))
        actions = self.posts()[0].metadata['actions']
        self.assertEqual(actions, [{'type': 'whatsapp_other', 'target': str(notice.pk), 'label': 'Otro…'}])
        self.assertTrue(self.posts()[0].metadata['whatsapp'])

    def test_many_open_ones_are_one_message_and_one_push(self):
        for i in range(6):
            self.notice(jid=f'5917000000{i}@s.whatsapp.net', name=f'P{i}', phone=f'5917000000{i}')
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)
        [post] = self.posts()
        self.assertTrue(post.body.startswith('Siguen pendientes en tu WhatsApp:'))
        self.assertEqual(post.body.count('• '), 3)
        self.assertNotIn('más.', post.body)  # the rest are named later, each after its own check
        self.assertEqual(WhatsAppNotice.objects.filter(followups=1).count(), 3)  # only the named are claimed
        self.assertEqual(self.pushes.call_count, 1)
        self.assertEqual(self.pushes.call_args.kwargs['title'], 'Pendiente · WhatsApp')
        self.assertIn('3 conversaciones siguen pendientes', self.pushes.call_args.args[1])
        # The other three come in the next one, named: never a burst.
        self.assertEqual(followups.run(TOLD + timedelta(hours=5)), 1)
        self.assertEqual(WhatsAppNotice.objects.filter(followups=1).count(), 6)

    def test_at_most_two_follow_up_messages_a_day(self):
        for hour in (0, 1, 2):
            self.notice(told=TOLD + timedelta(hours=hour), jid=f'59171{hour}@s.whatsapp.net', phone=f'59171{hour}')
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)
        self.assertEqual(followups.run(TOLD + timedelta(hours=5)), 1)
        self.assertEqual(followups.run(TOLD + timedelta(hours=6)), 0)  # the third waits for tomorrow
        self.assertEqual(followups.run(TOLD + timedelta(hours=21)), 1)  # 07:00 the next day

    def test_never_at_night_and_never_past_a_day_and_a_half(self):
        late = self.notice(told=datetime(2026, 11, 26, 19, tzinfo=tz.utc))
        self.assertEqual(followups.run(datetime(2026, 11, 26, 23, tzinfo=tz.utc)), 0)
        self.assertEqual(self.pushes.call_count, 0)
        self.assertEqual(followups.run(datetime(2026, 11, 27, 8, tzinfo=tz.utc)), 1)
        late.refresh_from_db()
        self.assertEqual(late.followups, 1)
        old = self.notice(told=TOLD - timedelta(hours=40), jid='5919@s.whatsapp.net')
        followups.run(TOLD + timedelta(hours=1))
        old.refresh_from_db()
        self.assertEqual(old.followups, 0)

    def test_her_own_clock_decides(self):
        from users.models import User
        from assistant.gmail.followups import zone_of
        User.objects.filter(pk=self.user.pk).update(country='VE')
        self.user.refresh_from_db()
        self.assertEqual(str(zone_of(self.user)), 'America/Caracas')
        self.zone.return_value = zone_of(self.user)
        self.notice(told=datetime(2026, 11, 26, 20, tzinfo=tz.utc))  # 16:00 in Caracas
        self.assertEqual(followups.run(datetime(2026, 11, 27, 2, tzinfo=tz.utc)), 0)  # 22:00 there, though 02 UTC
        self.assertEqual(followups.run(datetime(2026, 11, 27, 1, 30, tzinfo=tz.utc)), 1)  # 21:30 there

    def test_only_what_waits_for_her_and_was_told(self):
        self.notice(kind='delivery')
        self.notice(kind='order', jid='591700000022@s.whatsapp.net')
        self.notice(jid='5913@s.whatsapp.net', told_in_chat=False)  # before this build, or its post failed
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 0)

    def test_tell_marks_it_told(self):
        notice = self.notice(told_in_chat=False)
        chat.tell(self.link, notice, [])
        notice.refresh_from_db()
        self.assertIsNotNone(notice.told_at)

    def test_her_reply_after_it_settles_it(self):
        notice = self.notice()
        WhatsAppInbox.objects.create(link=self.link, source_key='mine', chat_key=service._chat_key(self.link, JID),
                                     from_me=True, sealed=service._seal({'text': 'sí'}))
        WhatsAppInbox.objects.filter(source_key='mine').update(created_at=TOLD + timedelta(hours=1))
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 0)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        self.assertEqual(followups.run(TOLD + timedelta(hours=22)), 0)

    def test_her_message_before_it_does_not(self):
        self.notice()
        WhatsAppInbox.objects.create(link=self.link, source_key='before', chat_key=service._chat_key(self.link, JID),
                                     from_me=True, sealed=service._seal({'text': 'hola'}))
        WhatsAppInbox.objects.filter(source_key='before').update(created_at=TOLD - timedelta(hours=1))
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)

    def draft(self, status, sending_at=TOLD + timedelta(hours=1), **fields):
        return WhatsAppDraft.objects.create(link=self.link, status=status, sealed=service._seal({'body': 'sí', **fields}),
                                            expires_at=TOLD + timedelta(days=1), sending_at=sending_at)

    def test_a_reply_sent_before_the_message_does_not_settle_it(self):
        self.notice()
        self.draft(WhatsAppDraft.Status.SENT, sending_at=TOLD - timedelta(hours=2), jid=JID)
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)

    def test_her_messages_are_judged_by_their_own_time(self):
        notice = self.notice()
        key = service._chat_key(self.link, JID)
        # Arrived late (history), but written before the message: not an answer.
        WhatsAppInbox.objects.create(link=self.link, source_key='old', chat_key=key, from_me=True,
                                     sealed=service._seal({'text': 'hola', 'at': int(TOLD.timestamp()) - 3600}))
        WhatsAppInbox.objects.filter(source_key='old').update(created_at=TOLD + timedelta(hours=1))
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)
        # Written after it: settles it, for the next morning's too.
        WhatsAppInbox.objects.create(link=self.link, source_key='new', chat_key=key, from_me=True,
                                     sealed=service._seal({'text': 'sí', 'at': int(TOLD.timestamp()) + 7200}))
        self.assertEqual(followups.run(TOLD + timedelta(hours=22)), 0)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)

    def test_a_sent_reply_settles_it_by_chat_or_by_number(self):
        for fields in ({'jid': JID}, {'phone': '59170000001'}):
            WhatsAppNotice.objects.all().delete()
            WhatsAppDraft.objects.all().delete()
            notice = self.notice()
            self.draft(WhatsAppDraft.Status.SENT, **fields)
            self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 0, fields)
            notice.refresh_from_db()
            self.assertIsNotNone(notice.resolved_at)

    def test_one_still_sending_does_not(self):
        self.notice()
        self.draft(WhatsAppDraft.Status.SENDING, jid=JID)
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)

    def test_a_newer_message_of_the_chat_carries_the_follow_ups(self):
        older = self.notice()
        self.notice(told=TOLD + timedelta(hours=1))
        self.assertEqual(followups.run(TOLD + timedelta(hours=5)), 1)
        older.refresh_from_db()
        self.assertIsNotNone(older.resolved_at)

    def test_two_sweeps_never_post_it_twice(self):
        notice = self.notice()
        stale = WhatsAppNotice.objects.select_related('link__user').get(pk=notice.pk)
        self.assertEqual(followups._person(self.link, (tz.utc, [(notice, 1)]), TOLD + timedelta(hours=4)), 1)
        self.assertEqual(followups._person(self.link, (tz.utc, [(stale, 1)]), TOLD + timedelta(hours=4)), 0)
        self.assertEqual(len(self.posts()), 1)

    def test_unlinking_erases_follow_ups_too(self):
        self.notice()
        followups.run(TOLD + timedelta(hours=4))
        self.assertEqual(len(self.posts()), 1)
        chat.erase(self.user)
        self.assertEqual(self.posts(), [])

    def test_never_for_a_link_gone(self):
        self.notice()
        self.link.state = self.link.State.GONE
        self.link.save()
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 0)

    def test_a_look_keeps_the_newest_message_time(self):
        self.patch('whatsapp_link.classify.important',
                   return_value=[{'kind': 'reply', 'summary': 's', 'replies': []}])
        link = self.link
        at = int(timezone.now().timestamp()) - 60
        self.message(link, text='¿Vienes?', at=at)
        service.sync(link.pk)
        notice = WhatsAppNotice.objects.get(link=link)
        self.assertEqual(service._unseal(notice.sealed, {})['at'], at)

    def test_what_is_not_due_takes_no_place(self):
        from users.models import Account, User
        other = User.objects.create(username='wa_waiting', firebase_uid='wa-waiting')
        Account.objects.create(user=other, account_type='personal', account_index=0)
        early = self.linked(user=other, phone_key=service.phone_key('59179999999'))
        for i in range(3):  # waiting for tomorrow's morning: sorted first, never due today
            WhatsAppNotice.objects.create(link=early, source_key=f'w{i}', kind='reply', told_at=TOLD - timedelta(hours=6),
                                          followups=1, followed_at=TOLD - timedelta(hours=2),
                                          sealed=service._seal({'chat': 'X', 'jid': f'5{i}@s.whatsapp.net'}))
        self.notice()
        self.patch('whatsapp_link.followups.PER_RUN', new=1)
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)

    def test_a_post_that_does_not_happen_releases_the_claim(self):
        notice = self.notice()
        with mock.patch.object(chat, 'follow_up', return_value=None):
            self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 0)
        notice.refresh_from_db()
        self.assertEqual((notice.followups, notice.followed_at), (0, None))
        self.assertEqual(followups.run(TOLD + timedelta(hours=5)), 1)

    def test_a_dismissed_one_is_never_claimed(self):
        notice = self.notice()
        stale = WhatsAppNotice.objects.select_related('link__user').get(pk=notice.pk)
        WhatsAppNotice.objects.filter(pk=notice.pk).update(dismissed=True)
        self.assertEqual(followups._person(self.link, (tz.utc, [(stale, 1)]), TOLD + timedelta(hours=4)), 0)

    def test_an_untold_newer_message_does_not_settle_it(self):
        older = self.notice()
        self.notice(told=TOLD + timedelta(hours=1), told_in_chat=False)
        self.notice(kind='delivery', told=TOLD + timedelta(hours=1))
        self.assertEqual(followups.run(TOLD + timedelta(hours=4)), 1)
        older.refresh_from_db()
        self.assertIsNone(older.resolved_at)
