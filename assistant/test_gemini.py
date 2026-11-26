"""Confío IA on Gemini: the transport (assistant/gemini.py), the fallback to
OpenAI, and keeping the cards a reply promises (engine._keep_card_promise)."""
import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from users.models import Account, User

from . import engine, gemini, service
from .models import AssistantTurn
from .tests import call_response, text_response


def gemini_text(text, **usage):
    return {'candidates': [{'content': {'role': 'model', 'parts': [{'text': text}]}, 'finishReason': 'STOP'}],
            'usageMetadata': {'promptTokenCount': 1000, 'cachedContentTokenCount': 600,
                              'candidatesTokenCount': 80, 'thoughtsTokenCount': 20, **usage}}


class TransportTests(SimpleTestCase):
    def test_items_become_alternating_turns_and_a_call_replays_its_own_part(self):
        part = {'functionCall': {'name': 'get_portfolio', 'args': {}}, 'thoughtSignature': 'sig'}
        out = gemini.contents([
            {'role': 'user', 'content': 'hola'},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': '¿cuánto tengo?'}]},
            {'type': 'reasoning', 'encrypted_content': 'x'},
            {'type': 'function_call', 'call_id': 'c1', 'name': 'get_portfolio', 'arguments': '{}',
             gemini._PART_KEY: part},
            {'type': 'function_call_output', 'call_id': 'c1', 'output': '{"total_usd": "5.00"}'},
            {'type': 'function_call_output', 'call_id': 'c9', 'output': 'texto suelto'},
        ])
        self.assertEqual([c['role'] for c in out], ['user', 'model', 'user'])
        self.assertEqual(len(out[0]['parts']), 2)               # two user messages merged
        self.assertIs(out[1]['parts'][0], part)                 # signature kept for the next step
        self.assertEqual(out[2]['parts'][0]['functionResponse'],
                         {'name': 'get_portfolio', 'response': {'total_usd': '5.00'}})
        self.assertEqual(out[2]['parts'][1]['functionResponse']['response'], {'result': 'texto suelto'})

    def test_tool_choice_effort_and_search_map_to_gemini(self):
        spec = {'type': 'function', 'name': 'navigate', 'parameters': {'type': 'object', 'properties': {}}}
        body = gemini.request_body({'model': 'gemini-4-hydrogen', 'instructions': 'sé breve', 'input': 'hola',
                                    'tools': [spec], 'tool_choice': 'none', 'reasoning': {'effort': 'low'}})
        self.assertEqual(body['systemInstruction']['parts'][0]['text'], 'sé breve')
        self.assertEqual(body['toolConfig']['functionCallingConfig']['mode'], 'NONE')
        self.assertEqual(body['generationConfig']['thinkingConfig'], {'thinkingLevel': 'low'})
        forced = gemini.request_body({'model': 'm', 'input': 'x', 'tools': [spec],
                                      'tool_choice': {'type': 'function', 'name': 'navigate'}})
        self.assertEqual(forced['toolConfig']['functionCallingConfig'],
                         {'mode': 'ANY', 'allowedFunctionNames': ['navigate']})

    def test_answers_calls_citations_and_stops(self):
        shaped = gemini.responses_shape({'candidates': [{'content': {'parts': [
            {'text': 'pensando', 'thought': True},
            {'functionCall': {'name': 'navigate', 'args': {'destination': 'pay_qr'}}},
        ]}, 'finishReason': 'STOP'}]})
        call = shaped['output'][0]
        self.assertEqual((call['type'], call['name'], json.loads(call['arguments'])),
                         ('function_call', 'navigate', {'destination': 'pay_qr'}))
        self.assertEqual(len(shaped['output']), 1)              # the thought never reaches the person

        usage = gemini.responses_shape(gemini_text('hola'))['usage']
        self.assertEqual(usage, {'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 600},
                                 'output_tokens': 100})       # thinking is billed as output
        cut = gemini.responses_shape({'candidates': [{'content': {'parts': [{'text': 'a'}]},
                                                      'finishReason': 'MAX_TOKENS'}]})
        self.assertEqual(cut['incomplete_details'], {'reason': 'max_output_tokens'})
        with self.assertRaises(gemini.GeminiUnavailable):
            gemini.responses_shape({'candidates': [{'finishReason': 'SAFETY'}]})
        with self.assertRaises(gemini.GeminiUnavailable):
            gemini.responses_shape({'promptFeedback': {'blockReason': 'SAFETY'}})
        with self.assertRaises(gemini.GeminiUnavailable):           # an empty STOP falls back too
            gemini.responses_shape({'candidates': [{'content': {'parts': []}, 'finishReason': 'STOP'}]})

    @override_settings(GEMINI_API_KEY='g-key')
    def test_the_key_goes_in_a_header_never_the_url(self):
        with patch('assistant.gemini.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = gemini_text('hola')
            gemini.post({'model': 'gemini-4-hydrogen', 'input': 'hola'}, timeout=5)
        url = post.call_args.args[0]
        self.assertNotIn('g-key', url)
        self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'], 'g-key')
        self.assertEqual(post.call_args.kwargs['timeout'], 5)


@override_settings(GEMINI_API_KEY='g-key', OPENAI_API_KEY='test-key', CONFIO_ASSISTANT_MODEL='gemini-4-hydrogen')
class FallbackTests(SimpleTestCase):
    def test_a_failed_gemini_call_moves_the_turn_to_the_fallback_model(self):
        payload = {'model': 'gemini-4-hydrogen', 'input': [
            {'type': 'function_call', 'call_id': 'c1', 'name': 'x', 'arguments': '{}', gemini._PART_KEY: {'a': 1}}]}
        with patch('assistant.gemini.post', side_effect=gemini.GeminiUnavailable('Gemini 503')), \
                patch('assistant.engine._openai_responses', return_value=text_response('ok')) as openai:
            data = engine._openai_post(payload)
        self.assertEqual(data['_provider_model'], 'gpt-6-luna')
        self.assertEqual(payload['model'], 'gpt-6-luna')       # the next step of the turn stays there
        self.assertNotIn(gemini._PART_KEY, openai.call_args.args[0]['input'][0])

    def test_an_empty_gemini_answer_is_still_metered(self):
        billed = {'input_tokens': 500, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens': 40}
        with patch('assistant.gemini.post', side_effect=gemini.GeminiUnavailable('empty', usage=billed)), \
                patch('assistant.engine._openai_responses', return_value=text_response('ok')):
            data = engine._openai_post({'model': 'gemini-4-hydrogen', 'input': 'x'})
        self.assertEqual(data['_gemini_usage'], ('gemini-4-hydrogen', billed))
        result = engine.TurnResult(reply='')
        engine._meter(result, data, 'gemini-4-hydrogen')
        self.assertEqual(result.models_used, ['gpt-6-luna', 'gemini-4-hydrogen'])
        self.assertGreater(result.google_cost_usd, 0)
        self.assertLess(result.google_cost_usd, result.cost_usd)  # luna's part stays OpenAI's

    def test_a_slow_caller_keeps_its_own_shorter_limit(self):
        with patch('assistant.gemini.post', return_value=text_response('ok')) as post:
            data = engine._openai_post({'model': 'gemini-4-hydrogen', 'input': 'x'}, timeout=5)
        self.assertEqual(post.call_args.kwargs['timeout'], 5)
        self.assertEqual(data['_provider_model'], 'gemini-4-hydrogen')

    def test_json_schema_calls_and_hosted_searches_stay_on_openai(self):
        for extra in ({'text': {'format': {'type': 'json_object'}}}, {'tools': [{'type': 'web_search'}]},
                      {'include': ['web_search_call.action.sources']}):
            payload = {'model': 'gemini-4-hydrogen', 'input': 'x', **extra}
            with patch('assistant.gemini.post') as model, \
                    patch('assistant.engine._openai_responses', return_value=text_response('ok')):
                data = engine._openai_post(payload)
            model.assert_not_called()
            self.assertEqual(data['_provider_model'], 'gpt-6-luna')
        from . import conf
        self.assertEqual(conf.openai_model(), 'gpt-6-luna')  # pets.py posts to OpenAI directly

    @override_settings(CONFIO_ASSISTANT_FALLBACK_MODEL='')
    def test_without_a_fallback_the_turn_is_unavailable(self):
        with patch('assistant.gemini.post', side_effect=gemini.GeminiUnavailable('down')), \
                self.assertRaises(engine.AssistantUnavailable):
            engine._openai_post({'model': 'gemini-4-hydrogen', 'input': 'x'})


@override_settings(GEMINI_API_KEY='g-key', OPENAI_API_KEY='test-key', CONFIO_ASSISTANT_MODEL='gemini-4-hydrogen')
class CardPassTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ana', email='ana@example.com', password='x',
                                             firebase_uid='fb-ana', first_name='Ana')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}
        push = patch('assistant.service.send_support_staff_push')
        push.start()
        self.addCleanup(push.stop)

    def ask(self, body, meta=None):
        return service.ask(self.user, self.account, None, self.jwt, body, screen='Home',
                           request_meta={'HTTP_X_CONFIO_HOME': 'conversation'} if meta is None else meta)

    def gemini_says(self, *replies):
        shaped = []
        for reply in replies:
            if isinstance(reply, tuple):
                name, args = reply
                shaped.append(gemini.responses_shape({'candidates': [{'content': {'parts': [
                    {'functionCall': {'name': name, 'args': args}}]}, 'finishReason': 'STOP'}]}))
            else:
                shaped.append(gemini.responses_shape(gemini_text(reply)))
        return patch('assistant.gemini.post', side_effect=shaped)

    def test_gemini_keeps_navigate_and_its_own_card_needs_no_other_call(self):
        nav = {'destination': 'pay_qr', 'asset': None, 'label': None}
        with self.gemini_says(('navigate', nav), 'En Pagar apuntas la cámara al QR.') as model, \
                patch('assistant.engine._openai_responses') as openai:
            outcome = self.ask('¿cómo pago un QR?')
        self.assertEqual(outcome.actions, [{'type': 'navigate', 'destination': 'pay_qr'}])
        self.assertIn('navigate', [tool.get('name') for tool in model.call_args_list[0].args[0]['tools']])
        openai.assert_not_called()
        turn = AssistantTurn.objects.get()
        self.assertEqual(turn.models_used, ['gemini-4-hydrogen'])
        # The answer step: 400 fresh * 1.50 + 600 cached * 0.075 + 100 out * 7.50 (per 1M); the call step sent none
        self.assertEqual(str(turn.cost_usd), '0.001395')
        self.assertEqual(turn.google_cost_usd, turn.cost_usd)  # all of it billed by Google

    def test_a_promised_card_naming_one_screen_is_made_by_code(self):
        answer = 'Entra a Recibir → Avanzado y copia tu dirección. Te dejo la tarjeta para que vayas directo.'
        with self.gemini_says(answer), patch('assistant.engine._openai_responses') as openai:
            outcome = self.ask('¿cómo recibo USDT?')
        self.assertEqual(outcome.reply_message.body, answer)
        self.assertEqual(outcome.actions, [{'type': 'card', 'destination': 'receive'}])  # a card in the chat
        openai.assert_not_called()
        self.assertIn('navigate:auto', [tool['name'] for tool in AssistantTurn.objects.get().tools])

    def test_an_unclear_promise_goes_to_the_card_model(self):
        answer = 'Puedes recargar o recibir dólares. Puedes tocar cualquiera de estas tarjetas.'
        with self.gemini_says(answer), patch('assistant.engine._openai_responses', return_value=call_response(
                'navigate', '{"destination": "receive", "asset": null, "label": null}')) as cards:
            outcome = self.ask('¿cómo pongo dinero?')
        self.assertEqual(outcome.actions, [{'type': 'card', 'destination': 'receive'}])  # a card, never opened over it
        card = cards.call_args.args[0]
        self.assertEqual(card['model'], 'gpt-6-luna')
        self.assertEqual([tool['name'] for tool in card['tools']], ['navigate'])
        self.assertIn(answer, card['instructions'])
        self.assertEqual(outcome.reply_message.body, answer)

    def test_a_promise_nobody_keeps_is_taken_out_of_the_reply(self):
        answer = 'Puedes recargar desde tu banco.\n\nToca la tarjeta de abajo. Cualquier duda, aquí estoy.'
        with self.gemini_says(answer), patch('assistant.engine._openai_responses', return_value=text_response('')):
            outcome = self.ask('¿cómo pongo dinero?')
        self.assertEqual(outcome.actions, [])
        self.assertEqual(outcome.reply_message.body, 'Puedes recargar desde tu banco.\n\nCualquier duda, aquí estoy.')

    def test_a_bank_card_or_no_promise_runs_nothing_more(self):
        for answer in ('No puedes recargar con tarjeta de crédito ni con tarjeta de débito.', '¡Hola! ¿Qué necesitas?'):
            with self.gemini_says(answer), patch('assistant.engine._openai_responses') as openai:
                outcome = self.ask('hola')
            self.assertEqual((outcome.reply_message.body, outcome.actions), (answer, []))
            openai.assert_not_called()

    def test_when_gemini_is_down_luna_answers_with_navigate(self):
        with patch('assistant.gemini.post', side_effect=gemini.GeminiUnavailable('timeout')), \
                patch('assistant.engine._openai_responses', side_effect=[
                    call_response('navigate', '{"destination": "pay_qr", "asset": null, "label": null}'),
                    text_response('En Pagar apuntas la cámara al QR.'),
                ]) as openai:
            outcome = self.ask('¿cómo pago un QR?')
        self.assertEqual(outcome.reply_message.body, 'En Pagar apuntas la cámara al QR.')
        self.assertEqual(outcome.actions, [{'type': 'navigate', 'destination': 'pay_qr'}])
        self.assertEqual([call.args[0]['model'] for call in openai.call_args_list], ['gpt-6-luna', 'gpt-6-luna'])

    @override_settings(CONFIO_ASSISTANT_MODEL='gpt-6-luna')
    def test_openai_turns_are_unchanged(self):
        with patch('assistant.engine._openai_responses', side_effect=[
                call_response('navigate', '{"destination": "pay_qr", "asset": null, "label": null}'),
                text_response('Te dejé Pagar.')]) as openai:
            outcome = self.ask('abre QR para pagar')
        self.assertEqual(outcome.actions, [{'type': 'navigate', 'destination': 'pay_qr'}])
        self.assertEqual(openai.call_count, 2)

    def test_a_list_or_a_boarding_card_is_never_cut(self):
        answer = 'Aquí va tu lista. Lleva:\n- Pasaporte\n- Tarjeta de embarque\n- Cargador\n\nBuen viaje.'
        with self.gemini_says(answer), patch('assistant.engine._openai_responses') as openai:
            outcome = self.ask('¿qué llevo al aeropuerto?')
        self.assertEqual((outcome.reply_message.body, outcome.actions), (answer, []))
        openai.assert_not_called()

    def test_another_card_keeps_the_sentence_that_points_at_it(self):
        from .engine import Toolbelt, TurnResult, Viewer, _keep_card_promise
        from zoneinfo import ZoneInfo
        result = TurnResult(reply='Te dejé la tarjeta con el mensaje; sale cuando toques Enviar.')
        result.whatsapp_card = True
        belt = Toolbelt(Viewer(user=None, account=None, account_type='personal', business_id=None,
                               is_business_owner=False, tz=ZoneInfo('America/La_Paz'),
                               request_meta={'HTTP_X_CONFIO_HOME': 'conversation'}), result, analyses_left=0)
        belt.card_spec = {'name': 'navigate'}
        with patch('assistant.engine._openai_responses') as openai:
            _keep_card_promise(belt, result)
        self.assertEqual(result.reply, 'Te dejé la tarjeta con el mensaje; sale cuando toques Enviar.')
        self.assertEqual(result.actions, [])
        openai.assert_not_called()

    def test_older_builds_get_no_card_only_the_promise_removed(self):
        answer = 'Entra a Recibir → Avanzado y copia tu dirección. Te dejo la tarjeta para que vayas directo.'
        with self.gemini_says(answer), patch('assistant.engine._openai_responses') as openai:
            outcome = self.ask('¿cómo recibo USDT?', meta={})
        self.assertEqual(outcome.actions, [])
        self.assertEqual(outcome.reply_message.body, 'Entra a Recibir → Avanzado y copia tu dirección.')
        openai.assert_not_called()

    @override_settings(CONFIO_ASSISTANT_MODEL='gpt-6-luna')
    def test_openai_turns_never_lose_a_sentence(self):
        answer = 'Toca la tarjeta de abajo para ver tu saldo.'
        with patch('assistant.engine._openai_responses', return_value=text_response(answer)):
            outcome = self.ask('¿cuánto tengo?')
        self.assertEqual(outcome.reply_message.body, answer)
