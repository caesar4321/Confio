"""A step before the checkout, and after it: where there is no agent at all."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from agent_tasks import agent, browsers, countries, guard, operate, runner, service, sites, vault
from agent_tasks.cdp import CdpError
from agent_tasks.models import AgentProfile, AgentTask


REAL_KICK = runner.kick   # before RowsBase patches it
from agent_tasks.tests.readers import (judge_by_words, payment_page_by_words, review_by_words, ship_to,
                                       total_on)
from agent_tasks.tests.base import (BASE, CODE, CODE_TEXT, RowsBase, SITE, cart_button, element, link, picture,
                                    search_box, snap)


def came_of(task):
    """What reading the payment came to: 'prepared', why it was not read (back to the agent), or how it ended."""
    if task.state == 'payment_ready':
        return 'prepared'
    if task.state == 'stopped':
        return task.reason
    if task.state == 'working' and task.history and task.history[-1]['did'] == runner.UNREAD:
        return task.history[-1]['result']
    return task.state


def field(label, ref, kind='text', **over):
    return element(label, ref=ref, tag='input', type=kind, **over)


def SIGN_IN(url=f'{BASE}/login'):
    return snap(url=url, secret=True, elements=[field('E-mail', 0, 'email', autocomplete='username'),
                                                field('Senha', 1, 'password'),
                                                element('Continuar com Google', ref=3),
                                                element('Entrar', ref=2, action=f'{BASE}/login', method='post')])


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
        self.reader.click.return_value = self.reader.type.return_value = ''
        self.browser.target = 'tab-9'
        self.reader.address = None
        self.decide = self.patch('agent_tasks.agent.decide')
        self.operate = self.patch('agent_tasks.agent.operate', return_value=('wait', {}))
        self.patch('agent_tasks.operate.MAX_UNREAD', new=10 ** 6)   # a test reads many times over
        self.payable = self.patch('agent_tasks.service.require_payable')
        # The click judge (a model) stands in with the guard's own reading of the words: tests of the
        # judge's real judgment run against recorded pages (scripts/ops, scratch eval), not here.
        self.judge = self.patch('agent_tasks.agent.judge', side_effect=judge_by_words)
        # The order's reader (a model) likewise: what a careful reader would say of the page's words.
        self.review = self.patch('agent_tasks.agent.review', side_effect=review_by_words)
        self.payment_page = self.patch('agent_tasks.agent.payment_page', side_effect=payment_page_by_words)
        # Confío pays it, unless the rail is switched off for everyone (Bolivia): the person's own
        # account state is what the manual tests set.
        self.mode = self.patch('agent_tasks.service.pay_mode', side_effect=lambda task, meta: (
            ('manual', '') if countries.rail(task.country) is not None and countries.rail(task.country).manual(meta)
            else ('confio', '')))

    def reading(self):
        """The order is placed and its payment is about to be read again, with its browser still open."""
        task = self.task
        task.state, task.reason, task.session_id, task.connect_url = 'awaiting_code', '', 's-1', 'wss://browser.invalid/s-1'
        task.session_expires_at = timezone.now() + timedelta(minutes=20)

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

    def test_a_step_that_comes_after_ten_minutes_never_opens_the_browser(self):
        task = self.make_task(state='queued', provider='', session_id='', connect_url='', session_expires_at=None)
        AgentTask.objects.filter(pk=task.pk).update(created_at=timezone.now() - timedelta(minutes=11))
        task = self.step(AgentTask.objects.get(pk=task.pk))
        self.assertEqual((task.state, task.reason), ('stopped', 'unavailable'))
        self.vendor.open.assert_not_called()

    def test_a_step_message_nobody_takes_expires(self):
        with mock.patch('agent_tasks.tasks.step.apply_async') as sent, \
                mock.patch('django.db.transaction.on_commit', side_effect=lambda send: send()):
            REAL_KICK(1, countdown=20)
        self.assertEqual(sent.call_args.kwargs['expires'], 320)

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

    def test_a_turn_too_short_to_open_is_not_handed_over(self):
        task = self.make_task(session_expires_at=timezone.now() + timedelta(seconds=80))
        self.assertEqual(self.step(task, SIGN_IN()).reason, 'session_expired')

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
    def test_a_checkout_is_worked_by_the_checkout_model_never_the_shopping_one(self):
        # The store's payment house is its checkout only once the agent is on its way there.
        for seen, phase in ((snap(url=f'{BASE}/checkout/review'), ''),
                            (snap(url=f'{BASE}/r', elements=[element('Confirmar pedido')]), ''),
                            (snap(url='https://www.mercadopago.com.br/checkout/v1/redirect'), 'ordering')):
            with self.subTest(url=seen.url):
                self.operate.reset_mock()
                task = self.step(self.make_task(phase=phase), seen)
                self.assertEqual(task.state, 'working')
                self.operate.assert_called_once()
                self.decide.assert_not_called()
                task.state = 'cancelled'
                task.save()

    def results(self):
        return snap(url=f'{BASE}/busca?q=chocolate', elements=[
            link('', '/p/A', ref=0, image='https://img.example/a.jpg'),
            link('Chocolate Abuelita 6 tabletas', '/p/A', ref=1),
            link('Chocolate Ibarra 540 g', '/p/B', ref=2, image='https://img.example/b.jpg'),
            element('Oferta', tag='a', href='https://evil.com/x', ref=3),
        ])

    def offered(self):
        self.decide.return_value = ('offer_products', {'items': [
            {'ref': 1, 'title': 'Chocolate Abuelita 6 tabletas', 'price': '$89.00'},
            {'ref': 2, 'title': 'Chocolate Ibarra 540 g', 'price': '$112.50'},
            {'ref': 3, 'title': 'Oferta', 'price': '$1'}, {'ref': 99, 'title': 'x', 'price': ''}]})
        return self.step(self.make_task(), self.results())

    def test_the_results_become_products_to_pick_in_the_chat(self):
        task = self.offered()
        self.assertEqual((task.state, task.reason), ('needs_person', 'choose'))
        # Only this store's product links; the picture of the same product's other link is used.
        self.assertEqual(task.options, [
            {'title': 'Chocolate Abuelita 6 tabletas', 'price': '$89.00', 'image': 'https://img.example/a.jpg',
             'href': f'{BASE}/p/A'},
            {'title': 'Chocolate Ibarra 540 g', 'price': '$112.50', 'image': 'https://img.example/b.jpg',
             'href': f'{BASE}/p/B'}])
        self.assertIsNone(task.checkout_at)
        self.assertIn('Elige una', self.post.call_args.args[1])

    def test_the_one_they_pick_is_opened_and_never_offered_again(self):
        task = self.offered()
        picked = service.choose(self.account, self.user, task.internal_id, 1)
        self.assertEqual((picked.state, picked.pending_url), ('working', f'{BASE}/p/B'))
        self.decide.reset_mock()
        task = self.step(picked, snap())
        self.browser.goto.assert_called_with(f'{BASE}/p/B')
        self.assertEqual(task.pending_url, '')
        self.decide.assert_not_called()
        # Picked: the agent buys it from its page (its add to cart included) under the checkout's lines.
        self.assertEqual((task.state, task.phase), ('working', 'ordering'))

    def test_a_pick_that_is_not_there_or_not_asked_is_refused(self):
        task = self.offered()
        for index in (5, -1):
            with self.assertRaises(service.TaskRefused):
                service.choose(self.account, self.user, task.internal_id, index)
        service.choose(self.account, self.user, task.internal_id, 0)
        with self.assertRaises(service.TaskRefused):
            service.choose(self.account, self.user, task.internal_id, 0)

    def test_a_single_match_needs_no_pick(self):
        self.decide.return_value = ('offer_products', {'items': [{'ref': 2, 'title': 'Ibarra', 'price': '$112'}]})
        task = self.step(self.make_task(), self.results())
        self.assertEqual((task.state, task.pending_url), ('working', f'{BASE}/p/B'))

    def test_a_captcha_is_waited_out_never_handed_to_the_person(self):
        task = self.step(self.make_task(), snap(captcha=True))
        self.assertEqual(task.state, 'working')
        self.assertEqual(task.history[-1]['did'], runner.CAPTCHA)
        self.decide.assert_not_called()
        # The model naming one is the same wait.
        self.decide.return_value = ('ask_person', {'kind': 'captcha'})
        task = self.step(task, snap())
        self.assertEqual((task.state, task.history[-1]['did']), ('working', runner.CAPTCHA))
        self.assertFalse(any('person' in str(call.args[2]) for call in self.post.call_args_list))

    def test_a_captcha_nobody_solves_ends_the_purchase(self):
        task = self.step(self.make_task(counts={'captcha': runner.CAPTCHA_TRIES}), snap(captcha=True))
        self.assertEqual((task.state, task.reason), ('stopped', 'blocked'))

    def test_the_model_hands_over_when_the_item_is_there(self):
        self.decide.return_value = ('ready_for_checkout', {})
        task = self.step(self.make_task(), snap())
        # Nobody is handed anything: the agent goes on to the checkout itself.
        self.assertEqual((task.state, task.phase), ('working', 'ordering'))

    def test_nobody_is_asked_to_confirm_what_they_could_not_pay(self):
        self.payable.side_effect = service.TaskRefused('unavailable')
        task = self.step(self.make_task(), snap(url=f'{BASE}/checkout'))
        self.assertEqual((task.reason, task.checkout_at), ('cannot_pay', None))


class AfterCheckoutTests(StepBase):
    def setUp(self):
        super().setUp()
        self.prepare = self.patch('payment_accounts.payment_intents.prepare')
        self.cancel = self.patch('payment_accounts.payment_intents.cancel')
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab-1',
                                   order={'amount': '91.90', 'total': 'R$ 91,90', 'pressed': True, 'approved': {'total': 'R$ 91,90'}})

    def intent(self, currency='BRL', exact=True, level='institution_charge'):
        self.prepare.return_value = SimpleNamespace(
            currency=currency, amount_exact=exact, amount_local=Decimal('91.90'), internal_id='intent-1',
            payee_level=level, rail_method_id='br_qr')

    def test_the_agent_is_out(self):
        self.decide.return_value = ('click', {'ref': 0})
        for seen in (snap(elements=[element('Confirmar compra')]), snap(url='https://evil.com/'), snap(secret=True),
                     snap('Access denied'), snap(elements=[element('Adicionar ao carrinho')])):
            with self.subTest(url=seen.url, text=seen.text):
                self.reading()
                self.task.save()
                self.step(self.task, seen)
                self.decide.assert_not_called()
                self.operate.assert_not_called()
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

    def test_without_a_reais_account_the_person_pays_the_pix_and_is_offered_one(self):
        self.mode.side_effect = None
        self.mode.return_value = ('manual', 'br_qr')
        self.read.return_value = [(CODE, 200)]
        self.reading()
        self.task.save()
        task = self.step(self.task)
        self.prepare.assert_not_called()
        self.assertEqual((task.state, task.reason, task.order['pay_qr'], task.order['offer']),
                         ('payment_ready', 'manual', CODE, 'br_qr'))
        self.assertIn('la próxima vez lo pago yo', self.post.call_args.args[1])

    def test_a_pix_for_another_amount_or_currency_is_never_handed_over(self):
        self.mode.side_effect = None
        self.mode.return_value = ('manual', 'br_qr')
        for code in (CODE.replace('5303986', '5303986540599.99'), CODE.replace('5303986', '5303840')):
            with self.subTest(code=code[60:90]):
                AgentTask.objects.filter(pk=self.task.pk).update(state='awaiting_code', reason='')
                self.task.refresh_from_db()
                self.reading()
                self.task.save()
                with mock.patch('agent_tasks.runner.code_on_screen', return_value=(code, '')):
                    task = self.step(self.task)
                self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
                self.assertNotIn('pay_qr', task.order)

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
        self.assertEqual(came_of(self.task), 'code')

    def refused(self, reason, **fields):
        self.reading()
        for key, value in fields.items():
            setattr(self.task, key, value)
        self.task.save()
        self.step(self.task)
        self.prepare.assert_not_called()
        self.assertEqual(came_of(self.task), reason)

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
        # A shopping page is not an order's own page; and an order page the agent read while shopping is not trusted.
        for url, why in ((f'{BASE}/p/1', 'code'), (f'{BASE}/p/1?variation=2', 'code'),
                         (f'{BASE}/compras/7', 'code'), (f'{BASE}/compras/7#x', 'code')):
            with self.subTest(url=url):
                self.browser.capture.return_value = (picture(url), picture(url))
                self.refused(why, visited_pages=[runner.same_page(f'{BASE}/p/1'), runner.same_page(f'{BASE}/compras/7')])

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
                self.reading()
                self.task.save()
                self.step(self.task)
                # Prepared to read who is paid, then dropped: no card is posted.
                self.assertEqual(came_of(self.task), 'unpaid')
                self.cancel.assert_called_with(self.account, 'intent-1')

    def test_an_unexact_or_foreign_charge_is_cancelled(self):
        for over in ({'currency': 'USD'}, {'exact': False}):
            with self.subTest(over=over):
                self.intent(**over)
                self.read.return_value = [(CODE, 200)]
                self.reading()
                self.task.save()
                self.step(self.task)
                self.assertEqual(came_of(self.task), 'unpaid')
                self.cancel.assert_called_with(self.account, 'intent-1')

    def test_a_refused_code_is_never_handed_on(self):
        from payment_accounts.services import PaymentAccountError
        self.prepare.side_effect = PaymentAccountError('No puedo verificar quién cobra.')
        self.read.return_value = [(CODE, 200)]
        self.step(self.task)
        self.assertEqual(came_of(self.task), 'unpaid')
        self.assertIn('No puedo verificar quién cobra.', self.post.call_args.args[1])
        self.assertNotIn(CODE, f'{self.post.call_args.args[1]} {self.task.history}')

    def test_an_outage_is_waited_out(self):
        self.prepare.side_effect = RuntimeError('provider down')
        self.read.return_value = [(CODE, 200)]
        self.step(self.task)
        self.assertEqual(came_of(self.task), 'awaiting_code')   # tried again by itself

    def test_the_agents_ceilings_do_not_stop_the_reading(self):
        self.task.steps = 60
        self.task.save()
        self.assertEqual(came_of(self.step(self.task, snap())), 'code')

    def test_a_message_over_the_page_gives_the_screen_straight_back(self):
        self.browser.capture.side_effect = CdpError('took too long')
        self.step(self.task)
        self.assertEqual(came_of(self.task), 'awaiting_code')
        self.vendor.close.assert_not_called()

    def test_stopping_says_there_may_be_an_order(self):
        self.task.session_expires_at = timezone.now()
        self.task.save()
        self.step(self.task)
        self.assertIn('Puede que el pedido haya quedado hecho', self.post.call_args.args[1])

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
        self.assertEqual((task.state, task.phase), ('working', 'ordering'))

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

    def test_what_only_the_person_could_give_ends_it_nobody_is_sent_to_the_store(self):
        for kind in ('choice', 'details', 'consent'):
            with self.subTest(kind=kind):
                self.decide.return_value = ('ask_person', {'kind': kind})
                task = self.step(self.make_task(), snap())
                self.assertEqual((task.state, task.reason), ('stopped', 'cannot_do'))

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

    def test_the_stores_own_checkout_is_not_a_page_the_agent_read(self):
        # Its payment data is read off such a page later: only shopping pages count as read.
        task = self.step(self.make_task(), snap(url=f'{BASE}/checkout/review'))
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
        # Not called done: the checkout model looks at the cart itself.
        self.assertEqual((task.state, task.phase), ('working', 'ordering'))


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
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab',
                                   order={'amount': '9', 'total': 'R$ 9,00', 'pressed': True, 'approved': {'total': 'R$ 9,00'}})

    def outcome(self, found, words, fields=()):
        self.read.return_value = found
        self.browser.capture.return_value = (picture(words=words, fields=fields), picture(words=words, fields=fields))
        self.reading()
        self.task.save()
        with mock.patch.object(runner.Step, 'save', lambda step, **fields: AgentTask.objects.filter(
                pk=step.task.pk).update(**{k: v for k, v in fields.items() if k != 'payment_intent'})):
            self.step(self.task)
        return came_of(self.task)

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
        # QR Bolivia on: Confío pays (the manual way has its own tests).
        patcher = mock.patch.object(countries.BoliviaQrRail, 'manual', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab',
                                   site='tienda.com.bo', country='BO', app_version='5.4.2',
                                   order={'amount': '150', 'total': 'Bs 150', 'pressed': True, 'approved': {'total': 'Bs 150'}})

    def outcome(self, found, level='provider_named', currency='BOB', method='bo_qr'):
        self.prepare.return_value = SimpleNamespace(currency=currency, amount_exact=True, amount_local=Decimal('150'),
                                                    internal_id='i', payee_level=level, rail_method_id=method)
        self.read.return_value = found
        shot = picture(url='https://tienda.com.bo/pedido/1')
        self.browser.capture.return_value = (shot, shot)
        self.reading()
        self.task.save()
        with mock.patch.object(runner.Step, 'save', lambda step, **fields: AgentTask.objects.filter(
                pk=step.task.pk).update(**{k: v for k, v in fields.items() if k != 'payment_intent'})), \
                mock.patch('payment_accounts.payment_intents.cancel'), mock.patch('agent_tasks.runner.post_payment'):
            self.step(self.task)
        return came_of(self.task)

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
                self.assertEqual(self.outcome([(BO_QR, 150)], level=level), 'unpaid')

    def test_with_qr_bolivia_off_the_person_pays_the_stores_qr(self):
        with mock.patch.object(countries.BoliviaQrRail, 'manual', return_value=True):
            self.assertEqual(self.outcome([(BO_QR, 150)]), 'prepared')
        self.prepare.assert_not_called()   # no Confío payment: the person's bank pays it
        self.task.refresh_from_db()
        self.assertEqual((self.task.reason, self.task.order['pay_qr']), ('manual', BO_QR))
        from agent_tasks.schema import task_type
        shown = task_type(self.task)
        self.assertEqual(shown.pay_qr, BO_QR)
        self.assertIn('Bs 150', shown.message)
        self.assertIn('app de tu banco', shown.message)

    def test_with_qr_bolivia_off_a_qr_for_another_amount_or_country_is_never_handed_over(self):
        for over in ({'amount': '99'}, ):
            AgentTask.objects.filter(pk=self.task.pk).update(order={**self.task.order, **over})
            self.task.refresh_from_db()
            with mock.patch.object(countries.BoliviaQrRail, 'manual', return_value=True):
                self.assertEqual(self.outcome([(BO_QR, 150)]), 'unpaid')
        AgentTask.objects.filter(pk=self.task.pk).update(order={**self.task.order, 'amount': '150'})
        self.task.refresh_from_db()
        peru = BO_QR.replace('5802BO', '5802PE')
        with mock.patch.object(countries.BoliviaQrRail, 'manual', return_value=True), \
                mock.patch.object(countries.BoliviaQrRail, 'codes', lambda rail, texts: set(texts)):
            self.assertEqual(self.outcome([(peru, 150)]), 'unpaid')

    def test_a_qr_confio_cannot_pay_for_this_person_is_handed_to_them(self):
        from payment_accounts.services import PaymentAccountError
        from payment_accounts.payment_intents import IntentRefused
        self.prepare.side_effect = IntentRefused('unavailable', 'Todavía no puedo preparar pagos desde aquí.')
        self.read.return_value = [(BO_QR, 150)]
        shot = picture(url='https://tienda.com.bo/pedido/1')
        self.browser.capture.return_value = (shot, shot)
        self.reading()
        self.task.save()
        with mock.patch('payment_accounts.payment_intents.cancel'):
            task = self.step(self.task)
        self.assertEqual((task.state, task.reason, task.order['pay_qr']), ('payment_ready', 'manual', BO_QR))

    def test_a_qr_the_provider_says_is_no_payment_is_never_handed_to_them(self):
        from payment_accounts.payment_intents import IntentRefused
        from payment_accounts.services import PaymentAccountError
        for refusal in (IntentRefused('rail', 'No es un QR de pago.'), IntentRefused('no_code', 'x'),
                        IntentRefused('no_amount', 'x'), PaymentAccountError('x')):
            with self.subTest(refusal=getattr(refusal, 'code', 'plain')):
                AgentTask.objects.filter(pk=self.task.pk).update(state='awaiting_code', reason='')
                self.task.refresh_from_db()
                self.prepare.side_effect = refusal
                self.assertEqual(self.outcome([(BO_QR, 150)]), 'unpaid')
                self.task.refresh_from_db()
                self.assertNotIn('pay_qr', self.task.order)

    def test_with_qr_bolivia_off_an_order_nobody_approved_gets_no_qr(self):
        AgentTask.objects.filter(pk=self.task.pk).update(order={'unapproved': True, 'total': 'Bs 150'})
        self.task.refresh_from_db()
        with mock.patch.object(countries.BoliviaQrRail, 'manual', return_value=True):
            self.assertEqual(self.outcome([(BO_QR, 150)]), 'unpaid')

    def test_another_rail_or_currency_is_refused(self):
        self.assertEqual(self.outcome([(BO_QR, 150)], currency='BRL'), 'unpaid')
        self.assertEqual(self.outcome([(BO_QR, 150)], method='br_qr'), 'unpaid')


class ManageTests(StepBase):
    """An order already placed: the model finds it and does what the store asks; a request is sent only
    after the person approves exactly it in the chat, once; buying, a card and the account never."""

    ORDERS = f'{BASE}/my-purchases/123'

    def setUp(self):
        super().setUp()
        self.manage = self.patch('agent_tasks.agent.manage', return_value=('wait', {}))

    def task(self, **over):
        return self.make_task(kind='manage', goal='cancela el chocolate', **over)

    def test_what_they_only_wanted_to_know_is_answered_with_the_stores_words(self):
        self.manage.return_value = ('answer', {'text': 'Tu pedido llega el jueves 26 de noviembre.'})
        task = self.step(self.task(), snap('Mis compras Llega el jueves 26', self.ORDERS, elements=[]))
        self.assertEqual((task.state, task.reason), ('stopped', 'answered'))
        self.assertIn('Esto muestra', self.post.call_args.args[1])
        self.assertIn('jueves 26 de noviembre', self.post.call_args.args[1])
        from agent_tasks.schema import task_type
        self.assertIn('jueves 26 de noviembre', task_type(task).message)
        self.reader.click.assert_not_called()

    def test_the_button_that_sends_the_request_is_never_pressed_it_is_approved(self):
        page = snap('Cancelar compra Motivo: ya no lo necesito', self.ORDERS, elements=[
            element('Cancelar compra', ref=0)])
        self.manage.return_value = ('press', {'ref': 0})
        task = self.step(self.task(), page)
        self.reader.click.assert_not_called()
        self.assertIn('submit_request', task.history[-1]['result'])
        self.manage.return_value = ('submit_request', {'ref': 0, 'what': 'cancelar el pedido del chocolate'})
        task = self.step(task, page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))
        from agent_tasks.schema import task_type
        shown = task_type(task)
        self.assertEqual(shown.request, 'cancelar el pedido del chocolate')
        self.assertIn('«cancelar el pedido del chocolate»', shown.message)
        self.reader.click.assert_not_called()
        task = service.answer_request(self.account, self.user, task.internal_id, True)
        task = self.step(task, page)
        self.reader.click.assert_called_once()   # exactly it, once
        self.assertEqual(task.order['submitted'], 1)
        task = self.step(task, page)              # never twice
        self.reader.click.assert_called_once()
        self.assertIn('already sent', task.history[-1]['result'])

    def test_an_approved_link_only_opens_the_form_and_its_button_is_asked_next(self):
        # 2026-11-24: the judge read Amazon's "Cancelar productos" link as the request; approving it used up the
        # one request, and the form's real "Solicitar cancelación" was refused as a second.
        self.judge.side_effect = None
        self.judge.return_value = ('request', 'cancels it')
        details = snap('Detalles del pedido', self.ORDERS, elements=[
            element('Cancelar productos', ref=0, tag='a', href=f'{BASE}/preship/cancel-items')])
        self.manage.return_value = ('submit_request', {'ref': 0, 'what': 'cancelar el pedido'})
        task = self.step(self.task(), details)
        task = self.step(service.answer_request(self.account, self.user, task.internal_id, True), details)
        self.reader.click.assert_called_once()
        self.assertFalse(task.order.get('submitted'))
        self.assertIn('nothing was sent', task.history[-1]['result'])
        form = snap('Motivo de cancelación', f'{BASE}/preship/cancel-items', elements=[
            element('Solicitar cancelación', ref=0)])
        task = self.step(task, form)
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))   # its own approval
        task = self.step(service.answer_request(self.account, self.user, task.internal_id, True), form)
        self.assertEqual(self.reader.click.call_count, 2)
        self.assertEqual(task.order['submitted'], 1)
        task = self.step(task, form)   # never twice
        self.assertEqual(self.reader.click.call_count, 2)

    def test_no_sends_nothing_and_ends_it(self):
        page = snap('Devolver', self.ORDERS, elements=[element('Solicitar devolución', ref=0)])
        self.manage.return_value = ('submit_request', {'ref': 0, 'what': 'devolver el chocolate'})
        task = self.step(self.task(), page)
        task = service.answer_request(self.account, self.user, task.internal_id, False)
        self.assertEqual((task.state, task.reason), ('stopped', 'declined'))
        self.reader.click.assert_not_called()

    def test_an_approval_is_for_that_request_on_that_page_only(self):
        page = snap('Cancelar', self.ORDERS, elements=[element('Cancelar compra', ref=0)])
        self.manage.return_value = ('submit_request', {'ref': 0, 'what': 'cancelar el pedido'})
        task = self.step(self.task(), page)
        task = service.answer_request(self.account, self.user, task.internal_id, True)
        other = snap('Cancelar', f'{BASE}/my-purchases/999', elements=[element('Cancelar compra', ref=0)])
        task = self.step(task, other)   # another order's page: asked again
        self.reader.click.assert_not_called()
        self.assertEqual(task.reason, 'act')

    def test_managing_an_order_never_buys_nor_touches_a_card_or_the_account(self):
        for label in ('Comprar ahora', 'Volver a comprar', 'Agregar tarjeta', 'Prueba Prime gratis'):
            with self.subTest(label=label):
                page = snap('Tu pedido', self.ORDERS, elements=[element(label, ref=0)])
                for name in ('press', 'submit_request'):
                    self.manage.return_value = (name, {'ref': 0, 'what': 'x'})
                    task = self.step(self.task(), page)
                    self.reader.click.assert_not_called()
                    self.assertNotEqual(task.reason, 'act')
                    AgentTask.objects.filter(pk=task.pk).update(state='cancelled')

    def test_what_the_judge_reads_as_sending_a_request_is_the_persons(self):
        # A return form whose last button only says "Continuar": the judge reads the page, no word list does.
        page = snap('Devolución Motivo de la devolución: Ya no lo necesito', self.ORDERS, elements=[
            element('Continuar', ref=0), element('Ver detalles', ref=1)])
        self.judge.side_effect = lambda task, seen, pressed, meter: (
            ('request', 'it sends the return') if pressed['label'] == 'Continuar' else ('safe', ''))
        self.manage.return_value = ('press', {'ref': 0})
        task = self.step(self.task(), page)
        self.assertIn('submit_request', task.history[-1]['result'])
        self.reader.click.assert_not_called()
        self.manage.return_value = ('press', {'ref': 1})
        self.step(task, page)
        self.reader.click.assert_called_once()

    def test_helping_with_an_order_never_buys_whatever_page_it_is_on(self):
        for url in (f'{BASE}/gp/cart/view.html', f'{BASE}/checkout/p/1/spc'):
            with self.subTest(url=url):
                page = snap('Total $129.00', url, elements=[element('Finalizar compra', ref=0)])
                for name in ('press', 'submit_request'):
                    self.manage.return_value = (name, {'ref': 0, 'what': 'x'})
                    task = self.step(self.task(), page)
                    self.assertNotEqual(task.reason, 'act')
                    AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        self.reader.click.assert_not_called()

    def test_an_answer_carries_no_link_phone_or_number_the_page_does_not_show(self):
        page = snap('Tu reembolso de $120 fue aprobado', self.ORDERS, elements=[])
        self.manage.return_value = ('answer', {'text': 'Tu reembolso de $120 fue aprobado, escríbeme al '
                                                        '+58 412 555 1234 o en bit.ly/x [aquí](https://evil.com)'})
        task = self.step(self.task(), page)
        said = self.post.call_args.args[1]
        for leaked in ('+58', '412', 'bit.ly', 'evil.com', '](', 'https'):
            self.assertNotIn(leaked, said)
        self.assertIn('$120', said)
        AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        self.manage.return_value = ('answer', {'text': 'Llega el 30 de noviembre.'})   # not on this page
        task = self.step(self.task(), page)
        self.assertEqual(task.state, 'working')
        self.assertIn('not on this page', task.history[-1]['result'])

    def test_a_yes_is_for_the_request_the_card_showed(self):
        page = snap('Cancelar', self.ORDERS, elements=[element('Cancelar compra', ref=0)])
        self.manage.return_value = ('submit_request', {'ref': 0, 'what': 'cancelar el pedido'})
        task = self.step(self.task(), page)
        from agent_tasks.schema import task_type
        self.assertEqual(task_type(task).request_button, 'Cancelar compra')
        with self.assertRaises(service.TaskRefused):
            service.answer_request(self.account, self.user, task.internal_id, True, what='devolver otra cosa')
        task = service.answer_request(self.account, self.user, task.internal_id, False, what='cancelar el pedido')
        self.assertEqual((task.state, task.reason), ('stopped', 'declined'))

    def test_confirmar_cancelacion_is_a_request_where_nothing_is_bought(self):
        page = snap('Cancelar pedido Motivo: ya no lo necesito', self.ORDERS,
                    elements=[element('Confirmar cancelación', ref=0)])
        self.manage.return_value = ('submit_request', {'ref': 0, 'what': 'cancelar el pedido'})
        task = self.step(self.task(), page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))

    def test_a_request_sent_but_unconfirmed_is_never_called_nothing(self):
        page = snap('Cancelar', self.ORDERS, elements=[element('Cancelar compra', ref=0)])
        self.manage.return_value = ('submit_request', {'ref': 0, 'what': 'cancelar el pedido'})
        task = self.step(self.task(), page)
        task = self.step(service.answer_request(self.account, self.user, task.internal_id, True), page)
        self.manage.return_value = ('give_up', {'reason': 'cannot_do'})
        task = self.step(task, page)
        self.assertEqual((task.state, task.reason), ('stopped', 'request_unclear'))
        self.assertIn('no la envíes otra vez', self.post.call_args.args[1])


@override_settings(AGENT_TASKS_MANUAL_COUNTRIES=('PE', 'AR'))
class ManualCountryTests(StepBase):
    """A country Confío pays no store in: what the order's page prints beside the store's own labels."""

    PAGE = ('Gracias por tu compra', 'Pedido 55120', 'Chocolate Sublime 6 unidades', 'Transferencia bancaria',
            'Monto a pagar', 'S/ 189,00', 'Banco', 'BCP', 'Cuenta', '191-2345678-0-12', 'Titular', 'Tienda SAC',
            'Referencia', 'PED-55120', 'Vence', '26 de noviembre')

    def setUp(self):
        super().setUp()
        self.read = self.patch('agent_tasks.qr.read', return_value=[])

    def outcome(self, page=None, site='tienda.com.pe', country='PE', item='Chocolate Sublime', again=None):
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab',
                                   site=site, country=country, phase='ordered',
                                   order={'amount': '189.00', 'total': 'S/ 189,00', 'pressed': True, 'item': item})
        url = f'https://www.{site}/compras/2000005' if site in sites.KNOWN else f'https://{site}/pedido/55120'
        page = page or self.PAGE
        self.browser.capture.return_value = (picture(url=url, text=page), picture(url=url, text=again or page))
        self.reading()
        self.task.save()
        task = self.step(self.task)
        AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        return task

    def details(self, task):
        return {d['label']: d['value'] for d in (task.order or {}).get('pay_details') or []}

    def test_what_the_page_prints_beside_its_labels_is_handed_to_them(self):
        task = self.outcome()
        self.assertEqual((task.state, task.reason), ('payment_ready', 'manual'))
        self.assertEqual(self.details(task), {'Monto': 'S/ 189,00', 'Cuenta': '191-2345678-0-12',
                                              'Referencia': 'PED-55120', 'Titular': 'Tienda SAC', 'Banco': 'BCP',
                                              'Paga antes de': '26 de noviembre'})
        from agent_tasks.schema import task_type
        self.assertIn('Nadie en Confío verificó', task_type(task).message)

    def test_an_account_in_the_items_title_is_never_taken(self):
        page = tuple('Chocolate Cuenta 191-2345678-0-12' if node == 'Chocolate Sublime 6 unidades' else node
                     for node in self.PAGE)
        task = self.outcome(page=page, item='Chocolate Cuenta 191-2345678-0-12')
        self.assertNotEqual(task.state, 'payment_ready')

    def test_two_accounts_are_never_chosen_between(self):
        page = (*self.PAGE, 'Cuenta', '999-0000000-0-99')
        task = self.outcome(page=page)
        self.assertNotEqual(task.state, 'payment_ready')

    def test_a_transfer_with_no_account_goes_back_to_the_agent(self):
        page = tuple(node for node in self.PAGE if node not in ('Cuenta', '191-2345678-0-12'))
        task = self.outcome(page=page)
        self.assertEqual(task.history[-1]['did'], runner.UNREAD)

    def test_another_amount_is_never_handed_over(self):
        page = tuple('S/ 19,00' if node == 'S/ 189,00' else node for node in self.PAGE)
        task = self.outcome(page=page)
        self.assertNotEqual(task.state, 'payment_ready')
        self.assertEqual(task.history[-1]['did'], runner.UNREAD)   # back to the agent, a few times at most

    def test_a_sellers_account_above_the_stores_block_is_never_chosen(self):
        seller = ('Mensaje del vendedor', 'Total', 'S/ 189,00', 'Cuenta', '0000003100099999999999',
                  *(f'Linea {n}' for n in range(20)))
        task = self.outcome(page=(*seller, *self.PAGE))
        self.assertNotEqual(task.state, 'payment_ready')

    def test_an_account_number_and_a_cci_are_both_handed_over(self):
        page = ('Gracias', 'Chocolate Sublime 6 unidades', 'Transferencia bancaria', 'Monto a pagar',
                'S/ 189.00 (incluye S/ 28.83 IGV)', 'Banco', 'BCP', 'Nro. de cuenta', '191-2345678-0-12',
                'Cuenta interbancaria (CCI)', '002-191-002345678012-55', 'Titular', 'Tienda SAC')
        task = self.outcome(page=page)
        details = self.details(task)
        self.assertEqual((details.get('Cuenta'), details.get('CCI')), ('191-2345678-0-12', '002-191-002345678012-55'))

    def test_a_cbu_and_its_alias_on_an_argentine_store(self):
        page = ('¡Gracias por tu compra!', 'Chocolate Águila', 'Transferencia bancaria', 'Total', '$ 189,00',
                'CBU: 0170099220000067797370', 'Alias: tienda.cacao.mp', 'Titular: Cacao SRL')
        task = self.outcome(page=page, site='tiendacacao.com.ar', country='AR', item='Chocolate Águila')
        self.assertEqual(self.details(task), {'Monto': 'S/ 189,00', 'CBU/CVU': '0170099220000067797370',
                                              'Alias': 'tienda.cacao.mp', 'Titular': 'Cacao SRL'})

    def test_a_product_code_is_never_the_payment_reference(self):
        page = (*self.PAGE[:3], 'Código: RM-1234', *self.PAGE[3:])
        task = self.outcome(page=page)
        self.assertEqual(self.details(task)['Referencia'], 'PED-55120')

    def test_a_voucher_with_transfer_words_in_the_footer_is_still_one(self):
        page = ('Gracias', 'Chocolate', 'Paga en efectivo', 'Monto a pagar', 'S/ 189,00', 'Código CIP', '2398 4471',
                'Paga antes de', '26/11 23:59', *(f'Linea {n}' for n in range(20)),
                'Medios de pago: transferencia, Rapipago')
        task = self.outcome(page=page, item='Chocolate')
        self.assertEqual(self.details(task).get('Referencia'), '2398 4471')

    def test_the_two_pictures_must_agree(self):
        changed = tuple('PED-99999' if node == 'PED-55120' else node for node in self.PAGE)
        task = self.outcome(again=changed)
        self.assertEqual(task.history[-1]['result'], 'screen')

    def test_on_a_marketplace_only_the_stores_payment_code_is_taken(self):
        page = ('Compra 2000005', 'Chocolate', 'Pagá en Rapipago', 'Monto a pagar', '$ 189,00',
                'Código de pago', '3456 7890 1234', 'Cuenta', '0000003100012345678901', 'Titular', 'Juan P')
        task = self.outcome(page=page, site='mercadolibre.com.ar', country='AR', item='Chocolate')
        self.assertEqual((task.state, self.details(task)), ('payment_ready', {'Monto': 'S/ 189,00',
                                                                             'Referencia': '3456 7890 1234'}))

    def test_on_a_marketplace_a_transfer_is_never_handed_over(self):
        page = ('Compra 2000005', 'Chocolate', 'Transferí al CBU', 'Monto a pagar', '$ 189,00',
                'CBU', '0000003100012345678901', 'Titular', 'Juan P')
        task = self.outcome(page=page, site='mercadolibre.com.ar', country='AR', item='Chocolate')
        self.assertNotEqual(task.state, 'payment_ready')

    def test_a_qr_there_counts_only_when_it_names_this_orders_amount(self):
        from agent_tasks import manual
        with mock.patch('agent_tasks.runner.code_on_screen', return_value=('QRSIMPLE:no-emv-at-all', '')):
            task = self.outcome()
        self.assertEqual(task.order['pay_qr'], '')   # an opaque QR is not shown; the labelled data is
        self.assertIn('Cuenta', self.details(task))


class PayModeTests(SimpleTestCase):
    def test_confio_pays_or_the_person_does_and_is_offered_the_account(self):
        from payment_accounts.local_money import REGION_UNSUPPORTED_MESSAGE
        from payment_accounts.services import PaymentAccountError
        rail = countries.RAILS['BR']
        with mock.patch.object(countries.PixRail, 'ready', return_value=None):
            self.assertEqual(rail.pay_mode(None, None, {}), ('confio', ''))
        with mock.patch.object(countries.PixRail, 'ready', side_effect=PaymentAccountError('Tu cuenta local todavía no está activa.')):
            self.assertEqual(rail.pay_mode(None, None, {}), ('manual', 'br_qr'))
        with mock.patch.object(countries.PixRail, 'ready', side_effect=PaymentAccountError(REGION_UNSUPPORTED_MESSAGE)):
            self.assertEqual(rail.pay_mode(None, None, {}), ('manual', ''))
        with mock.patch.object(countries.SpeiRail, 'ready', side_effect=PaymentAccountError('x')):
            self.assertEqual(countries.RAILS['MX'].pay_mode(None, None, {}), ('manual', 'mx_clabe'))
        with mock.patch('ramps.bolivia_qr.enabled', return_value=False):
            self.assertEqual(countries.RAILS['BO'].pay_mode(None, None, {}), ('manual', ''))
        with override_settings(AGENT_TASKS_MANUAL_COUNTRIES=('PE',)):
            self.assertEqual(countries.rail('PE').pay_mode(None, None, {}), ('manual', ''))
        self.assertIsNone(countries.rail('PE'))   # held until its reading is bound to the store's labels


class CountryTests(SimpleTestCase):
    def test_the_store_says_its_country(self):
        self.assertEqual(countries.country_of('mercadolivre.com.br'), 'BR')
        self.assertEqual(countries.country_of('tienda.com.bo'), 'BO')
        self.assertEqual(countries.country_of('tienda.com.pe'), 'PE')
        # Where Confío pays no store yet, the person pays it from their bank; elsewhere, nothing.
        with override_settings(AGENT_TASKS_MANUAL_COUNTRIES=('PE',)):
            self.assertEqual(countries.rail('PE').kind, 'manual')
        self.assertIsNone(countries.rail('ES'))

    def test_bolivia_is_paid_by_confio_for_everyone_or_by_the_person_for_everyone(self):
        rail = countries.RAILS['BO']
        # Off (a tester list never counts): the purchase still goes ahead, the person pays the QR.
        with mock.patch('ramps.bolivia_qr.enabled', return_value=False), \
                mock.patch('ramps.bolivia_qr.is_tester', return_value=True):
            rail.ready(None, None, {'HTTP_X_CONFIO_VERSION': '9.9.9'})
            self.assertTrue(rail.manual({'HTTP_X_CONFIO_VERSION': '9.9.9'}))
        with mock.patch('ramps.bolivia_qr.enabled', return_value=True), \
                mock.patch('ramps.bolivia_qr.client_supports', return_value=True):
            rail.ready(None, None, {})
            self.assertFalse(rail.manual({}))
        self.assertFalse(countries.RAILS['BR'].manual({}))


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
        for store in ('shein.com', 'loja.store', 'tienda.es'):
            with self.subTest(store=store):
                self.assertIsNone(countries.rail(countries.country_of(store)))


CHECKOUT = f'{BASE}/checkout/review'
DONE = snap('Pedido confirmado. Gracias por tu compra.', f'{BASE}/checkout/congrats')


def checkout_page(total='R$ 189,00', url=CHECKOUT, method='Pix', extra=''):
    return snap(f'Resumo do pedido Chocolate Ibarra {extra} Total {total}', url, elements=[
        element(method, ref=0, role='radio', tag='div', checked=True),
        element('Confirmar pedido', ref=1),
        element('Ajuda', ref=2, tag='a', href='https://evil.com/help'),
        element('Continuar', ref=3),
        element('Finalizar compra', ref=4)])


class SignInTests(StepBase):
    def test_with_no_saved_account_the_person_is_asked_in_the_chat(self):
        task = self.step(self.make_task(), SIGN_IN())
        self.assertEqual((task.state, task.reason), ('needs_person', 'login'))
        self.reader.type.assert_not_called()
        # What is true about it: kept encrypted, theirs to delete. Never "we do not store it".
        self.assertIn('cifrada', self.post.call_args.args[1])
        self.assertIn('borrarla cuando quieras', self.post.call_args.args[1])
        self.assertNotRegex(self.post.call_args.args[1].lower(), r'no (la |se )?guard')

    def test_the_saved_account_is_typed_by_the_runner_and_no_model_sees_it(self):
        vault.save(self.user, SITE, 'ana@example.com', 'hunter2!')
        task = self.step(self.make_task(), SIGN_IN())
        typed = [(call.args[1], call.kwargs.get('secret', False)) for call in self.reader.type.call_args_list]
        # The password only ever as a secret: into a password field that holds the focus (page.Reader.type).
        self.assertEqual(typed, [('ana@example.com', False), ('hunter2!', True)])
        # The form's own button is clicked: no Enter into whatever has the focus.
        self.assertEqual(self.reader.click.call_args.args[0]['label'], 'Entrar')
        self.browser.enter.assert_not_called()
        self.decide.assert_not_called()
        self.operate.assert_not_called()
        self.assertNotIn('hunter2', f'{task.history} {self.post.call_args_list}')
        self.assertEqual(task.counts['sign_ins'], 1)

    def test_only_on_the_stores_own_sign_in_address(self):
        vault.save(self.user, SITE, 'ana@example.com', 'hunter2!')
        from agent_tasks.models import AgentCredential
        self.assertNotIn('hunter2', AgentCredential.objects.get(user=self.user).secret)
        fields = SIGN_IN().elements
        self.decide.return_value = ('wait', {})
        for where in (snap(url=f'{BASE}/p/123', secret=True, elements=fields),        # a seller's page with a form
                      snap(url=f'{BASE}/checkout/pay', secret=True, elements=fields),   # a checkout's own fields
                      snap(url='https://evil.com/login', secret=True, elements=fields)):
            with self.subTest(url=where.url):
                task = self.step(self.make_task(), where)
                self.reader.type.assert_not_called()
                AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        # Never on a sign-up form.
        self.step(self.make_task(), SIGN_IN(url=f'{BASE}/registration'))
        self.reader.type.assert_not_called()

    def test_only_the_forms_own_button_is_clicked(self):
        vault.save(self.user, SITE, 'ana@example.com', 'hunter2!')
        fields = SIGN_IN().elements[:2]
        for buttons in ([element('Continuar com Google', ref=3, action=f'{BASE}/login')],     # another sign-in
                        [element('Criar conta', ref=3, action=f'{BASE}/login')],             # a sign-up
                        [element('Entrar', ref=2)]):                                        # no form behind it
            with self.subTest(buttons=buttons[0]['label']):
                self.reader.click.reset_mock()
                task = self.step(self.make_task(), snap(url=f'{BASE}/login', secret=True, elements=fields + buttons))
                self.reader.click.assert_not_called()
                AgentTask.objects.filter(pk=task.pk).update(state='cancelled')

    def test_a_return_address_that_says_register_is_still_a_sign_in(self):
        vault.save(self.user, SITE, 'ana@example.com', 'hunter2!')
        self.step(self.make_task(), SIGN_IN(url=f'{BASE}/login?return_to=/registration'))
        self.assertEqual(self.reader.click.call_args.args[0]['label'], 'Entrar')

    def test_a_payment_form_is_never_a_sign_in(self):
        vault.save(self.user, SITE, 'ana@example.com', 'hunter2!')
        self.decide.return_value = ('wait', {})
        page = snap(url=f'{BASE}/login', secret=True, elements=[
            field('E-mail', 0, 'email'), field('Código de seguridad (CVV)', 1, 'password'), element('Entrar', ref=2)])
        self.step(self.make_task(), page)
        self.reader.type.assert_not_called()

    def test_a_field_that_does_not_take_the_focus_gets_nothing_and_it_is_not_a_try(self):
        vault.save(self.user, SITE, 'ana@example.com', 'hunter2!')
        self.reader.type.side_effect = ['', 'not_focused']
        task = self.step(self.make_task(), SIGN_IN())
        self.reader.click.assert_not_called()
        self.assertIn('refused', task.history[-1]['result'])
        self.assertEqual(operate.count(task, 'sign_ins'), 0)

    def test_an_account_that_does_not_get_in_is_asked_again_once_then_it_ends(self):
        vault.save(self.user, SITE, 'ana@example.com', 'wrong')
        task = self.step(self.make_task(counts={'sign_ins': operate.MAX_SIGN_INS, 'asked_login': 1}), SIGN_IN())
        self.assertEqual((task.state, task.reason), ('needs_person', 'login'))
        self.assertIsNone(vault.get(self.user, SITE))
        self.assertIn('no me dejó entrar', self.post.call_args.args[1])
        AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        task = self.step(self.make_task(counts={'asked_login': operate.MAX_ASKS}), SIGN_IN())
        self.assertEqual((task.state, task.reason), ('stopped', 'sign_in'))

    def test_a_code_the_store_sent_is_asked_then_typed_once(self):
        page = snap(url=f'{BASE}/login/otp', secret=True, elements=[
            field('Código de verificación', 0, autocomplete='one-time-code'),
            element('Verificar', ref=1, action=f'{BASE}/login/otp', method='post')])
        task = self.step(self.make_task(), page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'otp'))
        service.give_code(self.account, self.user, task.internal_id, ' 482 913 ')
        task = self.step(task, page)
        self.assertEqual(self.reader.type.call_args.args[1], '482913')
        self.assertEqual(vault.take_code(task), '')   # used once
        self.assertNotIn('482913', str(task.history))

    def test_a_postal_code_a_coupon_or_a_search_box_is_not_a_code(self):
        self.decide.return_value = ('wait', {})
        for label in ('Código postal', 'Código promocional', 'Zip code', 'Shipping'):
            with self.subTest(label=label):
                page = snap(url=f'{BASE}/login', elements=[field(label, 0, maxlength=8), element('Continuar', ref=1)])
                task = self.step(self.make_task(), page)
                self.assertEqual(task.state, 'working')
                AgentTask.objects.filter(pk=task.pk).update(state='cancelled')

    def test_the_card_puts_the_account_in_the_vault_and_the_agent_goes_on(self):
        task = self.step(self.make_task(), SIGN_IN())
        answered = service.sign_in(self.account, self.user, task.internal_id, ' ana@example.com ', 'hunter2!')
        self.assertEqual(answered.state, 'working')
        self.assertEqual(vault.get(self.user, SITE), {'identifier': 'ana@example.com', 'password': 'hunter2!'})
        for bad in (('', 'x'), ('ana', '')):
            with self.assertRaises(service.TaskRefused):
                service.sign_in(self.account, self.user, task.internal_id, *bad)

    def test_a_deleted_persons_sign_ins_are_not_kept(self):
        vault.save(self.user, SITE, 'ana@example.com', 'hunter2!')
        self.user.is_active = False
        self.user.save()
        service.sweep()
        self.assertIsNone(vault.get(self.user, SITE))


class CheckoutTests(StepBase):
    ORDER = ('ready_to_order', {'ref': 1, 'item': 'Chocolate Ibarra', 'total': 'R$ 189,00'})

    def named(self, page=None, **over):
        self.operate.return_value = self.ORDER
        return self.step(self.make_task(phase='ordering', **over), page or checkout_page())

    def approved(self):
        task = self.named()
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))
        return service.approve(self.account, self.user, task.internal_id)

    def test_only_choices_links_and_listed_buttons_are_pressed(self):
        task = self.make_task(phase='ordering')
        for ref, pressed in ((0, True), (3, True),      # a choice; "Continuar"
                             (1, False), (4, False),    # "Confirmar pedido"; "Finalizar compra": may be the one that buys
                             (2, False)):               # a link out of the store
            self.reader.click.reset_mock()
            self.operate.return_value = ('press', {'ref': ref})
            task = self.step(task, checkout_page())
            self.assertEqual(self.reader.click.called, pressed, ref)
        self.assertIsNone(task.checkout_at)

    def test_tonights_amazon_controls_are_the_models_to_press(self):
        # The founder's Amazon México runs, 2026-11-24, each stopped by a word list: now pressed.
        product = f'{BASE}/p/MLB1'
        for label, url in (('Agregar al Carrito | Agregar al carrito', product),
                           ('Ir al carrito', product), ('1 Carrito | 1 artículo en el carrito', product),
                           ('Guardar para más tarde Volteck Adaptador de Enchufe Tipo E a Tipo A', f'{BASE}/gp/cart'),
                           ('No gracias | No gracias, continuar sin Amazon Prime', CHECKOUT),
                           ('Usar esta dirección', CHECKOUT), ('Envío estándar gratis', CHECKOUT),
                           ('Proceder al pago | Proceed to checkout', f'{BASE}/gp/cart'), ('Cerrar', CHECKOUT)):
            with self.subTest(label=label):
                self.assertTrue(guard.may_press(element(label), on_checkout=url == CHECKOUT), label)
        # The four lines hold, on or off a recognised checkout.
        for label in ('Confirmar', 'Realizar pedido', 'Pagar ahora', 'Comprar ahora', 'Agregar tarjeta de crédito',
                      'Pagar a meses sin intereses', 'Prueba Prime gratis', 'Eliminar mi cuenta', 'Cerrar sesión'):
            for on_checkout in (True, False):
                with self.subTest(label=label, on_checkout=on_checkout):
                    self.assertFalse(guard.may_press(element(label), on_checkout=on_checkout), label)

    def test_on_the_last_page_an_unknown_button_is_named_for_approval_never_pressed(self):
        # "Procesar pago" carries no final word: on the page with the total and the method it is the person's.
        page = snap('Resumen Chocolate Forma de pagamento Pix Total do pedido R$ 189,00', CHECKOUT, elements=[
            element('Pix', ref=0, role='radio', tag='div', checked=True), element('Procesar pago', ref=1),
            element('Cambiar', ref=2), element('Continuar', ref=3)])
        task = self.make_task(phase='ordering', goal='chocolate')
        self.operate.return_value = ('press', {'ref': 1})
        task = self.step(task, page)
        self.reader.click.assert_not_called()
        self.assertIn('ready_to_order', task.history[-1]['result'])
        for ref in (2, 3):   # an edit stays the model's; "Continuar" with no final button beside it may be the one
            self.operate.return_value = ('press', {'ref': ref})
            task = self.step(task, page)
        self.assertEqual(self.reader.click.call_count, 1)
        beside = snap(page.text, CHECKOUT, elements=[*page.elements, element('Realizar pedido', ref=4)])
        self.assertTrue(guard.may_press(element('Continuar'), on_checkout=True, stage='final', page=beside))
        self.assertFalse(guard.may_press(element('Continuar'), on_checkout=True, stage='final', page=page))
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': 'R$ 189,00'})
        task = self.step(task, page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))

    def test_a_checkout_page_with_money_is_held_to_the_last_pages_rules(self):
        # "Total $1,299.00" with no long total label: still strict on a checkout.
        page = snap('Revisa tu pedido Total $1,299.00', f'{BASE}/checkout/review',
                    elements=[element('Procesar pago', ref=0), element('Ordenar', ref=1)])
        self.assertEqual(guard.stage_of(page, on_checkout=True), 'money')
        for label in ('Procesar pago', 'Ordenar', 'Enviar orden', 'OK', 'Sin costo adicional', 'Sin comisión | Pagar',
                      'Usar esta dirección y enviar pedido', 'Continuar y enviar pedido', 'Proceder con el pedido'):
            for stage in ('money', 'final'):
                self.assertFalse(guard.may_press(element(label), on_checkout=True, stage=stage, page=page), label)
        for href in (f'{BASE}/checkout/review#', 'javascript:void(0)'):
            fake = element('Continuar', tag='a', href=href)
            self.assertFalse(guard.may_press(fake, on_checkout=True, stage='money', page=page), href)
        # A middle step's plain way on, and its edits: the model's.
        for label in ('Continuar', 'Usar esta dirección', 'Usar este método de pago', 'Cambiar dirección',
                      'No gracias', 'Sin garantía'):
            self.assertTrue(guard.may_press(element(label), on_checkout=True, stage='money', page=page), label)
        self.assertEqual(guard.stage_of(snap('Total S/. 120.00', f'{BASE}/checkout/pago', elements=[]),
                                        on_checkout=True), 'money')
        # A sign-in or offer step with no figure stays free.
        offer = snap('¿Quieres Prime?', f'{BASE}/checkout/p/1/pip', elements=[])
        self.assertEqual(guard.stage_of(offer, on_checkout=True), 'open')

    def test_the_address_is_read_beside_the_payment_not_from_the_header(self):
        text = ('Enviar a Julian - Ciudad 01000 Buscar ... Enviando a Ana Perez, Calle 1 #23, CDMX Cambiar '
                'Llega mañana Metodo de pago SPEI Total del pedido $189.00')
        self.assertEqual(ship_to(text), 'ana perez, calle 1 #23, cdmx')
        self.assertTrue(guard.may_press(element('Envío estándar (Predeterminada)', role='radio'), on_checkout=True,
                                        stage='final'))
        self.assertTrue(guard.may_press(element('Sin garantía'), on_checkout=True))

    def test_a_product_page_is_its_add_to_cart_and_the_way_on(self):
        product = snap('Chocolate Abuelita. Agrega la garantía!', f'{BASE}/p/MLB1', elements=[
            element('Agregar al carrito', ref=0), element('Agregar garantía extendida', ref=1),
            element('Ver más productos del vendedor', ref=2, tag='a', href=f'{BASE}/loja/x'),
            element('Seguir al vendedor', ref=3), element('Cerrar', ref=4)])
        stage = guard.stage_of(product, on_checkout=False)
        self.assertEqual(stage, 'shopping')
        pressed = {label: guard.may_press(element(label), on_checkout=False, stage=stage)
                   for label in ('Agregar al carrito', 'Agregar garantía extendida', 'Seguir al vendedor', 'Cerrar',
                                 'Ir al carrito')}
        self.assertEqual(pressed, {'Agregar al carrito': True, 'Agregar garantía extendida': False,
                                   'Seguir al vendedor': False, 'Cerrar': True, 'Ir al carrito': True})

    def test_the_delivery_address_is_part_of_the_approval(self):
        page = checkout_page(extra='Enviar a Ana Pérez, Calle 1 #23, CDMX Cambiar')
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate Ibarra', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertIn('calle 1', task.order['address'])
        task = service.approve(self.account, self.user, task.internal_id)
        moved = checkout_page(extra='Enviar a Otra Persona, Av 9, GDL Cambiar')
        task = self.step(task, moved)
        self.reader.click.assert_not_called()   # another address: asked again
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))

    def test_what_changes_the_account_or_buys_something_else_is_never_pressed(self):
        task = self.make_task(phase='ordering')
        for label in ('Cancelar pedido', 'Prueba Prime gratis', 'Comprar novamente', 'Eliminar dirección',
                      'Comprar con 1-Clic', 'Cerrar sesión'):
            page = snap('Total R$ 1,00', CHECKOUT, elements=[element(label, ref=0)])
            self.operate.return_value = ('press', {'ref': 0})
            task = self.step(task, page)
            self.reader.click.assert_not_called()
        account = snap('x', CHECKOUT, elements=[element('Sair', ref=0, tag='a', href=f'{BASE}/logout')])
        self.step(task, account)
        self.reader.click.assert_not_called()

    def test_the_order_is_named_and_waits_for_the_person_with_fixed_words(self):
        task = self.named()
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))
        self.assertEqual((task.order['item'], task.order['total'], task.order['amount']),
                         ('Chocolate Ibarra', 'R$ 189,00', '189.00'))
        self.reader.click.assert_not_called()
        # What the store wrote is on the card only: the note (the assistant's history) has fixed words.
        note = self.post.call_args.args[1]
        self.assertNotIn('Ibarra', note)
        self.assertNotIn('189', note)
        self.assertIsNone(task.checkout_at)

    def test_never_named_with_a_card_selected_or_the_rail_missing(self):
        both = checkout_page()
        both.elements.append(element('Cartão de crédito final 4242', ref=5, role='radio', tag='div', checked=True))
        for page in (both, checkout_page(method='Cartão de crédito final 4242'),
                     checkout_page(method='Entrega padrão', extra='Visa terminada en 4242'),
                     checkout_page(method='Entrega padrão')):
            task = self.named(page)
            self.assertEqual(task.state, 'working')
            self.assertIn('payment method', task.history[-1]['result'])
            AgentTask.objects.filter(pk=task.pk).update(state='cancelled')

    def test_the_total_is_the_whole_figure_beside_total(self):
        for total in ('R$ 89,00', 'R$ 189,0'):                       # a piece of the figure
            self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate Ibarra', 'total': total})
            task = self.step(self.make_task(phase='ordering'), checkout_page())
            self.assertIn('refused', task.history[-1]['result'])
            AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        # A subtotal, or a figure a seller's title carries, is not the total.
        page = snap('Chocolate R$ 12,00 Subtotal R$ 150,00 Frete R$ 39,00 Total R$ 189,00', CHECKOUT,
                    elements=checkout_page().elements)
        for total in ('R$ 150,00', 'R$ 12,00'):
            self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': total})
            task = self.step(self.make_task(phase='ordering'), page)
            self.assertIn('refused', task.history[-1]['result'])
            AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        self.assertEqual(operate.amount_of('R$ 1.234,56'), Decimal('1234.56'))
        self.assertEqual(operate.amount_of('$1,249.00'), Decimal('1249.00'))
        self.assertEqual(operate.amount_of('Bs 350'), Decimal('350.00'))

    def test_only_a_final_looking_button_of_a_checkout_page_is_named(self):
        self.operate.return_value = ('ready_to_order', {'ref': 3, 'item': 'Chocolate Ibarra', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering'), checkout_page())      # "Continuar"
        self.assertIn('the button that places', task.history[-1]['result'])
        AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        product = snap('Chocolate Ibarra Total R$ 189,00', f'{BASE}/p/1', elements=[
            element('Pix', ref=0, role='radio', tag='div', checked=True), element('Comprar agora', ref=1)])
        task = self.named(product)                                                # a product page's "buy now"
        self.assertIn('the button that places', task.history[-1]['result'])

    def test_approved_it_is_pressed_once_and_the_approval_is_used_up(self):
        task = self.approved()
        task = self.step(task, checkout_page())
        self.reader.click.assert_called_once()
        self.assertEqual(self.reader.click.call_args.args[0]['label'], 'Confirmar pedido')
        self.assertEqual((task.phase, task.order.get('approved')), ('ordered', None))
        self.assertIsNotNone(task.checkout_at)

    def test_approved_pressed_and_shown_the_order_becomes_a_payment_card(self):
        # The whole way, with no order state written by hand: approve, press, the order's page, the card.
        prepare = self.patch('payment_accounts.payment_intents.prepare')
        cancel = self.patch('payment_accounts.payment_intents.cancel')
        prepare.return_value = SimpleNamespace(currency='BRL', amount_exact=True, amount_local=Decimal('189.00'),
                                               internal_id='intent-1', payee_level='institution_charge',
                                               rail_method_id='br_qr')
        task = self.step(self.approved(), checkout_page())
        self.assertEqual(task.phase, 'ordered')
        self.operate.return_value = ('payment_shown', {})
        task = self.step(task, DONE)
        self.assertEqual(task.state, 'awaiting_code')
        self.read.return_value = [(CODE, 200)]
        self.browser.capture.return_value = (picture(url=DONE.url), picture(url=DONE.url))
        real = runner.Step.save

        def save(step, **fields):
            fields.pop('payment_intent', None)
            return real(step, **fields)

        self.task = task
        self.reading()
        task.save()
        with mock.patch.object(runner.Step, 'save', save):
            task = self.step(task)
        self.assertEqual(came_of(task), 'prepared')
        cancel.assert_not_called()

    def test_an_order_confio_cannot_pay_says_so_before_it_is_confirmed(self):
        self.mode.side_effect = None
        self.mode.return_value = ('manual', 'br_qr')
        task = self.named()
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))
        self.assertEqual((task.order['manual'], task.order['offer']), (True, 'br_qr'))
        self.assertIn('no puedo pagarlo yo', self.post.call_args.args[1])
        self.assertIn('desde tu banco', self.post.call_args.args[1])
        # The card they confirm on says it too.
        from agent_tasks.schema import task_type
        self.assertIn('no puedo pagarlo yo', task_type(task).message)
        # Approved as "they pay it": if Confío could pay it by the time it is pressed, they are asked again.
        task = service.approve(self.account, self.user, task.internal_id)
        self.assertTrue(task.order['approved']['manual'])
        self.mode.return_value = ('confio', '')
        task = self.step(task, checkout_page())
        self.reader.click.assert_not_called()
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))

    @override_settings(AGENT_TASKS_MANUAL_COUNTRIES=('PE',))
    def test_where_the_person_pays_it_any_way_but_a_card_or_a_wallet(self):
        for method, approved in (('Transferencia bancaria', True), ('PagoEfectivo', True), ('PayPal', False),
                                 ('Tarjeta de crédito', False), ('Mercado Pago', False),
                                 ('PagoEfectivo (banca móvil, Yape, Plin, agentes)', True), ('PSE', False),
                                 ('QR de Mercado Pago', False), ('Yape', False), ('MODO', False),
                                 ('Transferencia con Bancolombia', False), ('Efectivo en Rapipago', True)):
            with self.subTest(method=method):
                AgentTask.objects.filter(user=self.user).update(state='cancelled')
                page = checkout_page(total='S/ 189,00', url='https://tienda.com.pe/checkout/review', method=method)
                self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': 'S/ 189,00'})
                task = self.step(self.make_task(phase='ordering', goal='chocolate', site='tienda.com.pe',
                                                country='PE'), page)
                self.assertEqual(task.reason == 'approve', approved, task.history[-1])

    def test_the_same_purchase_on_the_next_page_is_pressed_under_its_approval(self):
        task = self.approved()
        self.operate.return_value = self.ORDER
        task = self.step(task, checkout_page(url=f'{BASE}/checkout/other'))
        self.reader.click.assert_called_once()

    def test_an_approved_button_that_was_only_a_way_on_leads_to_the_stores_final_one_once(self):
        # A payment step's "Continuar" on the page with the total and the method, approved; then the review.
        page = snap('Chocolate Ibarra Forma de pagamento Pix Total do pedido R$ 189,00', CHECKOUT, elements=[
            element('Pix', ref=0, role='radio', tag='input', type='radio', checked=True), element('Continuar', ref=1)])
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate Ibarra', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertEqual(task.reason, 'approve')
        task = service.approve(self.account, self.user, task.internal_id)
        task = self.step(task, page)
        self.reader.click.assert_called_once()
        self.assertEqual(task.phase, 'ordered')
        self.reader.click.reset_mock()
        # The store shows its review, with its own final button: the same purchase, no new ask, pressed once.
        self.operate.return_value = ('not_placed', {'ref': 1})
        task = self.step(task, page)   # the page it was pressed on, whatever its button says now: never twice
        self.reader.click.assert_not_called()
        self.assertIn('never twice', task.history[-1]['result'])
        review = f'{BASE}/checkout/final'
        task = self.step(task, checkout_page(url=review))
        self.reader.click.assert_called_once()
        self.assertEqual(len(task.order['pressed_at']), 2)
        for again in (review, f'{review}?step=2', f'{review}#x'):   # a slow store, a reload: never twice
            task = self.step(task, checkout_page(url=again))
            self.assertIn('never twice', task.history[-1]['result'])
        self.reader.click.assert_called_once()

    def test_after_the_order_another_total_or_a_card_is_never_pressed_under_its_approval(self):
        page = snap('Chocolate Ibarra Forma de pagamento Pix Total do pedido R$ 189,00', CHECKOUT, elements=[
            element('Pix', ref=0, role='radio', tag='input', type='radio', checked=True), element('Continuar', ref=1)])
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate Ibarra', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        task = self.step(service.approve(self.account, self.user, task.internal_id), page)
        self.reader.click.reset_mock()
        self.operate.return_value = ('not_placed', {'ref': 1})
        final = f'{BASE}/checkout/final'
        for other in (checkout_page(total='R$ 999,00', url=final), checkout_page(method='Cartão de crédito', url=final)):
            task = self.step(task, other)
            self.assertIn('not the order the person approved', task.history[-1]['result'])
        self.reader.click.assert_not_called()

    def test_after_the_approved_press_nothing_else_is_pressed(self):
        self.operate.return_value = self.ORDER
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), checkout_page())
        task = self.step(service.approve(self.account, self.user, task.internal_id), checkout_page())
        self.reader.click.assert_called_once()
        self.reader.click.reset_mock()
        self.operate.return_value = ('wait', {})
        task = self.step(task, snap('Gracias Tu pedido está en camino', f'{BASE}/checkout/done', elements=[]))
        self.assertEqual((task.phase, task.order.get('approved')), ('ordered', None))
        self.reader.click.assert_not_called()

    def test_a_press_after_the_approval_ends_it(self):
        task = self.approved()
        self.operate.return_value = ('press', {'ref': 0})   # the Pix choice: anything at all
        task = self.step(task, checkout_page())
        self.assertIsNone(task.order['approved'])

    def test_another_total_or_item_is_never_pressed_it_is_asked_again(self):
        for change in ({'total': 'R$ 249,00'},):
            task = self.approved()
            page = checkout_page(**change)
            self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate Ibarra',
                                                            'total': change.get('total', 'R$ 189,00')})
            task = self.step(task, page)
            self.reader.click.assert_not_called()
            self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))
            AgentTask.objects.filter(pk=task.pk).update(state='cancelled')

    def test_a_click_that_never_reached_it_is_no_order_but_one_that_did_is_never_repeated(self):
        task = self.approved()
        self.reader.click.return_value = 'covered'
        task = self.step(task, checkout_page())
        self.assertEqual((task.phase, task.checkout_at), ('ordering', None))   # kept its approval: named again
        self.reader.click.return_value = ''
        task = self.step(task, checkout_page())      # clicked; the slow page still shows the button
        self.assertEqual(task.phase, 'ordered')
        self.reader.click.reset_mock()
        self.operate.return_value = self.ORDER
        task = self.step(task, checkout_page())      # the same button, the same total: never a second press
        self.reader.click.assert_not_called()
        self.assertTrue(self.operate.call_args.kwargs['after'])

    def test_an_anchor_dressed_as_the_final_button_is_never_pressed(self):
        task = self.make_task(phase='ordering')
        page = checkout_page()
        # In-store hrefs: refused for being the final button, not for leaving the store.
        page.elements.append(element('Confirmar compra', ref=5, tag='a', href=f'{BASE}/checkout/confirm', role='button'))
        page.elements.append(element('Finalizar compra', ref=6, tag='a', href=f'{BASE}/checkout/place'))
        for ref in (5, 6):
            self.operate.return_value = ('press', {'ref': ref})
            task = self.step(task, page)
            self.assertIn('refused', task.history[-1]['result'])
        self.reader.click.assert_not_called()

    def test_amazons_real_spei_review_page_goes_to_the_persons_approval_then_is_pressed(self):
        # The founder's 10:36 run, replayed through the real order step on the recorded page.
        from agent_tasks.tests.test_real_pages import recorded
        real = recorded('amazon_mx_review_spei')
        item = 'De la Rosa Coconugs Chocolate con Coco, 336 g'
        page = snap(f'{real.text}\n{item}', real.url, elements=real.elements)   # the item prints below the first 1500 chars
        final = next(index for index, e in enumerate(real.elements) if e['label'] == 'Realiza tu pedido y paga')
        task = self.make_task(phase='ordering', site='amazon.com.mx', country='MX', goal='un chocolate',
                              options=[{'title': item, 'price': '$55.48', 'image': '', 'href': 'https://www.amazon.com.mx/dp/B0X'}])
        self.operate.return_value = ('ready_to_order', {'ref': final, 'item': item, 'total': '$99.48'})
        task = self.step(task, page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'), task.history[-1])
        self.assertEqual((task.order['total'], task.order['item']), ('$99.48', item))
        self.assertIn('calle falsa 123', task.order['address'])
        self.reader.click.assert_not_called()
        task = self.step(service.approve(self.account, self.user, task.internal_id, total='$99.48'), page)
        self.reader.click.assert_called_once()
        self.assertEqual(self.reader.click.call_args.args[0]['label'], 'Realiza tu pedido y paga')
        self.assertEqual(task.phase, 'ordered')

    def test_amazons_cart_page_lets_the_model_set_other_items_aside(self):
        # The founder's cart, 03:21: the real page, with prices and the way to the checkout on it.
        cart = snap('Carrito Turin Magno Chocolates $89.00 Volteck Adaptador $159.00 Subtotal (2 productos): $248.00',
                    'https://www.amazon.com.mx/gp/cart/view.html', elements=[
                        element('Proceder al pago', ref=0), element('Eliminar Volteck Adaptador | Eliminar', ref=1),
                        element('Guardar para más tarde Volteck Adaptador de Enchufe Tipo E a Tipo A', ref=2)])
        for on_checkout in (True, False):
            stage = guard.stage_of(cart, on_checkout=on_checkout)
            self.assertEqual(stage, 'open')
            for ref in (1, 2):
                self.assertTrue(guard.may_press(cart.element(ref), on_checkout=on_checkout, stage=stage, page=cart))

    def test_a_click_the_judge_cannot_tell_is_one_tap_for_the_person(self):
        page = snap('Carrito', f'{BASE}/gp/cart', elements=[element('Mover a la lista', ref=0)])
        self.judge.side_effect = None
        self.judge.return_value = ('unsure', 'unknown control')
        self.operate.return_value = ('press', {'ref': 0})
        task = self.step(self.make_task(phase='ordering'), page)
        self.reader.click.assert_not_called()
        self.assertEqual((task.state, task.reason), ('needs_person', 'step'))
        from agent_tasks.schema import task_type
        self.assertIn('«Mover a la lista»', task_type(task).message)
        task = service.answer_step(self.account, self.user, task.internal_id, True)
        self.judge.reset_mock()
        task = self.step(task, page)
        self.reader.click.assert_called_once()   # that very control, on that page, once
        self.judge.assert_not_called()
        self.assertIsNone(task.order.get('allowed_step'))

    def test_the_judge_decides_each_press_and_no_word_list_does(self):
        # What it reads as placing the order, a card or the account is never pressed; what it calls safe is,
        # whatever the control's words.
        page = snap('Envío', CHECKOUT, elements=[element('Empieza tu prueba gratis', ref=0)])
        self.operate.return_value = ('press', {'ref': 0})
        for verdict in ('places_order', 'card', 'account', 'request'):
            with self.subTest(verdict=verdict):
                self.judge.side_effect = None
                self.judge.return_value = (verdict, 'as it read the page')
                task = self.step(self.make_task(phase='ordering'), page)
                self.reader.click.assert_not_called()
                self.assertIn('refused', task.history[-1]['result'])
                AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        self.judge.return_value = ('safe', 'declines the offer')
        self.step(self.make_task(phase='ordering'), snap('Envío', CHECKOUT, elements=[element('No gracias', ref=0)]))
        self.reader.click.assert_called_once()

    def test_unsure_on_a_checkout_asks_the_person_about_that_one_step(self):
        self.judge.side_effect = None
        self.judge.return_value = ('unsure', '')
        page = snap('Envío Total $189.00', CHECKOUT, elements=[element('Siguiente paso', ref=0)])
        self.operate.return_value = ('press', {'ref': 0})
        task = self.step(self.make_task(phase='ordering'), page)
        self.assertEqual(task.reason, 'step')
        self.reader.click.assert_not_called()

    def test_the_browser_loads_amazons_prime_decline_and_never_a_sign_out(self):
        # The founder's 04:15 run: "No gracias" was clicked, and the browser's own filter stopped its page.
        self.assertFalse(guard.account_address('https://www.amazon.com.mx/checkout/p/p-703-5961383-3177812/prime/handler'))
        for url in (f'{BASE}/logout', f'{BASE}/account/delete', f'{BASE}/unsubscribe', f'{BASE}/gp/flex/sign-out'):
            self.assertTrue(guard.account_address(url), url)

    def test_a_pages_own_toggle_links_are_not_refused_by_their_address(self):
        # Recorded on Amazon México: "Ver más", "Ver más opciones" are javascript:void(0) links.
        self.assertTrue(guard.toggle_link('javascript:void(0)'))
        self.assertFalse(guard.toggle_link('javascript:fetch("/x")'))
        # And the checkout presses it: it stays on the page.
        page = snap('Selecciona un método de pago', CHECKOUT, elements=[
            element('Mostrar más métodos de pago', ref=0, tag='a', href='javascript:void(0)')])
        self.operate.return_value = ('press', {'ref': 0})
        self.step(self.make_task(phase='ordering'), page)
        self.reader.click.assert_called_once()

    def test_unsure_is_never_a_dead_end_the_person_is_asked_about_that_step(self):
        self.judge.side_effect = None
        self.judge.return_value = ('unsure', 'which method is selected is not shown')
        page = snap('Selecciona un método de pago Total del pedido $89.00', CHECKOUT,
                    elements=[element('Usar este método de pago', ref=0)])
        self.operate.return_value = ('press', {'ref': 0})
        task = self.step(self.make_task(phase='ordering'), page)
        self.reader.click.assert_not_called()
        self.assertEqual((task.state, task.reason), ('needs_person', 'step'))

    def test_a_yes_is_for_that_control_only_and_the_next_step_only(self):
        page = snap('Carrito', f'{BASE}/gp/cart', elements=[element('Mover', ref=0),
                                                            element('Mover', ref=1, tag='a', href=f'{BASE}/lista')])
        self.judge.side_effect = None
        self.judge.return_value = ('unsure', '')
        self.operate.return_value = ('press', {'ref': 0})
        task = self.step(self.make_task(phase='ordering'), page)
        task = service.answer_step(self.account, self.user, task.internal_id, True)
        self.operate.return_value = ('press', {'ref': 1})   # same words, another control: judged again
        task = self.step(task, page)
        self.reader.click.assert_not_called()
        self.assertIsNone(task.order.get('allowed_step'))   # and the yes is gone

    def test_no_to_a_step_sends_the_agent_another_way(self):
        page = snap('Carrito', f'{BASE}/gp/cart', elements=[element('Mover a la lista', ref=0)])
        self.judge.side_effect = None
        self.judge.return_value = ('unsure', '')
        self.operate.return_value = ('press', {'ref': 0})
        task = self.step(self.make_task(phase='ordering'), page)
        task = service.answer_step(self.account, self.user, task.internal_id, False)
        self.assertEqual(task.state, 'working')
        self.assertIn('said no', task.history[-1]['did'])

    def test_the_judge_never_lets_a_card_or_the_account_through_and_its_outage_asks(self):
        page = snap('Pago', CHECKOUT, elements=[element('Agregar método', ref=0)])
        self.operate.return_value = ('press', {'ref': 0})
        self.judge.side_effect = None
        for verdict in ('card', 'account'):
            self.judge.return_value = (verdict, 'x')
            task = self.step(self.make_task(phase='ordering'), page)
            self.assertIn('Never a card', task.history[-1]['result'])
            AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        self.judge.side_effect = agent.AgentUnavailable('down')
        task = self.step(self.make_task(phase='ordering'), page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'step'))
        self.reader.click.assert_not_called()

    def test_another_item_in_the_cart_is_set_aside_not_ordered(self):
        # The founder's cart, 2026-11-24: a plug adapter already in it beside the chocolate.
        for label in ('Guardar para más tarde Volteck Adaptador de Enchufe Tipo E a Tipo A', 'Eliminar Volteck Adaptador'):
            with self.subTest(label=label):
                self.assertTrue(guard.may_press(element(label), on_checkout=False))
        for label in ('Eliminar mi cuenta', 'Eliminar dirección', 'Comprar ahora'):
            with self.subTest(label=label):
                self.assertFalse(guard.may_press(element(label), on_checkout=False))

    def test_amazons_prime_offer_is_declined_never_joined(self):
        # The founder's order, 2026-11-24: Amazon's /checkout/p/.../pip page between the sign-in and the review.
        self.assertTrue(guard.may_press(element('No gracias | No gracias, continuar sin Amazon Prime'),
                                        on_checkout=True))
        self.assertTrue(guard.may_press(element('Continuar sin Prime'), on_checkout=True))
        for label in ('Prueba Prime gratis', 'Únete a Prime', 'No gracias | Probar Prime gratis 30 días',
                      'Suscribirme a Prime'):
            with self.subTest(label=label):
                self.assertFalse(guard.may_press(element(label), on_checkout=True))

    def test_a_method_radio_that_says_pay_with_it_may_be_chosen(self):
        self.assertTrue(guard.may_press(element('Pagar con SPEI', tag='input', type='radio'), on_checkout=True))
        self.assertFalse(guard.may_press(element('Pagar con SPEI', tag='label'), on_checkout=True))

    def test_an_add_to_cart_below_the_fold_is_pressed_for_real(self):
        # The founder's Amazon México order, 2026-11-24: the buy box was outside the first screen.
        task = self.make_task(phase='ordering')
        page = snap('Turin Magno Chocolates 73.6 g', f'{BASE}/p/MLB1', elements=[
            element('Agregar al carrito', ref=0, tag='input', type='submit', on_screen=False)])
        self.operate.return_value = ('press', {'ref': 0})
        task = self.step(task, page)
        self.reader.click.assert_called_once()
        self.assertEqual(task.history[-1]['result'], 'pressed')

    def test_a_label_or_tab_for_the_final_button_is_never_pressed(self):
        task = self.make_task(phase='ordering')
        page = checkout_page()
        page.elements.append(element('Confirmar compra', ref=5, tag='label'))
        page.elements.append(element('Realizar pedido', ref=6, role='tab'))
        for ref in (5, 6):
            self.operate.return_value = ('press', {'ref': ref})
            task = self.step(task, page)
            self.assertIn('refused', task.history[-1]['result'])
        self.reader.click.assert_not_called()

    def test_a_change_link_beside_the_method_does_not_hide_it(self):
        text = ('Revisar pedido Chocolate Alterar forma de pagamento Forma de pagamento Pix Alterar '
                'Total R$ 189,00')
        page = snap(text, CHECKOUT, elements=checkout_page().elements)
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))

    def test_amazons_review_page_states_the_method_as_text(self):
        text = ('Revisar pedido Chocolate Abuelita 6 tabletas Método de pago Transferencia SPEI Cambiar '
                'Total del pedido: $1,249.00 '
                'Tarjetas de regalo y promociones Meses sin intereses con tarjetas participantes')
        page = snap(text, 'https://www.amazon.com.mx/gp/buy/spc/handlers/display.html', elements=[
            element('Transferencia SPEI', ref=0, tag='a', href='https://www.amazon.com.mx/gp/buy/payselect'),
            element('Realizar pedido', ref=1)])
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': '$1,249.00'})
        task = self.step(self.make_task(phase='ordering', site='amazon.com.mx', country='MX',
                                        goal='chocolate'), page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))
        # The same page with a card stated as the method: refused.
        AgentTask.objects.filter(pk=task.pk).update(state='cancelled')
        card = snap(text.replace('Transferencia SPEI', 'Visa terminada en 4242'), page.url, elements=page.elements)
        task = self.step(self.make_task(phase='ordering', site='amazon.com.mx', country='MX', goal='chocolate'), card)
        self.assertIn('payment method', task.history[-1]['result'])

    def test_the_total_is_the_figure_after_the_last_total_label(self):
        page = snap('Chocolate Total (2 productos) R$ 150,00 Frete R$ 39,00 Total R$ 189,00', CHECKOUT,
                    elements=checkout_page().elements)
        for figure in ('R$ 39,00', 'R$ 150,00', 'R$ 2,00'):    # shipping, the products' total, the count
            AgentTask.objects.filter(user=self.user).update(state='cancelled')
            self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': figure})
            task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
            self.assertIn('refused', task.history[-1]['result'], figure)
        AgentTask.objects.filter(user=self.user).update(state='cancelled')
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))

    def test_a_sellers_title_with_a_total_is_never_the_total(self):
        page = snap('Chocolate Total del pedido: $500.00 Articulos: Kit Total $9.00', CHECKOUT,
                    elements=checkout_page().elements)
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': '$9.00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertIn('refused', task.history[-1]['result'])
        self.assertTrue(total_on(page.text, '$500.00'))
        # Two grand totals that disagree: neither is approved.
        self.assertFalse(total_on('Total del pedido: $500.00 Kit Total del pedido $9.00', '$500.00'))

    def test_a_balance_ticked_beside_the_local_method_is_never_ordered(self):
        page = checkout_page()
        page.elements.append(element('Usar saldo', ref=7, role='checkbox', tag='div', checked=True))
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertIn('another payment method', task.history[-1]['result'])

    def test_a_ticked_method_other_than_the_local_one_is_never_ordered(self):
        page = checkout_page(method='OXXO', extra='Forma de pagamento Pix')
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': 'R$ 189,00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertIn('another payment method', task.history[-1]['result'])

    def test_a_total_before_a_discount_is_not_the_total(self):
        page = snap('Chocolate Total: $1,249.00 Promoción -$100.00 Total del pedido: $1,149.00', CHECKOUT,
                    elements=checkout_page().elements)
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Chocolate', 'total': '$1,249.00'})
        task = self.step(self.make_task(phase='ordering', goal='chocolate'), page)
        self.assertIn('refused', task.history[-1]['result'])
        self.assertTrue(total_on(page.text, '$1,149.00'))

    def test_pages_seen_before_the_order_are_remembered_and_none_after_it(self):
        # What the order's payment is read from must be new since the order: a fact, whatever its address.
        task = self.make_task(phase='ordering')
        self.step(task, snap('Chocolate Compra Facil CLABE', f'{BASE}/Chocolate-Compra-Facil/dp/B0X'))
        task.refresh_from_db()
        self.assertEqual(len(task.visited_pages), 1)
        AgentTask.objects.filter(pk=task.pk).update(phase='ordered', checkout_at=timezone.now(), state='working')
        task.refresh_from_db()
        self.step(task, snap('Tu pedido', f'{BASE}/compras/9'))
        task.refresh_from_db()
        self.assertEqual(len(task.visited_pages), 1)

    def test_after_the_order_only_links_the_judge_calls_safe_open(self):
        task = self.make_task(phase='ordered', checkout_at=timezone.now())
        page = snap('Gracias por tu compra', f'{BASE}/checkout/congrats', elements=[
            element('Volver a comprar', ref=0, tag='a', href=f'{BASE}/p/1'),
            element('Ver detalle', ref=1, tag='a', href=f'{BASE}/compras/123'),
            element('Ayuda', ref=2, tag='a', href='https://evil.com/help')])
        self.judge.side_effect = lambda task, seen, pressed, meter: (
            ('account', 'buys again') if pressed['label'] == 'Volver a comprar' else ('safe', ''))
        for ref, said in ((0, 'refused: account'), (2, 'leaves the store')):
            self.operate.return_value = ('press', {'ref': ref})
            task = self.step(task, page)
            self.assertIn(said, task.history[-1]['result'])
        self.reader.click.assert_not_called()
        self.operate.return_value = ('press', {'ref': 1})
        task = self.step(task, page)
        self.assertEqual(task.history[-1]['result'], 'pressed')

    def test_a_product_page_is_never_an_orders_page(self):
        for url in (f'{BASE}/Chocolate-Compra-Facil/dp/B0X', f'{BASE}/gp/product/B0X',
                    'https://produto.mercadolivre.com.br/MLB-123-pago-pix', f'{BASE}/pagamento-facil/p/MLB9',
                    # A seller's profile, a brand store, a search, a store's front: named by whoever owns them.
                    'https://www.mercadolivre.com.br/perfil/PAGAMENTOS', 'https://lista.mercadolivre.com.br/compras',
                    'https://www.amazon.com.mx/stores/Gracias/page/ABC', 'https://www.amazon.com.mx/stores/page/A#pagos',
                    f'{BASE}/loja/compras/9', f'{BASE}/compras',
                    # A seller's words before a checkout's: still the seller's page.
                    'https://tienda.com.bo/producto/checkout/1', 'https://tienda.com.bo/p/checkout',
                    'https://tienda.com.bo/categoria/pagos/2', 'https://tienda.com.bo/u/vendedor/orders/1',
                    'https://tienda.com.bo/@vendedor1/pedidos/2'):
            self.assertFalse(guard.order_address(url), url)
        for url in ('https://www.amazon.com.mx/gp/buy/thankyou/handlers/display.html',
                    'https://www.amazon.com.mx/gp/your-account/order-details',
                    'https://www.mercadolivre.com.br/compras/123', f'{BASE}/checkout/congrats',
                    'https://www.amazon.com.mx/checkout/p/p-701-1/thankyou', 'https://tienda.com.bo/pedido/9'):
            self.assertTrue(guard.order_address(url), url)

    def test_an_order_nobody_approved_gets_no_payment_card(self):
        prepare = self.patch('payment_accounts.payment_intents.prepare')
        self.patch('payment_accounts.payment_intents.cancel')
        prepare.return_value = SimpleNamespace(currency='BRL', amount_exact=True, amount_local=Decimal('189.00'),
                                               internal_id='intent-1', payee_level='institution_charge',
                                               rail_method_id='br_qr')
        self.read.return_value = [(CODE, 200)]
        cancel = self.patch('payment_accounts.payment_intents.cancel')
        for order in ({'unapproved': True}, {'unapproved': True, 'amount': '189.00', 'total': 'R$ 189,00'},
                      {'amount': '189.00', 'total': 'R$ 189,00', 'approved': {'total': 'R$ 189,00'}}):
            AgentTask.objects.filter(user=self.user).update(state='cancelled')
            cancel.reset_mock()
            task = self.make_task(state='awaiting_code', phase='ordered', checkout_at=timezone.now(),
                                  shown_target='tab-1', order=order)
            task = self.step(task)
            self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'), order)
        prepare.assert_not_called()   # nothing is even prepared for an order nobody approved

    def test_the_card_says_what_the_total_is_made_of(self):
        from agent_tasks.schema import task_type
        self.review.side_effect = lambda task, page, element, item, meter: {
            **review_by_words(task, page, element, item, meter),
            'lines': [{'kind': 'products', 'amount': 'R$ 150,00'}, {'kind': 'shipping', 'amount': 'R$ 39,00'}]}
        task = self.named(checkout_page(extra='Produtos R$ 150,00 Frete R$ 39,00'))
        self.assertEqual(task.reason, 'approve')
        shown = task_type(task)
        self.assertIn('Total R$ 189,00: productos R$ 150,00 + envío R$ 39,00.', shown.message)
        self.assertEqual([(line.label, line.value) for line in shown.order.breakdown],
                         [('Productos', 'R$ 150,00'), ('Envío', 'R$ 39,00')])
        self.assertIn('envío R$ 39,00', self.post.call_args.args[1])   # the chat line says it too

    def test_the_approval_is_for_the_total_on_the_card_they_saw(self):
        task = self.named()
        with self.assertRaises(service.TaskRefused):
            service.approve(self.account, self.user, task.internal_id, total='R$ 99,00')
        self.assertEqual(service.approve(self.account, self.user, task.internal_id, total='R$ 189,00').state, 'working')

    def test_amazons_verification_steps_are_its_sign_in(self):
        for path in ('/ap/signin', '/ap/cvf/request', '/ap/mfa', '/ax/claim/signin', '/ap/challenge'):
            self.assertTrue(guard.login_address(f'https://www.amazon.com.mx{path}'), path)



    def test_nobody_approves_what_they_could_not_pay(self):
        self.payable.side_effect = service.TaskRefused('unavailable')
        task = self.step(self.make_task(), snap(url=CHECKOUT))
        self.assertEqual((task.state, task.reason), ('stopped', 'cannot_pay'))
        self.operate.assert_not_called()

    def test_an_order_the_store_shows_placed_is_said_never_denied(self):
        self.operate.return_value = ('order_placed', {})
        task = self.step(self.make_task(phase='ordering'), DONE)
        self.assertEqual((task.phase, task.order['unapproved']), ('ordered', True))
        self.assertIsNotNone(task.checkout_at)

    def test_after_the_order_only_links_to_its_pages_then_the_runner_reads(self):
        task = self.make_task(phase='ordered', checkout_at=timezone.now())
        page = snap('Tu pedido', f'{BASE}/compras/9', elements=[
            element('Cancelar pedido', ref=0), element('Volver a comprar', ref=1, tag='a', href=f'{BASE}/p/1'),
            element('Confirmar pedido', ref=2), element('Ver instrucciones de pago', ref=3, tag='a',
                                                        href=f'{BASE}/compras/9/pago')])
        self.judge.side_effect = lambda task, seen, pressed, meter: {
            'Volver a comprar': ('account', 'buys again'), 'Cancelar pedido': ('request', 'cancels it'),
            'Confirmar pedido': ('places_order', 'another order')}.get(pressed['label'], ('safe', ''))
        for ref, pressed in ((0, False), (1, False), (2, False), (3, True)):
            self.reader.click.reset_mock()
            self.operate.return_value = ('press', {'ref': ref})
            task = self.step(task, page)
            self.assertEqual(self.reader.click.called, pressed, ref)
        self.assertTrue(self.operate.call_args.kwargs['after'])
        # The payment is only "shown" on the order's own page.
        self.operate.return_value = ('payment_shown', {})
        task = self.step(task, snap('QR', f'{BASE}/p/1'))
        self.assertEqual(task.state, 'working')
        task = self.step(task, page)
        self.assertEqual((task.state, task.shown_target), ('awaiting_code', 'tab-9'))

    def test_the_facts_do_not_live_in_the_rolling_history(self):
        long = [{'did': 'wait', 'result': 'ok'}] * runner.HISTORY_KEPT
        task = self.make_task(phase='ordered', checkout_at=timezone.now(), history=long)
        self.operate.return_value = self.ORDER
        task = self.step(task, checkout_page())
        self.reader.click.assert_not_called()          # never a second order
        self.decide.assert_not_called()                # never back to shopping
        self.assertTrue(self.operate.call_args.kwargs['after'])

    def test_a_payment_that_is_not_read_goes_back_to_the_agent_then_ends_honestly(self):
        self.task = self.make_task(state='awaiting_code', phase='ordered', checkout_at=timezone.now(),
                                   shown_target='tab-1')
        task = self.step(self.task)
        self.assertEqual((task.state, task.history[-1]['did']), ('working', runner.UNREAD))
        with mock.patch('agent_tasks.operate.MAX_UNREAD', 1):
            self.reading()
            self.task.save()
            task = self.step(self.task)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('Puede que el pedido haya quedado hecho', self.post.call_args.args[1])

    def test_a_payment_for_another_amount_or_on_a_shopping_page_is_never_offered(self):
        prepare = self.patch('payment_accounts.payment_intents.prepare')
        cancel = self.patch('payment_accounts.payment_intents.cancel')
        prepare.return_value = SimpleNamespace(currency='BRL', amount_exact=True, amount_local=Decimal('91.90'),
                                               internal_id='intent-1', payee_level='institution_charge',
                                               rail_method_id='br_qr')
        self.read.return_value = [(CODE, 200)]
        self.task = self.make_task(state='awaiting_code', phase='ordered', checkout_at=timezone.now(),
                                   shown_target='tab-1', order={'amount': '189.00', 'total': 'R$ 189,00', 'pressed': True, 'approved': {'total': 'R$ 189,00'}})
        task = self.step(self.task)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        cancel.assert_called_with(self.account, 'intent-1')
        # A page the agent read while shopping (a seller's product page): not read at all.
        prepare.reset_mock()
        self.browser.capture.return_value = (picture(url=f'{BASE}/p/1'), picture(url=f'{BASE}/p/1'))
        self.reading()
        self.task.visited_pages = [runner.same_page(f'{BASE}/p/1')]
        self.task.save()
        task = self.step(self.task)
        prepare.assert_not_called()

    def test_after_an_order_no_ending_says_buy_it_yourself_and_a_cancel_says_an_order_may_exist(self):
        task = self.make_task(phase='ordered', checkout_at=timezone.now())
        self.operate.return_value = ('give_up', {'reason': 'cannot_do'})
        self.step(task, checkout_page())
        self.assertIn('Puede que el pedido haya quedado hecho', self.post.call_args.args[1])
        self.assertNotIn('Puedes comprar tú', self.post.call_args.args[1])
        other, account = self.person()
        placed = self.make_task(user=other, account=account, state='needs_person', phase='ordered',
                                checkout_at=timezone.now(), wait_until=timezone.now() + timedelta(minutes=5))
        service.cancel(account, other, placed.internal_id)
        self.assertIn('Puede que el pedido haya quedado hecho', self.post.call_args.args[1])

    def test_an_approval_needs_an_order_and_its_turn(self):
        task = self.make_task(state='needs_person', reason='approve', wait_until=timezone.now() + timedelta(minutes=5))
        with self.assertRaises(service.TaskRefused):
            service.approve(self.account, self.user, task.internal_id)   # no order named
