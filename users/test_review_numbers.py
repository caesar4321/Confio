"""Store-review numbers: Argentina bypasses every geo block, the US and UK
numbers bypass nothing, so reviewers can see both sides."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from users import review_numbers as rn

REVIEW = dict(
    REVIEW_TEST_ENABLED=True,
    REVIEW_TEST_PHONE_E164='+542025550123',
    REVIEW_TEST_CODE='111111',
    REVIEW_TEST_PHONE_E164_2='+542025550124',
    REVIEW_TEST_CODE_2='222222',
    REVIEW_TEST_GEO_BLOCKED_PHONES_E164=['+12025550125', '+447700900125'],
    REVIEW_TEST_GEO_BLOCKED_PHONES_E164_2=['+12025550126', '+447700900126'],
)


def _clear():
    rn._review_phone_keys.cache_clear()
    rn._shared_reviewer_phone_keys.cache_clear()


class _Cached:
    def setUp(self):
        _clear()
        self.addCleanup(_clear)


@override_settings(**REVIEW)
class ReviewNumberTests(_Cached, SimpleTestCase):
    def test_six_numbers_with_country_code_and_exemption(self):
        got = {(n.phone, n.code, n.country, n.geo_exempt) for n in rn.review_numbers()}
        self.assertEqual(got, {
            ('+542025550123', '111111', 'AR', True),
            ('+12025550125', '111111', 'US', False),
            ('+447700900125', '111111', 'GB', False),
            ('+542025550124', '222222', 'AR', True),
            ('+12025550126', '222222', 'US', False),
            ('+447700900126', '222222', 'GB', False),
        })

    def test_every_number_verifies_and_is_shared(self):
        for number in rn.review_numbers():
            self.assertEqual(rn.get_review_test_code_for_phone(number.phone), number.code)
            key = rn.normalize_any_phone(number.phone)
            self.assertTrue(rn.is_review_test_phone_key(key))
            self.assertTrue(rn.is_shared_reviewer_phone_key(key))

    def test_national_number_finds_its_own_country(self):
        self.assertEqual(rn.find_matching_review_number('2025550125'), '+12025550125')
        self.assertEqual(rn.find_matching_review_number('7700 900126'), '+447700900126')
        self.assertEqual(rn.find_matching_review_number('202 555 0123'), '+542025550123')

    @override_settings(REVIEW_TEST_GEO_BLOCKED_PHONES_E164=['+12025550123'])
    def test_shared_national_number_is_never_guessed(self):
        # +54 and +1 both end in 2025550123: which geo rules? Neither.
        self.assertIsNone(rn.find_matching_review_number('2025550123'))
        self.assertEqual(rn.find_matching_review_number('+12025550123'), '+12025550123')

    def test_only_argentina_is_geo_exempt(self):
        def user(key):
            return SimpleNamespace(phone_key=key)
        self.assertTrue(rn.is_geo_exempt_reviewer(user('54:2025550123')))
        self.assertTrue(rn.is_geo_exempt_reviewer(user('54:2025550124')))
        for key in ('1:2025550125', '44:7700900125', '1:2025550126', '44:7700900126',
                    '1:2025550123', '57:3001234567', None):
            self.assertFalse(rn.is_geo_exempt_reviewer(user(key)), key)

    @override_settings(REVIEW_TEST_ENABLED=False)
    def test_disabled_means_no_numbers(self):
        self.assertEqual(rn.review_numbers(), [])
        self.assertFalse(rn.is_geo_exempt_reviewer(SimpleNamespace(phone_key='54:2025550123')))


def _no_ip(country):
    return mock.patch('security.geo.get_country_for_ip', return_value=country)


@override_settings(**REVIEW)
class ReviewerGeoTests(_Cached, SimpleTestCase):
    def setUp(self):
        super().setUp()
        from cusd_plus.eligibility import (
            CONFIO_STOCK_BUY_POLICY, CRYPTO_POLICY, ONDO_POLICY, PERPS_POLICY)
        from presale.geo_utils import PRESALE_POLICY
        self.policies = {
            'presale': PRESALE_POLICY, 'ondo': ONDO_POLICY, 'stock_buy': CONFIO_STOCK_BUY_POLICY,
            'crypto': CRYPTO_POLICY, 'perps': PERPS_POLICY,
        }

    def test_argentina_reviewer_passes_everything_from_a_us_ip(self):
        user = SimpleNamespace(id=1, phone_country='AR', phone_key='54:2025550123')
        with _no_ip('US'), override_settings(CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=['US']):
            for name, policy in self.policies.items():
                self.assertTrue(policy.evaluate(user).allowed, name)
                self.assertTrue(policy.phone_eligible(user), name)

    def test_us_reviewer_gets_no_bypass(self):
        user = SimpleNamespace(id=1, phone_country='US', phone_key='1:2025550125')
        with _no_ip('US'):
            for name in ('presale', 'ondo', 'crypto', 'perps'):
                self.assertFalse(self.policies[name].evaluate(user).allowed, name)

    def test_uk_reviewer_gets_no_bypass(self):
        user = SimpleNamespace(id=1, phone_country='GB', phone_key='44:7700900126')
        with _no_ip('GB'):
            for name in ('presale', 'ondo', 'crypto', 'perps'):
                self.assertFalse(self.policies[name].evaluate(user).allowed, name)

    def test_anyone_on_a_us_or_uk_ip_is_refused_presale_and_crypto(self):
        user = SimpleNamespace(id=1, phone_country='VE', phone_key='58:4121234567')
        for country in ('US', 'GB'):
            with self.subTest(country=country), _no_ip(country):
                for name in ('presale', 'crypto', 'perps'):
                    self.assertFalse(self.policies[name].evaluate(user).allowed, name)
        with _no_ip('GB'):
            self.assertIn('Reino Unido', self.policies['presale'].evaluate(user).message)

    def test_argentina_reviewer_number_without_the_feature_is_a_normal_user(self):
        user = SimpleNamespace(id=1, phone_country='AR', phone_key='54:2025550123')
        with override_settings(REVIEW_TEST_ENABLED=False), _no_ip('US'):
            _clear()
            self.assertFalse(self.policies['perps'].evaluate(user).allowed)


@override_settings(**REVIEW)
class ReviewerLinkCountryTests(_Cached, TestCase):
    def _link(self, user, phone, selected):
        from sms_verification.models import SMSVerification
        from users.phone_linking import link_verified_phone
        ver = SMSVerification.objects.create(
            user=user, phone_number=phone, code_hash='x',
            expires_at=timezone.now() + timedelta(minutes=5))
        link_verified_phone(user, ver, selected)
        user.refresh_from_db()
        return user

    def _user(self, name):
        from users.models import User
        return User.objects.create_user(
            username=name, email=f'{name}@example.com', password='x', firebase_uid=name)

    def test_reviewer_number_keeps_its_own_country_whatever_was_selected(self):
        # The app preselects Argentina; +1 alone would resolve to Samoa.
        for phone, selected, country in (('+12025550125', 'AR', 'US'),
                                         ('+12025550126', 'CA', 'US'),
                                         ('+447700900125', 'AR', 'GB'),
                                         ('+542025550124', 'US', 'AR')):
            with self.subTest(phone=phone, selected=selected):
                user = self._link(self._user(f'rv{phone[1:]}{selected}'), phone, selected)
                self.assertEqual(user.phone_country, country)

    def test_reviewer_can_switch_between_countries(self):
        user = self._user('rvswitch')
        self.assertEqual(self._link(user, '+542025550123', 'AR').phone_country, 'AR')
        self._user('rvother')  # another reviewer already shares the US number
        user = self._link(user, '+12025550125', 'AR')
        self.assertEqual((user.phone_country, user.phone_key), ('US', '1:2025550125'))
        user = self._link(user, '+447700900125', 'GB')
        self.assertEqual((user.phone_country, user.phone_key), ('GB', '44:7700900125'))

    def test_ordinary_number_still_needs_the_matching_country(self):
        from users.phone_linking import PhoneLinkError
        with self.assertRaises(PhoneLinkError):
            self._link(self._user('plain'), '+573001234567', 'AR')
