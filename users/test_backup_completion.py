from django.test import TestCase
from django.utils import timezone

from users.models import Account, User


class BackupCompletionPolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='backup-policy', firebase_uid='backup-policy',
        )
        self.account, _ = Account.objects.get_or_create(
            user=self.user, account_type='personal', account_index=0,
        )

    def legacy(self):
        self.account.algorand_address = 'legacy-address'
        self.account.save(update_fields=['algorand_address'])

    def test_legacy_only_can_reach_migration_without_claiming_backup_verified(self):
        self.legacy()
        self.assertFalse(self.user.requires_backup_completion)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.backup_verified_at)
        self.assertIsNone(self.user.backup_provider)

    def test_new_unregistered_account_still_requires_backup(self):
        self.assertTrue(self.user.requires_backup_completion)

    def test_migrated_wallet_still_requires_backup(self):
        self.legacy()
        self.account.is_keyless_migrated = True
        self.account.save(update_fields=['is_keyless_migrated'])
        self.assertTrue(self.user.requires_backup_completion)

    def test_bsc_registration_still_requires_backup_even_with_legacy_flag(self):
        self.legacy()
        self.account.bsc_address = '0x' + '1' * 40
        self.account.save(update_fields=['bsc_address'])
        self.assertTrue(self.user.requires_backup_completion)

    def test_v2_or_unregistered_owned_sibling_prevents_legacy_exemption(self):
        self.legacy()
        sibling = Account.objects.create(user=self.user, account_type='personal', account_index=1)
        self.assertTrue(self.user.requires_backup_completion)
        sibling.algorand_address = 'sibling'
        sibling.is_keyless_migrated = True
        sibling.save()
        self.assertTrue(self.user.requires_backup_completion)
        sibling.is_keyless_migrated = False
        sibling.save()
        self.assertFalse(self.user.requires_backup_completion)
        sibling.soft_delete()
        self.assertFalse(self.user.requires_backup_completion)

    def test_no_active_primary_does_not_get_exemption(self):
        self.legacy()
        self.account.soft_delete()
        self.assertTrue(self.user.requires_backup_completion)

    def test_deleted_v2_sibling_does_not_block_active_legacy_wallet(self):
        self.legacy()
        Account.objects.create(
            user=self.user, account_type='personal', account_index=1,
            is_keyless_migrated=True, deleted_at=timezone.now(),
        )
        self.assertFalse(self.user.requires_backup_completion)

    def test_routing_exemption_does_not_allow_legacy_transactions(self):
        from blockchain.mutations import _get_wallet_upgrade_blocker as chain_blocker
        from ramps.schema import _get_wallet_upgrade_blocker as ramp_blocker

        self.legacy()
        self.assertFalse(self.user.requires_backup_completion)
        for blocker in (chain_blocker, ramp_blocker):
            self.assertIn('migracion', blocker(user=self.user, account=self.account))

    def test_verified_backup_remains_complete(self):
        self.user.backup_verified_at = timezone.now()
        self.assertFalse(self.user.requires_backup_completion)
