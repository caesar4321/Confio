"""A payment with a typed amount is asked by code first (assistant/sends.py)."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from assistant import engine, sends
from payment_accounts import intent_rails, payment_intents

CODE = '00020126580014br.gov.bcb.pix0136123e4567-e12b-12d3-a456-426655440000520400005303986540550.005802BR6304ABCD'


class TypedAmountIsAskedTests(SimpleTestCase):
    def belt(self, *texts):
        viewer = SimpleNamespace(account=object(), user=object(), request_meta={}, account_type='personal')
        return SimpleNamespace(result=engine.TurnResult(reply=''), payment_texts=list(texts), viewer=viewer,
                               turn_history=())

    def propose(self, belt, code=None, refused=None, **args):
        with mock.patch.object(payment_intents, 'prepare', return_value='card', side_effect=refused) as prepare, \
                mock.patch.object(payment_intents, '_track'), \
                mock.patch.object(payment_intents, 'word_rails', return_value=set(payment_intents.WORD_RAILS)), \
                mock.patch.object(payment_intents, 'code_in_words', return_value=code):
            args = {'rail': None, 'recipient': None, 'amount_usd': None, **args}
            try:
                return sends.propose(belt, **args), prepare
            except payment_intents.IntentRefused as exc:
                return exc.code, prepare

    def test_a_typed_send_is_a_question_and_prepares_nothing(self):
        for texts in (('envía 20 dólares a @ana',), ('20', 'quiero enviarle a @ana'),
                      ('20', 'a @ana', 'quiero enviar dinero')):
            belt = self.belt(*texts)
            out, prepare = self.propose(belt, rail=intent_rails.CONFIO_SEND, recipient='@ana', amount_usd=20)
            self.assertTrue(out['ok'], texts)
            prepare.assert_not_called()
            self.assertIn('US$20 (dólares) a @ana', belt.result.pending_action['question'])

    def test_another_currency_is_never_asked_as_dollars(self):
        for said in ('envía 500 a @ana en bolívares', 'envía 500 bolos a @ana', 'envía 500 a @ana, en pesos'):
            belt = self.belt(said)
            out, prepare = self.propose(belt, rail=intent_rails.CONFIO_SEND, recipient='@ana', amount_usd=500)
            self.assertEqual(out, 'not_said', said)
            self.assertIsNone(belt.result.pending_action)
            prepare.assert_not_called()

    def test_a_code_sent_to_be_paid_is_a_card_at_once_with_the_codes_amount(self):
        for latest in (CODE, f'paga {CODE}', f'paga esto por favor {CODE}', f'{CODE} pague esse pix'):
            with mock.patch.object(sends, '_has_amount', return_value=True):
                out, prepare = self.propose(self.belt(latest), code=CODE, amount_usd=500)
            self.assertEqual(out, 'card', latest)
            self.assertIsNone(prepare.call_args.kwargs['request']['amount_usd'])

    def test_a_code_talked_about_is_asked_never_prepared(self):
        for texts in ((f"don't pay this {CODE}",), (f'cancela {CODE}',), (f'ya lo pagué {CODE}',),
                      (f'¿qué es esto? {CODE}',), (f'{CODE} no lo pagues, es estafa',), (f'paga {CODE} ❌',),
                      (f'paga o boleto no valor de 550 {CODE}',), ('sí', CODE), ('paga esto', CODE),
                      ('¿me lo pagas?', CODE), ('mejor envía 20 a @ana', CODE), ('20', CODE)):
            belt = self.belt(*texts)
            with mock.patch.object(sends, '_has_amount', return_value=True):
                out, prepare = self.propose(belt, code=CODE, amount_usd=20)
            self.assertTrue(out['ok'], texts)
            prepare.assert_not_called()
            self.assertIn('•••ABCD', belt.result.pending_action['question'])
            self.assertIsNone(belt.result.pending_action['data']['request']['amount_usd'])
        for latest in ('no', 'no, cancela', 'cancela'):
            with mock.patch.object(sends, '_has_amount', return_value=True):
                out, prepare = self.propose(self.belt(latest, CODE), code=CODE)
            self.assertEqual(out, 'not_asked', latest)
        out, prepare = self.propose(self.belt('mejor a @ana', CODE), code=CODE, recipient='@ana')
        self.assertEqual(out, 'not_said')

    def test_an_open_code_is_asked_with_the_amount_they_wrote(self):
        for said, amount, shown in (('20', 20, 'US$20'), ('1.000', 1000, 'US$1000'), ('20 usdt', 20, 'US$20'),
                                    ('unos 20 dólares', 20, 'US$20'), ('son 20', 20, 'US$20')):
            belt = self.belt(said, CODE)
            with mock.patch.object(sends, '_has_amount', return_value=False):
                out, prepare = self.propose(belt, code=CODE, amount_usd=amount)
            self.assertTrue(out['ok'], said)
            prepare.assert_not_called()
            self.assertIn(f'{shown} (dólares) con el código', belt.result.pending_action['question'])
        with mock.patch.object(sends, '_has_amount', return_value=False):
            self.assertEqual(self.propose(self.belt(CODE), code=CODE)[0], 'no_amount')

    def test_a_code_that_already_got_its_card_is_not_asked_again(self):
        from datetime import timedelta

        from django.utils import timezone

        from assistant import confirm
        belt, now = self.belt('paga 20 dólares de luz'), timezone.now()
        lines = (('USER', CODE, {}), ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': {'id': 'i'}}),
                 ('USER', 'gracias', {}), ('AGENT', 'De nada.', {'ai': True}), ('USER', 'paga 20 dólares de luz', {}))
        belt.turn_history = [SimpleNamespace(sender_type=who, body=body, metadata=meta,
                                             created_at=now - timedelta(seconds=10 * (len(lines) - at)))
                             for at, (who, body, meta) in enumerate(lines)]
        self.assertNotIn(CODE, confirm.recent_texts(belt, until_card=True))
        self.assertIn(CODE, confirm.recent_texts(belt))

    def test_money_named_in_what_is_no_request_still_counts(self):
        from datetime import timedelta

        from django.utils import timezone
        now = timezone.now()
        for before, metadata in (('¿puedo enviar bolívares a @ana?', {}), ('¿puede ser en bolívares?', {}),
                                 ('envía 500 bolívares a @ana', {'modality': 'VOICE'}),
                                 ('esta factura en bolívares', {'modality': 'PHOTO'}),
                                 ('recibo: total 800 bolívares ' + 'línea ' * 120, {})):
            belt = self.belt('envíale 500 a @ana')
            belt.turn_history = [
                SimpleNamespace(sender_type='USER', body=before, metadata=metadata, created_at=now - timedelta(minutes=1)),
                SimpleNamespace(sender_type='USER', body='envíale 500 a @ana', metadata={}, created_at=now)]
            out, _prepare = self.propose(belt, rail=intent_rails.CONFIO_SEND, recipient='@ana', amount_usd=500)
            self.assertEqual(out, 'not_said', before[:60])
            self.assertIsNone(belt.result.pending_action)

    def test_a_static_codes_amount_is_in_the_question(self):
        found = {'dynamic': False, 'amount': '550.00'}
        with mock.patch('payment_accounts.local_money.pix_code', return_value=found):
            self.assertIn('R$550,00', sends.question({'code': CODE, 'amount_usd': None}, 'es'))

    def test_a_polite_question_is_a_request(self):
        for texts in (('¿puedes enviarle 20 dólares a @ana?',), ('20', '¿me ayudas a enviarle a @ana?')):
            out, _prepare = self.propose(self.belt(*texts), rail=intent_rails.CONFIO_SEND, recipient='@ana', amount_usd=20)
            self.assertTrue(out['ok'], texts)
        for said in ('¿puedes revisar si @ana es estafa? me pide 500 dólares', '¿puedes decirme quién es @ana?'):
            out, _prepare = self.propose(self.belt(said), rail=intent_rails.CONFIO_SEND, recipient='@ana', amount_usd=500)
            self.assertEqual(out, 'not_said', said)
        out, _prepare = self.propose(self.belt('¿cuánto es 500 dólares para @ana?'), rail=intent_rails.CONFIO_SEND,
                                     recipient='@ana', amount_usd=500)
        self.assertEqual(out, 'not_said')

    def test_their_yes_prepares_exactly_what_was_asked(self):
        from decimal import Decimal
        belt = self.belt('sí')
        belt.payments_ready = lambda: True
        data = {'source': 'owner_words', 'request': {'method_id': intent_rails.CONFIO_SEND, 'recipient': 'ana',
                                                     'amount_usd': '20'}}
        with mock.patch.object(payment_intents, 'prepare', return_value=SimpleNamespace(internal_id='i')) as prepare:
            done, _reply, extra = sends.confirmed(belt, data, 'es')
        self.assertTrue(done)
        self.assertEqual(extra['payment_intent'], {'id': 'i'})
        sent = prepare.call_args.kwargs['request']
        self.assertEqual((sent['recipient'], sent['amount_usd']), ('ana', Decimal('20')))
