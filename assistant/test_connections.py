"""Discovery, the waitlist and the 100 places (assistant/connections.py)."""
from datetime import timedelta
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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
        for bad in ('', 'nope', 'a@b', 'x' * 260 + '@gmail.com', 'ana@icloud.com', 'x@privaterelay.appleid.com'):
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
        row = self.say(email='ana@gmial.com')
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
