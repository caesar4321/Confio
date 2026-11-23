"""The edges of code's question (assistant/confirm.py): what counts as said, and what happens around a yes."""
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from assistant import confirm, sends, service, trades
from assistant.engine import TurnResult
from assistant.test_confirm import META, FlowBase
from assistant.tests import call_response, text_response
from inbox.models import SupportMessage


class WordsTests(SimpleTestCase):
    SALE = {'kind': 'trade', 'data': {'side': 'sell', 'sell_all': True}}

    def test_invisible_marks_and_typographic_punctuation_are_not_words(self):
        self.assertTrue(confirm.is_yes('s​í', self.SALE))
        self.assertTrue(confirm.is_yes('﻿sí⁠', self.SALE))
        for said in ('“no”', 'no—gracias', '‘no’', 'no – cancela'):
            self.assertTrue(confirm.is_no(said), said)
            self.assertFalse(confirm.is_yes(said, self.SALE), said)

    def test_more_ways_to_say_no(self):
        for said in ('no lo hagas', 'Never mind', 'esquece', 'déjalo así', 'no, olvídalo', 'es una estafa', "don't"):
            self.assertTrue(confirm.is_no(said), said)

    def test_a_number_that_cannot_be_taken_is_asked_again_and_nothing_else_is(self):
        for said in ('1.500', '$20', '20 bolívares', 'unos 20', '20 mil', '1,500 por favor', '20 o 30', '20 y 30'):
            self.assertTrue(confirm._number_shaped(said), said)
        for said in ('¿cuánto es 20 dólares en bolívares?', 'mejor envíale a @maria2', 'tengo 3', 'no, 20 no',
                     'recuerda que mi meta es 500 dólares', 'cancela todo, 2', 'manda 20 o 30', '20 a Ana'):
            self.assertFalse(confirm._number_shaped(said), said)

    def test_portuguese_words_spanish_shares(self):
        for said in ('manda 20 pra @ana', 'vende minha Tesla', 'paga esse pix', 'envia pra ela'):
            self.assertEqual(confirm.language([said]), 'pt', said)
        for said in ('compra Apple', 'vende mi Tesla', 'paga el pix', 'compra 20 dollars de Apple'):
            self.assertEqual(confirm.language([said]), 'es', said)

    def test_the_language_of_the_question(self):
        self.assertEqual(confirm.language(['quero vender minhas ações']), 'pt')
        self.assertEqual(confirm.language(['esqueça isso']), 'pt')
        self.assertEqual(confirm.language(['envíe 20 dólares']), 'es')       # Spanish too: never Portuguese
        self.assertEqual(confirm.language(['compre Apple']), 'es')
        self.assertEqual(confirm.language(['¿qué?']), 'es')
        self.assertEqual(confirm.language(['forget what I said']), 'en')
        self.assertEqual(confirm.language(['ok']), 'es')                       # a tie is Spanish

    def test_something_already_done_in_the_reply_leaves_no_room_for_a_question(self):
        self.assertFalse(confirm.busy(TurnResult(reply='')))
        self.assertTrue(confirm.busy(TurnResult(reply='', writes=['alert_deleted'])))
        # A tool's log line says nothing of what it saved: only result.writes does.
        self.assertFalse(confirm.busy(TurnResult(reply='', tools=[
            {'name': 'propose_target_allocation', 'ok': True, 'args': {'action': 'set'}}])))

    def test_a_no_ends_what_was_asked(self):
        now = timezone.now()
        lines = (('USER', 'vende 20 dólares de Tesla', {}), ('AGENT', 'Listo, no preparé nada.', {'declined': True}),
                 ('USER', 'sí', {}))
        belt = SimpleNamespace(payment_texts=['sí'], turn_history=[
            SimpleNamespace(sender_type=who, body=body, metadata=meta, created_at=now - timedelta(seconds=9 - at))
            for at, (who, body, meta) in enumerate(lines)])
        self.assertEqual(confirm.recent_texts(belt), ['sí'])
        self.assertEqual(confirm.recent_texts(belt, until_card=False), ['sí'])

    def test_a_trade_card_ends_what_was_asked(self):
        now = timezone.now()
        lines = (('USER', 'compra 20 dólares de Apple', {}),
                 ('AGENT', 'Preparé la orden.', {'ai': True, 'actions': [{'type': 'trade', 'ticker': 'AAPL'}]}),
                 ('USER', 'y otra', {}))
        belt = SimpleNamespace(payment_texts=['y otra'], turn_history=[
            SimpleNamespace(sender_type=who, body=body, metadata=meta, created_at=now - timedelta(seconds=9 - at))
            for at, (who, body, meta) in enumerate(lines)])
        self.assertEqual(confirm.recent_texts(belt), ['y otra'])

    def test_a_code_is_known_by_its_tag_only(self):
        tag = sends.code_tag('000201abc')
        self.assertEqual(len(tag), 16)
        self.assertEqual(tag, sends.code_tag('000201abc'))
        self.assertNotIn('000201abc', tag)
        belt = SimpleNamespace(turn_history=[SimpleNamespace(metadata={'payment_intent': {'id': 'i', 'code': tag}}),
                                             SimpleNamespace(metadata={'payment_intent': {'id': 'j'}}),
                                             SimpleNamespace(metadata={})])
        self.assertEqual(confirm.served_codes(belt), {tag})


class NamesAndMoneyTests(SimpleTestCase):
    def test_names_people_use(self):
        # Exact names only: no typo or plural is guessed ("moderno" is not Moderna).
        self.assertFalse(trades._named(['compra nvidea'], 'NVDA', 'NVIDIA Corporation'))
        self.assertFalse(trades._named(['quiero algo moderno'], 'MRNA', 'Moderna, Inc.'))
        self.assertTrue(trades._named(['compra nvidia'], 'NVDA', 'NVIDIA Corporation'))
        self.assertFalse(trades._named(['¿cuál es el costo?'], 'COST', 'Costco Wholesale Corporation'))
        self.assertFalse(trades._named(['ok ko'], 'KO', 'The Coca-Cola Company'))
        self.assertTrue(trades._named(['compra KO'], 'KO', 'The Coca-Cola Company'))
        self.assertTrue(trades._named(['compra coca cola'], 'KO', 'The Coca-Cola Company'))

    def test_money_has_no_thousands_mark(self):
        # "US$1.500" reads as one and a half dollars in Mexico.
        self.assertEqual(trades.money(Decimal('50000')), 'US$50000')
        self.assertEqual(trades.money(Decimal('1234.5')), 'US$1234,50')
        self.assertEqual(trades.money(Decimal('1234.5'), 'en'), 'US$1234.50')
        self.assertEqual(trades.money(Decimal('20')), 'US$20')

    def test_the_number_typed_alone(self):
        for said, value in (('20', '20.00'), ('20.', '20.00'), ('US$20', '20.00'), ('US$ 20', '20.00'),
                            ('usd 20', '20.00'), ('20,5', '20.50'), ('20.50', '20.50'), ('1500', '1500.00'),
                            ('20 dólares', '20.00'), ('20 usd', '20.00'), (' 20 ', '20.00'), ('.50', '0.50'),
                            ('0,5', '0.50'), ('20 por favor', '20.00'), ('20 dólares gracias', '20.00')):
            self.assertEqual(confirm.amount_answer(said), Decimal(value), said)
        for said in ('1.500', '1,500', '20 bolívares', 'unos 20', '¿20?', '20 o 30', '0', '20 👍', 'veinte', '',
                     '20 mil', 'Bs 20', '20%', '$20', '$ 20', '..5', '. 50', '20 pesos por favor'):
            self.assertIsNone(confirm.amount_answer(said), said)


class AroundTheYesTests(FlowBase):
    def test_a_no_is_marked_so_nothing_before_it_is_asked_again(self):
        self.asked()
        reply, _model = self.say('no')
        self.assertTrue(reply.metadata.get('declined'))
        self.assertEqual(self.cards(reply), [])

    def test_a_question_written_while_they_wrote_again_is_not_asked(self):
        args = {'side': 'sell', 'asset': 'Tesla', 'amount_usd': None, 'sell_all': True}
        calls = []

        def model(*_a, **_k):
            calls.append(1)
            if len(calls) == 1:
                conversation = SupportMessage.objects.filter(sender_type='USER').latest('created_at').conversation
                SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                              body='olvídalo')
                return call_response('propose_stock_trade', json.dumps(args))
            return text_response('Te pregunto.')

        with mock.patch('assistant.engine._openai_post', side_effect=model):
            outcome = service.ask(self.user, self.account, None, self.jwt, 'vende mi Tesla',
                                  request_meta={'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.0'})
        self.assertEqual(outcome.reply_message.body, 'Vi tu mensaje nuevo: dime de nuevo qué quieres hacer.')
        self.assertIsNone(confirm.take(outcome.reply_message.conversation))

    def test_a_question_that_cannot_be_kept_is_not_left_in_the_thread(self):
        with mock.patch('assistant.confirm.store', side_effect=RuntimeError('redis down')):
            reply = self.asked()
        self.assertEqual(reply.body, 'No pude dejarte la pregunta ahora. Pídemelo de nuevo en un momento.')
        reply, _model = self.say('sí', text_response('¿Sí a qué?'))
        self.assertEqual(self.cards(reply), [])

    def test_the_team_taking_the_thread_during_a_yes_leaves_no_card(self):
        self.asked()
        real = confirm.answer

        def taken(conversation, *args, **kwargs):
            SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                          body='Hola, te ayudo yo.', metadata={}, sender_user=self.staff())
            return real(conversation, *args, **kwargs)

        with mock.patch('assistant.confirm.answer', side_effect=taken), \
                mock.patch('assistant.engine._openai_post') as model:
            outcome = service.ask(self.user, self.account, None, self.jwt, 'sí',
                                  request_meta={'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.0'})
        model.assert_not_called()
        self.assertIsNone(outcome.reply_message)
        outcome.user_message.refresh_from_db()
        self.assertTrue(outcome.user_message.metadata.get('to_team'))     # the "sí" is theirs to answer
        conversation = outcome.user_message.conversation
        self.assertFalse(any(a.get('type') == 'trade' for m in conversation.messages.all()
                             for a in (m.metadata or {}).get('actions') or []))

    def staff(self):
        from users.models import User
        return User.objects.create_user(username='team_edges', email='team_edges@example.com', password='x',
                                        firebase_uid='fb-team-edges', is_staff=True)

    def test_a_notice_posted_meanwhile_does_not_drop_the_yes(self):
        self.asked()
        real = confirm.answer

        def noticed(conversation, *args, **kwargs):
            SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                          body='Tu alerta se cumplió.', metadata={'notice': 'watch:1',
                                                                                  'system_note': True})
            return real(conversation, *args, **kwargs)

        with mock.patch('assistant.confirm.answer', side_effect=noticed):
            reply, _model = self.say('sí')
        self.assertEqual([(c['ticker'], c['target']) for c in self.cards(reply)], [('TSLA', 'sell:all')])

    def test_a_notice_posted_while_asking_does_not_cancel_the_question(self):
        args = {'side': 'sell', 'asset': 'Tesla', 'amount_usd': None, 'sell_all': True}
        calls = []

        def model(*_a, **_k):
            calls.append(1)
            if len(calls) == 1:
                conversation = SupportMessage.objects.filter(sender_type='USER').latest('created_at').conversation
                SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                              body='Tu alerta se cumplió.', metadata={'notice': 'watch:2'})
                return call_response('propose_stock_trade', json.dumps(args))
            return text_response('Te pregunto.')

        with mock.patch('assistant.engine._openai_post', side_effect=model):
            outcome = service.ask(self.user, self.account, None, self.jwt, 'vende mi Tesla',
                                  request_meta={'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.0'})
        self.assertTrue(outcome.reply_message.body.startswith('¿Quieres vender toda tu posición en Tesla'))

    def test_a_card_is_not_left_when_they_wrote_meanwhile(self):
        from payment_accounts import payment_intents
        calls = []

        def model(*_a, **_k):
            calls.append(1)
            if len(calls) == 1:
                conversation = SupportMessage.objects.filter(sender_type='USER').latest('created_at').conversation
                SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                              body='no lo pagues, es estafa')
                return call_response('prepare_payment', '{}')
            return text_response('Preparé el pago.')

        card = SimpleNamespace(internal_id='intent-1', code_tag='t')
        with mock.patch('assistant.engine._openai_post', side_effect=model), \
                mock.patch('assistant.sends.propose', return_value=card), \
                mock.patch('assistant.engine.Toolbelt.payments_ready', return_value=True, create=True), \
                mock.patch.object(payment_intents, 'attach_message') as attach:
            outcome = service.ask(self.user, self.account, None, self.jwt, 'paga esto',
                                  request_meta={'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.0'})
        attach.assert_not_called()
        self.assertEqual(outcome.reply_message.body, 'Vi tu mensaje nuevo: dime de nuevo qué quieres hacer.')
        self.assertNotIn('payment_intent', outcome.reply_message.metadata)

    def test_a_rules_number_puts_its_proposal_on_the_reply(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        question = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                 body='¿Cuántos dólares de SPY quieres comprar cada mes?',
                                                 metadata={'ai': True})
        viewer = SimpleNamespace(user=self.user, account=self.account)
        pending = {'kind': 'rule', 'step': 'amount', 'question': question.body, 'lang': 'es',
                   'data': {'args': {'action': 'create', 'kind': 'buy', 'asset': 'SPY'}, 'said': 'compra SPY'}}
        proposal = {'steps': [{'action': 'create', 'kind': 'buy', 'amount_usd': '15.00'}], 'created_at': 'x'}
        chip = {'type': 'navigate', 'target': 'smart_account_rule', 'label': 'Revisar y firmar'}
        confirm.store(conversation, viewer, pending, question)
        with mock.patch('assistant.asked.rule', return_value=(True, 'Nueva regla.', {
                'actions': [chip], 'rule_proposal': proposal})) as rule, \
                mock.patch('assistant.engine._openai_post') as model:
            reply, _model = self.say('15')
        model.assert_not_called()
        self.assertEqual(rule.call_args.args[2], Decimal('15.00'))
        self.assertEqual(reply.metadata['rule_proposal'], proposal)
        self.assertEqual(reply.metadata['actions'], [chip])
        # A spoken number is not the answer: the question is used up and nothing is made.
        question = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                 body='¿Cuántos dólares?', metadata={'ai': True})
        confirm.store(conversation, viewer, pending, question)
        with mock.patch('assistant.asked.rule') as rule:
            self.assertIsNone(confirm.answer(conversation, viewer, '15', confirm.take(conversation),
                                             SupportMessage(conversation=conversation, sender_type='USER', body='15',
                                                            metadata={'modality': 'VOICE'})))
        rule.assert_not_called()

    def test_a_save_waits_for_the_replys_checks(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        viewer = SimpleNamespace(user=self.user, account=self.account)
        pending = {'kind': 'watch', 'step': 'amount', 'question': '¿De cuántos dólares?', 'lang': 'es',
                   'data': {'args': {}, 'said': ''}}
        saved = mock.Mock(return_value=(True, 'Listo, guardé tu alerta.', {'writes': True}))
        real = confirm.answer
        for meanwhile in ('team', 'no, cancela'):
            question = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT',
                                                     message_type='TEXT', body='¿De cuántos dólares?',
                                                     metadata={'ai': True})
            confirm.store(conversation, viewer, pending, question)

            def answered(conv, *args, _meanwhile=meanwhile, **kwargs):
                out = real(conv, *args, **kwargs)
                SupportMessage.objects.create(
                    conversation=conv, message_type='TEXT', metadata={},
                    **({'sender_type': 'AGENT', 'body': 'Te ayudo yo.', 'sender_user': self.staff()}
                       if _meanwhile == 'team' else {'sender_type': 'USER', 'body': _meanwhile}))
                return out

            with mock.patch('assistant.asked.watch', return_value=(True, '', {'deferred': saved})), \
                    mock.patch('assistant.confirm.answer', side_effect=answered):
                outcome = service.ask(self.user, self.account, None, self.jwt, '50',
                                      request_meta={'HTTP_X_CONFIO_HOME': 'conversation',
                                                    'HTTP_X_CONFIO_VERSION': '5.4.0'})
            saved.assert_not_called()
            if meanwhile == 'team':
                self.assertIsNone(outcome.reply_message)
                from assistant.models import AssistantThreadState
                AssistantThreadState.objects.all().delete()
                SupportMessage.objects.filter(conversation=conversation, sender_user__isnull=False).delete()
            else:
                self.assertTrue(outcome.reply_message.body.startswith('No preparé nada'), outcome.reply_message.body)

    def test_no_lo_pagues_under_a_codes_card_withdraws_it_in_code(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT', body='x')
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Preparé el pago.', metadata={'ai': True, 'payment_intent': {
                                          'id': '00000000-0000-0000-0000-000000000001', 'code': 'tag'}})
        for outcome, start in (('withdrawn', 'Listo: retiré esa tarjeta'), ('paid', 'Esa tarjeta ya no está pendiente')):
            with mock.patch('assistant.sends.withdraw_cards', return_value=outcome), \
                    mock.patch('assistant.engine._openai_post') as model:
                reply, _model = self.say('no lo pagues, es estafa')
            model.assert_not_called()
            self.assertTrue(reply.body.startswith(start), reply.body)
            self.assertTrue(reply.metadata.get('declined'))
            SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                          body='Preparé el pago.', metadata={'ai': True, 'payment_intent': {
                                              'id': '00000000-0000-0000-0000-000000000001', 'code': 'tag'}})
        # Not under a card: the model answers as always.
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Hola.', metadata={'ai': True})
        reply, model = self.say('¿esto es estafa?', text_response('Te explico.'))
        model.assert_called()

    def test_a_split_the_rules_already_buy_is_only_saved(self):
        from assistant import asked
        belt = SimpleNamespace(viewer=SimpleNamespace(user=self.user, request_meta={}, tz=None),
                               result=SimpleNamespace(writes=[]))
        with mock.patch('smart_account.assistant_ops.propose_target_allocation',
                        return_value={'steps': [], 'texto': 'Guardé tu objetivo: 70% SPY.'}):
            _done, _text, extra = asked.allocation(belt, {'args': {}, 'said': ''}, Decimal('100'), 'es')
            done, text, extra = extra['deferred']()
        self.assertEqual((done, text, extra), (True, 'Guardé tu objetivo: 70% SPY.', {'writes': True}))

    def test_a_card_that_cannot_be_attached_says_so(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = SupportMessage.objects.create(
            conversation=get_or_create_support_conversation(self.user, self.account, None),
            sender_type='AGENT', message_type='TEXT', body='Preparé el pago.',
            metadata={'ai': True, 'actions': [{'target': 'payment_intent'}], 'payment_intent': {'id': 'x'}})
        with mock.patch('payment_accounts.payment_intents.attach_message', side_effect=RuntimeError('gone')):
            self.assertFalse(service._attach('x', conversation))
        conversation.refresh_from_db()
        self.assertEqual(conversation.body, 'No pude dejarte la tarjeta del pago. Pídemelo de nuevo en un momento.')
        self.assertEqual(conversation.metadata['actions'], [])
        self.assertIsNone(conversation.metadata['payment_intent'])


class RoundSevenTests(SimpleTestCase):
    def test_amount_shapes(self):
        for said, amount in (('20 dólares, gracias', '20.00'), ('20, por favor', '20.00'), ('20,50', '20.50')):
            self.assertEqual(str(confirm.amount_answer(said)), amount, said)
        # Never an amount, but still a number: code asks again rather than the model taking the reply.
        for said in ('R$20', '¡20!', 'S/ 20', '€20', '20 USDT', '1 500', '20²', '⑳', '½', '２０'):
            self.assertIsNone(confirm.amount_answer(said), said)
            self.assertTrue(confirm._number_shaped(said), said)

    def test_the_alert_question_names_the_alert_in_every_language(self):
        from smart_account import watches
        with mock.patch('smart_account.watches._asset_label', return_value='Tesla (TSLA)'):
            for lang, expected in (
                    ('pt', 'Eu te aviso se Tesla (TSLA) subir para US$200.00 ou mais.'),
                    ('en', "I'll let you know if Tesla (TSLA) rises to US$200.00 or more.")):
                self.assertEqual(watches.describe_in(lang, 'asset_price_above', asset_key='tsla',
                                                     threshold=Decimal('200')), expected)
            saved = watches.describe_in('pt', 'asset_price_drop_pct', asset_key='tsla', threshold=Decimal('5'),
                                        action={'amount_usd': '50', 'asset_key': 'tsla'})
            self.assertIn('cair 5%', saved)
            self.assertIn('US$50.00', saved)

    def test_the_question_itself_carries_the_terms(self):
        from assistant.engine import Toolbelt, TurnResult, Viewer
        viewer = Viewer(user=mock.Mock(pk=1), account=mock.Mock(id=1), account_type='personal', business_id=None,
                        is_business_owner=False, tz=None)
        with mock.patch('assistant.engine.allowed_destinations', return_value=[]):
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.last_user_message = 'quero um alerta se a Tesla subir acima de 200 e deixe pronta uma compra'
        draft = {'texto': 'Te aviso si Tesla (TSLA) sube a US$200 o más.', 'kind': 'asset_price_above',
                 'threshold': '200', 'asset_key': 'tsla', 'currency': '', 'action': {}}
        with mock.patch('smart_account.watches.propose', return_value=draft), \
                mock.patch('smart_account.watches._asset_label', return_value='Tesla (TSLA)'), \
                mock.patch('smart_account.assistant_ops._resolve_asset', return_value={'name': 'Tesla'}), \
                mock.patch('smart_account.assistant_ops._viewer', return_value=None):
            belt.smart_account_alerts('create', kind='asset_price_above', asset='Tesla', threshold=200,
                                      action_asset='Tesla')
        self.assertTrue(belt.result.pending_action['question'].startswith(
            'Eu te aviso se Tesla (TSLA) subir para US$200.00 ou mais. De quantos dólares'))


class StoreFailureLanguageTests(FlowBase):
    def test_the_apology_is_in_the_questions_language(self):
        args = {'side': 'sell', 'asset': 'Tesla', 'amount_usd': None, 'sell_all': False}
        with mock.patch('assistant.confirm.store', side_effect=RuntimeError('redis down')):
            reply, _model = self.say('quero vender minha Tesla',
                                     call_response('propose_stock_trade', json.dumps(args)), text_response('ok'))
        self.assertNotIn('No pude', reply.body)
        self.assertEqual(self.cards(reply), [])


class RoundEightTests(FlowBase):
    def test_a_team_message_after_the_question_ends_it(self):
        # The team asks its own question; their "sí" answers the team, never code's question above it.
        self.asked()
        conversation = SupportMessage.objects.filter(sender_type='USER').latest('created_at').conversation
        service.send_team_notice(conversation, 'Ya acreditamos tu recarga. ¿Te llegó bien?', 'topup-1',
                                 user_id=self.user.id)
        reply, model = self.say('sí', text_response('Qué bueno.'))
        model.assert_called()
        self.assertEqual(self.cards(reply), [])

    def test_a_team_number_question_after_the_amount_question_ends_it(self):
        self.asked('vende Tesla', sell_all=False)
        conversation = SupportMessage.objects.filter(sender_type='USER').latest('created_at').conversation
        service.send_team_notice(conversation, '¿Cuántos dólares quieres retirar a tu banco?', 'out-1',
                                 user_id=self.user.id)
        reply, model = self.say('20', text_response('Anotado.'))
        model.assert_called()
        self.assertEqual(self.cards(reply), [])


class RoundEightWordsTests(SimpleTestCase):
    def test_english_requests_are_english(self):
        for said in ('keep 70/30 between SPY and bitcoin every month', 'alert me if TSLA drops 5%',
                     'invest 20 in apple'):
            self.assertEqual(confirm.language([said]), 'en', said)
        for said in ('vende mi Tesla', 'compra Apple', 'avísame si Tesla baja 5%'):
            self.assertEqual(confirm.language([said]), 'es', said)
        self.assertEqual(confirm.language(['quero vender minha Tesla']), 'pt')

    def test_marks_on_a_digit_are_never_read_away(self):
        for said in ('2\u03360', '2\u03050'):
            self.assertIsNone(confirm.amount_answer(said), said)
            self.assertTrue(confirm._number_shaped(said), said)
        self.assertEqual(str(confirm.amount_answer('20 dólares')), '20.00')

    def test_portuguese_and_english_confirmations_name_the_rule(self):
        from assistant import asked
        steps = [{'action': 'create', 'kind': 'buy', 'amount_usd': '20', 'frequency': 'weekly', 'asset_name': 'Apple'}]
        dated = [{**steps[0], 'first_run_at': '2026-12-05T09:00:00-04:00'}]
        self.assertEqual(asked._step_lines(dated, 'pt'),
                         ['Nova regra: comprar US$20.00 de Apple toda semana, a partir de 05/12.'])
        self.assertEqual(asked._step_lines(dated, 'en'), ['New rule: buy US$20.00 of Apple every week, starting 05/12.'])
        self.assertEqual(asked._step_lines(steps, 'pt'), ['Nova regra: comprar US$20.00 de Apple toda semana.'])
        self.assertEqual(asked._step_lines(steps, 'en'), ['New rule: buy US$20.00 of Apple every week.'])
        cancel = [{'action': 'cancel', 'kind': 'buy', 'amount_usd': None, 'frequency': None, 'asset_name': 'Apple'}]
        self.assertEqual(asked._step_lines(cancel, 'en'), ['Cancel the rule for Apple.'])


class RoundNineTests(FlowBase):
    def _alert_question(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        question = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                 body='¿Guardo esta alerta?', metadata={'ai': True})
        draft = {'kind': 'asset_price_below', 'threshold': '200', 'asset_key': 'stock:TSLAon', 'currency': '',
                 'action': {}, 'texto': 'Te aviso si Tesla baja a US$200.00 o menos.'}
        service._store_pending_watch(conversation, SimpleNamespace(user=self.user), draft, question)
        return conversation

    def _yes_with(self, conversation, meanwhile):
        from users.models import User
        real_lock = service.lock_user
        staff = User.objects.create_user(username=f'team_r9_{meanwhile}', email=f'r9{meanwhile}@example.com',
                                         password='x', firebase_uid=f'fb-r9-{meanwhile}', is_staff=True)

        def lock(user):
            # What landed after the "sí" and before the save takes the person's lock.
            if meanwhile and not getattr(lock, 'done', False) and SupportMessage.objects.filter(
                    conversation=conversation, sender_type='USER', body='sí').exists():
                lock.done = True
                SupportMessage.objects.create(conversation=conversation, message_type='TEXT', metadata={}, **(
                    {'sender_type': 'AGENT', 'body': 'Te ayudo yo.', 'sender_user': staff} if meanwhile == 'team'
                    else {'sender_type': 'USER', 'body': 'no, cancela'}))
            return real_lock(user)

        with mock.patch('assistant.service.lock_user', side_effect=lock), \
                mock.patch('smart_account.watches.save') as save, \
                mock.patch('assistant.engine._openai_post', side_effect=[text_response('Claro.')] * 3):
            service.ask(self.user, self.account, None, self.jwt, 'sí', request_meta=META)
        return save

    def test_the_alert_yes_saves_when_nothing_came_after_it(self):
        self.assertTrue(self._yes_with(self._alert_question(), None).called)

    def test_a_team_reply_or_a_new_message_after_the_yes_stops_the_alert_save(self):
        for meanwhile in ('team', 'user'):
            cache.clear()
            save = self._yes_with(self._alert_question(), meanwhile)
            self.assertFalse(save.called, meanwhile)

    def test_a_direction_control_is_never_read_away_from_the_number(self):
        for said in ('‮02', '2​0', '⁦20⁩'):
            self.assertIsNone(confirm.amount_answer(said), repr(said))
            self.assertTrue(confirm._number_shaped(said), repr(said))


class RoundTenTests(FlowBase):
    def test_a_team_notice_after_the_answer_stops_the_card(self):
        self.asked('vende Tesla', sell_all=False)
        real = confirm.answer

        def noticed(conversation, *args, **kwargs):
            out = real(conversation, *args, **kwargs)
            service.send_team_notice(conversation, 'Mantenimiento a las 22:00.', 'maint-1', user_id=self.user.id)
            return out

        with mock.patch('assistant.confirm.answer', side_effect=noticed):
            reply, _model = self.say('20')
        self.assertEqual(self.cards(reply), [])
        self.assertIn('equipo', reply.body)

    def test_portuguese_requests_are_portuguese(self):
        for said in ('me avise se a Tesla cair 5%', 'compre Apple todo mês', 'manda dinheiro para @ana',
                     'invista em Apple'):
            self.assertEqual(confirm.language([said]), 'pt', said)
        for said in ('avísame si Tesla baja 5%', 'pague este recibo', 'mande 20 a Ana', 'compra Apple cada mes'):
            self.assertEqual(confirm.language([said]), 'es', said)

    def test_the_plain_alert_in_portuguese(self):
        draft = {'kind': 'asset_price_below', 'threshold': '200', 'asset_key': 'stock:TSLAon', 'currency': '',
                 'action': {}, 'texto': 'Te aviso si Tesla baja a US$200.00 o menos.', 'lang': 'pt'}
        with mock.patch('smart_account.watches._asset_label', return_value='Tesla (TSLA)'):
            self.assertEqual(service.watch_confirmation_question(draft),
                             'Salvo este alerta? Eu te aviso se Tesla (TSLA) cair para US$200.00 ou menos. '
                             'Responda "sim" para salvar.')
        self.assertTrue(service.watch_confirmation_question({**draft, 'lang': 'es'}).startswith(
            '¿Guardo esta alerta? Te aviso si Tesla baja'))


class RoundElevenTests(FlowBase):
    def test_names_and_formal_spanish_stay_spanish(self):
        for said in ('Dele 20 dólares a Juan', 'Envíale a João', 'Quiero enviarle a Conceição por Pix',
                     'Envía a Paulo Conceição'):
            self.assertEqual(confirm.language([said]), 'es', said)
        for said in ('é golpe?', 'É golpe?', 'não quero', 'compre Apple todo mês'):
            self.assertEqual(confirm.language([said]), 'pt', said)

    def test_a_team_notice_while_asking_again_closes_the_question(self):
        question = self.asked('vende Tesla', sell_all=False).body
        real = confirm.answer

        def noticed(conversation, *args, **kwargs):
            out = real(conversation, *args, **kwargs)
            service.send_team_notice(conversation, 'No operes ahora: mantenimiento.', 'maint-2', user_id=self.user.id)
            return out

        with mock.patch('assistant.confirm.answer', side_effect=noticed):
            reply, _model = self.say('1.500')
        self.assertNotIn(question, reply.body)
        reply, model = self.say('20', text_response('Claro.'))
        model.assert_called()
        self.assertEqual(self.cards(reply), [])


class RoundTwelveTests(FlowBase):
    def test_spanish_with_lowercase_names_and_loanwords_stays_spanish(self):
        for said in ('mándale 20 a joão', 'envía a joão 20', 'envíale a conceição', 'paga el pix de joão',
                     'haz un split 60/40 entre apple y tesla', 'pon un split 70/30 de apple y tesla',
                     'set de alertas para tesla'):
            self.assertEqual(confirm.language([said]), 'es', said)
        for said in ('não quero', 'é golpe?', 'manda dinheiro para @ana', 'me avise se a Tesla cair 5%'):
            self.assertEqual(confirm.language([said]), 'pt', said)
        for said in ('invest 20 in apple', 'alert me if TSLA drops 5%', 'forget what I said'):
            self.assertEqual(confirm.language([said]), 'en', said)

    def test_a_server_line_after_the_alert_yes_does_not_lose_it(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        question = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                 body='¿Guardo esta alerta?', metadata={'ai': True})
        draft = {'kind': 'asset_price_below', 'threshold': '200', 'asset_key': 'stock:TSLAon', 'currency': '',
                 'action': {}, 'texto': 'Te aviso si Tesla baja a US$200.00 o menos.'}
        service._store_pending_watch(conversation, SimpleNamespace(user=self.user), draft, question)
        real_lock = service.lock_user

        def lock(user):
            if not getattr(lock, 'done', False) and SupportMessage.objects.filter(
                    conversation=conversation, sender_type='USER', body='sí').exists():
                lock.done = True
                SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                              body='Tu alerta se cumplió.', metadata={'system_note': True})
            return real_lock(user)

        with mock.patch('assistant.service.lock_user', side_effect=lock), \
                mock.patch('smart_account.watches.save') as save, \
                mock.patch('assistant.engine._openai_post', side_effect=[text_response('Claro.')] * 3):
            service.ask(self.user, self.account, None, self.jwt, 'sí', request_meta=META)
        self.assertTrue(save.called)


class NoticeDuringTheTurnTests(FlowBase):
    CODE = ('00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865406'
            '10.005802BR5913Fulano de Tal6008BRASILIA62070503***6304ABCD')

    def _pasted(self, notice):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        responses = [call_response('prepare_payment', json.dumps({'rail': None, 'recipient': None,
                                                                  'amount_usd': None})), text_response('Listo.')]
        calls = {'n': 0}

        def post(*_a, **_k):
            calls['n'] += 1
            if calls['n'] == 2 and notice:
                service.send_team_notice(conversation, 'No pagues nada ahora: mantenimiento.', 'maint-x',
                                         user_id=self.user.id)
            return responses[calls['n'] - 1]

        with mock.patch('assistant.engine.Toolbelt.payments_ready', return_value=True), \
                mock.patch('assistant.sends._has_amount', return_value=True), \
                mock.patch('payment_accounts.payment_intents.code_in_words', return_value=self.CODE), \
                mock.patch('payment_accounts.payment_intents.prepare_from_request',
                           return_value=SimpleNamespace(internal_id='intent-9')), \
                mock.patch('payment_accounts.payment_intents.attach_message') as attach, \
                mock.patch('assistant.engine._openai_post', side_effect=post):
            outcome = service.ask(self.user, self.account, None, self.jwt, self.CODE, request_meta=META)
        return outcome.reply_message, attach

    def test_a_pasted_code_gets_its_card(self):
        reply, attach = self._pasted(False)
        self.assertTrue(attach.called)
        self.assertTrue(reply.metadata.get('payment_intent'))

    def test_a_team_notice_while_the_model_ran_stops_the_card(self):
        reply, attach = self._pasted(True)
        self.assertFalse(attach.called)
        self.assertFalse(reply.metadata.get('payment_intent'))
        self.assertIn('equipo', reply.body)


class RoundThirteenTests(SimpleTestCase):
    def test_language_from_words_not_names_or_loans(self):
        for said in ('Vendeme 20 shares de Tesla stock', 'Comprame 20 shares de Tesla stock',
                     'Hazme un buy de Tesla every month', 'liquida Tesla para joão', 'transfiere 20 a joão',
                     'mándale 20 a joão', 'Envíale a João', 'ya está', 'pague el código', 'set de alertas para tesla'):
            self.assertEqual(confirm.language([said]), 'es', said)
        for said in ('não quero', 'é golpe?', 'compre Apple todo mês', 'manda dinheiro para @ana',
                     'me avise se a Tesla cair 5%', 'quero vender minha Tesla', 'invista em Apple'):
            self.assertEqual(confirm.language([said]), 'pt', said)
        for said in ('invest 20 in apple', 'alert me if TSLA drops 5%', 'I want to buy a share of Apple',
                     'forget what I said', 'keep 70/30 between SPY and bitcoin every month'):
            self.assertEqual(confirm.language([said]), 'en', said)

    def test_a_number_dressed_up_is_asked_again(self):
        for said in ('20 👍', '20 :)', '*20*', '(20)', '20,-', 'son 20', 'R$20', 'S/ 20', '50%'):
            self.assertIsNone(confirm.amount_answer(said), said)
            self.assertTrue(confirm._number_shaped(said), said)
        for said in ('tengo 3', 'no, 20 no', '¿20?', 'manda 20 a @ana', 'recuerda que mi meta es 500 dólares'):
            self.assertFalse(confirm._number_shaped(said), said)


class RoundFourteenTests(SimpleTestCase):
    def test_queria_is_spanish_too(self):
        for said in ('quería comprar Tesla', 'quería enviarle a @ana', 'queria pagar este codigo'):
            self.assertEqual(confirm.language([said]), 'es', said)
        self.assertEqual(confirm.language(['eu queria vender minha Tesla']), 'pt')

    def test_argentine_dollars_and_thousands(self):
        for said, amount in (('u$s 20', '20.00'), ('U$D 20', '20.00'), ('u$s20', '20.00')):
            self.assertEqual(str(confirm.amount_answer(said)), amount, said)
        self.assertIsNone(confirm.amount_answer('20k'))
        self.assertTrue(confirm._number_shaped('20k'))


class RoundFifteenTests(SimpleTestCase):
    def test_words_both_languages_share_never_make_it_portuguese(self):
        for said in ('Confío pro, compra apple', 'vende Tesla', 'paga el pix', 'manda 20 a @ana', 'compra pro'):
            self.assertEqual(confirm.language([said]), 'es', said)
        for said in ('vende minha Tesla', 'paga esse pix', 'manda pra ela'):
            self.assertEqual(confirm.language([said]), 'pt', said)


class RoundSixteenTests(FlowBase):
    def test_words_portuguese_shares_are_not_spanish(self):
        for said in ('envia isso', 'envia a ela', 'quero vendê-la'):
            self.assertEqual(confirm.language([said]), 'pt', said)
        for said in ('envíale 20 a @ana', 'vende la de Tesla'):
            self.assertEqual(confirm.language([said]), 'es', said)

    def test_an_accent_typed_apart_is_still_the_amount(self):
        self.assertEqual(str(confirm.amount_answer('20 do\u0301lares')), '20.00')
        self.assertIsNone(confirm.amount_answer('2\u03360'))

    def test_a_dropped_card_is_closed_and_not_counted(self):
        from payment_accounts.models import PaymentIntent
        retired = []
        with mock.patch.object(PaymentIntent.objects, 'filter') as found:
            found.return_value.update.side_effect = lambda **kw: retired.append(kw) or 1
            service._retire_unshown({'id': 'intent-1'})
        self.assertEqual(retired[0]['state'], 'expired')
        self.assertEqual(retired[0]['state_reason'], 'dropped_in_chat')


class RoundSeventeenTests(FlowBase):
    def test_names_never_choose_the_language(self):
        for said in ('envía a Uma', 'manda 20 a Ela', 'paga a Isso', 'mándale a Essa'):
            self.assertEqual(confirm.language([said]), 'es', said)
        for said in ('Isso é golpe?', 'Ela quer vender', 'uma ação da Tesla'):
            self.assertEqual(confirm.language([said]), 'pt', said)

    def test_more_numbers_asked_again_and_not_knowing_is_not_a_no(self):
        for said in ('20mil', '20 lucas', '20 nomás'):
            self.assertIsNone(confirm.amount_answer(said), said)
            self.assertTrue(confirm._number_shaped(said), said)
        self.asked('vende Tesla', sell_all=False)
        reply, model = self.say('no sé', text_response('Te cuento.'))
        model.assert_called()
        self.assertNotIn('no preparé nada', reply.body)

    def test_a_call_is_never_offered_the_tools_code_asks_about_in_the_chat(self):
        from assistant import voice
        for name in ('propose_smart_account_rule', 'propose_target_allocation', 'smart_account_alerts'):
            self.assertIn(name, voice.TEXT_ONLY_TOOLS)

    def test_a_card_that_cannot_be_attached_is_closed(self):
        reply = SupportMessage(body='x', metadata={})
        with mock.patch('payment_accounts.payment_intents.attach_message', side_effect=RuntimeError('db')), \
                mock.patch('assistant.service._retire_unshown') as retire, \
                mock.patch.object(SupportMessage, 'save'):
            self.assertFalse(service._attach('intent-7', reply))
        retire.assert_called_once_with({'id': 'intent-7'})


class RoundEighteenTests(FlowBase):
    def test_a_doubt_that_starts_with_no_is_the_models(self):
        for said in ('no sé cuánto poner', 'no tengo idea', 'no estoy seguro, ¿cuál es el mínimo?', 'nao sei quanto'):
            self.asked('vende Tesla', sell_all=False)
            reply, model = self.say(said, text_response('Te explico.'))
            model.assert_called()
            self.assertNotIn('no preparé nada', reply.body, said)
        for said in ('no, 20 no', 'cancela todo, 2'):
            self.asked('vende Tesla', sell_all=False)
            reply, model = self.say(said)
            model.assert_not_called()
            self.assertIn('no preparé nada', reply.body, said)

    def test_english_with_i_and_e_wallet(self):
        for said in ('Can I buy Apple?', 'um I want to sell my Tesla', 'send 20 to my e-wallet please'):
            self.assertEqual(confirm.language([said]), 'en', said)

    def test_no_lo_pagues_withdraws_the_scanned_card_right_above(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'old', 'code': 'c'}})
        SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                      body='Preparé este pago.', metadata={'payment_intent': {'id': 'scanned'}})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no lo pagues', metadata={})
        from assistant import sends
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), 'no lo pagues', said)
        self.assertTrue(out[0])
        _account, messages, ids = withdraw.call_args[0]
        self.assertEqual(ids, ['scanned'])
        self.assertNotIn('old', ids)

    def test_the_same_yes_twice_keeps_the_alert_save(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        question = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                 body='¿Guardo esta alerta?', metadata={'ai': True})
        draft = {'kind': 'asset_price_below', 'threshold': '200', 'asset_key': 'stock:TSLAon', 'currency': '',
                 'action': {}, 'texto': 'Te aviso si Tesla baja a US$200.00 o menos.'}
        service._store_pending_watch(conversation, SimpleNamespace(user=self.user), draft, question)
        real_lock = service.lock_user

        def lock(user):
            if not getattr(lock, 'done', False) and SupportMessage.objects.filter(
                    conversation=conversation, sender_type='USER', body='sí').exists():
                lock.done = True
                SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                              body='sí', metadata={})
            return real_lock(user)

        with mock.patch('assistant.service.lock_user', side_effect=lock), \
                mock.patch('smart_account.watches.save') as save, \
                mock.patch('assistant.engine._openai_post', side_effect=[text_response('Claro.')] * 3):
            service.ask(self.user, self.account, None, self.jwt, 'sí', request_meta=META)
        self.assertTrue(save.called)


class RoundTwentyTests(FlowBase):
    def test_an_alert_question_is_not_kept_when_they_wrote_while_the_model_answered(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        draft = {'kind': 'asset_price_below', 'threshold': '200', 'asset_key': 'stock:TSLAon', 'currency': '',
                 'action': {}, 'texto': 'Te aviso si Tesla baja a US$200.00 o menos.'}
        responses = [call_response('smart_account_alerts', json.dumps(
            {'action': 'create', 'kind': 'asset_price_below', 'asset': 'Tesla', 'currency': None, 'threshold': 200,
             'action_asset': None, 'action_amount_usd': None, 'alert_id': None})), text_response('Listo.')]

        def post(*_a, **_k):
            out = responses.pop(0)
            if not responses:       # "no espera, mejor a 150" written while the model answers
                SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                              body='no espera, mejor a 150', sender_user=self.user)
            return out

        with mock.patch('assistant.engine.Toolbelt.smart_ops', return_value=True), \
                mock.patch('smart_account.watches.propose', return_value=dict(draft)), \
                mock.patch('assistant.engine._openai_post', side_effect=post):
            first = service.ask(self.user, self.account, None, self.jwt, 'avísame si Tesla baja a 200',
                                request_meta=META)
        self.assertNotIn('¿Guardo esta alerta?', first.reply_message.body)
        self.assertIsNone(cache.get(service._pending_watch_key(conversation)))
        with mock.patch('smart_account.watches.save') as save, \
                mock.patch('assistant.engine._openai_post', side_effect=[text_response('Claro.')] * 3):
            service.ask(self.user, self.account, None, self.jwt, 'sí', request_meta=META)
        self.assertFalse(save.called)


class ReplayFindingsTests(SimpleTestCase):
    def test_a_level_passed_with_its_sign_is_a_plain_number(self):
        from smart_account import watches
        for given, level in (('5%', '5'), (' 5 % ', '5'), ('US$200', '200'), ('200 USD', '200'), ('5,5%', '5.5'),
                             (5, 5), ('200', '200')):
            self.assertEqual(watches._level(given), level, given)
        self.assertIsNone(watches._level('%'))


class RoundTwentyTwoTests(FlowBase):
    def _thread(self, card, sender='AGENT'):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        above = SupportMessage.objects.create(conversation=conversation, sender_type=sender, message_type='TEXT',
                                              body='Tarjeta', metadata={'ai': True, 'payment_intent': card})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no lo pagues', metadata={})
        return conversation, above, said

    def _withdraw(self, conversation, said, text='no lo pagues, es estafa'):
        from assistant import sends
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), text, said)
        return out, withdraw.call_args[0] if withdraw.called else None

    def test_a_requoted_card_is_withdrawn_by_its_message(self):
        conversation, above, said = self._thread({'id': 'old-quote', 'code': 'tag'})
        out, (_account, messages, ids) = self._withdraw(conversation, said)
        self.assertTrue(out[0])
        self.assertEqual(messages, [above.pk])
        self.assertEqual(ids, ['old-quote'])

    def test_a_typed_amount_card_is_withdrawn_too(self):
        conversation, above, said = self._thread({'id': 'send-1'})
        out, _args = self._withdraw(conversation, said, 'no lo envíes, es estafa')
        self.assertTrue(out[0])
        self.assertIn('pídemelo de nuevo', out[1])


class RoundTwentyThreeTests(FlowBase):
    def test_a_card_scanned_under_the_question_ends_it(self):
        self.asked('vende Tesla', sell_all=False)
        conversation = SupportMessage.objects.filter(sender_type='USER').latest('created_at').conversation
        SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                      body='Preparé este pago. Revísalo antes de pagar.',
                                      metadata={'payment_intent': {'id': 'scanned-1'}, 'system_note': True})
        with mock.patch('assistant.sends.withdraw_declined', return_value=(True, 'Listo: retiré esa tarjeta.',
                                                                           {'declined': True})) as withdraw:
            reply, model = self.say('no lo pagues')
        withdraw.assert_called_once()
        model.assert_not_called()
        self.assertIn('retiré esa tarjeta', reply.body)
        # A server line without a card still does not end the question.
        self.asked('vende Tesla', sell_all=False)
        SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                      body='Tu alerta se cumplió.', metadata={'system_note': True})
        reply, _model = self.say('20')
        self.assertEqual(self.cards(reply)[0]['target'], 'sell:20.00')


class RoundTwentyFourTests(FlowBase):
    def test_emoji_are_not_odd_numbers(self):
        for said in ('no sé 🤷‍♀️', 'mejor mañana te digo ❤️', 'para mi mamá ❤️', 'luego ✌️'):
            self.assertFalse(confirm._number_shaped(said), said)
        for said in ('2̶0', '‮02', '20²', '２０'):
            self.assertTrue(confirm._number_shaped(said), said)
        self.asked('vende Tesla', sell_all=False)
        reply, model = self.say('no sé 🤷‍♀️', text_response('Te ayudo.'))
        model.assert_called()

    def test_not_a_scam_said_plainly_keeps_the_card(self):
        from assistant import sends
        self.assertFalse(sends._said_not_to_pay('no es estafa, págalo'))
        self.assertFalse(sends._said_not_to_pay('não é golpe, pode pagar'))
        self.assertTrue(sends._said_not_to_pay('¿no es estafa?'))
        self.assertTrue(sends._said_not_to_pay('es estafa'))
        self.assertTrue(sends._said_not_to_pay('no es estafa? no lo pagues'))

    def test_a_no_to_the_alert_question_is_answered_by_code(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        question = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                 body='¿Guardo esta alerta?', metadata={'ai': True})
        draft = {'kind': 'asset_price_below', 'threshold': '200', 'asset_key': 'stock:TSLAon', 'currency': '',
                 'action': {}, 'texto': 'Te aviso si Tesla baja a US$200.00 o menos.'}
        service._store_pending_watch(conversation, SimpleNamespace(user=self.user), draft, question)
        with mock.patch('smart_account.watches.save') as save:
            reply, model = self.say('no')
        model.assert_not_called()
        self.assertFalse(save.called)
        self.assertEqual(reply.body, 'Listo, no guardé nada.')


class RoundTwentyFiveTests(FlowBase):
    def test_a_joiner_inside_a_number_is_asked_again(self):
        for said in ('2‍0', '1‍00', '2️0'):
            self.assertIsNone(confirm.amount_answer(said), repr(said))
            self.assertTrue(confirm._number_shaped(said), repr(said))
        self.assertFalse(confirm._number_shaped('no sé 🤷‍♀️'))

    def test_a_withdrawn_card_is_cancelled_and_never_requoted(self):
        from payment_accounts import payment_intents
        old = SimpleNamespace(state_reason='declined_in_chat', family='local_charge')
        with mock.patch.object(payment_intents, '_require_owner'), \
                mock.patch.object(payment_intents, '_owned', return_value=old):
            with self.assertRaises(Exception) as refused:
                payment_intents.requote(self.account, self.user, 'x')
        self.assertIn('not_open', str(getattr(refused.exception, 'code', '')) + str(refused.exception))
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1', 'code': 't'}})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no lo pagues', metadata={'modality': 'VOICE'})
        from assistant import sends
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), 'no lo pagues', said)
        self.assertTrue(out[0])                          # a voice note withdraws too
        withdraw.assert_called_once()


class RoundTwentySixTests(FlowBase):
    def _card(self, conversation, sender='AGENT'):
        return SupportMessage.objects.create(conversation=conversation, sender_type=sender, message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c9',
                                                                                                    'code': 't'}})

    def test_no_lo_pagues_after_their_own_line_still_withdraws_the_card(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        card = self._card(conversation)
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                      body='espera', metadata={})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no lo pagues, es estafa', metadata={})
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account),
                                          'no lo pagues, es estafa', said)
        self.assertTrue(out[0])
        self.assertEqual(withdraw.call_args[0][1], [card.pk])
        # The assistant answered in between: that card is no longer "right above".
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Claro.', metadata={'ai': True})
        later = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                              body='no lo pagues', metadata={})
        self.assertIsNone(sends.withdraw_declined(conversation, SimpleNamespace(account=self.account),
                                                  'no lo pagues', later))

    def test_a_caption_under_a_card_withdraws_it(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        self._card(conversation)
        with mock.patch('assistant.sends.withdraw_declined',
                        return_value=(True, 'Listo: retiré esa tarjeta.', {'declined': True})) as withdraw, \
                mock.patch('assistant.engine._openai_post') as model, \
                mock.patch('assistant.photos.prepare', return_value='data:image/jpeg;base64,aGk='), \
                mock.patch('assistant.photos.keep'):
            outcome = service.ask(self.user, self.account, None, self.jwt, 'no lo pagues, es estafa',
                                  request_meta=META, photo=('aGk=', 'image/jpeg'))
        withdraw.assert_called_once()
        model.assert_not_called()
        self.assertIn('retiré esa tarjeta', outcome.reply_message.body)

    def test_no_card_of_a_withdrawn_message_is_requoted(self):
        from payment_accounts import payment_intents
        old = SimpleNamespace(state_reason='superseded', family='local_charge', message_id=77)
        with mock.patch.object(payment_intents, '_require_owner'), \
                mock.patch.object(payment_intents, '_owned', return_value=old), \
                mock.patch.object(payment_intents, '_withdrawn_message', return_value=True) as marked:
            with self.assertRaises(Exception) as refused:
                payment_intents.requote(self.account, self.user, 'x')
        self.assertIn('not_open', str(getattr(refused.exception, 'code', '')) + str(refused.exception))
        marked.assert_called_once_with(77)


class WithdrawCardsTests(FlowBase):
    """withdraw_cards on real rows: what is closed, what is said to be paid, and that nothing comes back."""

    def _row(self, message_id, state, **kw):
        from datetime import timedelta as delta
        from payment_accounts.models import PaymentIntent
        return PaymentIntent.objects.create(
            confio_account=self.account, user=self.user, created_by='assistant', source='pasted_code',
            rail_method_id='br_qr', family=kw.pop('family', 'local_charge'), payee_name='X',
            payee_level='unverified', amount_local=Decimal('10'), currency='BRL', total_usd=Decimal('2'),
            fee_usd=Decimal('0'), estimated_return_usd=Decimal('0'), rate=Decimal('5'),
            expires_at=timezone.now() + delta(minutes=5), display_hash='h', state=state, message_id=message_id, **kw)

    def _card(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        return SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True})

    def test_unpaid_rows_are_cancelled_and_the_message_marked(self):
        from assistant import sends
        from payment_accounts import payment_intents
        card = self._card()
        old = self._row(card.pk, 'expired', state_reason='requoted')
        live = self._row(card.pk, 'quoted')
        self.assertEqual(sends.withdraw_cards(self.account, [card.pk], [str(old.internal_id)]), 'withdrawn')
        for row in (old, live):
            row.refresh_from_db()
            self.assertEqual((row.state, row.state_reason), ('cancelled', 'declined_in_chat'))
        card.refresh_from_db()
        self.assertTrue(card.metadata.get('withdrawn'))
        self.assertTrue(payment_intents._withdrawn_message(card.pk))

    def test_a_paid_requote_is_said_to_be_paid(self):
        from assistant import sends
        card = self._card()
        old = self._row(card.pk, 'expired', state_reason='requoted')
        self._row(card.pk, 'submitted', outcome='paid', supersedes=old)
        with mock.patch('payment_accounts.payment_intents.status', return_value=('paid', None)):
            self.assertEqual(sends.withdraw_cards(self.account, [card.pk], [str(old.internal_id)]), 'paid')

    def test_a_failed_approval_is_not_paid_and_never_requoted(self):
        from assistant import sends
        from payment_accounts import payment_intents
        card = self._card()
        row = self._row(card.pk, 'submitted', family='ramp_order', order_ref='ord-1')
        with mock.patch('payment_accounts.payment_intents.status', return_value=('expired', None)):
            self.assertEqual(sends.withdraw_cards(self.account, [card.pk], [str(row.internal_id)]), 'withdrawn')
        with mock.patch.object(payment_intents, '_require_owner'):
            with self.assertRaises(Exception) as refused:
                payment_intents.requote(self.account, self.user, str(row.internal_id))
        self.assertIn('not_open', str(getattr(refused.exception, 'code', '')) + str(refused.exception))

    def test_le_forms_are_a_no(self):
        from assistant import sends
        for said in ('no le pagues', 'no le envíes', 'no le mandes nada', 'no se lo pagues', 'no los pagues'):
            self.assertTrue(sends._said_not_to_pay(said), said)


    def test_a_payment_waiting_for_the_signature_is_said_so_and_left_alone(self):
        from assistant import sends
        card = self._card()
        row = self._row(card.pk, 'submitted')
        with mock.patch('payment_accounts.payment_intents.status', return_value=('awaiting_signature', None)):
            self.assertEqual(sends.withdraw_cards(self.account, [card.pk], [str(row.internal_id)]), 'signing')
        row.refresh_from_db()
        self.assertEqual(row.state, 'submitted')           # never overwritten: its journey is the payment
        self.assertIn('no lo firmes', sends._STILL_YOURS['signing']['es'])

    def test_no_card_of_theirs_is_not_called_withdrawn(self):
        from assistant import sends
        card = self._card()
        self.assertEqual(sends.withdraw_cards(self.account, [card.pk], ['00000000-0000-0000-0000-00000000abcd']),
                         'none')


class StoreTaskBesideAQuestionTests(SimpleTestCase):
    def test_no_purchase_starts_in_a_reply_that_carries_codes_question(self):
        from assistant.engine import Toolbelt, Viewer
        viewer = Viewer(user=mock.Mock(pk=1), account=mock.Mock(id=1), account_type='personal', business_id=None,
                        is_business_owner=False, tz=None)
        with mock.patch('assistant.engine.allowed_destinations', return_value=[]):
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.result.pending_action = {'kind': 'trade', 'question': '¿Cuántos dólares…?'}
        with mock.patch('agent_tasks.assistant_tool.call') as start:
            out = belt.start_store_task(store='amazon')
        self.assertIs(out['ok'], False)
        start.assert_not_called()


class RoundTwentyNineTests(FlowBase):
    def test_no_question_or_card_after_a_store_purchase_started(self):
        result = TurnResult(reply='')
        result.store_task_started = True
        self.assertTrue(confirm.busy(result))
        from assistant.engine import Toolbelt, Viewer
        viewer = Viewer(user=mock.Mock(pk=1), account=mock.Mock(id=1), account_type='personal', business_id=None,
                        is_business_owner=False, tz=None)
        with mock.patch('assistant.engine.allowed_destinations', return_value=[]):
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        with mock.patch('agent_tasks.assistant_tool.call', return_value=({'ok': True}, None)):
            belt.start_store_task(store='amazon')
        self.assertTrue(confirm.busy(belt.result))

    def test_no_lo_pagues_while_the_team_has_the_thread_still_withdraws(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1', 'code': 't'}})
        with mock.patch('assistant.service.is_human_mode', return_value=True), \
                mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw, \
                mock.patch('assistant.engine._openai_post') as model, \
                self.captureOnCommitCallbacks(execute=True):
            outcome = service.ask(self.user, self.account, None, self.jwt, 'no lo pagues, es estafa',
                                  request_meta=META)
        model.assert_not_called()
        self.assertIsNone(outcome.reply_message)
        withdraw.assert_called_once()
        self.assertTrue(SupportMessage.objects.filter(conversation=conversation, sender_type='SYSTEM',
                                                      body__startswith='Listo: retiré esa tarjeta').exists())


class RoundThirtyTests(FlowBase):
    def test_out_of_turns_no_lo_pagues_still_withdraws(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1', 'code': 't'}})
        with mock.patch('assistant.service.remaining_turns', return_value=0), \
                mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw, \
                self.captureOnCommitCallbacks(execute=True):
            service.ask(self.user, self.account, None, self.jwt, 'no lo pagues, es estafa', request_meta=META)
        withdraw.assert_called_once()
        self.assertTrue(SupportMessage.objects.filter(conversation=conversation, sender_type='SYSTEM',
                                                      body__startswith='Listo: retiré esa tarjeta').exists())

    def test_everyday_phrases_are_not_a_no(self):
        from assistant import sends
        for said in ('págalo todo de golpe', 'no es ninguna estafa, págalo', 'tranquila, no es estafa, págalo'):
            self.assertFalse(sends._said_not_to_pay(said), said)
        for said in ('es un golpe, no lo pagues', 'es estafa', '¿no es estafa?'):
            self.assertTrue(sends._said_not_to_pay(said), said)


class RoundThirtyOneTests(FlowBase):
    def test_told_to_pay_it_beats_a_softer_word(self):
        from assistant import sends
        for said in ('págalo de un golpe', 'ya pagué la luz, ahora págalo', 'no creo que sea estafa, págalo',
                     'no hay estafa, dale págalo', 'págalo, no es mío el problema'):
            self.assertFalse(sends._said_not_to_pay(said), said)
        for said in ('es estafa, dale', 'no lo pagues, dale', 'ya lo pagué', 'es un golpe', 'no es mío'):
            self.assertTrue(sends._said_not_to_pay(said), said)

    def test_a_newer_code_ends_the_walk(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'a1', 'code': 't'}})
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                      body='paga este también CODE', metadata={})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no, ese no lo pagues', metadata={})
        with mock.patch('assistant.sends.intents_codes', side_effect=lambda text: ['c'] if 'CODE' in text else []), \
                mock.patch('assistant.sends.withdraw_cards') as withdraw:
            self.assertIsNone(sends.withdraw_declined(conversation, SimpleNamespace(account=self.account),
                                                      'no, ese no lo pagues', said))
        withdraw.assert_not_called()

    def test_the_line_goes_in_the_cards_own_thread(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        service._note_in_thread(conversation, 'Listo: retiré esa tarjeta.', 'withdrawn:1')
        service._note_in_thread(conversation, 'Listo: retiré esa tarjeta.', 'withdrawn:1')
        self.assertEqual(conversation.messages.filter(sender_type='SYSTEM', metadata__notice='withdrawn:1').count(), 1)

    def test_what_was_already_changed_is_said(self):
        result = TurnResult(reply='')
        result.writes = ['alert_deleted']
        self.assertEqual(service._done_already(result, 'es'), ' Además, borré la alerta.')
        self.assertEqual(service._done_already(TurnResult(reply=''), 'es'), '')


class RoundThirtyTwoTests(SimpleTestCase):
    def test_a_no_then_a_scam_word_withdraws(self):
        from assistant import sends
        for said in ('No, es estafa', 'No. Es una estafa.', 'NO, ES ESTAFA', 'ahora no, es estafa',
                     'creo que no, es estafa', 'no!! es un fraude', 'Não, é golpe', 'no, scam'):
            self.assertTrue(sends._said_not_to_pay(said), said)
        for said in ('no es estafa, págalo', 'não é golpe, pode pagar', "it's not a scam, pay it"):
            self.assertFalse(sends._said_not_to_pay(said), said)

    def test_i_did_not_pay_it_is_not_dont_pay_it(self):
        from assistant import sends
        for said in ('Págalo, que no lo pagué ayer', 'no lo pagué todavía, págalo', 'págalo, todavía no lo pagué'):
            self.assertFalse(sends._said_not_to_pay(said), said)
        self.assertTrue(sends._said_not_to_pay('no lo pagues, dale'))

    def test_every_form_of_dont(self):
        from assistant import sends
        for said in ('no le pague', 'no la pague', 'no lo envíe', 'não envie', 'não mande', "don't send it",
                     'do not send it', 'no lo vayas a pagar', 'no pagar'):
            self.assertTrue(sends._said_not_to_pay(said), said)


class RoundThirtyThreeTests(FlowBase):
    def test_more_ways_to_say_dont_pay(self):
        from assistant import sends
        for said in ('no me lo pagues', 'no quiero que lo pagues', 'ni se te ocurra pagarlo', 'eso no se paga',
                     'não quero pagar', 'não vou pagar', 'nem pague', "I don't want to pay it", "I won't pay it"):
            self.assertTrue(sends._said_not_to_pay(said), said)

    def _thread(self, *after):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        card = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True, 'payment_intent': {
                                                 'id': 'c1', 'code': sends_tag('CODE-A')}})
        for sender, body, metadata in after:
            SupportMessage.objects.create(conversation=conversation, sender_type=sender, message_type='TEXT',
                                          body=body, metadata=metadata)
        return conversation, card

    def test_a_limit_notice_between_does_not_hide_the_card(self):
        from assistant import sends
        from assistant.service import LIMIT_REPLY
        conversation, card = self._thread(('USER', '¿esto qué es?', {}),
                                          ('AGENT', LIMIT_REPLY, {'ai': True, 'limit': True}))
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no lo pagues', metadata={})
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), 'no lo pagues', said)
        self.assertTrue(out[0])
        self.assertEqual(withdraw.call_args[0][1], [card.pk])

    def test_the_cards_own_code_pasted_again_still_withdraws_another_does_not(self):
        from assistant import sends
        conversation, card = self._thread()
        codes = lambda text: [c for c in ('CODE-A', 'CODE-B') if c in str(text)]
        with mock.patch('assistant.sends.intents_codes', side_effect=codes), \
                mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                                 body='¿esto es estafa? CODE-A', metadata={})
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account),
                                          '¿esto es estafa? CODE-A', said)
            self.assertTrue(out[0])
            other = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                                  body='no lo pagues CODE-B', metadata={})
            self.assertIsNone(sends.withdraw_declined(conversation, SimpleNamespace(account=self.account),
                                                      'no lo pagues CODE-B', other))
        self.assertEqual(withdraw.call_count, 1)

    def test_a_percent_is_never_a_price_level(self):
        from smart_account import watches
        from smart_account.assistant_ops import OpsRefused
        with mock.patch.object(watches, 'operable_account', return_value=object()), \
                mock.patch.object(watches.SmartAccountWatch.objects, 'filter') as found:
            found.return_value.count.return_value = 0
            with self.assertRaises(OpsRefused):
                watches.propose(self.user, said='avísame si Tesla baja 5%', kind='asset_price_below', asset='Tesla',
                                threshold='5%')


def sends_tag(code):
    from assistant import sends
    return sends.code_tag(code)


class RoundThirtyFourTests(FlowBase):
    def test_everyday_ways_to_say_no_and_scam_words(self):
        from assistant import sends
        for said in ('cancel it', 'anula el pago', 'no lo hagas', 'no, no lo hagas',
                     'no hagas ese pago', 'no lo pago', 'mejor no lo pago', 'no pienso pagarlo', 'no lo voy a enviar',
                     'no quiero enviarlo', 'ya no lo quiero', 'me quieren estafar', 'me están estafando',
                     'me estafaron', 'es un estafador', 'dale, no lo voy a pagar', 'ok dale, no lo quiero pagar'):
            self.assertTrue(sends._said_not_to_pay(said), said)
        for said in ('ya pagué la luz, ahora págalo', 'no es estafa, págalo', 'págalo de un golpe'):
            self.assertFalse(sends._said_not_to_pay(said), said)

    def test_the_model_can_withdraw_the_card_above_in_any_wording(self):
        from assistant.engine import Toolbelt, Viewer
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        card = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1'}})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='mmm prefiero que no salga esa plata', metadata={})
        viewer = Viewer(user=self.user, account=self.account, account_type='personal', business_id=None,
                        is_business_owner=False, tz=None)
        with mock.patch('assistant.engine.allowed_destinations', return_value=[]):
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.turn_history = [card, said]
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = belt.withdraw_payment_card()
        self.assertIs(out['ok'], True)
        self.assertIn('retiré esa tarjeta', out['texto'])
        self.assertEqual(withdraw.call_args[0][1], [card.pk])
        self.assertTrue(confirm.busy(belt.result))
        # Nothing above: nothing to withdraw, and it says so.
        belt2_said = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                   body='Hola.', metadata={'ai': True})
        belt.turn_history = [belt2_said, said]
        later = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                              body='cancélalo', metadata={})
        belt.turn_history = [later]
        with mock.patch('assistant.sends.withdraw_cards') as never:
            self.assertIs(belt.withdraw_payment_card()['ok'], False)
        never.assert_not_called()

    def test_a_percent_the_person_wrote_is_never_a_price_level(self):
        from smart_account import watches
        from smart_account.assistant_ops import OpsRefused
        with mock.patch.object(watches, 'operable_account', return_value=object()), \
                mock.patch.object(watches.SmartAccountWatch.objects, 'filter') as found:
            found.return_value.count.return_value = 0
            with self.assertRaises(OpsRefused):
                watches.propose(self.user, said='avísame si Tesla baja 5%', kind='asset_price_below', asset='Tesla',
                                threshold='5')


class CancelarIsPayTests(SimpleTestCase):
    def test_cancelar_is_never_a_word_level_no(self):
        # "cancelar" is "to pay" in much of Latin America: the model reads it under a card, the words never do.
        from assistant import sends
        for said in ('cancélalo', 'cancela esa factura', 'cancela ese pago'):
            self.assertFalse(sends._said_not_to_pay(said), said)


class RoundThirtyFiveTests(FlowBase):
    def test_the_tools_withdrawal_is_answered_in_codes_words(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1'}})
        with mock.patch('assistant.engine.Toolbelt.payments_ready', return_value=True), \
                mock.patch('assistant.sends.withdraw_cards', return_value='signing'):
            reply, _model = self.say('mmm prefiero que no salga esa plata',
                                     call_response('withdraw_payment_card', '{}'),
                                     text_response('Listo, retiré la tarjeta: ya no se puede pagar.'))
        self.assertTrue(reply.body.startswith('Ese pago ya está esperando tu firma: no lo firmes'), reply.body)
        self.assertNotIn('ya no se puede pagar', reply.body)

    def test_a_scanned_cards_own_code_with_no_lo_pagues_withdraws_it(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        card = SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                             body='Preparé este pago.', metadata={'payment_intent': {'id': 's1'}})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='CODE-A no lo pagues, es estafa', metadata={})
        with mock.patch('assistant.sends.intents_codes', side_effect=lambda t: ['CODE-A'] if 'CODE-A' in str(t) else []), \
                mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account),
                                          'CODE-A no lo pagues, es estafa', said)
        self.assertTrue(out[0])
        self.assertEqual(withdraw.call_args[0][1], [card.pk])


class RoundThirtySixTests(FlowBase):
    def _card(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1'}})
        return conversation

    def test_a_payment_after_the_withdrawal_never_rewrites_it(self):
        self._card()
        with mock.patch('assistant.engine.Toolbelt.payments_ready', return_value=True), \
                mock.patch('assistant.sends.withdraw_cards', return_value='signing'):
            reply, _model = self.say('me arrepentí de ese, mejor envíale a @ana',
                                     call_response('withdraw_payment_card', '{}'),
                                     call_response('prepare_payment', json.dumps(
                                         {'rail': 'confio_send', 'recipient': '@ana', 'amount_usd': None})),
                                     text_response('Listo.'))
        self.assertTrue(reply.body.startswith('Ese pago ya está esperando tu firma: no lo firmes'), reply.body)
        self.assertTrue(reply.metadata.get('declined'))

    def test_the_withdrawal_wins_over_a_question_asked_first(self):
        self._card()
        with mock.patch('assistant.engine.Toolbelt.payments_ready', return_value=True), \
                mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            reply, _model = self.say('me arrepentí de ese, mejor envíale a @ana',
                                     call_response('prepare_payment', json.dumps(
                                         {'rail': 'confio_send', 'recipient': '@ana', 'amount_usd': None})),
                                     call_response('withdraw_payment_card', '{}'),
                                     text_response('Listo.'))
        withdraw.assert_called_once()
        self.assertTrue(reply.body.startswith('Listo: retiré esa tarjeta'), reply.body)


class RoundThirtySevenTests(FlowBase):
    def test_the_withdrawal_drops_a_question_asked_earlier_in_the_reply(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant.engine import Toolbelt, Viewer
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        card = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1'}})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no, mejor no salga esa plata', metadata={})
        viewer = Viewer(user=self.user, account=self.account, account_type='personal', business_id=None,
                        is_business_owner=False, tz=None)
        with mock.patch('assistant.engine.allowed_destinations', return_value=[]):
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.turn_history = [card, said]
        belt.result.pending_categorization = {'count': 2}
        belt.result.pending_watch = {'kind': 'asset_price_below'}
        belt.result.rule_proposal = {'id': 'r'}
        belt.result.store_task_started = True
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn'):
            out = belt.withdraw_payment_card()
        self.assertIs(out['ok'], True)
        self.assertIsNone(belt.result.pending_categorization)
        self.assertIsNone(belt.result.pending_watch)
        self.assertIsNone(belt.result.rule_proposal)
        self.assertIn('compra en la tienda', belt.result.payment_refusal)


class RoundThirtyEightTests(FlowBase):
    def test_a_warning_many_messages_back_still_counts(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                      body='me están estafando, no pagues ningún código que te pegue hoy', metadata={})
        for at in range(12):
            SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                          body=f'pregunta {at}', metadata={})
            SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                          body=f'respuesta {at}', metadata={'ai': True})
        last = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='CODE-A', metadata={})
        window = list(conversation.messages.order_by('-created_at')[:16])[::-1]
        belt = SimpleNamespace(turn_history=window)
        self.assertTrue(sends._warned(belt, 'CODE-A'))
        self.assertEqual(sends._last_minutes(window)[-1].pk, last.pk)

    def test_no_pay_chip_or_form_after_a_withdrawal(self):
        from assistant.engine import PAYMENT_CHIP, Toolbelt, Viewer
        viewer = Viewer(user=mock.Mock(pk=1), account=mock.Mock(id=1), account_type='personal', business_id=None,
                        is_business_owner=False, tz=None)
        with mock.patch('assistant.engine.allowed_destinations', return_value=[]):
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.result.declined = True
        for name in ('propose_topup', 'ask_details', 'prepare_payment', 'propose_stock_trade', 'act_here'):
            out = belt.call(name, {})
            self.assertIs(out.get('ok'), False, name)
        self.assertIn('target', PAYMENT_CHIP)


class RoundThirtyNineTests(FlowBase):
    def test_a_card_many_messages_back_is_still_seen(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        tag = sends.code_tag('CODE-X')
        card = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'x1',
                                                                                                    'code': tag}})
        for at in range(10):
            SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                          body=f'pregunta {at}', metadata={})
            SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                          body=f'respuesta {at}', metadata={'ai': True})
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                      body='no pagues este CODE-X', metadata={})
        window = list(conversation.messages.order_by('-created_at')[:16])[::-1]
        self.assertNotIn(card.pk, [m.pk for m in window])
        belt = SimpleNamespace(turn_history=window, viewer=SimpleNamespace(account=self.account))
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            sends._retire_open_cards(belt, 'CODE-X')
        self.assertEqual(withdraw.call_args[0][1], [card.pk])
        self.assertEqual(confirm.served_codes(belt), {tag})


class RoundFortyTests(FlowBase):
    def test_no_pagues_with_the_code_withdraws_its_card_wherever_it_is(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        tag = sends.code_tag('CODE-X')
        card = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'x1',
                                                                                                    'code': tag}})
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                      body='¿y cuánto tengo?', metadata={})
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Tienes US$100.', metadata={'ai': True})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no pagues este CODE-X', metadata={})
        codes = lambda text: ['CODE-X'] if 'CODE-X' in str(text) else []
        with mock.patch('assistant.sends.intents_codes', side_effect=codes), \
                mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account),
                                          'no pagues este CODE-X', said)
        self.assertTrue(out[0])
        self.assertIn('retiré esa tarjeta', out[1])
        self.assertEqual(withdraw.call_args[0][1], [card.pk])
        self.assertEqual(out[2].get('refused_code'), tag)


class RoundFortyOneTests(FlowBase):
    def test_a_scanned_card_above_does_not_hide_the_codes_own_card(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        tag = sends.code_tag('CODE-X')
        own = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                            body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'a',
                                                                                                   'code': tag}})
        scanned = SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                                body='Preparé este pago.', metadata={'payment_intent': {'id': 'b'}})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='no pagues CODE-X', metadata={})
        with mock.patch('assistant.sends.intents_codes', side_effect=lambda t: ['CODE-X'] if 'CODE-X' in str(t) else []), \
                mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn') as withdraw:
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), 'no pagues CODE-X', said)
        self.assertTrue(out[0])
        self.assertEqual(sorted(withdraw.call_args[0][1]), sorted([own.pk, scanned.pk]))

    def test_no_rule_button_after_a_withdrawal(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant.engine import Toolbelt, Viewer
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        card = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True, 'payment_intent': {'id': 'c1'}})
        said = SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                             body='mejor no', metadata={})
        viewer = Viewer(user=self.user, account=self.account, account_type='personal', business_id=None,
                        is_business_owner=False, tz=None)
        with mock.patch('assistant.engine.allowed_destinations', return_value=[]):
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.turn_history = [card, said]
        belt.result.actions = [{'type': 'navigate', 'target': 'smart_account_rule', 'label': 'Revisar y firmar'},
                               {'type': 'navigate', 'target': 'receive', 'label': 'Recibir'}]
        with mock.patch('assistant.sends.withdraw_cards', return_value='withdrawn'):
            belt.withdraw_payment_card()
        self.assertEqual([a['target'] for a in belt.result.actions], ['receive'])


class RoundFortyTwoTests(FlowBase):
    def test_a_reply_carrying_a_code_is_never_an_answer(self):
        pending = {'kind': 'payment', 'step': 'amount', 'user_id': self.user.pk, 'account_id': self.account.id,
                   'reply_id': 'Q', 'lang': 'es', 'data': {'request': {}}}
        said = SimpleNamespace(metadata={}, body='')
        with mock.patch('payment_accounts.payment_intents.find_pix_codes', return_value=['CODE']), \
                mock.patch.object(confirm, 'previous_message', return_value='Q'):
            viewer = SimpleNamespace(user=self.user, account=self.account)
            self.assertIsNone(confirm.answer(SimpleNamespace(), viewer, 'no pagues este CODE 2024', pending, said))

    def test_codes_no_to_a_codes_question_records_the_code(self):
        pending = {'kind': 'payment', 'step': 'yes', 'user_id': self.user.pk, 'account_id': self.account.id,
                   'reply_id': 'Q', 'lang': 'es', 'data': {'request': {'code_tag': 'tag-x'}}}
        said = SimpleNamespace(metadata={}, body='no')
        with mock.patch.object(confirm, 'previous_message', return_value='Q'):
            viewer = SimpleNamespace(user=self.user, account=self.account)
            out = confirm.answer(SimpleNamespace(), viewer, 'no', pending, said)
        self.assertEqual(out[2], {'declined': True, 'refused_code': 'tag-x'})


class RoundFortyThreeTests(FlowBase):
    def test_an_older_paid_card_of_the_code_is_left_out(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        cards = []
        for state, outcome in (('submitted', 'paid'), ('quoted', '')):
            card = SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                                 body='Tarjeta', metadata={'ai': True})
            row = RoundFortyFourTests._row(self, card.pk, state, outcome=outcome)
            card.metadata = {'ai': True, 'payment_intent': {'id': str(row.internal_id)}}
            card.save()
            cards.append(card)
        paid, live = cards
        self.assertEqual([m.pk for m in sends._with_open_rows(self.account, [paid, live])], [live.pk])

    def test_a_refusal_keeps_no_form_beside_it(self):
        from assistant.engine import TurnResult as Result
        result = Result(reply='x')
        result.declined, result.payment_refusal = True, 'No preparé el pago de ese código.'
        result.actions = [{'type': 'form', 'target': 'topup:BOB=500'}, {'type': 'navigate', 'target': 'receive'}]
        kept = [a for a in result.actions if a.get('type') not in ('trade', 'form', 'payment')
                and a.get('target') not in ('payment_intent', 'smart_account_rule', 'ia_plus', 'cuenta_inteligente')]
        self.assertEqual([a['target'] for a in kept], ['receive'])


class RoundFortyFourTests(FlowBase):
    def _row(self, message_id, state, **kw):
        from datetime import timedelta as delta
        from payment_accounts.models import PaymentIntent
        return PaymentIntent.objects.create(
            confio_account=self.account, user=self.user, created_by='assistant', source='pasted_code',
            rail_method_id='br_qr', family=kw.pop('family', 'local_charge'), payee_name='X',
            payee_level='unverified', amount_local=Decimal('10'), currency='BRL', total_usd=Decimal('2'),
            fee_usd=Decimal('0'), estimated_return_usd=Decimal('0'), rate=Decimal('5'),
            expires_at=timezone.now() + delta(minutes=5), display_hash='h', state=state, message_id=message_id, **kw)

    def _card(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        return SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                             body='Tarjeta', metadata={'ai': True})

    def test_a_live_card_withdrawn_beside_a_paid_one_says_both(self):
        from assistant import sends
        paid_card, live_card = self._card(), self._card()
        self._row(paid_card.pk, 'submitted', outcome='paid')
        live = self._row(live_card.pk, 'quoted')
        with mock.patch('payment_accounts.payment_intents.status', return_value=('paid', None)):
            outcome = sends.withdraw_cards(self.account, [paid_card.pk, live_card.pk], [])
        self.assertEqual(outcome, 'withdrawn')
        self.assertTrue(outcome.paid)
        live.refresh_from_db()
        self.assertEqual(live.state, 'cancelled')
        said = sends._withdrawal_answer(outcome, True, 'no lo pagues', 'es')[1]
        self.assertTrue(said.startswith('Listo: retiré esa tarjeta'), said)
        self.assertIn('Otro pago de ese código ya se había hecho', said)

    def test_an_old_quote_beside_a_paid_requote_is_not_a_withdrawal(self):
        from assistant import sends
        card = self._card()
        old = self._row(card.pk, 'expired', state_reason='requoted')
        self._row(card.pk, 'submitted', outcome='paid', supersedes=old)
        with mock.patch('payment_accounts.payment_intents.status', return_value=('paid', None)):
            self.assertEqual(sends.withdraw_cards(self.account, [card.pk], [str(old.internal_id)]), 'paid')


class RoundFortyFiveTests(RoundFortyFourTests):
    def test_the_teams_own_warning_stops_a_code_pasted_alone(self):
        from inbox.schema import get_or_create_support_conversation
        from assistant import sends
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                      body='me llegó este cobro raro', metadata={})
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', message_type='TEXT',
                                      body='Ese código es una estafa: no lo pagues.', metadata={'notice': 'warn-1'})
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', message_type='TEXT',
                                      body='CODE-A', metadata={})
        window = list(conversation.messages.order_by('created_at'))
        self.assertTrue(sends._warned(SimpleNamespace(turn_history=window), 'CODE-A'))

    def test_a_card_waiting_for_its_signature_is_said_beside_the_withdrawal(self):
        from assistant import sends
        signing_card, live_card = self._card(), self._card()
        self._row(signing_card.pk, 'submitted')
        self._row(live_card.pk, 'quoted')
        for message in (signing_card, live_card):
            message.metadata = {'ai': True, 'payment_intent': {'id': 'x', 'code': 'tag'}}
        self.assertEqual(len(sends._with_open_rows(self.account, [signing_card, live_card])), 2)
        with mock.patch('payment_accounts.payment_intents.status', return_value=('awaiting_signature', None)):
            outcome = sends.withdraw_cards(self.account, [signing_card.pk, live_card.pk], [])
        self.assertEqual(outcome, 'withdrawn')
        self.assertIn('no lo firmes', sends._withdrawal_answer(outcome, True, 'no lo pagues', 'es')[1])


class RoundFortySixBase(FlowBase):
    CODE = 'CODE-X'
    _row = RoundFortyFourTests._row

    def _msg(self, conversation, sender, body, metadata=None, **kw):
        return SupportMessage.objects.create(conversation=conversation, sender_type=sender, message_type='TEXT',
                                             body=body, metadata=metadata or {}, **kw)


class RoundFortySixTests(RoundFortySixBase):
    def test_a_payment_made_after_a_lapsed_card_is_said(self):
        # An old quote lapsed, the code was pasted again and paid: "no lo pagues <code>" withdraws the old card and
        # says the newer payment went out.
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        tag = sends.code_tag(self.CODE)
        self._msg(conversation, 'USER', self.CODE)
        m1 = self._msg(conversation, 'AGENT', 'Tarjeta 1', {'ai': True})
        r1 = self._row(m1.pk, 'expired', state_reason='quote_expired')
        m1.metadata = {'ai': True, 'payment_intent': {'id': str(r1.internal_id), 'code': tag}}
        m1.save()
        self._msg(conversation, 'USER', self.CODE)
        m2 = self._msg(conversation, 'AGENT', 'Tarjeta 2', {'ai': True})
        r2 = self._row(m2.pk, 'submitted', outcome='paid')
        m2.metadata = {'ai': True, 'payment_intent': {'id': str(r2.internal_id), 'code': tag}}
        m2.save()
        self._msg(conversation, 'USER', '¿ya llegó?')
        self._msg(conversation, 'AGENT', 'Sí, ya llegó.', {'ai': True})
        no = self._msg(conversation, 'USER', f'es estafa, no lo pagues {self.CODE}')
        with mock.patch('assistant.sends.intents_codes',
                        side_effect=lambda t: [self.CODE] if self.CODE in str(t) else []), \
                mock.patch('payment_accounts.payment_intents.status', return_value=('paid', None)):
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), no.body, no)
        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual((r1.state, r2.state), ('cancelled', 'submitted'))
        self.assertIn('Otro pago de ese código ya se había hecho', out[1])

    def test_an_older_paid_card_stays_out_beside_an_open_one(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        tag = sends.code_tag(self.CODE)
        m1 = self._msg(conversation, 'AGENT', 'Tarjeta 1', {'ai': True})
        r1 = self._row(m1.pk, 'submitted', outcome='paid')
        m1.metadata = {'ai': True, 'payment_intent': {'id': str(r1.internal_id), 'code': tag}}
        m1.save()
        m2 = self._msg(conversation, 'AGENT', 'Tarjeta 2', {'ai': True})
        r2 = self._row(m2.pk, 'quoted')
        m2.metadata = {'ai': True, 'payment_intent': {'id': str(r2.internal_id), 'code': tag}}
        m2.save()
        self._msg(conversation, 'AGENT', 'Otra cosa.', {'ai': True})
        no = self._msg(conversation, 'USER', f'no lo pagues {self.CODE}')
        with mock.patch('assistant.sends.intents_codes',
                        side_effect=lambda t: [self.CODE] if self.CODE in str(t) else []), \
                mock.patch('payment_accounts.payment_intents.status', return_value=('paid', None)):
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), no.body, no)
        r2.refresh_from_db()
        self.assertEqual(r2.state, 'cancelled')
        self.assertTrue(out[1].startswith('Listo: retiré esa tarjeta'))
        self.assertNotIn('Otro pago', out[1])


@override_settings(CONFIO_ASSISTANT_HUMAN_MODE_HOURS=24)
class RoundFortySixTeamTests(RoundFortySixBase):
    def _held_thread_with_card(self):
        from inbox.schema import get_or_create_support_conversation
        from users.models import User
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        staff = User.objects.create_user(username='staff_r46', email='s46@example.com', password='x',
                                         firebase_uid='fb-staff-r46', is_staff=True)
        self._msg(conversation, 'USER', 'ayuda con un cobro')
        self._msg(conversation, 'AGENT', 'Hola, te ayudamos.', sender_user=staff)
        card = self._msg(conversation, 'SYSTEM', 'Escaneaste un QR', {'system_note': True})
        row = self._row(card.pk, 'quoted')
        card.metadata = {'system_note': True, 'payment_intent': {'id': str(row.internal_id)}}
        card.save()
        return conversation, row

    def _ask(self, said):
        conversation, row = self._held_thread_with_card()
        with mock.patch('assistant.engine._openai_post', side_effect=[text_response('Un golpe suele...')]), \
                self.captureOnCommitCallbacks(execute=True):
            service.ask(self.user, self.account, None, self.jwt, said, request_meta=META)
        row.refresh_from_db()
        notes = list(conversation.messages.filter(sender_type='SYSTEM', body__contains='retiré')
                     .values_list('body', flat=True))
        return row, notes

    def test_a_doubt_answered_while_the_team_holds_the_thread_withdraws_the_card(self):
        row, notes = self._ask('¿Cómo sé si un pix es golpe?')
        self.assertEqual(row.state, 'cancelled')
        self.assertEqual(len(notes), 1, notes)

    def test_a_plain_no_while_the_team_holds_the_thread_withdraws_once(self):
        row, notes = self._ask('es golpe, no lo pagues')
        self.assertEqual(row.state, 'cancelled')
        self.assertEqual(len(notes), 1, notes)


class RoundFortySevenTests(RoundFortySixBase):
    def test_an_older_paid_card_stays_out_when_the_open_one_is_right_above(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        tag = sends.code_tag(self.CODE)
        m1 = self._msg(conversation, 'AGENT', 'Tarjeta 1', {'ai': True})
        r1 = self._row(m1.pk, 'submitted', outcome='paid')
        m1.metadata = {'ai': True, 'payment_intent': {'id': str(r1.internal_id), 'code': tag}}
        m1.save()
        self._msg(conversation, 'USER', self.CODE)
        m2 = self._msg(conversation, 'AGENT', 'Tarjeta 2', {'ai': True})
        r2 = self._row(m2.pk, 'quoted')
        m2.metadata = {'ai': True, 'payment_intent': {'id': str(r2.internal_id), 'code': tag}}
        m2.save()
        no = self._msg(conversation, 'USER', f'no lo pagues {self.CODE}')
        with mock.patch('assistant.sends.intents_codes',
                        side_effect=lambda t: [self.CODE] if self.CODE in str(t) else []), \
                mock.patch('payment_accounts.payment_intents.status', return_value=('paid', None)):
            out = sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), no.body, no)
        r2.refresh_from_db()
        self.assertEqual(r2.state, 'cancelled')
        self.assertTrue(out[1].startswith('Listo: retiré esa tarjeta'), out[1])
        self.assertNotIn('Otro pago', out[1])

    def test_a_short_balance_refusal_says_what_is_missing_in_their_language(self):
        from decimal import Decimal as D
        from payment_accounts.shortfall import short_of_dollars
        with mock.patch('payment_accounts.shortfall.dollars_held', return_value=D('2')):
            refusal = short_of_dollars(object(), D('5'))
        fake = SimpleNamespace(payments_ready=lambda: True, result=SimpleNamespace(actions=[]),
                               viewer=SimpleNamespace(account=None, user=object(), request_meta={}))
        for lang, words in (('pt', 'faltam US$3.00'), ('en', 'US$3.00 is missing')):
            with mock.patch('payment_accounts.payment_intents.prepare', side_effect=refusal), \
                    mock.patch('assistant.topup_limits.offered', return_value=True), \
                    mock.patch('assistant.here.forms_for', return_value=['topup']):
                done, text, extra = sends.confirmed(fake, {'request': {'amount_usd': '5'}, 'source': 'assistant'},
                                                    lang)
            self.assertFalse(done)
            self.assertIn(words, text)
            self.assertEqual([a.get('why') for a in extra['actions']], ['shortfall'])


@override_settings(CONFIO_ASSISTANT_HUMAN_MODE_HOURS=24)
class RoundFortySevenTeamTests(RoundFortySixBase):
    def test_the_team_held_withdrawal_line_is_codes_answer_to_that_code(self):
        from inbox.schema import get_or_create_support_conversation
        conversation = get_or_create_support_conversation(self.user, self.account, None)
        tag = sends.code_tag(self.CODE)
        card = self._msg(conversation, 'AGENT', 'Tarjeta', {'ai': True})
        row = self._row(card.pk, 'quoted')
        card.metadata = {'ai': True, 'payment_intent': {'id': str(row.internal_id), 'code': tag}}
        card.save()
        no = self._msg(conversation, 'USER', f'no lo pagues {self.CODE}')
        with mock.patch('assistant.sends.intents_codes',
                        side_effect=lambda t: [self.CODE] if self.CODE in str(t) else []):
            service._withdraw_while_human(self.user, self.account, conversation, no.body, no)
        note = conversation.messages.get(metadata__notice=f'withdrawn:{no.pk}')
        self.assertEqual((note.metadata.get('declined'), note.metadata.get('refused_code')), (True, tag))
        self.assertTrue(confirm._ends(note, 'untagged', tag))


class RoundFortyEightTests(RoundFortySixBase):
    def _conv(self):
        from inbox.schema import get_or_create_support_conversation
        return get_or_create_support_conversation(self.user, self.account, None)

    def _card(self, conversation, state, **kw):
        tag = sends.code_tag(self.CODE)
        message = self._msg(conversation, 'AGENT', 'Tarjeta', {'ai': True})
        row = self._row(message.pk, state, **kw)
        message.metadata = {'ai': True, 'payment_intent': {'id': str(row.internal_id), 'code': tag}}
        message.save()
        return message, row

    def _no(self, conversation, no, shown='paid'):
        with mock.patch('assistant.sends.intents_codes',
                        side_effect=lambda t: [self.CODE] if self.CODE in str(t) else []), \
                mock.patch('payment_accounts.payment_intents.status', return_value=(shown, None)):
            return sends.withdraw_declined(conversation, SimpleNamespace(account=self.account), no.body, no)

    def test_an_older_card_paid_before_its_outcome_was_written_stays_out(self):
        conversation = self._conv()
        self._card(conversation, 'submitted', outcome='')
        self._msg(conversation, 'USER', self.CODE)
        _message, live = self._card(conversation, 'quoted')
        self._msg(conversation, 'AGENT', 'Otra cosa.', {'ai': True})
        out = self._no(conversation, self._msg(conversation, 'USER', f'no lo pagues {self.CODE}'))
        live.refresh_from_db()
        self.assertEqual(live.state, 'cancelled')
        self.assertNotIn('Otro pago', out[1])

    def test_an_older_card_paid_through_a_requote_stays_out(self):
        conversation = self._conv()
        first, _old = self._card(conversation, 'expired', state_reason='requoted')
        self._row(first.pk, 'submitted', outcome='paid')
        self._msg(conversation, 'USER', self.CODE)
        _message, live = self._card(conversation, 'quoted')
        self._msg(conversation, 'AGENT', 'Otra cosa.', {'ai': True})
        out = self._no(conversation, self._msg(conversation, 'USER', f'no lo pagues {self.CODE}'))
        live.refresh_from_db()
        self.assertEqual(live.state, 'cancelled')
        self.assertNotIn('Otro pago', out[1])

    def test_an_older_card_waiting_for_its_signature_is_still_said(self):
        conversation = self._conv()
        self._card(conversation, 'submitted', outcome='')
        self._msg(conversation, 'USER', self.CODE)
        self._card(conversation, 'quoted')
        self._msg(conversation, 'AGENT', 'Otra cosa.', {'ai': True})
        out = self._no(conversation, self._msg(conversation, 'USER', f'no lo pagues {self.CODE}'),
                       shown='awaiting_signature')
        self.assertIn('no lo firmes', out[1])

    def test_the_line_said_when_the_team_took_the_thread_is_codes_answer(self):
        conversation = self._conv()
        result = TurnResult(reply='', declined=True, payment_refusal='No preparé el pago de ese código.')
        result.refused_code = sends.code_tag(self.CODE)
        mine = self._msg(conversation, 'USER', f'no lo pagues {self.CODE}')
        service._say_anyway(conversation, result, 'es', mine)
        note = conversation.messages.get(metadata__notice=f'done:{mine.pk}')
        self.assertEqual(note.metadata.get('refused_code'), result.refused_code)
        self.assertTrue(confirm._ends(note, 'untagged', result.refused_code))
