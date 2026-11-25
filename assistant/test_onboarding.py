"""First steps done in the chat: verification as a card, no walks out of the
chat where a card exists, the top-up form when a first trade has no dollars,
guide chips said as the person's words, labels in their language, Comprar only
where it sells, and the Colombia pauses only about Colombia (2026-11-25)."""
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings

from users.models import User

from .engine import Toolbelt, TurnResult, Viewer, allowed_destinations

CONVERSATION = {'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.2'}


def _viewer(user, meta=None, account=None):
    return Viewer(user=user, account=account, account_type='personal', business_id=None, is_business_owner=False,
                  tz=ZoneInfo('UTC'), request_meta=CONVERSATION if meta is None else meta)


class VerificationCardGuidanceTests(TestCase):
    def test_identity_notes_hand_the_card_never_a_menu_path(self):
        from .prompts import IDENTITY_NOTES
        for key, note in IDENTITY_NOTES.items():
            self.assertNotIn('Perfil →', note, key)
        for key in ('unverified', 'pending', 'rejected', 'other_country'):
            self.assertIn('`verification`', IDENTITY_NOTES[key], key)

    def test_the_chat_prompt_says_every_verify_first_leaves_the_card(self):
        from .prompts import build_system_prompt
        prompt = build_system_prompt(first_name='Ana', account_label='personal', country='MX', screen='Home',
                                     local_now='now', destinations=['verification', 'receive'], conversation=True,
                                     identity='unverified')
        self.assertIn('deja en la misma respuesta la tarjeta de Verificación', prompt)
        self.assertIn('nunca le digas que cree una cuenta', prompt)
        self.assertIn('`start_store_task`, úsala', prompt)
        self.assertIn('sigue la sección «Pagar en moneda local»', prompt)

    def test_verification_note_guidance_points_to_the_card(self):
        from .verification_note import GUIDANCE
        self.assertNotIn('Perfil →', GUIDANCE)
        self.assertIn('`verification`', GUIDANCE)

    def test_ios_says_not_in_this_app(self):
        from .prompts import faq_text
        self.assertIn('no digas «en Confío»', faq_text(dex=False))


class WalksInTheChatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='walks', email='w@example.com', password='x',
                                             firebase_uid='fb-walks')

    def _walks(self, meta, destinations):
        belt = Toolbelt(_viewer(self.user, meta), TurnResult(reply=''), analyses_left=0)
        belt.destinations = destinations
        with patch('assistant.guide.walks_on_this_build', return_value=True), \
                patch('assistant.guide.walk_trail', return_value=('stop',)):
            return belt._walks()

    def test_no_walk_out_of_the_chat_where_its_card_exists(self):
        from .guide import WALKS
        walks = self._walks(CONVERSATION, ['verification', 'send', 'top_up'])
        self.assertNotIn('verify', walks)
        self.assertNotIn('send', walks)
        self.assertNotIn('top_up', walks)
        self.assertIn('invite', walks)          # no `invite` card for this person: the walk stays
        # The five-tab app keeps every walk.
        self.assertEqual(self._walks({'HTTP_X_CONFIO_VERSION': '5.4.2'}, ['verification', 'send']), list(WALKS))


class LabelsInTheirLanguageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='labels', email='l@example.com', password='x',
                                             firebase_uid='fb-labels')

    def _belt(self, said):
        belt = Toolbelt(_viewer(self.user), TurnResult(reply=''), analyses_left=0)
        belt.last_user_message = said
        return belt

    def test_show_me_in_portuguese(self):
        belt = self._belt('como eu pago com Pix? você pode me mostrar')
        belt._walk_keys = ['pay_qr']
        self.assertEqual(belt.show_steps('pay_qr'), {'ok': True, 'boton': 'Mostre-me'})
        self.assertEqual(belt.result.actions[0]['label'], 'Mostre-me')
        belt = self._belt('¿cómo pago con un QR?')
        belt._walk_keys = ['pay_qr']
        self.assertEqual(belt.show_steps('pay_qr')['boton'], 'Muéstrame')

    def test_a_card_carries_its_portuguese_name_and_spanish_stays_the_apps(self):
        belt = self._belt('quero receber dólares, você pode me ajudar')
        belt.navigate('receive', open_now=False)
        self.assertEqual(belt.result.actions, [{'type': 'card', 'destination': 'receive', 'target': 'receive',
                                                'label': 'Receber dinheiro'}])
        belt = self._belt('quiero recibir dólares')
        belt.navigate('receive', open_now=False)
        self.assertEqual(belt.result.actions, [{'type': 'card', 'destination': 'receive'}])


class ComprarWhereItSellsTests(TestCase):
    def test_comprar_screens_only_where_comprar_sells(self):
        user = User.objects.create_user(username='comprar', email='c@example.com', password='x',
                                        firebase_uid='fb-comprar')
        with patch('security.geo.country_of', return_value='MX'):
            with override_settings(MARKETPLACE_CLOSED_COUNTRIES='MX'):
                keys = allowed_destinations(_viewer(user))
                for key in ('comprar', 'my_store', 'market_orders'):
                    self.assertNotIn(key, keys)
            with override_settings(MARKETPLACE_CLOSED_COUNTRIES=''):
                self.assertIn('comprar', allowed_destinations(_viewer(user)))

    def test_the_description_keeps_online_stores_out(self):
        from .destinations import DESTINATIONS
        self.assertIn('No es para tiendas en línea', DESTINATIONS['comprar'])


class ColombiaNoteScopeTests(TestCase):
    def test_outside_colombia_the_pause_is_only_for_colombia(self):
        from . import rails
        with override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=['CO']):
            mexico = rails.colombia_pause_note('MX')
            colombia = rails.colombia_pause_note('CO')
        self.assertIn('valen solo si la persona vive en Colombia', mexico)
        self.assertNotIn('valen solo si', colombia)
        self.assertIn('PSE', colombia)
        with override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=[]):
            self.assertEqual(rails.colombia_pause_note('MX'), '')


class GuideChipsInTheChatTests(TestCase):
    def test_walks_become_the_persons_words_and_verification_keeps_its_chip(self):
        from .guide import INVEST_OPTIONS, STEPS, in_chat_chips
        top_up = in_chat_chips('top_up', STEPS['top_up'].chips)
        self.assertEqual((top_up[0].label, top_up[0].kind, top_up[0].trail), ('Quiero recargar', 'ask', ()))
        self.assertEqual(top_up[1].kind, 'dismiss')
        self.assertEqual(in_chat_chips('send', STEPS['send'].chips)[0].label, 'Quiero enviarle dinero a alguien')
        options = in_chat_chips('invest', (INVEST_OPTIONS['stocks'],))
        self.assertEqual((options[0].label, options[0].kind, options[0].answer),
                         ('Quiero comprar acciones', 'ask', 'stocks'))
        self.assertEqual(in_chat_chips('verify', STEPS['verify'].chips), STEPS['verify'].chips)

    def test_current_says_them_only_where_the_chat_is_inicio(self):
        from . import guide
        user = User.objects.create_user(username='guide-chat', email='g@example.com', password='x',
                                        firebase_uid='fb-guide-chat')
        with patch('assistant.guide.current_key', return_value='send'), \
                patch('assistant.guide._text', return_value='¿Te muestro cómo enviarle a alguien?'):
            chat = guide.current(_viewer(user), CONVERSATION)
            tabs = guide.current(_viewer(user, {}), {})
        self.assertEqual(chat.chips[0].kind, 'ask')
        self.assertEqual(tabs.chips[0].kind, 'navigate')

    def test_top_up_brief_in_the_chat_does_not_promise_a_walk(self):
        from .guide import CHAT_BRIEFS
        self.assertNotIn('paso a paso', CHAT_BRIEFS['top_up'])


class FirstTradeWithoutDollarsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='nodollars', email='n@example.com', password='x',
                                             firebase_uid='fb-nodollars')

    def _belt(self):
        belt = Toolbelt(_viewer(self.user), TurnResult(reply=''), analyses_left=0)
        belt.payments_ready = lambda: True
        return belt

    def test_nothing_to_buy_with_refuses_the_amount_and_leaves_the_form(self):
        from . import trades
        belt = self._belt()
        with patch('payment_accounts.shortfall.dollars_held', return_value=Decimal('0')), \
                patch('assistant.trades._account_address', return_value=''), \
                patch('assistant.sends._topup_form', side_effect=lambda b, actions: actions.append(
                    {'type': 'form', 'target': 'topup', 'why': 'shortfall', 'label': 'Recargar'}) or True):
            out = trades._no_dollars(belt)
        self.assertFalse(out['ok'])
        self.assertIn('formulario de recarga', out['motivo'])
        self.assertEqual(belt.result.actions[0]['target'], 'topup')
        with patch('payment_accounts.shortfall.dollars_held', return_value=Decimal('25')), \
                patch('assistant.trades._account_address', return_value=''):
            self.assertIsNone(trades._no_dollars(self._belt()))
        # Unknown balance: no claim, the amount step goes on.
        with patch('payment_accounts.shortfall.dollars_held', return_value=None):
            self.assertIsNone(trades._no_dollars(self._belt()))

    def test_account_dollars_count_while_hands_off_is_on(self):
        from . import trades
        with patch('payment_accounts.shortfall.dollars_held', side_effect=[Decimal('0'), Decimal('40')]), \
                patch('assistant.trades._account_address', return_value='0xacc'):
            self.assertEqual(trades._dollars(self._belt().viewer), Decimal('40'))

    def test_short_card_says_what_is_missing_with_the_form(self):
        from . import trades
        actions = []
        with patch('payment_accounts.shortfall.dollars_held', return_value=Decimal('5')), \
                patch('assistant.trades._account_address', return_value=''), \
                patch('assistant.sends._topup_form', side_effect=lambda b, a: a.append({'target': 'topup'}) or True):
            note = trades._short_note(self._belt(), Decimal('20'), 'es', actions)
            pt = trades._short_note(self._belt(), Decimal('20'), 'pt', [])
        self.assertIn('te faltan US$15.00', note)
        self.assertIn('formulario de abajo', note)
        self.assertEqual(actions, [{'target': 'topup'}])
        self.assertIn('faltam US$15.00', pt)
        with patch('payment_accounts.shortfall.dollars_held', return_value=Decimal('50')), \
                patch('assistant.trades._account_address', return_value=''):
            self.assertEqual(trades._short_note(self._belt(), Decimal('20'), 'es', []), '')

    def test_the_paywall_keeps_its_offer_and_adds_the_top_up(self):
        from types import SimpleNamespace

        from . import trades
        belt = self._belt()
        route = SimpleNamespace(code='paywall', facts={})
        with patch('smart_account.hands_off.enabled', return_value=True), \
                patch('smart_account.hands_off.route', return_value=route), \
                patch('smart_account.relay_trades.asset_token', return_value='0xtoken'), \
                patch('assistant.trades._conversation_id', return_value=None), \
                patch('payment_accounts.shortfall.dollars_held', return_value=Decimal('0')), \
                patch('assistant.trades._account_address', return_value=''), \
                patch('assistant.sends._topup_form', side_effect=lambda b, a: a.append({'target': 'topup'}) or True):
            done, reply, extra = trades._hands_off(
                belt, {'side': 'buy', 'ticker': 'AAPL', 'amount': '20.00', 'kind': 'stock'}, 'es',
                signed_card={'type': 'trade'}, diy={'screen': 'BuyStock', 'params': {'ticker': 'AAPL'}})
        self.assertTrue(done)
        self.assertIn('Cuenta inteligente', reply)
        self.assertIn('te faltan US$20.00', reply)
        self.assertEqual([a.get('type') or a.get('target') for a in extra['actions']],
                         ['trade_offer', 'trade', 'topup'])


class FirstUseNoteTests(TestCase):
    def test_how_to_start_is_not_a_reason(self):
        from .first_use import spec
        self.assertIn('pregunta cómo empezar', spec()['description'])


class LanguageNoteTests(TestCase):
    def test_a_portuguese_message_is_named_for_the_model(self):
        from .engine import language_note
        user = User.objects.create_user(username='lang', email='lang@example.com', password='x',
                                        firebase_uid='fb-lang')
        belt = Toolbelt(_viewer(user), TurnResult(reply=''), analyses_left=0)
        belt.last_user_message = 'quero receber dólares, você pode me ajudar'
        self.assertIn('contesta todo en portugués', language_note(belt))
        belt.last_user_message = 'quiero recibir dólares'
        self.assertEqual(language_note(belt), '')


class RefusedPurchaseVerificationCardTests(TestCase):
    """A purchase refused before anyone verified the person leaves the Verificación card."""

    def _belt(self):
        n = User.objects.count()
        user = User.objects.create_user(username=f'refused-buy-{n}', email=f'rb{n}@example.com', password='x',
                                        firebase_uid=f'fb-refused-buy-{n}')
        belt = Toolbelt(_viewer(user), TurnResult(reply=''), analyses_left=0)
        belt.destinations = ['verification', 'receive']
        belt.store_tasks_ready = lambda: True
        belt.payment_texts = ['quiero comprar algo en Amazon']
        return belt

    def _start(self, belt, identity, minor=None):
        refused = ({'ok': False, 'motivo': 'Verifica tu identidad en Confío para que pueda comprar por ti.'}, None)
        with patch('agent_tasks.assistant_tool.call', return_value=refused), \
                patch('assistant.engine._identity_status', return_value=identity), \
                patch('security.minors.minor_refusal', return_value=minor):
            return belt.start_store_task(store='amazon.com.mx')

    def test_unverified_gets_the_card(self):
        belt = self._belt()
        out = self._start(belt, 'unverified')
        self.assertIn('tarjeta', out)
        self.assertEqual(belt.result.actions, [{'type': 'card', 'destination': 'verification'}])

    def test_verified_or_minor_gets_no_card(self):
        for identity, minor in (('verified', None), ('in_review', None), ('unverified', 'Debes tener 18 años.')):
            belt = self._belt()
            out = self._start(belt, identity, minor)
            self.assertNotIn('tarjeta', out)
            self.assertEqual(belt.result.actions, [])


class PaymentAnswersStayInTheChatTests(TestCase):
    def test_prompt_keeps_payments_in_the_chat_and_gives_the_first_step(self):
        from .prompts import GUIDE_CONVERSATION_NOTE, build_system_prompt
        prompt = build_system_prompt(first_name='Ana', account_label='personal', country='MX', screen='Home',
                                     local_now='now', destinations=['verification', 'send'], conversation=True,
                                     identity='unverified')
        self.assertIn('no lleva tarjeta de pantalla: ni Enviar ni Pagar', prompt)
        self.assertIn('sigue la sección «Pagar en moneda local»', prompt)
        self.assertIn('no le devuelvas la pregunta', prompt)
        self.assertIn('no le devuelvas la pregunta', GUIDE_CONVERSATION_NOTE)
