import hashlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from config.admin_dashboard import confio_admin_site
from users.admin import UserAdmin
from users.models import Account

User = get_user_model()


class CloudKitAdminColumnTests(TestCase):
    def setUp(self):
        self.admin = UserAdmin(User, confio_admin_site)

    def _user(self, **fields):
        return User(username='ck_admin', firebase_uid='ck_admin', **fields)

    def test_a_proven_copy_shows_with_its_build(self):
        html = self.admin.cloudkit_display(self._user(
            cloudkit_backup_state='proven', cloudkit_backup_verified_at=timezone.now(),
            last_app_platform='ios', last_app_version='5.3.5'))
        self.assertIn('Proven', html)
        self.assertIn('ios 5.3.5', html)

    def test_no_report_shows_the_build_that_explains_it(self):
        html = self.admin.cloudkit_display(self._user(last_app_platform='ios', last_app_version='5.2.1'))
        self.assertIn('No report', html)
        self.assertIn('ios 5.2.1', html)

    def test_a_full_icloud_was_never_proven(self):
        html = self.admin.cloudkit_display(self._user(cloudkit_backup_state='icloud_full'))
        self.assertIn('iCloud full', html)
        self.assertIn('never proven', html)

    def test_a_proof_of_another_wallet_shows_as_stale(self):
        user = self._user(cloudkit_backup_state='proven', cloudkit_backup_verified_at=timezone.now(),
                          cloudkit_backup_wallet_hash=hashlib.sha256(b'0xold').hexdigest())
        user.personal_bsc_address = '0xNEW'
        self.assertIn('Stale', self.admin.cloudkit_display(user))
        user.personal_bsc_address = '0xOLD'
        self.assertIn('Proven', self.admin.cloudkit_display(user))

    def test_the_list_query_carries_the_registered_address(self):
        user = User.objects.create_user(username='ck_admin_q', firebase_uid='ck_admin_q')
        Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address='0xABC')
        row = self.admin.get_queryset(None).get(pk=user.pk)
        self.assertEqual(row.personal_bsc_address, '0xABC')

    def test_device_text_is_escaped(self):
        html = self.admin.cloudkit_display(self._user(last_app_version='<b>x'))
        self.assertIn('&lt;b&gt;x', html)

    def test_the_admin_configuration_is_valid(self):
        self.assertEqual(self.admin.check(), [])
