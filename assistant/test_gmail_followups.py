"""Follow-ups for what Confío IA told about her Gmail and is still open, until the next day (2026-11-26)."""
from datetime import date, datetime, timedelta, timezone as tz
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache

from inbox.models import SupportMessage
from users.models import Account

from .gmail import chat, config, crypto, followups, sync, text
from .gmail.errors import GmailError
from .gmail.models import MailNeed
from .test_gmail_pilot import GmailPilotTest, gmail_message

TOLD = datetime(2026, 11, 26, 10, tzinfo=tz.utc)  # the person's clock is UTC in these tests


def millis(moment):
    return str(int(moment.timestamp() * 1000))


class StepTests(GmailPilotTest):
    def test_the_schedule(self):
        step, utc = followups.step, tz.utc
        self.assertEqual(step(TOLD, 0, None, TOLD + timedelta(hours=3, minutes=59), utc), 0)
        self.assertEqual(step(TOLD, 0, None, TOLD + timedelta(hours=4), utc), 1)
        self.assertEqual(step(TOLD, 0, None, datetime(2026, 11, 26, 22, 30, tzinfo=utc), utc), 0)  # night
        first = TOLD + timedelta(hours=4)
        self.assertEqual(step(TOLD, 1, first, TOLD + timedelta(hours=8), utc), 0)  # same day
        self.assertEqual(step(TOLD, 1, first, datetime(2026, 11, 27, 7, tzinfo=utc), utc), 2)
        self.assertEqual(step(TOLD, 1, first, datetime(2026, 11, 27, 12, tzinfo=utc), utc), 0)  # mornings only
        self.assertEqual(step(TOLD, 2, first, datetime(2026, 11, 27, 8, tzinfo=utc), utc), 0)
        self.assertEqual(step(TOLD, 0, None, TOLD + timedelta(hours=37), utc), 0)
        self.assertEqual(step(None, 0, None, TOLD + timedelta(hours=5), utc), 0)
        caracas = ZoneInfo('America/Caracas')  # UTC-4
        self.assertEqual(step(TOLD, 0, None, datetime(2026, 11, 27, 1, tzinfo=utc), caracas), 1)  # 21:00 there
        self.assertEqual(step(TOLD, 0, None, datetime(2026, 11, 27, 2, tzinfo=utc), caracas), 0)  # 22:00 there

    def test_when_by_her_calendar_days(self):
        utc = tz.utc
        self.assertEqual(followups.when_words(TOLD, TOLD + timedelta(hours=4), utc), 'hace 4 h')
        self.assertEqual(followups.when_words(datetime(2026, 11, 26, 23, tzinfo=utc),
                                              datetime(2026, 11, 27, 7, tzinfo=utc), utc), 'ayer')
        self.assertEqual(followups.when_words(TOLD, TOLD + timedelta(days=2), utc), 'anteayer')
        self.assertEqual(followups.when_words(TOLD, TOLD + timedelta(days=5), utc), 'hace 5 días')

    def test_her_zone_is_her_countrys(self):
        from users.models import User
        User.objects.filter(pk=self.user.pk).update(country='BO')
        self.user.refresh_from_db()
        self.assertEqual(str(followups.zone_of(self.user)), 'America/La_Paz')


class FollowupBase(GmailPilotTest):
    consent = config.THREAD_CONSENT_VERSION

    def setUp(self):
        super().setUp()
        cache.clear()
        Account.objects.create(user=self.user, account_type='personal', account_index=0)
        zone = patch('assistant.gmail.followups.zone_of', return_value=tz.utc)
        zone.start()
        self.pushed = patch.object(chat, 'push_follow_up').start()
        self.addCleanup(patch.stopall)
        self.connection = self.connect(consent_version=self.consent)
        self.raw = {**gmail_message(sender='Ana <ana@example.com>', subject='¿Nos vemos el sábado?'),
                    'internalDate': millis(TOLD - timedelta(minutes=5))}
        self.box.message_marks.return_value = {'threadId': 'thread1', 'labelIds': ['INBOX'],
                                               'internalDate': self.raw['internalDate']}
        self.box.thread_marks.return_value = [{'labelIds': ['INBOX'], 'internalDate': self.raw['internalDate']}]
        self.box.message.side_effect = AssertionError('a follow-up never reads the mail text again')

    def need(self, kind='reply', told=TOLD, due=None, sender='Ana', about='a1', thread=''):
        need = MailNeed.objects.create(connection=self.connection, source_key=f'k{MailNeed.objects.count()}',
                                       kind=kind, due_date=due, told_at=told,
                                       sealed=crypto.seal({'id': 'abc123', 'sender': sender, 'summary': 'Pregunta',
                                                           'shown_sender': sender, 'thread': thread,
                                                           'shown_subject': '¿Nos vemos el sábado?'}))
        if told is not None:
            message = chat._post(self.user, 'contado', f'gmail-need:{need.pk}', connection=self.connection,
                                 extra={'mail_about': about})
            SupportMessage.objects.filter(pk=message.pk).update(created_at=told)
        return need

    def posts(self):
        return list(SupportMessage.objects.filter(conversation__user=self.user,
                                                  metadata__notice__startswith='gmail-followup:').order_by('pk'))

    def sweep(self, at):
        with self.with_box():
            return followups.run(at)


class FollowupTests(FollowupBase):
    def test_four_hours_later_then_the_next_morning_then_never(self):
        need = self.need()
        self.assertEqual(self.sweep(TOLD + timedelta(hours=3)), 0)
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 1)
        self.assertEqual(self.sweep(TOLD + timedelta(hours=6)), 0)
        self.assertEqual(self.sweep(datetime(2026, 11, 27, 8, tzinfo=tz.utc)), 1)
        self.assertEqual(self.sweep(datetime(2026, 11, 27, 9, tzinfo=tz.utc)), 0)
        first, second = self.posts()
        self.assertIn('«Ana» sigue esperando tu respuesta a «¿Nos vemos el sábado?». ¿Le respondo?', first.body)
        self.assertEqual(first.metadata['actions'], [{'type': 'mail_reply', 'target': str(need.pk), 'label': 'Responder…'}])
        self.assertTrue(first.metadata['gmail'])
        self.assertEqual(self.pushed.call_count, 2)
        self.assertEqual(self.box.thread_marks.call_args.args[0], 'thread1')  # labels and dates only

    def test_many_open_ones_are_one_message_and_one_push(self):
        import itertools
        threads = itertools.count()
        self.box.message_marks.side_effect = lambda _id: {'threadId': f't{next(threads)}', 'labelIds': ['INBOX'],
                                                          'internalDate': self.raw['internalDate']}
        for i in range(6):
            self.need(sender=f'P{i}', about=f'a{i}')
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 1)
        [post] = self.posts()
        self.assertTrue(post.body.startswith('Siguen pendientes en tu Gmail:'))
        self.assertEqual(post.body.count('• '), 3)
        self.assertNotIn('más.', post.body)  # the rest are named later, each after its own check
        self.assertEqual(MailNeed.objects.filter(followups=1).count(), 3)  # only the named are claimed
        self.assertEqual(self.pushed.call_count, 1)
        self.assertEqual(self.pushed.call_args.args[1], 3)
        self.assertEqual(self.sweep(TOLD + timedelta(hours=5)), 1)  # the other three, named
        self.assertEqual(MailNeed.objects.filter(followups=1).count(), 6)
        self.need(sender='P9', about='a9', told=TOLD + timedelta(hours=2))
        self.assertEqual(self.sweep(TOLD + timedelta(hours=6)), 0)  # two a day at most

    def test_her_reply_in_the_thread_settles_it(self):
        need = self.need()
        self.box.thread_marks.return_value = [
            {'labelIds': ['INBOX'], 'internalDate': self.raw['internalDate']},
            {'labelIds': ['SENT'], 'internalDate': millis(TOLD + timedelta(hours=1))}]
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 0)
        need.refresh_from_db()
        self.assertIsNotNone(need.resolved_at)
        self.assertEqual(self.sweep(datetime(2026, 11, 27, 8, tzinfo=tz.utc)), 0)
        self.assertEqual(self.posts(), [])

    def test_a_reply_of_hers_before_the_mail_does_not(self):
        self.need()
        self.box.thread_marks.return_value = [{'labelIds': ['SENT'], 'internalDate': millis(TOLD - timedelta(hours=2))}]
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 1)

    def test_a_failed_read_posts_nothing_and_waits_an_hour(self):
        need = self.need()
        self.box.thread_marks.side_effect = GmailError(500)
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 0)
        self.box.thread_marks.side_effect = None
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4, minutes=10)), 0)  # waiting
        need.refresh_from_db()
        self.assertEqual((need.followups, need.resolved_at), (0, None))
        cache.delete(f'gmail-followup-wait:{need.pk}')  # the hour has passed
        self.assertEqual(self.sweep(TOLD + timedelta(hours=5)), 1)

    def test_dismissed_or_never_told_is_never_followed_up(self):
        dismissed = self.need()
        MailNeed.objects.filter(pk=dismissed.pk).update(dismissed=True)
        self.need(told=None)  # only counted in the morning notice
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 0)

    def test_a_payment_on_the_morning_it_is_due(self):
        self.need(kind='payment', told=TOLD - timedelta(days=1), due=date(2026, 11, 28))
        self.assertEqual(self.sweep(datetime(2026, 11, 27, 8, tzinfo=tz.utc)), 0)  # not due yet
        self.assertEqual(self.sweep(datetime(2026, 11, 28, 6, tzinfo=tz.utc)), 0)  # before 7
        self.assertEqual(self.sweep(datetime(2026, 11, 28, 8, tzinfo=tz.utc)), 1)
        self.assertEqual(self.sweep(datetime(2026, 11, 28, 9, tzinfo=tz.utc)), 0)  # once
        [post] = self.posts()
        self.assertTrue(post.body.startswith('Recordatorio: «¿Nos vemos el sábado?» de «Ana» vence hoy.'))
        self.assertEqual(post.metadata['actions'], [])
        self.box.thread_marks.assert_not_called()  # a payment reads that mail only

    def test_a_payment_told_this_morning_is_not_told_again(self):
        self.need(kind='deadline', told=datetime(2026, 11, 28, 7, tzinfo=tz.utc), due=date(2026, 11, 28))
        self.assertEqual(self.sweep(datetime(2026, 11, 28, 9, tzinfo=tz.utc)), 0)

    def test_a_copy_of_a_dismissed_payment_is_not_reminded(self):
        first = self.need(kind='payment', told=TOLD - timedelta(days=20), due=date(2026, 11, 28), about='same')
        MailNeed.objects.filter(pk=first.pk).update(dismissed=True)
        copy = self.need(kind='payment', told=TOLD - timedelta(days=1), due=date(2026, 11, 28), about='same')
        self.assertEqual(self.sweep(datetime(2026, 11, 28, 8, tzinfo=tz.utc)), 0)
        copy.refresh_from_db()
        self.assertIsNotNone(copy.resolved_at)

    def test_two_sweeps_never_post_it_twice(self):
        need = self.need()
        stale = MailNeed.objects.select_related('connection__user').get(pk=need.pk)
        with self.with_box():
            self.assertEqual(followups._person(self.connection, (tz.utc, [(need, 1)]), TOLD + timedelta(hours=4)), 1)
            self.assertEqual(followups._person(self.connection, (tz.utc, [(stale, 1)]), TOLD + timedelta(hours=4)), 0)
        self.assertEqual(len(self.posts()), 1)

    def test_disconnecting_erases_follow_ups_too(self):
        self.need()
        self.sweep(TOLD + timedelta(hours=4))
        self.assertEqual(len(self.posts()), 1)
        chat.erase(self.user.pk)
        self.assertEqual(self.posts(), [])

    def test_reads_have_their_own_daily_count(self):
        from .gmail import limits
        self.assertIn('followup', limits.PER_DAY)
        self.need()
        with patch.object(limits, 'claim') as claim:
            self.sweep(TOLD + timedelta(hours=4))
        self.assertEqual(claim.call_args.args[1], 'followup')


class MoreFollowupTests(FollowupBase):
    def test_she_threw_the_mail_away(self):
        need = self.need()
        self.box.message_marks.return_value = {**self.box.message_marks.return_value, 'labelIds': ['TRASH']}
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 0)
        need.refresh_from_db()
        self.assertIsNotNone(need.resolved_at)

    def test_two_needs_of_one_thread_are_one_reminder(self):
        older = self.need(about='x1')
        newer = self.need(about='x2', told=TOLD + timedelta(minutes=30))
        self.assertEqual(self.sweep(TOLD + timedelta(hours=5)), 1)
        [post] = self.posts()
        self.assertEqual(post.body.count('sigue esperando'), 1)
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertIsNotNone(older.resolved_at)
        self.assertEqual(newer.followups, 1)

    def test_what_is_not_due_takes_no_place(self):
        from users.models import User
        waiting = User.objects.create(username='waiting_one', firebase_uid='waiting-one')
        Account.objects.create(user=waiting, account_type='personal', account_index=0)
        early = self.connect(user=waiting, consent_version=self.consent)
        for i in range(3):  # waiting for tomorrow's morning: sorted first, never due today
            MailNeed.objects.create(connection=early, source_key=f'w{i}', kind='reply', told_at=TOLD - timedelta(hours=6),
                                    followups=1, followed_at=TOLD - timedelta(hours=2),
                                    sealed=crypto.seal({'id': 'abc123'}))
        self.need()
        with patch.object(followups, 'PER_RUN', 1):
            self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 1)

    def test_a_post_that_does_not_happen_releases_the_claim(self):
        need = self.need()
        with patch.object(chat, 'follow_up', return_value=None):
            self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 0)
        need.refresh_from_db()
        self.assertEqual((need.followups, need.followed_at), (0, None))
        self.assertEqual(self.sweep(TOLD + timedelta(hours=5)), 1)


class ThreadAndPushTests(FollowupBase):
    def test_a_newer_told_mail_of_the_thread_settles_the_older_across_runs(self):
        older = self.need(thread='th1', about='o')
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 1)  # the older, alone so far
        newer = self.need(thread='th1', about='n', told=TOLD + timedelta(hours=5))
        self.assertEqual(self.sweep(datetime(2026, 11, 27, 8, tzinfo=tz.utc)), 1)  # the newer one's first
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertIsNotNone(older.resolved_at)
        self.assertEqual(older.followups, 1)  # never its second
        self.assertEqual(newer.followups, 1)

    def test_a_follow_up_already_posted_counts_as_posted(self):
        need = self.need()
        tag = f'gmail-followup:{need.pk}.1'
        first = chat.follow_up(self.connection, [(need, 1)])
        self.assertEqual(first.metadata['notice'], tag)
        self.assertEqual(chat.follow_up(self.connection, [(need, 1)]).pk, first.pk)


class ReminderPushTests(GmailPilotTest):
    def test_the_push_reads_as_a_reminder_and_leaves_the_morning_count_alone(self):
        connection = self.connect(consent_version=config.CHAT_CONSENT_VERSION)
        need = MailNeed.objects.create(connection=connection, source_key='p', kind='reply', sealed=crypto.seal({}))
        with patch('assistant.gmail.chat.timezone.now', return_value=datetime(2026, 11, 27, 15, tzinfo=tz.utc)), \
                patch('assistant.gmail.config.utc_offset', return_value=0), \
                patch('notifications.utils.create_notification') as created:
            self.assertTrue(chat.push_follow_up(connection, 2))
            self.assertFalse(chat.push_follow_up(connection, 1))  # one Gmail push an hour
        kwargs = created.call_args.kwargs
        self.assertEqual(kwargs['title'], 'Pendiente · Gmail')
        self.assertEqual(kwargs['message'], '2 correos siguen pendientes. Te lo recuerdo en Confío IA.')
        need.refresh_from_db()
        self.assertIsNone(need.notified_at)

    def test_never_at_night(self):
        connection = self.connect(consent_version=config.CHAT_CONSENT_VERSION)
        with patch('assistant.gmail.chat.timezone.now', return_value=datetime(2026, 11, 27, 4, tzinfo=tz.utc)), \
                patch('assistant.gmail.config.utc_offset', return_value=0), \
                patch('notifications.utils.create_notification') as created:
            self.assertFalse(chat.push_follow_up(connection, 1))
        created.assert_not_called()


class ThreadConsentTests(FollowupBase):
    consent = config.CHAT_CONSENT_VERSION  # agreed to the conversation, not to reading threads

    def test_no_reply_follow_up_without_the_thread_consent(self):
        self.need()
        self.assertEqual(self.sweep(TOLD + timedelta(hours=4)), 0)
        self.box.thread_marks.assert_not_called()

    def test_a_due_payment_still_is(self):
        self.need(kind='payment', told=TOLD - timedelta(days=1), due=date(2026, 11, 28))
        self.assertEqual(self.sweep(datetime(2026, 11, 28, 8, tzinfo=tz.utc)), 1)


class TellTests(GmailPilotTest):
    def test_telling_marks_it_told_and_leaves_the_morning_count_alone(self):
        Account.objects.create(user=self.user, account_type='personal', account_index=0)
        connection = self.connect(consent_version=config.CHAT_CONSENT_VERSION)
        need = MailNeed.objects.create(connection=connection, source_key='told', kind='reply',
                                       sealed=crypto.seal({'id': 'abc123', 'sender': 'Ana'}))
        with patch.object(chat, '_push') as push:
            chat.tell(connection, need, text.parse(gmail_message()))
        push.assert_called_once()
        need.refresh_from_db()
        self.assertIsNotNone(need.told_at)
        self.assertIsNone(need.notified_at)
        shown = crypto.unseal(need.sealed)
        self.assertEqual((shown['shown_sender'], shown['shown_subject'], shown['thread']),
                         ('Ana', 'Factura de luz', 'thread1'))  # only a push that went out settles the morning count (_push)


class NightPushTests(GmailPilotTest):
    def test_a_push_at_night_waits_for_the_morning_count(self):
        connection = self.connect(consent_version=config.CHAT_CONSENT_VERSION)
        need = MailNeed.objects.create(connection=connection, source_key='n', kind='reply', sealed=crypto.seal({}))
        with patch('assistant.gmail.chat.timezone.now', return_value=datetime(2026, 11, 27, 4, tzinfo=tz.utc)), \
                patch('assistant.gmail.config.utc_offset', return_value=0), \
                patch('notifications.utils.create_notification') as created:
            chat._push(connection, need)
        created.assert_not_called()
        need.refresh_from_db()
        self.assertIsNone(need.notified_at)
