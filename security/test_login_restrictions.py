from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from security.login_restrictions import login_is_restricted


class LoginRestrictionTests(SimpleTestCase):
    def test_disabled_account_denied_even_without_device(self):
        user = SimpleNamespace(is_active=False, deleted_at=None)
        self.assertTrue(login_is_restricted(user, None))

    @patch('security.login_restrictions.UserBan.objects')
    def test_active_account_with_ban_denied(self, bans):
        bans.filter.return_value.exclude.return_value.exists.return_value = True
        user = SimpleNamespace(is_active=True, deleted_at=None)
        self.assertTrue(login_is_restricted(user, None))

    @patch('security.login_restrictions.RegistrationRestriction.objects')
    def test_new_identity_on_blocked_device_denied(self, devices):
        import hashlib
        devices.filter.return_value.exists.return_value = True
        for value in ({'deviceId': 'test-device'}, '{"deviceId":"test-device"}'):
            self.assertTrue(login_is_restricted(None, value))
        devices.filter.assert_called_with(
            kind='device', value=hashlib.sha256(b'test-device').hexdigest(),
            is_active=True,
        )

    @patch('security.login_restrictions.RegistrationRestriction.objects')
    def test_unblocked_device_allowed(self, devices):
        devices.filter.return_value.exists.return_value = False
        self.assertFalse(login_is_restricted(None, {'deviceId': 'allowed'}))

    def test_missing_device_preserves_legacy_login(self):
        self.assertFalse(login_is_restricted(None, None))

    @patch('security.login_restrictions.RegistrationRestriction.objects')
    def test_new_identity_from_restricted_ip_denied(self, restrictions):
        restrictions.filter.return_value.exists.return_value = True
        self.assertTrue(login_is_restricted(None, None, {'REMOTE_ADDR': '2001:db8:0::1'}))
        restrictions.filter.assert_called_with(kind='ip', value='2001:db8::1', is_active=True)

    @patch('security.login_restrictions.RegistrationRestriction.objects')
    @patch('security.login_restrictions.UserBan.objects')
    def test_existing_unbanned_user_keeps_access_from_restricted_source(self, bans, restrictions):
        bans.filter.return_value.exclude.return_value.exists.return_value = False
        user = SimpleNamespace(is_active=True, deleted_at=None)
        self.assertFalse(login_is_restricted(user, {'deviceId': 'blocked'}, {'REMOTE_ADDR': '192.0.2.1'}))
        restrictions.filter.assert_not_called()

    @patch('firebase_admin.auth.verify_id_token', return_value={'uid': 'new-id'})
    @patch('security.login_restrictions.login_is_restricted', return_value=True)
    @patch('users.models.User.objects.get_or_create')
    @patch('users.models.User.all_objects.filter')
    def test_blocked_login_never_creates_user(self, users, create, restricted, verify):
        from users.web3auth_schema import Web3AuthLoginMutation
        users.return_value.first.return_value = None
        result = Web3AuthLoginMutation.mutate(
            None, SimpleNamespace(context=SimpleNamespace()),
            firebase_id_token='test', device_fingerprint={'deviceId': 'blocked'},
        )
        self.assertFalse(result.success)
        self.assertIsNone(result.access_token)
        create.assert_not_called()
