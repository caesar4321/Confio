"""Each local payment rail's guidance follows its live switch (assistant/pay_rails.py)."""
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import TestCase, override_settings

from users.models import User
from users.models_rail_waitlist import LocalRailWaitlistEntry

from . import pay_rails
from .engine import Toolbelt, TurnResult, Viewer

META = {'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.2'}
ALL_WORD_RAILS = 'br_pix,ar_cvu,co_breb,mx_clabe'


class PayRailStateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='rails', email='rails@example.com', password='x',
                                             firebase_uid='fb-rails')
        from users.models import Account
        self.account = Account.objects.create(user=self.user, account_type='personal')

    def _belt(self, ready=True, meta=META):
        viewer = Viewer(user=self.user, account=self.account, account_type='personal', business_id=None,
                        is_business_owner=False, tz=ZoneInfo('UTC'), request_meta=meta)
        belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.payments_ready = lambda: ready
        return belt

    def _state(self, key, belt=None):
        belt = belt or self._belt()
        return pay_rails.state(pay_rails.BY_KEY[key], belt.viewer, belt)

    def test_infinia_rails_follow_the_provider_switch_and_rules(self):
        live = ('live', '', None)
        with override_settings(PAYMENT_INTENTS_WORD_RAILS=ALL_WORD_RAILS), \
                patch('payment_accounts.payment_intents._identity', return_value=None):
            for key in ('pix_code', 'pix_key', 'spei', 'breb_key', 'breb_qr', 'ar_cvu', 'ar_qr'):
                with patch('payment_accounts.local_money.rail_status', return_value=live):
                    self.assertEqual(self._state(key), 'on', key)
                with patch('payment_accounts.local_money.rail_status',
                           return_value=('unavailable', 'infinia_co_partner_paused', None)):
                    self.assertEqual(self._state(key), 'paused', key)
                with patch('payment_accounts.local_money.rail_status',
                           return_value=('needs_verification', 'identity_required', None)):
                    self.assertEqual(self._state(key), 'verify', key)
            # The real switch: the provider's flags off is "off" for every rail.
            with override_settings(INFINIA_PAYMENT_ACCOUNTS_ENABLED=False):
                self.assertEqual(self._state('spei'), 'off')
        # A typed key is only taken where its word rail is on; a pasted code always.
        with override_settings(PAYMENT_INTENTS_WORD_RAILS=''), \
                patch('payment_accounts.payment_intents._identity', return_value=None), \
                patch('payment_accounts.local_money.rail_status', return_value=live):
            self.assertEqual(self._state('spei'), 'screen')
            self.assertEqual(self._state('pix_code'), 'on')
            self.assertEqual(self._state('pix_code', self._belt(ready=False)), 'screen')

    def test_pago_movil_follows_its_send_switch_and_floor(self):
        with override_settings(VE_PAGOMOVIL_SEND_ENABLED=True, VE_PAGOMOVIL_SEND_MIN_APP_VERSION='5.3.0'):
            self.assertEqual(self._state('pagomovil'), 'on')
        with override_settings(VE_PAGOMOVIL_SEND_ENABLED=True, VE_PAGOMOVIL_SEND_MIN_APP_VERSION='9.0.0'):
            self.assertEqual(self._state('pagomovil'), 'update')
        with override_settings(VE_PAGOMOVIL_SEND_ENABLED=False):
            self.assertEqual(self._state('pagomovil'), 'off')

    def test_bolivia_qr_follows_its_send_switch(self):
        with override_settings(BOLIVIA_QR_SEND_ENABLED=True, BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9'):
            self.assertEqual(self._state('bo_qr'), 'on')
        with override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS=''):
            self.assertEqual(self._state('bo_qr'), 'off')
        with override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS=str(self.user.pk),
                               BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9'):
            self.assertEqual(self._state('bo_qr'), 'on')          # a listed tester before the switch

    def test_peru_is_its_waitlist_only(self):
        self.assertEqual(self._state('pe_qr'), 'off')

    def test_the_section_flips_with_the_switch_no_prompt_edit(self):
        belt = self._belt()
        with override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS='',
                               VE_PAGOMOVIL_SEND_ENABLED=False, INFINIA_PAYMENT_ACCOUNTS_ENABLED=False):
            off = pay_rails.section(belt.viewer, belt)
        cache.clear()
        with override_settings(BOLIVIA_QR_SEND_ENABLED=True, BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9',
                               VE_PAGOMOVIL_SEND_ENABLED=True, VE_PAGOMOVIL_SEND_MIN_APP_VERSION='5.3.0',
                               INFINIA_PAYMENT_ACCOUNTS_ENABLED=False):
            on = pay_rails.section(belt.viewer, belt)
        bo_off = next(line for line in off.splitlines() if '(BO)' in line)
        bo_on = next(line for line in on.splitlines() if '(BO)' in line)
        self.assertIn('no está disponible por ahora', bo_off)
        self.assertIn('llegará muy pronto', bo_off)
        self.assertIn('`notify_rail` (`bo_qr`)', bo_off)
        self.assertIn('disponible; se hace con el botón de QR', bo_on)
        self.assertIn('`pagomovil_payment`', next(line for line in on.splitlines() if '(VE)' in line))
        self.assertIn('no está disponible', next(line for line in on.splitlines() if '(PE)' in line))

    def test_rail_lines_reach_the_prompt_for_the_own_account_only(self):
        from .engine import _run_turn_once  # noqa: F401  (the section is added there)
        belt = self._belt()
        self.assertTrue(belt._pay_rails_offered())
        self.assertIn('notify_rail', {spec['name'] for spec in belt.specs()})
        belt.viewer.account_type = 'business'
        self.assertFalse(belt._pay_rails_offered())

    def test_notify_offers_and_the_yes_joins_the_waitlist_only_while_off(self):
        # The model asked «¿Te aviso?» itself and a bare "Si" got its last answer repeated, with nobody
        # added (2026-11-26): the offer is now code's question, and the yes joins in code.
        belt = self._belt()
        with override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS=''):
            out = belt.call('notify_rail', {'rail': 'bo_qr'})
            self.assertTrue(out['pendiente_de_confirmacion'])
            self.assertEqual(belt.result.pending_watch['notice_rail'], 'bo_qr')
            self.assertFalse(LocalRailWaitlistEntry.objects.filter(user=self.user).exists())
            self.assertEqual(pay_rails.join(belt.viewer, 'bo_qr'), 'joined')
        row = LocalRailWaitlistEntry.objects.get(user=self.user, rail_id='send_bo_qr')
        self.assertEqual((row.direction, row.country), ('send', 'BO'))
        with override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS=''):
            again = self._belt().call('notify_rail', {'rail': 'bo_qr'})
        self.assertTrue(again['ya_anotada'])
        with override_settings(BOLIVIA_QR_SEND_ENABLED=True, BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9'):
            self.assertFalse(self._belt().call('notify_rail', {'rail': 'bo_qr'})['ok'])
            self.assertIn(pay_rails.join(belt.viewer, 'bo_qr'), ('open', 'update'))
        self.assertFalse(self._belt().call('notify_rail', {'rail': 'nope'})['ok'])


class PaymentGuidanceInPromptTests(TestCase):
    def test_no_rail_state_is_hard_coded_in_the_prompt(self):
        from .prompts import BO_WITHDRAW_NOTES, CHAT_FIRST_NOTE, faq_text
        for note in BO_WITHDRAW_NOTES.values():
            self.assertNotIn('Pagar QR locales todavía no se puede', note)
        self.assertIn('Pagar en moneda local', CHAT_FIRST_NOTE)
        self.assertNotIn('pagar QR locales de Bolivia llegará muy pronto', faq_text())


class ScannerNoteTests(TestCase):
    def test_the_scanner_says_when_the_countrys_qr_is_off(self):
        cache.clear()
        user = User.objects.create_user(username='scan', email='scan@example.com', password='x',
                                        firebase_uid='fb-scan')
        from users.models import Account
        viewer = Viewer(user=user, account=Account.objects.create(user=user, account_type='personal'),
                        account_type='personal', business_id=None, is_business_owner=False, tz=ZoneInfo('UTC'),
                        request_meta=META)
        belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        belt.payments_ready = lambda: True
        belt.destinations = ['pay_qr']
        with patch('security.geo.country_of', return_value='BO'):
            with override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_TEST_USER_IDS=''):
                self.assertIn('hoy no se puede', belt.navigate('pay_qr')['qr_de_su_pais'])
            with override_settings(BOLIVIA_QR_SEND_ENABLED=True, BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9'):
                self.assertNotIn('qr_de_su_pais', belt.navigate('pay_qr'))
