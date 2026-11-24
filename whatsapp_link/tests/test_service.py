"""The WhatsApp link without a browser, a model or a push: every way out is stubbed."""
import contextlib
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from agent_tasks import browsers
from whatsapp_link import service, tasks as _tasks, web  # noqa: F401 - patched below
from whatsapp_link.models import WhatsAppDraft, WhatsAppLink, WhatsAppNotice

CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'whatsapp-link-tests'}}
PHONE = '59171234567'
CONSENT = service.CONSENT_VERSION


class FakePage:
    def __init__(self, *_args, **_kwargs):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def guard_documents(self, _allowed):
        pass

    def call(self, *_args, **_kwargs):
        return {}

    def goto(self, _url):
        pass

    def pump(self, _seconds):
        pass

    def close(self):
        self.closed = True


@override_settings(CACHES=CACHE, WHATSAPP_LINK_ENABLED=True)
class LinkTestBase(TestCase):
    def setUp(self):
        from users.models import User
        cache.clear()
        self.user = User.objects.create(username='wa_owner', firebase_uid='wa-owner', phone_country='BO',
                                        phone_number='71234567')
        self.other = User.objects.create(username='wa_other', firebase_uid='wa-other')
        self.vendor = self.patch('agent_tasks.browsers.provider').return_value
        self.vendor.name = 'fake'
        self.vendor.create_profile.return_value = 'ctx-1'
        self.vendor.open.return_value = browsers.Session(
            id='sess-1', connect_url='wss://secret', expires_at=timezone.now() + timedelta(minutes=10))
        self.page = FakePage()
        self.patch('whatsapp_link.service.Page', return_value=self.page)
        self.pushes = self.patch('whatsapp_link.service._notify')
        self.tasks = self.patch('whatsapp_link.tasks')
        self.patch('django.db.transaction.on_commit', side_effect=lambda fn, *a, **k: fn())

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def linked(self, user=None, **over):
        fields = dict(state=WhatsAppLink.State.LINKED, provider='fake', context_id='ctx-1', phone_hint='4567',
                      phone_key=service.phone_key(PHONE),
                      consent_version=CONSENT, linked_at=timezone.now(),
                      next_sync_at=timezone.now() - timedelta(minutes=1))
        fields.update(over)
        return WhatsAppLink.objects.create(user=user or self.user, **fields)


class PairingTest(LinkTestBase):
    def test_start_seals_the_number_and_queues_a_pairing(self):
        link = service.start_link(self.user, CONSENT)
        link.refresh_from_db()
        self.assertEqual(link.state, 'pairing')
        self.assertEqual(link.phone_hint, '4567')
        self.assertNotIn(PHONE, link.sealed_phone)
        self.assertEqual(service._unseal(link.sealed_phone), PHONE)
        self.tasks.pair.delay.assert_called_once_with(link.pk, str(link.grant))

    def test_only_the_persons_own_number_after_consent(self):
        with self.assertRaises(service.LinkRefused) as caught:
            service.start_link(self.other, CONSENT)  # no number in Confío
        self.assertEqual(caught.exception.code, 'no_phone')
        with self.assertRaises(service.LinkRefused) as caught:
            service.start_link(self.user, 0)
        self.assertEqual(caught.exception.code, 'consent')
        self.tasks.pair.delay.assert_not_called()

    def test_a_new_pairing_keeps_nothing_of_the_last(self):
        link = self.linked(state=WhatsAppLink.State.GONE)
        WhatsAppNotice.objects.create(link=link, source_key='k', kind='order', sealed=service._seal({}))
        WhatsAppDraft.objects.create(link=link, sealed=service._seal({}), expires_at=timezone.now() + timedelta(hours=1))
        service.start_link(self.user, CONSENT)
        self.assertFalse(WhatsAppNotice.objects.exists())
        self.assertFalse(WhatsAppDraft.objects.exists())

    def test_a_pairing_waits_for_the_one_holding_the_browser(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(lease_until=timezone.now() + timedelta(minutes=1))
        with mock.patch.object(web, 'ask_for_code') as ask:
            service.pair(link.pk, str(link.grant))
        ask.assert_not_called()
        self.tasks.pair.apply_async.assert_called_once_with((link.pk, str(link.grant), 1), countdown=4)

    def test_a_linked_whatsapp_is_not_paired_again(self):
        self.linked()
        with self.assertRaises(service.LinkRefused) as caught:
            service.start_link(self.user, CONSENT)
        self.assertEqual(caught.exception.code, 'already_linked')

    def test_pair_reads_the_code_and_watches(self):
        link = service.start_link(self.user, CONSENT)
        with mock.patch.object(web, 'ask_for_code', return_value='ABCD1234') as ask:
            service.pair(link.pk, str(link.grant))
        ask.assert_called_once_with(self.page, PHONE)
        link.refresh_from_db()
        self.assertEqual(service._unseal(link.sealed_code), 'ABCD1234')
        self.assertEqual(link.context_id, 'ctx-1')
        self.assertIsNone(link.lease_until)
        self.assertNotIn('wss://secret', link.sealed_connect_url)
        self.tasks.watch.apply_async.assert_called_once()
        # The person's own profile, in the link's region, on a desktop screen.
        kwargs = self.vendor.open.call_args.kwargs
        self.assertEqual(kwargs['profile_id'], 'ctx-1')
        self.assertEqual(kwargs['region'], 'eu-central-1')
        self.assertEqual(kwargs['viewport']['width'], 1280)

    def test_a_second_pair_never_replaces_a_code_given_out(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(code_at=timezone.now(), sealed_code=service._seal('ABCD1234'))
        with mock.patch.object(web, 'ask_for_code') as ask:
            service.pair(link.pk, str(link.grant))
        ask.assert_not_called()
        self.vendor.open.assert_not_called()

    def test_unlinking_twice_says_so_once(self):
        self.linked()
        self.assertTrue(service.unlink(self.user))
        self.assertFalse(service.unlink(self.user))

    def test_a_rotated_secret_key_is_not_a_new_number(self):
        link = self.linked()
        with override_settings(SECRET_KEY='rotated-' + 'x' * 50, SECRET_KEY_FALLBACKS=[self._old_secret()]):
            self.assertFalse(service.number_changed(link))

    @staticmethod
    def _old_secret():
        from django.conf import settings
        return settings.SECRET_KEY

    def test_an_old_grant_does_nothing(self):
        link = service.start_link(self.user, CONSENT)
        with mock.patch.object(web, 'ask_for_code') as ask:
            service.pair(link.pk, '00000000-0000-0000-0000-000000000000')
        ask.assert_not_called()
        self.vendor.open.assert_not_called()

    def test_a_refused_number_fails_and_closes_the_browser(self):
        link = service.start_link(self.user, CONSENT)
        with mock.patch.object(web, 'ask_for_code', side_effect=web.WebError('phone_invalid')):
            service.pair(link.pk, str(link.grant))
        link.refresh_from_db()
        self.assertEqual((link.state, link.reason), ('failed', 'phone_invalid'))
        self.vendor.close.assert_called_with('sess-1')
        self.assertEqual(link.session_id, '')
        # A code typed at that moment could have linked it: the profile goes too.
        self.vendor.delete_profile.assert_called_once_with('ctx-1')
        self.assertEqual((link.context_id, link.sealed_phone), ('', ''))

    def test_watch_sees_the_link_and_closes_the_browser(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(
            session_id='sess-1', sealed_connect_url=service._seal('wss://secret'),
            session_expires_at=timezone.now() + timedelta(minutes=5), sealed_code=service._seal('ABCD1234'))
        with mock.patch.object(web, 'screen', return_value='chats'):
            service.watch(link.pk, str(link.grant))
        link.refresh_from_db()
        self.assertEqual(link.state, 'linked')
        self.assertEqual((link.sealed_code, link.sealed_phone), ('', ''))
        self.assertIsNotNone(link.next_sync_at)
        self.vendor.close.assert_called_with('sess-1')
        self.pushes.assert_called_once()

    def test_watch_keeps_the_code_fresh(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(
            session_id='sess-1', sealed_connect_url=service._seal('wss://secret'),
            session_expires_at=timezone.now() + timedelta(minutes=5), sealed_code=service._seal('ABCD1234'))
        with mock.patch.object(web, 'screen', return_value='code'), \
                mock.patch.object(web, 'read_code', return_value='WXYZ9876'), \
                mock.patch.object(service, 'WATCH_SECONDS', 0.01):
            service.watch(link.pk, str(link.grant))
        link.refresh_from_db()
        self.assertEqual(service._unseal(link.sealed_code), 'WXYZ9876')
        self.tasks.watch.apply_async.assert_called_once()

    def test_a_made_link_is_never_failed(self):
        link = self.linked()
        service._fail(link, 'whatsapp')
        link.refresh_from_db()
        self.assertEqual((link.state, link.context_id), ('linked', 'ctx-1'))
        self.vendor.delete_profile.assert_not_called()

    def test_typed_just_as_the_code_was_asked_again(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(
            session_id='sess-1', sealed_connect_url=service._seal('wss://secret'),
            session_expires_at=timezone.now() + timedelta(minutes=5), context_id='ctx-1')
        screens = iter(['login', 'chats'])
        with mock.patch.object(web, 'screen', side_effect=lambda _p: next(screens)), \
                mock.patch.object(web, 'ask_for_code', side_effect=web.WebError('no_next')):
            service.watch(link.pk, str(link.grant))
        link.refresh_from_db()
        self.assertEqual(link.state, 'linked')
        self.vendor.delete_profile.assert_not_called()

    def test_an_already_linked_profile_must_be_the_persons_number(self):
        link = service.start_link(self.user, CONSENT)
        with mock.patch.object(web, 'ask_for_code', side_effect=web.WebError('already_linked')), \
                mock.patch.object(web, 'wait_for', return_value='chats'), \
                mock.patch.object(web, 'signed_in_number', return_value='5491100000000'):
            service.pair(link.pk, str(link.grant))
        link.refresh_from_db()
        self.assertEqual((link.state, link.reason), ('failed', 'not_own_phone'))
        self.vendor.delete_profile.assert_called_once_with('ctx-1')

    def test_an_already_linked_own_profile_is_linked(self):
        link = service.start_link(self.user, CONSENT)
        with mock.patch.object(web, 'ask_for_code', side_effect=web.WebError('already_linked')), \
                mock.patch.object(web, 'wait_for', return_value='chats'), \
                mock.patch.object(web, 'signed_in_number', return_value=PHONE):
            service.pair(link.pk, str(link.grant))
        link.refresh_from_db()
        self.assertEqual(link.state, 'linked')

    def test_argentine_mobiles_carry_the_nine(self):
        self.user.phone_country, self.user.phone_number = 'AR', '1123456789'
        self.assertEqual(service.own_phone(self.user), '5491123456789')

    def test_an_expired_pairing_fails(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(
            session_id='sess-1', sealed_connect_url=service._seal('wss://secret'),
            session_expires_at=timezone.now() + timedelta(seconds=5))
        service.watch(link.pk, str(link.grant))
        link.refresh_from_db()
        self.assertEqual((link.state, link.reason), ('failed', 'timeout'))

    def test_status_shows_the_code_only_while_pairing(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(sealed_code=service._seal('ABCD1234'), code_at=timezone.now())
        self.assertEqual(service.status(self.user)['code'], 'ABCD1234')
        WhatsAppLink.objects.filter(pk=link.pk).update(state='linked')
        self.assertIsNone(service.status(self.user)['code'])
        self.assertEqual(service.status(self.other)['state'], 'none')


class ReadingTest(LinkTestBase):
    ROWS = [
        {'name': 'Farmacia Central', 'preview': 'Su pedido está listo, son Bs 120', 'unread': 1, 'group': False,
         'time': '10:01'},
        {'name': 'Familia', 'preview': 'Ana: hola', 'unread': 3, 'group': True, 'time': '10:02'},
        {'name': 'Banco', 'preview': 'Tu código de verificación es 482913', 'unread': 1, 'group': False,
         'time': '10:03'},
        {'name': 'Pedro', 'preview': 'jaja', 'unread': 1, 'group': False, 'time': '10:04'},
    ]

    def run_sync(self, link, rows=None, verdicts=None):
        verdicts = verdicts if verdicts is not None else [{'kind': 'order', 'summary': 'Pedido listo'}, None]
        with mock.patch.object(service, '_read', return_value=rows if rows is not None else self.ROWS), \
                mock.patch('whatsapp_link.classify.important', return_value=verdicts) as classify:
            service.sync(link.pk)
        return classify

    def test_only_important_one_to_one_chats_are_kept_sealed(self):
        link = self.linked()
        classify = self.run_sync(link)
        sent = classify.call_args.args[0]
        # Groups and login codes never reach the model.
        self.assertEqual([row['chat'] for row in sent], ['Farmacia Central', 'Pedro'])
        notice = WhatsAppNotice.objects.get()
        self.assertEqual(notice.kind, 'order')
        self.assertNotIn('Farmacia', notice.sealed)
        self.assertEqual(service._unseal(notice.sealed)['chat'], 'Farmacia Central')
        # The push says how many, never what or who.
        message = self.pushes.call_args.args[1]
        self.assertIn('1 mensaje importante', message)
        self.assertNotIn('Farmacia', message)
        link.refresh_from_db()
        self.assertIsNotNone(link.last_sync_at)
        self.assertGreater(link.next_sync_at, timezone.now() + timedelta(minutes=100))

    def test_a_message_is_judged_once(self):
        link = self.linked()
        self.run_sync(link)
        WhatsAppLink.objects.filter(pk=link.pk).update(next_sync_at=timezone.now())
        classify = self.run_sync(link, verdicts=[])
        classify.assert_not_called()
        self.assertEqual(WhatsAppNotice.objects.count(), 1)
        self.assertEqual(self.pushes.call_count, 1)

    def test_not_due_is_not_read(self):
        link = self.linked(next_sync_at=timezone.now() + timedelta(hours=1))
        with mock.patch.object(service, '_read') as read:
            service.sync(link.pk)
        read.assert_not_called()

    def test_unlinked_from_the_phone_is_gone(self):
        link = self.linked()
        with mock.patch.object(service, '_read', side_effect=web.WebError('gone')):
            service.sync(link.pk)
            link.refresh_from_db()
            # Once is not proof: it looks again minutes later.
            self.assertEqual(link.state, 'linked')
            self.vendor.delete_profile.assert_not_called()
            self.assertLess(link.next_sync_at, timezone.now() + timedelta(minutes=11))
            WhatsAppLink.objects.filter(pk=link.pk).update(next_sync_at=timezone.now())
            cache.set(service._gone_key(link), (timezone.now() - timedelta(minutes=11)).timestamp())
            service.sync(link.pk)
        link.refresh_from_db()
        self.assertEqual(link.state, 'gone')
        self.vendor.delete_profile.assert_called_once_with('ctx-1')
        self.assertEqual(self.pushes.call_args.args[1], service.GONE)

    def test_a_failed_read_backs_off(self):
        link = self.linked()
        with mock.patch.object(service, '_read', side_effect=browsers.BrowserUnavailable('x')):
            service.sync(link.pk)
        link.refresh_from_db()
        self.assertEqual(link.failures, 1)
        self.assertEqual(link.state, 'linked')

    def test_a_changed_confio_number_unlinks(self):
        link = self.linked()
        self.user.phone_number = '79994567'  # same last four digits
        self.user.save()
        with mock.patch.object(service, '_read') as read:
            service.sync(link.pk)
        read.assert_not_called()
        self.assertEqual(WhatsAppLink.objects.get(pk=link.pk).reason, 'unlinking')

    def test_opening_confio_ia_never_hurries_the_second_look(self):
        link = self.linked(last_sync_at=timezone.now() - timedelta(hours=2))
        with mock.patch.object(service, '_read', side_effect=web.WebError('gone')):
            service.sync(link.pk)
            self.assertFalse(service.refresh(self.user))
            # Even when a read runs early, it is not the second look until ten minutes passed.
            WhatsAppLink.objects.filter(pk=link.pk).update(next_sync_at=timezone.now())
            service.sync(link.pk)
        self.assertEqual(WhatsAppLink.objects.get(pk=link.pk).state, 'linked')
        self.vendor.delete_profile.assert_not_called()

    def test_a_good_read_between_clears_a_gone_sighting(self):
        link = self.linked()
        with mock.patch.object(service, '_read', side_effect=web.WebError('gone')):
            service.sync(link.pk)
        WhatsAppLink.objects.filter(pk=link.pk).update(next_sync_at=timezone.now())
        self.run_sync(link, rows=[])
        WhatsAppLink.objects.filter(pk=link.pk).update(next_sync_at=timezone.now())
        with mock.patch.object(service, '_read', side_effect=web.WebError('gone')):
            service.sync(link.pk)
        self.assertEqual(WhatsAppLink.objects.get(pk=link.pk).state, 'linked')

    def test_outdated_consent_waits_without_blocking_others(self):
        link = self.linked(consent_version=0)
        self.assertNotIn(link.pk, service.due_ids())
        with mock.patch.object(service, '_read') as read:
            service.sync(link.pk)
        read.assert_not_called()
        self.assertTrue(service.status(self.user)['consent_outdated'])
        self.assertFalse(service.refresh(self.user))
        service.accept_consent(self.user, CONSENT)
        self.assertIn(link.pk, service.due_ids())

    def test_too_many_browsers_open_waits_without_blame(self):
        link = self.linked()
        self.linked(user=self._person(0), session_id='s0', session_expires_at=timezone.now() + timedelta(minutes=5))
        with mock.patch.object(web, 'wait_for') as waited:
            service.sync(link.pk)
        waited.assert_not_called()
        self.vendor.open.assert_not_called()
        link.refresh_from_db()
        self.assertEqual(link.failures, 0)
        self.assertLess(link.next_sync_at, timezone.now() + timedelta(minutes=16))

    def _person(self, n):
        from users.models import User
        return User.objects.create(username=f'wa_busy_{n}', firebase_uid=f'wa-busy-{n}')

    def test_purchases_keep_their_browsers(self):
        from agent_tasks.models import AgentTask
        from users.models import Account
        account = Account.objects.create(user=self.other, account_type='personal', account_index=0)
        for n in range(2):
            AgentTask.objects.create(account=account, user=self._person(10 + n), goal='x', site='x.com.br',
                                     country='BR', state='working', session_id=f'shop{n}',
                                     session_expires_at=timezone.now() + timedelta(minutes=5))
        link = self.linked()
        self.assertFalse(service._room(link, 'background'))  # a read always leaves one browser free
        self.assertTrue(service._room(link, 'pair'))

    def test_a_send_is_not_held_behind_someone_elses_pairing(self):
        link = self.linked()
        self.linked(user=self._person(20), state=WhatsAppLink.State.PAIRING, session_id='pairing',
                    session_expires_at=timezone.now() + timedelta(minutes=8))
        self.assertFalse(service._room(link, 'pair'))
        self.assertFalse(service._room(link, 'background'))
        self.assertTrue(service._room(link, 'send'))

    def test_a_finished_read_starts_the_next_due_one(self):
        link = self.linked()
        other = self.linked(user=self._person(30), context_id='ctx-9')
        self.run_sync(link, rows=[])
        self.tasks.sync.apply_async.assert_called_once_with((other.pk,), expires=240)

    def test_a_pairing_waits_for_a_free_browser(self):
        link = service.start_link(self.user, CONSENT)
        with mock.patch.object(service, '_room', return_value=False), mock.patch.object(web, 'ask_for_code') as ask:
            service.pair(link.pk, str(link.grant))
        ask.assert_not_called()
        link.refresh_from_db()
        self.assertEqual(link.state, 'pairing')
        self.tasks.pair.apply_async.assert_called_once_with((link.pk, str(link.grant), 1), countdown=10)

    def test_the_kill_switch_stops_reading(self):
        link = self.linked()
        with override_settings(WHATSAPP_LINK_ENABLED=False), mock.patch.object(service, '_read') as read:
            service.sync(link.pk)
            service.sweep()
        read.assert_not_called()
        self.tasks.sync.apply_async.assert_not_called()

    def test_refresh_is_throttled(self):
        link = self.linked(last_sync_at=timezone.now() - timedelta(minutes=5))
        self.assertFalse(service.refresh(self.user))
        WhatsAppLink.objects.filter(pk=link.pk).update(last_sync_at=timezone.now() - timedelta(hours=1))
        self.assertTrue(service.refresh(self.user))
        self.tasks.sync.apply_async.assert_called_once_with((link.pk,), expires=240)
        WhatsAppLink.objects.filter(pk=link.pk).update(last_sync_at=None, failures=2)
        self.assertFalse(service.refresh(self.user))  # never past a backoff

    def test_private_text(self):
        self.assertTrue(service.private({'name': 'X', 'preview': 'Tu código de WhatsApp: 123-456'}))
        self.assertTrue(service.private({'name': 'Banco', 'preview': 'Tu clave dinámica es 48 21'}))
        self.assertTrue(service.private({'name': 'Banco', 'preview': 'Token: 4821. No lo compartas.'}))
        self.assertFalse(service.private({'name': 'Tienda', 'preview': 'Tu pedido sale mañana'}))


class UnlinkTest(LinkTestBase):
    def test_unlink_erases_now_and_the_worker_deletes_the_profile(self):
        link = self.linked()
        WhatsAppNotice.objects.create(link=link, source_key='k', kind='order', sealed=service._seal({}))
        WhatsAppDraft.objects.create(link=link, sealed=service._seal({}), expires_at=timezone.now() + timedelta(hours=1))
        service.unlink(self.user)
        self.assertFalse(WhatsAppNotice.objects.exists())
        self.assertFalse(WhatsAppDraft.objects.exists())
        self.assertEqual(service.status(self.user)['state'], 'none')
        self.tasks.forget.delay.assert_called_once_with(link.pk)
        with mock.patch.object(web, 'wait_for', return_value='chats'), mock.patch.object(web, 'log_out') as out:
            service.forget(link.pk)
        out.assert_called_once_with(self.page)
        self.vendor.delete_profile.assert_called_once_with('ctx-1')
        self.assertFalse(WhatsAppLink.objects.exists())
        self.tasks.drop_profile.delay.assert_not_called()  # already deleted: nothing orphaned

    def test_a_vendor_outage_keeps_the_row_for_the_sweep(self):
        link = self.linked()
        service.unlink(self.user)
        self.vendor.delete_profile.side_effect = browsers.BrowserUnavailable('down')
        with mock.patch.object(web, 'wait_for', return_value='login'):
            service.forget(link.pk)
        self.assertTrue(WhatsAppLink.objects.filter(pk=link.pk, reason='unlinking').exists())
        # The retry deletes only: it never opens another browser.
        self.vendor.delete_profile.side_effect = None
        opened = self.vendor.open.call_count
        service.forget(link.pk)
        self.assertEqual(self.vendor.open.call_count, opened)
        self.assertFalse(WhatsAppLink.objects.exists())

    def test_the_profile_retry_leaves_a_new_pairing_alone(self):
        link = self.linked(state=WhatsAppLink.State.FAILED)
        real = service._taken

        @contextlib.contextmanager
        def taken(link_id, *args, **kwargs):
            # The person asked again between the sweep's listing and its lease.
            WhatsAppLink.objects.filter(pk=link_id).update(state=WhatsAppLink.State.PAIRING)
            with real(link_id, *args, **kwargs) as row:
                yield row
        with mock.patch.object(service, '_taken', taken):
            service.sweep_vendor()
        self.vendor.delete_profile.assert_not_called()
        self.assertEqual(WhatsAppLink.objects.get(pk=link.pk).context_id, 'ctx-1')

    def test_the_profile_retry_deletes_a_failed_ones(self):
        link = self.linked(state=WhatsAppLink.State.FAILED)
        service.sweep_vendor()
        self.vendor.delete_profile.assert_called_once_with('ctx-1')
        self.assertEqual(WhatsAppLink.objects.get(pk=link.pk).context_id, '')

    def test_a_cascade_delete_still_deletes_the_profile(self):
        self.linked()
        self.user.delete()
        self.tasks.drop_profile.delay.assert_called_once_with('fake', 'ctx-1', '')

    def test_the_sweep_unlinks_banned_people(self):
        from security.models import UserBan
        link = self.linked()
        self.linked(user=self.other, context_id='ctx-2')
        with mock.patch('security.tasks.sync_face_blocklist'):
            UserBan.objects.create(user=self.user, ban_type='permanent', reason='fraud', reason_details='test')
        with mock.patch.object(service, 'due_ids', return_value=[]):
            service.sweep()
        self.assertEqual(WhatsAppLink.objects.get(pk=link.pk).reason, 'unlinking')
        self.assertEqual(WhatsAppLink.objects.get(user=self.other).reason, '')


class SendingTest(LinkTestBase):
    def draft(self, **over):
        self.linked()
        return service.create_draft(self.user, **{'chat': 'Farmacia Central', 'body': '¿Tienen ibuprofeno?', **over})

    def test_one_chat_or_one_number(self):
        self.linked()
        with self.assertRaises(service.LinkRefused):
            service.create_draft(self.user, body='hola')
        with self.assertRaises(service.LinkRefused):
            service.create_draft(self.user, chat='A', phone=PHONE, body='hola')

    def test_a_new_number_needs_its_country_code(self):
        self.linked()
        with self.assertRaises(service.LinkRefused) as caught:
            service.create_draft(self.user, phone='4141234567', body='hola')
        self.assertEqual(caught.exception.code, 'phone')
        made = service.create_draft(self.user, phone='+58 414 1234567', body='hola')
        self.assertEqual(made['phone'], '+584141234567')

    def test_send_needs_the_shown_text(self):
        made = self.draft()
        with self.assertRaises(service.LinkRefused) as caught:
            service.send_draft(self.user, made['id'], 'not-the-hash')
        self.assertEqual(caught.exception.code, 'changed')
        self.tasks.send.delay.assert_not_called()

    def test_someone_elses_draft_is_not_found(self):
        made = self.draft()
        with self.assertRaises(service.LinkRefused):
            service.send_draft(self.other, made['id'], made['display_hash'])

    def test_sent_once_and_the_text_is_dropped(self):
        made = self.draft()
        service.send_draft(self.user, made['id'], made['display_hash'])
        self.tasks.send.delay.assert_called_once_with(made['id'])
        with self.assertRaises(service.LinkRefused):
            service.send_draft(self.user, made['id'], made['display_hash'])  # already sending
        with mock.patch.object(web, 'wait_for', return_value='chats'), \
                mock.patch.object(web, 'open_chat_by_name') as opened, \
                mock.patch.object(web, 'send_text', return_value=True) as typed:
            service.send(made['id'])
        opened.assert_called_once_with(self.page, 'Farmacia Central')
        self.assertEqual(typed.call_args.args[:2], (self.page, '¿Tienen ibuprofeno?'))
        draft = WhatsAppDraft.objects.get(pk=made['id'])
        self.assertEqual(draft.status, 'sent')
        self.assertEqual(service._unseal(draft.sealed), {})
        service.send(made['id'])  # a repeated task does nothing
        typed.assert_called_once()

    def test_nothing_typed_goes_back_to_draft(self):
        made = self.draft()
        service.send_draft(self.user, made['id'], made['display_hash'])
        with mock.patch.object(web, 'wait_for', return_value='chats'), \
                mock.patch.object(web, 'open_chat_by_name', side_effect=web.WebError('chat_not_found')):
            service.send(made['id'])
        draft = WhatsAppDraft.objects.get(pk=made['id'])
        self.assertEqual((draft.status, draft.reason), ('draft', 'chat_not_found'))

    def test_unlinked_while_sending_never_presses_enter(self):
        made = self.draft()
        service.send_draft(self.user, made['id'], made['display_hash'])

        def typing(_page, _body, still_wanted, _progress=None):
            service.unlink(self.user)
            self.assertFalse(still_wanted())
            raise web.WebError('not_wanted')
        with mock.patch.object(web, 'wait_for', return_value='chats'), mock.patch.object(web, 'open_chat_by_name'), \
                mock.patch.object(web, 'send_text', side_effect=typing):
            service.send(made['id'])
        self.assertFalse(WhatsAppDraft.objects.exists())

    def test_a_silent_send_becomes_unknown_never_resent(self):
        made = self.draft()
        service.send_draft(self.user, made['id'], made['display_hash'])
        WhatsAppDraft.objects.filter(pk=made['id']).update(sending_at=timezone.now() - timedelta(minutes=15))
        with mock.patch.object(service, 'due_ids', return_value=[]):
            service.sweep()
        draft = WhatsAppDraft.objects.get(pk=made['id'])
        self.assertEqual((draft.status, draft.reason), ('unknown', 'unknown'))
        self.assertEqual(service._unseal(draft.sealed), {})

    def test_no_send_after_the_confio_number_changed(self):
        made = self.draft()
        self.user.phone_number = '79994567'  # same last four digits
        self.user.save()
        with self.assertRaises(service.LinkRefused) as caught:
            service.send_draft(self.user, made['id'], made['display_hash'])
        self.assertEqual(caught.exception.code, 'not_linked')

    def test_an_approved_send_waits_for_a_free_browser(self):
        made = self.draft()
        service.send_draft(self.user, made['id'], made['display_hash'])
        with mock.patch.object(service, '_room', return_value=False):
            service.send(made['id'])
        self.assertEqual(WhatsAppDraft.objects.get(pk=made['id']).status, 'sending')
        self.tasks.send.apply_async.assert_called_once_with((made['id'], 1), countdown=20)

    def test_unlinking_never_waits_for_a_browser(self):
        link = self.linked()
        service.unlink(self.user)
        with mock.patch.object(service, '_room', return_value=False), \
                mock.patch.object(web, 'wait_for', return_value='chats'), mock.patch.object(web, 'log_out') as out:
            service.forget(link.pk)
        out.assert_not_called()  # no browser free: the logout is skipped, the profile still goes
        self.vendor.delete_profile.assert_called_once_with('ctx-1')
        self.assertFalse(WhatsAppLink.objects.exists())

    def test_whatsapp_never_takes_more_than_two_worker_places(self):
        with service._slot() as first, service._slot() as second, service._slot() as third:
            self.assertEqual((first, second, third), (True, True, False))
        with service._slot() as again:
            self.assertTrue(again)  # given back

    def test_a_waiting_pairing_is_never_left_unwatched(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(
            session_id='sess-1', session_expires_at=timezone.now() + timedelta(minutes=5), code_at=timezone.now())
        with service._slot(), service._slot():
            service.watch(link.pk, str(link.grant))
            service.watch(link.pk, str(link.grant))  # still no place: it keeps waiting
        self.assertEqual(self.tasks.watch.apply_async.call_count, 2)
        WhatsAppLink.objects.filter(pk=link.pk).update(session_expires_at=timezone.now() - timedelta(seconds=1))
        with service._slot(), service._slot():
            service.watch(link.pk, str(link.grant))  # its browser is gone: nothing left to watch
        self.assertEqual(self.tasks.watch.apply_async.call_count, 2)

    def test_duplicate_watchers_merge_into_one(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(
            session_id='sess-1', session_expires_at=timezone.now() + timedelta(minutes=5), code_at=timezone.now(),
            lease_until=timezone.now() + timedelta(minutes=1))  # another watcher is looking right now
        service.watch(link.pk, str(link.grant))
        service.watch(link.pk, str(link.grant))  # a duplicate within 20 s ends instead of re-queueing
        self.tasks.watch.apply_async.assert_called_once_with((link.pk, str(link.grant)), countdown=3)

    def test_a_pairing_without_a_place_waits_then_ends(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(context_id='ctx-1', provider='fake')
        with service._slot(), service._slot():
            service.pair(link.pk, str(link.grant))
            self.tasks.pair.apply_async.assert_called_once_with((link.pk, str(link.grant), 1), countdown=10)
            service.pair(link.pk, str(link.grant), service.PAIR_RETRIES)
        link.refresh_from_db()
        self.assertEqual((link.state, link.reason), ('failed', 'browser'))
        self.vendor.delete_profile.assert_called_once_with('ctx-1')

    def test_a_pairing_with_a_code_out_is_never_failed_for_a_place(self):
        link = service.start_link(self.user, CONSENT)
        WhatsAppLink.objects.filter(pk=link.pk).update(code_at=timezone.now())
        with service._slot(), service._slot():
            service.pair(link.pk, str(link.grant), service.PAIR_RETRIES)
        self.assertEqual(WhatsAppLink.objects.get(pk=link.pk).state, 'pairing')

    def test_an_unlink_without_a_place_hands_the_profile_over(self):
        link = self.linked()
        service.unlink(self.user)
        with service._slot(), service._slot():
            service.forget(link.pk)
            self.tasks.forget.apply_async.assert_called_once_with((link.pk, 1), countdown=15)  # tries first
            service.forget(link.pk, 4)
        self.tasks.drop_profile.delay.assert_called_once_with('fake', 'ctx-1', '')
        self.vendor.delete_profile.assert_not_called()  # never inline on the browser worker
        self.assertFalse(WhatsAppLink.objects.exists())

    def test_a_send_without_a_place_waits(self):
        made = self.draft()
        service.send_draft(self.user, made['id'], made['display_hash'])
        with service._slot(), service._slot():
            service.send(made['id'])
        self.assertEqual(WhatsAppDraft.objects.get(pk=made['id']).status, 'sending')
        self.tasks.send.apply_async.assert_called_once_with((made['id'], 1), countdown=20)

    def test_a_new_version_replaces_the_unsent_one(self):
        old = self.draft(body='Primera versión')
        new = service.create_draft(self.user, chat='Farmacia Central', body='Segunda versión')
        # A late "Enviar" for the first version (stalled in the network) sends nothing.
        with self.assertRaises(service.LinkRefused) as caught:
            service.send_draft(self.user, old['id'], old['display_hash'])
        self.assertEqual(caught.exception.code, 'not_found')
        service.send_draft(self.user, new['id'], new['display_hash'])
        self.tasks.send.delay.assert_called_once_with(new['id'])

    def test_no_new_message_while_one_is_on_its_way(self):
        sending = self.draft()
        service.send_draft(self.user, sending['id'], sending['display_hash'])
        with self.assertRaises(service.LinkRefused) as caught:
            service.create_draft(self.user, chat='Farmacia Central', body='Otra cosa')
        self.assertEqual(caught.exception.code, 'on_its_way')
        self.assertEqual(WhatsAppDraft.objects.get(pk=sending['id']).status, 'sending')

    def test_daily_cap(self):
        made = self.draft()
        with override_settings(WHATSAPP_LINK_SENDS_PER_DAY=0):
            with self.assertRaises(service.LinkRefused):
                service.send_draft(self.user, made['id'], made['display_hash'])


class GuardTest(TestCase):
    def test_only_whatsapp_web_documents(self):
        self.assertTrue(web.allowed('https://web.whatsapp.com/'))
        self.assertFalse(web.allowed('https://evil.example/'))
        self.assertFalse(web.allowed('http://web.whatsapp.com/'))
        self.assertFalse(web.allowed('https://web.whatsapp.com.evil.example/'))

    def test_names_are_quoted_for_page_scripts(self):
        self.assertEqual(web._js('a"); alert(1); ("'), '"a\\"); alert(1); (\\""')

    def test_business_accounts_are_refused(self):
        user = SimpleNamespace(is_active=True)
        with self.assertRaises(service.LinkRefused):
            service.allowed(user, SimpleNamespace(pk=1), {'account_type': 'business'})


class FakeWeb:
    """A WhatsApp Web chat as send_text sees it: a box, sent bubbles, Enter."""

    def __init__(self, enter_sends=True, box='', pending=False):
        self.box, self.bubbles, self.enter_sends, self.entered, self.pending = box, 0, enter_sends, 0, pending

    def evaluate(self, expression):
        if 'msg-time' in expression:
            return self.pending
        if 'message-out' in expression:
            return self.bubbles
        if 'innerText' in expression:
            return self.box
        if 'getBoundingClientRect' in expression:
            return [10, 10]
        if "execCommand('selectAll'" in expression:
            self.box = ''
        return None

    def click(self, *_point):
        pass

    def pump(self, _seconds):
        pass

    def insert(self, text):
        self.box += text

    def call(self, *_args, **_kwargs):
        return {}

    def enter(self):
        self.entered += 1
        if self.enter_sends:
            self.bubbles += 1
            self.box = ''


@mock.patch.object(web, '_pace', lambda *a: None)
class SendTextTest(TestCase):
    def test_sent_means_a_new_bubble_and_an_empty_box(self):
        page = FakeWeb()
        self.assertTrue(web.send_text(page, 'Hola 👋 ¿tienen stock?'))
        self.assertEqual(page.entered, 1)

    def test_enter_that_did_nothing_is_not_sent(self):
        page = FakeWeb(enter_sends=False)
        self.patch_wait = mock.patch.object(web, 'CONFIRM_SECONDS', 0.01)
        self.patch_wait.start()
        self.addCleanup(self.patch_wait.stop)
        self.assertFalse(web.send_text(page, 'Gracias'))
        self.assertEqual(page.box, '')  # our text does not stay behind

    def test_a_bubble_still_on_the_clock_is_not_sent_yet(self):
        page = FakeWeb(pending=True)
        with mock.patch.object(web, 'CONFIRM_SECONDS', 0.01), mock.patch.object(web, 'PENDING_SECONDS', 0.01):
            self.assertEqual(web.send_text(page, 'Hola'), 'pending')
        self.assertEqual(page.entered, 1)

    def test_no_enter_when_no_longer_wanted(self):
        page = FakeWeb()
        with self.assertRaises(web.WebError) as caught:
            web.send_text(page, 'Hola', lambda: False)
        self.assertEqual(caught.exception.code, 'not_wanted')
        self.assertEqual((page.entered, page.box), (0, ''))

    def test_a_leftover_try_of_ours_is_taken_back_first(self):
        page = FakeWeb(box='Hola de un intento anterior')
        self.assertTrue(web.send_text(page, 'Hola'))
        self.assertEqual(page.entered, 1)

    def test_a_line_that_went_out_is_never_called_unsent(self):
        page = FakeWeb()
        page.insert = lambda text: (setattr(page, 'bubbles', 1), setattr(page, 'box', page.box + text + 'x'))
        with self.assertRaises(web.WebError) as caught:
            web.send_text(page, 'Hola')
        self.assertEqual(caught.exception.code, 'partial_sent')
        self.assertNotIn('partial_sent', web.BEFORE_ENTER)

    def test_the_code_screen_must_name_exactly_the_number(self):
        page = mock.Mock()
        texts = {'ok': 'Enter code on phone\nLinking WhatsApp account +591 71234567',
                 'prefixed': 'Enter code on phone\nLinking WhatsApp account +49 59171234567'}
        for case, expected in (('ok', 'ABCD1234'), ('prefixed', None)):
            page.evaluate.side_effect = lambda expression, text=texts[case]: (
                'ABCD1234' if 'groups' in expression else text)
            with mock.patch.object(web, 'wait_for', return_value='code'):
                if expected:
                    self.assertEqual(web.ask_for_code(page, PHONE), expected)
                else:
                    with self.assertRaises(web.WebError) as caught:
                        web.ask_for_code(page, PHONE)
                    self.assertEqual(caught.exception.code, 'phone_mismatch')

    def test_signed_in_number(self):
        page = mock.Mock()
        page.evaluate.return_value = '"59171234567:12@c.us"'
        self.assertEqual(web.signed_in_number(page), '59171234567')
        page.evaluate.return_value = ''
        self.assertEqual(web.signed_in_number(page), '')
