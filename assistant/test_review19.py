"""Review of 2026-11-26: a search result told without searching, a contact typed as a word, «15mi» read as
millions with a scam warning, and Gemini's long answers."""
import json
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

User = get_user_model()


class PromptTests(SimpleTestCase):
    def prompt(self):
        from .prompts import build_system_prompt
        return build_system_prompt(first_name='Luis', account_label='personal', country='VE', screen='Home',
                                   local_now='26/11/2026 15:00', destinations=[])

    def test_amounts_written_loosely_are_thousands(self):
        self.assertIn('«15mi»', self.prompt())
        self.assertIn('«15M» puede ser cualquiera de los dos', self.prompt())
        self.assertIn('son miles (15.000), nunca millones', self.prompt())

    def test_no_scam_warning_without_a_sign(self):
        self.assertIn('Nunca lo llames estafa', self.prompt())
        self.assertIn('Pago Móvil de un amigo es normal', self.prompt())

    def test_short_first_and_said_again_at_the_end(self):
        prompt = self.prompt()
        self.assertNotIn('el largo que la tarea necesite', prompt)
        self.assertNotIn('tu mejor respuesta completa', prompt)
        self.assertIn('también empiezas corto', prompt)
        self.assertTrue(prompt.rstrip().endswith('salvo que pida detalle o un texto largo.'))


class ClaimedUnreadTests(SimpleTestCase):
    def belt(self, offered=('search_whatsapp_messages', 'ask_my_mail')):
        from .engine import TurnResult
        belt = SimpleNamespace(force_tool='', saw_web=False, specs=lambda: [{'name': n} for n in offered])
        return belt, TurnResult(reply='')

    def check(self, reply, tools=(), **kw):
        from .engine import _claimed_unread
        belt, result = self.belt(**kw)
        result.reply = reply
        result.tools = [{'name': name} for name in tools]
        return _claimed_unread(belt, result)

    def test_a_result_told_without_a_search(self):
        said = 'No encontré mensajes de un chat llamado «mio» en lo guardado de WhatsApp (hasta los últimos 30 días).'
        self.assertEqual(self.check(said), 'search_whatsapp_messages')
        self.assertEqual(self.check('En tu correo encontré la factura de la luz.'), 'ask_my_mail')
        self.assertEqual(self.check('Não encontrei mensagens da Ana no seu WhatsApp.'), 'search_whatsapp_messages')

    def test_not_after_a_read_nor_for_what_is_only_offered(self):
        said = 'No encontré mensajes de «mio» en tu WhatsApp.'
        self.assertEqual(self.check(said, tools=['search_whatsapp_messages']), '')
        self.assertEqual(self.check(said, tools=['ask_my_mail:denied']), '')
        self.assertEqual(self.check(said, offered=()), '')  # nothing to search with: not run again
        for plain in ('Puedo buscar en tus chats de WhatsApp de los últimos 30 días.',
                      'No encontré tu pago en el historial; si lo enviaste por WhatsApp, mándame el comprobante aquí.',
                      'No encontré a Ana entre tus contactos de Confío; invítala por WhatsApp.',
                      'Este chat es para ayudarte; no encontré ese movimiento en tu cuenta.',
                      'Não encontrei seu pagamento; fale com o suporte pelo WhatsApp.',
                      'No encontré una cuenta con ese correo.', 'Tu correo tiene que estar verificado.',
                      'No encontré el mensaje de error que mencionas; mándame una captura, o escríbenos por WhatsApp.',
                      'No hay forma de pagar por WhatsApp.', 'Puedo leer los correos de tu Gmail conectado.',
                      'Tu correo electrónico es necesario para encontrar tu cuenta.'):
            self.assertEqual(self.check(plain), '', plain)


class ClaimedUnreadTurnTests(TestCase):
    def test_runs_again_made_to_search(self):
        from users.models import Account

        from .engine import Viewer, run_turn
        user = User.objects.create_user(username='cu1', email='cu1@example.com', password='x', firebase_uid='fb-cu1')
        account = Account.objects.create(user=user, account_type='personal', account_index=0)
        viewer = Viewer(user=user, account=account, account_type='personal', business_id=None,
                        is_business_owner=False, tz=ZoneInfo('UTC'))

        def message(text):
            return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
        invented = message('No encontré mensajes de un chat llamado «mio» en lo guardado de WhatsApp.')
        search = {'output': [{'type': 'function_call', 'name': 'search_whatsapp_messages', 'call_id': 'a',
                              'arguments': json.dumps({'chat': 'mio', 'words': None, 'days': None})}]}
        found = {'ok': True, 'nota': 'n', 'mensajes': [{'chat': 'Mio', 'de': 'contacto', 'cuando': 'hace 2 h',
                                                        'texto': 'hola'}], '_grant': 'g'}
        with mock.patch('assistant.engine._openai_post', side_effect=[invented, search, message('Mio: «hola».')]) as post, \
                mock.patch('whatsapp_link.assistant_tool.ready', return_value=True), \
                mock.patch('whatsapp_link.assistant_tool.history_call', return_value=found):
            result = run_turn(viewer, [SimpleNamespace(sender_type='USER', body='Hay un contacto llamado mio',
                                                       metadata={})],
                              first_name='Luis', account_label='personal', country='VE', analyses_left=0,
                              reserve_analysis=lambda: False)
        self.assertEqual(post.call_args_list[1].args[0]['tool_choice'],
                         {'type': 'function', 'name': 'search_whatsapp_messages'})
        self.assertEqual(result.reply, 'Mio: «hola».')
        self.assertIn('search_whatsapp_messages', [t['name'] for t in result.tools])
        system = post.call_args_list[1].args[0]['instructions']
        self.assertIn('Busca con search_whatsapp_messages', system)
        self.assertNotIn('Llama get_portfolio', system)


class ContactAsWordTests(SimpleTestCase):
    def test_a_word_in_no_message_is_tried_as_the_chat_name(self):
        from whatsapp_link import assistant_tool
        line = {'chat': 'charcuteria', 'de': 'contacto', 'texto': 'Mano si te paso 15mi', 'at': 0}
        calls = []

        def history(link, *, chat=None, words=None, days=None):
            calls.append((chat, words))
            return ([], True) if words else ([line], True)
        link = SimpleNamespace(grant='g')
        with mock.patch.object(assistant_tool, '_link', return_value=link), \
                mock.patch.object(assistant_tool.service, 'history', side_effect=history):
            out = assistant_tool.history_call(SimpleNamespace(), chat_name=None, words='Charcutería')
        self.assertEqual(calls, [(None, 'Charcutería'), ('Charcutería', None)])
        self.assertEqual(out['mensajes'][0]['chat'], 'charcuteria')
        self.assertIn('coincide con el nombre de uno o más chats', out['nota'])

    def test_not_when_a_chat_was_named_or_words_were_found(self):
        from whatsapp_link import assistant_tool
        calls = []

        def history(link, *, chat=None, words=None, days=None):
            calls.append((chat, words))
            return [], True
        with mock.patch.object(assistant_tool, '_link', return_value=SimpleNamespace(grant='g', linked_at=None,
                                                                                     history_at=None)), \
                mock.patch.object(assistant_tool.service, 'history', side_effect=history), \
                mock.patch.object(assistant_tool, '_nothing_note', return_value='nada'):
            assistant_tool.history_call(SimpleNamespace(), chat_name='Ana', words='sábado')
        self.assertEqual(calls, [('Ana', 'sábado')])
