"""Reading a Mexican store's SPEI details off its own checkout page."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone

from agent_tasks import countries, runner, spei
from agent_tasks.models import AgentTask
from agent_tasks.tests.base import picture
from agent_tasks.tests.test_runner import StepBase

CLABE = '646180157000000004'
OTHER = '012180001234567899'   # BBVA, valid check digit
MERCADO_PAGO = ('Tu pedido', 'Botella térmica 750 ml', 'Paga con transferencia SPEI', 'CLABE', '646 180 157 000 000 004',
                'Monto a transferir', '$1,249.00', 'Referencia', '4021775', 'Vence el 25 de noviembre')
EBANX = ('Instrucciones de pago', 'CLABE interbancaria: 646180157000000004', 'Importe a pagar: $ 1,249.00 MXN',
         'Concepto: SHEIN 88231', 'Banco: STP')


class ReadTests(SimpleTestCase):
    def test_a_mercado_pago_ticket(self):
        self.assertEqual(spei.read(MERCADO_PAGO),
                         ({'clabe': CLABE, 'amount': Decimal('1249.00'), 'reference': '4021775'}, ''))

    def test_labels_in_the_same_line(self):
        self.assertEqual(spei.read(EBANX)[0], {'clabe': CLABE, 'amount': Decimal('1249.00'),
                                               'reference': 'SHEIN 88231'})

    def test_whole_pesos(self):
        page = ('CLABE', CLABE, 'Total a pagar', '$1,249', 'Referencia', '77')
        self.assertEqual(spei.read(page)[0]['amount'], Decimal('1249'))

    def test_anything_missing_is_not_guessed(self):
        for drop in ('Monto a transferir', 'Referencia', 'CLABE'):
            with self.subTest(drop=drop):
                page = tuple(node for node in MERCADO_PAGO if node != drop)
                self.assertEqual(spei.read(page), (None, 'code'))
        self.assertEqual(spei.read(('Paga con tarjeta', 'Total', '$10.00')), (None, 'code'))

    def test_two_of_anything_is_never_chosen_between(self):
        cases = {
            'two clabes': MERCADO_PAGO + ('CLABE', OTHER),
            # A seller's title on the order page with a CLABE in it, unlabelled.
            'a clabe in a title': ('Botella ' + OTHER,) + MERCADO_PAGO,
            'two amounts': MERCADO_PAGO + ('Monto a pagar', '$1,250.00'),
            'two references': MERCADO_PAGO + ('Concepto', 'X 99'),
        }
        for name, page in cases.items():
            with self.subTest(name):
                self.assertEqual(spei.read(page), (None, 'several'))
        self.assertEqual(spei.read(None), (None, 'several'))

    def test_an_account_with_a_bad_check_digit_is_no_account(self):
        page = tuple('646180157000000005' if node == '646 180 157 000 000 004' else node for node in MERCADO_PAGO)
        self.assertEqual(spei.read(page), (None, 'several'))

    def test_only_the_first_thing_after_a_label(self):
        page = ('CLABE', 'Copiar', CLABE, 'Monto', '$5.00', 'Referencia', '12')
        self.assertEqual(spei.read(page), (None, 'several'))
        self.assertEqual(spei.read(('CLABE', ':', CLABE, 'Monto', '$5.00', 'Referencia', '12'))[0]['clabe'], CLABE)

    def test_a_reference_carries_a_digit(self):
        page = tuple('Pendiente' if node == '4021775' else node for node in MERCADO_PAGO)
        self.assertEqual(spei.read(page), (None, 'several'))

    def test_round_fourteen(self):
        cases = {
            # Cents drawn apart are never whole pesos.
            'superscript cents': ('CLABE', CLABE, 'Monto a pagar', '$1,249', '50', 'Referencia', '4021775'),
            # The store's own value does not read, a seller's labelled text does: never filled in.
            'unreadable store amount': ('CLABE', CLABE, 'Monto a pagar', 'MXN 1,249.00', 'Referencia', '4021775',
                                        'Importe: $12,490.00'),
            'unreadable store reference': ('CLABE', CLABE, 'Monto a pagar', '$1,249.00', 'Referencia', '#A-4021/5',
                                           'Concepto: 999'),
            # A numeric reference is a field the payout cannot fill.
            'numeric reference': MERCADO_PAGO + ('Referencia numérica', '4021775'),
            # Dollars on the page: a "$" is not surely pesos.
            'dollars': MERCADO_PAGO + ('Equivale a US$ 68.00',),
            # Three values far apart are not one ticket.
            'far apart': ('CLABE', CLABE) + ('texto',) * 20 + ('Monto a pagar', '$1,249.00', 'Referencia', '4021775'),
            # A dash in a reference the payout cannot send.
            'dash': ('CLABE', CLABE, 'Monto a pagar', '$1,249.00', 'Referencia', '4021-775'),
        }
        for name, page in cases.items():
            with self.subTest(name):
                self.assertEqual(spei.read(page), (None, 'several'))
        page = ('CLABE', CLABE, 'Monto a pagar', '$', '1,249.00', 'Referencia', '4021775')
        self.assertEqual(spei.read(page)[0]['amount'], Decimal('1249.00'))
        # A bare "Total" is not the amount to transfer.
        self.assertEqual(spei.read(('CLABE', CLABE, 'Total', '$1,249.00', 'Referencia', '4021775')), (None, 'code'))


class MexicoTests(StepBase):
    def setUp(self):
        super().setUp()
        self.prepare = self.patch('payment_accounts.payment_intents.prepare')
        self.task = self.make_task(state='awaiting_code', checkout_at=timezone.now(), shown_target='tab',
                                   site='mercadolibre.com.mx', country='MX')

    def outcome(self, text, amount='1249.00', level='store_checkout', text_again=None):
        self.prepare.return_value = SimpleNamespace(currency='MXN', amount_exact=True, amount_local=Decimal(amount),
                                                    internal_id='i', payee_level=level, rail_method_id='mx_clabe')
        url = 'https://www.mercadolibre.com.mx/compra/123/pago'
        self.browser.capture.return_value = (picture(url=url, text=text),
                                             picture(url=url, text=text if text_again is None else text_again))
        self.task.state = 'awaiting_code'
        self.task.save()
        with mock.patch.object(runner.Step, 'save', lambda step, **fields: AgentTask.objects.filter(
                pk=step.task.pk).update(**{k: v for k, v in fields.items() if k != 'payment_intent'})), \
                mock.patch('payment_accounts.payment_intents.cancel'), mock.patch('agent_tasks.runner.post_payment'):
            self.step(self.task)
        return self.task.reason if self.task.state == 'needs_person' else 'prepared'

    def test_the_orders_spei_details_become_the_card(self):
        self.assertEqual(self.outcome(MERCADO_PAGO), 'prepared')
        self.assertEqual(self.prepare.call_args.args[2], CLABE)
        request = self.prepare.call_args.kwargs['request']
        self.assertEqual((request['method_id'], request['amount_local'], request['reference']),
                         ('mx_clabe', '1249.00', '4021775'))
        self.assertEqual(self.prepare.call_args.kwargs['source'], 'agent_checkout')

    def test_a_card_for_another_amount_is_refused(self):
        self.assertEqual(self.outcome(MERCADO_PAGO, amount='1249.01'), 'code_refused')

    def test_only_its_own_payee_level(self):
        self.assertEqual(self.outcome(MERCADO_PAGO, level='unverified'), 'unsigned')

    def test_a_page_that_changed_between_the_two_pictures(self):
        changed = tuple('$1,250.00' if node == '$1,249.00' else node for node in MERCADO_PAGO)
        self.assertEqual(self.outcome(MERCADO_PAGO, text_again=changed), 'screen')
        self.prepare.assert_not_called()

    def test_the_store_is_mexican_by_its_address(self):
        self.assertEqual(countries.country_of('mercadolibre.com.mx'), 'MX')
        self.assertEqual(countries.rail('MX').method_id, 'mx_clabe')
