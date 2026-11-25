"""Who may start, watch and forget."""
from types import SimpleNamespace
from unittest import mock
from datetime import timedelta

from django.test import SimpleTestCase, override_settings
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
                           ('goal', {'goal': 'x'}), ('goal', {'goal': 'x' * 401})):
            with self.subTest(code=code, over=str(over)[:50]):
                self.refused(code, self.start, **over)
        self.assertFalse(AgentTask.objects.exists())

    def test_any_store_may_be_searched_whatever_its_country(self):
        # Founder, 2026-11-25: try any store; paying is what depends on the country (stop 'no_rail').
        task = self.start(site='mercadolibre.com.pe')
        self.assertEqual((task.state, task.country), ('queued', 'PE'))

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

    @override_settings(AGENT_TASKS_PER_DAY_PLUS=2)
    def test_a_purchase_set_aside_before_its_browser_opened_is_free(self):
        for goal in ('uno', 'otro', 'otro más'):   # the earlier ones never opened a browser
            AgentTask.objects.filter(user=self.user).update(created_at=timezone.now() - timedelta(minutes=2))
            self.start(goal=goal)
        AgentTask.objects.filter(user=self.user).update(provider='fake')   # now they all did
        AgentTask.objects.filter(user=self.user, state__in=AgentTask.ACTIVE).update(state='stopped')
        self.refused('daily_limit', self.start, goal='y otra')

    @override_settings(AGENT_TASKS_PER_DAY=2)
    def test_a_purchase_whose_browser_the_vendor_refused_is_free(self):
        # The founder's evening, 2026-11-24: two refused by the vendor's plan, then "limit reached".
        self.make_task(state='stopped', reason='busy', provider='')
        self.make_task(state='stopped', reason='busy', provider='')
        self.start(goal='chocolate')

    def test_nothing_is_started_without_a_browser_worker(self):
        self.worker.return_value = False
        self.refused('unavailable', self.start)
        self.assertFalse(AgentTask.objects.exists())

    @override_settings(AGENT_TASKS_PER_DAY_PLUS=1)
    def test_a_day_has_a_limit(self):
        self.make_task(state='stopped')
        self.refused('daily_limit', self.start)

    @override_settings(AGENT_TASKS_PER_DAY=1, AGENT_TASKS_PER_DAY_PLUS=3)
    def test_a_cuenta_inteligente_subscriber_has_more(self):
        self.make_task(state='stopped')
        with mock.patch('assistant.billing.has_plus', return_value=True):
            self.start(goal='otra')
            AgentTask.objects.filter(user=self.user, state__in=AgentTask.ACTIVE).update(state='stopped', provider='fake')
            self.make_task(state='stopped')
            with self.assertRaises(service.TaskRefused) as refused:
                self.start(goal='y otra')
        self.assertIn('3 compras', str(refused.exception))

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


class PayableTests(SimpleTestCase):
    def test_nobody_unverified_gets_the_buying_agent_whoever_would_pay(self):
        from payment_accounts.services import PaymentAccountError
        user, account = SimpleNamespace(is_active=True), SimpleNamespace()
        with mock.patch('payment_accounts.payment_intents.allowed', return_value=True), \
                mock.patch('security.minors.minor_refusal', return_value=''):
            with mock.patch('payment_accounts.schema._verified_identity', side_effect=PaymentAccountError('x')):
                with self.assertRaises(service.TaskRefused) as refused:
                    service.require_payable(account, user, 'MX', {})
            self.assertIn('Verifica tu identidad', str(refused.exception))
            with mock.patch('payment_accounts.schema._verified_identity', return_value=object()):
                service.require_payable(account, user, 'MX', {})   # no local account needed to start


class JourneyTests(SimpleTestCase):
    """Where the purchase is, for the card's journey (schema.stage_of), and what it says it is doing."""

    def at(self, **over):
        from agent_tasks.schema import stage_of
        task = SimpleNamespace(state='working', phase='', checkout_at=None, trace=[], **over) if 'state' not in over \
            else SimpleNamespace(**{'phase': '', 'checkout_at': None, 'trace': [], **over})
        return stage_of(task)

    def test_each_part_of_a_purchase_has_its_station(self):
        self.assertEqual(self.at(), 'search')
        self.assertEqual(self.at(state='needs_person'), 'search')   # picking a product
        self.assertEqual(self.at(state='working', phase='ordering',
                                 trace=[{'url': 'www.amazon.com.mx/gp/cart/view.html'}]), 'cart')
        self.assertEqual(self.at(state='working', phase='ordering',
                                 trace=[{'url': 'www.amazon.com.mx/checkout/p/p-1/spc'}]), 'checkout')
        self.assertEqual(self.at(state='working', phase='ordered'), 'pay')
        self.assertEqual(self.at(state='awaiting_code'), 'pay')
        self.assertEqual(self.at(state='payment_ready', phase='ordered'), 'done')
        # Where it stopped stays where it was.
        self.assertEqual(self.at(state='stopped', phase='ordering', trace=[{'url': 'tienda.mx/carrito'}]), 'cart')

    def test_what_it_says_it_is_doing_never_says_bought(self):
        from agent_tasks.schema import WORKING_AT
        self.assertEqual(set(WORKING_AT), {'search', 'cart', 'checkout', 'pay', 'manage'})
        for words in WORKING_AT.values():
            self.assertNotRegex(words.lower(), r'compr[eé]|pagu[eé]|pedido hecho|listo')


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

    def test_an_order_question_with_no_store_goes_to_the_last_purchase(self):
        self.make_task(state='stopped', site='amazon.com.mx', country='MX', checkout_at=timezone.now())
        with mock.patch('agent_tasks.service.require_payable'):
            result, task = self.call(['¿dónde está mi pedido?'], store=None, what='dónde está mi pedido', kind='manage')
        self.assertTrue(result['ok'], result)
        self.assertEqual((task.kind, task.site), ('manage', 'amazon.com.mx'))

    def test_a_purchase_is_still_a_purchase(self):
        with mock.patch('agent_tasks.service.require_payable'):
            result, task = self.call(['compra um cabo no mercado livre'])
        self.assertEqual(task.kind, 'buy')

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
    def test_a_refined_request_replaces_the_purchase_with_the_new_words(self):
        first = self.start(goal='un cargador')
        second = self.start(goal='un cargador USB-C')   # "que sea USB-C", seconds later
        first.refresh_from_db()
        self.assertEqual((first.state, first.reason), ('cancelled', 'replaced'))
        self.assertEqual((second.state, second.goal), ('queued', 'un cargador USB-C'))

    def test_one_never_started_within_minutes_is_not_started_late_even_with_a_worker(self):
        old = self.make_task(state='queued', provider='', session_id='', connect_url='', session_expires_at=None)
        AgentTask.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=11))
        young_user, young_account = self.person()
        young = self.make_task(user=young_user, account=young_account, state='queued', provider='', session_id='',
                               connect_url='', session_expires_at=None)
        AgentTask.objects.filter(pk=young.pk).update(created_at=timezone.now() - timedelta(minutes=9))
        service.sweep()   # a worker is alive here
        old.refresh_from_db()
        young.refresh_from_db()
        self.assertEqual((old.state, old.reason), ('stopped', 'unavailable'))
        self.assertEqual(young.state, 'queued')   # nine minutes: still its turn to start

    def test_forgetting_a_store_in_use_says_so(self):
        self.make_task(state='working')
        with self.assertRaises(service.TaskRefused) as refused:
            service.forget_store(self.account, self.user, SITE)
        self.assertEqual(refused.exception.code, 'store_busy')


class ChooseCartTests(ServiceBase):
    """Several products with quantities, confirmed once (spec decision 42), through the GraphQL mutation."""

    OPTIONS = [{'title': 'Chocolate Abuelita', 'price': 'R$ 89,00', 'cap': 'R$ 143,00', 'cap_amount': '143',
                'image': '', 'href': f'{BASE}/p/A'},
               {'title': 'Ibarra', 'price': 'R$ 112,50', 'cap': 'R$ 180,00', 'cap_amount': '180',
                'image': '', 'href': f'{BASE}/p/B'},
               {'title': 'Sem preço', 'price': 'consultar', 'cap': '', 'cap_amount': '', 'image': '',
                'href': f'{BASE}/p/C'}]

    def test_the_app_is_given_the_rule_and_each_read_price_to_show_the_top_total_first(self):
        from agent_tasks.schema import task_type
        shown = task_type(self.waiting(reason='choose', options=self.OPTIONS))
        self.assertEqual([option.unit for option in shown.options], ['89.00', '112.50', None])
        rule = shown.cap_rule
        self.assertEqual((rule.margin, rule.min_extra, rule.comma_decimals, rule.max_quantity), ('0.6', '30', True, 9))
        AgentTask.objects.update(state='working', reason='')
        self.assertIsNone(task_type(AgentTask.objects.get()).cap_rule)   # only while choosing

    def test_the_mutation_takes_indices_and_quantities_with_the_shown_top_total(self):
        from agent_tasks import schema
        task = self.waiting(reason='choose', options=self.OPTIONS)
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        with mock.patch('agent_tasks.schema._owner', return_value=(self.account, self.user)):
            answer = schema.ChooseAgentOptions.mutate(None, info, task.internal_id, items=[
                SimpleNamespace(index=1, quantity=3), SimpleNamespace(index=0, quantity=1)], cap='R$ 774,00')
            refused = schema.ChooseAgentOptions.mutate(None, info, task.internal_id, items=[
                SimpleNamespace(index=0, quantity=1)], cap=None)
        self.assertTrue(answer.success, answer.errors)
        task.refresh_from_db()
        # 89 + 3 × 112,50 = 426,50; + 60% = 682,40 → 683: the app sent another figure, so nothing is approved.
        self.assertNotIn('cap', task.order)
        self.assertEqual([(one['title'], one['quantity']) for one in task.order['cart']],
                         [('Chocolate Abuelita', 1), ('Ibarra', 3)])
        self.assertEqual((refused.success, refused.error_code), (False, 'not_open'))   # answered once

    def test_a_cart_with_an_unread_price_approves_no_top_total(self):
        task = self.waiting(reason='choose', options=self.OPTIONS)
        task = service.choose_cart(self.account, self.user, task.internal_id,
                                   [{'index': 0, 'quantity': 1}, {'index': 2, 'quantity': 1}], cap='R$ 143,00')
        self.assertNotIn('cap', task.order)
        self.assertEqual(task.pending_url, f'{BASE}/p/A')

    def test_the_exact_top_total_shown_approves_up_to_it(self):
        task = self.waiting(reason='choose', options=self.OPTIONS)
        task = service.choose_cart(self.account, self.user, task.internal_id,
                                   [{'index': 1, 'quantity': 3}, {'index': 0, 'quantity': 1}], cap='R$ 683,00')
        self.assertEqual((task.order['cap']['amount'], task.order['cap']['item']),
                         ('683', '1 × Chocolate Abuelita · 3 × Ibarra'))


class AccountWaitTests(ServiceBase):
    """A purchase the Cuenta inteligente pays: it waits for the account, never for the personal wallet's card."""

    HOLD = {'code': '646180157000000004', 'extra': {'amount_local': '925.00', 'reference': 'Pedido 1'},
            'since': '2026-11-24T00:00:00+00:00', 'until': '2099-01-01T00:00:00+00:00', 'tries': 0, 'units': '1'}

    def on_hold(self, **over):
        return self.waiting(reason='account_wait', checkout_at=timezone.now(),
                            order={'total': '$925.00', 'pay_hold': dict(self.HOLD),
                                   'account_wait': {'code': 'no_rule', 'amount_usd': '200.00', 'text': 'Activa'}},
                            **over)

    def test_ya_lo_hice_asks_the_account_again_through_the_runner(self):
        task = self.on_hold()
        self.refused('not_open', service.resume, self.account, self.user, task.internal_id)
        resumed = service.resume_payment(self.account, self.user, task.internal_id)
        self.assertEqual((resumed.state, resumed.reason, resumed.order['pay_hold']['asked']),
                         ('awaiting_code', '', True))
        self.kick.assert_called_with(task.pk)
        self.refused('not_open', service.resume_payment, self.account, self.user, task.internal_id)
        AgentTask.objects.filter(pk=task.pk).update(state='stopped')
        other = self.waiting(reason='approve')
        self.refused('not_open', service.resume_payment, self.account, self.user, other.internal_id)

    def test_the_card_states_and_the_wait_shown(self):
        from agent_tasks import schema
        task = self.on_hold()
        shown = schema.task_type(task)
        self.assertEqual((shown.reason, shown.message), ('account_wait', 'Activa'))
        figures, _ = service.account_wait(self.account, self.user, task.internal_id)
        self.assertEqual(figures['amount_usd'], '200.00')
        AgentTask.objects.filter(pk=task.pk).update(state='payment_ready', reason='account',
                                                    order={'total': '$925.00', 'account_usd': '52.48'})
        task.refresh_from_db()
        message = schema.task_type(task).message
        self.assertIn('Tu Cuenta inteligente está pagando', message)
        self.assertIn('US$52.48', message)
        self.assertNotIn('Preparé el pago', message)

    def test_the_sweep_rechecks_expires_and_never_posts_a_card_for_the_account(self):
        task = self.on_hold()
        AgentTask.objects.filter(pk=task.pk).update(updated_at=timezone.now() - timedelta(minutes=10))
        with mock.patch.object(service, 'account_changed', return_value=True) as changed, \
                mock.patch.object(service, 'worker_alive', return_value=True):
            service._sweep()
        changed.assert_called_once()
        task.refresh_from_db()
        self.assertEqual(task.state, 'awaiting_code')
        # Retrying with no browser: its expired session is not a reason to end it.
        AgentTask.objects.filter(pk=task.pk).update(session_expires_at=timezone.now() - timedelta(minutes=1),
                                                    updated_at=timezone.now())
        with mock.patch.object(service, 'worker_alive', return_value=True):
            service._sweep()
        task.refresh_from_db()
        self.assertEqual(task.state, 'awaiting_code')
        AgentTask.objects.filter(pk=task.pk).update(state='needs_person', reason='account_wait',
                                                    wait_until=timezone.now() - timedelta(seconds=1))
        with mock.patch.object(service, 'worker_alive', return_value=True):
            service._sweep()
        task.refresh_from_db()
        self.assertEqual((task.state, task.reason), ('stopped', 'account_timeout'))
        self.assertIn('sin pagar', self.post.call_args.args[1])
