from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from config.admin_dashboard import get_fcm_reachability_metrics

from .fcm_service import register_device_token
from .models import FCMDeviceToken


User = get_user_model()


class FCMDeviceRegistrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='fcm-user',
            email='fcm-user@example.com',
            password='testpass123',
            firebase_uid='firebase-fcm-user',
        )

    def test_registration_reactivates_current_token_and_deactivates_replaced_token(self):
        old_token = FCMDeviceToken.objects.create(
            user=self.user,
            token='old-token',
            device_type='ios',
            device_id='device-1',
        )
        current_token = FCMDeviceToken.objects.create(
            user=self.user,
            token='current-token',
            device_type='ios',
            device_id='device-1',
            is_active=False,
            failure_count=5,
            last_failure=timezone.now(),
            last_failure_reason='previous failure',
        )

        registered = register_device_token(
            user=self.user,
            token='current-token',
            device_type='ios',
            device_id='device-1',
            device_name='Test iPhone',
            app_version='4.5.2',
        )

        old_token.refresh_from_db()
        current_token.refresh_from_db()
        self.assertEqual(registered.pk, current_token.pk)
        self.assertFalse(old_token.is_active)
        self.assertTrue(current_token.is_active)
        self.assertEqual(current_token.failure_count, 0)
        self.assertIsNone(current_token.last_failure)
        self.assertEqual(current_token.device_name, 'Test iPhone')
        self.assertEqual(current_token.app_version, '4.5.2')

    def test_reachability_metrics_include_users_without_phone_numbers(self):
        second_user = User.objects.create_user(
            username='second-fcm-user',
            email='second-fcm-user@example.com',
            password='testpass123',
            firebase_uid='firebase-second-fcm-user',
        )
        inactive_user = User.objects.create_user(
            username='inactive-fcm-user',
            email='inactive-fcm-user@example.com',
            password='testpass123',
            firebase_uid='firebase-inactive-fcm-user',
        )
        now = timezone.now()
        FCMDeviceToken.objects.create(
            user=self.user,
            token='first-active-token',
            device_type='ios',
            last_used=now,
        )
        FCMDeviceToken.objects.create(
            user=self.user,
            token='second-active-token',
            device_type='ios',
            last_used=now,
        )
        FCMDeviceToken.objects.create(
            user=second_user,
            token='old-active-token',
            device_type='android',
            last_used=now - timedelta(days=31),
        )
        FCMDeviceToken.objects.create(
            user=inactive_user,
            token='inactive-token',
            device_type='android',
            is_active=False,
            last_used=now,
        )

        metrics = get_fcm_reachability_metrics(now)

        self.assertEqual(metrics, {
            'active_users': 2,
            'recent_users': 1,
            'active_tokens': 3,
        })
