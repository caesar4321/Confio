"""The store-review deep link (users/review_access.py)."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from security.geo import store_review_exempt
from users.models_review_access import ReviewAccess
from users.review_access import apply_review_access

User = get_user_model()
TOKEN = 'r' * 40


@override_settings(REVIEW_LINK_TOKEN=TOKEN, REVIEW_LINK_MONTHLY_CAP=2)
@patch('users.review_access._alert')
class ReviewAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='reviewer', firebase_uid='reviewer')
        User.objects.filter(pk=self.user.pk).update(country='US', country_source='signup_ip')
        self.user.refresh_from_db()

    def test_argentina_link_exempts_and_us_link_does_not(self, _alert):
        # protects=AR shows every feature, US shows the blocks; fails_when=US gets the exemption; no_claim=each product's own policy lists
        self.assertEqual(apply_review_access(self.user, 'ar', TOKEN), (True, None))
        self.assertTrue(store_review_exempt(self.user))
        self.assertEqual(apply_review_access(self.user, 'US', TOKEN), (True, None))
        self.assertFalse(store_review_exempt(self.user))
        self.user.refresh_from_db()
        self.assertEqual((self.user.country, self.user.country_source), ('US', 'review'))

    def test_wrong_token_fails_and_the_sixth_failure_is_rate_limited(self, _alert):
        # protects=the token cannot be guessed online; fails_when=unlimited attempts; no_claim=cache durability
        for _ in range(5):
            self.assertEqual(apply_review_access(self.user, 'AR', 'nope')[1], 'Enlace inválido.')
        self.assertIn('Demasiados intentos', apply_review_access(self.user, 'AR', TOKEN)[1])

    def test_reapplying_keeps_history_and_the_monthly_cap_counts_it(self, _alert):
        # protects=a leaked AR link opens at most CAP exempt grants a month; fails_when=re-applies dodge the count; no_claim=month boundaries
        other = User.objects.create_user(username='reviewer-2', firebase_uid='reviewer-2')
        self.assertTrue(apply_review_access(self.user, 'AR', TOKEN)[0])
        ReviewAccess.objects.filter(user=self.user).update(created_at=timezone.now() - timedelta(minutes=5))
        self.assertTrue(apply_review_access(self.user, 'AR', TOKEN)[0])
        self.assertEqual(ReviewAccess.objects.filter(user=self.user).count(), 2)
        self.assertEqual(ReviewAccess.objects.filter(user=self.user, superseded_at__isnull=True).count(), 1)
        ok, error = apply_review_access(other, 'AR', TOKEN)
        self.assertFalse(ok)
        self.assertIn('ya no está disponible', error)

    def test_the_same_link_delivered_twice_is_one_grant(self, _alert):
        # protects=a double delivery (cold start + listener) counts once toward the cap; fails_when=two rows 15 ms apart; no_claim=a deliberate re-open later (counts, see above)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(apply_review_access(self.user, 'AR', TOKEN), (True, None))
            self.assertEqual(apply_review_access(self.user, 'AR', TOKEN), (True, None))
        self.assertEqual(ReviewAccess.objects.filter(user=self.user).count(), 1)
        self.assertEqual(_alert.call_count, 1)

    def test_clearing_the_token_ends_every_grant(self, _alert):
        # protects=one setting switches all grants off; fails_when=grants outlive the token; no_claim=none beyond protects
        apply_review_access(self.user, 'AR', TOKEN)
        with override_settings(REVIEW_LINK_TOKEN=''):
            self.assertFalse(store_review_exempt(self.user))

    @patch('users.residence.residence_country_for', return_value=None)
    def test_an_ended_grant_restores_the_previous_country(self, _res, _alert):
        # protects=a reviewer account gets its own country back; fails_when=it stays on the review country forever; no_claim=none beyond protects
        from users.residence import refresh_residence_country
        apply_review_access(self.user, 'AR', TOKEN)
        ReviewAccess.objects.filter(user=self.user).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.user.refresh_from_db()
        self.assertTrue(refresh_residence_country(self.user))
        self.user.refresh_from_db()
        self.assertEqual((self.user.country, self.user.country_source), ('US', 'signup_ip'))
