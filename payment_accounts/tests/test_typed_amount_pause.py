"""A payment from the chat is asked by code first, and how many dollars is always asked (assistant/sends.py)."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from assistant import confirm, engine, sends
from payment_accounts import intent_rails, payment_intents

CODE = '00020126580014br.gov.bcb.pix0136123e4567-e12b-12d3-a456-426655440000520400005303986540550.005802BR6304ABCD'


class _Card(str):
    """A prepared card, as the tests see it ('card'); code may note on it which code it served."""


class _Helpers(SimpleTestCase):
    def belt(self, *texts):
        viewer = SimpleNamespace(account=object(), user=object(), request_meta={}, account_type='personal')
        return SimpleNamespace(result=engine.TurnResult(reply=''), payment_texts=list(texts), viewer=viewer,
                               turn_history=())

    def propose(self, belt, code=None, refused=None, **args):
        with mock.patch.object(payment_intents, 'prepare', return_value=_Card('card'), side_effect=refused) as prepare, \
                mock.patch.object(payment_intents, '_track'), \
                mock.patch.object(payment_intents, 'word_rails', return_value=set(payment_intents.WORD_RAILS)), \
                mock.patch.object(payment_intents, 'code_in_words', return_value=code):
            # Whatever amount the model had in mind, propose never takes one: code asks.
            args.pop('amount_usd', None)
            args = {'rail': None, 'recipient': None, **args}
            try:
                return sends.propose(belt, **args), prepare
            except payment_intents.IntentRefused as exc:
                return exc.code, prepare


class TypedAmountIsAskedTests(_Helpers):
    def test_a_typed_send_is_a_question_and_prepares_nothing(self):
        for texts in (('envía 20 dólares a @ana',), ('20 dólares', 'quiero enviarle a @ana'),
                      ('20 dólares', 'a @ana', 'quiero enviar dinero')):
            belt = self.belt(*texts)
            out, prepare = self.propose(belt, rail=intent_rails.CONFIO_SEND, recipient='@ana', amount_usd=20)
            self.assertTrue(out['ok'], texts)
            prepare.assert_not_called()
            self.assertEqual(belt.result.pending_action['question'],
                             '¿Cuántos dólares quieres enviar a @ana? Escribe solo el número.')
            self.assertEqual(belt.result.pending_action['step'], 'amount')
            self.assertIsNone(belt.result.pending_action['data']['request']['amount_usd'])

    def test_how_much_is_never_read_from_their_words(self):
        for said in ('envía 500 a @ana en bolívares', 'envía Bs 500 en dólares a @ana', 'envía 500 dólares a @ana',
                     'envía 20 dólares a @ana, no, bolívares'):
            belt = self.belt(said)
            out, prepare = self.propose(belt, rail=intent_rails.CONFIO_SEND, recipient='@ana', amount_usd=500)
            self.assertTrue(out['ok'], said)
            prepare.assert_not_called()
            self.assertNotIn('500', belt.result.pending_action['question'], said)
            self.assertIsNone(belt.result.pending_action['data']['request']['amount_usd'])

    def test_a_code_sent_to_be_paid_is_a_card_at_once_with_the_codes_amount(self):
        for latest in (CODE, f'paga {CODE}', f'paga esto por favor {CODE}', f'{CODE} pague esse pix'):
            card = SimpleNamespace()
            with mock.patch.object(sends, '_has_amount', return_value=True), \
                    mock.patch.object(payment_intents, 'prepare', return_value=card) as prepare, \
                    mock.patch.object(payment_intents, '_track'), \
                    mock.patch.object(payment_intents, 'word_rails', return_value=set(payment_intents.WORD_RAILS)), \
                    mock.patch.object(payment_intents, 'code_in_words', return_value=CODE):
                out = sends.propose(self.belt(latest), rail=None, recipient=None)
            self.assertIs(out, card, latest)
            self.assertIsNone(prepare.call_args.kwargs['request']['amount_usd'])
            self.assertEqual(out.code_tag, sends.code_tag(CODE))      # the card says which code it served

    def test_a_code_declined_before_it_was_pasted_is_not_paid_at_once(self):
        from datetime import timedelta

        from django.utils import timezone
        now = timezone.now()
        for before in ('creo que es estafa, no lo pagues', 'no lo pagues'):
            belt = self.belt(CODE, before)
            belt.turn_history = [SimpleNamespace(sender_type='USER', body=before, metadata={'modality': 'VOICE'},
                                                 created_at=now - timedelta(seconds=20)),
                                 SimpleNamespace(sender_type='USER', body=CODE, metadata={}, created_at=now)]
            with mock.patch.object(sends, '_has_amount', return_value=True):
                out, prepare = self.propose(belt, code=CODE)
            self.assertEqual(out, 'declined', before)
            prepare.assert_not_called()

    def test_a_code_talked_about_is_asked_never_prepared(self):
        for texts in ((f'cancela {CODE}',), (f'¿qué es esto? {CODE}',), (f'paga {CODE} ❌',),
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
            self.assertEqual(out, 'declined', latest)
        # Said not to be paid, beside it or before it: not even asked.
        for texts in ((f"don't pay this {CODE}",), (f'ya lo pagué {CODE}',), (f'{CODE} no lo pagues, es estafa',),
                      ('es una estafa?', CODE), ('creo que es estafa', 'paga', CODE), (CODE, 'ya pagué este'),
                      (CODE, 'ya está pagado'), (CODE, 'esto ya se pagó'), (CODE, 'ya lo pagamos'),
                      (CODE, 'no quiero pagar este'), (CODE, 'no lo voy a pagar'), (CODE, 'no hay que pagarlo'),
                      (CODE, 'I already paid'), (CODE, 'já paguei'), (CODE, 'é golpe?')):
            belt = self.belt(*texts)
            with mock.patch.object(sends, '_has_amount', return_value=True):
                out, prepare = self.propose(belt, code=CODE, amount_usd=20)
            self.assertEqual(out, 'declined', texts)
            self.assertIsNone(belt.result.pending_action)
            prepare.assert_not_called()
        out, prepare = self.propose(self.belt('mejor a @ana', CODE), code=CODE, recipient='@ana')
        self.assertEqual(out, 'not_said')

    def test_an_open_code_is_asked_how_many_dollars(self):
        for texts in (('20 dólares', CODE), (CODE,), (f'paga {CODE}',)):
            belt = self.belt(*texts)
            with mock.patch.object(sends, '_has_amount', return_value=False):
                out, prepare = self.propose(belt, code=CODE, amount_usd=20)
            self.assertTrue(out['ok'], texts)
            prepare.assert_not_called()
            self.assertEqual(belt.result.pending_action['question'],
                             '¿Cuántos dólares quieres pagar con el código •••ABCD? Escribe solo el número.')
            self.assertIsNone(belt.result.pending_action['data']['request']['amount_usd'])

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
        self.assertNotIn(CODE, confirm.recent_texts(belt))
        self.assertIn(CODE, confirm.recent_texts(belt, until_card=False))
        # A card that does not say its code (made before cards said it) ends what the code path reads.
        self.assertNotIn(CODE, confirm.recent_texts(belt, until_card='untagged'))
        tagged = list(belt.turn_history)
        tagged[1] = SimpleNamespace(sender_type='AGENT', body='Preparé el pago.', created_at=tagged[1].created_at,
                                    metadata={'ai': True, 'payment_intent': {'id': 'i', 'code': sends.code_tag(CODE)}})
        belt.turn_history = tagged
        self.assertIn(CODE, confirm.recent_texts(belt, until_card='untagged'))
        self.assertEqual(confirm.served_codes(belt), {sends.code_tag(CODE)})

    def test_a_code_carded_at_once_is_never_asked_again(self):
        from datetime import timedelta

        from django.utils import timezone

        from assistant import confirm
        belt, now = self.belt('págalo'), timezone.now()
        for card in ({'id': 'i', 'code': sends.code_tag(CODE)}, {'id': 'i'}):
            lines = (('USER', CODE, {}), ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': card}),
                     ('USER', 'págalo', {}))
            belt.turn_history = [SimpleNamespace(sender_type=who, body=body, metadata=meta,
                                                 created_at=now - timedelta(seconds=10 * (len(lines) - at)))
                                 for at, (who, body, meta) in enumerate(lines)]
            served = confirm.served_codes(belt)
            with mock.patch.object(payment_intents, 'find_pix_codes', side_effect=lambda t: [CODE] if CODE in t else []):
                texts = [text for text in confirm.recent_texts(belt, until_card='untagged')
                         if not any(sends.code_tag(found) in served for found in payment_intents.find_pix_codes(text))]
            self.assertNotIn(CODE, texts, card)

    def test_money_named_anywhere_is_never_the_amount(self):
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
            # Whatever money was named around it, how many dollars is asked.
            self.assertTrue(out['ok'], before[:60])
            self.assertEqual(belt.result.pending_action['question'],
                             '¿Cuántos dólares quieres enviar a @ana? Escribe solo el número.')

    def test_a_static_codes_amount_is_in_the_question(self):
        found = {'dynamic': False, 'amount': '550.00'}
        with mock.patch('payment_accounts.local_money.pix_code', return_value=found):
            self.assertIn('R$550,00', sends.question({'code': CODE, 'amount_usd': None}, 'es'))

    def test_a_polite_question_is_a_request(self):
        for texts in (('¿puedes enviarle 20 dólares a @ana?',), ('20 dólares', '¿me ayudas a enviarle a @ana?')):
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



class AroundAPastedCodeTests(_Helpers):
    def history(self, belt, *lines):
        from datetime import timedelta

        from django.utils import timezone
        now = timezone.now()
        belt.turn_history = [SimpleNamespace(sender_type=who, body=body, metadata=meta,
                                             created_at=now - timedelta(seconds=10 * (len(lines) - at)))
                             for at, (who, body, meta) in enumerate(lines)]
        return belt

    def codes(self):
        return mock.patch.object(payment_intents, 'find_pix_codes',
                                 side_effect=lambda t: [c for c in (CODE, OTHER) if c in t])

    def test_a_code_with_its_card_pasted_again_is_not_asked_about_an_older_one(self):
        card = {'id': 'i', 'code': sends.code_tag(CODE)}
        for latest in (CODE, f'paga {CODE}'):
            belt = self.history(self.belt(latest), ('USER', f'{OTHER} esto es para el alquiler', {}),
                                ('AGENT', 'Te explico.', {'ai': True}), ('USER', CODE, {}),
                                ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': card}),
                                ('USER', latest, {}))
            real = confirm.served_codes
            with self.codes(), mock.patch.object(sends, '_has_amount', return_value=True), \
                    mock.patch.object(payment_intents, 'prepare') as prepare, \
                    mock.patch.object(confirm, 'served_codes', side_effect=lambda b, open_only=False: real(b)):
                with self.assertRaises(payment_intents.IntentRefused) as refused:
                    sends.propose(belt, rail=None, recipient=None)
            self.assertIn('ya tiene su tarjeta', str(refused.exception))
            self.assertIsNone(belt.result.pending_action)
            prepare.assert_not_called()

    def test_a_code_pasted_alone_gets_its_card_whatever_was_said_before(self):
        # Founder, 2026-11-23: alone in its own message, the code's own amount is the card; signed on the phone.
        for before in ('esto es para el alquiler', 'gracias', 'hola'):
            belt = self.history(self.belt(CODE, before), ('USER', before, {}), ('USER', CODE, {}))
            with mock.patch.object(sends, '_has_amount', return_value=True):
                out, prepare = self.propose(belt, code=CODE)
            self.assertEqual(out, 'card', before)

    def test_a_dont_pay_before_another_card_still_asks_first(self):
        other = {'id': 'b', 'code': sends.code_tag(OTHER)}
        belt = self.history(self.belt(CODE), ('USER', 'mi tío me va a mandar un pix, no lo pagues, es estafa', {}),
                            ('AGENT', 'Entendido.', {'ai': True}), ('USER', OTHER, {}),
                            ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': other}), ('USER', CODE, {}))
        with self.codes(), mock.patch.object(sends, '_has_amount', return_value=True), \
                mock.patch.object(confirm, 'served_codes', side_effect=lambda b, open_only=False: set()):
            out, prepare = self.propose(belt, code=CODE)
        prepare.assert_not_called()
        self.assertTrue(out == 'declined' or belt.result.pending_action, out)

    def test_a_dont_pay_said_a_moment_before_still_asks_first(self):
        belt = self.history(self.belt(CODE), ('USER', 'no pagues el código que te voy a mandar', {}),
                            ('AGENT', 'Entendido.', {'ai': True}), ('USER', CODE, {}))
        with mock.patch.object(sends, '_has_amount', return_value=True):
            out, prepare = self.propose(belt, code=CODE)
        prepare.assert_not_called()
        self.assertTrue(out == 'declined' or belt.result.pending_action, out)

    def test_pasted_again_after_the_refusal_it_gets_its_card(self):
        belt = self.history(self.belt(CODE), ('USER', f'{CODE} es estafa?', {}),
                            ('AGENT', 'No preparo el pago de ese código…', {'ai': True, 'declined': True,
                                                                            'refused_code': sends.code_tag(CODE)}),
                            ('USER', CODE, {}))
        with mock.patch.object(sends, '_has_amount', return_value=True):
            out, prepare = self.propose(belt, code=CODE)
        self.assertEqual(out, 'card')

    def test_old_words_about_another_code_or_scams_refuse_nothing(self):
        card = {'id': 'i', 'code': sends.code_tag(OTHER)}
        for lines in ((('USER', OTHER, {}), ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': card}),
                       ('USER', 'listo, ya lo pagué, gracias', {}), ('AGENT', 'De nada.', {'ai': True}),
                       ('USER', '¿cómo me pagan?', {}), ('AGENT', 'Así.', {'ai': True}), ('USER', CODE, {})),
                      (('USER', '¿cómo sé si un QR es una estafa?', {}), ('AGENT', 'Así.', {'ai': True}),
                       ('USER', 'ok', {}), ('AGENT', 'Listo.', {'ai': True}), ('USER', CODE, {}))):
            belt = self.history(self.belt(CODE), *lines)
            with self.codes(), mock.patch.object(sends, '_has_amount', return_value=True), \
                    mock.patch.object(confirm, 'served_codes', side_effect=lambda b, open_only=False: set()):
                out, prepare = self.propose(belt, code=CODE)
            self.assertNotEqual(out, 'declined', lines[0][1])

    def test_pague_spanish_past_is_never_pay_it(self):
        for latest in (f'pagué este pix {CODE}', f'pagué {CODE}', f'{CODE} pagué', f'ya lo pagué {CODE}'):
            with mock.patch.object(sends, '_has_amount', return_value=True), \
                    mock.patch.object(sends, '_retire_open_cards'):
                out, prepare = self.propose(self.belt(latest), code=CODE)
            self.assertEqual(out, 'declined', latest)
            prepare.assert_not_called()
        # Portuguese "pague" (pay) is still a request.
        with mock.patch.object(sends, '_has_amount', return_value=True):
            out, _prepare = self.propose(self.belt(f'{CODE} pague esse pix'), code=CODE)
        self.assertEqual(out, 'card')

    def test_words_about_an_earlier_codes_card_refuse_nothing_now(self):
        card = {'id': 'i', 'code': sends.code_tag(OTHER)}
        belt = self.history(self.belt(CODE), ('USER', OTHER, {}),
                            ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': card}),
                            ('USER', 'listo ya lo pagué', {}), ('AGENT', '¡Bien!', {'ai': True}), ('USER', CODE, {}))
        with self.codes(), mock.patch.object(sends, '_has_amount', return_value=True), \
                mock.patch.object(sends, '_retire_open_cards') as retire, \
                mock.patch.object(confirm, 'served_codes', side_effect=lambda b, open_only=False: set()):
            out, _prepare = self.propose(belt, code=CODE)
        self.assertNotEqual(out, 'declined')
        retire.assert_not_called()

    def test_no_lo_pagues_beside_a_code_with_an_open_card_withdraws_it(self):
        card = {'id': 'i', 'code': sends.code_tag(CODE)}
        said = f'{CODE} es una estafa, no lo pagues'
        belt = self.history(self.belt(said), ('USER', CODE, {}),
                            ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': card}), ('USER', said, {}))
        with self.codes(), mock.patch.object(sends, '_retire_open_cards') as retire, \
                mock.patch.object(sends, '_has_amount', return_value=True):
            out, prepare = self.propose(belt, code=CODE)
        self.assertEqual(out, 'declined')
        retire.assert_called_once()

    def test_open_cards_that_cannot_be_read_prepare_nothing(self):
        with mock.patch.object(confirm, 'served_codes', side_effect=lambda b, open_only=False: None if open_only
                               else set()), mock.patch.object(sends, '_has_amount', return_value=True):
            with self.assertRaises(payment_intents.IntentRefused) as refused:
                with mock.patch.object(payment_intents, 'code_in_words', return_value=CODE):
                    sends.propose(self.belt(CODE), rail=None, recipient=None)
        self.assertIn('No pude revisar ese código', str(refused.exception))

    def test_a_code_paid_before_can_be_paid_again(self):
        # A shop's printed code: its card was paid (no longer open), and pasted again alone it is a new payment.
        card = {'id': 'i', 'code': sends.code_tag(CODE)}
        belt = self.history(self.belt(CODE), ('USER', CODE, {}),
                            ('AGENT', 'Preparé el pago.', {'ai': True, 'payment_intent': card}), ('USER', CODE, {}))
        real = confirm.served_codes
        with mock.patch.object(confirm, 'served_codes', side_effect=lambda b, open_only=False: set() if open_only
                               else real(b)), mock.patch.object(sends, '_has_amount', return_value=True):
            out, prepare = self.propose(belt, code=CODE)
        self.assertEqual(out, 'card')


OTHER = CODE.replace('ABCD', 'EF12')
