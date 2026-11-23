"""Beyond bills: wider reading, a one-line summary, and Google Calendar in the daily notice."""
from datetime import date, datetime, timedelta, timezone as tz
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
from graphene.test import Client

from notifications.models import Notification

from .gmail import client, config, crypto, oauth, reader, schema, service, session, sync, text
from .gmail.errors import MailRefused
from .gmail.models import GmailConnection, MailNeed
from .test_gmail_pilot import PERSONAL, GmailPilotTest, gmail_message, model_answer

DAY = date(2026, 11, 23)
# The default offset is UTC-6: 14:00 UTC is 08:00 for the person, 21:00 UTC is 15:00.
MORNING = datetime(2026, 11, 23, 14, tzinfo=tz.utc)
LAST_MORNING_HOUR = datetime(2026, 11, 23, 16, tzinfo=tz.utc)
AFTERNOON = datetime(2026, 11, 23, 21, tzinfo=tz.utc)
MINE = {'organizer': {'self': True}}


def event(summary='Dentista', start='2026-11-23T15:00:00-06:00', end=None, **extra):
    timed = len(start) > 10
    begins = {'dateTime': start} if timed else {'date': start}
    ends = {'dateTime' if timed else 'date': end} if end else {}
    return {'summary': summary, 'status': 'confirmed', 'start': begins, 'end': ends, **MINE, **extra}


class ReadingTests(GmailPilotTest):
    def detect(self, **answer):
        fields = {'kind': 'reply', 'due_date': None, 'amount': None, 'currency': None, 'summary': None, **answer}
        self.openai_post.return_value = model_answer(**fields)
        return reader.detect(text.parse(gmail_message()), DAY)

    def test_the_search_no_longer_asks_for_bill_words(self):
        self.assertNotIn('factura', sync.FILTER)
        for kept_out in ('-category:promotions', '-category:social', '-in:spam', '-in:trash', '-in:sent'):
            self.assertIn(kept_out, sync.FILTER)

    def test_new_kinds_are_fixed_and_fit_the_column(self):
        for kind in ('reply', 'appointment', 'delivery', 'money'):
            self.assertEqual(self.detect(kind=kind)['kind'], kind)
        self.assertIsNone(self.detect(kind='call_this_number'))
        self.assertEqual(set(reader.KINDS), set(MailNeed.Kind.values))
        self.assertEqual(set(reader.KINDS), set(sync.WORDS))
        self.assertLessEqual(max(map(len, reader.KINDS)), MailNeed._meta.get_field('kind').max_length)

    def test_a_past_date_is_when_it_happened_not_a_reason_to_drop_it(self):
        for kind in ('reply', 'delivery', 'money'):
            self.assertEqual(self.detect(kind=kind, due_date='2026-11-20'), {
                'kind': kind, 'due_date': None, 'amount': None, 'currency': None, 'summary': ''})
        for kind in ('payment', 'appointment', 'deadline'):
            self.assertIsNone(self.detect(kind=kind, due_date='2026-11-20'))
        self.assertEqual(self.detect(kind='delivery', due_date='2026-11-25')['due_date'], date(2026, 11, 25))

    def test_a_summary_carries_no_number_link_or_address(self):
        found = self.detect(summary='Llama al +58 412-555 0199 o entra a evil.example/pago y escribe a a@evil.example')
        for planted in ('412', '0199', 'evil.example', '@'):
            self.assertNotIn(planted, found['summary'])
        self.assertTrue(any(ch.isalpha() for ch in found['summary']))
        self.assertFalse(any(ch.isdigit() for ch in found['summary']))

    def test_hidden_joiners_and_other_dots_do_not_save_a_link(self):
        joiner, selector = chr(0x200D), chr(0xFE0F)
        for planted in (f'confio-soporte.{joiner}com', f'confio-soporte{joiner}.com', f'confio-soporte.{selector}com',
                        f'ayuda@{joiner}gmail.{joiner}com', 'evil' + chr(0x06D4) + 'com', 'evil' + chr(0xB7) + 'com',
                        'evil.' + chr(0x302A) + 'com', 'evil' + chr(0x0336) + '.com', '@soporte_banco'):
            for shown in (self.detect(summary=f'Entra a {planted} ya')['summary'],
                          text.strict_line(f'Entra a {planted} ya', 80, numbers=True)):
                self.assertEqual(shown.replace('[enlace]', '').replace('[correo]', '').split(), ['Entra', 'a', 'ya'])

    def test_circled_superscript_and_roman_digits_are_numbers_too(self):
        found = self.detect(summary='Llama al ④①② ⑤⑤⑤ ⓪①⑨⑨ o al ⁴¹² ⁵⁵⁵ o al ４１２５５５ ya')['summary']
        self.assertEqual(found, 'Llama al o al o al ya')

    def test_a_number_in_pieces_does_not_ride_in_a_title(self):
        for planted in ('7001–2345', '7001‑2345', '7001|2345', '7_0_0_1_2_3', '70 01 y 23 45 y 67 89',
                        '7⃣0⃣0⃣1⃣2⃣', '1234 ext 5678'):
            shown = text.strict_line(f'Llama {planted}', 80, numbers=True)
            self.assertLess(sum(ch.isdigit() for ch in shown), 5, planted)
        self.assertEqual(text.strict_line('Reunión N° 3 a las 15:00, señor Ñandú', 80, numbers=True),
                         'Reunión N° 3 a las 15:00, señor Ñandú')

    def test_a_summary_is_one_short_line(self):
        found = self.detect(summary='palabra ' * 80 + '\nsegunda línea')
        self.assertLessEqual(len(found['summary']), reader.MAX_SUMMARY + 1)
        self.assertNotIn('\n', found['summary'])
        self.assertEqual(self.detect(summary=['x'])['summary'], '')

    def run_sync(self, need, message, **row):
        row = self.connect(**row)
        self.box.search.return_value = ['abc123']
        self.box.message.return_value = message
        with self.with_box(), patch.object(reader, 'detect', return_value=need) as detect:
            sync.sync(row.pk)
        return row, detect

    def recent(self, days=0):
        message = gmail_message()
        message['internalDate'] = str(int((timezone.now() - timedelta(days=days)).timestamp() * 1000))
        return message

    def test_the_summary_is_stored_sealed_and_shown(self):
        need = {'kind': 'reply', 'due_date': None, 'amount': None, 'currency': None, 'summary': 'RESUMEN-PRIVADO'}
        row, _detect = self.run_sync(need, self.recent())
        self.assertNotIn('RESUMEN-PRIVADO', row.needs.get().sealed)
        shown = service.overview(self.user, self.account, PERSONAL)['needs']
        self.assertEqual(shown[0]['summary'], 'RESUMEN-PRIVADO')

    def test_an_old_letter_without_a_date_is_not_news(self):
        need = {'kind': 'reply', 'due_date': None, 'amount': None, 'currency': None, 'summary': ''}
        self.assertFalse(self.run_sync(need, self.recent(days=10))[0].needs.exists())

    def test_an_old_mail_with_a_date_ahead_still_counts(self):
        need = {'kind': 'payment', 'due_date': timezone.now().date() + timedelta(days=5), 'amount': None,
                'currency': None, 'summary': ''}
        self.assertTrue(self.run_sync(need, self.recent(days=10))[0].needs.exists())


class OlderConsentTests(GmailPilotTest):
    """Connected when the text promised bills only: nothing is read until they accept today's."""

    def test_not_synced_not_noticed_not_shown(self):
        row = self.connect(consent_version=1, can_calendar=True)
        MailNeed.objects.create(connection=row, source_key='a', kind='payment', sealed=crypto.seal({'id': 'a'}),
                                due_date=DAY)
        self.assertEqual(sync.due_connection_ids(), [])
        self.box.search.side_effect = AssertionError('read under an older consent')
        with self.with_box(), patch.object(sync, 'events_today') as counted:
            sync.sync(row.pk)
            self.assertEqual(sync.nudge(MORNING), 0)
        counted.assert_not_called()
        shown = service.overview(self.user, self.account, PERSONAL)
        self.assertTrue(shown['needs_reconnect'] and shown['consent_outdated'])
        self.assertEqual(shown['needs'], [])
        self.refused('reconnect', service.agenda, self.user)
        # Asked for directly, past the app: still no call to Google, for mail or calendar.
        with patch.object(client, 'access_token', side_effect=AssertionError('token used')):
            self.refused('reconnect', session.mailbox, row)
            self.refused('reconnect', session.calendar, row)
            with patch.object(reader, 'plan_search', return_value=''):
                self.refused('reconnect', service.ask, self.user, '¿qué vence?')

    def test_an_app_with_the_old_consent_text_cannot_connect(self):
        self.refused('consent', oauth.start, self.user, 1)

    def test_current_consent_is_not_outdated(self):
        self.connect()
        self.assertFalse(service.overview(self.user, self.account, PERSONAL)['consent_outdated'])


class CalendarReadTests(GmailPilotTest):
    NOW = datetime(2026, 11, 23, 14, tzinfo=tz.utc)

    def events(self, *items, days=1, zone='America/La_Paz', now=None, pages=None):
        answers = pages or [{'timeZone': zone, 'items': list(items)}]
        with patch.object(client, '_call', side_effect=answers) as call:
            found = client.Calendar('access').events(now or self.NOW, days, -6)
        return found, call

    def test_asks_for_few_fields_of_the_primary_calendar(self):
        _found, call = self.events()
        params = call.call_args.kwargs['params']
        self.assertEqual(params['singleEvents'], 'true')
        self.assertLess(params['timeMin'], self.NOW.isoformat())
        self.assertGreater(params['timeMax'], (self.NOW + timedelta(days=1)).isoformat())
        for private in ('description', 'location', 'email', 'displayName', 'hangoutLink', 'creator'):
            self.assertNotIn(private, params['fields'])
        self.assertEqual(params['maxAttendees'], 1)
        self.assertTrue(call.call_args.args[1].endswith('/calendars/primary/events'))

    def test_only_what_the_person_made_or_said_yes_to(self):
        found, _call = self.events(
            event('Mío'),
            event('Aceptado', organizer={}, attendees=[{'self': True, 'responseStatus': 'accepted'}]),
            event('Quizás', organizer={}, attendees=[{'self': True, 'responseStatus': 'tentative'}]),
            event('Mío con invitados', attendees=[{'responseStatus': 'needsAction'}]),
            event('Sin responder', organizer={}, attendees=[{'self': True, 'responseStatus': 'needsAction'}]),
            event('Rechazado', attendees=[{'self': True, 'responseStatus': 'declined'}]),
            event('A otra dirección', organizer={}, attendees=[{'responseStatus': 'accepted'}]),
            # What the field mask really returns for someone else's event: an empty organizer, or none.
            event('De otro, sin invitados', organizer={}),
            {'summary': 'De otro, sin organizador', 'status': 'confirmed',
             'start': {'dateTime': '2026-11-23T15:00:00-06:00'}},
            event('Cancelado', status='cancelled'),
            event('Cumpleaños', eventType='birthday'),
            event('Vuelo sacado de un correo', eventType='fromGmail'),
            'not-an-event', event('Sin fecha', start='nunca-jamás'))
        self.assertEqual([e['title'] for e in found], ['Mío', 'Aceptado', 'Quizás', 'Mío con invitados'])

    def test_the_day_is_the_calendars_own(self):
        # 14:00 UTC on the 23rd is already the 24th in Tokyo and still the 23rd in La Paz.
        late = event('Tarde', start='2026-11-24T03:30:00Z')  # 23:30 on the 23rd in La Paz, 12:30 on the 24th in Tokyo
        found, _call = self.events(late)
        self.assertEqual([(e['title'], e['day']) for e in found], [('Tarde', DAY)])
        found, _call = self.events(late, zone='Asia/Tokyo', now=datetime(2026, 11, 23, 16, tzinfo=tz.utc))
        self.assertEqual([(e['title'], e['day']) for e in found], [('Tarde', date(2026, 11, 24))])

    def test_an_unknown_zone_falls_back_to_the_offset(self):
        found, _call = self.events(event('Tarde', start='2026-11-24T05:30:00Z'),
                                   event('Mañana', start='2026-11-24T06:30:00Z'), zone='No/Such_Zone')
        self.assertEqual([e['title'] for e in found], ['Tarde'])

    def test_a_timed_event_still_running_counts_today(self):
        found, _call = self.events(
            event('Congreso', start='2026-11-22T09:00:00-04:00', end='2026-11-24T18:00:00-04:00'),
            event('Ayer', start='2026-11-22T09:00:00-04:00', end='2026-11-22T10:00:00-04:00'),
            event('Hasta la medianoche', start='2026-11-22T22:00:00-04:00', end='2026-11-23T00:00:00-04:00'))
        self.assertEqual([(e['title'], e['day']) for e in found], [('Congreso', DAY)])

    def test_all_day_events_cover_their_days(self):
        found, _call = self.events(
            event('Hoy', start='2026-11-23', end='2026-11-24'),
            event('Viaje largo', start='2026-11-20', end='2026-11-26'),
            event('Ayer', start='2026-11-22', end='2026-11-23'),
            event('Sin fin', start='2026-11-23'))
        self.assertEqual([e['title'] for e in found], ['Hoy', 'Viaje largo', 'Sin fin'])
        self.assertTrue(all(e['all_day'] and e['day'] == DAY for e in found))

    def test_a_flood_of_invitations_does_not_hide_real_events(self):
        spam = [event(f'Spam {n}', organizer={}, attendees=[{'self': True, 'responseStatus': 'needsAction'}])
                for n in range(250)]
        found, call = self.events(pages=[
            {'timeZone': 'America/La_Paz', 'items': spam, 'nextPageToken': 'next'},
            {'items': [event('Real')]}])
        self.assertEqual([e['title'] for e in found], ['Real'])
        self.assertEqual(call.call_args.kwargs['params']['pageToken'], 'next')

    def test_pages_are_bounded(self):
        page = {'timeZone': 'America/La_Paz', 'items': [], 'nextPageToken': 'again'}
        _found, call = self.events(pages=[page] * 10)
        self.assertEqual(call.call_count, client.Calendar.MAX_PAGES)

    def test_refusals_say_why(self):
        self.refused('not_connected', session.calendar, None)
        row = self.connect(can_calendar=False)
        self.refused('no_calendar', session.calendar, row)
        row.can_calendar, row.status = True, GmailConnection.Status.EXPIRED
        self.refused('reconnect', session.calendar, row)


class ConnectCalendarTests(GmailPilotTest):
    def save(self, scope):
        attempt = type('Attempt', (), {'consent_version': config.CONSENT_VERSION})()
        row, _stale = oauth._save(self.user, attempt, {'refresh_token': 'r', 'scope': scope}, 'owner@gmail.example')
        return row

    def test_calendar_permission_is_optional_and_recorded(self):
        self.assertFalse(self.save(config.READ_SCOPE).can_calendar)
        row = self.save(f'{config.READ_SCOPE} {config.CALENDAR_SCOPE}')
        self.assertTrue(row.can_calendar)
        self.assertFalse(self.save(config.READ_SCOPE).can_calendar)

    def test_another_mailbox_erases_the_notices_of_the_previous_one(self):
        self.connect()
        Notification.objects.create(user=self.user, notification_type='SYSTEM', title='t', message='2 pagos',
                                    data={'type': oauth.NOTICE_TYPE})
        attempt = type('Attempt', (), {'consent_version': config.CONSENT_VERSION})()
        oauth._save(self.user, attempt, {'refresh_token': 'r', 'scope': config.READ_SCOPE}, 'otra@gmail.example')
        self.assertFalse(Notification.objects.exists())

    def test_the_notice_is_written_with_the_type_disconnect_erases(self):
        self.notify_patch_off()
        with patch('notifications.utils.create_notification') as create:
            sync._notify(self.user, sync.RECONNECT)
        self.assertEqual(create.call_args.kwargs['data'], {'type': oauth.NOTICE_TYPE})
        with patch('notifications.utils.create_notification', side_effect=SoftTimeLimitExceeded()):
            with self.assertRaises(SoftTimeLimitExceeded):
                sync._notify(self.user, sync.RECONNECT)

    def notify_patch_off(self):
        patch.stopall()

    def test_disconnect_erases_the_notices_that_counted_mail_and_events(self):
        row = self.connect()
        for kind, user in (('assistant_mail', self.user), ('other', self.user), ('assistant_mail', self.other)):
            Notification.objects.create(user=user, notification_type='SYSTEM', title='t', message='2 pagos',
                                        data={'type': kind})
        with patch.object(client, 'revoke', return_value=True):
            oauth.disconnect(row)
        left = sorted(Notification.objects.values_list('user_id', 'data__type'))
        self.assertEqual(left, sorted([(self.user.pk, 'other'), (self.other.pk, 'assistant_mail')]))


class NoticeTests(GmailPilotTest):
    def need(self, row, key, kind, **fields):
        return MailNeed.objects.create(connection=row, source_key=key, kind=kind, sealed=crypto.seal({'id': key}),
                                       **fields)

    def nudge(self, now, events=None):
        failing = isinstance(events, BaseException)
        with patch.object(sync, 'events_today', side_effect=events if failing else None,
                          return_value=None if failing else events) as counted:
            sent = sync.nudge(now)
        return sent, counted

    def said(self):
        return self.notify.call_args.args[1][1]

    def test_counts_by_kind_then_calendar_and_nothing_else(self):
        row = self.connect(can_calendar=True)
        self.need(row, 'a', 'payment', due_date=DAY)
        self.need(row, 'b', 'payment', due_date=DAY + timedelta(days=1))
        MailNeed.objects.filter(pk=self.need(row, 'c', 'reply').pk).update(created_at=MORNING - timedelta(hours=2))
        sent, _counted = self.nudge(MORNING, events=3)
        self.assertEqual(sent, 1)
        self.assertEqual(self.said(), 'Tienes por atender: 2 pagos y 1 correo por responder. '
                                      f'Hoy en tu calendario: 3 eventos. {sync.WHERE}')

    def test_calendar_alone_is_a_notice(self):
        self.connect(can_calendar=True)
        self.assertEqual(self.nudge(MORNING, events=1)[0], 1)
        self.assertEqual(self.said(), f'Hoy en tu calendario: 1 evento. {sync.WHERE}')

    def test_nothing_today_is_no_notice_and_one_calendar_call(self):
        row = self.connect(can_calendar=True)
        sent, counted = self.nudge(MORNING, events=0)
        self.assertEqual((sent, counted.call_count), (0, 1))
        self.notify.assert_not_called()
        sent, counted = self.nudge(MORNING + timedelta(minutes=15), events=5)
        self.assertEqual((sent, counted.call_count), (0, 0))
        row.refresh_from_db()
        self.assertEqual(row.calendar_checked_on, DAY)

    def test_the_calendar_is_counted_in_the_morning_only(self):
        self.connect(can_calendar=True)
        sent, counted = self.nudge(AFTERNOON, events=4)
        self.assertEqual((sent, counted.call_count), (0, 0))

    def test_no_calendar_permission_no_calendar_call(self):
        row = self.connect(can_calendar=False)
        self.need(row, 'a', 'trip', due_date=DAY)
        sent, counted = self.nudge(MORNING, events=9)
        self.assertEqual((sent, counted.call_count), (1, 0))
        self.assertEqual(self.said(), f'Tienes por atender: 1 viaje. {sync.WHERE}')

    def test_a_failed_calendar_holds_the_notice_then_goes_without_it(self):
        row = self.connect(can_calendar=True)
        self.need(row, 'a', 'delivery', due_date=DAY)
        with self.assertLogs(sync.logger, 'WARNING') as logs:
            self.assertEqual(self.nudge(MORNING, events=RuntimeError('TITULO-PRIVADO'))[0], 0)
        self.assertNotIn('TITULO-PRIVADO', '\n'.join(logs.output))
        self.notify.assert_not_called()
        with self.assertLogs(sync.logger, 'WARNING'):
            self.assertEqual(self.nudge(LAST_MORNING_HOUR, events=RuntimeError('x'))[0], 1)
        self.assertEqual(self.said(), f'Tienes por atender: 1 entrega. {sync.WHERE}')
        row.refresh_from_db()
        self.assertIsNone(row.calendar_checked_on)

    def test_a_held_notice_goes_whole_on_the_next_sweep(self):
        row = self.connect(can_calendar=True)
        self.need(row, 'a', 'delivery', due_date=DAY)
        with self.assertLogs(sync.logger, 'WARNING'):
            self.nudge(MORNING, events=RuntimeError('x'))
        self.assertEqual(self.nudge(MORNING + timedelta(minutes=15), events=2)[0], 1)
        self.assertEqual(self.said(), f'Tienes por atender: 1 entrega. Hoy en tu calendario: 2 eventos. {sync.WHERE}')

    def test_the_sweeps_time_limit_is_not_swallowed(self):
        self.connect(can_calendar=True)
        with self.assertRaises(SoftTimeLimitExceeded):
            self.nudge(MORNING, events=SoftTimeLimitExceeded())

    def test_slow_calendars_do_not_take_the_whole_sweep(self):
        self.connect(can_calendar=True)
        self.connect(user=self.other, can_calendar=True)
        # The first count takes longer than the whole budget: the second person waits for the next sweep.
        clock = iter([0, sync.CALENDAR_SECONDS + 1])
        with patch.object(sync.time, 'monotonic', side_effect=lambda: next(clock)):
            sent, counted = self.nudge(MORNING, events=1)
        self.assertEqual((sent, counted.call_count), (1, 1))
        self.assertEqual(self.nudge(MORNING + timedelta(minutes=15), events=1)[0], 1)

    def test_a_calendar_that_keeps_failing_stops_holding_the_mail(self):
        row = self.connect(can_calendar=True)
        self.need(row, 'a', 'payment', due_date=DAY)
        with self.assertLogs(sync.logger, 'WARNING'):
            sent = [self.nudge(MORNING + timedelta(minutes=15 * n), events=RuntimeError('x'))[0]
                    for n in range(sync.CALENDAR_TRIES)]
        self.assertEqual(sent, [0] * (sync.CALENDAR_TRIES - 1) + [1])

    def test_undated_since_yesterday_began_also_off_the_hour(self):
        row = self.connect()
        now = MORNING + timedelta(minutes=47)
        midnight = datetime(2026, 11, 22, 6, tzinfo=tz.utc)  # yesterday 00:00 at UTC-6
        MailNeed.objects.filter(pk=self.need(row, 'in', 'reply').pk).update(created_at=midnight + timedelta(minutes=1))
        MailNeed.objects.filter(pk=self.need(row, 'out', 'money').pk).update(created_at=midnight - timedelta(minutes=1))
        self.assertEqual(self.nudge(now)[0], 1)
        self.assertEqual(self.said(), f'Tienes por atender: 1 correo por responder. {sync.WHERE}')

    def test_a_grant_that_ended_at_the_calendar_says_reconnect(self):
        self.connect(can_calendar=True)
        ended = MailRefused('reconnect', 'x')
        ended.ended_now = True
        self.assertEqual(self.nudge(MORNING, events=ended)[0], 0)
        self.notify.assert_called_once_with(self.user, sync.RECONNECT)
        # A sync saw it end first and already said so: not twice.
        self.assertEqual(self.nudge(MORNING + timedelta(minutes=15), events=MailRefused('reconnect', 'x'))[0], 0)
        self.assertEqual(self.notify.call_count, 1)

    def test_an_expired_connection_gets_no_notice_for_a_list_it_cannot_open(self):
        row = self.connect(status=GmailConnection.Status.EXPIRED)
        self.need(row, 'a', 'payment', due_date=DAY)
        self.assertEqual(self.nudge(MORNING)[0], 0)

    def test_after_the_notice_only_what_is_due_today_and_only_once(self):
        row = self.connect(can_calendar=True)
        self.assertEqual(self.nudge(MORNING, events=2)[0], 1)
        self.need(row, 'a', 'reply')
        self.need(row, 'b', 'payment', due_date=DAY + timedelta(days=1))
        self.assertEqual(self.nudge(AFTERNOON, events=2)[0], 0)
        self.need(row, 'c', 'payment', due_date=DAY)
        sent, counted = self.nudge(AFTERNOON, events=2)
        self.assertEqual((sent, counted.call_count), (1, 0))
        self.assertEqual(self.said(), f'Tienes por atender: 1 pago. {sync.WHERE}')
        self.need(row, 'd', 'deadline', due_date=DAY)
        self.assertEqual(self.nudge(AFTERNOON + timedelta(hours=1))[0], 0)
        self.assertEqual(self.notify.call_count, 2)

    def test_what_waited_is_in_tomorrows_notice(self):
        row = self.connect()
        self.need(row, 'x', 'payment', due_date=DAY)
        self.assertEqual(self.nudge(MORNING)[0], 1)
        MailNeed.objects.filter(pk=self.need(row, 'a', 'reply').pk).update(created_at=MORNING + timedelta(minutes=1))
        self.need(row, 'b', 'payment', due_date=DAY + timedelta(days=1))
        # Tomorrow's sweep runs late: more than 24 hours after the reply arrived.
        late = MORNING + timedelta(days=1, hours=3)
        self.assertEqual(self.nudge(late)[0], 1)
        self.assertEqual(self.said(), f'Tienes por atender: 1 pago y 1 correo por responder. {sync.WHERE}')

    def test_none_at_night_on_the_persons_clock(self):
        row = self.connect(can_calendar=True)
        self.need(row, 'a', 'money', due_date=DAY)
        night = datetime(2026, 11, 23, 9, tzinfo=tz.utc)  # 03:00 at UTC-6
        self.assertEqual(self.nudge(night, events=2)[0], 0)
        # The same instant is 10:00 in Spain.
        with patch.object(config, 'utc_offset', return_value=1):
            self.assertEqual(self.nudge(night, events=2)[0], 1)

    def test_dismissed_old_and_far_needs_are_not_counted(self):
        row = self.connect()
        self.need(row, 'a', 'payment', due_date=DAY, dismissed=True)
        self.need(row, 'b', 'payment', due_date=DAY + timedelta(days=9))
        MailNeed.objects.filter(pk=self.need(row, 'c', 'reply').pk).update(created_at=MORNING - timedelta(days=3))
        self.assertEqual(self.nudge(MORNING)[0], 0)

    def test_the_count_returns_a_number_only(self):
        row = self.connect(can_calendar=True)
        with patch.object(session, 'calendar') as opened:
            opened.return_value.events.return_value = [{'title': 'TITULO-PRIVADO'}] * 2
            self.assertEqual(sync.events_today(row, MORNING, -6), 2)
        opened.return_value.events.assert_called_once_with(MORNING, 1, -6)

    def test_every_word_of_the_notice_is_ours_and_counts_are_capped(self):
        title, body = sync.notice({kind: 2 for kind in reader.KINDS}, 2)
        self.assertEqual(title, 'Confío IA')
        for words in (*sync.WORDS.values(), sync.EVENTS):
            self.assertIn(f'2 {words[1]}', body)
        self.assertEqual(sync.notice({'reply': 150}, 0)[1], f'Tienes por atender: más de 9 correos por responder. {sync.WHERE}')


class AgendaTests(GmailPilotTest):
    def agenda(self, items):
        with patch.object(session, 'calendar') as opened:
            opened.return_value.events.return_value = items
            return service.agenda(self.user), opened

    def test_titles_are_shown_trimmed_without_links_or_long_numbers(self):
        self.connect(can_calendar=True)
        found, opened = self.agenda([
            {'title': 'Pagar en evil.example/ya ' + 'x' * 200, 'day': DAY, 'starts_at': None, 'all_day': True},
            {'title': 'Sala 3 a las 15:00, soporte +58 412 555 0199', 'day': DAY, 'starts_at': MORNING,
             'all_day': False},
            {'title': '', 'day': DAY, 'starts_at': MORNING, 'all_day': False}])
        self.assertNotIn('evil.example', found[0]['title'])
        self.assertLessEqual(len(found[0]['title']), service.MAX_EVENT_TITLE + 1)
        # Eight digits or more in one title: all of them go, the room number too.
        self.assertEqual(found[1]['title'], 'Sala a las soporte +')
        self.assertEqual(found[2]['title'], 'Sin título')
        self.assertEqual(opened.return_value.events.call_args.args[1], service.AGENDA_DAYS)

    def test_no_model_sees_the_calendar(self):
        self.connect(can_calendar=True)
        self.agenda([])
        self.openai_post.assert_not_called()

    def test_refused_without_connection_or_permission(self):
        self.refused('not_connected', service.agenda, self.user)
        self.connect(can_calendar=False)
        self.refused('no_calendar', service.agenda, self.user)

    def run_mutation(self, user, account_type='personal'):
        info_context = type('Request', (), {'user': user})()
        models = (user, self.account, None, {'account_type': account_type})
        with patch.object(schema, 'get_context_models', return_value=models), \
                patch('graphql_jwt.decorators.login_required', lambda f: f):
            import graphene
            built = graphene.Schema(query=schema.Query, mutation=schema.Mutation)
            return Client(built).execute(
                'mutation ShowAssistantMailAgenda { showAssistantMailAgenda '
                '{ success errorCode events { title day startsAt allDay } } }',
                context_value=info_context)

    def test_through_the_schema_for_a_tester_only(self):
        self.connect(can_calendar=True)
        items = [{'title': 'Dentista', 'day': DAY, 'starts_at': MORNING, 'all_day': False}]
        with patch.object(session, 'calendar') as opened:
            opened.return_value.events.return_value = items
            answer = self.run_mutation(self.user)['data']['showAssistantMailAgenda']
            self.assertEqual(answer, {'success': True, 'errorCode': None, 'events': [
                {'title': 'Dentista', 'day': '2026-11-23', 'startsAt': '2026-11-23T14:00:00+00:00', 'allDay': False}]})
            business = self.run_mutation(self.user, 'business')['data']['showAssistantMailAgenda']
            self.assertEqual((business['success'], business['errorCode'], business['events']),
                             (False, 'unavailable', None))
            with self.settings(GMAIL_PILOT_USER_IDS=str(self.other.pk)):
                gone = self.run_mutation(self.user)['data']['showAssistantMailAgenda']
            self.assertEqual((gone['success'], gone['errorCode']), (False, 'unavailable'))

    def test_operation_is_redactable_and_takes_no_account(self):
        self.assertIn('AssistantMail', schema.ShowAssistantMailAgenda.__name__)
        self.assertEqual(list(schema.ShowAssistantMailAgenda._meta.arguments), [])
