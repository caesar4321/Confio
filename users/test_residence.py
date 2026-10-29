"""User.country: signup IP, daily residence refresh, backfill (users.residence)."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from security.geo import country_of
from users.residence import backfill_country, refresh_residence_country, set_country_from_request

User = get_user_model()


class ResidenceCountryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='res-user', firebase_uid='res-user')

    @patch('users.residence._request_ip_country', return_value='co')
    def test_signup_ip_seeds_a_missing_country(self, _ip):
        # protects=a phone-less signup still gets a country; fails_when=new accounts stay country-less; no_claim=real Cloudflare header parsing
        self.assertTrue(set_country_from_request(self.user, {}))
        self.user.refresh_from_db()
        self.assertEqual((self.user.country, self.user.country_source), ('CO', 'signup_ip'))

    @patch('users.residence._request_ip_country', return_value='US')
    def test_login_ip_never_moves_a_known_country(self, _ip):
        # protects=one trip or VPN login relocates nobody; fails_when=login overwrites the stored country; no_claim=none beyond protects
        User.objects.filter(pk=self.user.pk).update(country='BO', country_source='residence')
        self.user.refresh_from_db()
        self.assertFalse(set_country_from_request(self.user, {}))
        self.user.refresh_from_db()
        self.assertEqual(self.user.country, 'BO')

    @patch('users.residence.residence_country_for', return_value='BOL')
    def test_daily_refresh_moves_to_the_residence_majority(self, _res):
        # protects=residence (ISO-3) lands as ISO-2; fails_when=the alpha-3 is stored or ignored; no_claim=the IP majority maths in security.geo
        User.objects.filter(pk=self.user.pk).update(country='AR', country_source='signup_ip')
        self.user.refresh_from_db()
        self.assertTrue(refresh_residence_country(self.user))
        self.user.refresh_from_db()
        self.assertEqual((self.user.country, self.user.country_source), ('BO', 'residence'))

    @patch('users.residence.residence_country_for', return_value=None)
    def test_daily_refresh_never_writes_null(self, _res):
        # protects="unknown today" keeps the known country; fails_when=refresh nulls a country; no_claim=none beyond protects
        User.objects.filter(pk=self.user.pk).update(country='PE', country_source='residence')
        self.user.refresh_from_db()
        self.assertFalse(refresh_residence_country(self.user))
        self.user.refresh_from_db()
        self.assertEqual(self.user.country, 'PE')

    @override_settings(REVIEW_LINK_TOKEN='t' * 40)
    @patch('users.residence.residence_country_for', return_value='ARG')
    def test_daily_refresh_leaves_review_accounts_alone(self, _res):
        # protects=a live review-link grant owns the account's country; fails_when=refresh overwrites it; no_claim=expiry restore (users/test_review_access.py)
        from datetime import timedelta
        from django.utils import timezone
        from users.models_review_access import ReviewAccess
        User.objects.filter(pk=self.user.pk).update(country='US', country_source='review')
        ReviewAccess.objects.create(user=self.user, country='US', expires_at=timezone.now() + timedelta(days=1))
        self.user.refresh_from_db()
        self.assertFalse(refresh_residence_country(self.user))
        self.user.refresh_from_db()
        self.assertEqual(self.user.country, 'US')

    @patch('users.residence.residence_country_for', return_value=None)
    def test_backfill_falls_back_to_the_verified_phone_country(self, _res):
        # protects=88% of users with no recent IP keep their phone country; fails_when=backfill leaves them null; no_claim=none beyond protects
        User.objects.filter(pk=self.user.pk).update(phone_country='VE')
        self.user.refresh_from_db()
        self.assertTrue(backfill_country(self.user))
        self.user.refresh_from_db()
        self.assertEqual((self.user.country, self.user.country_source), ('VE', 'legacy_phone'))

    @patch('users.residence.residence_country_for', return_value=None)
    @patch('users.residence._request_ip_country', return_value='BO')
    def test_login_seeds_a_phone_era_account_from_its_phone_not_the_ip(self, _ip, _res):
        # protects=a verified phone country is never replaced by one login's IP; fails_when=login seeds the request IP for a legacy account; no_claim=none beyond protects
        User.objects.filter(pk=self.user.pk).update(phone_country='US')
        self.user.refresh_from_db()
        self.assertTrue(set_country_from_request(self.user, {}))
        self.user.refresh_from_db()
        self.assertEqual((self.user.country, self.user.country_source), ('US', 'legacy_phone'))

    def test_a_forged_country_header_is_ignored_off_cloudflare(self):
        # protects=a header sent straight to the origin cannot pick a stored country; fails_when=CF-IPCountry is trusted without Cloudflare; no_claim=real Cloudflare IP ranges
        from users.residence import _request_ip_country
        meta = {'HTTP_CF_IPCOUNTRY': 'BO', 'REMOTE_ADDR': '127.0.0.1'}
        with patch('security.request_utils.came_through_cloudflare', return_value=False):
            self.assertIsNone(_request_ip_country(meta))
        with patch('security.request_utils.came_through_cloudflare', return_value=True):
            self.assertEqual(_request_ip_country(meta), 'BO')

    def test_country_of_prefers_residence_over_phone(self):
        # protects=gates read where the user lives; fails_when=the phone prefix still wins; no_claim=none beyond protects
        User.objects.filter(pk=self.user.pk).update(phone_country='VE', country='CO')
        self.user.refresh_from_db()
        self.assertEqual(country_of(self.user), 'CO')


class ReviewNumberPinTests(TestCase):
    @patch('users.residence.residence_country_for', return_value='ARG')
    def test_review_numbers_keep_their_country_over_ip(self, _res):
        # protects=a US review number shows the US blocks even from an Argentine IP; fails_when=backfill/refresh use the IP; no_claim=reviewer number configuration
        from types import SimpleNamespace
        user = User.objects.create_user(username='reviewer-us', firebase_uid='reviewer-us')
        with patch('users.review_numbers.review_number_for_key',
                   return_value=SimpleNamespace(country='US', geo_exempt=False)):
            self.assertTrue(backfill_country(user))
            user.refresh_from_db()
            self.assertEqual((user.country, user.country_source), ('US', 'review'))
            self.assertFalse(refresh_residence_country(user))
            user.refresh_from_db()
            self.assertEqual(user.country, 'US')
