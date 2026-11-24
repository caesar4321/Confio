"""The click judge's first reader, Google's Decisions API: it settles a click only when it is confident;
anything else goes to the judge model."""
from types import SimpleNamespace
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from agent_tasks import agent

TASK = SimpleNamespace(site='loja.com.br', country='BR', goal='chocolate', user_id=None)
PAGE = SimpleNamespace(url='https://loja.com.br/checkout', title='Checkout', text='Total R$ 9,00', elements=[],
                       look=lambda element: b'jpeg-bytes')
BUTTON = {'tag': 'button', 'label': 'Continuar'}


def answered(choice, confidence, status=200):
    response = mock.Mock(status_code=status)
    response.json.return_value = {'answers': {'verdict': {'type': 'choice', 'choice': choice, 'confidence': confidence}},
                                  'usage': {'total_input_tokens': 2000}}
    return response


@override_settings(GEMINI_API_KEY='test-key')
class DecisionTests(SimpleTestCase):
    def judge(self, decision, gpt=('verdict', {'verdict': 'account', 'why': 'gpt'})):
        with mock.patch('agent_tasks.agent.requests.post', **decision) as post, \
                mock.patch('agent_tasks.agent._call', return_value=gpt) as call:
            meter = agent.Meter()
            got = agent.judge(TASK, PAGE, BUTTON, meter)
        return got, post, call, meter

    def test_a_confident_answer_settles_the_click_alone(self):
        (verdict, why), post, call, meter = self.judge({'return_value': answered('places_order', 0.98)})
        self.assertEqual(verdict, 'places_order')
        call.assert_not_called()
        body = post.call_args.kwargs['json']
        self.assertEqual(body['model'], 'gemini-decision-1')
        self.assertEqual(post.call_args.kwargs['headers'], {'x-goog-api-key': 'test-key'})
        self.assertEqual(set(body['questions']['verdict']['criteria']), set(agent.VERDICTS))
        self.assertEqual(body['input'][1]['type'], 'image')   # the boxed picture goes with it
        self.assertGreater(meter.usd, 0)

    def test_not_confident_unsure_or_failed_goes_to_the_judge_model(self):
        for decision in ({'return_value': answered('safe', 0.76)}, {'return_value': answered('unsure', 0.99)},
                         {'return_value': answered('nonsense', 0.99)}, {'return_value': answered('safe', 0.99, 400)},
                         {'return_value': answered('safe', 0.99, 429)},
                         {'side_effect': requests.Timeout()},
                         {'return_value': answered('safe', 98)}, {'return_value': answered('safe', float('inf'))},
                         {'return_value': answered('safe', True)}, {'return_value': answered('safe', None)}):
            with self.subTest(decision=decision):
                (verdict, why), post, call, _ = self.judge(decision)
                self.assertEqual((verdict, why), ('account', 'gpt'))
                call.assert_called_once()

    def test_a_token_count_out_of_range_never_crashes_the_step(self):
        response = answered('safe', 0.99)
        response.json.return_value['usage'] = {'total_input_tokens': float('inf')}
        (verdict, why), post, call, _ = self.judge({'return_value': response})
        self.assertEqual((verdict, why), ('account', 'gpt'))

    def test_off_or_without_a_key_only_the_judge_model_reads(self):
        with self.settings(GEMINI_API_KEY=''):
            (verdict, _), post, call, _ = self.judge({'return_value': answered('safe', 0.99)})
        post.assert_not_called()
        self.assertEqual(verdict, 'account')
        with mock.patch('agent_tasks.conf.get', side_effect=lambda key: '' if key == 'AGENT_TASKS_DECISION_MODEL'
                        else agent.conf.DEFAULTS.get(key)):
            (verdict, _), post, call, _ = self.judge({'return_value': answered('safe', 0.99)})
        post.assert_not_called()
