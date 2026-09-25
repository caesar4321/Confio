from unittest import mock
from decimal import Decimal

from django.test import TestCase

from conversion.models import Conversion
from ramps.metrics import (
    deposit_volume_and_count,
    fund_flow_breakdown,
    deposit_operation_count,
    deposited_volume_by_provider,
    withdrawn_volume_and_count,
)
from ramps.models import RampTransaction


class DepositedMetricsTests(TestCase):
    """Use bulk fixtures so provider/recovery signals do not create evidence."""

    def conversion(self, **overrides):
        values = dict(conversion_type='usdt_to_cusd', status='COMPLETED',
            from_amount=100, to_amount=99, net_amount_exact=99)
        values.update(overrides)
        return Conversion.objects.bulk_create([Conversion(**values)])[0]

    def ramp(self, **overrides):
        values = dict(provider='koywe', direction='on_ramp', status='COMPLETED',
            destination='cusd_plus', final_amount=99, final_currency='CUSD_BSC')
        values.update(overrides)
        return RampTransaction.objects.bulk_create([RampTransaction(**values)])[0]

    def test_provider_completion_alone_is_not_delivery(self):
        self.ramp()
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_verified_raw_usdt_receipt_counts_actual_not_provider_quote(self):
        self.ramp(final_currency='USDT BSC', metadata={
            'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 1, 'bsc_arrival_amount': '100'})
        self.assertEqual(deposited_volume_by_provider()['koywe'], 100)

    def test_completed_usdc_receipt_counts_without_mint(self):
        from usdc_transactions.models import USDCDeposit
        deposit = USDCDeposit.objects.bulk_create([USDCDeposit(amount=73,
            status='COMPLETED', actor_type='user')])[0]
        self.ramp(usdc_deposit=deposit, final_currency='CUSD', final_amount=999)
        self.assertEqual(deposited_volume_by_provider()['koywe'], 73)
        USDCDeposit.objects.filter(pk=deposit.pk).update(is_deleted=True)
        self.assertEqual(deposited_volume_by_provider()['koywe'], 0)

    def test_completed_conversion_takes_precedence_over_raw_receipt(self):
        self.ramp(conversion=self.conversion(), metadata={
            'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 0, 'bsc_arrival_amount': '100'})
        self.assertEqual(deposited_volume_by_provider()['koywe'], 99)

    def test_failed_or_pending_deposits_and_outgoing_receipts_are_excluded(self):
        from usdc_transactions.models import USDCDeposit
        for status in ('FAILED', 'PROCESSING', 'PENDING'):
            deposit = USDCDeposit.objects.bulk_create([USDCDeposit(amount=73,
                status=status, actor_type='user')])[0]
            self.ramp(usdc_deposit=deposit)
        self.ramp(direction='off_ramp', metadata={
            'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 0, 'bsc_arrival_amount': '100'})
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_malformed_or_incomplete_scanner_evidence_cannot_break_metric(self):
        valid = {'bsc_arrival_tx_hash': '0x' + 'a' * 64,
            'bsc_arrival_log_index': 0, 'bsc_arrival_amount': '100'}
        for overrides in ({'bsc_arrival_amount': 'NaN'}, {'bsc_arrival_amount': '9' * 100},
                          {'bsc_arrival_amount': '-1'}, {'bsc_arrival_amount': None},
                          {'bsc_arrival_amount': {}}, {'bsc_arrival_tx_hash': 'provider-only'},
                          {'bsc_arrival_log_index': None}):
            self.ramp(metadata={**valid, **overrides})
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_failed_pending_deleted_or_wrong_direction_conversion_is_excluded(self):
        for overrides in ({'status': 'SUBMITTED'}, {'status': 'FAILED'},
                          {'is_deleted': True}, {'conversion_type': 'cusd_to_usdt'}):
            self.ramp(conversion=self.conversion(**overrides))
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_completed_batch_preserves_per_ramp_allocation(self):
        conversion = self.conversion()
        self.ramp(conversion=conversion, final_amount=Decimal('39.6'))
        self.ramp(conversion=conversion, final_amount=Decimal('59.4'))
        self.assertEqual(deposited_volume_by_provider()['koywe'], Decimal('99'))

    def test_all_product_types_and_providers_with_verified_delivery(self):
        for provider, kind, currency in (
            ('koywe', 'usdt_to_cusd', 'CUSD_BSC'),
            ('guardarian', 'usdc_to_cusd', 'CUSD'),
            ('transak', 'to_savings', 'CUSD+'),
        ):
            self.ramp(provider=provider, final_currency=currency,
                conversion=self.conversion(conversion_type=kind))
        totals = deposited_volume_by_provider()
        self.assertEqual([totals[p] for p in ('koywe', 'guardarian', 'transak')], [99, 99, 99])

    def test_quote_currency_outgoing_and_unfinished_ramp_are_excluded(self):
        conversion = self.conversion()
        for overrides in ({'final_currency': 'USDT BSC'}, {'direction': 'off_ramp'},
                          {'status': 'PROCESSING'}, {'final_amount': -1}):
            self.ramp(conversion=conversion, **overrides)
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_metrics_use_fixed_query_count(self):
        conversion = self.conversion()
        for _ in range(20):
            self.ramp(conversion=conversion, final_amount=1)
        with self.assertNumQueries(3):
            self.assertEqual(deposited_volume_by_provider()['koywe'], 20)

    def test_public_graphql_uses_verified_database_totals_and_cache(self):
        import graphene
        from django.core.cache import cache
        from unittest.mock import patch
        from ramps.schema import Query

        self.addCleanup(cache.delete, 'landing_stats_v3')
        cache.delete('landing_stats_v3')
        self.ramp(conversion=self.conversion(), final_amount=Decimal('12.34'))
        self.ramp(final_amount=999)
        schema = graphene.Schema(query=Query)
        result = schema.execute('{ landingStats { depositedVolumeUsd } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['landingStats']['depositedVolumeUsd'], 12.34)
        with patch('ramps.metrics.deposited_volume_by_provider', side_effect=AssertionError('cache miss')):
            cached = schema.execute('{ landingStats { depositedVolumeUsd } }')
        self.assertIsNone(cached.errors)
        self.assertEqual(cached.data, result.data)


class FundFlowMetricsTests(TestCase):
    """Withdrawals and the shared operation count."""

    ramp = DepositedMetricsTests.ramp

    def test_operation_count_matches_what_the_volume_counts(self):
        self.ramp()  # provider completion alone: not a deposit
        self.ramp(final_currency='USDT BSC', metadata={
            'bsc_arrival_tx_hash': '0x' + 'b' * 64,
            'bsc_arrival_log_index': 2, 'bsc_arrival_amount': '50'})
        self.assertEqual(deposited_volume_by_provider()['koywe'], 50)
        self.assertEqual(deposit_operation_count(), 1)

    def test_withdrawal_counts_actual_amount_once(self):
        self.ramp(direction='off_ramp', crypto_currency='USDC Algorand',
                  crypto_amount_estimated=120, crypto_amount_actual=100)
        self.ramp(direction='off_ramp', crypto_currency='USDT BSC', status='FAILED', crypto_amount_actual=500)
        self.ramp(direction='off_ramp', crypto_currency='USDT BSC',
                  crypto_amount_estimated=80, crypto_amount_actual=None)
        self.assertEqual(withdrawn_volume_and_count(), (Decimal('100'), 1))

    def test_non_dollar_withdrawal_is_not_counted_as_dollars(self):
        self.ramp(direction='off_ramp', provider='guardarian', crypto_currency='ALGO', crypto_amount_actual=1000)
        self.ramp(direction='off_ramp', provider='guardarian', crypto_currency='BTC', crypto_amount_actual=2)
        self.ramp(direction='off_ramp', crypto_currency='USDT BSC', crypto_amount_actual=10)
        self.assertEqual(withdrawn_volume_and_count(), (Decimal('10'), 1))


def pin_future_cutoff(test):
    """Rows in these tests are created "now"; pin the historical cutoff far
    ahead so they stay before it whatever day the suite runs."""
    from datetime import datetime, timezone as tz
    patcher = mock.patch('ramps.direct_transfers.PROOF_CUTOFF', datetime(2100, 1, 1, tzinfo=tz.utc))
    patcher.start()
    test.addCleanup(patcher.stop)


class DirectTransferProofTests(TestCase):
    """ramps.direct_transfers: a proof needs an exact on-chain match."""

    USDC = 31566704

    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        from users.models import Account, User
        pin_future_cutoff(self)
        self.user = User.objects.create(username='proof-user', firebase_uid='proof-uid', phone_country='VE')
        self.wallet = 'W' * 58
        self.other_confio = 'C' * 58
        Account.objects.create(user=self.user, account_type='personal', account_index=0, algorand_address=self.wallet)
        other = User.objects.create(username='other-user', firebase_uid='other-uid')
        Account.objects.create(user=other, account_type='personal', account_index=0, algorand_address=self.other_confio)
        self.now = timezone.now()
        self.later = int((self.now + timedelta(minutes=5)).timestamp())

    def deposit(self, amount='40', source='X' * 58):
        from usdc_transactions.models import USDCDeposit
        return USDCDeposit.objects.create(actor_user=self.user, actor_type='user', amount=Decimal(amount),
            actor_address=self.wallet, source_address=source, status='COMPLETED')

    def tx(self, txid, sender, receiver, units, round_time=None):
        return {'id': txid, 'sender': sender, 'round-time': round_time or self.later,
                'asset-transfer-transaction': {'asset-id': self.USDC, 'amount': units, 'receiver': receiver}}

    def indexer(self, *txs):
        fake = mock.Mock()
        fake.search_transactions.return_value = {'transactions': list(txs)}
        return fake

    def run_verify(self, indexer, **kwargs):
        from ramps.direct_transfers import verify_direct_transfers
        with self.settings(ALGORAND_USDC_ASSET_ID=self.USDC, ALGORAND_SPONSOR_ADDRESS='S' * 58):
            return verify_direct_transfers(indexer, **kwargs)

    def test_exact_match_records_proof_and_counts(self):
        from ramps.models import DirectTransferProof
        deposit = self.deposit()
        outcome = self.run_verify(self.indexer(self.tx('TX1', 'X' * 58, self.wallet, 40_000_000)))
        self.assertEqual(outcome, {'verified': 1})
        proof = DirectTransferProof.objects.get()
        self.assertEqual((proof.usdc_deposit_id, proof.transaction_hash, proof.amount), (deposit.pk, 'TX1', Decimal('40')))

    def test_wrong_amount_wrong_sender_or_outside_window_is_not_proof(self):
        from datetime import timedelta
        self.deposit()
        far = int((self.now + timedelta(days=3)).timestamp())
        outcome = self.run_verify(self.indexer(
            self.tx('TX1', 'X' * 58, self.wallet, 39_000_000),
            self.tx('TX2', 'Q' * 58, self.wallet, 40_000_000),
            self.tx('TX3', 'X' * 58, self.wallet, 40_000_000, round_time=far),
        ))
        self.assertEqual(outcome, {'no_matching_transfer': 1})

    def test_transfers_between_confio_wallets_are_excluded(self):
        self.deposit(source=self.other_confio)
        indexer = self.indexer(self.tx('TX1', self.other_confio, self.wallet, 40_000_000))
        self.assertEqual(self.run_verify(indexer), {'internal_counterparty': 1})
        indexer.search_transactions.assert_not_called()

    def test_dollar_plus_bridge_arrival_is_excluded(self):
        from conversion.models import Conversion
        Conversion.objects.bulk_create([Conversion(conversion_type='from_savings', status='COMPLETED',
            from_amount=40, to_amount=40, bridge_arrival_tx='TXBRIDGE')])
        self.deposit()
        outcome = self.run_verify(self.indexer(self.tx('TXBRIDGE', 'X' * 58, self.wallet, 40_000_000)))
        self.assertEqual(outcome, {'bridge_arrival': 1})

    def test_deleted_confio_account_is_still_internal(self):
        from users.models import Account
        Account.objects.filter(algorand_address=self.other_confio).update(deleted_at=self.now)
        self.assertFalse(Account.objects.filter(algorand_address=self.other_confio).exists())
        self.deposit(source=self.other_confio)
        indexer = self.indexer(self.tx('TX1', self.other_confio, self.wallet, 40_000_000))
        self.assertEqual(self.run_verify(indexer), {'internal_counterparty': 1})

    def retire(self, address):
        from users.models import Account, RetiredWalletAddress
        account = Account.all_objects.get(algorand_address=address)
        RetiredWalletAddress.objects.create(chain='algorand', address=address, account=account, user=account.user)
        Account.all_objects.filter(pk=account.pk).update(algorand_address=None)

    def test_retired_confio_wallet_is_still_internal_both_directions(self):
        from usdc_transactions.models import USDCWithdrawal
        self.retire(self.other_confio)
        self.deposit(source=self.other_confio)
        USDCWithdrawal.objects.create(actor_user=self.user, actor_type='user', amount=Decimal('5'),
            actor_address=self.wallet, destination_address=self.other_confio.lower(), status='COMPLETED')
        indexer = self.indexer(self.tx('TX1', self.other_confio, self.wallet, 40_000_000))
        self.assertEqual(self.run_verify(indexer), {'internal_counterparty': 2})

    def test_existing_proof_with_a_now_known_internal_counterparty_is_revoked(self):
        from ramps.models import DirectTransferProof
        self.deposit(source=self.other_confio)
        # Proven while the address was not yet known to be Confío's.
        from users.models import Account
        Account.all_objects.filter(algorand_address=self.other_confio).update(algorand_address='Z' * 58)
        self.assertEqual(self.run_verify(self.indexer(
            self.tx('TX1', self.other_confio, self.wallet, 40_000_000))), {'verified': 1})
        Account.all_objects.filter(algorand_address='Z' * 58).update(algorand_address=self.other_confio)
        self.retire(self.other_confio)
        outcome = self.run_verify(self.indexer())
        self.assertEqual(outcome['proofs_revoked'], 1)
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_transfers_to_confio_contracts_are_internal(self):
        from algosdk.logic import get_application_address
        from usdc_transactions.models import USDCWithdrawal
        escrow = get_application_address(744151196)  # a cUSD mint pays USDC to the app escrow
        USDCWithdrawal.objects.create(actor_user=self.user, actor_type='user', amount=Decimal('10'),
            actor_address=self.wallet, destination_address=escrow, status='COMPLETED')
        indexer = self.indexer(self.tx('TXMINT', self.wallet, escrow, 10_000_000))
        with self.settings(ALGORAND_CUSD_APP_ID=744151196):
            self.assertEqual(self.run_verify(indexer), {'internal_counterparty': 1})

    def test_dry_run_matches_a_real_run_after_revocation(self):
        from conversion.models import Conversion
        from ramps.models import DirectTransferProof
        self.deposit()
        self.assertEqual(self.run_verify(self.indexer(self.tx('TXOLD', 'X' * 58, self.wallet, 40_000_000))), {'verified': 1})
        Conversion.objects.bulk_create([Conversion(conversion_type='from_savings', status='COMPLETED',
            from_amount=40, to_amount=40, bridge_arrival_tx='TXOLD')])
        indexer = self.indexer(self.tx('TXOLD', 'X' * 58, self.wallet, 40_000_000),
                               self.tx('TXNEW', 'X' * 58, self.wallet, 40_000_000))
        dry = self.run_verify(indexer, dry_run=True)
        self.assertEqual(DirectTransferProof.objects.get().transaction_hash, 'TXOLD')  # untouched
        real = self.run_verify(indexer)
        self.assertEqual(dry, real)
        self.assertEqual(real, {'proofs_revoked': 1, 'verified': 1})
        self.assertEqual(DirectTransferProof.objects.get().transaction_hash, 'TXNEW')

    def test_rows_after_the_cutoff_are_never_proven_or_counted(self):
        from datetime import timedelta
        from django.utils import timezone
        from ramps.direct_transfers import PROOF_CUTOFF
        from ramps.models import DirectTransferProof
        from usdc_transactions.models import USDCDeposit
        # A fabricated row pairing a registered-but-unowned wallet with a
        # stranger's public transfer, created once the metric is public.
        row = self.deposit()
        USDCDeposit.objects.filter(pk=row.pk).update(created_at=PROOF_CUTOFF + timedelta(days=1))
        late = int((PROOF_CUTOFF + timedelta(days=1, minutes=5)).timestamp())
        self.assertEqual(self.run_verify(self.indexer(self.tx('TXF', 'X' * 58, self.wallet, 40_000_000, round_time=late))), {})
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_replaced_wallet_without_retirement_record_is_still_internal(self):
        from usdc_transactions.models import USDCWithdrawal
        from users.models import Account
        # The other Confío user once withdrew from their old wallet...
        other = Account.all_objects.get(algorand_address=self.other_confio)
        USDCWithdrawal.objects.create(actor_user=other.user, actor_type='user', amount=Decimal('1'),
            actor_address=self.other_confio, destination_address='E' * 58, status='COMPLETED')
        # ...then replaced it via the legacy path, which records nothing.
        Account.all_objects.filter(pk=other.pk).update(algorand_address='R' * 58)
        self.deposit(source=self.other_confio)
        indexer = self.indexer(self.tx('TX1', self.other_confio, self.wallet, 40_000_000))
        self.assertEqual(self.run_verify(indexer).get('internal_counterparty'), 1)

    def test_wallet_known_only_from_payment_history_is_internal(self):
        from users.models import Account
        Account.all_objects.filter(algorand_address=self.other_confio).update(algorand_address='R' * 58)  # replaced, unrecorded
        self.deposit(source=self.other_confio)
        indexer = self.indexer(self.tx('TX1', self.other_confio, self.wallet, 40_000_000))
        # Its only surviving trace is a payment (building a real invoice is out of scope here).
        with mock.patch('payments.models.PaymentTransaction.all_objects') as payments:
            chain = payments.all.return_value.exclude.return_value.exclude.return_value
            chain.values_list.return_value.distinct.return_value = [self.other_confio]
            self.assertEqual(self.run_verify(indexer).get('internal_counterparty'), 1)

    def test_command_clears_the_public_cache_on_revocation_only_runs(self):
        from django.core.cache import cache
        from django.core.management import call_command
        cache.set('fund_flow_stats_v4', {'total_usd': 1}, 600)
        with mock.patch('ramps.direct_transfers.verify_direct_transfers', return_value={'proofs_revoked': 1}), \
             mock.patch('blockchain.algorand_client.AlgorandClient'):
            call_command('verify_direct_transfers', stdout=mock.Mock())
        self.assertIsNone(cache.get('fund_flow_stats_v4'))

    def test_transfer_behind_a_ramp_cannot_prove_a_duplicate_row(self):
        from ramps.models import DirectTransferProof
        linked = self.deposit()
        RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='on_ramp',
            status='COMPLETED', usdc_deposit=linked)])
        self.deposit()  # a second, unlinked row for the SAME on-chain transfer
        outcome = self.run_verify(self.indexer(self.tx('TX1', 'X' * 58, self.wallet, 40_000_000)))
        self.assertEqual(outcome, {'ramp_transfers_reserved': 1, 'transfer_already_counted': 1})
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_every_transfer_a_ramp_could_own_is_reserved(self):
        from datetime import timedelta
        from ramps.models import DirectTransferProof
        from usdc_transactions.models import USDCDeposit
        # Two ramp rows at +24h and +48h; transfers at +12h and +30h. Taking
        # only the newest match per ramp would free +12h for the orphan.
        rows = []
        for hours in (24, 48):
            row = self.deposit()
            USDCDeposit.objects.filter(pk=row.pk).update(created_at=self.now + timedelta(hours=hours))
            rows.append(row)
        RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='on_ramp',
            status='COMPLETED', usdc_deposit=row) for row in rows])
        self.deposit()  # orphan duplicate at +0h
        t12 = int((self.now + timedelta(hours=12)).timestamp())
        t30 = int((self.now + timedelta(hours=30)).timestamp())
        indexer = self.indexer(self.tx('T30', 'X' * 58, self.wallet, 40_000_000, round_time=t30),
                               self.tx('T12', 'X' * 58, self.wallet, 40_000_000, round_time=t12))
        outcome = self.run_verify(indexer)
        self.assertEqual(outcome['transfer_already_counted'], 1)
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_proof_is_revoked_when_its_transfer_later_backs_a_ramp(self):
        from ramps.models import DirectTransferProof
        orphan = self.deposit()
        indexer = self.indexer(self.tx('TX1', 'X' * 58, self.wallet, 40_000_000))
        self.assertEqual(self.run_verify(indexer), {'verified': 1})
        duplicate = self.deposit()  # attributed to a ramp only after the first run
        RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='on_ramp',
            status='COMPLETED', usdc_deposit=duplicate)])
        self.assertEqual(self.run_verify(indexer, dry_run=True)['proofs_revoked'], 1)
        self.assertTrue(DirectTransferProof.objects.filter(usdc_deposit=orphan).exists())  # dry run keeps it
        outcome = self.run_verify(indexer)
        self.assertEqual(outcome['proofs_revoked'], 1)
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_admin_cannot_add_change_or_delete_proofs(self):
        from django.contrib.admin.sites import AdminSite
        from ramps.admin import DirectTransferProofAdmin
        from ramps.models import DirectTransferProof
        admin = DirectTransferProofAdmin(DirectTransferProof, AdminSite())
        self.assertFalse(admin.has_add_permission(None))
        self.assertFalse(admin.has_change_permission(None))
        self.assertFalse(admin.has_delete_permission(None))
        from types import SimpleNamespace
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = SimpleNamespace(has_perm=lambda *_: True, is_active=True, is_staff=True)
        self.assertNotIn('delete_selected', admin.get_actions(request))

    def test_ramp_row_with_lowercase_address_still_reserves_its_transfer(self):
        from ramps.models import DirectTransferProof
        linked = self.deposit(source=('X' * 58).lower())
        RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='on_ramp',
            status='COMPLETED', usdc_deposit=linked)])
        self.deposit()  # scanner duplicate, uppercase
        outcome = self.run_verify(self.indexer(self.tx('TX1', 'X' * 58, self.wallet, 40_000_000)))
        self.assertEqual(outcome, {'ramp_transfers_reserved': 1, 'transfer_already_counted': 1})
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_completed_ramp_reserves_its_transfer_even_if_linked_row_is_processing(self):
        from usdc_transactions.models import USDCWithdrawal
        from ramps.models import DirectTransferProof
        common = dict(actor_user=self.user, actor_type='user', amount=Decimal('20'),
                      actor_address=self.wallet, destination_address='Y' * 58)
        linked = USDCWithdrawal.objects.create(status='PROCESSING', **common)
        RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='off_ramp',
            status='COMPLETED', crypto_currency='USDC Algorand', crypto_amount_actual=Decimal('20'),
            usdc_withdrawal=linked)])
        USDCWithdrawal.objects.create(status='COMPLETED', **common)  # orphan, same payout
        outcome = self.run_verify(self.indexer(self.tx('TXOUT', self.wallet, 'Y' * 58, 20_000_000)))
        self.assertEqual(outcome, {'ramp_transfers_reserved': 1, 'transfer_already_counted': 1})
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_clawback_is_never_proof(self):
        self.deposit()
        clawback = self.tx('TX1', 'X' * 58, self.wallet, 40_000_000)
        clawback['asset-transfer-transaction']['sender'] = self.other_confio
        self.assertEqual(self.run_verify(self.indexer(clawback)), {'no_matching_transfer': 1})

    def test_inner_transfer_is_reported_not_proven(self):
        from ramps.models import DirectTransferProof
        self.deposit()
        parent = {'id': 'APPCALL', 'sender': 'X' * 58, 'round-time': self.later, 'tx-type': 'appl',
                  'inner-txns': [{'tx-type': 'axfer', 'sender': 'X' * 58, 'asset-transfer-transaction': {
                      'asset-id': self.USDC, 'amount': 40_000_000, 'receiver': self.wallet}}]}
        self.assertEqual(self.run_verify(self.indexer(parent)), {'inner_transfer_unsupported': 1})
        self.assertFalse(DirectTransferProof.objects.exists())

    def test_follows_indexer_pages(self):
        self.deposit()
        fake = mock.Mock()
        fake.search_transactions.side_effect = [
            {'transactions': [self.tx('TXA', 'Q' * 58, self.wallet, 40_000_000)], 'next-token': 'p2'},
            {'transactions': [self.tx('TXB', 'X' * 58, self.wallet, 40_000_000)]},
        ]
        self.assertEqual(self.run_verify(fake), {'verified': 1})
        self.assertEqual(fake.search_transactions.call_args_list[1].kwargs['next_page'], 'p2')

    def test_bridge_arrival_is_skipped_not_final(self):
        from conversion.models import Conversion
        from ramps.models import DirectTransferProof
        Conversion.objects.bulk_create([Conversion(conversion_type='from_savings', status='COMPLETED',
            from_amount=40, to_amount=40, bridge_arrival_tx='TXBRIDGE')])
        self.deposit()
        outcome = self.run_verify(self.indexer(
            self.tx('TXBRIDGE', 'X' * 58, self.wallet, 40_000_000),
            self.tx('TXREAL', 'X' * 58, self.wallet, 40_000_000),
        ))
        self.assertEqual(outcome, {'verified': 1})
        self.assertEqual(DirectTransferProof.objects.get().transaction_hash, 'TXREAL')

    def test_one_transaction_proves_one_row_and_dry_run_writes_nothing(self):
        from ramps.models import DirectTransferProof
        self.deposit(); self.deposit()  # two rows, one on-chain transfer
        indexer = self.indexer(self.tx('TX1', 'X' * 58, self.wallet, 40_000_000))
        self.assertEqual(self.run_verify(indexer, dry_run=True), {'verified': 1, 'transfer_already_counted': 1})
        self.assertFalse(DirectTransferProof.objects.exists())
        self.assertEqual(self.run_verify(indexer), {'verified': 1, 'transfer_already_counted': 1})
        self.assertEqual(DirectTransferProof.objects.count(), 1)
        # Rerunnable: the proven row is skipped; the other's transfer is taken.
        self.assertEqual(self.run_verify(indexer), {'transfer_already_counted': 1})


class PerimeterFlowTests(TestCase):
    """Movido = conversions across the Confío-dollar perimeter; cUSD <-> cUSD+ excluded."""

    def setUp(self):
        from users.models import User
        self.people = [User.objects.create(username=f'flow{i}', firebase_uid=f'flow-uid-{i}', phone_country='BR')
                       for i in range(5)]

    def conversion(self, conversion_type, amount_in, amount_out=None, *, direction='', user=None, **overrides):
        values = dict(conversion_type=conversion_type, status='COMPLETED', from_amount=Decimal(amount_in),
                      to_amount=Decimal(amount_out if amount_out is not None else amount_in),
                      perimeter_direction=direction, actor_user=user or self.people[0], actor_type='user')
        values.update(overrides)
        return Conversion.objects.bulk_create([Conversion(**values)])[0]

    def test_entries_and_exits_from_every_era(self):
        self.conversion('usdc_to_cusd', '10')                                   # Algorand, unlabeled
        self.conversion('usdt_to_cusd', '20', '19.8', direction='entry')        # BSC
        self.conversion('to_savings', '5', direction='entry')                   # straight into Dollar+
        self.conversion('cusd_to_usdc', '7')                                    # Algorand exit
        self.conversion('cusd_to_usdt', '12', '11.9', direction='exit')         # BSC exit, after fee
        self.conversion('from_savings', '3', direction='exit')
        flow = fund_flow_breakdown()
        # Entries at what came in; exits at what went out.
        self.assertEqual((flow['deposited_usd'], flow['deposit_count']), (Decimal('35'), 3))
        self.assertEqual((flow['withdrawn_usd'], flow['withdrawal_count']), (Decimal('21.9'), 3))

    def test_only_cusd_cusd_plus_moves_are_excluded(self):
        self.conversion('to_savings', '50', direction='internal')
        self.conversion('from_savings', '50', direction='internal')
        self.conversion('usdc_to_algo', '9')                                     # never crosses
        self.conversion('usdt_to_cusd', '99', status='FAILED', direction='entry')
        self.conversion('usdt_to_cusd', '99', is_deleted=True, direction='entry')
        flow = fund_flow_breakdown()
        self.assertEqual((flow['deposit_count'], flow['withdrawal_count']), (0, 0))

    def test_every_channel_counts_once(self):
        # A ramp's deposit is counted by its conversion, never on top of it.
        conv = self.conversion('usdt_to_cusd', '40', direction='entry')
        RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='on_ramp',
            status='COMPLETED', destination='cusd', final_amount=40, final_currency='CUSD_BSC', conversion=conv)])
        flow = fund_flow_breakdown()
        self.assertEqual((flow['deposited_usd'], flow['deposit_count']), (Decimal('40'), 1))

    def test_countries_need_five_people_and_show_counts_not_dollars(self):
        for person in self.people:
            self.conversion('usdt_to_cusd', '10', direction='entry', user=person)
        from users.models import User
        whale = User.objects.create(username='whale', firebase_uid='whale-uid', phone_country='CL')
        for _ in range(4):
            self.conversion('cusd_to_usdt', '5000', direction='exit', user=whale)
        flow = fund_flow_breakdown()
        self.assertEqual(flow['countries'], [('BR', 5)])
        self.assertEqual(flow['withdrawn_usd'], Decimal('20000'))
        self.assertIsNotNone(flow['since'])

    def test_withdrawal_median_still_comes_from_fiat_payouts(self):
        from datetime import timedelta
        self.conversion('cusd_to_usdt', '10', direction='exit')
        for minutes in range(1, 11):
            ramp = RampTransaction.objects.bulk_create([RampTransaction(provider='koywe', direction='off_ramp',
                status='COMPLETED', crypto_currency='USDT BSC', crypto_amount_actual=Decimal('10'))])[0]
            RampTransaction.objects.filter(pk=ramp.pk).update(completed_at=ramp.created_at + timedelta(minutes=minutes))
        flow = fund_flow_breakdown()
        self.assertEqual(flow['withdrawal_timing_samples'], 10)
        self.assertAlmostEqual(flow['median_withdrawal_minutes'], 5.5, places=3)
        self.assertEqual(flow['withdrawal_count'], 1)  # volume comes from conversions only
