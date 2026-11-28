"""Review of 2026-11-28: Spanish chips for a Brazilian, a «Muéstrame» button promised and not shown (Natane)."""
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .engine import TurnResult, Viewer, _keep_show_me_promise


class PortugueseChipTests(SimpleTestCase):
    CONVERSATION = {'HTTP_X_CONFIO_HOME': 'conversation'}

    def chips(self, country='BR', history=(), asked=(), holding=None, funded=False, screen='Home'):
        from . import suggestions
        state = suggestions._State(personal=True, employee=False, country=country, funded=funded,
                                   topup_in_progress=False, verification_pending=False, ondo_eligible=True,
                                   probe_answered=False)
        viewer = Viewer(user=None, account=None, account_type='personal', business_id=None, is_business_owner=False,
                        tz=ZoneInfo('UTC'))
        with patch('assistant.suggestions._state', return_value=state), \
                patch('assistant.suggestions._own_messages',
                      return_value=[suggestions._norm(h) for h in history]), \
                patch('assistant.suggestions._recently_asked',
                      return_value={suggestions._norm(a) for a in asked}), \
                patch('assistant.suggestions._top_holding', return_value=holding), \
                patch('assistant.suggestions._has_local_rate', return_value=False):
            return suggestions.build(viewer, screen, self.CONVERSATION)

    def test_brazil_gets_portuguese_chips(self):
        out = self.chips()
        texts = [s.text for s in out.starters]
        self.assertIn('Como recebo dólares de outra pessoa?', texts)
        self.assertTrue(all(s.prompt == '' or not s.prompt.startswith('¿') for s in out.starters), texts)
        self.assertTrue(all(not s.text.startswith('¿') for s in out.hints))

    def test_the_persons_own_words_decide(self):
        # A Venezuelan in Brazil writes Spanish: Spanish chips.
        es = self.chips(history=['Quiero enviar dinero a mi mamá en Caracas'])
        self.assertIn('¿Cómo recibo dólares de otra persona?', [s.text for s in es.starters])
        # A Brazilian anywhere writes Portuguese; a tapped Spanish chip is not their words.
        pt = self.chips(country='AR', funded=True, history=['¿Cómo recibo dólares de otra persona?',
                                                            'Quero recarregar por Pix, não consigo'])
        self.assertFalse(any(s.text.startswith('¿') for s in pt.starters), [s.text for s in pt.starters])

    def test_a_portuguese_chip_asked_makes_room(self):
        out = self.chips(asked=['Como recebo dólares de outra pessoa?'])
        self.assertNotIn('norail.receive', [s.id for s in out.starters])

    def test_ticker_chip(self):
        out = self.chips(funded=True, holding='PEP')
        chip = next(s for s in out.starters if s.id == 'own.stock')
        self.assertEqual((chip.text, chip.prompt), ('Como está PEP hoje?', 'Como está PEP hoje e por que subiu ou caiu?'))

    def test_every_chip_has_portuguese(self):
        import re
        from pathlib import Path
        from . import suggestions
        source = Path(suggestions.__file__).read_text()
        said = set(re.findall(r"_s\(\s*'[^']+',\s*'((?:[^'\\]|\\.)+)'", source))
        said |= set(re.findall(r"_s\(\s*'[^']+',\s*'[^']*',\s*'((?:[^'\\]|\\.)+)'", source))
        said |= {chip for _id, chip, _words in suggestions.GENERAL_KINDS}
        self.assertEqual(sorted(said - set(suggestions.PORTUGUESE)), [])


class ShowMePromiseTests(SimpleTestCase):
    def guard(self, reply, actions=()):
        result = TurnResult(reply=reply)
        result.actions = list(actions)
        _keep_show_me_promise(result)
        return result.reply

    def test_promise_with_no_button_is_taken_out(self):
        said = ('En Recibir, toca «Compartir» para enviarle tu número. Si quieres, toca el botón «Muéstrame» y te '
                'señalo los pasos en la app.')
        self.assertEqual(self.guard(said), 'En Recibir, toca «Compartir» para enviarle tu número.')
        self.assertEqual(self.guard('Use o Pix. Toque em "Mostre-me" para ver os passos.'), 'Use o Pix.')

    def test_left_alone(self):
        walk = {'type': 'walk', 'target': 'share_number', 'label': 'Muéstrame'}
        said = 'Toca el botón «Muéstrame» y te señalo los pasos.'
        self.assertEqual(self.guard(said, [walk]), said)
        for plain in ('Escríbeme «muéstrame cómo» cuando quieras.' , 'Dime muéstrame y te explico.',
                      'Toca «Muéstrame»'):
            kept = self.guard(plain)
            self.assertTrue(kept, plain)
        self.assertEqual(self.guard('Dime muéstrame y te explico.'), 'Dime muéstrame y te explico.')


class AuditFindingsTests(PortugueseChipTests):
    def test_no_signal_falls_back_to_country(self):
        out = self.chips(history=['oi', 'bom dia'])
        self.assertIn('Como recebo dólares de outra pessoa?', [s.text for s in out.starters])

    def test_ticker_shape_is_one_ticker(self):
        from . import suggestions
        self.assertFalse(suggestions._is_chip('como está o pix hoje?'))
        self.assertFalse(suggestions._is_chip('¿cómo va todo lo de mi recarga hoy?'))
        self.assertTrue(suggestions._is_chip('como está pep hoje?'))
        self.assertTrue(suggestions._is_chip('¿cómo va nvda hoy?'))

    def test_portuguese_informational_chips_are_taps(self):
        from .engine import is_tapped_text
        for chip in ('Quanto custa usar o Confío?', 'É seguro? Quem controla meu dinheiro?'):
            self.assertTrue(is_tapped_text(chip), chip)

    def test_bold_and_single_quotes(self):
        for said in ('Abre Recibir. Toca el botón **Muéstrame** abajo.', "Abre Recibir. Puedes tocar 'Muéstrame'."):
            self.assertEqual(ShowMePromiseTests().guard(said), 'Abre Recibir.', said)


class SmartAccountIdentityNoteTests(SimpleTestCase):
    def sections(self, **kw):
        from .prompts import _paid_offer_sections
        with patch('users.paid_offers.price', return_value='14.99'), \
                patch('assistant.prompts._smart_account_rails', return_value=''):
            return _paid_offer_sections(['cuenta_inteligente', 'verification'], **kw)

    def test_unverified_on_the_real_screen_gets_the_verification_card_line(self):
        out = self.sections(smart_account_real=True, smart_account_needs_identity=True)
        self.assertIn('tarjeta de `verification`', out)

    def test_not_for_anyone_else(self):
        for kw in ({'smart_account_real': True}, {'smart_account_real': True, 'smart_account_open': True,
                                                  'smart_account_needs_identity': True},
                   {'smart_account_needs_identity': True}):
            self.assertNotIn('tarjeta de `verification`', self.sections(**kw), kw)
        from .prompts import _paid_offer_sections
        with patch('users.paid_offers.price', return_value='14.99'), \
                patch('assistant.prompts._smart_account_rails', return_value=''):
            no_card = _paid_offer_sections(['cuenta_inteligente'], smart_account_real=True,
                                           smart_account_needs_identity=True)
        self.assertNotIn('tarjeta de `verification`', no_card)

    def test_only_people_with_something_to_do(self):
        from .engine import _smart_account_needs_identity
        viewer = Viewer(user=SimpleNamespace(pk=1), account=None, account_type='personal', business_id=None,
                        is_business_owner=False, tz=ZoneInfo('UTC'))
        for status in ('verified', 'in_review', None, 'other_country'):
            with patch('assistant.engine.smart_account_real_screen', return_value=True), \
                    patch('assistant.engine._identity_status', return_value=status), \
                    patch('smart_account.offer.subscribe_block') as block:
                self.assertFalse(_smart_account_needs_identity(viewer), status)
            block.assert_not_called()
        for status in ('unverified', 'rejected', 'pending'):
            with patch('assistant.engine.smart_account_real_screen', return_value=True), \
                    patch('assistant.engine._identity_status', return_value=status), \
                    patch('smart_account.offer.subscribe_block', return_value='identity'):
                self.assertTrue(_smart_account_needs_identity(viewer), status)
