"""A payment prepared in the chat that the dollars held do not cover: the answer
says what is missing and, where the person tops up from the chat, leaves the
top-up form under it. The card stays; nothing is refused."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from assistant.engine import PAYMENT_CHIP, Toolbelt


def belt(actions=None):
    fake = SimpleNamespace(viewer=SimpleNamespace(account=object()),
                           result=SimpleNamespace(actions=[dict(PAYMENT_CHIP)] if actions is None else list(actions)))
    fake._topup_form = lambda: Toolbelt._topup_form(fake)
    return fake


INTENT = SimpleNamespace(total_usd=Decimal('30.00'))


class PaymentShortfallTests(SimpleTestCase):
    def run_with(self, held, offered=True, forms=('topup',), actions=None):
        fake = belt(actions)
        with mock.patch('payment_accounts.shortfall.dollars_held', return_value=held), \
                mock.patch('assistant.topup_limits.offered', return_value=offered), \
                mock.patch('assistant.here.forms_for', return_value=list(forms)):
            out = Toolbelt._payment_shortfall(fake, INTENT)
        return out, fake.result.actions

    def test_says_what_is_missing_and_leaves_the_form(self):
        out, actions = self.run_with(Decimal('12.5'))
        self.assertEqual(out['te_faltan_usd'], 'US$17.50')
        self.assertIn('US$17.50', out['nota_saldo'])
        self.assertIn('formulario de recarga', out['nota_saldo'])
        self.assertEqual(actions, [dict(PAYMENT_CHIP), {'type': 'form', 'target': 'topup', 'why': 'shortfall', 'label': 'Recargar'}])

    def test_no_form_where_the_chat_does_not_top_up(self):
        for kwargs in ({'offered': False}, {'forms': ()}, {'actions': [dict(PAYMENT_CHIP), {'type': 'form',
                                                                                         'target': 'x'}]}):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                out, actions = self.run_with(Decimal('1'), **kwargs)
                self.assertEqual(out['te_faltan_usd'], 'US$29.00')
                self.assertIn('respuestas aprobadas', out['nota_saldo'])
                self.assertEqual(sum(a.get('target') == 'topup' for a in actions), 0)

    def test_nothing_said_when_enough_or_unknown(self):
        for held in (Decimal('30'), Decimal('100'), None):
            with self.subTest(held=held):
                out, actions = self.run_with(held)
                self.assertEqual(out, {})
                self.assertEqual(actions, [dict(PAYMENT_CHIP)])


class ConfirmedPaymentShortfallTests(SimpleTestCase):
    """The usual path: the person said yes and the card is made then (sends.confirmed)."""

    def run_with(self, held, offered=True, lang='es'):
        from assistant import sends
        actions = [dict(PAYMENT_CHIP)]
        fake = belt(actions)
        with mock.patch('payment_accounts.shortfall.dollars_held', return_value=held), \
                mock.patch('assistant.topup_limits.offered', return_value=offered), \
                mock.patch('assistant.here.forms_for', return_value=['topup']):
            note = sends._short_note(fake, INTENT, lang, actions)
        return note, actions

    def test_the_reply_says_what_is_missing_and_the_form_is_beside_the_card(self):
        note, actions = self.run_with(Decimal('20'))
        self.assertEqual(note, ' Tu saldo en dólares no alcanza: te faltan US$10.00. Recarga con el formulario de abajo '
                               'y después confirma.')
        self.assertEqual(actions[-1], {'type': 'form', 'target': 'topup', 'why': 'shortfall', 'label': 'Recargar'})
        note, actions = self.run_with(Decimal('20'), offered=False)
        self.assertEqual(note, ' Tu saldo en dólares no alcanza: te faltan US$10.00. Recarga antes de confirmar.')
        self.assertEqual(actions, [dict(PAYMENT_CHIP)])
        self.assertIn('US$10.00', self.run_with(Decimal('20'), lang='pt')[0])

    def test_nothing_when_enough_or_unknown(self):
        for held in (Decimal('30'), None):
            self.assertEqual(self.run_with(held), ('', [dict(PAYMENT_CHIP)]))


class ReplyFilterTests(SimpleTestCase):
    def test_beside_a_card_only_the_card_and_the_shortfall_form_stand(self):
        from assistant.service import card_actions
        form = {'type': 'form', 'target': 'topup', 'why': 'shortfall', 'label': 'Recargar'}
        actions = [dict(PAYMENT_CHIP), form, {'type': 'form', 'target': 'topup', 'label': 'Recargar'},
                   {'type': 'navigate', 'target': 'home'}, {'type': 'form', 'target': 'ramp_address'}]
        # A top-up form the model left on its own (nothing short) does not stand beside the card.
        self.assertEqual(card_actions(actions), [dict(PAYMENT_CHIP), form])


class ShortRefusalTests(SimpleTestCase):
    """prepare refuses too few dollars re-raised under its own code (IntentRefused): still seen as short."""

    def refusal(self):
        from payment_accounts.payment_intents import IntentRefused
        from payment_accounts.shortfall import short_of_dollars
        with mock.patch('payment_accounts.shortfall.dollars_held', return_value=Decimal('2')):
            short = short_of_dollars(object(), Decimal('5'))
        try:
            try:
                raise short
            except Exception as exc:
                raise IntentRefused('rail', str(exc)) from exc
        except IntentRefused as wrapped:
            return wrapped

    def test_the_chat_leaves_the_form_under_the_refusal(self):
        fake = belt([])
        with mock.patch('assistant.topup_limits.offered', return_value=True), \
                mock.patch('assistant.here.forms_for', return_value=['topup']):
            out = Toolbelt._short_refusal(fake, self.refusal(), {'ok': False, 'motivo': 'x'})
        self.assertIn('formulario de recarga', out['nota'])
        self.assertEqual(fake.result.actions, [{'type': 'form', 'target': 'topup', 'why': 'shortfall', 'label': 'Recargar'}])

    def test_the_yes_path_leaves_the_form_under_the_refusal(self):
        from assistant import sends
        fake = belt([])
        fake.payments_ready = lambda: True
        fake.viewer.user, fake.viewer.request_meta = object(), {}
        with mock.patch('payment_accounts.payment_intents.prepare', side_effect=self.refusal()), \
                mock.patch('assistant.topup_limits.offered', return_value=True), \
                mock.patch('assistant.here.forms_for', return_value=['topup']):
            done, text, extra = sends.confirmed(fake, {'request': {'amount_usd': '5'}, 'source': 'assistant'}, 'es')
        self.assertFalse(done)
        self.assertTrue(text.startswith('No tienes saldo suficiente para este pago: te faltan US$3.00'), text)
        self.assertEqual(extra, {'actions': [{'type': 'form', 'target': 'topup', 'why': 'shortfall', 'label': 'Recargar'}]})


class NoFigureTests(SimpleTestCase):
    def test_the_model_is_asked_for_a_figure_only_when_there_is_one(self):
        from payment_accounts.shortfall import short_of_dollars
        for held, wanted in ((Decimal('2'), 'cifra del motivo tal cual'), (None, 'sin dar ninguna cifra')):
            with mock.patch('payment_accounts.shortfall.dollars_held', return_value=held):
                exc = short_of_dollars(object(), Decimal('5'))
            fake = belt([])
            with mock.patch('assistant.topup_limits.offered', return_value=True), \
                    mock.patch('assistant.here.forms_for', return_value=['topup']):
                out = Toolbelt._short_refusal(fake, exc, {'ok': False, 'motivo': str(exc)})
            self.assertIn(wanted, out['nota'])
