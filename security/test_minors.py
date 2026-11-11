"""Verified minors: who counts, when the limit lifts, and where it applies.

Policy: "Confío Minimum Age and Minors Policy", section 5. Only a verified
date of birth counts; every acquisition gate refuses a verified under-18,
every exit stays open.
"""
from datetime import date, datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from security.minors import MINOR_MESSAGE, age_on, is_known_minor, minor_refusal
from security.models import IdentityVerification
from users.models import User

# Local tests carry the prod alert secret: never reach real Telegram.
_ALERTS = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)


def setUpModule():
    _ALERTS.start()


def tearDownModule():
    _ALERTS.stop()


# 2026-11-03 18:00 UTC: 2026-11-03 in Caracas (UTC-4) and Bogotá (UTC-5).
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=dt_timezone.utc)


def _now(at=NOW):
    return mock.patch('django.utils.timezone.now', return_value=at)


def _no_ip():
    return mock.patch('security.geo.get_country_for_ip', return_value=None)


class MinorFixture(TestCase):
    seq = 0

    def make_user(self, born=None, *, status='verified', country='VE'):
        MinorFixture.seq += 1
        n = MinorFixture.seq
        user = User.objects.create_user(
            username=f'minor-test-{n}', password='x', firebase_uid=f'minor-test-{n}',
            phone_country=country)
        if born is not None or status != 'verified':
            IdentityVerification.objects.create(
                user=user, status=status, verified_date_of_birth=born,
                verified_first_name='Ana', verified_last_name='Perez',
                verified_nationality='VEN', verified_address='x', verified_city='x',
                verified_state='x', verified_country='VEN', document_type='national_id',
                document_number=f'V{n:08d}', document_issuing_country='VEN',
            )
        return user


class WhoIsAMinorTests(MinorFixture):
    def test_age_counts_whole_years(self):
        self.assertEqual(age_on(date(2010, 11, 4), date(2026, 11, 3)), 15)
        self.assertEqual(age_on(date(2010, 11, 3), date(2026, 11, 3)), 16)
        self.assertIsNone(age_on(None, date(2026, 11, 3)))

    def test_verified_under_18_is_a_minor(self):
        with _now():
            user = self.make_user(date(2012, 1, 1))  # 14
            self.assertTrue(is_known_minor(user))
            self.assertEqual(minor_refusal(user), MINOR_MESSAGE)

    def test_verified_adult_is_not(self):
        with _now():
            self.assertFalse(is_known_minor(self.make_user(date(2000, 1, 1))))

    def test_no_birth_date_on_file_is_never_restricted(self):
        with _now():
            self.assertFalse(is_known_minor(self.make_user()))
            # A pending attempt is not decided: its birth date does not count.
            self.assertFalse(is_known_minor(self.make_user(date(2012, 1, 1), status='pending')))

    def test_rejected_or_expired_attempt_birth_date_counts(self):
        # Rejected attempts keep the OCR'd birth date (user 13712's case).
        with _now():
            self.assertTrue(is_known_minor(self.make_user(date(2009, 3, 22), status='rejected')))
            self.assertTrue(is_known_minor(self.make_user(date(2010, 1, 1), status='expired')))
            self.assertFalse(is_known_minor(self.make_user(date(2000, 1, 1), status='rejected')))

    def test_placeholder_birth_date_never_counts(self):
        from security.didit import PLACEHOLDER_BIRTH_DATE
        from security.minors import known_age
        with _now():
            user = self.make_user(PLACEHOLDER_BIRTH_DATE, status='rejected')
            self.assertIsNone(known_age(user, date(2026, 11, 3)))
            self.assertFalse(is_known_minor(user))

    def test_soft_deleted_attempt_still_counts(self):
        from django.utils import timezone
        with _now():
            user = self.make_user(date(2011, 1, 1), status='rejected')
            IdentityVerification.all_objects.filter(user=user).update(deleted_at=timezone.now())
            self.assertTrue(is_known_minor(user))

    def test_verified_placeholder_does_not_mask_a_minor_attempt(self):
        from security.didit import PLACEHOLDER_BIRTH_DATE
        with _now():
            user = self.make_user(date(2011, 1, 1), status='rejected')
            IdentityVerification.objects.create(
                user=user, status='verified', verified_date_of_birth=PLACEHOLDER_BIRTH_DATE,
                verified_first_name='Ana', verified_last_name='Perez', verified_nationality='VEN',
                verified_address='x', verified_city='x', verified_state='x', verified_country='VEN',
                document_type='national_id', document_number='V-PLACE-1', document_issuing_country='VEN')
            self.assertTrue(is_known_minor(user))

    def test_current_verified_document_wins_over_attempts(self):
        with _now():
            user = self.make_user(date(2012, 1, 1), status='rejected')
            IdentityVerification.objects.create(
                user=user, status='verified', verified_date_of_birth=date(2000, 1, 1),
                verified_first_name='Ana', verified_last_name='Perez', verified_nationality='VEN',
                verified_address='x', verified_city='x', verified_state='x', verified_country='VEN',
                document_type='national_id', document_number='V-ADULT-1', document_issuing_country='VEN')
            self.assertFalse(is_known_minor(user))

    def test_youngest_decided_attempt_counts_without_a_verified_document(self):
        with _now():
            user = self.make_user(date(2000, 1, 1), status='rejected')
            IdentityVerification.objects.create(
                user=user, status='rejected', verified_date_of_birth=date(2011, 5, 5),
                verified_first_name='Ana', verified_last_name='Perez', verified_nationality='VEN',
                verified_address='x', verified_city='x', verified_state='x', verified_country='VEN',
                document_type='national_id', document_number='V-MINOR-2', document_issuing_country='VEN')
            self.assertTrue(is_known_minor(user))

    def test_verified_document_without_birth_date_is_not_a_minor(self):
        with _now():
            self.assertFalse(is_known_minor(self.make_user(None, status='verified')))

    def test_limit_lifts_on_the_18th_birthday_never_early(self):
        user = self.make_user(date(2008, 11, 4))
        # 11:00 UTC on the birthday: already 2026-11-04 in every LATAM zone,
        # but still 2026-11-03 at UTC-12, so the limit holds (never early).
        with _now(datetime(2026, 11, 4, 11, 0, tzinfo=dt_timezone.utc)):
            self.assertTrue(is_known_minor(user))
        # 12:30 UTC: the birthday has arrived everywhere on Earth.
        with _now(datetime(2026, 11, 4, 12, 30, tzinfo=dt_timezone.utc)):
            self.assertFalse(is_known_minor(user))

    def test_stand_in_users_never_hit_the_database(self):
        self.assertFalse(is_known_minor(None))
        self.assertFalse(is_known_minor(SimpleNamespace(id=1, phone_country='VE')))
        self.assertFalse(is_known_minor(SimpleNamespace(pk=1, id=1, phone_country='VE')))
        self.assertFalse(is_known_minor(mock.MagicMock()))
        self.assertFalse(is_known_minor(mock.MagicMock(pk=1)))
        self.assertFalse(is_known_minor(User(phone_country='VE')))  # unsaved

    def test_comprar_reads_the_same_age(self):
        from marketplace.checkout import buyer_age, is_of_age
        with _now():
            user = self.make_user(date(2010, 6, 1))
            self.assertEqual(buyer_age(user, date(2026, 11, 3)), 16)
            self.assertFalse(is_of_age(user, 'VE'))


class AcquisitionPolicyTests(MinorFixture):
    """Ondo (Dollar+ and stocks), Futuros and presale refuse verified
    minors; their exits never do."""

    def setUp(self):
        self.ctx = _now()
        self.ctx.start()
        self.addCleanup(self.ctx.stop)
        self.minor = self.make_user(date(2012, 1, 1))
        self.adult = self.make_user(date(2000, 1, 1))

    def test_ondo_refuses_a_minor_with_the_age_copy(self):
        from cusd_plus.eligibility import ONDO_POLICY, check_savings_mint_eligibility, is_ondo_eligible
        with _no_ip():
            decision = ONDO_POLICY.evaluate(self.minor, {})
            self.assertFalse(decision.allowed)
            self.assertEqual((decision.message, decision.blocked_by), (MINOR_MESSAGE, 'age'))
            self.assertFalse(check_savings_mint_eligibility(self.minor, {}))
            # Recipients (send, payroll, invites) get plain cUSD, not cUSD+.
            self.assertFalse(is_ondo_eligible(self.minor))
            self.assertTrue(ONDO_POLICY.evaluate(self.adult, {}).allowed)

    def test_stock_buys_refused_but_sells_stay_open(self):
        from cusd_plus.eligibility import check_stock_buy_eligibility
        from cusd_plus.schema import _stock_issuer_eligible
        with _no_ip():
            self.assertFalse(check_stock_buy_eligibility(self.minor, {}))
            # The sell and discovery check skips the minors layer.
            self.assertTrue(_stock_issuer_eligible(self.minor, {}))
            self.assertTrue(check_stock_buy_eligibility(self.adult, {}))

    def test_futures_opens_refused_but_closes_and_discovery_stay_open(self):
        from cusd_plus import perps_risk
        with _no_ip(), self.settings(
                PERPS_ENABLED=True, PERPS_IOS_ENABLED=True, PERPS_TRADING_ENABLED=True,
                CUSD_PLUS_7702_ENABLED=True, CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x1',
                PERPS_ALLOWED_USER_IDS=''):
            self.assertTrue(perps_risk.surfaces_enabled(self.minor, {}))
            self.assertFalse(perps_risk.open_enabled(self.minor, {}))
            self.assertEqual(perps_risk.open_gate(self.minor, {}), 'trade_not_available')
            self.assertTrue(perps_risk.open_enabled(self.adult, {}))

    def test_presale_refuses_a_minor(self):
        from types import MappingProxyType
        from presale.geo_utils import check_presale_eligibility
        with _no_ip(), mock.patch('presale.geo_utils.country_rules',
                                  return_value=MappingProxyType({})):
            self.assertEqual(check_presale_eligibility(self.minor), (False, MINOR_MESSAGE))
            self.assertEqual(check_presale_eligibility(self.adult), (True, None))

    def test_store_review_bypass_still_wins(self):
        # Store-review accounts pass every policy; the bypass runs first.
        from dataclasses import replace
        from cusd_plus.eligibility import ONDO_POLICY
        policy = replace(ONDO_POLICY, bypass=lambda user: True)
        self.assertTrue(policy.evaluate(self.minor, {}).allowed)


class RailRefusalTests(MinorFixture):
    """Every rail refuses at the action with the same copy."""

    def setUp(self):
        self.ctx = _now()
        self.ctx.start()
        self.addCleanup(self.ctx.stop)
        self.minor = self.make_user(date(2012, 1, 1))
        self.adult = self.make_user(date(2000, 1, 1))

    def _info(self, user):
        return SimpleNamespace(context=SimpleNamespace(user=user, META={}))

    def test_cobre_and_infinia_entry_refused(self):
        from payment_accounts.schema import _require_adult
        from payment_accounts.schema import PaymentAccountError
        with self.assertRaisesMessage(PaymentAccountError, MINOR_MESSAGE):
            _require_adult(self._info(self.minor))
        _require_adult(self._info(self.adult))

    def test_payment_bridge_home_stays_open(self):
        from payment_accounts.schema import QuotePaymentBridge
        with mock.patch('payment_accounts.schema._active_account', side_effect=RuntimeError('reached')), \
                mock.patch('payment_accounts.schema._public_error', side_effect=lambda exc: str(exc)):
            out = QuotePaymentBridge.mutate(None, self._info(self.minor), 'f', '1', 'r', direction='to_provider')
            self.assertEqual(out.errors, [MINOR_MESSAGE])
            out = QuotePaymentBridge.mutate(None, self._info(self.minor), 'f', '1', 'r', direction='to_wallet')
            self.assertEqual(out.errors, ['reached'])

    def test_journeys_home_stay_open_and_bank_sends_refused(self):
        from payment_accounts.cobre_journey_schema import CreateCobreJourney
        from payment_accounts.journey_schema import CreateInfiniaJourney
        reached = mock.patch('payment_accounts.schema._active_account', side_effect=RuntimeError('reached'))
        public = mock.patch('payment_accounts.schema._public_error', side_effect=lambda exc: str(exc))
        with reached, public:
            for mutation, extra in ((CreateInfiniaJourney, {}), (CreateCobreJourney, {'copco_account_id': 'c'})):
                out = mutation.mutate(None, self._info(self.minor), local_account_id='l',
                                      crypto_account_id='k', direction='to_bank', **extra)
                self.assertEqual(out.errors, [MINOR_MESSAGE])
                out = mutation.mutate(None, self._info(self.minor), local_account_id='l',
                                      crypto_account_id='k', direction='to_wallet', **extra)
                self.assertEqual(out.errors, ['reached'])

    def test_payout_to_own_wallet_stays_open(self):
        from payment_accounts.schema import _is_own_wallet
        account = SimpleNamespace(bsc_address='0xAbC')
        self.assertTrue(_is_own_wallet(account, 'crypto_wallet', {'address': '0xabc'}))
        self.assertFalse(_is_own_wallet(account, 'crypto_wallet', {'address': '0xdef'}))
        self.assertFalse(_is_own_wallet(account, 'bank_account', {'address': '0xabc'}))
        self.assertFalse(_is_own_wallet(SimpleNamespace(bsc_address=''), 'crypto_wallet', {'address': ''}))

    def test_breb_application_refused(self):
        from payment_accounts.breb_location_schema import ApplyCobreBreb
        with mock.patch('payment_accounts.schema._active_account', side_effect=AssertionError('reached')), \
                mock.patch('payment_accounts.schema._public_error', side_effect=lambda exc: str(exc)):
            out = ApplyCobreBreb.mutate(None, self._info(self.minor), 'c', '{}', 't')
        self.assertEqual((out.success, out.error), (False, MINOR_MESSAGE))

    def test_existing_orders_never_fund(self):
        from ramps import bolivia_qr_schema, ve_pagomovil_schema
        order = SimpleNamespace(actor_address='0xabc')
        with mock.patch('ramps.ve_pagomovil.owned_order', return_value=order), \
                mock.patch('ramps.ve_pagomovil.enabled', return_value=True), \
                mock.patch.object(ve_pagomovil_schema, '_user', return_value=self.minor):
            out = ve_pagomovil_schema.StartVePagoMovilSendFunding().mutate(self._info(self.minor), 'o')
        self.assertEqual(out.error, MINOR_MESSAGE)
        with mock.patch('ramps.bolivia_qr_send.owned_order', return_value=order), \
                mock.patch('ramps.bolivia_qr.enabled', return_value=True), \
                mock.patch.object(bolivia_qr_schema, '_user', return_value=self.minor):
            out = bolivia_qr_schema.StartBoliviaQrSendFunding().mutate(self._info(self.minor), 'o')
        self.assertEqual(out.error, MINOR_MESSAGE)

    def test_pago_movil_and_bolivia_qr_refused(self):
        from ramps import bolivia_qr_schema, ve_pagomovil_schema
        from ramps.ve_pagomovil import VePagoMovilError
        account = SimpleNamespace(account_type='personal', bsc_address='0xabc')
        patches = [
            mock.patch('ramps.ve_pagomovil.enabled', return_value=True),
            mock.patch('ramps.bolivia_qr.offered', return_value=True),
            mock.patch('ramps.schema._employee_ramp_denial', return_value=None),
            mock.patch('ramps.schema._get_ramp_account_for_user', return_value=account),
            mock.patch('ramps.bolivia_qr_schema._personal_owner', return_value=account),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for module, direction in ((ve_pagomovil_schema, ve_pagomovil_schema.TOPUP),
                                  (bolivia_qr_schema, bolivia_qr_schema.RECEIVE)):
            with mock.patch.object(module, '_user', return_value=self.minor):
                with self.assertRaises(VePagoMovilError) as caught:
                    module._preflight(self._info(self.minor), direction)
                self.assertEqual(str(caught.exception), MINOR_MESSAGE)
                self.assertIsNone(caught.exception.next_step)

    def test_koywe_order_refused_before_any_provider_work(self):
        from ramps.schema import CreateRampOrder
        info = self._info(self.minor)  # a saved User is authenticated
        with mock.patch('ramps.schema._employee_ramp_denial', return_value=None), \
                mock.patch('ramps.schema._resolve_ramp_country_code',
                           side_effect=AssertionError('provider work reached')):
            out = CreateRampOrder.mutate(None, info, 'ON_RAMP', '10', 'X')
        self.assertEqual((out.success, out.error), (False, MINOR_MESSAGE))

    def test_guardarian_proxy_refused(self):
        import json
        from django.test import RequestFactory
        from config.views import guardarian_transaction_proxy
        request = RequestFactory().post('/x', data='{}', content_type='application/json',
                                        HTTP_AUTHORIZATION='JWT t')
        with self.settings(GUARDARIAN_API_KEY='k'), \
                mock.patch('security.integrity_service.app_check_service.verify_request_header',
                           return_value={'success': True}), \
                mock.patch('config.views.jwt_decode', return_value={'user_id': self.minor.id}), \
                mock.patch('security.face_client.request_update_required', return_value=False):
            response = guardarian_transaction_proxy(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)['error'], MINOR_MESSAGE)
