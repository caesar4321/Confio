from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from notifications.models import FCMDeviceToken, Notification
from users.models import User


class NotifyOutdatedBuildsTests(TestCase):
    def _user(self, name, *devices):
        user = User.objects.create(username=name, firebase_uid=name)
        for i, (platform, version, age_min) in enumerate(devices):
            token = FCMDeviceToken.objects.create(
                user=user, token=f'{name}-{i}', device_type=platform, device_id=f'{name}-{i}',
                app_version=version, is_active=True,
                # A push delivery bumps last_used on every device: never the signal.
                last_used=timezone.now())
            # Registration (app start) is what moves updated_at.
            FCMDeviceToken.objects.filter(pk=token.pk).update(
                updated_at=timezone.now() - timedelta(minutes=age_min))
        return user

    def _run(self, *args):
        out = StringIO()
        with mock.patch('notifications.utils.send_push_notification', return_value={'success': True}) as push:
            call_command('notify_outdated_builds', '--below', '5.2.6', *args, stdout=out)
        return out.getvalue(), push

    def test_main_device_decides_and_unreadable_versions_are_skipped(self):
        old = self._user('old', ('android', '5.2.4', 1))
        self._user('updated_main', ('ios', '5.1.0', 60), ('ios', '5.2.6', 1))
        self._user('garbled', ('android', 'dev-build', 1))
        out, push = self._run('--send')
        self.assertIn('below 5.2.6: 1 (skipped 1', out)
        notices = Notification.objects.filter(notification_type='ANNOUNCEMENT')
        self.assertEqual(list(notices.values_list('user_id', flat=True)), [old.id])
        notice = notices.get()
        self.assertIn('Google Play', notice.message)
        self.assertIsNone(notice.action_url)  # older builds can't open store links
        self.assertIn('play.google.com', notice.data['store_url'])
        self.assertEqual(push.call_count, 1)

    def test_dry_run_sends_nothing(self):
        self._user('old', ('android', '4.1.0', 1))
        out, push = self._run()
        self.assertIn('DRY RUN', out)
        self.assertFalse(Notification.objects.exists())
        push.assert_not_called()

    def test_platform_filter_never_overrides_the_main_device(self):
        # Main phone is an updated iPhone; an old Android token lingers.
        self._user('iphone_main', ('ios', '5.2.6', 1), ('android', '5.1.0', 90))
        out, push = self._run('--platform', 'android', '--send')
        self.assertIn('below 5.2.6: 0', out)
        push.assert_not_called()
