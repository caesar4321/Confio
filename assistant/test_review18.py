"""Review 2026-11-26: the yes to «¿Te aviso?» joins in code, the trade question
follows the newest message's language, and a balance with no address says why."""
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from users.models import User
from users.models_rail_waitlist import LocalRailWaitlistEntry


class NewestMessageLanguageTests(SimpleTestCase):
    def test_the_newest_message_decides_when_it_can(self):
        from .confirm import language
        earlier = ["Let's buy one more dollar of Tesla.", '1.02', "Let's buy one dollar of Tesla."]
        self.assertEqual(language(['Vamos a vender todo Tesla.', *earlier]), 'es')
        self.assertEqual(language(['Sí', *earlier]), 'es')

    def test_portuguese_stays_portuguese(self):
        from .confirm import language
        for texts in (['Vamos vender tudo da Tesla', 'quero vender'],
                      ['Vamos vender todas', 'Quero vender a Tesla', 'obrigado'],
                      ['Vende todo o Tesla', 'Quero vender Tesla'],
                      ['Agora vende todas', 'quero vender Tesla']):
            self.assertEqual(language(texts), 'pt', texts)

    def test_a_yes_that_says_me(self):
        from .confirm import is_save_yes
        for text in ('sí, me avisas', 'Sim, me avisa', 'si me anotas', 'yes, notify me'):
            self.assertTrue(is_save_yes(text, 'notice'), text)
        for text in ('me', 'me avisas cuando?', 'no me avises'):
            self.assertFalse(is_save_yes(text, 'notice'), text)

    def test_a_tool_only_answer_gets_codes_line(self):
        from .engine import NOTICE_LEAD, TurnResult, _finish
        result = TurnResult(reply='')
        result.pending_watch = {'notice_rail': 'bo_qr'}
        self.assertEqual(_finish(result).reply, NOTICE_LEAD)

    def test_a_bare_number_or_name_keeps_the_conversation_language(self):
        from .confirm import language
        self.assertEqual(language(['1.02', "Let's buy one dollar of Tesla."]), 'en')
        self.assertEqual(language(['Tesla', 'I want to buy Tesla']), 'en')
        self.assertEqual(language(['Add it to my todo list', 'I want to buy Tesla']), 'en')
        self.assertEqual(language(['1.02']), 'es')
        self.assertEqual(language([]), 'es')


class NoticeYesTests(TestCase):
    def setUp(self):
        cache.clear()
        from inbox.models import SupportConversation
        from users.models import Account
        self.user = User.objects.create_user(username='nt1', email='nt1@example.com', password='x',
                                             firebase_uid='fb-nt1')
        self.account = Account.objects.create(user=self.user, account_type='personal')
        self.conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')

    def viewer(self):
        from .engine import Viewer
        return Viewer(user=self.user, account=self.account, account_type='personal', business_id=None,
                      is_business_owner=False, tz=ZoneInfo('UTC'), request_meta={})

    def offer_and_answer(self, text):
        from . import service
        from .service import _append
        reply = _append(self.conversation, sender_type='AGENT', body='… ' + service.watch_confirmation_question(
            {'notice_rail': 'bo_qr', 'lang': 'es'}), metadata={'ai': True})
        draft = {'notice_rail': 'bo_qr', 'rail_name': 'QR', 'lang': 'es', 'user_id': self.user.pk,
                 'reply_id': reply.id}
        answer = _append(self.conversation, sender_type='USER', sender_user=self.user, body=text,
                         metadata={'modality': 'TEXT'})
        return service.confirm_pending_watch(self.conversation, self.viewer(), text, draft, answer)

    @override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS='')
    def test_a_bare_si_joins(self):
        for text in ('Si', 'sí, avísame'):
            LocalRailWaitlistEntry.objects.all().delete()
            joined, said = self.offer_and_answer(text)
            self.assertEqual(joined, 1, text)
            self.assertIn('te aviso cuando esté disponible', said)
            self.assertTrue(LocalRailWaitlistEntry.objects.filter(user=self.user, rail_id='send_bo_qr').exists())

    @override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS='')
    def test_a_no_or_another_question_does_not(self):
        joined, said = self.offer_and_answer('no')
        self.assertEqual((joined, said), (0, 'Listo, no te anoté.'))
        self.assertIsNone(self.offer_and_answer('¿y cuándo?'))
        self.assertFalse(LocalRailWaitlistEntry.objects.exists())

    @override_settings(BOLIVIA_QR_SEND_ENABLED=True, BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9')
    def test_opened_meanwhile_joins_nothing(self):
        joined, said = self.offer_and_answer('Si')
        self.assertEqual(joined, 0)
        self.assertIn('actualiza Confío', said)   # no app version sent: only a newer app has it
        self.assertFalse(LocalRailWaitlistEntry.objects.exists())

    @override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS='')
    def test_an_unreadable_state_is_never_called_open(self):
        with mock.patch('assistant.pay_rails.state', return_value=''):
            joined, said = self.offer_and_answer('Si')
        self.assertEqual(joined, 0)
        self.assertIn('No pude anotarte', said)
        self.assertFalse(LocalRailWaitlistEntry.objects.exists())

    def test_the_offer_line_asks_the_model_to_call_the_tool(self):
        from . import pay_rails
        line = pay_rails._line(pay_rails.BY_KEY['bo_qr'], 'off')
        self.assertIn('llama `notify_rail` (`bo_qr`)', line)
        self.assertIn('No escribas tú «¿Te aviso?»', line)


class NoAddressPortfolioTests(SimpleTestCase):
    def test_says_why_and_never_blames_a_tool(self):
        from . import engine
        viewer = SimpleNamespace(is_employee=False, account=SimpleNamespace(bsc_address=None, created_at=None),
                                 tz=ZoneInfo('UTC'), user=SimpleNamespace(pk=1))
        with mock.patch.object(engine, '_ondo_decision', return_value=(True, '')), \
                mock.patch.object(engine, '_legacy_cusd', return_value=None), \
                mock.patch.object(engine, 'month_summary_data', return_value={}), \
                mock.patch.object(engine, '_plus_net_apy', return_value='3%'):
            out = engine.portfolio_data(viewer)
        self.assertEqual(out['confio_dollar_usd'], 'desconocido')
        self.assertIn('red nueva', out['motivo_saldos'])
        self.assertIn('Inicio', out['motivo_saldos'])
        self.assertIn('No digas que es 0', out['motivo_saldos'])

    def test_the_prompt_forbids_talking_about_tools(self):
        from .prompts import SYSTEM_PROMPT
        self.assertIn('Nunca hables de «la herramienta»', SYSTEM_PROMPT)
