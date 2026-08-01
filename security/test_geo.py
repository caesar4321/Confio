"""The geo refactor must not have changed either policy's answer.

presale and cusd_plus each had their own phone+IP pair; the mechanism is now
shared (security/geo.py) and each feature supplies only its policy. These
pin the semantics that were in force BEFORE the move — including the two
places the features deliberately disagree — so the refactor is provably
behaviour-preserving on two legal controls.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from security.geo import GeoDecision


def _user(country, phone_key=None):
    return SimpleNamespace(id=1, phone_country=country, phone_key=phone_key)


def _no_ip(country=None):
    """Pin IP resolution so these tests exercise policy, not the network."""
    return mock.patch('security.geo.get_country_for_ip', return_value=country)


class OndoPolicyTests(SimpleTestCase):
    def setUp(self):
        from cusd_plus.eligibility import ONDO_POLICY
        self.policy = ONDO_POLICY

    def test_blocked_phone_country_refused(self):
        with _no_ip():
            self.assertFalse(self.policy.evaluate(_user('US')).allowed)

    def test_eligible_phone_country_allowed(self):
        with _no_ip():
            self.assertTrue(self.policy.evaluate(_user('VE')).allowed)

    def test_missing_phone_country_fails_CLOSED(self):
        # The documented Ondo posture: no verified country means we cannot
        # attest a jurisdiction.
        with _no_ip():
            self.assertFalse(self.policy.evaluate(_user(None)).allowed)
        self.assertFalse(self.policy.phone_eligible(_user(None)))

    def test_eligible_phone_but_blocked_ip_refused(self):
        # The bug this whole refactor came from: phone says yes, IP says no.
        with _no_ip('US'):
            decision = self.policy.evaluate(_user('VE'), {})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_by, 'ip')

    def test_unresolvable_ip_fails_OPEN(self):
        with _no_ip(None):
            self.assertTrue(self.policy.evaluate(_user('VE'), {}).allowed)

    def test_resolver_raising_fails_OPEN(self):
        # An outage must not strand an attested-eligible user's mint.
        with mock.patch('security.geo.get_country_for_ip',
                        side_effect=RuntimeError('resolver down')):
            self.assertTrue(self.policy.evaluate(_user('VE')).allowed)

    def test_phone_eligible_ignores_ip_by_design(self):
        # The half-check is for callers with no request (Celery, recipients).
        with _no_ip('US'):
            self.assertTrue(self.policy.phone_eligible(_user('VE')))


class PresalePolicyTests(SimpleTestCase):
    def setUp(self):
        from presale.geo_utils import PRESALE_POLICY, US_BLOCK_MSG, KR_BLOCK_MSG
        self.policy = PRESALE_POLICY
        self.us_msg, self.kr_msg = US_BLOCK_MSG, KR_BLOCK_MSG

    def test_us_and_kr_phone_get_their_own_copy(self):
        with _no_ip():
            self.assertEqual(self.policy.evaluate(_user('US')).message, self.us_msg)
            self.assertEqual(self.policy.evaluate(_user('KR')).message, self.kr_msg)

    def test_missing_phone_country_fails_OPEN(self):
        # DIVERGES from Ondo on purpose, and now says so out loud.
        with _no_ip():
            self.assertTrue(self.policy.evaluate(_user(None)).allowed)

    @override_settings(PRESALE_IP_BLOCKED_COUNTRIES=['US'])
    def test_blocked_ip_refused_with_the_us_copy(self):
        with _no_ip('US'):
            decision = self.policy.evaluate(_user('VE'))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.message, self.us_msg)

    @override_settings(PRESALE_IP_BLOCKED_COUNTRIES=[])
    def test_empty_ip_list_skips_the_ip_check(self):
        with _no_ip('US'):
            self.assertTrue(self.policy.evaluate(_user('VE')).allowed)

    @override_settings(PRESALE_IP_BLOCKED_COUNTRIES=['BR'])
    def test_ip_list_is_read_at_call_time(self):
        # It comes from a Django setting, so it must not be frozen at import.
        with _no_ip('BR'):
            self.assertFalse(self.policy.evaluate(_user('VE')).allowed)

    def test_ip_list_is_separate_from_the_phone_list(self):
        # KR blocks by phone but is NOT in the default IP list.
        with override_settings(PRESALE_IP_BLOCKED_COUNTRIES=['US']), _no_ip('KR'):
            self.assertTrue(self.policy.evaluate(_user('VE')).allowed)

    def test_resolver_raising_PROPAGATES(self):
        # Preserved: presale never swallowed a resolver error.
        with mock.patch('security.geo.get_country_for_ip',
                        side_effect=RuntimeError('resolver down')):
            with self.assertRaises(RuntimeError):
                self.policy.evaluate(_user('VE'))

    def test_review_account_bypasses_everything(self):
        with mock.patch('users.review_numbers.is_review_test_phone_key',
                        return_value=True), _no_ip('US'):
            self.assertTrue(self.policy.evaluate(_user('US', 'k')).allowed)

    def test_legacy_wrapper_still_returns_bool_and_message(self):
        from presale.geo_utils import check_presale_eligibility
        with _no_ip():
            ok, msg = check_presale_eligibility(_user('US'))
        self.assertFalse(ok)
        self.assertEqual(msg, self.us_msg)


class DecisionTests(SimpleTestCase):
    def test_decision_is_truthy_by_allowance(self):
        self.assertTrue(bool(GeoDecision(True)))
        self.assertFalse(bool(GeoDecision(False, 'nope', 'phone')))
