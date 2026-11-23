"""A step before the checkout, and after it: where there is no agent at all."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from agent_tasks import agent, browsers, countries, runner, service
from agent_tasks.cdp import CdpError
from agent_tasks.models import AgentProfile, AgentTask
from agent_tasks.tests.base import (BASE, CODE, CODE_TEXT, RowsBase, SITE, cart_button, element, link, picture,
                                    search_box, snap)


class StepBase(RowsBase):
    def setUp(self):
        super().setUp()
        self.connection = self.patch('agent_tasks.runner.Page')
        self.browser = self.connection.return_value.__enter__.return_value
        self.browser.refused_document = self.browser.refused_send = False
        self.browser.capture.return_value = (picture(), picture())
        self.read = self.patch('agent_tasks.qr.read', return_value=[])
        self.reader = self.patch('agent_tasks.page.Reader').return_value
        self.reader.press.return_value = self.reader.search.return_value = ''
        self.reader.address = None
        self.decide = self.patch('agent_tasks.agent.decide')
        self.payable = self.patch('agent_tasks.service.require_payable')

    def step(self, task, seen=None):
        if seen is not None:
            self.reader.read.return_value = seen
        runner.run_step(task.pk)
        task.refresh_from_db()
        return task

    def untouched(self):
        self.reader.press.assert_not_called()
        self.reader.search.assert_not_called()
        self.browser.goto.assert_not_called()


class LoopTests(StepBase):
    def test_a_queued_task_opens_its_own_stores_profile(self):
        self.vendor.create_profile.return_value = 'profile-1'
        self.vendor.open.return_value = browsers.Session('s-2', 'wss://b', timezone.now() + timedelta(minutes=20))
        task = self.step(self.make_task(state='queued', session_id='', connect_url='', session_expires_at=None))
        self.assertEqual((task.state, task.session_id), ('working', 's-2'))
        self.assertEqual(AgentProfile.objects.get(user=self.user, site=SITE).external_id, 'profile-1')
        self.browser.goto.assert_called_once_with(f'https://{SITE}/')
        self.decide.assert_not_called()

    def test_a_held_lease_or_a_spent_token_is_no_step(self):
        task = self.make_task(steps=4, lease_until=timezone.now() + timedelta(seconds=60))
        self.step(task)
        task.lease_until = None
        task.save()
        runner.run_step(task.pk, 3)
        self.reader.read.assert_not_called()

    def test_a_task_waiting_for_the_person_runs_no_step(self):
        for state in ('needs_person', 'stopped', 'payment_ready'):
            with self.subTest(state=state):
                task = self.make_task(state=state)
                self.step(task)
                self.reader.read.assert_not_called()
                task.state = 'cancelled'
                task.save()

    def test_a_link_is_opened_by_its_address_and_never_clicked(self):
        self.decide.return_value = ('click', {'ref': 0})
        self.step(self.make_task(), snap(elements=[link('Garrafa 750 ml')]))
        self.browser.goto.assert_called_once_with(f'{BASE}/p/MLB1')
        self.reader.press.assert_not_called()

    def test_add_to_cart_is_pressed(self):
        self.decide.return_value = ('click', {'ref': 0})
        button = cart_button()
        self.step(self.make_task(), snap(elements=[button]))
        self.reader.press.assert_called_once_with(button)

    def test_a_search(self):
        self.decide.return_value = ('search', {'ref': 0, 'text': 'garrafa térmica'})
        box = search_box()
        self.step(self.make_task(), snap(elements=[box]))
        self.reader.search.assert_called_once_with(box, 'garrafa térmica')

    def test_what_orders_is_refused_whatever_the_model_names(self):
        for item in (element('Comprar agora'), element('Confirmar'), link('Comprar agora'),
                     link('Ver', '/gz/checkout/buy')):
            with self.subTest(item=item['label']):
                self.decide.return_value = ('click', {'ref': 0})
                task = self.step(self.make_task(), snap(elements=[item]))
                self.untouched()
                self.assertIn('refused', task.history[-1]['result'])
                task.state = 'cancelled'
                task.save()

    def test_an_action_the_agent_does_not_have_does_nothing(self):
        for name in ('pay', 'open_url', 'type', 'choose', 'propose_order', 'evaluate'):
            with self.subTest(name=name):
                self.decide.return_value = (name, {'ref': 0, 'url': f'{BASE}/x', 'text': 'x'})
                task = self.step(self.make_task(), snap(elements=[element('Adicionar ao carrinho')]))
                self.untouched()
                task.state = 'cancelled'
                task.save()

    def test_leaving_the_store_goes_back_home_without_asking_the_model(self):
        self.step(self.make_task(), snap(url='https://evil.com/'))
        self.decide.assert_not_called()
        self.browser.goto.assert_called_once_with(f'https://{SITE}/')

    def test_a_block_stops_without_another_try(self):
        task = self.step(self.make_task(), snap('Access denied'))
        self.assertEqual((task.state, task.reason), ('stopped', 'blocked'))
        self.decide.assert_not_called()
        self.vendor.close.assert_called_once_with('s-1')

    def test_a_sign_in_is_handed_over_once_by_itself(self):
        task = self.step(self.make_task(), snap(secret=True))
        self.assertEqual((task.state, task.reason), ('needs_person', 'login'))
        self.decide.assert_not_called()
        task.state = 'working'  # they said they are done, and the header's box is still there
        task.save()
        self.decide.return_value = ('wait', {})
        self.assertEqual(self.step(task, snap(secret=True)).state, 'working')
        self.decide.assert_called_once()

    def test_a_turn_too_short_to_open_is_not_handed_over(self):
        task = self.make_task(session_expires_at=timezone.now() + timedelta(seconds=80))
        self.assertEqual(self.step(task, snap(secret=True)).reason, 'session_expired')

    def test_a_cancellation_during_a_step_wins_over_its_click(self):
        task = self.make_task()

        def cancelled_meanwhile(*args):
            service.cancel(self.account, self.user, task.internal_id)
            return 'click', {'ref': 0}

        self.decide.side_effect = cancelled_meanwhile
        self.step(task, snap(elements=[cart_button()]))
        self.untouched()
        self.assertEqual(task.state, 'cancelled')

    def test_ceilings_stop_it(self):
        for over in ({'steps': 45}, {'cost_usd': Decimal('1.00')}):
            with self.subTest(over=over):
                self.assertEqual(self.step(self.make_task(**over)).reason, 'too_long')

    def test_three_failures_end_it(self):
        self.decide.side_effect = agent.AgentUnavailable('down')
        task = self.make_task()
        for _ in range(runner.MAX_FAILURES):
            self.step(task, snap())
        self.assertEqual((task.state, task.reason), ('stopped', 'error'))

    def test_a_full_vendor_says_busy(self):
        self.vendor.create_profile.side_effect = browsers.BrowserUnavailable('quota', 'quota')
        task = self.step(self.make_task(state='queued', session_id='', connect_url='', session_expires_at=None))
        self.assertEqual(task.reason, 'busy')


class HandOverTests(StepBase):
    def test_a_checkout_is_the_persons_without_asking_the_model(self):
        for seen in (snap(url=f'{BASE}/checkout/review'), snap(url=f'{BASE}/r', elements=[element('Confirmar pedido')]),
                     snap(url='https://www.mercadopago.com.br/checkout/v1/redirect')):
            with self.subTest(url=seen.url):
                task = self.step(self.make_task(), seen)
                self.assertEqual((task.state, task.reason), ('needs_person', 'checkout'))
                self.assertIsNotNone(task.checkout_at)
                self.decide.assert_not_called()
                self.untouched()
                task.state = 'cancelled'
                task.save()

    def test_the_model_hands_over_when_the_item_is_there(self):
        self.decide.return_value = ('ready_for_checkout', {})
        task = self.step(self.make_task(), snap())
        self.assertEqual((task.state, task.reason), ('needs_person', 'checkout'))

    def test_the_checkout_says_what_they_have_to_pay_with(self):
        self.held.return_value = Decimal('12.3')
        self.step(self.make_task(), snap(url=f'{BASE}/checkout'))
        text = self.post.call_args.args[1]
        self.assertIn('Tienes US$12.30 en dólares', text)
        # The lock screen never shows a balance.
        self.assertNotIn('US$', self.post.call_args.kwargs['push_body'])
        AgentTask.objects.filter(user=self.user).update(state='cancelled')
        # Unknown: no figure at all, never a confident zero.
        self.held.return_value = None
        self.step(self.make_task(), snap(url=f'{BASE}/checkout'))
        self.assertNotIn('Tienes', self.post.call_args.args[1])

    def test_nobody_is_asked_to_confirm_what_they_could_not_pay(self):
        self.payable.side_effect = service.TaskRefused('unavailable')
        task = self.step(self.make_task(), snap(url=f'{BASE}/checkout'))
        self.assertEqual((task.reason, task.checkout_at), ('cannot_pay', None))


class AfterCheckoutTests(StepBase):
    def setUp(self):
        super().setUp()
        self.prepare = self.patch('payment_accounts.payment_intents.prepare')
        self.cancel = self.patch('payment_accounts.payment_intents.cancel')
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab-1')

    def intent(self, currency='BRL', exact=True, level='institution_charge'):
        self.prepare.return_value = SimpleNamespace(
            currency=currency, amount_exact=exact, amount_local=Decimal('91.90'), internal_id='intent-1',
            payee_level=level, rail_method_id='br_qr')

    def test_the_agent_is_out(self):
        self.decide.return_value = ('click', {'ref': 0})
        for seen in (snap(elements=[element('Confirmar compra')]), snap(url='https://evil.com/'), snap(secret=True),
                     snap('Access denied'), snap(elements=[element('Adicionar ao carrinho')])):
            with self.subTest(url=seen.url, text=seen.text):
                self.step(self.task, seen)
                self.decide.assert_not_called()
                self.untouched()

    def test_the_qr_on_their_screen_becomes_a_payment_card(self):
        self.intent()
        self.read.return_value = [(CODE, 200), ('https://loja.com.br/app', 90)]
        saved = {}
        real = runner.Step.save

        def save(step, **fields):
            if 'payment_intent' in fields:
                saved.update(fields)
                fields.pop('payment_intent')
            return real(step, **fields)

        with mock.patch.object(runner.Step, 'save', save):
            self.step(self.task)
        self.assertEqual((self.task.state, saved['state']), ('payment_ready', 'payment_ready'))
        self.browser.capture.assert_called_once_with('tab-1')
        self.assertEqual(self.prepare.call_args.args[:3], (self.account, self.user, CODE))
        self.assertEqual(self.prepare.call_args.kwargs['request'], {'method_id': 'br_qr', 'meta': {}})
        self.decide.assert_not_called()

    def test_a_card_the_balance_does_not_cover_says_what_is_missing(self):
        intent = SimpleNamespace(total_usd=Decimal('20.00'), internal_id='intent-1')
        self.held.return_value = Decimal('15.501')
        runner.post_payment(self.task, intent)
        text = self.post.call_args.args[1]
        self.assertIn('te faltan US$4.50', text)
        self.assertNotIn('faltan', self.post.call_args.kwargs['push_body'])
        self.assertEqual(self.post.call_args.kwargs['intent'], intent)  # the card is still there
        self.held.return_value = Decimal('25')
        runner.post_payment(self.task, intent)
        self.assertNotIn('faltan', self.post.call_args.args[1])

    def test_no_page_is_ever_read_for_a_code(self):
        self.step(self.task, snap(f'{CODE_TEXT}\n{CODE}', f'{BASE}/pedido/1'))
        self.reader.read.assert_not_called()
        self.prepare.assert_not_called()
        self.assertEqual((self.task.state, self.task.reason), ('needs_person', 'code'))

    def refused(self, reason, **fields):
        self.task.state = 'awaiting_code'
        for key, value in fields.items():
            setattr(self.task, key, value)
        self.task.save()
        self.step(self.task)
        self.prepare.assert_not_called()
        self.assertEqual((self.task.state, self.task.reason), ('needs_person', reason))

    def test_only_one_whole_pix_code_counts(self):
        for found in ([], [('https://loja.com.br/app', 200)], [(CODE[:-1] + '0', 200)], [(f'paga aqui {CODE}', 200)]):
            with self.subTest(found=str(found)[:30]):
                self.read.return_value = found
                self.refused('code')

    def test_two_pix_qrs_are_not_guessed_between(self):
        self.read.return_value = [(CODE, 200), ('other', 200)]
        with mock.patch('payment_accounts.payment_intents.find_pix_codes', side_effect=lambda text: [text]):
            self.refused('several')

    def test_both_pictures_say_the_same(self):
        self.read.side_effect = [[(CODE, 200)], []]
        self.refused('screen')

    def test_only_the_tab_they_were_shown(self):
        self.read.return_value = [(CODE, 200)]
        self.refused('screen', shown_target='')
        self.browser.capture.assert_not_called()

    def test_a_tab_that_went_or_moved(self):
        self.browser.capture.return_value = None
        self.refused('screen')

    def test_only_on_the_stores_pages(self):
        self.read.return_value = [(CODE, 200)]
        for url in ('https://evil.com/rastreio', 'about:blank', '', 'https://www.mercadopago.com.br/checkout/v1/redirect'):
            with self.subTest(url=url):
                self.browser.capture.return_value = (picture(url), picture(url))
                self.refused('offsite')

    def test_never_on_a_page_the_agent_read(self):
        self.read.return_value = [(CODE, 200)]
        for url in (f'{BASE}/p/1', f'{BASE}/p/1?variation=2', f'{BASE}/p/1#reviews', f'{BASE}/s'):
            with self.subTest(url=url):
                self.browser.capture.return_value = (picture(url), picture(url))
                self.refused('code', visited_pages=[runner.same_page(f'{BASE}/p/1'), runner.same_page(f'{BASE}/s')])

    def test_a_photo_sized_qr_is_never_taken(self):
        for found in ([(CODE, 75)], [(CODE, 120)]):
            with self.subTest(found=found):
                self.read.return_value = found
                self.refused('several')

    def test_an_amount_a_known_payment_house_signed_counts(self):
        self.intent(level='institution_amount')
        self.read.return_value = [(CODE, 172)]
        with mock.patch.object(runner.Step, 'save', lambda step, **fields: None):
            self.step(self.task)
        self.cancel.assert_not_called()

    def test_a_payment_qr_of_ordinary_size_counts(self):
        self.intent()
        self.read.return_value = [(CODE, 110)]
        shot = picture(words=(f'Copia e cola: {CODE}', CODE), fields=(CODE,))
        self.browser.capture.return_value = (shot, shot)
        with mock.patch.object(runner.Step, 'save', lambda step, **fields: None):
            self.step(self.task)
        self.assertEqual(self.prepare.call_args.args[2], CODE)
        self.cancel.assert_not_called()

    def test_only_a_payee_its_bank_signs(self):
        self.read.return_value = [(CODE, 200)]
        for level in ('signed_amount', 'signed_charge', 'self_reported', 'unverified'):
            with self.subTest(level=level):
                self.intent(level=level)
                self.task.state = 'awaiting_code'
                self.task.save()
                self.step(self.task)
                # Prepared to read who is paid, then dropped: no card is posted.
                self.assertEqual((self.task.state, self.task.reason), ('needs_person', 'unsigned'))
                self.cancel.assert_called_with(self.account, 'intent-1')

    def test_an_unexact_or_foreign_charge_is_cancelled(self):
        for over in ({'currency': 'USD'}, {'exact': False}):
            with self.subTest(over=over):
                self.intent(**over)
                self.read.return_value = [(CODE, 200)]
                self.task.state, self.task.session_id = 'awaiting_code', 's-1'
                self.task.save()
                self.step(self.task)
                self.assertEqual((self.task.state, self.task.reason), ('needs_person', 'code_refused'))
                self.cancel.assert_called_with(self.account, 'intent-1')

    def test_a_refused_code_is_never_handed_on(self):
        from payment_accounts.services import PaymentAccountError
        self.prepare.side_effect = PaymentAccountError('No puedo verificar quién cobra.')
        self.read.return_value = [(CODE, 200)]
        self.step(self.task)
        self.assertEqual((self.task.state, self.task.reason), ('needs_person', 'code_refused'))
        self.vendor.close.assert_not_called()
        self.assertNotIn(CODE, f'{self.post.call_args.args[1]} {self.task.history}')

    def test_an_outage_is_waited_out(self):
        self.prepare.side_effect = RuntimeError('provider down')
        self.read.return_value = [(CODE, 200)]
        self.step(self.task)
        self.assertEqual((self.task.state, self.task.reason), ('needs_person', 'retry'))

    def test_the_agents_ceilings_do_not_stop_the_reading(self):
        self.task.steps = 60
        self.task.save()
        self.assertEqual(self.step(self.task, snap()).reason, 'code')

    def test_a_message_over_the_page_gives_the_screen_straight_back(self):
        self.browser.capture.side_effect = CdpError('took too long')
        self.step(self.task)
        self.assertEqual((self.task.state, self.task.reason), ('needs_person', 'screen'))
        self.vendor.close.assert_not_called()

    def test_stopping_says_there_may_be_an_order(self):
        self.task.session_expires_at = timezone.now()
        self.task.save()
        self.step(self.task)
        self.assertIn('Si ya confirmaste el pedido', self.post.call_args.args[1])

    def test_the_connection_only_looks(self):
        self.step(self.task, snap())
        self.assertIs(self.connection.call_args.kwargs['active'], False)
        self.browser.guard_documents.assert_not_called()


class RoundThreeStepTests(StepBase):
    def test_a_sign_in_turn_never_takes_a_code(self):
        self.read.return_value = [(CODE, 200)]
        self.decide.return_value = ('wait', {})
        task = self.make_task(history=[{'did': runner.RESUMED, 'result': 'done'}])
        self.assertEqual(self.step(task, snap(CODE)).state, 'working')
        self.assertIsNone(task.checkout_at)
        self.browser.capture.assert_not_called()

    def test_a_press_that_went_on_to_the_checkout_is_not_pressed_again(self):
        self.decide.return_value = ('click', {'ref': 0})
        self.reader.press.side_effect = lambda button: setattr(self.browser, 'refused_document', True) or ''
        task = self.step(self.make_task(), snap(url=f'{BASE}/p/1', elements=[cart_button()]))
        self.assertEqual((task.state, task.reason), ('needs_person', 'checkout'))

    def test_a_lost_answer_is_not_pressed_again(self):
        self.decide.return_value = ('click', {'ref': 0})
        self.reader.press.side_effect = CdpError('lost')
        task = self.make_task()
        seen = snap(url=f'{BASE}/p/1', elements=[cart_button()])
        self.step(task, seen)
        self.step(task, seen)
        self.assertEqual(self.reader.press.call_count, 1)

    def test_a_home_that_keeps_sending_us_away_ends_it(self):
        history = [{'did': 'left the store', 'result': 'x'}] * runner.MAX_LEFT_STORE
        self.assertEqual(self.step(self.make_task(history=history), snap(url='https://evil.com/')).reason, 'cannot_do')

    def test_choice_details_and_consent_do_not_come_back_to_the_agent(self):
        for kind in ('choice', 'details', 'consent'):
            with self.subTest(kind=kind):
                self.decide.return_value = ('ask_person', {'kind': kind})
                task = self.step(self.make_task(), snap())
                self.assertEqual((task.state, task.reason), ('needs_person', kind))
                self.assertIsNotNone(task.checkout_at)
                task.state = 'cancelled'
                task.save()

    def test_a_sign_in_comes_back(self):
        self.decide.return_value = ('ask_person', {'kind': 'login'})
        self.assertIsNone(self.step(self.make_task(), snap()).checkout_at)

    def test_a_checkout_turn_is_long_enough_or_not_started(self):
        task = self.make_task(session_expires_at=timezone.now() + timedelta(seconds=200))
        self.assertEqual(self.step(task, snap(url=f'{BASE}/checkout')).reason, 'session_expired')
        self.assertIsNone(task.checkout_at)

    def test_documents_are_checked_while_the_agent_works(self):
        self.decide.return_value = ('wait', {})
        self.step(self.make_task(), snap())
        allowed = self.browser.guard_documents.call_args.args[0]
        self.assertFalse(allowed(f'{BASE}/gz/checkout/buy?item=9', 'GET'))
        self.assertTrue(allowed(f'{BASE}/p/1', 'GET'))
        self.assertIs(self.connection.call_args.kwargs['active'], True)


class RoundFiveStepTests(StepBase):
    def setUp(self):
        super().setUp()
        self.prepare = self.patch('payment_accounts.payment_intents.prepare')

    def test_every_page_the_agent_reads_is_remembered(self):
        self.decide.return_value = ('wait', {})
        task = self.step(self.make_task(), snap(url=f'{BASE}/p/1?x=1'))
        self.assertEqual(task.visited_pages, [runner.same_page(f'{BASE}/p/1')])

    def test_a_checkouts_own_page_may_show_the_qr_later(self):
        task = self.step(self.make_task(visited_pages=[runner.same_page(f'{BASE}/checkout/review')]),
                         snap(url=f'{BASE}/checkout/review'))
        self.assertEqual(task.visited_pages, [])

    def test_the_tab_they_kept_open_is_still_read(self):
        self.decide.return_value = ('ready_for_checkout', {})
        task = self.step(self.make_task(shown_target='login-tab'), snap(url=f'{BASE}/p/1'))
        self.assertEqual(task.shown_target, 'login-tab')

    def test_a_press_not_sent_may_be_tried_again(self):
        self.decide.return_value = ('click', {'ref': 0})
        self.reader.press.side_effect = ['changed', '']
        task = self.make_task()
        seen = snap(url=f'{BASE}/p/1', elements=[cart_button()])
        self.step(task, seen)
        self.step(task, seen)
        self.assertEqual(self.reader.press.call_count, 2)

    def test_another_product_may_be_added(self):
        self.decide.return_value = ('click', {'ref': 0})
        task = self.make_task()
        self.step(task, snap(url=f'{BASE}/p/1', elements=[cart_button()]))
        self.step(task, snap(url=f'{BASE}/p/2', elements=[cart_button()]))
        self.assertEqual(self.reader.press.call_count, 2)

    @override_settings(AGENT_TASKS_HOLD_SECONDS=30, AGENT_TASKS_MAX_STEPS=4)
    def test_one_connection_works_several_steps_and_keeps_the_ceiling(self):
        self.decide.return_value = ('wait', {})
        task = self.step(self.make_task(), snap())
        self.assertEqual((task.reason, self.decide.call_count, self.connection.call_count), ('too_long', 4, 1))
        self.browser.guard_documents.assert_called_once()


class RoundSixStepTests(StepBase):
    def test_the_press_sends_only_to_the_cart_it_was_judged_for(self):
        self.decide.return_value = ('click', {'ref': 0})
        button = cart_button()
        self.step(self.make_task(), snap(url=f'{BASE}/p/1', elements=[button]))
        allowed = self.browser.only_sending.call_args_list[0].args[0]
        self.assertTrue(allowed('POST', button['action']))
        self.assertFalse(allowed('POST', f'{BASE}/checkout/place-order'))
        self.assertIsNone(self.browser.only_sending.call_args.args[0])

    @override_settings(AGENT_TASKS_HOLD_SECONDS=30)
    def test_the_kill_switch_is_seen_inside_a_hold(self):
        def switched_off(*args):
            from django.conf import settings
            settings.AGENT_TASKS_ENABLED = False
            return 'wait', {}

        self.decide.side_effect = switched_off
        self.assertEqual(self.step(self.make_task(), snap()).reason, 'busy')
        self.decide.assert_called_once()


class RoundSevenStepTests(StepBase):
    def test_a_form_search_is_opened_as_an_address(self):
        self.decide.return_value = ('search', {'ref': 0, 'text': 'garrafa'})
        for address, opened in ((f'{BASE}/jm/search?as_word=garrafa', True), (f'{BASE}/checkout?q=garrafa', False)):
            with self.subTest(address=address):
                self.browser.goto.reset_mock()
                self.reader.search.side_effect = lambda *a: setattr(self.reader, 'address', address) or ''
                task = self.step(self.make_task(), snap(elements=[search_box()]))
                self.assertEqual(self.browser.goto.called, opened)
                task.state = 'cancelled'
                task.save()

    def test_an_add_that_was_stopped_is_never_called_done(self):
        self.decide.return_value = ('click', {'ref': 0})
        self.reader.press.side_effect = lambda button: setattr(self.browser, 'refused_send', True) or ''
        task = self.step(self.make_task(), snap(url=f'{BASE}/p/1', elements=[cart_button()]))
        self.assertEqual((task.state, task.reason), ('needs_person', 'checkout'))
        self.assertIn('Puede que no', self.post.call_args.args[1])


class PageIdentityTests(StepBase):
    def test_routes_tell_pages_apart_and_links_do_not(self):
        same = runner.same_page
        self.assertEqual(same(f'{BASE}/p/1'), same(f'{BASE}/p/1?x=1#reviews'))
        self.assertNotEqual(same(f'{BASE}/index.php?route=product/product&product_id=4'),
                            same(f'{BASE}/index.php?route=checkout/success'))
        self.assertNotEqual(same(f'{BASE}/#/produto/1'), same(f'{BASE}/#/pedido/9'))
        self.assertEqual(same(f'{BASE}/index.php?route=product/product&product_id=4'),
                         same(f'{BASE}/index.php?route=product/product&product_id=4&tracking=x'))


def with_crc(body):
    """A Pix code body with its CRC16-CCITT, as a real code carries it."""
    value = 0xFFFF
    for byte in body.encode():
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ 0x1021) & 0xFFFF if value & 0x8000 else (value << 1) & 0xFFFF
    return f'{body}{value:04X}'


class WrittenCodeTests(StepBase):
    def setUp(self):
        super().setUp()
        self.prepare = self.patch('payment_accounts.payment_intents.prepare')
        self.read = self.patch('agent_tasks.qr.read')
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab')

    def outcome(self, found, words, fields=()):
        self.read.return_value = found
        self.browser.capture.return_value = (picture(words=words, fields=fields), picture(words=words, fields=fields))
        self.task.state = 'awaiting_code'
        self.task.save()
        with mock.patch.object(runner.Step, 'save', lambda step, **fields: AgentTask.objects.filter(
                pk=step.task.pk).update(**{k: v for k, v in fields.items() if k != 'payment_intent'})):
            self.step(self.task)
        return self.task.reason if self.task.state == 'needs_person' else 'prepared'

    def test_a_seller_qr_beside_the_stores_written_code(self):
        self.assertEqual(countries.RAILS['BR'].codes([with_crc(CODE[:-4])]), {CODE})
        other = with_crc(CODE[:-4].replace('4d8f085b', '99999999'))
        self.assertEqual(self.outcome([(other, 139)], (f'Copia e cola {CODE}',)), 'several')

    def test_the_stores_qr_beside_its_written_code(self):
        self.prepare.return_value = SimpleNamespace(currency='BRL', amount_exact=True, amount_local=Decimal('9'),
                                                    internal_id='i', payee_level='institution_amount',
                                                    rail_method_id='br_qr')
        self.assertEqual(self.outcome([(CODE, 110)], (f'Copia e cola {CODE}',), fields=(f' {CODE} ',)), 'prepared')

    def test_a_code_in_a_product_title_does_not_lower_the_floor(self):
        # The store's own code lives only in a JS property; the seller's code is in the title.
        self.assertEqual(self.outcome([(CODE, 120)], (f'Garrafa azul {CODE}',)), 'several')
        self.assertEqual(self.outcome([(CODE, 120)], (CODE,)), 'several')

    def test_with_no_written_code_only_a_large_qr(self):
        self.assertEqual(self.outcome([(CODE, 120)], ('Pague com Pix',)), 'several')
        self.prepare.return_value = SimpleNamespace(currency='BRL', amount_exact=True, amount_local=Decimal('9'),
                                                    internal_id='i', payee_level='institution_amount',
                                                    rail_method_id='br_qr')
        self.assertEqual(self.outcome([(CODE, 150)], ('Pague com Pix',)), 'prepared')


class SamePageTests(SimpleTestCase):
    def test_route_keys_in_any_order_or_case(self):
        self.assertEqual(runner.same_page(f'{BASE}/s?p=1&product=x'), runner.same_page(f'{BASE}/s?Product=x&p=1&utm=a'))
        self.assertNotEqual(runner.same_page(f'{BASE}/s?p=1'), runner.same_page(f'{BASE}/s?p=2'))


BO_QR = 'QRSIMPLE:00020101021226480015bo.bnb.qrsimple0112100000123452040000530306854031505802BO'


class BoliviaTests(StepBase):
    """Bolivia's rail: the provider decodes the bank QR and names who is paid."""

    def setUp(self):
        super().setUp()
        self.prepare = self.patch('payment_accounts.payment_intents.prepare')
        self.read = self.patch('agent_tasks.qr.read')
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab',
                                   site='tienda.com.bo', country='BO', app_version='5.4.2')

    def outcome(self, found, level='provider_named', currency='BOB', method='bo_qr'):
        self.prepare.return_value = SimpleNamespace(currency=currency, amount_exact=True, amount_local=Decimal('150'),
                                                    internal_id='i', payee_level=level, rail_method_id=method)
        self.read.return_value = found
        shot = picture(url='https://tienda.com.bo/pedido/1')
        self.browser.capture.return_value = (shot, shot)
        self.task.state = 'awaiting_code'
        self.task.save()
        with mock.patch.object(runner.Step, 'save', lambda step, **fields: AgentTask.objects.filter(
                pk=step.task.pk).update(**{k: v for k, v in fields.items() if k != 'payment_intent'})), \
                mock.patch('payment_accounts.payment_intents.cancel'), mock.patch('agent_tasks.runner.post_payment'):
            self.step(self.task)
        return self.task.reason if self.task.state == 'needs_person' else 'prepared'

    def test_the_banks_qr_goes_to_the_provider_with_the_build(self):
        self.assertEqual(self.outcome([(BO_QR, 150)]), 'prepared')
        self.assertEqual(self.prepare.call_args.args[2], BO_QR)
        self.assertEqual(self.prepare.call_args.kwargs['request'],
                         {'method_id': 'bo_qr', 'meta': {'HTTP_X_CONFIO_VERSION': '5.4.2'}})

    def test_links_and_other_schemes_are_not_its_qr(self):
        rail = countries.RAILS['BO']
        self.assertEqual(rail.codes(['https://tienda.com.bo/app', 'www.x.bo', CODE, BO_QR, 'short']), {BO_QR})
        self.assertEqual(self.outcome([('https://tienda.com.bo/app', 200)]), 'code')

    def test_no_code_is_written_so_only_a_large_qr(self):
        self.assertEqual(self.outcome([(BO_QR, 130)]), 'several')
        self.assertEqual(self.outcome([(BO_QR, 150), ('https://tienda.com.bo/app', 150)]), 'prepared')

    def test_two_candidate_qrs_are_never_chosen_between(self):
        self.assertEqual(self.outcome([(BO_QR, 150), (BO_QR + 'X', 150)]), 'several')

    def test_only_a_payee_the_provider_names(self):
        for level in ('institution_amount', 'self_reported', 'unverified'):
            with self.subTest(level=level):
                self.assertEqual(self.outcome([(BO_QR, 150)], level=level), 'unsigned')

    def test_another_rail_or_currency_is_refused(self):
        self.assertEqual(self.outcome([(BO_QR, 150)], currency='BRL'), 'code_refused')
        self.assertEqual(self.outcome([(BO_QR, 150)], method='br_qr'), 'code_refused')


class CountryTests(SimpleTestCase):
    def test_the_store_says_its_country(self):
        self.assertEqual(countries.country_of('mercadolivre.com.br'), 'BR')
        self.assertEqual(countries.country_of('tienda.com.bo'), 'BO')
        self.assertEqual(countries.country_of('tienda.com.pe'), 'PE')
        self.assertIsNone(countries.rail('PE'))

    def test_bolivia_is_open_to_everyone_or_nobody(self):
        from payment_accounts.services import PaymentAccountError
        rail = countries.RAILS['BO']
        with mock.patch('ramps.bolivia_qr.enabled', return_value=False), \
                mock.patch('ramps.bolivia_qr.is_tester', return_value=True):
            with self.assertRaises(PaymentAccountError):
                rail.ready(None, None, {'HTTP_X_CONFIO_VERSION': '9.9.9'})
        with mock.patch('ramps.bolivia_qr.enabled', return_value=True), \
                mock.patch('ramps.bolivia_qr.client_supports', return_value=True):
            rail.ready(None, None, {})


class BoliviaCandidateTests(SimpleTestCase):
    def test_other_schemes_and_countries_are_not_bolivian(self):
        rail = countries.RAILS['BO']
        peru = '00020101021226190015pe.com.interbank5204000053036045802PE5903ABC6004LIMA6304ABCD'
        for text in ('bitcoin:bc1qxyzxyzxyzxyzxyz', 'BEGIN:VCARD\nFN:Ana\nEND:VCARD', '{"sku": "123456789012"}',
                     'upi://pay?pa=a@b', 'WIFI:S:loja;T:WPA;P:12345678;;'):
            with self.subTest(text=text[:20]):
                self.assertEqual(rail.codes([text]), set())
        with mock.patch('payment_accounts.local_money.emv_fields', return_value={'58': 'PE'}):
            self.assertEqual(rail.codes([peru]), set())
        self.assertEqual(rail.codes([BO_QR]), {BO_QR})

    def test_a_store_without_a_country_domain_is_refused(self):
        for store in ('shein.com', 'tienda.co', 'loja.store'):
            with self.subTest(store=store):
                self.assertIsNone(countries.rail(countries.country_of(store)))
