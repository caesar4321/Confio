"""The chat prepares no payment from a typed amount (assistant.engine.TYPED_AMOUNTS_PAUSED)."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from assistant import engine
from payment_accounts import payment_intents


class TypedAmountPauseTests(SimpleTestCase):
    def call(self, texts, side_effect=None, **args):
        viewer = SimpleNamespace(account=object(), user=object(), request_meta={})
        belt = SimpleNamespace(result=engine.TurnResult(reply=''), paid_used=set(), saw_web=False,
                               payment_texts=texts, viewer=viewer)
        shown = {'payee_name': 'Padaria', 'payee_level': 'self_reported', 'amount_local': '50.00',
                 'currency': 'BRL', 'total_usd': '9.00'}
        with mock.patch.object(payment_intents, 'prepare_from_request', side_effect=side_effect,
                               return_value=SimpleNamespace(internal_id='x', amount_exact=True)) as prepare, \
                mock.patch.object(payment_intents, 'display_fields', return_value=shown):
            return engine.Toolbelt.prepare_payment(belt, **args), prepare, belt.result

    def test_no_rail_takes_a_typed_amount(self):
        for rail in payment_intents.WORD_RAILS:
            out, prepare, result = self.call(['envía 500 a @ana en bolívares'], rail=rail, recipient='@ana', amount_usd=500)
            self.assertEqual((out['ok'], out['_denied'], out['motivo']), (False, True, engine.TYPED_AMOUNT_REFUSAL), rail)
            prepare.assert_not_called()
            self.assertIsNone(result.payment_intent)
            self.assertEqual(result.payment_refusal, engine.TYPED_AMOUNT_REFUSAL)

    def test_a_recipient_beside_an_older_code_pays_nothing(self):
        out, prepare, _result = self.call(['mejor a @ana', '000201'], recipient='@ana', amount_usd=20)
        self.assertFalse(out['ok'])
        prepare.assert_not_called()

    def test_a_code_never_gets_the_models_amount(self):
        out, prepare, _result = self.call(['paga este pix 000201'], amount_usd=500)
        self.assertTrue(out['ok'])
        self.assertIsNone(prepare.call_args.kwargs['amount_usd'])

    def test_a_typed_request_is_never_told_to_paste_a_code(self):
        refused = payment_intents.IntentRefused('no_code', 'Pega el código Pix (copia e cola) completo.')
        out, _prepare, result = self.call(['envía 20 a @ana'], side_effect=refused)
        self.assertEqual((out['motivo'], result.payment_refusal), (engine.TYPED_AMOUNT_REFUSAL,) * 2)
        out, prepare, _result = self.call([], rail='confio_send', recipient='@ana', amount_usd=20)     # spoken
        self.assertEqual(out['motivo'], engine.TYPED_AMOUNT_REFUSAL)
        prepare.assert_not_called()
        out, _prepare, _result = self.call(['paga este pix 000201 cortado'], side_effect=refused)
        self.assertIn('Pega el código', out['motivo'])      # a code was there: its own reason stands

    def test_an_open_code_is_sent_to_pagar(self):
        refused = payment_intents.IntentRefused('no_amount', 'Dime cuántos dólares quieres enviar.')
        out, _prepare, result = self.call(['paga este pix 000201'], side_effect=refused)
        self.assertEqual(out['motivo'], engine.TYPED_AMOUNT_REFUSAL)
        self.assertEqual(result.payment_refusal, engine.TYPED_AMOUNT_REFUSAL)
