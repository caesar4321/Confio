from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from users.models import User
from sms_verification.models import SMSVerification
from sms_verification.schema import VerifySMSCode
from telegram_verification.models import TelegramVerification
from telegram_verification.schema import VerifyTelegramCode


def confirmed_test_link(user, proof, country):
    """Simulate reviewing and explicitly confirming each ownership preview."""
    from users.phone_linking import link_verified_phone, PhoneRelinkRequired
    token = None
    for _ in range(4):
        try:
            return link_verified_phone(user, proof, country, confirmation_token=token)
        except PhoneRelinkRequired as required:
            token = required.token
    raise AssertionError('Phone ownership did not settle during test confirmation')


@override_settings(REVIEW_TEST_ENABLED=False, TELEGRAM_API_TOKEN='test')
class PhoneRelinkingTests(TestCase):
    phone = '3132587634'
    e164 = '+573132587634'

    def setUp(self):
        self.old = User.objects.create_user(username='old', firebase_uid='google-old', email='previous@example.com',
                                            phone_country='CO', phone_number=self.phone)
        self.new = User.objects.create_user(username='new', firebase_uid='apple-new')
        claim_patch = patch('send.invite_bsc_flow.claim_pending_bsc_invites')
        self.claim = claim_patch.start()
        self.addCleanup(claim_patch.stop)
        from users.review_numbers import _review_phone_keys
        _review_phone_keys.cache_clear()
        self.addCleanup(_review_phone_keys.cache_clear)

    def verify(self, channel, *, valid=True, expired=False, request_user=None, country='CO', confirm=True):
        model = SMSVerification if channel == 'sms' else TelegramVerification
        extra = {'code_hash': 'unused'} if channel == 'sms' else {'request_id': 'request'}
        request = model.objects.create(
            user=request_user or self.new, phone_number=self.e164,
            expires_at=timezone.now() + timedelta(minutes=-1 if expired else 5), **extra)
        info = SimpleNamespace(context=SimpleNamespace(user=self.new))
        if channel == 'sms':
            with patch('sms_verification.schema._lookup_e164', return_value=self.e164), \
                 patch('sms_verification.schema.check_verification', return_value=(valid, 'approved')):
                result = VerifySMSCode.mutate(None, info, self.phone, country, '123456')
        else:
            response = Mock(status_code=200)
            response.json.return_value = {'ok': True, 'result': {
                'delivery_status': {'status': 'delivered'},
                'verification_status': {'status': 'code_valid' if valid else 'code_invalid'}}}
            with patch('telegram_verification.schema.lookup_phone_number', return_value=self.e164), \
                 patch('telegram_verification.schema.requests.post', return_value=response):
                result = VerifyTelegramCode.mutate(None, info, self.phone, country, '123456')
        if confirm and getattr(result, 'relink_confirmation', None):
            from users.phone_link_schema import ConfirmPhoneRelink
            result = ConfirmPhoneRelink.mutate(None, info, result.relink_confirmation.token)
        request.refresh_from_db()
        self.old.refresh_from_db()
        self.new.refresh_from_db()
        return result, request

    def assert_transferred(self, channel):
        result, request = self.verify(channel)
        self.assertTrue(result.success, result.error)
        self.assertTrue(request.is_verified)
        self.assertIsNone(self.old.phone_number)
        self.assertIsNone(self.old.phone_key)
        self.assertIsNone(self.old.phone_country)
        self.assertEqual(self.new.phone_key, '57:3132587634')
        self.assertEqual(self.old.firebase_uid, 'google-old')
        self.assertEqual(self.new.firebase_uid, 'apple-new')
        self.claim.assert_called_once_with(self.new, '57:3132587634')

    def test_sms_transfers_verified_phone_during_onboarding(self):
        self.assert_transferred('sms')

    def test_telegram_transfers_verified_phone_during_onboarding(self):
        self.assert_transferred('telegram')

    def assert_unchanged(self, channel, **kwargs):
        result, request = self.verify(channel, **kwargs)
        self.assertFalse(result.success)
        self.assertFalse(request.is_verified)
        self.assertEqual(self.old.phone_key, '57:3132587634')
        self.claim.assert_not_called()

    def test_invalid_codes_do_not_transfer(self):
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                self.assert_unchanged(channel, valid=False)

    def test_expired_codes_do_not_transfer(self):
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                self.assert_unchanged(channel, expired=True)

    def test_other_users_verification_does_not_transfer(self):
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                self.assert_unchanged(channel, request_user=self.old)

    def test_profile_phone_change_cannot_take_an_owned_number(self):
        self.new.phone_country = 'CO'
        self.new.phone_number = '3001234567'
        self.new.save()
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                self.assert_unchanged(channel)
                self.assertEqual(self.new.phone_number, '3001234567')

    def test_link_uses_provider_phone_instead_of_raw_input(self):
        self.phone = '3001112222'
        self.assert_transferred('sms')

    def test_failure_consuming_proof_rolls_back_both_accounts(self):
        original_save = SMSVerification.save

        def fail_consumption(instance, *args, **kwargs):
            if instance.is_verified:
                raise RuntimeError('write failed')
            return original_save(instance, *args, **kwargs)

        with patch.object(SMSVerification, 'save', new=fail_consumption):
            self.assert_unchanged('sms')
        self.assertIsNone(self.new.phone_number)

    def test_stale_request_user_cannot_bypass_profile_restriction(self):
        User.objects.filter(pk=self.new.pk).update(
            phone_country='CO', phone_number='3001234567', phone_key='57:3001234567')
        self.assertIsNone(self.new.phone_number)
        self.assert_unchanged('sms')

    def test_used_proof_cannot_reclaim_a_transferred_phone(self):
        from users.phone_linking import PhoneLinkError
        link_verified_phone = confirmed_test_link
        _, proof = self.verify('sms')
        other_proof = SMSVerification.objects.create(
            user=self.old, phone_number=self.e164, code_hash='unused',
            expires_at=timezone.now() + timedelta(minutes=5))
        link_verified_phone(self.old, other_proof, 'CO')
        # Even a stale in-memory proof cannot be consumed a second time.
        proof.is_verified = False
        with self.assertRaises(PhoneLinkError):
            link_verified_phone(self.new, proof, 'CO')
        self.old.refresh_from_db()
        self.new.refresh_from_db()
        self.assertEqual(self.old.phone_key, '57:3132587634')
        self.assertIsNone(self.new.phone_key)

    def test_current_owner_can_verify_again(self):
        self.new = self.old
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                result, proof = self.verify(channel)
                self.assertTrue(result.success, result.error)
                self.assertTrue(proof.is_verified)
                self.assertEqual(self.new.phone_key, '57:3132587634')

    def test_profile_can_change_to_unowned_verified_number(self):
        self.new.phone_country = 'CO'
        self.new.phone_number = '3001234567'
        self.new.save()
        self.e164 = '+573001112222'
        self.phone = '3001112222'
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                result, proof = self.verify(channel)
                self.assertTrue(result.success, result.error)
                self.assertTrue(proof.is_verified)
                self.assertEqual(self.new.phone_key, '57:3001112222')
                self.assertEqual(self.old.phone_key, '57:3132587634')

    def test_country_cannot_redirect_verified_phone(self):
        from users.phone_linking import PhoneLinkError
        link_verified_phone = confirmed_test_link
        proof = SMSVerification.objects.create(
            user=self.new, phone_number=self.e164, code_hash='unused',
            expires_at=timezone.now() + timedelta(minutes=5))
        with self.assertRaises(PhoneLinkError):
            link_verified_phone(self.new, proof, 'VE')
        self.new.refresh_from_db()
        self.assertIsNone(self.new.phone_key)

    def test_account_deactivated_during_verification_cannot_take_phone(self):
        User.objects.filter(pk=self.new.pk).update(is_active=False)
        self.assert_unchanged('sms')

    def test_phone_transfer_updates_both_users_modification_times(self):
        old_timestamp = self.old.updated_at
        new_timestamp = self.new.updated_at
        result, _ = self.verify('sms')
        self.assertTrue(result.success, result.error)
        self.assertGreater(self.old.updated_at, old_timestamp)
        self.assertGreater(self.new.updated_at, new_timestamp)

    def test_legacy_phone_update_cannot_link_or_clear_a_phone(self):
        from users.schema import UpdatePhoneNumber
        for user, phone in ((self.new, '3001234567'), (self.old, '')):
            with self.subTest(user=user.pk):
                result = UpdatePhoneNumber.mutate(
                    None, SimpleNamespace(context=SimpleNamespace(user=user)), '+57', phone)
                self.assertFalse(result.success)
        self.new.refresh_from_db()
        self.old.refresh_from_db()
        self.assertIsNone(self.new.phone_number)
        self.assertEqual(self.old.phone_key, '57:3132587634')

    def test_legacy_acknowledgement_checks_fresh_ownership(self):
        from users.schema import UpdatePhoneNumber
        stale_old = User.objects.get(pk=self.old.pk)
        result, _ = self.verify('sms')
        self.assertTrue(result.success)
        for user, expected in ((stale_old, False), (self.new, True)):
            result = UpdatePhoneNumber.mutate(
                None, SimpleNamespace(context=SimpleNamespace(user=user)), '+57', self.phone)
            self.assertEqual(result.success, expected)
        self.old.refresh_from_db()
        self.assertIsNone(self.old.phone_key)

    @override_settings(REVIEW_TEST_ENABLED=True, REVIEW_TEST_PHONE_E164='+12025550123',
                       REVIEW_TEST_CODE='123456', REVIEW_TEST_PHONE_E164_2=None)
    def test_review_numbers_use_actual_country_and_keep_shared_owners(self):
        self.e164 = '+12025550123'
        self.phone = '2025550123'
        self.old.phone_country = 'US'
        self.old.phone_number = self.phone
        self.old.save()
        for channel in ('sms', 'telegram'):
            with self.subTest(channel=channel):
                result, proof = self.verify(channel, country='VE')
                self.assertTrue(result.success, result.error)
                self.assertTrue(proof.is_verified)
                self.assertEqual(self.old.phone_key, '1:2025550123')
                self.assertEqual(self.new.phone_key, '1:2025550123')



class ConcurrentPhoneRelinkingTests(TransactionTestCase):
    @override_settings(REVIEW_TEST_ENABLED=False)
    def test_simultaneous_verified_links_leave_exactly_one_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connection, close_old_connections
        link_verified_phone = confirmed_test_link

        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL is required to exercise ownership locking')
        owner = User.objects.create_user(username='owner', firebase_uid='owner',
                                         phone_country='CO', phone_number='3132587634')
        users = [User.objects.create_user(username=f'new{i}', firebase_uid=f'new{i}')
                 for i in range(2)]
        proofs = [SMSVerification.objects.create(
            user=user, phone_number='+573132587634', code_hash='unused',
            expires_at=timezone.now() + timedelta(minutes=5)) for user in users]
        barrier = Barrier(2)

        def link(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return link_verified_phone(users[index], proofs[index], 'CO')
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(link, i) for i in range(2)]
            self.assertEqual([future.result(timeout=15) for future in futures],
                             ['57:3132587634', '57:3132587634'])
        self.assertEqual(User.objects.filter(phone_key='57:3132587634').count(), 1)
        self.assertEqual(SMSVerification.objects.filter(is_verified=True).count(), 2)
        owner.refresh_from_db()
        self.assertIsNone(owner.phone_key)
