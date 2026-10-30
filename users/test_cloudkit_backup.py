import hashlib
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from users.models import Account
from users.schema import ReportCloudKitBackup


def wallet_hash(address):
    return hashlib.sha256(address.lower().encode()).hexdigest()


class ReportCloudKitBackupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='cloudkit', firebase_uid='cloudkit-uid')
        self.account = Account.objects.create(
            user=self.user, account_type='personal', account_index=0, bsc_address='0xAbC',
        )
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))

    def report(self, state, hashes=None):
        result = ReportCloudKitBackup().mutate(self.info, state, wallet_hashes=hashes)
        self.user.refresh_from_db()
        return result

    def test_proof_for_the_registered_wallet_is_recorded(self):
        self.assertTrue(self.report('proven', [wallet_hash('0xabc')]).success)
        self.assertEqual(self.user.cloudkit_backup_state, 'proven')
        self.assertEqual(self.user.cloudkit_backup_wallet_hash, wallet_hash('0xabc'))
        self.assertIsNotNone(self.user.cloudkit_backup_verified_at)

    def test_proof_for_another_wallet_is_refused(self):
        result = self.report('proven', [wallet_hash('0xdef')])
        self.assertFalse(result.success)
        self.assertEqual(self.user.cloudkit_backup_state, '')
        self.assertIsNone(self.user.cloudkit_backup_verified_at)

    def test_proof_goes_stale_when_the_wallet_changes(self):
        self.report('proven', [wallet_hash('0xabc')])
        self.account.bsc_address = '0xdef'
        self.account.save(update_fields=['bsc_address'])
        self.assertFalse(self.report('proven', [wallet_hash('0xabc')]).success)
        self.assertNotEqual(self.user.cloudkit_backup_wallet_hash, wallet_hash('0xdef'))

    def test_a_legacy_algorand_wallet_can_prove_its_backup(self):
        self.account.bsc_address = None
        self.account.algorand_address = 'ALGOADDR'
        self.account.save(update_fields=['bsc_address', 'algorand_address'])
        self.assertTrue(self.report('proven', [wallet_hash('ALGOADDR')]).success)

    def test_proof_must_cover_every_registered_address(self):
        self.account.algorand_address = 'ALGOADDR'
        self.account.save(update_fields=['algorand_address'])
        self.assertFalse(self.report('proven', [wallet_hash('0xabc')]).success)
        self.assertTrue(self.report('proven', [wallet_hash('0xabc'), wallet_hash('ALGOADDR')]).success)

    def test_it_never_touches_the_backup_gate(self):
        verified_at = timezone.now()
        get_user_model().objects.filter(pk=self.user.pk).update(
            backup_provider='icloud', backup_verified_at=verified_at)
        self.user.refresh_from_db()
        self.report('failed')
        self.report('proven', [wallet_hash('0xabc')])
        self.assertEqual(self.user.backup_provider, 'icloud')
        self.assertEqual(self.user.backup_verified_at, verified_at)

    def test_a_failure_keeps_the_last_proof_time(self):
        self.report('proven', [wallet_hash('0xabc')])
        proven_at = self.user.cloudkit_backup_verified_at
        self.report('failed')
        self.assertEqual(self.user.cloudkit_backup_state, 'failed')
        self.assertEqual(self.user.cloudkit_backup_verified_at, proven_at)

    def test_unknown_states_are_refused(self):
        self.assertFalse(self.report('verified').success)
        self.assertEqual(self.user.cloudkit_backup_state, '')
