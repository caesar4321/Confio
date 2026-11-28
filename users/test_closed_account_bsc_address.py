"""A closed account's BSC address can never be claimed by another account.

History (portfolio, stock ledger, activity, returns) is looked up by
address, so registering a closed account's address would show its trades
to whoever registered it.
"""
import importlib
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps as global_apps
from django.test import TestCase
from django.utils import timezone

from users.models import Account, Business, RetiredWalletAddress, User
from users.schema import UpdateAccountBscAddress

CLOSED = '0xAbCdEf' + '1' * 34
FRESH = '0x' + '2' * 40
PERSONAL_CONTEXT = {'account_type': 'personal', 'account_index': 0, 'business_id': None}


def make_user(name):
    user = User(username=name, firebase_uid=name)
    User.objects.bulk_create([user])
    return user


class ClosedAccountBscAddressTests(TestCase):
    def setUp(self):
        self.owner = make_user('closed-owner')
        self.business = Business.objects.create(name='Tienda X', category='retail')
        self.closed = Account.objects.create(
            user=self.owner, account_type='business', account_index=0,
            business=self.business, bsc_address=CLOSED, is_keyless_migrated=True)
        self.claimer = make_user('claimer')
        self.claimer_account = Account.objects.create(
            user=self.claimer, account_type='personal', account_index=0, is_keyless_migrated=True)

    def register(self, address, user=None):
        info = SimpleNamespace(context=SimpleNamespace(user=user or self.claimer))
        with patch('users.jwt_context.get_jwt_business_context_with_validation',
                   return_value=PERSONAL_CONTEXT):
            return UpdateAccountBscAddress.mutate(None, info, address)

    def test_closing_a_business_account_retires_its_address(self):
        self.closed.soft_delete()
        retired = RetiredWalletAddress.objects.get(chain='bsc', address=CLOSED.lower())
        self.assertEqual(retired.account_id, self.closed.pk)
        self.assertEqual(retired.user_id, self.owner.pk)
        self.assertTrue(RetiredWalletAddress.is_retired('bsc', CLOSED))

    def test_closed_and_retired_address_cannot_be_registered_by_another_user(self):
        self.closed.soft_delete()
        result = self.register(CLOSED.upper().replace('0X', '0x'))
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'Esa dirección BSC ya está registrada en otra cuenta.')
        self.claimer_account.refresh_from_db()
        self.assertIsNone(self.claimer_account.bsc_address)

    def test_refused_even_when_closed_without_retiring(self):
        # Accounts closed before soft_delete retired addresses (or by a
        # queryset update) are still refused: any row that ever held it.
        Account.all_objects.filter(pk=self.closed.pk).update(deleted_at=timezone.now())
        self.assertFalse(RetiredWalletAddress.objects.exists())
        result = self.register(CLOSED)
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'Esa dirección BSC ya está registrada en otra cuenta.')
        self.claimer_account.refresh_from_db()
        self.assertIsNone(self.claimer_account.bsc_address)

    def test_closing_a_row_closed_by_a_queryset_update_retires_it(self):
        stale = Account.objects.get(pk=self.closed.pk)   # still thinks it is open
        Account.all_objects.filter(pk=self.closed.pk).update(deleted_at=timezone.now())
        stale.soft_delete()
        self.assertTrue(RetiredWalletAddress.is_retired('bsc', CLOSED))

    def test_a_hard_delete_retires_the_address_first(self):
        Account.all_objects.filter(pk=self.closed.pk).delete()
        self.assertTrue(RetiredWalletAddress.objects.filter(address=CLOSED.lower(), user=self.owner).exists())
        self.assertFalse(self.register(CLOSED).success)

    def test_a_hard_deleted_accounts_address_stays_reserved(self):
        Account.objects.filter(pk=self.claimer_account.pk).update(bsc_address=FRESH)
        Account.all_objects.filter(pk=self.claimer_account.pk).delete()   # retired: account NULL
        Account.objects.create(user=self.owner, account_type='personal', account_index=0,
                               is_keyless_migrated=True)
        refused = self.register(FRESH, user=self.owner)
        self.assertFalse(refused.success)
        self.assertEqual(refused.error, 'Esa dirección BSC ya está registrada en otra cuenta.')
        # The same person too, as the signed paths (an operator re-creating
        # the account deletes the retired row).
        Account.objects.create(user=self.claimer, account_type='personal', account_index=0,
                               is_keyless_migrated=True)
        self.assertFalse(self.register(FRESH).success)

    def test_a_reconciled_away_wallet_is_never_taken_back(self):
        # A wallet the person was moved off on purpose, its account later
        # hard-deleted: not theirs to register again.
        RetiredWalletAddress.objects.create(chain='bsc', address=FRESH, account=None, user=self.claimer)
        refused = self.register(FRESH)
        self.assertFalse(refused.success)
        self.assertTrue(RetiredWalletAddress.is_retired('bsc', FRESH))

    def test_a_users_hard_delete_cascades_and_retires(self):
        User.all_objects.filter(pk=self.owner.pk).delete()
        row = RetiredWalletAddress.objects.get(address=CLOSED.lower())
        self.assertIsNone(row.account_id)
        self.assertIsNone(row.user_id)
        self.assertFalse(self.register(CLOSED).success)

    def test_a_stale_copys_old_address_is_not_what_closing_retires(self):
        stale = Account.objects.get(pk=self.closed.pk)
        Account.objects.filter(pk=self.closed.pk).update(bsc_address=FRESH)   # moved since
        stale.soft_delete()
        self.assertTrue(RetiredWalletAddress.objects.filter(address=FRESH.lower()).exists())
        self.assertFalse(RetiredWalletAddress.objects.filter(address=CLOSED.lower()).exists())

    def test_a_stale_copys_hard_delete_retires_the_stored_address(self):
        stale = Account.objects.get(pk=self.closed.pk)
        Account.objects.filter(pk=self.closed.pk).update(bsc_address=FRESH)   # moved since
        stale.delete()
        self.assertTrue(RetiredWalletAddress.objects.filter(address=FRESH.lower()).exists())
        self.assertFalse(self.register(FRESH).success)

    def test_re_sending_its_own_address_succeeds(self):
        Account.objects.filter(pk=self.claimer_account.pk).update(bsc_address=FRESH)
        # Another person's closed row with the same address (from before).
        Account.all_objects.filter(pk=self.closed.pk).update(bsc_address=FRESH.lower(), deleted_at=timezone.now())
        self.assertTrue(self.register(FRESH).success)

    def test_a_cuenta_inteligente_contract_is_never_a_personal_wallet(self):
        from smart_account.models import SmartAccount
        contract = '0x' + '5c' * 20
        owner_personal = Account.objects.create(user=self.owner, account_type='personal', account_index=0,
                                                bsc_address='0x' + '4d' * 20, is_keyless_migrated=True)
        smart = SmartAccount.objects.create(owner_user=self.owner, owner_account=owner_personal,
                                            contract_address=contract)
        smart.soft_delete()   # closed, and no users.Account row holds it: still a contract
        self.assertFalse(Account.all_objects.filter(bsc_address__iexact=contract).exists())
        refused = self.register(contract.upper().replace('0X', '0x'))
        self.assertFalse(refused.success)
        self.assertEqual(refused.error, 'Esa dirección BSC ya está registrada en otra cuenta.')

    def test_fresh_address_still_registers(self):
        self.closed.soft_delete()
        result = self.register(FRESH)
        self.assertTrue(result.success, result.error)
        self.claimer_account.refresh_from_db()
        self.assertEqual(self.claimer_account.bsc_address, FRESH)

    def test_restored_account_accepts_sends_again(self):
        self.closed.soft_delete()
        self.closed.restore()
        self.assertFalse(RetiredWalletAddress.is_retired('bsc', CLOSED))
        # The audit row stays, still naming the account that owned it.
        self.assertEqual(RetiredWalletAddress.objects.get(address=CLOSED.lower()).account_id, self.closed.pk)

    def test_restore_refuses_while_another_live_account_holds_the_address(self):
        Account.all_objects.filter(pk=self.closed.pk).update(deleted_at=timezone.now())
        Account.objects.filter(pk=self.claimer_account.pk).update(bsc_address=CLOSED.lower())
        closed = Account.all_objects.get(pk=self.closed.pk)
        with self.assertRaises(ValueError):
            closed.restore()
        self.assertIsNotNone(Account.all_objects.get(pk=self.closed.pk).deleted_at)

    def test_restore_refuses_an_address_retired_to_another_account(self):
        earlier = Account.objects.create(
            user=self.owner, account_type='personal', account_index=0, is_keyless_migrated=True)
        RetiredWalletAddress.objects.create(chain='bsc', address=CLOSED, account=earlier, user=self.owner)
        self.closed.soft_delete()
        with self.assertRaises(ValueError):
            Account.all_objects.get(pk=self.closed.pk).restore()

    def test_retiring_skips_an_address_a_live_account_holds(self):
        from users.models import retire_closed_account_address
        Account.all_objects.filter(pk=self.closed.pk).update(deleted_at=timezone.now())
        Account.objects.filter(pk=self.claimer_account.pk).update(bsc_address=CLOSED.lower())
        with self.assertLogs('users.models', level='WARNING'):
            self.assertIsNone(retire_closed_account_address(Account.all_objects.get(pk=self.closed.pk)))
        self.assertFalse(RetiredWalletAddress.objects.exists())

    def test_restore_answers_when_a_signed_path_took_the_address_meanwhile(self):
        from django.db.models import QuerySet
        self.closed.soft_delete()
        RetiredWalletAddress.objects.all().delete()   # only the live-holder race is under test
        closed = Account.all_objects.get(pk=self.closed.pk)
        # Taken after restore's checks, by a path that takes no lock.
        Account.objects.filter(pk=self.claimer_account.pk).update(bsc_address=CLOSED.lower())
        real_exists = QuerySet.exists
        calls = []

        def checks_pass_once(qs):
            calls.append(qs.model)
            return False if len(calls) <= 2 else real_exists(qs)
        with patch.object(QuerySet, 'exists', checks_pass_once):
            with self.assertRaises(ValueError):
                closed.restore()
        self.assertIsNotNone(closed.deleted_at)
        self.assertIsNotNone(Account.all_objects.get(pk=self.closed.pk).deleted_at)

    def test_closing_again_keeps_the_first_close_and_retires_nothing(self):
        # Closed before this fix, then registered by someone else: closing it
        # again must not refuse raw-address sends to that live account.
        Account.all_objects.filter(pk=self.closed.pk).update(deleted_at=timezone.now())
        Account.objects.filter(pk=self.claimer_account.pk).update(bsc_address=CLOSED.lower())
        closed = Account.all_objects.get(pk=self.closed.pk)
        closed.soft_delete()
        self.assertFalse(RetiredWalletAddress.objects.exists())
        first_close = Account.all_objects.get(pk=self.closed.pk).deleted_at
        closed.deleted_at = None  # a stale copy that thinks it is open
        closed.soft_delete()
        self.assertFalse(RetiredWalletAddress.objects.exists())
        self.assertEqual(Account.all_objects.get(pk=self.closed.pk).deleted_at, first_close)
        self.assertFalse(RetiredWalletAddress.is_retired('bsc', CLOSED))

    def test_closing_a_smart_account_does_not_retire_its_contract(self):
        smart = Account.objects.create(
            user=self.owner, account_type='smart', account_index=0, bsc_address=FRESH)
        smart.soft_delete()
        self.assertFalse(RetiredWalletAddress.objects.filter(address=FRESH.lower()).exists())

    def test_existing_retired_row_of_another_account_is_kept(self):
        earlier = Account.objects.create(
            user=self.owner, account_type='personal', account_index=0, is_keyless_migrated=True)
        RetiredWalletAddress.objects.create(
            chain='bsc', address=CLOSED, account=earlier, user=self.owner)
        self.closed.soft_delete()
        retired = RetiredWalletAddress.objects.get(chain='bsc', address=CLOSED.lower())
        self.assertEqual(retired.account_id, earlier.pk)
        self.assertTrue(Account.all_objects.get(pk=self.closed.pk).deleted_at)


class BackfillClosedAccountAddressesTests(TestCase):
    def setUp(self):
        self.migration = importlib.import_module(
            'users.migrations.0067_retire_closed_account_bsc_addresses')
        self.owner = make_user('backfill-owner')

    def close(self, **fields):
        account = Account.objects.create(user=self.owner, **fields)
        Account.all_objects.filter(pk=account.pk).update(deleted_at=timezone.now())
        return account

    def run_backfill(self, apps=global_apps):
        with patch('builtins.print'):
            self.migration.retire(apps, None)

    def test_runs_on_the_historical_models(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        business = self.close(account_type='business', account_index=0, bsc_address=CLOSED)
        state = MigrationExecutor(connection).loader.project_state(
            ('users', '0067_retire_closed_account_bsc_addresses'))
        self.run_backfill(state.apps)
        self.assertEqual(list(RetiredWalletAddress.objects.values_list('address', 'account_id')),
                         [(CLOSED.lower(), business.pk)])

    def test_retires_closed_keyed_accounts_only(self):
        business = self.close(account_type='business', account_index=0, bsc_address=CLOSED)
        self.close(account_type='smart', account_index=0, bsc_address=FRESH)
        self.close(account_type='personal', account_index=1, bsc_address='')
        self.run_backfill()
        rows = list(RetiredWalletAddress.objects.values_list('address', 'account_id', 'user_id'))
        self.assertEqual(rows, [(CLOSED.lower(), business.pk, self.owner.pk)])
        self.run_backfill()  # idempotent
        self.assertEqual(RetiredWalletAddress.objects.count(), 1)

    def test_reports_an_address_retired_to_another_persons_account(self):
        first_owner = make_user('backfill-first')
        first = Account.objects.create(user=first_owner, account_type='personal', account_index=0,
                                       is_keyless_migrated=True)
        RetiredWalletAddress.objects.create(chain='bsc', address=CLOSED, account=first, user=first_owner)
        later = self.close(account_type='business', account_index=0, bsc_address=CLOSED)
        with patch('builtins.print') as out:
            self.migration.retire(global_apps, None)
        printed = ' '.join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn(f'retired to another account: closed account={later.pk} retired account={first.pk}', printed)
        self.assertEqual(RetiredWalletAddress.objects.get().account_id, first.pk)

    def test_retires_a_hard_deleted_accounts_traded_address(self):
        from blockchain.models import SponsoredBatch
        gone = '0x' + '9a' * 20
        SponsoredBatch.objects.create(user=self.owner, user_bsc_address=gone.upper().replace('0X', '0x'),
                                      kind='stock_buy', num_calls=1, calls_json='[]', tx_hash='0x' + '01' * 32,
                                      status='confirmed', gas_limit=1, max_fee_wei=1, block_number=1)
        SponsoredBatch.objects.create(user=self.owner, user_bsc_address='0xcap', kind='stock_buy', num_calls=1,
                                      calls_json='[]', tx_hash='0x' + '02' * 32, status='confirmed',
                                      gas_limit=1, max_fee_wei=1, block_number=1)
        self.run_backfill()
        self.assertEqual(list(RetiredWalletAddress.objects.values_list('address', 'account_id', 'user_id')),
                         [(gone, None, self.owner.pk)])

    def test_reports_trades_of_other_people_on_a_held_address(self):
        from blockchain.models import SponsoredBatch
        held = '0x' + '7b' * 20
        holder = make_user('backfill-holder')
        live = Account.objects.create(user=holder, account_type='personal', account_index=0,
                                      bsc_address=held, is_keyless_migrated=True)
        SponsoredBatch.objects.create(user=self.owner, user_bsc_address=held, kind='stock_buy', num_calls=1,
                                      calls_json='[]', tx_hash='0x' + '03' * 32, status='confirmed',
                                      gas_limit=1, max_fee_wei=1, block_number=1)
        with patch('builtins.print') as out:
            self.migration.retire(global_apps, None)
        printed = ' '.join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn(f'trades of other people: live account={live.pk} signers={[self.owner.pk]}', printed)

    def test_skips_an_address_a_live_account_holds(self):
        self.close(account_type='business', account_index=0, bsc_address=CLOSED)
        other = make_user('backfill-live')
        Account.objects.create(user=other, account_type='personal', account_index=0,
                               bsc_address=CLOSED.lower(), is_keyless_migrated=True)
        with patch('builtins.print') as out:
            self.migration.retire(global_apps, None)
        self.assertFalse(RetiredWalletAddress.objects.exists())
        self.assertIn('held by a live account', ' '.join(str(c.args[0]) for c in out.call_args_list))
