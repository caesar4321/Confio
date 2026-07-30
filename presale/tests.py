from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from django.contrib.auth import get_user_model

from presale.models import PresalePhase, PresalePurchase, PresaleMigrationCredit
from presale.tasks import (
    sync_presale_migration_credits,
    build_presale_credit_batch,
    verify_presale_migration_credits,
    CREDIT_MIGRATED_SELECTOR,
)
from users.models import Account

User = get_user_model()

VAULT = '0x00000000000000000000000000000000000000AA'
BSC_ADDR = '0xF29A418744E793973BF4eEc676F8a30B2793b623'


def _mk_user(username, bsc_address=None):
    user = User.objects.create(username=username, firebase_uid=f'uid-{username}')
    Account.objects.create(
        user=user,
        account_type='personal',
        account_index=0,
        bsc_address=bsc_address,
    )
    return user


class PresaleMigrationCreditPipelineTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.phase = PresalePhase.objects.create(
            phase_number=1,
            name='Fase 1',
            description='x',
            price_per_token=Decimal('0.2'),
            goal_amount=Decimal('1000000'),
        )

    def _purchase(self, user, confio, status='completed'):
        return PresalePurchase.objects.create(
            user=user,
            phase=self.phase,
            cusd_amount=Decimal('10'),
            confio_amount=Decimal(confio),
            price_per_token=Decimal('0.2'),
            status=status,
        )

    def test_sync_creates_rows_only_for_linked_users_and_sums(self):
        linked = _mk_user('linked', BSC_ADDR)
        unlinked = _mk_user('unlinked')
        self._purchase(linked, '100.5')
        self._purchase(linked, '49.5')
        self._purchase(linked, '999', status='failed')  # ignored
        self._purchase(unlinked, '77')

        res = sync_presale_migration_credits()
        self.assertEqual(res['created'], 1)
        self.assertEqual(res['awaiting_bsc_address'], 1)

        row = PresaleMigrationCredit.objects.get(user=linked)
        self.assertEqual(row.confio_amount, Decimal('150'))
        self.assertEqual(row.bsc_address, BSC_ADDR)
        self.assertEqual(row.status, 'pending')
        self.assertEqual(row.confio_base_units, 150 * 10**18)

        # idempotent: second run creates nothing new
        res2 = sync_presale_migration_credits()
        self.assertEqual(res2['created'], 0)
        self.assertEqual(PresaleMigrationCredit.objects.count(), 1)

        # user links later → picked up on next sync
        acct = unlinked.accounts.get(account_type='personal')
        acct.bsc_address = '0x' + 'b' * 40
        acct.save(update_fields=['bsc_address'])
        res3 = sync_presale_migration_credits()
        self.assertEqual(res3['created'], 1)

    @override_settings(BSC_PRESALE_VAULT_ADDRESS=VAULT)
    def test_batch_queues_rows_and_encodes_calldata(self):
        linked = _mk_user('linked', BSC_ADDR)
        self._purchase(linked, '150')
        sync_presale_migration_credits()

        res = build_presale_credit_batch()
        self.assertEqual(res['count'], 1)
        self.assertEqual(res['to'], VAULT)
        self.assertEqual(res['total_confio'], '150.000000')
        data = bytes.fromhex(res['data'][2:])
        self.assertEqual(data[:4], CREDIT_MIGRATED_SELECTOR)
        # address and 150e18 appear in the encoded tail
        self.assertIn(bytes.fromhex(BSC_ADDR[2:].lower()), data)
        self.assertIn((150 * 10**18).to_bytes(32, 'big'), data)

        row = PresaleMigrationCredit.objects.get(user=linked)
        self.assertEqual(row.status, 'queued')
        self.assertEqual(row.batch_id, res['batch_id'])

        # reprint is idempotent and does not re-queue
        reprint = build_presale_credit_batch(batch_id=res['batch_id'])
        self.assertEqual(reprint['data'], res['data'])

        # nothing pending left
        empty = build_presale_credit_batch()
        self.assertEqual(empty['count'], 0)

    def test_batch_requires_vault_setting(self):
        with override_settings(BSC_PRESALE_VAULT_ADDRESS=None):
            with self.assertRaises(RuntimeError):
                build_presale_credit_batch()

    @override_settings(BSC_PRESALE_VAULT_ADDRESS=VAULT)
    def test_verify_flips_to_credited_only_when_chain_confirms(self):
        linked = _mk_user('linked', BSC_ADDR)
        self._purchase(linked, '150')
        sync_presale_migration_credits()
        build_presale_credit_batch()

        # chain shows nothing yet (Safe hasn't executed)
        with mock.patch('cusd_plus.tasks._rpc', return_value='0x0'):
            res = verify_presale_migration_credits()
        self.assertEqual(res, {'verified': 0, 'still_pending': 1})
        self.assertEqual(PresaleMigrationCredit.objects.get(user=linked).status, 'queued')

        # chain confirms the full credit
        onchain = hex(150 * 10**18)
        with mock.patch('cusd_plus.tasks._rpc', return_value=onchain) as rpc:
            res = verify_presale_migration_credits()
            call_obj = rpc.call_args[0][1][0]
            self.assertEqual(call_obj['to'], VAULT)
        self.assertEqual(res['verified'], 1)
        row = PresaleMigrationCredit.objects.get(user=linked)
        self.assertEqual(row.status, 'credited')
        self.assertIsNotNone(row.credited_at)
