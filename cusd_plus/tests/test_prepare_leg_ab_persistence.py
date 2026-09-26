from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from conversion.models import Conversion
from cusd_plus.prepare_leg_ab import _create_conversion_for_current_addresses
from users.models import Account


User = get_user_model()


class LegABPersistenceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username='leg-ab-owner',
            firebase_uid='leg-ab-owner-uid',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            algorand_address='A' * 58,
            bsc_address='0x' + '1' * 40,
        )

    def _create(self):
        return _create_conversion_for_current_addresses(
            account_id=self.account.id,
            expected_algorand_address='A' * 58,
            expected_bsc_address='0x' + '1' * 40,
            amount=Decimal('12.5'),
            receive_usd=Decimal('12.3456789'),
        )

    def test_creates_conversion_for_locked_current_snapshot(self):
        conversion = self._create()

        self.assertIsNotNone(conversion)
        self.assertEqual(conversion.actor_user, self.user)
        self.assertEqual(conversion.actor_address, 'A' * 58)
        self.assertEqual(conversion.user_bsc_address, '0x' + '1' * 40)
        self.assertEqual(conversion.to_amount, Decimal('12.345679'))

    def test_rejects_pack_when_address_changed_before_persistence(self):
        self.account.bsc_address = '0x' + '2' * 40
        self.account.save(update_fields=['bsc_address'])

        self.assertIsNone(self._create())
        self.assertFalse(Conversion.objects.exists())


class ConversionCompletionEvidenceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username='completion-owner', firebase_uid='completion-owner-uid',
        )
        self.row = Conversion.objects.create(
            actor_user=self.user, actor_type='user', conversion_type='to_savings',
            from_amount=Decimal('20'), to_amount=Decimal('19.8'),
            user_bsc_address='0x' + '1' * 40, status='DEST_ARRIVED',
        )
        self.tx_hash = '0x' + 'ab' * 32
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))

    def advance(self, tx_ref='', status='COMPLETED'):
        from cusd_plus.schema import AdvanceCusdPlusConversion
        with mock.patch('cusd_plus.schema._actor_filter', return_value={
                'actor_user': self.user, 'actor_type': 'user'}):
            return AdvanceCusdPlusConversion.mutate(
                None, self.info, str(self.row.internal_id), status, tx_ref,
            )

    def test_arrival_or_client_hash_cannot_complete_conversion(self):
        for direction in ('to_savings', 'from_savings'):
            self.row.conversion_type = direction
            self.row.save(update_fields=['conversion_type'])
            for tx_hash in ('', self.tx_hash):
                with self.subTest(direction=direction, tx_hash=tx_hash):
                    result = self.advance(tx_hash)
                    self.assertFalse(result.success)
                    self.row.refresh_from_db()
                    self.assertEqual(self.row.status, 'DEST_ARRIVED')
                    self.assertIsNone(self.row.completed_at)
                    self.assertFalse(self.row.to_transaction_hash)

    def test_submitted_or_failed_mint_cannot_be_completed_by_client(self):
        self.row.to_transaction_hash = self.tx_hash
        for status in ('SUBMITTED', 'FAILED'):
            self.row.status = status
            self.row.save(update_fields=['status', 'to_transaction_hash'])
            self.assertFalse(self.advance(self.tx_hash).success)
            self.row.refresh_from_db()
            self.assertEqual(self.row.status, status)

    def test_completed_acknowledgment_is_idempotent_and_requires_matching_hash(self):
        self.row.status = 'COMPLETED'
        self.row.to_transaction_hash = self.tx_hash
        self.row.completed_at = timezone.now()
        self.row.save(update_fields=['status', 'to_transaction_hash', 'completed_at'])
        completed_at = self.row.completed_at
        updated_at = self.row.updated_at
        self.assertTrue(self.advance(self.tx_hash.upper()).success)
        self.assertFalse(self.advance('').success)
        self.assertFalse(self.advance('0x' + 'cd' * 32).success)
        self.row.refresh_from_db()
        self.assertEqual(self.row.completed_at, completed_at)
        self.assertEqual(self.row.updated_at, updated_at)
        self.assertEqual(self.row.to_transaction_hash, self.tx_hash)

    def test_other_user_cannot_acknowledge_or_complete_conversion(self):
        self.info.context.user = User.objects.create(
            username='completion-other', firebase_uid='completion-other-uid',
        )
        self.assertFalse(self.advance(self.tx_hash).success)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'DEST_ARRIVED')

    def test_signed_source_leg_still_advances(self):
        self.row.status = 'CREATED'
        self.row.save(update_fields=['status'])
        self.assertTrue(self.advance(self.tx_hash, status='SRC_COMMITTED').success)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'SRC_COMMITTED')
        self.assertEqual(self.row.from_transaction_hash, self.tx_hash)

    def batch(self, status, *, retry=0, attempt=0, user=None, wallet=None):
        from blockchain.models import SponsoredBatch
        prefix = f'savings-mint-{self.row.internal_id}' + (f'_r{retry}' if retry else '')
        return SponsoredBatch.objects.create(
            user=user or self.user, user_bsc_address=wallet or self.row.user_bsc_address,
            kind='subscribe', status=status, client_request_id=prefix + f'_a{attempt}',
            num_calls=1, calls_json='[]', gas_limit=100000, max_fee_wei='1',
        )

    def request_id(self):
        from cusd_plus.schema import CusdPlusConversionType, _serialize
        return CusdPlusConversionType.resolve_mint_request_id(_serialize(self.row), self.info)

    def test_mint_identity_retains_pending_unknown_and_confirmed_attempts(self):
        base = f'savings-mint-{self.row.internal_id}'
        self.assertEqual(self.request_id(), base)
        batch = self.batch('signed')
        for status in ('signed', 'sent', 'dropped', 'reorged', 'confirmed'):
            batch.status = status
            batch.save(update_fields=['status'])
            self.assertEqual(self.request_id(), base)

    def test_mint_identity_advances_only_when_all_attempts_prove_failure(self):
        base = f'savings-mint-{self.row.internal_id}'
        self.batch('noop_failed')
        pending = self.batch('sent', attempt=1)
        self.assertEqual(self.request_id(), base)
        pending.status = 'reverted'
        pending.save(update_fields=['status'])
        self.assertEqual(self.request_id(), base + '_r1')
        self.batch('reverted', retry=1)
        self.assertEqual(self.request_id(), base + '_r2')

    def test_mint_identity_ignores_other_wallet_and_user_batches(self):
        base = f'savings-mint-{self.row.internal_id}'
        other = User.objects.create(username='retry-other', firebase_uid='retry-other')
        self.batch('reverted', user=other)
        self.batch('reverted', wallet='0x' + '2' * 40)
        self.assertEqual(self.request_id(), base)

    def test_mint_identity_does_not_exhaust_after_ten_proven_failures(self):
        for retry in range(11):
            self.batch('reverted', retry=retry)
        self.assertEqual(self.request_id(), f'savings-mint-{self.row.internal_id}_r11')

    def persist_mint(self, batch, amount=None):
        import json
        from cusd_plus.schema import _persist_savings_mint
        from cusd_plus.sponsor_7702 import SEL_SUBSCRIBE_AND_MINT
        units = int((self.row.to_amount if amount is None else amount) * 10**18)
        batch.calls_json = json.dumps([{
            'data': '0x' + SEL_SUBSCRIBE_AND_MINT + f'{units:064x}' + '0' * 128,
        }])
        _persist_savings_mint(batch, '0xsigned')

    def test_mint_reservation_allows_first_batch(self):
        self.persist_mint(self.batch('signed'))

    def test_mint_reservation_allows_retry_after_proven_failure(self):
        self.batch('reverted')
        self.persist_mint(self.batch('signed', retry=1))

    def test_mint_reservation_allows_original_noop_retry_to_win(self):
        from cusd_plus.sponsor_7702 import PolicyError
        self.batch('noop_failed')
        self.persist_mint(self.batch('signed', attempt=1))
        with self.assertRaisesRegex(PolicyError, 'savings_mint_superseded'):
            self.persist_mint(self.batch('signed', retry=1))

    def test_mint_reservation_rejects_delayed_old_attempt_after_new_generation(self):
        from cusd_plus.sponsor_7702 import PolicyError
        self.batch('noop_failed')
        self.batch('signed', retry=1)
        with self.assertRaisesRegex(PolicyError, 'savings_mint_superseded'):
            self.persist_mint(self.batch('signed', attempt=1))

    def test_mint_reservation_rejects_second_live_attempt(self):
        from cusd_plus.sponsor_7702 import PolicyError
        self.batch('signed')
        with self.assertRaisesRegex(PolicyError, 'savings_mint_already_reserved'):
            self.persist_mint(self.batch('signed', attempt=1))

    def test_mint_reservation_is_shared_by_operators_of_same_wallet(self):
        from cusd_plus.sponsor_7702 import PolicyError
        other = User.objects.create(username='mint-operator', firebase_uid='mint-operator')
        self.batch('signed', user=other)
        with self.assertRaisesRegex(PolicyError, 'savings_mint_already_reserved'):
            self.persist_mint(self.batch('signed'))

    def test_mint_reservation_rejects_completed_saga(self):
        from cusd_plus.sponsor_7702 import PolicyError
        self.row.status = 'COMPLETED'
        self.row.save(update_fields=['status'])
        with self.assertRaisesRegex(PolicyError, 'savings_mint_not_pending'):
            self.persist_mint(self.batch('signed'))

    def test_mint_reservation_rejects_wrong_amount(self):
        from cusd_plus.sponsor_7702 import PolicyError
        with self.assertRaisesRegex(PolicyError, 'savings_mint_amount_mismatch'):
            self.persist_mint(self.batch('signed'), Decimal('20'))
