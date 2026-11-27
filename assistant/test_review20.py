"""Review of 2026-11-26 night: a screen claimed by its verb and never opened, a card promised in
English, and a photo follow-up that could not search."""
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from users.models import User

from .engine import Toolbelt, TurnResult, Viewer


def _belt(meta=None):
    user, _ = User.objects.get_or_create(username='rv20', defaults={'phone_country': 'VE'})
    viewer = Viewer(user=user, account=None, account_type='personal', business_id=None, is_business_owner=False,
                    tz=ZoneInfo('UTC'), request_meta=meta or {})
    return Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)


class ScreenByItsVerbTests(TestCase):
    def opened(self, reply):
        from .engine import _open_claimed_screen
        belt = _belt()
        belt.result.reply = reply
        _open_claimed_screen(belt, belt.result)
        return [a['destination'] for a in belt.result.actions]

    def test_la_pantalla_para_recargar_opens_recargar(self):
        self.assertEqual(self.opened('¡Listo! Abro la pantalla para recargar con Pago Móvil.'), ['top_up'])
        self.assertEqual(self.opened('Te abro la pantalla de retirar.'), ['withdraw'])
        self.assertEqual(self.opened('Abriré la pantalla para enviar.'), ['send'])

    def test_not_a_verb_alone_nor_a_doubtful_claim(self):
        for reply in ('Te llevo a recargar tu saldo.', '¿Te abro la pantalla para recargar?',
                      'Si quieres, abro la pantalla para recargar.', 'Abrí la pantalla para recargar antes.',
                      'Abro la pantalla para recargar o la de retirar.'):
            self.assertEqual(self.opened(reply), [], reply)


class CardPromiseInOtherLanguagesTests(SimpleTestCase):
    def test_english_and_portuguese_promises(self):
        from .engine import _CARD_PROMISE
        for said in ('You can open it directly from the card below.', 'Tap the card below to go there.',
                     'Toque no cartão abaixo.', 'Abra pelo cartão logo abaixo.'):
            self.assertTrue(_CARD_PROMISE.search(said), said)
        for said in ('Use your debit card to pay.', 'Your card was declined.', 'Pague com o cartão de crédito.',
                     'Bring your boarding card.', 'Card games are fun.', 'Tap the card on the POS terminal to pay.',
                     'Press the card firmly against the reader.', 'Click the card number field and type it.',
                     'The cards below have no annual fee:', 'Toque o cartão na maquininha para pagar.',
                     'Aperte o botão e aproxime o cartão.'):
            self.assertFalse(_CARD_PROMISE.search(said), said)

    def test_an_unkept_english_promise_is_taken_out(self):
        from .engine import _without_promises
        self.assertEqual(_without_promises('Go to Send → To my own account. You can open it from the card below.'),
                         'Go to Send → To my own account.')


class SearchWithAPhotoInViewTests(TestCase):
    def test_the_tools_refuse_while_a_photo_is_seen(self):
        from .engine import _NO_SEARCH_WITH_A_PHOTO
        belt = _belt()
        belt.photos = {1: 'data:image/jpeg;base64,'}
        with patch('assistant.market.web_search') as search:
            self.assertEqual(belt.search_web('PLT'), _NO_SEARCH_WITH_A_PHOTO)
            self.assertEqual(belt.search_market_news('Apple'), _NO_SEARCH_WITH_A_PHOTO)
        search.assert_not_called()

    def test_starts_over_unless_something_was_written(self):
        from .engine import PhotoFreePass, _photo_free_pass
        belt = SimpleNamespace(photos={1: 'x'}, force_tool='')
        with self.assertRaises(PhotoFreePass):
            _photo_free_pass(belt, SimpleNamespace(tools=[{'name': 'context:recall_memory'}], actions=[]),
                             ['get_portfolio', 'search_web'])
        # After reads it starts over too; after a write the search tool refuses instead.
        with self.assertRaises(PhotoFreePass):
            _photo_free_pass(belt, SimpleNamespace(tools=[{'name': 'get_stock_quote'}, {'name': 'navigate'}],
                                                   actions=[{'type': 'card'}]), ['search_market_news'])
        _photo_free_pass(belt, SimpleNamespace(tools=[{'name': 'prepare_payment'}], actions=[]), ['search_web'])
        _photo_free_pass(SimpleNamespace(photos={}, force_tool=''), SimpleNamespace(tools=[], actions=[]),
                         ['search_web'])
        _photo_free_pass(SimpleNamespace(photos={1: 'x'}, force_tool='get_portfolio'),
                         SimpleNamespace(tools=[], actions=[]), ['search_web'])

    def test_not_on_the_message_with_the_photo_nor_after_a_smaller_retry(self):
        from .engine import _photo_free_pass
        nothing = SimpleNamespace(tools=[], actions=[])
        _photo_free_pass(SimpleNamespace(photos={1: 'x'}, force_tool='', photo_now=True), nothing, ['search_web'])
        _photo_free_pass(SimpleNamespace(photos={1: 'x'}, force_tool='', shrunk=True), nothing, ['search_web'])


class PhotoFreeAfterARawPassTests(SimpleTestCase):
    def test_a_raw_pass_that_wants_the_web_starts_over_without_the_photo(self):
        """Audit 2026-11-27: PhotoFreePass raised in the raw pass escaped the turn (a 500, no reply)."""
        from . import context as context_rules
        from .engine import PhotoFreePass, _run_turn
        belt = SimpleNamespace(photos={7: 'x'}, force_tool='')
        result = SimpleNamespace(reply='x', tools=[], actions=[])
        passes = []

        def once(belt, result, viewer, history, **who):
            passes.append((dict(belt.photos), belt.force_tool))
            if len(passes) == 1:
                raise context_rules.RawPass()
            if len(passes) == 2:
                raise PhotoFreePass('search_market_news')
            return 'done'
        with patch('assistant.engine._run_turn_once', side_effect=once), \
                patch('assistant.context.start_raw_pass'):
            self.assertEqual(_run_turn(belt, result, None, []), 'done')
        self.assertEqual(passes, [({7: 'x'}, ''), ({7: 'x'}, ''), ({}, 'search_market_news')])
        self.assertEqual(belt.photo_free_ids, {7})

    def test_answers_given_after_the_photo_are_hidden_from_that_pass(self):
        from .engine import _model_history
        msgs = [SimpleNamespace(id=1, sender_type='AGENT', body='Hola', metadata={}),
                SimpleNamespace(id=7, sender_type='USER', body='[foto]', metadata={'modality': 'PHOTO'}),
                SimpleNamespace(id=8, sender_type='AGENT', body='Dice PLT Platino', metadata={}),
                SimpleNamespace(id=9, sender_type='USER', body='La app se llama livo', metadata={})]
        belt = SimpleNamespace(photo_free_ids={7})
        with patch('assistant.context.model_messages', side_effect=lambda belt, history: list(history)):
            shown = _model_history(belt, msgs)
        self.assertEqual([m.body for m in shown],
                         ['Hola', '[foto]', '[Tu respuesta sobre una foto que ya no ves]', 'La app se llama livo'])
        self.assertEqual(shown[2].id, 8)


class PhotoNoLongerHeldTests(SimpleTestCase):
    def test_an_answer_about_an_expired_photo_still_starts_over(self):
        """Re-audit: 16 minutes later the photo has left the cache, the reply that read it has not."""
        from .engine import PhotoFreePass, _photo_free_pass, _photo_seen_by_this_pass
        belt = SimpleNamespace(photos={}, photo_ids={7}, force_tool='')
        self.assertTrue(_photo_seen_by_this_pass(belt))
        with self.assertRaises(PhotoFreePass):
            _photo_free_pass(belt, SimpleNamespace(tools=[], actions=[]), ['search_web'])
        belt.photo_free_ids = {7}
        self.assertFalse(_photo_seen_by_this_pass(belt))
        self.assertFalse(_photo_seen_by_this_pass(SimpleNamespace(photos={}, photo_ids=set())))

    def test_masks_from_the_first_photo_keeps_team_words_and_metadata(self):
        from .engine import _model_history
        msgs = [SimpleNamespace(id=5, sender_type='USER', body='[foto 1]', metadata={'modality': 'PHOTO'}),
                SimpleNamespace(id=6, sender_type='AGENT', body='Dice busca X', metadata={'ai': True, 'actions': []}),
                SimpleNamespace(id=7, sender_type='USER', body='[foto 2]', metadata={'modality': 'PHOTO'}),
                SimpleNamespace(id=8, sender_type='AGENT', body='Soy del equipo', metadata={}, sender_user_id=3),
                SimpleNamespace(id=9, sender_type='AGENT', body='', metadata={'ai': True})]
        with patch('assistant.context.model_messages', side_effect=lambda belt, history: list(history)):
            shown = _model_history(SimpleNamespace(photo_free_ids={5, 7}), msgs)
        self.assertEqual([m.body for m in shown], ['[foto 1]', '[Tu respuesta sobre una foto que ya no ves]',
                                                   '[foto 2]', 'Soy del equipo', ''])
        self.assertEqual(shown[1].metadata, {'ai': True, 'actions': []})

    def test_what_the_dropped_pass_read_is_dropped(self):
        from .engine import _start_photo_free
        belt = SimpleNamespace(photos={7: 'x'}, photo_ids={5, 7}, force_tool='', docs_read={'d'})
        result = SimpleNamespace(reply='r', actions=[{'type': 'card'}],
                                 tools=[{'name': 'get_stock_quote'}, {'name': 'context:recall_memory'}])
        _start_photo_free(belt, result, 'search_market_news')
        self.assertEqual((belt.photos, belt.photo_free_ids, belt.force_tool, belt.docs_read),
                         ({}, {5, 7}, 'search_market_news', set()))
        self.assertEqual((result.reply, result.actions), ('', []))
        self.assertEqual([t['name'] for t in result.tools], ['context:get_stock_quote', 'context:recall_memory'])
