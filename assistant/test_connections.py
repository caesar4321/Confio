"""Discovery, the waitlist and the 100 places (assistant/connections.py)."""
from datetime import timedelta
from unittest import mock

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib import messages
from django.contrib.admin.models import LogEntry
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from assistant import connections, connections_admin
from assistant.connections_models import AssistantConnectionRequest as Request
from assistant.gmail import config, sync
from assistant.gmail.models import GmailConnection

PERSONAL = {'account_type': 'personal'}
OFF = dict(CONFIO_ASSISTANT_ENABLED=True, ASSISTANT_CONNECTIONS_DISCOVERY_ENABLED=True,
           GMAIL_OAUTH_CLIENT_ID='client', GMAIL_OAUTH_CLIENT_SECRET='secret',
           GMAIL_OAUTH_REDIRECT_URI='https://example.test/cb', GMAIL_TOKEN_KEY='k', GMAIL_PILOT_USER_IDS='')
ON = {**OFF, 'GMAIL_PILOT_USER_IDS': '999999901'}


@override_settings(**OFF)
class ConnectionsTests(TestCase):
    def setUp(self):
        patches = [mock.patch('security.utils.check_user_banned', return_value=(False, None)),
                   mock.patch('assistant.gmail.client.revoke', return_value=True),
                   mock.patch.object(connections, '_notify')]
        self.banned, self.revoke, self.notify = [patch.start() for patch in patches]
        self.addCleanup(mock.patch.stopall)
        self.user = self.person('ana', 'ana@gmail.com')

    def person(self, name, email=None):
        return get_user_model().objects.create_user(
            username=f'cx_{name}', email=email or f'{name}@example.com', password='x', firebase_uid=f'cx-{name}')

    def see(self, user=None, jwt=PERSONAL):
        return connections.overview(user or self.user, object(), jwt)

    def say(self, wants=True, email='', user=None, feature='gmail'):
        connections.answer(user or self.user, object(), PERSONAL, feature, wants, email)
        return Request.objects.get(user=user or self.user, feature=feature)

    def invite(self, *rows):
        ids = [row.pk for row in rows]
        connections.reserve(ids)
        return connections.give(ids)

    def connected(self, user):
        now = timezone.now()
        return GmailConnection.objects.create(user=user, consent_version=1, connected_at=now, next_sync_at=now)

    def test_switch_off_shows_and_stores_nothing(self):
        with override_settings(ASSISTANT_CONNECTIONS_DISCOVERY_ENABLED=False):
            self.assertIsNone(self.see())
            with self.assertRaises(connections.ConnectionRefused):
                self.say()
        self.assertFalse(Request.objects.exists())

    def test_business_context_gets_nothing(self):
        self.assertIsNone(self.see(jwt={'account_type': 'business', 'business_id': '1'}))
        with self.assertRaises(connections.ConnectionRefused):
            connections.answer(self.user, object(), {'account_type': 'business'}, 'gmail', True)

    def test_soon_is_a_plain_answer_and_keeps_no_address(self):
        self.assertEqual(self.see()['gmail'], 'soon')
        row = self.say(email='other@gmail.com')
        self.assertEqual((row.answer, row.google_email), ('yes', ''))
        self.assertEqual(self.see()['gmail'], 'waiting')

    def test_leaving_the_list_and_coming_back(self):
        self.say()
        self.assertEqual(self.say(wants=False).answer, 'no')
        self.assertEqual(self.see()['gmail'], 'soon')
        self.assertTrue(self.see()['gmail_answered'])

    def test_unknown_feature_is_refused(self):
        with self.assertRaises(connections.ConnectionRefused):
            self.say(feature='bank')

    def test_calendar_waitlist(self):
        self.say(feature='calendar')
        self.assertEqual(self.see()['calendar'], 'waiting')
        self.say(feature='calendar', wants=False)
        self.assertEqual(self.see()['calendar'], 'soon')

    @override_settings(**ON)
    def test_request_needs_a_valid_google_address(self):
        self.assertEqual(self.see()['gmail'], 'request')
        for bad in ('', 'nope', 'a@b', 'x' * 260 + '@gmail.com', 'ana@icloud.com', 'x@privaterelay.appleid.com',
                    'a@hotmail.es', 'a@yahoo.com.ar', 'a@live.com.mx', 'a@proton.me', 'a@empresa.com', 'a@gmail.com.ar',
                    'a@notgmail.com'):
            with self.assertRaises(connections.ConnectionRefused):
                self.say(email=bad)
        self.assertEqual(self.say(email='second@gmail.com').google_email, 'second@gmail.com')
        self.assertEqual(self.see()['google_email'], 'second@gmail.com')

    def test_an_early_yes_chooses_the_account_when_places_open(self):
        row = self.say()  # signs in with Gmail: still never used without asking
        with override_settings(**ON):
            seen = self.see()
            self.assertEqual((seen['gmail'], seen['gmail_answered']), ('request', False))
            self.assertEqual(seen['suggested_email'], 'ana@gmail.com')
            self.assertEqual(connections.reserve([row.pk])['skipped'], 1)

    @override_settings(**ON)
    def test_reserved_is_frozen_and_has_no_access_until_given(self):
        row = self.say(email='old@gmail.com')
        self.assertEqual(connections.reserve([row.pk])['reserved'], 1)
        self.assertFalse(config.user_allowed(self.user))
        self.notify.assert_not_called()
        self.assertEqual(self.say(email='new@gmail.com').google_email, 'old@gmail.com')
        self.assertEqual(self.see()['gmail'], 'waiting')
        self.assertEqual(connections.give([row.pk])['given'], 1)
        self.assertTrue(config.user_allowed(self.user))
        self.assertEqual(self.see()['google_email'], 'old@gmail.com')
        self.notify.assert_called_once()

    @override_settings(**ON)
    def test_giving_without_reserving_does_nothing(self):
        row = self.say(email='ana@gmail.com')
        self.assertEqual(connections.give([row.pk])['skipped'], 1)
        self.assertFalse(config.user_allowed(self.user))

    @override_settings(**ON)
    def test_never_the_sign_in_gmail_for_someone_invited_with_another(self):
        row = self.say(email='second@gmail.com')
        self.invite(row)
        connection = self.connected(self.user)
        sync.cleanup()
        self.assertEqual(Request.objects.get().google_email, '')
        connection.delete()  # they disconnected
        seen = self.see()
        self.assertEqual((seen['gmail'], seen['google_email']), ('invited', None))

    @override_settings(**ON)
    def test_leaving_after_an_invitation_really_leaves(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        used = connections.seats_used()
        left = self.say(wants=False)
        self.assertEqual((left.answer, left.google_email), ('no', ''))
        self.assertIsNotNone(left.removed_at)
        self.assertFalse(config.user_allowed(self.user))
        self.assertEqual(self.see()['gmail'], 'left')
        self.assertEqual(connections.seats_used(), used)
        self.assertEqual(connections.reserve([row.pk])['skipped'], 1)

    @override_settings(**ON)
    def test_a_removed_person_can_leave_the_list(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        connections.remove([row.pk])
        self.assertEqual(self.see()['gmail'], 'waiting')
        self.say(wants=False)
        self.assertEqual(self.see()['gmail'], 'left')

    @override_settings(**ON)
    def test_the_switch_off_invitee_can_leave_the_list(self):
        self.invite(self.say(email='ana@gmail.com'))
        with override_settings(GMAIL_PILOT_USER_IDS=''):
            self.assertEqual(self.say(wants=False).answer, 'no')
            self.assertEqual(self.see()['gmail'], 'left')

    def test_no_places_while_the_pilot_is_off(self):
        row = self.say()
        self.assertEqual(connections.reserve([row.pk])['skipped'], 1)
        self.assertEqual(connections.give([row.pk])['skipped'], 1)
        self.assertIsNone(Request.objects.get().invited_at)

    @override_settings(**ON)
    def test_the_switch_off_beats_an_invitation(self):
        self.invite(self.say(email='ana@gmail.com'))
        with override_settings(GMAIL_PILOT_USER_IDS=''):
            self.assertEqual(config.tester_ids(), set())
            self.assertFalse(config.user_allowed(self.user))
            self.assertEqual(self.see()['gmail'], 'waiting')
            self.connected(self.user)
            self.assertEqual(self.see()['gmail'], 'paused')

    @override_settings(**ON)
    def test_never_past_one_hundred_and_first_asked_first(self):
        rows = [self.say(email=f'p{n}@gmail.com', user=self.person(f'p{n}')) for n in range(3)]
        with mock.patch.object(config, 'MAX_TESTERS', 3):
            self.assertEqual(connections.reserve([r.pk for r in reversed(rows)]),
                             {'reserved': 2, 'skipped': 0, 'no_seat': 1})
            self.assertIsNone(Request.objects.get(pk=rows[2].pk).invited_at)
            self.assertEqual(self.see(rows[2].user)['gmail'], 'waiting_full')
            self.assertEqual(self.see()['gmail'], 'full')
            self.assertEqual(self.say(email='ana@gmail.com').google_email, '')  # full: just "avísame"
            self.assertEqual(self.see()['gmail'], 'waiting_full')
            connections.forget_addresses()
            self.assertEqual(Request.objects.get(pk=rows[2].pk).google_email, '')
            self.assertNotEqual(Request.objects.get(pk=rows[0].pk).google_email, '')

    @override_settings(**ON, GMAIL_PILOT_FULL=True)
    def test_the_owner_can_say_google_is_full(self):
        self.assertEqual(self.see()['gmail'], 'full')
        self.assertEqual(self.say(email='ana@gmail.com').google_email, '')

    @override_settings(**ON)
    def test_a_new_configured_account_does_not_drop_who_is_in(self):
        self.invite(self.say(email='ana@gmail.com'))
        with override_settings(GMAIL_PILOT_USER_IDS='999999901,999999902'), mock.patch.object(config, 'MAX_TESTERS', 2):
            self.assertTrue(config.user_allowed(self.user))

    @override_settings(**ON)
    def test_a_removed_place_stays_spent_and_loses_the_connection(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        used = connections.seats_used()
        self.connected(self.user)
        self.assertEqual(connections.remove([row.pk]), 1)
        self.assertFalse(GmailConnection.objects.exists())
        self.assertEqual(connections.seats_used(), used)
        self.assertFalse(config.user_allowed(self.user))
        self.assertEqual(Request.objects.get().google_email, '')

    @override_settings(**ON)
    def test_the_sweep_erases_a_connection_that_outlived_its_place(self):
        self.invite(self.say(email='ana@gmail.com'))
        self.connected(self.user)
        self.say(wants=False)
        sync.cleanup()
        self.assertFalse(GmailConnection.objects.exists())

    @override_settings(**ON)
    def test_the_sweep_catches_a_connect_inside_the_removal(self):
        self.invite(self.say(email='ana@gmail.com'))
        Request.objects.update(removed_at=timezone.now())  # its clock, before a connect that saw the old row
        self.connected(self.user)
        sync.cleanup()
        self.assertFalse(GmailConnection.objects.exists())

    @override_settings(**ON)
    def test_a_connect_that_finishes_after_removal_saves_nothing(self):
        from assistant.gmail import oauth
        from assistant.gmail.errors import MailRefused
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        connections.remove([row.pk])
        with self.assertRaises(MailRefused):
            oauth._save(self.user, mock.Mock(consent_version=1), {'refresh_token': 'r'}, 'ana@gmail.com')
        self.assertFalse(GmailConnection.objects.exists())

    @override_settings(**ON)
    def test_reserved_then_left_is_asked_again_before_any_access(self):
        row = self.say(email='old@gmail.com')
        connections.reserve([row.pk])
        self.say(wants=False)
        self.assertEqual(self.see()['gmail'], 'request')
        with self.assertRaises(connections.ConnectionRefused):
            self.say()
        row = self.say(email='new@gmail.com')
        self.assertEqual(row.google_email, 'new@gmail.com')
        self.assertEqual(connections.give([row.pk])['given'], 0)  # not before it is reserved again
        self.assertEqual(self.invite(row)['given'], 1)
        self.assertEqual(self.see()['google_email'], 'new@gmail.com')

    @override_settings(**ON)
    def test_a_typo_can_be_corrected_even_when_full(self):
        row = self.say(email='anna@gmail.com')
        connections.reserve([row.pk])
        connections.remove([row.pk])
        with override_settings(GMAIL_PILOT_FULL=True):
            self.assertEqual(self.see()['gmail'], 'request')
            self.assertEqual(self.say(email='ana@gmail.com').google_email, 'ana@gmail.com')
            self.assertEqual(self.invite(row)['given'], 1)

    @override_settings(**ON)
    def test_an_address_erased_before_google_is_never_given(self):
        row = self.say(email='ana@gmail.com')
        connections.reserve([row.pk])
        Request.objects.filter(pk=row.pk).update(google_email='')  # a ban, then lifted
        self.assertEqual(connections.give([row.pk])['given'], 0)
        self.assertEqual(self.see()['gmail'], 'request')
        self.assertEqual(self.invite(self.say(email='ana@gmail.com'))['given'], 1)

    @override_settings(**ON)
    def test_spent_places_in_the_list_can_be_told(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        self.assertEqual(connections.tell_waiting([row.pk]), 0)
        connections.remove([row.pk])
        self.assertEqual(connections.tell_waiting([row.pk]), 1)

    @override_settings(**ON)
    def test_the_switch_only_pauses_a_configured_account_connected_later(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        connections.remove([row.pk])
        connection = self.connected(self.user)
        GmailConnection.objects.filter(pk=connection.pk).update(connected_at=timezone.now() + timedelta(hours=1))
        with override_settings(GMAIL_PILOT_USER_IDS=''):
            sync.cleanup()
        self.assertTrue(GmailConnection.objects.exists())

    @override_settings(**ON)
    def test_a_configured_account_is_not_removed_here(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        with override_settings(GMAIL_PILOT_USER_IDS=f'999999901,{self.user.pk}'):
            self.assertEqual(connections.remove([row.pk]), 0)
            self.assertFalse(self.see()['gmail_answered'])

    @override_settings(**ON)
    def test_given_back_without_spending_another(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        connections.remove([row.pk])
        self.assertEqual(self.invite(row)['given'], 0)  # the bulk steps never let a removed person back in
        self.assertFalse(config.user_allowed(self.user))
        with mock.patch.object(config, 'MAX_TESTERS', 2):
            self.assertEqual(connections.give_back([row.pk])['given'], 1)
        self.assertIsNone(self.see()['google_email'])  # not held any more, and not guessed

    @override_settings(**ON)
    def test_deleting_the_person_keeps_the_place_spent(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        used = connections.seats_used()
        Request.objects.filter(pk=row.pk).update(user=None)  # what SET_NULL leaves
        self.assertEqual(connections.seats_used(), used)
        connections.forget_addresses()
        self.assertEqual(Request.objects.get().google_email, '')

    def test_the_relation_never_cascades(self):
        from django.db.models import SET_NULL
        self.assertIs(Request._meta.get_field('user').remote_field.on_delete, SET_NULL)

    @override_settings(**ON)
    def test_not_for_banned_people_or_a_no(self):
        row = self.say(wants=False)
        self.assertEqual(connections.reserve([row.pk])['skipped'], 1)
        row = self.say(email='ana@gmail.com')
        self.banned.return_value = (True, 'x')
        self.assertEqual(connections.reserve([row.pk])['skipped'], 1)

    @override_settings(**ON)
    def test_the_sweep_forgets_a_banned_persons_address(self):
        from security.models import UserBan
        self.say(email='ana@gmail.com')
        UserBan.objects.create(user=self.user, ban_type='permanent', reason='fraud', reason_details='x')
        connections.forget_addresses()
        self.assertEqual(Request.objects.get().google_email, '')

    @override_settings(**ON)
    def test_twice_is_one_notice(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        self.assertEqual(self.invite(row)['skipped'], 1)
        self.notify.assert_called_once()

    def test_waiters_can_be_told(self):
        yes, no = self.say(feature='calendar'), self.say(wants=False, user=self.person('eva'))
        self.assertEqual(connections.tell_waiting([yes.pk, no.pk]), 1)
        self.assertIsNotNone(Request.objects.get(pk=yes.pk).notified_at)

    @override_settings(**ON)
    def test_a_tester_can_still_answer_with_discovery_off(self):
        with override_settings(ASSISTANT_CONNECTIONS_DISCOVERY_ENABLED=False,
                               GMAIL_PILOT_USER_IDS=str(self.user.pk)):
            self.assertIsNotNone(self.see())
            self.assertEqual(self.say(feature='calendar').answer, 'yes')

    @override_settings(**ON)
    def test_the_sweep_forgets_with_the_account(self):
        self.say(email='second@gmail.com')
        get_user_model().objects.filter(pk=self.user.pk).update(deleted_at=timezone.now())
        connections.forget_addresses()
        self.assertEqual(Request.objects.get().google_email, '')

    def test_the_admin_cannot_free_a_place(self):
        model_admin = connections_admin.ConnectionRequestAdmin(Request, AdminSite())
        self.assertFalse(model_admin.has_delete_permission(None))
        self.assertFalse(model_admin.has_add_permission(None))

    @override_settings(**ON)
    def test_the_admin_shows_an_address_only_once_frozen(self):
        model_admin = connections_admin.ConnectionRequestAdmin(Request, AdminSite())
        row = self.say(email='ana@gmail.com')
        self.assertNotIn('@', model_admin.address(row))
        connections.reserve([row.pk])
        row.refresh_from_db()
        self.assertEqual(model_admin.address(row), 'ana@gmail.com')

    def test_schema_names_are_redacted_ones(self):
        from assistant import connections_schema
        fields = [*connections_schema.Query._meta.fields, *connections_schema.Mutation._meta.fields]
        self.assertTrue(fields and all('assistant_mail' in name for name in fields))


@override_settings(**ON)
class PilotSafeguardTests(TestCase):
    """What must hold before the first place is given."""

    setUp = ConnectionsTests.setUp
    person = ConnectionsTests.person
    say = ConnectionsTests.say
    see = ConnectionsTests.see
    invite = ConnectionsTests.invite
    connected = ConnectionsTests.connected

    def staff(self):
        if not hasattr(self, '_staff'):
            self._staff = get_user_model().objects.create_superuser(
                username='cx_admin', email='admin@example.com', password='x', firebase_uid='cx-admin')
        return self._staff

    def press(self, action, rows, extra=None):
        request = RequestFactory().post('/admin/', {ACTION_CHECKBOX_NAME: [row.pk for row in rows],
                                                    'action': action, **(extra or {})})
        request.user = self.staff()
        model_admin = connections_admin.ConnectionRequestAdmin(Request, AdminSite())
        with mock.patch.object(model_admin, 'message_user'), mock.patch.object(
                model_admin.admin_site, 'each_context', return_value={}):
            return getattr(model_admin, action)(request, Request.objects.filter(pk__in=[row.pk for row in rows]))

    def confirm(self, action, rows):
        seen = [f'{row.pk}:{connections.as_shown(Request.objects.get(pk=row.pk))}' for row in rows]
        return self.press(action, rows, {'confirmed': action, 'seen': seen})

    def test_googlemail_and_capitals_are_gmail(self):
        self.assertEqual(self.say(email='Ana@GoogleMail.com').google_email, 'Ana@GoogleMail.com')

    def test_the_first_click_changes_nothing(self):
        row = self.say(email='ana@gmail.com')
        page = self.press('reserve_place', [row])
        self.assertEqual(page.template_name, 'admin/assistant/connection_confirm.html')
        self.assertEqual((page.context_data['rows'], page.context_data['spends']), ([row], 1))
        self.assertIsNone(Request.objects.get().invited_at)

    def test_a_confirmation_for_another_action_does_not_count(self):
        row = self.say(email='ana@gmail.com')
        self.press('reserve_place', [row], {'confirmed': 'give_place', 'seen': [f'{row.pk}:0:ana@gmail.com']})
        self.assertIsNone(Request.objects.get().invited_at)

    def test_only_what_was_shown_is_reserved(self):
        shown, later = self.say(email='ana@gmail.com'), self.say(email='eva@gmail.com', user=self.person('eva'))
        self.press('reserve_place', [shown, later],
                   {'confirmed': 'reserve_place', 'seen': [f'{shown.pk}:0:ana@gmail.com']})
        self.assertIsNotNone(Request.objects.get(pk=shown.pk).invited_at)
        self.assertIsNone(Request.objects.get(pk=later.pk).invited_at)

    def test_an_address_changed_after_the_page_is_not_reserved(self):
        row = self.say(email='old@gmail.com')
        shown = f'{row.pk}:{connections.as_shown(row)}'
        self.say(email='new@gmail.com')
        self.press('reserve_place', [row], {'confirmed': 'reserve_place', 'seen': [shown]})
        self.assertIsNone(Request.objects.get().invited_at)

    def test_access_needs_its_own_confirmation(self):
        row = self.say(email='ana@gmail.com')
        connections.reserve([row.pk])
        self.press('give_place', [row])
        self.assertIsNone(Request.objects.get().ready_at)
        self.confirm('give_place', [row])
        self.assertIsNotNone(Request.objects.get().ready_at)

    def test_a_mistaken_reservation_is_undone(self):
        row = self.say(email='ana@gmail.com')
        before = connections.seats_used()
        connections.reserve([row.pk])
        self.press('undo_reservation', [row])
        self.assertIsNotNone(Request.objects.get().invited_at)
        self.confirm('undo_reservation', [row])
        row.refresh_from_db()
        self.assertEqual((row.invited_at, row.removed_at, row.google_email), (None, None, 'ana@gmail.com'))
        self.assertEqual(connections.seats_used(), before)
        self.assertEqual(self.see()['gmail'], 'waiting')
        self.assertEqual(self.invite(row)['given'], 1)  # it can be given later

    def test_undo_frees_the_place_of_who_left_or_was_deleted(self):
        left, gone = self.say(email='ana@gmail.com'), self.say(email='eva@gmail.com', user=self.person('eva'))
        before = connections.seats_used()
        connections.reserve([left.pk, gone.pk])
        self.say(wants=False)
        Request.objects.filter(pk=gone.pk).update(user=None)
        self.assertEqual(connections.undo_reserve([left.pk, gone.pk])['undone'], 2)
        self.assertEqual(connections.seats_used(), before)

    def test_never_undone_once_given_even_if_removed(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        self.assertEqual(connections.undo_reserve([row.pk])['undone'], 0)
        connections.remove([row.pk])
        self.assertEqual(connections.undo_reserve([row.pk])['undone'], 0)
        self.assertIsNotNone(Request.objects.get().invited_at)

    def test_every_change_says_who_and_never_the_address(self):
        row = self.say(email='ana@gmail.com')
        self.confirm('reserve_place', [row])
        self.confirm('undo_reservation', [row])
        self.confirm('reserve_place', [row])
        self.confirm('give_place', [row])
        self.press('take_place', [row])
        self.confirm('return_place', [row])
        entries = list(LogEntry.objects.filter(object_id=str(row.pk)).order_by('pk'))
        self.assertEqual([entry.user_id for entry in entries], [self.staff().pk] * 6)
        self.assertEqual(len({entry.change_message for entry in entries}), 5)
        self.assertNotIn('@', ''.join(entry.change_message + entry.object_repr for entry in entries))

    def test_what_changed_nothing_is_not_recorded(self):
        self.press('take_place', [self.say(email='ana@gmail.com')])
        self.assertFalse(LogEntry.objects.exists())

    def test_no_access_without_its_record(self):
        row = self.say(email='ana@gmail.com')
        connections.reserve([row.pk])
        with self.assertRaises(RuntimeError):
            connections.give([row.pk], log=mock.Mock(side_effect=RuntimeError))
        self.assertIsNone(Request.objects.get().ready_at)
        self.notify.assert_not_called()

    def test_connecting_erases_the_address_before_any_sweep(self):
        from assistant.gmail import crypto, oauth
        self.invite(self.say(email='ana@gmail.com'))
        with mock.patch.object(crypto, 'seal', return_value='sealed'), mock.patch.object(
                crypto, 'opaque', return_value='key'):
            connection, _ = oauth._save(self.user, mock.Mock(consent_version=1),
                                        {'refresh_token': 'r', 'scope': ''}, 'ana@gmail.com')
            self.assertEqual(Request.objects.get().google_email, '')
            oauth.disconnect(GmailConnection.objects.get(pk=connection.pk))
        self.assertEqual(Request.objects.get().google_email, '')
        self.assertEqual(self.see()['gmail'], 'invited')

    def told(self, action, rows, extra=None):
        """What the operator is told, and how loud."""
        request = RequestFactory().post('/admin/', {ACTION_CHECKBOX_NAME: [row.pk for row in rows],
                                                    'action': action, **(extra or {})})
        request.user = self.staff()
        model_admin = connections_admin.ConnectionRequestAdmin(Request, AdminSite())
        with mock.patch.object(model_admin, 'message_user') as said, mock.patch.object(
                model_admin, 'response_post_save_change', return_value='back'):
            getattr(model_admin, action)(request, Request.objects.filter(pk__in=[row.pk for row in rows]))
        return said.call_args.args[1:]

    def test_a_refused_reservation_never_says_to_add_it_in_google(self):
        row = self.say(email='old@gmail.com')
        shown = f'{row.pk}:{connections.as_shown(row)}'
        self.say(email='new@gmail.com')
        words, level = self.told('reserve_place', [row], {'confirmed': 'reserve_place', 'seen': [shown]})
        self.assertIn('no agregues nada en Google', words)
        self.assertEqual(level, messages.WARNING)

    def test_no_page_and_no_console_step_while_the_pilot_is_off(self):
        row = self.say(email='ana@gmail.com')
        with override_settings(GMAIL_PILOT_USER_IDS=''):
            self.assertIn('no agregues nada en Google', self.told('reserve_place', [row])[0])

    def test_an_old_undo_page_cannot_free_a_newer_reservation(self):
        row = self.say(email='ana@gmail.com')
        connections.reserve([row.pk])
        row.refresh_from_db()
        old_page = f'{row.pk}:{connections.as_shown(row)}'
        connections.undo_reserve([row.pk])
        connections.reserve([row.pk])
        self.press('undo_reservation', [row], {'confirmed': 'undo_reservation', 'seen': [old_page]})
        self.assertIsNotNone(Request.objects.get().invited_at)

    def test_an_old_reserve_page_cannot_spend_after_an_undo(self):
        row = self.say(email='ana@gmail.com')
        connections.reserve([row.pk])
        Request.objects.filter(pk=row.pk).update(removed_at=timezone.now())  # asked again: the page says "Gasta 0"
        row.refresh_from_db()
        old_page = f'{row.pk}:{connections.as_shown(row)}'
        connections.undo_reserve([row.pk])
        self.press('reserve_place', [row], {'confirmed': 'reserve_place', 'seen': [old_page]})
        self.assertIsNone(Request.objects.get().invited_at)

    def test_a_stored_address_that_is_not_gmail_gets_no_place(self):
        row = self.say(email='ana@gmail.com')
        Request.objects.filter(pk=row.pk).update(google_email='ana@yahoo.com')
        self.assertEqual(connections.reserve([row.pk])['reserved'], 0)
        Request.objects.filter(pk=row.pk).update(invited_at=timezone.now())
        self.assertEqual(connections.give([row.pk])['given'], 0)

    def test_returning_access_needs_a_confirmation(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        connections.remove([row.pk])
        self.press('return_place', [row])
        self.assertFalse(config.user_allowed(self.user))
        self.confirm('return_place', [row])
        self.assertTrue(config.user_allowed(self.user))

    def test_the_page_never_posts_more_than_a_round(self):
        rows = [self.say(email=f'q{n}@gmail.com', user=self.person(f'q{n}')) for n in range(3)]
        with mock.patch.object(config, 'MAX_TESTERS', 2):
            page = self.press('reserve_place', rows)
        self.assertEqual((page.context_data['rows'], page.context_data['next_round']), (rows[:2], 1))

    def test_an_old_undo_page_cannot_free_who_was_reserved_again(self):
        row = self.say(email='ana@gmail.com')
        connections.reserve([row.pk])
        Request.objects.filter(pk=row.pk).update(removed_at=timezone.now())
        row.refresh_from_db()
        old_page = f'{row.pk}:{connections.as_shown(row)}'
        connections.reserve([row.pk])  # the same address, the same place
        self.press('undo_reservation', [row], {'confirmed': 'undo_reservation', 'seen': [old_page]})
        self.assertIsNotNone(Request.objects.get().invited_at)

    def test_an_old_return_page_cannot_undo_a_later_removal(self):
        row = self.say(email='ana@gmail.com')
        self.invite(row)
        connections.remove([row.pk])
        row.refresh_from_db()
        old_page = f'{row.pk}:{connections.as_shown(row)}'
        connections.give_back([row.pk])
        connections.remove([row.pk])
        self.press('return_place', [row], {'confirmed': 'return_place', 'seen': [old_page]})
        self.assertFalse(config.user_allowed(self.user))

    def test_a_forged_seen_is_ignored(self):
        row = self.say(email='ana@gmail.com')
        self.press('reserve_place', [row], {'confirmed': 'reserve_place', 'seen': [chr(0xb2) + ':x']})
        self.assertIsNone(Request.objects.get().invited_at)


class ConfirmPageTests(TestCase):
    def test_the_page_posts_back_what_it_showed_and_escapes_it(self):
        from django.template.loader import render_to_string
        row = Request(pk=7, google_email='a"b@gmail.com', answer='yes', feature='gmail')
        page = render_to_string('admin/assistant/connection_confirm.html', {
            'rows': [row], 'shown': [(row, '7:0:a"b@gmail.com')], 'action': 'reserve_place', 'checkbox': ACTION_CHECKBOX_NAME, 'warning': 'w', 'button': 'b'})
        self.assertIn('name="confirmed" value="reserve_place"', page)
        self.assertIn('name="_selected_action" value="7"', page)
        self.assertIn('value="7:0:a&quot;b@gmail.com"', page)


@override_settings(**ON)
class AdminFlowTests(TestCase):
    """The real site, its changelist POST and the rendered page."""

    def test_select_confirm_reserve(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from config.admin_dashboard import confio_admin_site
        users = get_user_model().objects
        person = users.create_user(username='cx_flow', email='flow@example.com', password='x', firebase_uid='cx-flow')
        staff = users.create_superuser(username='cx_boss', email='boss@example.com', password='x', firebase_uid='cx-boss')
        staff.is_verified = lambda: True
        row = Request.objects.create(user=person, feature='gmail', answer='yes', google_email='flow@gmail.com')
        model_admin = confio_admin_site._registry[Request]

        def post(data):
            request = RequestFactory().post('/', {ACTION_CHECKBOX_NAME: [row.pk], 'index': '0', **data})
            request.user, request.session = staff, {}
            request._dont_enforce_csrf_checks = True
            request._messages = FallbackStorage(request)
            return model_admin.changelist_view(request)

        with mock.patch('security.utils.check_user_banned', return_value=(False, None)):
            page = post({'action': 'reserve_place'})
            page.render()
            self.assertIn('flow@gmail.com', page.content.decode())
            self.assertIsNone(Request.objects.get().invited_at)
            done = post({'action': 'reserve_place', 'confirmed': 'reserve_place', 'seen': f'{row.pk}:0:flow@gmail.com'})
            self.assertEqual(done.status_code, 302)
            self.assertIsNotNone(Request.objects.get().invited_at)
            self.assertEqual(LogEntry.objects.get().user_id, staff.pk)
            self.assertEqual(post({'action': 'reserve_place'}).status_code, 302)  # nothing left to confirm


@override_settings(**ON, GMAIL_PILOT_SELF_SERVE=True)
class SelfServeTests(TestCase):
    """Unverified production: anyone takes one of the places left by connecting."""
    setUp = ConnectionsTests.setUp
    person = ConnectionsTests.person
    see = ConnectionsTests.see

    def start(self, user=None):
        from assistant.gmail import oauth
        return oauth.start(user or self.user, config.CONSENT_VERSION)

    def take(self, user):
        from django.db import transaction
        from assistant.gmail import oauth
        with transaction.atomic():
            oauth._take_place(user)

    def test_anyone_may_connect_and_connecting_spends_a_place(self):
        self.assertEqual(self.see()['gmail'], 'invited')
        before = connections.seats_used()
        self.take(self.user)
        row = Request.objects.get(user=self.user, feature='gmail')
        self.assertTrue(row.invited_at and row.ready_at and not row.removed_at and not row.google_email)
        self.assertEqual(connections.seats_used(), before + 1)
        self.assertTrue(config.user_allowed(self.user))

    def test_google_screen_holds_a_place_and_full_stops_before_it(self):
        left = connections.seats_left()
        self.start()
        self.assertEqual(connections.seats_left(), left - 1)
        self.start()  # a new attempt replaces the old one
        self.assertEqual(connections.seats_left(), left - 1)
        from assistant.gmail.errors import MailRefused
        late = self.person('late')
        with mock.patch.object(connections, 'seats_left', return_value=0):
            self.assertFalse(config.user_allowed(late))
            self.assertEqual(self.see(late)['gmail'], 'full')
            with self.assertRaises(MailRefused) as caught:
                self.start(late)
        self.assertEqual(caught.exception.code, 'full')

    def test_every_account_that_consented_counts_once(self):
        from assistant.gmail import oauth
        from assistant.gmail.models import GmailGrant
        left = connections.seats_left()
        oauth._granted('a@gmail.com')
        oauth._granted('A@gmail.com')
        oauth._granted('')
        self.assertEqual(GmailGrant.objects.count(), 2)
        self.assertEqual(connections.seats_left(), left - 2)  # two Google accounts, neither the configured owner's

    def test_their_own_hold_never_counts_against_them(self):
        self.start()
        with mock.patch.object(connections, 'seats_left', return_value=0):
            self.assertTrue(config.user_allowed(self.user))  # the last place is the one they hold

    def test_coming_back_from_google_counts_once_whatever_happens(self):
        from assistant.gmail import client, oauth
        from assistant.gmail.errors import GmailError, MailRefused
        from assistant.gmail.models import GmailGrant, GmailOAuthState
        url, verifier = self.start()
        from urllib.parse import parse_qs, urlparse
        state = parse_qs(urlparse(url).query)['state'][0]
        with mock.patch.object(client, 'exchange_code', side_effect=GmailError(400)):
            with self.assertRaises(MailRefused):
                oauth.complete(self.user, 'code', state, verifier)
        self.assertEqual(GmailGrant.objects.count(), 1)
        self.assertFalse(GmailOAuthState.objects.exists())
        with self.assertRaises(MailRefused):  # used once
            oauth.complete(self.user, 'code', state, verifier)
        self.assertEqual(GmailGrant.objects.count(), 1)

    def test_a_late_return_from_google_is_still_counted(self):
        from urllib.parse import parse_qs, urlparse
        from assistant.gmail import oauth
        from assistant.gmail.errors import MailRefused
        from assistant.gmail.models import GmailGrant, GmailOAuthState
        url, verifier = self.start()
        GmailOAuthState.objects.update(expires_at=timezone.now() - timedelta(minutes=30))
        sync.cleanup(timezone.now())  # the sweep keeps it for a while
        with mock.patch.object(connections, 'seats_left', return_value=0):
            self.assertTrue(config.user_allowed(self.user))
        state = parse_qs(urlparse(url).query)['state'][0]
        with self.assertRaises(MailRefused) as caught:
            oauth.complete(self.user, 'code', state, verifier)
        self.assertEqual((caught.exception.code, GmailGrant.objects.count()), ('expired', 1))

    def test_places_and_google_accounts_are_counted_once_each(self):
        from assistant.gmail import crypto, oauth
        left = connections.seats_left()
        configured = get_user_model().objects.create_user(
            username='cx_owner', email='o@example.com', password='x', firebase_uid='cx-owner', pk=999999901)
        oauth._granted('owner@gmail.com')  # the configured owner's mailbox, connected
        now = timezone.now()
        GmailConnection.objects.create(user=configured, consent_version=2, connected_at=now, next_sync_at=now,
                                       email_key=crypto.opaque('owner@gmail.com'))
        self.assertEqual(connections.seats_left(), left)  # one person, one account: still one place
        oauth._granted('')  # someone who consented and was never connected
        self.assertEqual(connections.seats_left(), left - 1)

    def test_a_reserved_place_is_not_held_twice(self):
        Request.objects.create(user=self.user, feature='gmail', answer='yes', invited_at=timezone.now())
        with mock.patch.object(connections, 'seats_left', return_value=0):
            self.start()
            self.assertTrue(config.user_allowed(self.user))

    def test_a_member_reconnects_even_when_full(self):
        self.take(self.user)
        with mock.patch.object(connections, 'seats_left', return_value=0):
            self.start()  # no refusal
            self.assertTrue(config.user_allowed(self.user))

    def test_a_place_taken_away_is_not_taken_again(self):
        self.take(self.user)
        connections.remove([Request.objects.get(user=self.user).pk])
        self.assertFalse(config.user_allowed(self.user))
        from assistant.gmail.errors import MailRefused
        with self.assertRaises(MailRefused):
            self.take(self.user)

    def test_waiting_people_hear_the_news(self):
        Request.objects.create(user=self.user, feature='gmail', answer='yes')
        self.assertEqual(connections.tell_waiting(Request.objects.values_list('pk', flat=True)), 1)

    def test_off_without_the_switch_or_the_list(self):
        with override_settings(GMAIL_PILOT_SELF_SERVE=False):
            self.assertFalse(config.user_allowed(self.user))
        with override_settings(GMAIL_PILOT_USER_IDS=''):
            self.assertFalse(config.user_allowed(self.user))

    def test_banned_never(self):
        self.banned.return_value = (True, None)
        self.assertFalse(config.user_allowed(self.user))
