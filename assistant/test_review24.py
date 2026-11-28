"""Review of 2026-11-28: the Preventa card promised and not made, and "¿cuánto cotiza hoy un token?"
answered "no puedo ver" (Jose, Argentina)."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .engine import _CARD_PROMISE, Toolbelt, TurnResult, Viewer, _ends_on_screen, _keep_card_promise

HOME = {'HTTP_X_CONFIO_HOME': 'conversation'}


class PresaleCardPromiseTests(SimpleTestCase):
    def guard(self, reply, destinations=('presale', 'receive', 'top_up')):
        result = TurnResult(reply=reply)
        belt = Toolbelt(Viewer(user=None, account=None, account_type='personal', business_id=None,
                               is_business_owner=False, tz=ZoneInfo('America/La_Paz'), request_meta=HOME),
                        result, analyses_left=0)
        belt.card_spec = {'name': 'navigate'}
        belt.destinations = list(destinations)
        with patch('assistant.engine._openai_responses') as card_model, \
                patch('assistant.engine._add_cards') as add_cards:
            _keep_card_promise(belt, result)
        card_model.assert_not_called()
        return result, add_cards

    def test_the_presale_card_promised_is_made(self):
        for said in ('Ten en cuenta que quedan bloqueados.\n\nSi quieres verla o participar, te dejo aquí el '
                     'acceso a la Preventa de $CONFIO:',
                     'El precio sube con cada compra. Puedes ver el precio actual entrando a la pantalla de la '
                     'Preventa:'):
            result, _ = self.guard(said)
            self.assertEqual(result.actions, [{'type': 'card', 'destination': 'presale'}], said)
            self.assertEqual(result.reply, said)

    def test_no_presale_for_this_person_the_promise_goes(self):
        result, add_cards = self.guard('El precio sube. Te dejo aquí el acceso a la Preventa de $CONFIO:',
                                       destinations=('receive',))
        self.assertEqual(result.actions, [])
        self.assertEqual(result.reply, 'El precio sube.')

    def test_screen_colon_only_at_the_very_end_and_only_a_screen(self):
        self.assertFalse(_ends_on_screen('Abre la pantalla de Recibir:\n1. Toca Avanzado.'))
        self.assertFalse(_ends_on_screen('En la pantalla de tu banco:'))
        self.assertFalse(_ends_on_screen('la pantalla de la preventa:'))  # a word, not the screen's name
        self.assertTrue(_ends_on_screen('Lo ves en la pantalla de Recibir:  '))
        for said in ('Puedes verlo en la pantalla de **Preventa**:', '**Puedes verlo en la pantalla de la Preventa:**',
                     'Lo ves en la pantalla de «Preventa»:', 'Entra a la Preventa:', 'Abre Recibir:'):
            self.assertTrue(_ends_on_screen(said), said)
        self.assertFalse(_ends_on_screen('Abre tu banco:'))
        # Never part of the sentence-by-sentence promise check.
        self.assertFalse(_CARD_PROMISE.search('En la pantalla de Retirar te pedirá estos datos:'))

    def test_a_list_opened_by_a_screen_is_kept(self):
        said = 'En la pantalla de Enviar verás:\n- Monto\n- Destinatario\n\nTe dejo aquí el acceso a Recibir:'
        result, _ = self.guard(said)
        self.assertEqual(result.actions, [{'type': 'card', 'destination': 'receive'}])
        self.assertEqual(result.reply, said)
        result, _ = self.guard(said, destinations=('presale',))
        self.assertEqual(result.actions, [])
        self.assertEqual(result.reply, 'En la pantalla de Enviar verás:\n- Monto\n- Destinatario')


class PresalePriceToolTests(SimpleTestCase):
    def call(self, price=Decimal('0.231467'), source='live', buyable=True):
        belt = SimpleNamespace(_presale_buyable=lambda: buyable)
        with patch('presale.price_utils.get_confio_price_with_source', return_value=(price, source)):
            return Toolbelt.get_presale_price(belt)

    def test_live_price_never_rounded_up_and_written_with_a_comma(self):
        out = self.call()
        self.assertEqual((out['ok'], out['precio_usd'], out['rango_usd']), (True, '0,2314', '0,20 a 1,30'))
        self.assertNotIn('último precio', out['nota'])

    def test_last_known_says_so_and_a_fallback_is_never_today_s_price(self):
        self.assertIn('último precio', self.call(source='last_known')['nota'])
        for source in ('phase', 'floor'):
            self.assertFalse(self.call(source=source)['ok'], source)

    def test_only_for_someone_who_may_buy_now(self):
        self.assertIn('error', self.call(buyable=False))

    def test_read_failure_is_an_honest_no(self):
        belt = SimpleNamespace(_presale_buyable=lambda: True)
        with patch('presale.price_utils.get_confio_price_with_source', side_effect=RuntimeError('rpc')):
            self.assertFalse(Toolbelt.get_presale_price(belt)['ok'])


class PresaleBuyableTests(SimpleTestCase):
    def buyable(self, access='buy', active=True, destinations=('presale',), employee=False, fails=False):
        viewer = SimpleNamespace(user=SimpleNamespace(pk=1), is_employee=employee, request_meta={})
        belt = SimpleNamespace(viewer=viewer, destinations=list(destinations))
        settings_row = SimpleNamespace(is_presale_active=active)
        with patch('presale.models.PresaleSettings.get_settings', return_value=settings_row), \
                patch('presale.geo_utils.presale_access',
                      side_effect=RuntimeError('geo') if fails else (lambda *a, **k: {'access': access})):
            return Toolbelt._presale_buyable(belt)

    def test_only_an_open_sale_in_an_open_country(self):
        self.assertTrue(self.buyable())
        for kw in ({'access': 'waitlist'}, {'access': 'blocked'}, {'active': False}, {'destinations': ()},
                   {'employee': True}, {'fails': True}):
            self.assertFalse(self.buyable(**kw), kw)
