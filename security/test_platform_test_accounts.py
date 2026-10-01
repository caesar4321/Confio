from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from security import platform_test_accounts as pta
from security.models import IntegrityVerdict


class GoogleNetworkTests(SimpleTestCase):
    def test_google_prelaunch_ranges(self):
        for ip in ('66.249.84.131', '74.125.210.64', '66.102.7.72', '192.178.11.132'):
            self.assertTrue(pta.is_google_network(ip), ip)
        for ip in ('158.172.227.34', '50.218.251.4', '', 'not-an-ip'):
            self.assertFalse(pta.is_google_network(ip), ip)


class PrelaunchTaggingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='robot', firebase_uid='robot-uid')

    def test_google_network_and_no_app_check_ever_tags(self):
        IntegrityVerdict.objects.create(user=None, device_fingerprint='fp-robot', passed=False,
                                        trigger_action='signup', app_licensing='MISSING_TOKEN')
        self.assertTrue(pta.tag_if_prelaunch_robot(self.user, '66.249.84.131', 'fp-robot'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_platform_test_account)

    def test_a_device_that_passed_app_check_is_a_real_user(self):
        IntegrityVerdict.objects.create(user=self.user, device_fingerprint='fp-real', passed=True,
                                        trigger_action='login')
        self.assertFalse(pta.tag_if_prelaunch_robot(self.user, '66.249.84.131', 'fp-real'))

    def test_outside_google_networks_is_never_tagged(self):
        self.assertFalse(pta.tag_if_prelaunch_robot(self.user, '158.172.227.34', 'fp-robot'))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_platform_test_account)

    def test_analytics_leave_tagged_accounts_out(self):
        from users.analytics import get_real_users_queryset
        get_user_model().objects.filter(pk=self.user.pk).update(phone_number='+5491100000000', is_platform_test_account=True)
        self.assertFalse(get_real_users_queryset().filter(pk=self.user.pk).exists())

    def test_other_accounts_on_a_robot_device_are_tagged_from_any_network(self):
        from django.utils import timezone
        from security.models import DeviceFingerprint, IPAddress, IPDeviceUser
        device = DeviceFingerprint.objects.create(fingerprint='fp-lab', device_details={})
        first = get_user_model().objects.create(username='robot-1', firebase_uid='robot-1')
        google = IPAddress.objects.create(ip_address='66.249.84.131', first_seen=timezone.now(), last_seen=timezone.now())
        IPDeviceUser.objects.create(ip_address=google, device_fingerprint=device, user=first,
                                    first_seen=timezone.now(), last_seen=timezone.now())
        # One account seen on Google: could be a real phone behind a Google proxy.
        self.assertFalse(pta.tag_if_prelaunch_robot(self.user, '50.218.251.4', 'fp-lab'))
        second = get_user_model().objects.create(username='robot-2', firebase_uid='robot-2')
        IPDeviceUser.objects.create(ip_address=google, device_fingerprint=device, user=second,
                                    first_seen=timezone.now(), last_seen=timezone.now())
        self.assertTrue(pta.tag_if_prelaunch_robot(self.user, '50.218.251.4', 'fp-lab'))
        # A real device on that same non-Google network is left alone.
        other = get_user_model().objects.create(username='person', firebase_uid='person')
        self.assertFalse(pta.tag_if_prelaunch_robot(other, '50.218.251.4', 'fp-phone'))
