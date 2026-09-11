from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from sms_verification.schema import VerifySMSCode
from telegram_verification.schema import VerifyTelegramCode
from users.test_phone_relinking import PhoneRelinkingTests


@override_settings(REVIEW_TEST_ENABLED=False, TELEGRAM_API_TOKEN='test')
class PhonePreviewRecoveryTests(TestCase):
    phone = PhoneRelinkingTests.phone
    e164 = PhoneRelinkingTests.e164
    setUp = PhoneRelinkingTests.setUp
    verify = PhoneRelinkingTests.verify

    def retry(self, channel, code='123456', user=None):
        info = SimpleNamespace(context=SimpleNamespace(user=user or self.new))
        if channel == 'sms':
            with patch('sms_verification.schema._lookup_e164', return_value=self.e164), \
                 patch('sms_verification.schema.check_verification') as provider:
                result = VerifySMSCode.mutate(None, info, self.phone, 'CO', code)
        else:
            with patch('telegram_verification.schema.lookup_phone_number', return_value=self.e164), \
                 patch('telegram_verification.schema.requests.post') as provider:
                result = VerifyTelegramCode.mutate(None, info, self.phone, 'CO', code)
        provider.assert_not_called()
        return result

    def test_lost_preview_retries_without_rechecking_consumed_provider_code(self):
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                _, proof = self.verify(channel, confirm=False)
                self.assertEqual(len(proof.approved_code_hash), 64)
                self.assertFalse(proof.is_verified)
                result = self.retry(channel)
                self.assertFalse(result.success)
                self.assertEqual(result.relink_confirmation.accounts[0].email, 'pr•••@example.com')
                self.old.refresh_from_db()
                self.assertEqual(self.old.phone_key, '57:3132587634')
                self.claim.assert_not_called()

    def test_cached_approval_never_discloses_account_for_wrong_code_and_caps_attempts(self):
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                _, proof = self.verify(channel, confirm=False)
                for _ in range(5):
                    result = self.retry(channel, '654321')
                    self.assertFalse(result.success)
                    self.assertIsNone(result.relink_confirmation)
                proof.refresh_from_db()
                self.assertEqual(proof.attempts, 5)
                result = self.retry(channel)
                self.assertFalse(result.success)
                self.assertIsNone(result.relink_confirmation)

    def test_wrong_retry_does_not_prevent_correct_retry_before_limit(self):
        for channel in ('sms', 'telegram'):
            self.verify(channel, confirm=False)
            self.assertIsNone(self.retry(channel, '000000').relink_confirmation)
            self.assertIsNotNone(self.retry(channel).relink_confirmation)

    def test_expired_cached_approval_cannot_disclose_account(self):
        for channel in ('sms', 'telegram'):
            _, proof = self.verify(channel, confirm=False)
            proof.expires_at = timezone.now() - timedelta(seconds=1)
            proof.save(update_fields=['expires_at'])
            result = self.retry(channel)
            self.assertFalse(result.success)
            self.assertIsNone(result.relink_confirmation)

    def test_cached_approval_is_bound_to_user_and_request(self):
        for channel in ('sms', 'telegram'):
            _, proof = self.verify(channel, confirm=False)
            result = self.retry(channel, user=self.old)
            self.assertFalse(result.success)
            self.assertIsNone(result.relink_confirmation)
            # Copying an approval hash onto a fresh request grants no approval.
            proof.pk = None
            if channel == 'telegram':
                proof.request_id = 'replacement-request'
            proof.save()
            result = self.retry(channel)
            self.assertFalse(result.success)
            self.assertIsNone(result.relink_confirmation)
