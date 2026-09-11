"""Offline legacy-writer concurrency/state guard tests."""
import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch


class LegacyWalletWriteTests(TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'users._wallet_writes_test',
            Path(__file__).resolve().parents[1] / 'users/wallet_address_writes.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'users.models': MagicMock()}):
            spec.loader.exec_module(self.module)
        self.account = SimpleNamespace(pk=1, algorand_address=None,
            bsc_address=None, is_keyless_migrated=True)
        self.current = SimpleNamespace(**vars(self.account), save=MagicMock())
        self.module.Account.objects.select_for_update.return_value.get.return_value = self.current
        self.module.RetiredWalletAddress.objects.filter.return_value.exists.return_value = False
        self.atomic = patch.object(self.module.transaction, 'atomic', side_effect=nullcontext)
        self.atomic.start()
        self.addCleanup(self.atomic.stop)

    def test_fresh_legacy_registration_updates_only_address(self):
        self.module.persist_legacy_wallet_fields(self.account, algorand_address='A' * 58)
        self.current.save.assert_called_once_with(update_fields=['algorand_address'])
        self.assertEqual(self.account.algorand_address, 'A' * 58)

    def test_reconciled_wallet_cannot_acquire_algorand_anchor(self):
        self.account.bsc_address = self.current.bsc_address = '0x' + '1' * 40
        with self.assertRaises(self.module.WalletRegistrationChanged):
            self.module.persist_legacy_wallet_fields(self.account, algorand_address='A' * 58)
        self.current.save.assert_not_called()

    def test_stale_caller_cannot_overwrite_reconciled_state(self):
        self.current.bsc_address = '0x' + '1' * 40
        with self.assertRaises(self.module.WalletRegistrationChanged):
            self.module.persist_legacy_wallet_fields(self.account, algorand_address='A' * 58)
        self.current.save.assert_not_called()

    def test_retired_algorand_anchor_is_rejected(self):
        self.module.RetiredWalletAddress.objects.filter.return_value.exists.return_value = True
        with self.assertRaises(self.module.WalletRegistrationChanged):
            self.module.persist_legacy_wallet_fields(self.account, algorand_address='A' * 58)
        self.current.save.assert_not_called()

    def test_migration_flag_update_keeps_current_wallet(self):
        self.account.bsc_address = self.current.bsc_address = '0x' + '1' * 40
        self.module.persist_legacy_wallet_fields(self.account, is_keyless_migrated=True)
        self.current.save.assert_called_once_with(update_fields=['is_keyless_migrated'])
