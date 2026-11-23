"""Who may start, watch and forget."""
from types import SimpleNamespace
from unittest import mock
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from agent_tasks import assistant_tool, browsers, runner, service
from agent_tasks.models import AgentProfile, AgentTask
from agent_tasks.tests.base import BASE, RowsBase, SITE

REAL_WORKER_ALIVE = service.worker_alive   # before any test patches it
BUILD = {'HTTP_X_CONFIO_VERSION': '5.4.0', 'HTTP_X_CONFIO_BROWSER_TASKS': '1'}


class ServiceBase(RowsBase):
    def setUp(self):
        super().setUp()
        self.payable = self.patch('agent_tasks.service.require_payable')

    def refused(self, code, call, *args, **kwargs):
        with self.assertRaises(service.TaskRefused) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def start(self, account=None, user=None, **over):
        args = dict(goal='compra um cabo usb c', site=SITE, meta=BUILD)
        return service.start(account or self.account, user or self.user, **{**args, **over})

    def waiting(self, **over):
        fields = dict(state='needs_person', wait_until=timezone.now() + timedelta(minutes=4))
        return self.make_task(**{**fields, **over})


class StartTests(ServiceBase):
    def test_anyone_with_the_build_may_start(self):
        task = self.start()
        self.assertEqual((task.state, task.site, task.goal), ('queued', SITE, 'compra um cabo usb c'))
        self.kick.assert_called_once_with(task.pk)

    def test_refusals(self):
        for code, over in (('update_app', {'meta': {**BUILD, 'HTTP_X_CONFIO_VERSION': '5.3.9'}}),
                           ('update_app', {'meta': {}}),
                           ('update_app', {'meta': {'HTTP_X_CONFIO_VERSION': '5.4.0'}}),
                           ('store', {'site': 'mercadolivre-ofertas.com'}), ('store', {'site': 'itau.com.br'}),
                           ('country', {'site': 'tienda.com.pe'}), ('goal', {'goal': 'x'}), ('goal', {'goal': 'x' * 401})):
            with self.subTest(code=code, over=str(over)[:50]):
                self.refused(code, self.start, **over)
        self.assertFalse(AgentTask.objects.exists())

    def test_the_kill_switch(self):
        with override_settings(AGENT_TASKS_ENABLED=False):
            self.refused('unavailable', self.start)
        with override_settings(BROWSERBASE_API_KEY=''):
            self.refused('unavailable', self.start)
        self.qr.return_value = False
        self.refused('unavailable', self.start)

    def test_only_the_owners_personal_account(self):
        user, business = self.person('business')
        self.refused('not_personal', self.start, account=business, user=user)
        stranger, _ = self.person()
        self.refused('not_personal', self.start, user=stranger)

    def test_a_purchase_that_could_not_be_paid_is_not_started(self):
        self.payable.side_effect = service.TaskRefused('unavailable')
        self.refused('unavailable', self.start)
        self.assertFalse(AgentTask.objects.exists())

    def test_a_new_request_sets_the_earlier_purchase_aside_by_itself(self):
        earlier = self.start()
        AgentTask.objects.filter(pk=earlier.pk).update(created_at=timezone.now() - timedelta(minutes=2))
        later = self.start(goal='un chocolate amargo')
        earlier.refresh_from_db()
        self.assertEqual((earlier.state, earlier.reason), ('cancelled', 'replaced'))
        self.assertEqual(later.state, 'queued')
        # Its note says so; nothing says "tarea".
        said = [call.args[1] for call in self.post.call_args_list]
        self.assertTrue(any('Dejé la compra en' in text for text in said), said)
        self.assertFalse(any('tarea' in text.lower() for text in said), said)

    def test_nothing_is_set_aside_when_the_new_one_is_refused(self):
        earlier = self.start()
        AgentTask.objects.filter(pk=earlier.pk).update(created_at=timezone.now() - timedelta(minutes=2))
        self.payable.side_effect = service.TaskRefused('unavailable')
        self.refused('unavailable', self.start, goal='otra cosa')
        earlier.refresh_from_db()
        self.assertEqual(earlier.state, 'queued')

    def test_an_order_at_the_checkout_is_never_set_aside(self):
        earlier = self.waiting(checkout_at=timezone.now())
        with self.assertRaises(service.TaskRefused) as refused:
            self.start(goal='un cargador')
        self.assertEqual(refused.exception.code, 'checkout_open')
        self.assertIn(earlier.site, str(refused.exception))
        earlier.refresh_from_db()
        self.assertEqual(earlier.state, 'needs_person')

    @override_settings(AGENT_TASKS_PER_DAY=2)
    def test_a_purchase_set_aside_before_its_browser_opened_is_free(self):
        for goal in ('uno', 'otro', 'otro más'):   # the earlier ones never opened a browser
            AgentTask.objects.filter(user=self.user).update(created_at=timezone.now() - timedelta(minutes=2))
            self.start(goal=goal)
        AgentTask.objects.filter(user=self.user).update(provider='fake')   # now they all did
        AgentTask.objects.filter(user=self.user, state__in=AgentTask.ACTIVE).update(state='stopped')
        self.refused('daily_limit', self.start, goal='y otra')

    def test_nothing_is_started_without_a_browser_worker(self):
        self.worker.return_value = False
        self.refused('unavailable', self.start)
        self.assertFalse(AgentTask.objects.exists())

    @override_settings(AGENT_TASKS_PER_DAY=1)
    def test_a_day_has_a_limit(self):
        self.make_task(state='stopped')
        self.refused('daily_limit', self.start)

    @override_settings(AGENT_TASKS_MAX_CONCURRENT=1)
    def test_the_browsers_are_finite(self):
        user, account = self.person()
        self.make_task(user=user, account=account)
        self.refused('busy', self.start)

    @override_settings(AGENT_TASKS_ALL_PER_DAY=1)
    def test_everybody_together_has_a_daily_limit(self):
        user, account = self.person()
        self.make_task(user=user, account=account, state='stopped')
        self.refused('busy', self.start)


class PersonsTurnTests(ServiceBase):
    def test_the_live_view(self):
        task = self.waiting()
        self.vendor.live_view.return_value = ('https://live.invalid/x', f'{BASE}/login', 'tab-7')
        url, seconds, showing, _view = service.live_view(self.account, self.user, task.internal_id)
        self.assertEqual((url, showing), ('https://live.invalid/x', f'www.{SITE}'))
        self.assertLessEqual(seconds, 240)
        with override_settings(AGENT_TASKS_ENABLED=False):
            self.refused('unavailable', service.live_view, self.account, self.user, task.internal_id)
        task.refresh_from_db()
        self.assertEqual(task.shown_target, 'tab-7')
        self.vendor.live_view.return_value = ('https://live.invalid/x', 'https://evil.com/login', 'tab-9')
        self.refused('left_store', service.live_view, self.account, self.user, task.internal_id)
        task.refresh_from_db()
        self.assertEqual(task.shown_target, 'tab-7')

    def test_only_on_the_persons_turn_and_with_time_to_use_it(self):
        task = self.make_task(state='working')
        self.refused('not_open', service.live_view, self.account, self.user, task.internal_id)
        task.state, task.wait_until = 'needs_person', timezone.now() + timedelta(seconds=20)
        task.save()
        self.refused('not_open', service.live_view, self.account, self.user, task.internal_id)

    def test_the_payment_house_is_shown_only_in_the_checkout(self):
        task = self.waiting()
        self.vendor.live_view.return_value = ('https://live.invalid/x', 'https://www.mercadopago.com.br/checkout/v1', 't')
        self.refused('left_store', service.live_view, self.account, self.user, task.internal_id)
        task.checkout_at = timezone.now()
        task.save()
        self.assertTrue(service.live_view(self.account, self.user, task.internal_id))
        self.vendor.live_view.return_value = ('https://live.invalid/x', 'https://3ds.banco.example/auth', 't')
        self.assertEqual(service.live_view(self.account, self.user, task.internal_id)[2], '3ds.banco.example')

    def test_the_tab_read_is_the_one_on_the_persons_screen(self):
        task = self.waiting(checkout_at=timezone.now())
        self.vendor.live_view.return_value = ('https://live.invalid/x', f'{BASE}/pedido', 'tab-1')
        shown = service.live_view(self.account, self.user, task.internal_id)[3]
        # A later open whose answer the phone never got recorded another tab...
        self.vendor.live_view.return_value = ('https://live.invalid/y', f'{BASE}/pago', 'tab-2')
        service.live_view(self.account, self.user, task.internal_id)
        task.refresh_from_db()
        self.assertEqual(task.shown_target, 'tab-2')
        # ...but "Ya terminé" names the screen they saw: that tab is read.
        self.assertEqual(service.resume(self.account, self.user, task.internal_id, view=shown).state, 'awaiting_code')
        task.refresh_from_db()
        self.assertEqual(task.shown_target, 'tab-1')

    def test_a_view_not_signed_for_this_task_is_refused_and_nothing_moves(self):
        task = self.waiting(checkout_at=timezone.now())
        forged = [
            'tab-1',                                                  # unsigned
            service.view_token(SimpleNamespace(internal_id='00000000-0000-0000-0000-000000000000'), 'tab-1'),
            service.view_token(task, 'tab-1')[:-2] + 'xx',            # tampered
            service.view_token(task, ''),                             # no tab
        ]
        for view in forged:
            with self.subTest(view=view):
                self.refused('view', service.resume, self.account, self.user, task.internal_id, view)
                task.refresh_from_db()
                self.assertEqual(task.state, 'needs_person')
        # An older app sends none: the tab the last open recorded.
        self.assertEqual(service.resume(self.account, self.user, task.internal_id).state, 'awaiting_code')

    def test_resume_before_the_checkout_works_again(self):
        task = self.waiting()
        self.assertEqual(service.resume(self.account, self.user, task.internal_id).state, 'working')
        self.refused('not_open', service.resume, self.account, self.user, task.internal_id)

    def test_resume_after_it_only_reads_the_code(self):
        task = self.waiting(checkout_at=timezone.now())
        self.assertEqual(service.resume(self.account, self.user, task.internal_id).state, 'awaiting_code')

    def test_nobody_elses(self):
        task = self.waiting()
        user, account = self.person()
        for call in (service.get, service.cancel, service.resume, service.live_view):
            with self.subTest(call=call.__name__):
                self.refused('not_found', call, account, user, task.internal_id)

    def test_forgetting_deletes_at_the_vendor_first(self):
        AgentProfile.objects.create(user=self.user, site=SITE, provider='fake', external_id='p-1')
        self.vendor.delete_profile.side_effect = browsers.BrowserUnavailable('down')
        self.refused('unavailable', service.forget_store, self.account, self.user, SITE)
        self.assertEqual(service.stores(self.account, self.user), [SITE])
        self.vendor.delete_profile.side_effect = None
        service.forget_store(self.account, self.user, SITE)
        self.assertEqual(service.stores(self.account, self.user), [])


class SweepTests(ServiceBase):
    def test_expired_waits_end(self):
        task = self.waiting(wait_until=timezone.now() - timedelta(seconds=1))
        service.sweep()
        task.refresh_from_db()
        self.assertEqual((task.state, task.reason), ('stopped', 'person_timeout'))

    def test_the_sweep_never_undoes_a_resume(self):
        task = self.make_task(state='awaiting_code')
        self.assertFalse(runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person'}))

    def test_a_lost_step_runs_again_once_per_interval(self):
        task = self.make_task()
        AgentTask.objects.filter(pk=task.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
        service.sweep()
        service.sweep()
        self.kick.assert_called_once_with(task.pk)

    def test_a_deleted_person_leaves_nothing_behind(self):
        task = self.make_task()
        AgentProfile.objects.create(user=self.user, site=SITE, provider='fake', external_id='p-1')
        self.user.soft_delete()
        service.sweep()
        task.refresh_from_db()
        self.assertEqual((task.state, task.goal), ('cancelled', ''))
        self.assertFalse(AgentProfile.objects.exists())
        self.vendor.delete_profile.assert_called_once_with('p-1')

    def test_old_tasks_keep_no_personal_text(self):
        task = self.make_task(state='stopped', history=[{'did': 'x', 'result': 'ok'}], session_id='')
        AgentTask.objects.filter(pk=task.pk).update(created_at=timezone.now() - timedelta(days=31))
        service.sweep()
        task.refresh_from_db()
        self.assertEqual((task.goal, task.history), ('', []))

    def test_one_bad_row_does_not_stop_the_sweep(self):
        gone, _ = self.person()
        AgentProfile.objects.create(user=gone, site=SITE, provider='fake', external_id='p-9')
        gone.soft_delete()
        self.vendor.delete_profile.side_effect = RuntimeError('unexpected')
        task = self.waiting(wait_until=timezone.now() - timedelta(seconds=1))
        service.sweep()
        task.refresh_from_db()
        self.assertEqual(task.state, 'stopped')

    def test_a_soft_time_limit_ends_the_sweep(self):
        from celery.exceptions import SoftTimeLimitExceeded
        self.waiting(wait_until=timezone.now() - timedelta(seconds=1))
        self.patch('agent_tasks.runner.end', side_effect=SoftTimeLimitExceeded())
        with self.assertRaises(SoftTimeLimitExceeded):
            service.sweep()


class ToolTests(ServiceBase):
    def call(self, texts, **over):
        viewer = type('Viewer', (), {'account': self.account, 'user': self.user, 'request_meta': BUILD})()
        return assistant_tool.call(viewer, texts, **{'saw_web': False, **over})

    def test_the_goal_is_the_persons_words(self):
        result, task = self.call(['compra um cabo no mercado livre'], store='amazon.com.br')
        self.assertTrue(result['ok'])
        self.assertEqual((task.goal, task.site), ('compra um cabo no mercado livre', SITE))

    def test_never_after_reading_the_web_or_without_the_persons_words(self):
        for texts, over in ((['compra um cabo no mercado livre'], {'saw_web': True}), ([], {}),
                            (['compra um cabo'], {'store': 'evil-store.com'})):
            with self.subTest(over=over, texts=texts):
                result, task = self.call(texts, **over)
                self.assertFalse(result['ok'])
                self.assertIsNone(task)

    def test_what_to_buy_said_a_few_messages_before(self):
        # The founder's conversation, 2026-11-23: the thing and the country came before "do it for me".
        recent = ["I want to buy a chocolate from Mexico's available online stores", 'In my Mexican address',
                  'How about buying it from Amazon', 'You should do it for me']
        with mock.patch('agent_tasks.service.require_payable'):
            result, task = self.call(['You should do it for me', 'How about buying it from Amazon'], recent=recent,
                                     store='amazon.com')
        self.assertTrue(result['ok'], result)
        self.assertEqual((task.site, task.country), ('amazon.com.mx', 'MX'))
        self.assertIn('chocolate', task.goal)
        self.assertTrue(task.goal.endswith('You should do it for me'))

    def test_recent_words_that_are_not_this_message_are_not_used(self):
        result, task = self.call(['compra um cabo no mercado livre'], recent=['outra coisa', 'compra um cabo'])
        self.assertEqual(task.goal, 'compra um cabo no mercado livre')


class WorkerTests(ServiceBase):
    def test_the_workers_mark_lasts_a_while_and_a_step_leaves_one_too(self):
        from django.core.cache import cache
        with mock.patch.object(service, '_shared_cache', return_value=True):
            cache.delete(service.WORKER_KEY)
            self.assertFalse(REAL_WORKER_ALIVE())
            service.worker_seen()
            self.assertTrue(REAL_WORKER_ALIVE())
            cache.delete(service.WORKER_KEY)
            from agent_tasks import runner
            runner.run_step(999999)   # no such purchase: still proof a worker runs
            self.assertTrue(REAL_WORKER_ALIVE())

    def test_a_cache_only_this_process_sees_never_says_the_worker_is_gone(self):
        with mock.patch.object(service, '_shared_cache', return_value=False):
            self.assertTrue(REAL_WORKER_ALIVE())

    def test_one_heartbeat_at_a_time(self):
        from django.core.cache import cache
        cache.delete(service.HEARTBEAT_PENDING_KEY)
        with mock.patch('agent_tasks.tasks.heartbeat.apply_async') as sent:
            service.sweep()
            service.sweep()   # the first is unanswered: no second one piles up
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(sent.call_args.kwargs['queue'], 'browser')
        service.worker_seen()   # answered
        with mock.patch('agent_tasks.tasks.heartbeat.apply_async') as sent:
            service.sweep()
        self.assertEqual(sent.call_count, 1)

    def test_with_no_worker_only_a_purchase_that_never_opened_is_stopped(self):
        old = timezone.now() - timedelta(minutes=4)
        never = dict(state='queued', provider='', session_id='', connect_url='', session_expires_at=None)
        stuck = self.make_task(**never)
        people = [self.person() for _ in range(3)]
        opened = self.make_task(user=people[0][0], account=people[0][1], state='queued', provider='fake')
        confirmed = self.make_task(user=people[1][0], account=people[1][1], state='awaiting_code',
                                   checkout_at=timezone.now())
        fresh = self.make_task(user=people[2][0], account=people[2][1], **never)
        AgentTask.objects.exclude(pk=fresh.pk).update(created_at=old)
        self.worker.return_value = False
        with mock.patch('agent_tasks.tasks.heartbeat.apply_async'):
            service.sweep()
        for row in (stuck, opened, confirmed, fresh):
            row.refresh_from_db()
        self.assertEqual((stuck.state, stuck.reason), ('stopped', 'unavailable'))
        # Anything a worker touched, an order after the checkout, or a moment-old one: untouched here.
        self.assertEqual((opened.state, confirmed.state, fresh.state), ('queued', 'awaiting_code', 'queued'))
        self.assertTrue(any('Ahora no puedo abrir el navegador' in call.args[1]
                            for call in self.post.call_args_list))

    def test_the_chat_does_not_offer_purchases_without_a_worker(self):
        viewer = SimpleNamespace(user=self.user, account_type='personal', is_employee=False, request_meta=BUILD)
        self.assertTrue(assistant_tool.ready(viewer))
        self.worker.return_value = False
        self.assertFalse(assistant_tool.ready(viewer))


class SameStoreTests(ServiceBase):
    def test_a_follow_up_within_a_minute_is_the_same_purchase(self):
        first = self.start()
        with self.assertRaises(service.TaskRefused) as refused:
            self.start(goal='y que sea USB-C')
        self.assertEqual(refused.exception.code, 'just_started')
        first.refresh_from_db()
        self.assertEqual(first.state, 'queued')

    def test_one_never_started_within_minutes_is_not_started_late_even_with_a_worker(self):
        old = self.make_task(state='queued', provider='', session_id='', connect_url='', session_expires_at=None)
        AgentTask.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=11))
        service.sweep()   # a worker is alive here
        old.refresh_from_db()
        self.assertEqual((old.state, old.reason), ('stopped', 'unavailable'))

    def test_forgetting_a_store_in_use_says_so(self):
        self.make_task(state='working')
        with self.assertRaises(service.TaskRefused) as refused:
            service.forget_store(self.account, self.user, SITE)
        self.assertEqual(refused.exception.code, 'store_busy')
