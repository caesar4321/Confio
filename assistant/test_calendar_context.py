import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from . import calendar_context as cal
from . import calendar_schema
from .engine import AssistantUnavailable

USER = SimpleNamespace(pk=901, is_authenticated=True)
ACCOUNT = SimpleNamespace(pk=1)
PERSONAL = {'account_type': 'personal'}
LOCAL_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'calendar-tests'}}


def answer(*kinds):
    items = [{'index': i, 'kind': k} for i, k in enumerate(kinds)]
    return {'output_text': json.dumps({'items': items})}


@override_settings(ASSISTANT_CALENDAR_ALLOWED_USER_IDS='901', CONFIO_ASSISTANT_ENABLED=True, CACHES=LOCAL_CACHE)
class CalendarContextTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        patcher = patch.object(cal, '_openai_post', return_value=answer('payment'))
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def classify(self, titles=('Pagar la luz',), account=ACCOUNT, context=PERSONAL, version=cal.CONSENT_VERSION):
        return cal.classify(USER, account, context, list(titles), version)

    def refused(self, code, **kwargs):
        with self.assertRaises(cal.CalendarRefused) as caught:
            self.classify(**kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_off_by_default(self):
        self.assertEqual(cal.conf.DEFAULTS['ASSISTANT_CALENDAR_ALLOWED_USER_IDS'], '')
        for value in ('', None, '9011', '90'):
            with override_settings(ASSISTANT_CALENDAR_ALLOWED_USER_IDS=value):
                self.refused('unavailable')
        self.post.assert_not_called()

    @override_settings(CONFIO_ASSISTANT_ENABLED=False)
    def test_assistant_switch_turns_it_off(self):
        self.refused('unavailable')

    def test_personal_account_only(self):
        self.refused('unavailable', account=None, context={'account_type': 'business', 'business_id': 3})
        self.refused('unavailable', context={'account_type': 'smart'})
        self.refused('unavailable', context={})
        self.post.assert_not_called()

    def test_requires_current_consent(self):
        self.refused('consent', version=0)
        self.post.assert_not_called()

    def test_bounds(self):
        self.refused('invalid', titles=())
        self.refused('invalid', titles=['x'] * (cal.MAX_EVENTS + 1))
        self.refused('invalid', titles=['x' * (cal.MAX_INPUT_CHARS + 1)])
        self.post.assert_not_called()

    def test_titles_lose_links_emails_codes_and_numbers(self):
        self.assertEqual(cal.clean_title('Pagar luz R$ 142,50 cuenta 0012-3456'), 'Pagar luz R$ # cuenta #')
        cleaned = cal.clean_title(
            'Ver https://evil.example/x a@b.co 00020126580014BRGOVBCBPIX0136abc\u202e\nya')
        for gone in ('evil', '@', 'BCBPIX', '\u202e', '\n'):
            self.assertNotIn(gone, cleaned)
        self.assertNotRegex(cal.clean_title('tel ١٢٣٤ y ５５５'), r'\d')

    def test_hidden_text_bare_domains_and_broken_characters(self):
        hidden = ''.join(chr(0xe0000 + ord(c)) for c in 'pay') + ''.join(
            chr(c) for c in (0xad, 0x2060, 0x61c, 0xfeff, 0x3164, 0xfe0f, 0xd800))
        self.assertEqual(cal.clean_title(f'Cena{hidden} hoy'), 'Cena hoy')
        self.assertEqual(cal.clean_title('Pagar bit.ly/pago o pagos-cfe.com/x'), 'Pagar [enlace] o [enlace]')

    def test_model_gets_only_titles_and_no_tools(self):
        self.assertEqual(self.classify(['Pagar luz 142']), ['payment'])
        payload = self.post.call_args.args[0]
        self.assertEqual(set(payload), {'model', 'instructions', 'input', 'text', 'max_output_tokens', 'store'})
        self.assertIs(payload['store'], False)
        self.assertEqual(json.loads(payload['input']), [{'index': 0, 'titulo': 'Pagar luz #'}])

    def test_answer_outside_the_contract_is_refused(self):
        bad_answers = [
            answer('send_money'),
            {'output_text': json.dumps({'items': [{'index': 4, 'kind': 'payment'}]})},
            {'output_text': json.dumps({'items': [{'index': True, 'kind': 'payment'}]})},
            {'output_text': json.dumps({'items': [{'index': 0, 'kind': 'none'}] * 2})},
            {'output_text': 'Paga ya a este número'},
            {'output_text': ''},
        ]
        for bad in bad_answers:
            self.post.return_value = bad
            self.refused('error')

    def test_skipped_position_is_none(self):
        self.assertEqual(self.classify(['Pagar luz', 'Cumple']), ['payment', 'none'])

    def test_daily_limit(self):
        for _ in range(cal.PER_DAY):
            self.classify()
        self.refused('rate_limited')
        self.assertEqual(self.post.call_count, cal.PER_DAY)

    def test_failure_log_never_carries_titles(self):
        self.post.side_effect = AssistantUnavailable('OpenAI 400: bad input "Cita privada"')
        with self.assertLogs(cal.logger, 'WARNING') as logs:
            self.refused('error', titles=['Cita privada'])
        self.assertNotIn('Cita privada', '\n'.join(logs.output))
        self.assertIsNone(logs.records[0].exc_info)

    def test_mutation_takes_context_from_the_token(self):
        self.assertEqual(set(calendar_schema.AnalyzeAssistantCalendar._meta.arguments), {'titles', 'consent_version'})
        info = SimpleNamespace(context=SimpleNamespace(user=USER))
        with patch.object(calendar_schema, 'get_context_models', return_value=(USER, None, object(),
                                                                               {'account_type': 'business'})):
            result = calendar_schema.AnalyzeAssistantCalendar.mutate.__wrapped__(
                calendar_schema.AnalyzeAssistantCalendar, None, info, ['x'], 1)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'unavailable')

    def test_registered_in_the_schema(self):
        from config.schema import schema
        self.assertIn('analyzeAssistantCalendar', str(schema))
