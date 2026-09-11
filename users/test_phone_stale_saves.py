from datetime import timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from sms_verification.models import SMSVerification
from users.models import User
from users.test_phone_relinking import confirmed_test_link as link_verified_phone


@override_settings(REVIEW_TEST_ENABLED=False)
class PhoneStaleSaveTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='phone-owner', firebase_uid='phone-owner',
            phone_number='3132587634', phone_country='CO')
        self.recipient = User.objects.create_user(
            username='phone-recipient', firebase_uid='phone-recipient')

    def transfer(self):
        proof = SMSVerification.objects.create(
            user=self.recipient, phone_number='+573132587634', code_hash='approved',
            expires_at=timezone.now() + timedelta(minutes=5))
        link_verified_phone(self.recipient, proof, 'CO')

    def assert_owner_unlinked(self):
        fresh = User.objects.get(pk=self.owner.pk)
        self.assertIsNone(fresh.phone_number)
        self.assertIsNone(fresh.phone_country)
        self.assertIsNone(fresh.phone_key)

    def test_stale_full_save_does_not_restore_transferred_phone(self):
        stale = User.objects.get(pk=self.owner.pk)
        self.transfer()
        stale.username = 'renamed-owner'
        stale.save()
        stale.first_name = 'Updated'
        stale.save()
        self.assert_owner_unlinked()
        self.assertEqual(User.objects.get(pk=stale.pk).username, 'renamed-owner')

    def test_created_instance_full_save_does_not_restore_phone(self):
        self.transfer()
        self.owner.first_name = 'Updated'
        self.owner.save()
        self.assert_owner_unlinked()

    def test_intentional_phone_change_still_normalizes_and_persists(self):
        user = User.objects.get(pk=self.owner.pk)
        user.phone_number = '+573001234567'
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.phone_number, '3001234567')
        self.assertEqual(user.phone_key, '57:3001234567')

    def test_refresh_updates_snapshot_for_later_transfer(self):
        stale = User.objects.get(pk=self.recipient.pk)
        self.transfer()
        stale.refresh_from_db(fields=['phone_number', 'phone_country', 'phone_key'])
        # Simulate a later ownership change after this request refreshed.
        User.objects.filter(pk=stale.pk).update(
            phone_number=None, phone_country=None, phone_key=None)
        stale.first_name = 'Updated'
        stale.save()
        self.assertIsNone(User.objects.get(pk=stale.pk).phone_key)

    def test_unrelated_refresh_does_not_accept_pending_phone_edit(self):
        user = User.objects.get(pk=self.owner.pk)
        user.phone_number = '3001234567'
        user.refresh_from_db(fields=['first_name'])
        user.save()
        self.assertEqual(User.objects.get(pk=user.pk).phone_key, '57:3001234567')

    def test_generator_refresh_tracks_phone_snapshot(self):
        stale = User.objects.get(pk=self.recipient.pk)
        self.transfer()
        stale.refresh_from_db(fields=(
            name for name in ['phone_number', 'phone_country', 'phone_key']))
        User.objects.filter(pk=stale.pk).update(
            phone_number=None, phone_country=None, phone_key=None)
        stale.first_name = 'Updated'
        stale.save()
        self.assertIsNone(User.objects.get(pk=stale.pk).phone_key)

    def test_deferred_full_save_does_not_load_or_restore_phone(self):
        stale = User.objects.only('id', 'username').get(pk=self.owner.pk)
        self.transfer()
        stale.username = 'deferred-owner'
        with CaptureQueriesContext(connection) as queries:
            stale.save()
        self.assertFalse(any(
            query['sql'].lstrip().upper().startswith('SELECT')
            and '"users_user"' in query['sql']
            for query in queries.captured_queries
        ), 'Saving an unrelated field must not load deferred user columns')
        self.assert_owner_unlinked()
        self.assertNotIn('phone_number', stale.__dict__)

    def test_deferred_phone_read_tracks_snapshot(self):
        stale = User.objects.only('id', 'username').get(pk=self.owner.pk)
        self.assertEqual(stale.phone_number, '3132587634')
        self.transfer()
        stale.username = 'deferred-owner'
        stale.save()
        self.assert_owner_unlinked()

    def test_intentional_deferred_phone_edit_is_saved(self):
        user = User.objects.only('id', 'username').get(pk=self.owner.pk)
        user.phone_number = '3001234567'
        user.save()
        self.assertEqual(User.objects.get(pk=user.pk).phone_key, '57:3001234567')

    def test_unrelated_partial_save_preserves_pending_phone_edit(self):
        user = User.objects.get(pk=self.owner.pk)
        user.phone_number = '3001234567'
        user.first_name = 'Updated'
        user.save(update_fields=['first_name'])
        self.assertEqual(User.objects.get(pk=user.pk).phone_key, '57:3132587634')
        user.save()
        self.assertEqual(User.objects.get(pk=user.pk).phone_key, '57:3001234567')
