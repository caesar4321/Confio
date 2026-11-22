"""The server asks, and a "sí" answers only that (assistant/confirm.py), through service.ask."""
import json
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from assistant import confirm, service
from assistant.tests import call_response, text_response
from users.models import Account, User

META = {'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.0'}
WHOLE = '¿Quieres vender toda tu posición en Tesla (TSLA)? Responde sí o no.'


class YesTests(SimpleTestCase):
    SALE = {'kind': 'trade', 'data': {'side': 'sell', 'sell_all': True}}
    BUY = {'kind': 'trade', 'data': {'side': 'buy', 'sell_all': False}}

    def test_yes(self):
        for said in ('Sí', 'si', 'SÍ.', 'sí, por favor', 'sí 👍', 'dale', 'exacto', 'véndela', 'toda', 'sí, toda',
                     'yes', 'yes please', 'all of it', 'sim', 'tudo'):
            self.assertTrue(confirm.is_yes(said, self.SALE), said)

    def test_not_yes(self):
        for said in ('sí, mañana', 'sí, la mitad', 'sí, una parte', 'sí, si sube', 'sí, Apple', 'ok lo pienso',
                     'perfecto, déjalo', 'todo bien', 'todo ok', '¿sí?', 'sí?', 'sí？', 'vende la mitad', 'vende 3',
                     'sí ❌', 'sí👎', 'dale 🚫', 'ok 🤔', 'sí ❓', 'sí ❔', 'nunca vendería', 'gracias', 'no', 'compra', '👍', '', 'si quieres', 'sí, 500', 'vende Apple'):
            self.assertFalse(confirm.is_yes(said, self.SALE), said)
        for said in ('toda', 'véndela', 'vende'):
            self.assertFalse(confirm.is_yes(said, self.BUY), said)


@override_settings(OPENAI_API_KEY='test-key')
class ConfirmFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='ana_confirm', email='confirm@example.com', password='x',
                                             firebase_uid='fb-confirm', first_name='Ana')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}
        for target, value in (('assistant.trades.offered', True), ('assistant.market.listed_asset', ('TSLA', 'Tesla')),
                              ('assistant.trades._held', [{'ticker': 'TSLA'}, {'ticker': 'AAPL'}]),
                              ('cusd_plus.gm_api.all_market', []), ('assistant.first_use.due', False),
                              ('assistant.service.send_support_staff_push', None)):
            patched = mock.patch(target, return_value=value)
            patched.start()
            self.addCleanup(patched.stop)

    def say(self, body, *responses):
        with mock.patch('assistant.engine._openai_post', side_effect=list(responses)) as model:
            outcome = service.ask(self.user, self.account, None, self.jwt, body, request_meta=META)
        return outcome.reply_message, model

    def asked(self, body='quiero vender mi acción de Tesla', **args):
        args = {'side': 'sell', 'asset': 'Tesla', 'amount_usd': None, 'sell_all': True, **args}
        reply, _model = self.say(body, call_response('propose_stock_trade', json.dumps(args)),
                                 text_response('Te dejé la tarjeta. ¿O prefieres esperar a mañana?'))
        return reply

    def cards(self, reply):
        return [a for a in (reply.metadata.get('actions') or []) if a.get('type') == 'trade']

    def test_the_question_is_code_and_the_whole_reply(self):
        reply = self.asked()
        self.assertEqual(reply.body, WHOLE)
        self.assertEqual(reply.metadata['actions'], [])

    def test_yes_leaves_exactly_that_card_without_the_model(self):
        self.asked()
        reply, model = self.say('Sí')
        model.assert_not_called()
        self.assertEqual([(c['ticker'], c['target']) for c in self.cards(reply)], [('TSLA', 'sell:all')])

    def test_an_amount_is_exactly_the_one_asked(self):
        reply = self.asked('vende 3 dólares de Tesla', amount_usd=3, sell_all=False)
        self.assertIn('US$3 (dólares) de Tesla (TSLA)', reply.body)
        reply, _model = self.say('sí')
        self.assertEqual(self.cards(reply)[0]['target'], 'sell:3.00')

    def test_no_is_answered_by_code(self):
        self.asked()
        reply, model = self.say('no, gracias')
        model.assert_not_called()
        self.assertEqual((reply.body, reply.metadata['actions']), ('Listo, no preparé nada.', []))

    def test_anything_else_is_the_models_and_uses_the_question_up(self):
        for said in ('sí, mañana', 'mejor la mitad', '¿cuánto me darían?', 'vende la mitad'):
            self.asked()
            reply, model = self.say(said, text_response('Claro.'))
            model.assert_called()
            self.assertEqual(self.cards(reply), [], said)
            reply, model = self.say('sí', text_response('¿Sí a qué?'))
            model.assert_called()
            self.assertEqual(self.cards(reply), [], said)

    def test_one_yes_one_card(self):
        self.asked()
        self.say('sí')
        reply, _model = self.say('sí', text_response('Ya está la tarjeta arriba.'))
        self.assertEqual(self.cards(reply), [])

    def test_a_message_in_between_ends_it(self):
        question = self.asked()
        service._append(question.conversation, sender_type='AGENT', body='Un aviso.', metadata={'ai': True})
        reply, _model = self.say('sí', text_response('¿Sí a qué?'))
        self.assertEqual(self.cards(reply), [])

    def test_only_the_same_person_account_and_a_typed_message(self):
        from types import SimpleNamespace
        pending = {'kind': 'trade', 'user_id': 1, 'account_id': 2, 'reply_id': 3,
                   'data': {'side': 'sell', 'sell_all': True}}
        for user, account, metadata in ((9, 2, {}), (1, 9, {}), (1, 2, {'modality': 'VOICE'}),
                                        (1, 2, {'client_reported': True})):
            viewer = SimpleNamespace(user=SimpleNamespace(pk=user), account=SimpleNamespace(id=account))
            message = SimpleNamespace(metadata=metadata)
            self.assertIsNone(confirm.answer(None, viewer, 'sí', pending, message))

    def test_the_models_own_question_confirms_nothing(self):
        self.say('quiero vender Tesla', text_response('¿Quieres vender toda tu posición en Tesla (TSLA)?'))
        reply, model = self.say('sí', text_response('Claro.'))
        model.assert_called()
        self.assertEqual(self.cards(reply), [])

    def test_the_question_survives_a_model_with_no_words_or_no_answer(self):
        from assistant.engine import AssistantUnavailable
        args = json.dumps({'side': 'sell', 'asset': 'Tesla', 'amount_usd': None, 'sell_all': True})
        for after in (text_response(''), AssistantUnavailable('down')):
            cache.clear()
            reply, _model = self.say('quiero vender Tesla', call_response('propose_stock_trade', args), after)
            self.assertEqual(reply.body, WHOLE)
            reply, _model = self.say('sí')
            self.assertEqual(self.cards(reply)[0]['target'], 'sell:all')

    def test_writing_again_while_it_is_prepared_means_no_card(self):
        question = self.asked()
        from assistant import trades
        real = trades.confirmed

        def slow(*args, **kwargs):
            service._append(question.conversation, sender_type='USER', sender_user=self.user, body='no, cancela',
                            metadata={'modality': 'TEXT'})
            return real(*args, **kwargs)
        with mock.patch('assistant.trades.confirmed', side_effect=slow):
            reply, _model = self.say('sí')
        self.assertEqual(self.cards(reply), [])
        self.assertIn('escribiste algo después', reply.body)

    def test_the_same_yes_sent_twice_keeps_the_card(self):
        question = self.asked()
        from assistant import trades
        real = trades.confirmed

        def slow(*args, **kwargs):
            service._append(question.conversation, sender_type='USER', sender_user=self.user, body='sí',
                            metadata={'modality': 'TEXT'})
            return real(*args, **kwargs)
        with mock.patch('assistant.trades.confirmed', side_effect=slow):
            reply, _model = self.say('sí')
        self.assertEqual(self.cards(reply)[0]['target'], 'sell:all')

    def test_money_named_in_a_question_reaches_the_amount(self):
        self.say('¿puedo comprar Tesla con pesos?', text_response('La compra es en dólares.'))
        args = json.dumps({'side': 'buy', 'asset': 'Tesla', 'amount_usd': 50000, 'sell_all': False})
        with mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True):
            reply, _model = self.say('compra 50000 de Tesla', call_response('propose_stock_trade', args),
                                     text_response('¿Cuántos dólares?'))
        self.assertEqual(reply.body, '¿Cuántos dólares?')
        self.assertEqual(self.cards(reply), [])

    def test_forget_everything_is_no_yes(self):
        self.asked()
        with mock.patch('assistant.memory.screen_on', return_value=True), \
                mock.patch('assistant.memory.saw'), \
                mock.patch('assistant.memory.asks_to_forget', return_value=True), \
                mock.patch('assistant.memory.forget_unanswered'), \
                mock.patch('assistant.memory.handle_message', return_value=None), \
                mock.patch('assistant.memory.schedule_summary'), \
                mock.patch('assistant.context.load', return_value=None):
            reply, _model = self.say('sí', text_response('Listo.'))
        self.assertEqual(self.cards(reply), [])

    def test_a_trade_is_proposed_only_by_a_pass_without_stored_data(self):
        from assistant import context
        for tool in ('propose_stock_trade', 'prepare_payment'):
            self.assertNotIn(tool, context.SAFE_WITH_CONTEXT)

    def test_a_payment_from_question_to_card(self):
        from types import SimpleNamespace
        request = {'method_id': 'confio_send', 'recipient': 'ana', 'amount_usd': 20}
        with mock.patch('assistant.engine.Toolbelt.payments_ready', return_value=True), \
                mock.patch('payment_accounts.payment_intents.request_from_words',
                           return_value=(request, 'owner_words')):
            args = json.dumps({'rail': 'confio_send', 'recipient': '@ana', 'amount_usd': 20})
            reply, _model = self.say('envía 20 dólares a @ana', call_response('prepare_payment', args),
                                     text_response('Listo.'))
            self.assertIn('US$20 (dólares) a @ana', reply.body)
            with mock.patch('payment_accounts.payment_intents.prepare',
                            return_value=SimpleNamespace(internal_id='intent-1')) as prepare, \
                    mock.patch('payment_accounts.payment_intents.attach_message') as attach:
                reply, model = self.say('sí')
        model.assert_not_called()
        self.assertEqual(prepare.call_args.kwargs['request']['recipient'], 'ana')
        self.assertEqual(reply.metadata['payment_intent'], {'id': 'intent-1'})
        attach.assert_called_once()

    def test_the_store_lasts_fifteen_minutes(self):
        self.asked()
        with mock.patch.object(confirm.cache, 'set') as stored:
            self.asked()
        self.assertEqual(stored.call_args.args[2], timedelta(minutes=15).total_seconds())
