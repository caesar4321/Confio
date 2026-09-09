from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from security.app_check_diagnostics import login_diagnostics
from security.integrity_service import app_check_service
from security.models import IntegrityVerdict
from users.web3auth_schema import Web3AuthLoginMutation


class LoginAttestationTests(TestCase):
    def setUp(self):
        self.request = SimpleNamespace(META={}, headers={
            'X-Confio-Build': '123', 'X-Confio-Platform': 'android',
            'X-AppCheck-Debug-Error': 'app attestation failed: secret@example.com\nforged log',
        })
        self.claims = {'uid': 'new-attestation-user', 'email': 'test@example.com',
                       'firebase': {'sign_in_provider': 'google.com'}}

    def login(self):
        with patch('firebase_admin.auth.verify_id_token', return_value=self.claims), \
                patch('security.login_restrictions.login_is_restricted', return_value=False):
            return Web3AuthLoginMutation.mutate(
                None, SimpleNamespace(context=self.request), firebase_id_token='identity-token')

    @override_settings(APP_CHECK_ENFORCE=True)
    def test_rejected_signup_records_sanitized_verdict_without_creating_user(self):
        result = self.login()
        self.assertFalse(result.success)
        self.assertFalse(get_user_model().objects.filter(firebase_uid=self.claims['uid']).exists())
        verdict = IntegrityVerdict.objects.get()
        self.assertIsNone(verdict.user_id)
        self.assertEqual(verdict.trigger_action, 'signup')
        self.assertEqual(verdict.raw_response['login_diagnostics']['client_error_code'], 'attestation_rejected')
        self.assertEqual(verdict.raw_response['login_diagnostics']['client_build'], '123')
        self.assertNotIn('secret@example.com', str(verdict.raw_response))
        self.assertIn('Pre-signup', str(verdict))

    @override_settings(APP_CHECK_ENFORCE=False)
    def test_warning_policy_reaches_account_creation_without_attestation(self):
        # Stop at the downstream account boundary; no wallet/chain work in this test.
        with patch('users.web3auth_schema.User.objects.get_or_create', side_effect=RuntimeError('downstream test stop')) as create:
            self.login()
        create.assert_called_once()
        self.assertFalse(IntegrityVerdict.objects.get().passed)

    @override_settings(APP_CHECK_ENFORCE=True)
    def test_valid_attestation_reaches_account_creation(self):
        self.request.headers['X-Firebase-AppCheck'] = 'attestation-token'
        with patch.object(app_check_service, 'verify_token', return_value={'valid': True}), \
                patch('users.web3auth_schema.User.objects.get_or_create', side_effect=RuntimeError('downstream test stop')) as create:
            self.login()
        create.assert_called_once()
        self.assertTrue(IntegrityVerdict.objects.get().passed)

    @override_settings(APP_CHECK_ENFORCE=True)
    def test_invalid_attestation_is_rejected_and_token_is_not_in_diagnostics(self):
        self.request.headers['X-Firebase-AppCheck'] = 'private-attestation-token'
        with patch.object(app_check_service, 'verify_token', return_value={'valid': False, 'error': 'INVALID_TOKEN'}):
            result = self.login()
        self.assertFalse(result.success)
        self.assertFalse(get_user_model().objects.filter(firebase_uid=self.claims['uid']).exists())
        verdict = IntegrityVerdict.objects.get()
        self.assertTrue(verdict.raw_response['login_diagnostics']['enforced'])
        self.assertNotIn('private-attestation-token', str(verdict.raw_response))

    @override_settings(APP_CHECK_ENFORCE=False)
    def test_kill_switch_is_global_not_login_only(self):
        # Deliberately all-or-nothing. An earlier revision enforced sensitive
        # operations even with login relaxed; that only moved the dead end from
        # sign-in to the first payment. Callers still pass should_enforce=True —
        # the switch is resolved centrally so they cannot opt out of it.
        for action in ('payment', 'transfer', 'payroll', 'reward_claim', 'topup_sell'):
            result = app_check_service.verify_and_record(
                user=None, token='', action=action, should_enforce=True)
            self.assertTrue(result['success'], action)
            self.assertFalse(result['passed'], action)  # telemetry still recorded
            self.assertFalse(result['is_blocked'], action)

    @override_settings(APP_CHECK_ENFORCE=True)
    def test_sensitive_operations_block_while_switch_is_on(self):
        result = app_check_service.verify_and_record(
            user=None, token='', action='payment', should_enforce=True)
        self.assertFalse(result['success'])
        self.assertTrue(result['is_blocked'])

    @override_settings(APP_CHECK_ENFORCE=False)
    def test_invalid_identity_token_still_rejected_without_verdict_or_account(self):
        with patch('firebase_admin.auth.verify_id_token', side_effect=ValueError('invalid')):
            result = Web3AuthLoginMutation.mutate(None, SimpleNamespace(context=self.request), firebase_id_token='bad')
        self.assertFalse(result.success)
        self.assertFalse(IntegrityVerdict.objects.exists())
        self.assertFalse(get_user_model().objects.filter(firebase_uid=self.claims['uid']).exists())

    def test_untrusted_headers_never_become_raw_diagnostics(self):
        self.request.headers = {'X-AppCheck-Debug-Error': 'private-token\r\nsecret',
                                'X-Confio-Build': 'email@example.com', 'X-Confio-Platform': 'secret'}
        self.assertEqual(login_diagnostics(self.request), {
            'client_error_code': 'unknown', 'client_build': 'unknown',
            'client_platform': 'unknown', 'client_reported': True})

    @override_settings(APP_CHECK_ENFORCE=True)
    def test_existing_user_failure_remains_linked_without_profile_mutation(self):
        user = get_user_model().objects.create_user(
            username='attestation-existing', firebase_uid=self.claims['uid'])
        result = self.login()
        self.assertFalse(result.success)
        verdict = IntegrityVerdict.objects.get()
        self.assertEqual(verdict.user_id, user.id)
        self.assertEqual(verdict.trigger_action, 'login')
        user.refresh_from_db()
        self.assertEqual(user.username, 'attestation-existing')

    @override_settings(APP_CHECK_ENFORCE=False)
    def test_account_restrictions_precede_attestation_policy(self):
        with patch('firebase_admin.auth.verify_id_token', return_value=self.claims), \
                patch('security.login_restrictions.login_is_restricted', return_value=True):
            result = Web3AuthLoginMutation.mutate(None, SimpleNamespace(context=self.request), firebase_id_token='identity-token')
        self.assertFalse(result.success)
        self.assertFalse(IntegrityVerdict.objects.exists())
        self.assertFalse(get_user_model().objects.filter(firebase_uid=self.claims['uid']).exists())
