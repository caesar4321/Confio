"""Venezuelan store purchases paid by Pago Móvil before the order exists (pagomovil.py)."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from agent_tasks import countries, pagomovil, runner, service
from agent_tasks.models import AgentTask
from agent_tasks.tests.base import element, picture, snap
from agent_tasks.tests.test_runner import StepBase

SITE = 'tienda.com.ve'
URL = f'https://www.{SITE}/checkout'
TEXT = ('Resumen del pedido', 'Harina PAN 1 kg', 'Total Bs. 1.234,56', 'Paga con Pago Móvil', 'Banco: Banesco (0134)',
        'Teléfono: 0414-1234567', 'RIF: J-12345678-9', 'Titular: Tienda Ejemplo CA', 'Monto: Bs. 1.234,56',
        'Número de referencia', 'Entrega: Av. Libertador 10, Caracas')
REFERENCE = '004512345678'


def read_as(amount='Bs. 1.234,56', fields=(('reference', 2, True),), phone='0414-1234567', shown=True):
    return {'shown': shown, 'bank': 'Banesco (0134)', 'phone': phone, 'document': 'J-12345678-9',
            'holder': 'Tienda Ejemplo CA', 'amount': amount, 'why': '',
            'fields': [{'asks': asks, 'ref': ref, 'required': required} for asks, ref, required in fields]}


def page(text=TEXT):
    return snap(' '.join(text), URL, elements=[
        element('Pago Móvil', ref=0, role='radio', tag='div', checked=True),
        element('Confirmar pago', ref=1),
        element('Número de referencia', ref=2, tag='input', type='text'),
        element('Teléfono de quien paga', ref=3, tag='input', type='tel')])


def review(task, seen, element, item, meter):
    return {'places_order': True, 'pays_with': 'asked', 'total': 'Bs. 1.234,56', 'item_shown': True,
            'ship_to': 'Av. Libertador 10, Caracas', 'why': '', 'lines': []}


class ReadTests(SimpleTestCase):
    task = SimpleNamespace(site=SITE, user_id=1)

    def shots(self, first=TEXT, second=None):
        return (picture(url=URL, text=first), picture(url=URL, text=first if second is None else second))

    def read(self, *readings, shots=None):
        with mock.patch('agent_tasks.agent.read_pagomovil', side_effect=list(readings) * (2 // len(readings))):
            return pagomovil.read(self.task, page(), shots or self.shots(), None)

    def test_the_stores_data_is_read_when_every_value_is_written(self):
        details, why = self.read(read_as())
        self.assertEqual(why, '')
        self.assertEqual({key: details[key] for key in ('bank_code', 'phone', 'cedula', 'amount_ves', 'asks')},
                         {'bank_code': '0134', 'phone': '584141234567', 'cedula': 'J123456789',
                          'amount_ves': '1234.56', 'asks': ['reference']})
        self.assertEqual(details['refs'], {'reference': 2})

    def test_a_value_the_page_does_not_write_is_never_taken(self):
        self.assertEqual(self.read(read_as(phone='0414-7654321')), (None, 'code'))
        self.assertEqual(self.read(read_as(amount='Bs. 1.300,00')), (None, 'code'))
        self.assertEqual(self.read(read_as(shown=False)), (None, 'code'))

    def test_two_pictures_must_agree(self):
        changed = tuple('Monto: Bs. 1.300,00' if node.startswith('Monto') else node for node in TEXT) + (
            'Total Bs. 1.300,00',)
        readings = [read_as(), read_as(amount='Bs. 1.300,00')]
        with mock.patch('agent_tasks.agent.read_pagomovil', side_effect=readings):
            self.assertEqual(pagomovil.read(self.task, page(), self.shots(TEXT, changed), None), (None, 'screen'))

    def test_a_bank_is_one_of_ours_alone(self):
        self.assertEqual(pagomovil.bank_code('0105 Mercantil'), '0105')
        self.assertEqual(pagomovil.bank_code('Mercantil'), '0105')
        self.assertEqual(pagomovil.bank_code('Banco'), '')
        self.assertEqual(pagomovil.bank_code('0102 o 0134'), '')

    def test_venezuelan_stores_pay_by_pago_movil_before_the_order(self):
        rail = countries.rail(countries.country_of('farmatodo.com.ve'))
        self.assertEqual((rail.method_id, rail.currency, rail.numeric, rail.pay_before_order),
                         ('ve_pagomovil_send', 'VES', '928', True))
        self.assertFalse(countries.rail('MX').pay_before_order)

    @override_settings(VE_PAGOMOVIL_SEND_ENABLED=True, VE_PAGOMOVIL_SEND_MIN_APP_VERSION='1.0.0',
                       SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS='')
    def test_without_the_purchase_spender_it_is_never_ordered(self):
        from payment_accounts.services import PaymentAccountError
        with self.assertRaises(PaymentAccountError):
            countries.rail('VE').ready(None, None, {'HTTP_X_CONFIO_VERSION': '9.0.0'})
        self.assertEqual(countries.rail('VE').pay_mode(None, None, {}), ('manual', ''))


class VenezuelaBase(StepBase):
    def setUp(self):
        super().setUp()
        self.patch('agent_tasks.agent.review', side_effect=review)
        self.reading_model = self.patch('agent_tasks.agent.read_pagomovil', return_value=read_as())
        self.prepare = self.patch('payment_accounts.payment_intents.prepare')
        self.prepare.return_value = SimpleNamespace(
            currency='VES', amount_exact=True, amount_local=Decimal('1201.00'), minimum_local=Decimal('1234.56'),
            internal_id='i', payee_level='unverified', rail_method_id='ve_pagomovil_send')
        self.pay = self.patch('agent_tasks.account_pay.pay', return_value=True)
        self.alert = self.patch('config.ops_alerts.send_ops_alert')
        self.browser.capture.return_value = (picture(url=URL, text=TEXT), picture(url=URL, text=TEXT))

    def make_ve(self, **over):
        return self.make_task(**{'site': SITE, 'country': 'VE', 'goal': 'harina pan', **over})


class PayFirstTests(VenezuelaBase):
    def approved(self):
        self.operate.return_value = ('ready_to_order', {'ref': 1, 'item': 'Harina PAN 1 kg', 'total': 'Bs. 1.234,56'})
        task = self.step(self.make_ve(phase='ordering'), page())
        self.assertEqual((task.state, task.reason), ('needs_person', 'approve'))
        return service.approve(self.account, self.user, task.internal_id)

    def test_approved_it_is_paid_exactly_and_nothing_is_pressed(self):
        task = self.step(self.approved(), page())
        self.reader.click.assert_not_called()
        self.reader.type.assert_not_called()
        self.assertEqual(task.phase, 'paying')
        self.assertIsNotNone(task.checkout_at)
        self.assertTrue(task.order['pay_first'])
        self.assertIsNone(self.prepare.call_args.args[2])   # no code: the store's data is the request
        request = self.prepare.call_args.kwargs['request']
        self.assertEqual((request['method_id'], request['amount_local'], request['phone'], request['cedula'],
                          request['bank_code']), ('ve_pagomovil_send', '1234.56', '584141234567', 'J123456789', '0134'))
        self.assertNotIn('reference', request)
        self.assertEqual(self.prepare.call_args.kwargs['source'], 'agent_checkout')
        self.pay.assert_called_once()
        self.assertEqual(self.pay.call_args.kwargs['extra']['amount_local'], '1234.56')

    def test_a_store_that_asks_the_payers_data_is_stopped_before_any_money(self):
        self.reading_model.return_value = read_as(fields=(('reference', 2, True), ('payer_phone', 3, True)))
        task = self.step(self.approved(), page())
        self.assertEqual((task.state, task.reason), ('stopped', 'payer_data'))
        self.prepare.assert_not_called()
        self.pay.assert_not_called()
        self.assertIsNone(task.checkout_at)
        self.assertIn('datos de quien paga', self.post.call_args.args[1])
        # The Avísame probe applies to it.
        task = service.answer_notify(self.account, self.user, task.internal_id, True)
        self.assertEqual(task.order['notify'], 'yes')
        from agent_tasks.schema import task_type
        self.assertEqual(task_type(task).notify, 'yes')

    def test_an_optional_payer_field_is_left_empty(self):
        self.reading_model.return_value = read_as(fields=(('reference', 2, True), ('payer_phone', 3, False)))
        self.step(self.approved(), page())
        self.pay.assert_called_once()

    def test_another_amount_than_the_approved_one_is_never_paid(self):
        text = tuple('Monto: Bs. 1.300,00' if node.startswith('Monto') else node for node in TEXT)
        self.browser.capture.return_value = (picture(url=URL, text=text), picture(url=URL, text=text))
        self.reading_model.return_value = read_as(amount='Bs. 1.300,00')
        task = self.step(self.approved(), page())
        self.prepare.assert_not_called()
        self.assertIn('refused', task.history[-1]['result'])

    def test_a_card_for_other_bolivares_is_cancelled(self):
        self.prepare.return_value.minimum_local = Decimal('1234.00')
        with mock.patch('payment_accounts.payment_intents.cancel') as cancel:
            task = self.step(self.approved(), page())
        cancel.assert_called_once()
        self.pay.assert_not_called()
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))

    def test_without_the_account_it_is_never_the_card(self):
        self.pay.return_value = False
        with mock.patch('payment_accounts.payment_intents.cancel') as cancel:
            task = self.step(self.approved(), page())
        cancel.assert_called_once()
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('no salió dinero', self.post.call_args.args[1])


class PaidTests(VenezuelaBase):
    def paying(self):
        return self.make_ve(state='payment_ready', reason='account', phase='paying', checkout_at=timezone.now(),
                            session_id='', connect_url='', order={
                                'pay_first': True, 'amount': '1234.56', 'total': 'Bs. 1.234,56',
                                'item': 'Harina PAN 1 kg', 'address': 'Av. Libertador 10, Caracas',
                                'pagomovil': {'bank_code': '0134', 'phone': '584141234567', 'cedula': 'J123456789',
                                              'amount_ves': '1234.56', 'asks': ['reference']}})

    def test_store_paid_queues_the_report_on_a_fresh_session_once(self):
        task = self.paying()
        self.assertTrue(service.store_paid(task.pk, reference=REFERENCE, paid_ves='1234.56', origin_bank='0156',
                                           paid_at='2026-11-25T14:00:00+00:00'))
        task.refresh_from_db()
        self.assertEqual((task.state, task.phase, task.session_id), ('queued', 'report', ''))
        self.assertEqual(task.order['paid']['reference'], REFERENCE)
        self.kick.assert_called_once()
        self.assertIn(REFERENCE, self.post.call_args.args[1])
        # The webhook and the poll: the same values again change nothing.
        self.assertTrue(service.store_paid(task.pk, reference=REFERENCE, paid_ves='1234.56'))
        self.kick.assert_called_once()
        # A purchase being paid is never set aside by a new one.
        AgentTask.objects.filter(pk=task.pk).update(state='payment_ready', phase='paying')
        with self.assertRaises(service.TaskRefused) as refused:
            service.start(self.account, self.user, goal='otra cosa', site=SITE,
                          meta={'HTTP_X_CONFIO_VERSION': '9.0.0', 'HTTP_X_CONFIO_BROWSER_TASKS': '1'})
        self.assertEqual(refused.exception.code, 'checkout_open')

    def test_the_report_keeps_no_hold_and_a_hand_over_in_it_goes_back_to_the_browser(self):
        task = self.paying()
        AgentTask.objects.filter(pk=task.pk).update(order={**task.order, 'pay_hold': {'code': 'x', 'extra': {}}})
        self.assertTrue(service.store_paid(task.pk, reference=REFERENCE, paid_ves='1234.56'))
        task.refresh_from_db()
        self.assertNotIn('pay_hold', task.order, 'a report is never paid again from a hold')
        # A CAPTCHA solved by the person during the report: back to the browser, never to the payment.
        AgentTask.objects.filter(pk=task.pk).update(state='needs_person', reason='captcha', checkout_at=timezone.now(),
                                                    wait_until=timezone.now() + timedelta(minutes=4))
        task = service.resume(self.account, self.user, task.internal_id)
        self.assertEqual((task.state, task.phase), ('working', 'report'))

    def test_store_unpaid_stops_it_once_with_no_order(self):
        task = self.paying()
        self.assertTrue(service.store_unpaid(task.pk, why='rejected'))
        self.assertTrue(service.store_unpaid(task.pk, why='rejected'))
        task.refresh_from_db()
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertEqual(self.post.call_count, 1)
        self.assertIn('no hice el pedido', self.post.call_args.args[1])


class ReportTests(VenezuelaBase):
    def setUp(self):
        super().setUp()
        self.report = self.patch('agent_tasks.agent.report', return_value=('payment_step', {'ref': 1}))
        self.placed = self.patch('agent_tasks.agent.placed', return_value=(True, ''))

    def reporting(self, **counts):
        return self.make_ve(phase='report', checkout_at=timezone.now(), counts=counts, order={
            'pay_first': True, 'amount': '1234.56', 'total': 'Bs. 1.234,56', 'item': 'Harina PAN 1 kg',
            'address': 'Av. Libertador 10, Caracas',
            'pagomovil': {'bank_code': '0134', 'phone': '584141234567', 'cedula': 'J123456789',
                          'amount_ves': '1234.56', 'asks': ['reference']},
            'paid': {'reference': REFERENCE, 'paid_ves': '1234.56', 'origin_bank': '0156',
                     'paid_at': '2026-11-25T14:00:00+00:00'}})

    def test_code_types_the_reference_presses_once_and_the_order_is_confirmed(self):
        task = self.step(self.reporting(), page())
        self.reader.type.assert_called_once()
        self.assertEqual((self.reader.type.call_args.args[0]['ref'], self.reader.type.call_args.args[1]),
                         (2, REFERENCE))
        self.reader.click.assert_called_once()
        self.assertEqual(self.reader.click.call_args.args[0]['label'], 'Confirmar pago')
        self.assertTrue(task.order['report']['pressed'])
        self.report.return_value = ('order_placed', {})
        task = self.step(task, snap('Pedido recibido. Gracias.', f'https://www.{SITE}/pedido/1'))
        self.assertEqual((task.state, task.reason), ('payment_ready', 'reported'))
        self.reader.click.assert_called_once()
        self.assertIn(REFERENCE, self.post.call_args.args[1])

    def test_another_amount_at_the_store_is_never_reported(self):
        text = tuple('Monto: Bs. 1.300,00' if node.startswith('Monto') else node for node in TEXT)
        self.browser.capture.return_value = (picture(url=URL, text=text), picture(url=URL, text=text))
        self.reading_model.return_value = read_as(amount='Bs. 1.300,00')
        task = self.step(self.reporting(), page())
        self.assertEqual((task.state, task.reason), ('stopped', 'report_failed'))
        self.reader.type.assert_not_called()
        self.reader.click.assert_not_called()
        said = self.post.call_args.args[1]
        for fact in (REFERENCE, 'Bs. 1.234,56', 'Banesco', '584141234567', 'J123456789'):
            self.assertIn(fact, said)
        self.alert.assert_called_once()

    def test_a_failed_session_is_tried_again_then_given_to_the_person(self):
        self.report.return_value = ('give_up', {'reason': 'cannot_do', 'why': ''})
        task = self.step(self.reporting(), page())
        self.assertEqual((task.state, task.session_id, task.counts['report_tries']), ('queued', '', 1))
        self.alert.assert_not_called()
        AgentTask.objects.filter(pk=task.pk).update(session_id='s-2', connect_url='wss://b',
                                                    session_expires_at=timezone.now() + timedelta(minutes=20),
                                                    state='working', counts={'report_tries': 2})
        task = self.step(AgentTask.objects.get(pk=task.pk), page())
        self.assertEqual((task.state, task.reason), ('stopped', 'report_failed'))
        self.assertIn(REFERENCE, self.post.call_args.args[1])
        self.alert.assert_called_once()

    def test_after_the_final_press_it_is_never_submitted_again(self):
        task = self.reporting()
        AgentTask.objects.filter(pk=task.pk).update(order={**task.order, 'report': {'pressed': True}})
        self.report.return_value = ('give_up', {'reason': 'cannot_do', 'why': ''})
        task = self.step(AgentTask.objects.get(pk=task.pk), page())
        self.assertEqual((task.state, task.reason), ('stopped', 'report_failed'))
        self.assertIn('no vi que la tienda lo confirmara', self.post.call_args.args[1])

    def test_a_report_queued_long_after_the_purchase_still_opens_its_browser(self):
        task = self.reporting()
        AgentTask.objects.filter(pk=task.pk).update(state='queued', session_id='', connect_url='',
                                                    session_expires_at=None,
                                                    created_at=timezone.now() - timedelta(hours=2))
        from agent_tasks import browsers
        self.vendor.create_profile.return_value = 'profile-ve'
        self.vendor.open.return_value = browsers.Session('s-3', 'wss://b', timezone.now() + timedelta(minutes=20))
        task = self.step(AgentTask.objects.get(pk=task.pk))
        self.assertEqual((task.state, task.session_id), ('working', 's-3'))
