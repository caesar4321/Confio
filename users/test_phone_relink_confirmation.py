from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase, override_settings
from django.utils import timezone

from users.models import User
from users.phone_link_schema import ConfirmPhoneRelink
from users.test_phone_relinking import PhoneRelinkingTests


# Reuse mutation fixtures, not their test methods.
@override_settings(REVIEW_TEST_ENABLED=False, TELEGRAM_API_TOKEN='test')
class PhoneRelinkConfirmationTests(TestCase):
    phone = PhoneRelinkingTests.phone
    e164 = PhoneRelinkingTests.e164
    setUp = PhoneRelinkingTests.setUp
    verify = PhoneRelinkingTests.verify

    def confirm(self, token, user=None):
        return ConfirmPhoneRelink.mutate(None,
            SimpleNamespace(context=SimpleNamespace(user=user or self.new)), token)

    def test_both_channels_show_account_without_transferring_until_confirmed(self):
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                result, proof = self.verify(channel, confirm=False)
                self.assertFalse(result.success)
                self.assertIsNotNone(result.relink_confirmation)
                self.assertEqual(result.relink_confirmation.accounts[0].email, 'previous@example.com')
                self.assertEqual(result.relink_confirmation.accounts[0].username, 'old')
                self.assertFalse(proof.is_verified)
                self.assertEqual(self.old.phone_key, '57:3132587634')
                self.assertIsNone(self.new.phone_key)
                self.claim.assert_not_called()
        result = self.confirm(result.relink_confirmation.token)
        self.assertTrue(result.success, result.error)
        self.old.refresh_from_db()
        self.new.refresh_from_db()
        self.assertIsNone(self.old.phone_key)
        self.assertEqual(self.new.phone_key, '57:3132587634')
        self.claim.assert_called_once()

    def test_invalid_code_does_not_disclose_account(self):
        for channel in ('sms', 'telegram'):
            result, _ = self.verify(channel, valid=False, confirm=False)
            self.assertFalse(result.success)
            self.assertIsNone(result.relink_confirmation)

    def test_cancel_leaves_original_link_and_proof_unconsumed(self):
        _, proof = self.verify('sms', confirm=False)
        self.assertFalse(proof.is_verified)
        self.assertEqual(self.old.phone_key, '57:3132587634')
        self.assertIsNone(self.new.phone_key)
        self.claim.assert_not_called()

    def test_foreign_and_tampered_tokens_do_not_transfer_or_disclose(self):
        result, _ = self.verify('sms', confirm=False)
        token = result.relink_confirmation.token
        for candidate, user in ((token, self.old), (token + 'tampered', self.new)):
            result = self.confirm(candidate, user)
            self.assertFalse(result.success)
            self.assertIsNone(result.relink_confirmation)
        self.old.refresh_from_db()
        self.assertEqual(self.old.phone_key, '57:3132587634')

    def test_expired_proof_cannot_be_confirmed(self):
        result, proof = self.verify('sms', confirm=False)
        proof.expires_at = timezone.now() - timedelta(seconds=1)
        proof.save(update_fields=['expires_at'])
        result = self.confirm(result.relink_confirmation.token)
        self.assertFalse(result.success)
        self.assertIsNone(result.relink_confirmation)
        self.old.refresh_from_db()
        self.assertEqual(self.old.phone_key, '57:3132587634')

    def test_changed_owner_requires_new_account_preview(self):
        result, _ = self.verify('sms', confirm=False)
        self.old.phone_number = None
        self.old.save()
        replacement = User.objects.create_user(username='replacement', firebase_uid='replacement',
            email='replacement@example.com', phone_country='CO', phone_number=self.phone)
        result = self.confirm(result.relink_confirmation.token)
        self.assertFalse(result.success)
        self.assertEqual(result.relink_confirmation.accounts[0].email, replacement.email)
        replacement.refresh_from_db()
        self.assertEqual(replacement.phone_key, '57:3132587634')
        self.assertTrue(self.confirm(result.relink_confirmation.token).success)

    def test_transient_confirmation_failure_can_retry_same_token(self):
        from unittest.mock import patch
        result, proof = self.verify('sms', confirm=False)
        token = result.relink_confirmation.token
        with patch('users.phone_link_schema.link_verified_phone', side_effect=RuntimeError('temporary')):
            result = self.confirm(token)
        self.assertTrue(result.retryable)
        self.assertFalse(result.success)
        proof.refresh_from_db()
        self.assertFalse(proof.is_verified)
        self.assertTrue(self.confirm(token).success)
        self.assertFalse(self.confirm(token + 'invalid').retryable)

    def test_retry_acknowledges_completed_link_without_retransferring(self):
        result, proof = self.verify('sms', confirm=False)
        token = result.relink_confirmation.token
        self.assertTrue(self.confirm(token).success)
        self.assertTrue(self.confirm(token).success)
        # Once the phone moves again, the consumed proof cannot take it back.
        User.objects.filter(pk=self.new.pk).update(phone_number=None, phone_country=None, phone_key=None)
        self.old.refresh_from_db()
        self.old.phone_number = self.phone
        self.old.phone_country = 'CO'
        self.old.save()
        result = self.confirm(token)
        self.assertFalse(result.success)
        self.assertIsNone(result.relink_confirmation)
        self.old.refresh_from_db()
        self.assertEqual(self.old.phone_key, '57:3132587634')

    def test_signed_confirmation_expires_even_if_proof_is_still_active(self):
        from unittest.mock import patch
        result, proof = self.verify('sms', confirm=False)
        proof.expires_at = timezone.now() + timedelta(hours=1)
        proof.save(update_fields=['expires_at'])
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 601):
            result = self.confirm(result.relink_confirmation.token)
        self.assertFalse(result.success)
        self.assertIsNone(result.relink_confirmation)

    def test_graphql_exposes_preview_and_confirmation_mutation(self):
        from unittest.mock import patch
        import graphene
        from sms_verification.models import SMSVerification
        from sms_verification.schema import VerifySMSCode
        from users.schema import Mutation as UserMutation

        class Query(graphene.ObjectType):
            ping = graphene.String()

        class Mutation(graphene.ObjectType):
            verify_sms_code = VerifySMSCode.Field()
            confirm_phone_relink = ConfirmPhoneRelink.Field()

        self.assertIn('confirm_phone_relink', UserMutation._meta.fields)
        schema = graphene.Schema(query=Query, mutation=Mutation)
        SMSVerification.objects.create(user=self.new, phone_number=self.e164, code_hash='unused',
                                       expires_at=timezone.now() + timedelta(minutes=5))
        with patch('sms_verification.schema._lookup_e164', return_value=self.e164), \
             patch('sms_verification.schema.check_verification', return_value=(True, 'approved')):
            result = schema.execute('''mutation {
              verifySmsCode(phoneNumber: "3132587634", countryCode: "CO", code: "123456") {
                success relinkConfirmation { token accounts { email username } }
              }
            }''', context_value=SimpleNamespace(user=self.new))
        self.assertIsNone(result.errors)
        preview = result.data['verifySmsCode']['relinkConfirmation']
        self.assertEqual(preview['accounts'], [{'email': 'previous@example.com', 'username': 'old'}])
        result = schema.execute('''mutation($token: String!) {
          confirmPhoneRelink(token: $token) { success error relinkConfirmation { token } }
        }''', variable_values={'token': preview['token']}, context_value=SimpleNamespace(user=self.new))
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['confirmPhoneRelink']['success'])
