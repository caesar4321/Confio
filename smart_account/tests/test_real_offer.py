"""The new app build always opens the real Cuenta inteligente screens
(founder, 2026-11-21): the offer shows the whole pitch to any personal,
non-employee viewer on a supported build whatever the server flags say;
signing stays gated (canSubscribe / blockedReason). Also: 'opening' while a
subscribe is being reconciled, and payout rails named by the server."""
from datetime import timedelta, timezone as dt_timezone
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from smart_account import offer, schema, services
from smart_account.models import SmartAccountPreparedAction

from .base import BUILD, VAULT, SmartAccountTestCase, WAD
from .base import INFINIA_SWITCHES

FLAG_OFF = 'Todavía no puedes abrir tu Cuenta inteligente.'


class RealOfferTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user('u')
        patcher = mock.patch('smart_account.offer.crypto_investing_enabled', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def offer(self, **kw):
        return schema.Query.resolve_smart_account_offer(None, self.info(self.user, **kw))

    def assert_full_pitch(self, result):
        self.assertEqual({p.key: p.price_usd for p in result.plans}, {'annual': '149.99', 'monthly': '14.99'})
        self.assertEqual(len(result.disclosures), 6)
        self.assertTrue(result.headline)
        self.assertEqual(len(result.benefits), 4)
        self.assertIn(result.dollar, ('cusd', 'cusd_plus'))
        self.assertEqual(result.payout_rails, [])
        self.assertEqual(result.payout_rail_options, [])

    def test_flag_off_still_shows_the_whole_pitch_with_a_clear_reason(self):
        with override_settings(SMART_ACCOUNT_ENABLED=False):
            result = self.offer()
        self.assertTrue(result.available)
        self.assertFalse(result.can_subscribe)
        self.assertEqual(result.blocked_reason, FLAG_OFF)
        self.assertEqual(result.blocked_code, 'disabled')
        self.assert_full_pitch(result)

    def test_no_factory_address_still_shows_the_pitch_with_settings_prices(self):
        with override_settings(SMART_ACCOUNT_FACTORY_ADDRESS=''):
            result = self.offer()
        self.assertTrue(result.available)
        self.assertFalse(result.can_subscribe)
        self.assert_full_pitch(result)

    def test_not_on_the_canary_list_and_not_on_the_probe(self):
        with override_settings(SMART_ACCOUNT_ALLOWED_USER_IDS='', SMART_ACCOUNT_PROBE_ENABLED=False):
            result = self.offer()
        self.assertTrue(result.available)
        self.assertFalse(result.can_subscribe)
        self.assertEqual(result.blocked_reason, FLAG_OFF)

    def test_identity_gate_keeps_its_reason(self):
        self.unverified.add(self.user.pk)
        result = self.offer()
        self.assertTrue(result.available)
        self.assertFalse(result.can_subscribe)
        self.assertEqual(result.blocked_code, 'identity')

    def test_old_build_is_not_available(self):
        result = self.offer(meta={'HTTP_X_CONFIO_VERSION': '5.0.0'})
        self.assertFalse(result.available)
        self.assertFalse(result.can_subscribe)

    def test_business_context_is_not_available(self):
        result = self.offer(account_type='business', business_id=1)
        self.assertFalse(result.available)
        self.assertFalse(result.can_subscribe)

    def test_prepare_keeps_refusing_with_the_flag_off(self):
        self.fund(VAULT, self.user.wallet, 500 * WAD)
        with override_settings(SMART_ACCOUNT_ENABLED=False):
            with self.assertRaises(services.PrepareError) as raised:
                services.prepare_subscribe(self.viewer(self.user), 'annual',
                                           [{'asset_key': 'cusd_plus', 'units': 'max'}], True)
        self.assertEqual(raised.exception.code, 'disabled')
        self.assertEqual(raised.exception.message, FLAG_OFF)


class OpeningTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user('u')
        self.fund(VAULT, self.user.wallet, 500 * WAD)

    def _sign(self, status='sent'):
        batch = services.prepare_subscribe(self.viewer(self.user), 'annual',
                                           [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], True)
        from blockchain.models import SponsoredBatch
        sponsored = SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=self.user.wallet, kind='smart_subscribe', num_calls=3,
            calls_json='[]', tx_hash='0x' + 'ab' * 32, gas_limit=1, max_fee_wei='1', status=status)
        SmartAccountPreparedAction.objects.filter(request_id=batch.request_id).update(
            consumed=True, consumed_at=timezone.now(), sponsored_batch=sponsored)
        return sponsored

    def test_a_subscribe_on_the_wire_reads_opening_and_no_second_one_is_offered_or_prepared(self):
        self._sign()
        account = schema.Query.resolve_smart_account(None, self.info(self.user))
        self.assertEqual(account.status, 'opening')
        with mock.patch('smart_account.offer.crypto_investing_enabled', return_value=False):
            result = schema.Query.resolve_smart_account_offer(None, self.info(self.user))
        self.assertFalse(result.can_subscribe)
        self.assertEqual(result.blocked_code, 'opening')
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_subscribe(self.viewer(self.user), 'annual',
                                       [{'asset_key': 'cusd_plus', 'units': 'max'}], True)
        self.assertEqual(raised.exception.code, 'opening')

    def test_a_reverted_subscribe_is_not_opening(self):
        self._sign(status='reverted')
        self.assertEqual(schema.Query.resolve_smart_account(None, self.info(self.user)).status, 'none')

    def test_the_window_is_bounded(self):
        sponsored = self._sign()
        SmartAccountPreparedAction.objects.filter(sponsored_batch=sponsored).update(
            consumed_at=timezone.now() - timedelta(minutes=offer.OPENING_WINDOW_MINUTES + 1))
        self.assertEqual(schema.Query.resolve_smart_account(None, self.info(self.user)).status, 'none')


@override_settings(SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True, **INFINIA_SWITCHES)
class PayoutRailNameTests(SmartAccountTestCase):
    def test_options_come_from_the_server_names_for_exactly_the_offered_rails(self):
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='br_pix,ar_cvu,co_breb,ar_qr,co_qr,br_qr,nope,br_pix_receive,mx_clabe'):
            self.assertEqual(offer.payout_rails(), ['br_pix', 'mx_clabe'])
            self.assertEqual(offer.payout_rail_options(), [
                {'key': 'br_pix', 'label': 'Pix', 'hint': 'Chave Pix: CPF, celular, e-mail o aleatoria'},
                {'key': 'mx_clabe', 'label': 'CLABE', 'hint': 'Transferencia SPEI a cualquier banco'},
            ])
            user = self.make_user('u')
            with mock.patch('smart_account.offer.crypto_investing_enabled', return_value=False):
                result = schema.Query.resolve_smart_account_offer(None, self.info(user))
            self.assertEqual([(o.key, o.label) for o in result.payout_rail_options],
                             [('br_pix', 'Pix'), ('mx_clabe', 'CLABE')])

    def test_assistant_names_a_newly_switched_on_rail(self):
        from assistant.prompts import _smart_account_rails
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe,br_pix,ar_cvu'):
            self.assertEqual(_smart_account_rails(),
                             ' a otras personas en Confío y a cuentas guardadas de CLABE y Pix')
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='ar_qr'):
            self.assertEqual(_smart_account_rails(), ' a otras personas en Confío')

    def test_join(self):
        self.assertEqual(offer.join_es(['A']), 'A')
        self.assertEqual(offer.join_es(['A', 'B', 'C']), 'A, B y C')
        self.assertEqual(offer.join_es([]), '')


class AssistantDoorTests(SmartAccountTestCase):
    def viewer(self, user, version='6.0.0', account_type='personal', owner=True):
        from assistant.engine import Viewer
        return Viewer(user=user, account=None, account_type=account_type, business_id=None,
                      is_business_owner=owner, tz=dt_timezone.utc,
                      request_meta={'HTTP_X_CONFIO_VERSION': version})

    @override_settings(SMART_ACCOUNT_ENABLED=False, SMART_ACCOUNT_PROBE_ENABLED=False)
    def test_new_build_keeps_the_door_and_gets_the_real_wording(self):
        from assistant.engine import allowed_destinations, smart_account_real_screen
        from assistant.prompts import _paid_offer_sections
        user = self.make_user('u')
        new = self.viewer(user)
        self.assertTrue(smart_account_real_screen(new))
        self.assertIn('cuenta_inteligente', allowed_destinations(new))
        text = _paid_offer_sections(['cuenta_inteligente'], smart_account_real=True)
        self.assertIn('No hay lista de espera', text)
        self.assertNotIn('(lista de espera)', text)
        self.assertIn('US$149.99 al año', text)

    @override_settings(SMART_ACCOUNT_ENABLED=False, SMART_ACCOUNT_PROBE_ENABLED=False)
    def test_old_build_and_employees_keep_the_probe_behaviour(self):
        from assistant.engine import allowed_destinations, smart_account_real_screen
        from assistant.prompts import _paid_offer_sections
        user = self.make_user('u')
        old = self.viewer(user, version='5.0.0')
        self.assertFalse(smart_account_real_screen(old))
        self.assertNotIn('cuenta_inteligente', allowed_destinations(old))
        employee = self.viewer(user, account_type='business', owner=False)
        self.assertFalse(smart_account_real_screen(employee))
        self.assertIn('(lista de espera)', _paid_offer_sections(['cuenta_inteligente']))
