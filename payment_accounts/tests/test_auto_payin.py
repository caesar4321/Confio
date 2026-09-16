from unittest import mock
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from payment_accounts.auto_payin import enqueue, process, sync_verified_rail
from payment_accounts.models import AutomaticPayin, InfiniaJourney, LedgerEntry
from .test_infinia_journeys import JourneyTests


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
    PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
    PAYMENT_BRIDGE_POLYGON_ENABLED=True, CUSD_PLUS_7702_ENABLED=True)
class AutomaticPayinTests(TestCase):
    setUp = JourneyTests.setUp
    credit = JourneyTests.credit
    inbound = JourneyTests.inbound
    quote = JourneyTests.quote
    prepared = JourneyTests.prepared

    def test_clabe_snapshot_verifies_spei_and_removal_clears_it(self):
        self.local.country, self.local.asset = 'MEX', 'MXN'
        self.local.provider_data = {'latest': {'funding_instructions': {
            'type': 'fiat', 'account_number': '032180000118359719'}}}
        self.local.save()
        sync_verified_rail(self.local)
        self.local.refresh_from_db()
        self.assertEqual(self.local.payin_rail, 'SPEI')
        self.local.provider_data['latest']['funding_instructions']['account_number'] = '032180000118359710'
        self.local.save(update_fields=['provider_data'])
        sync_verified_rail(self.local)
        self.local.refresh_from_db()
        self.assertEqual(self.local.payin_rail, '')

    def test_country_alone_does_not_verify_a_rail(self):
        self.local.country, self.local.asset = 'MEX', 'MXN'
        self.local.provider_data = {'latest': {'funding_instructions': []}}
        self.local.save()
        sync_verified_rail(self.local)
        self.assertEqual(self.local.payin_rail, '')

    def test_other_verified_receiving_shapes(self):
        for country, asset, instruction, rail in [
            ('BRA', 'BRL', {'pix_key_brl': {'pix_key': 'receiver@example.com'}}, 'PIX'),
            ('COL', 'COP', {'breb_key': '@receiver'}, 'BREB'),
            ('ARG', 'ARS', {'type': 'fiat', 'account_number': '2850590940090418135201'}, 'CBU'),
        ]:
            self.local.country, self.local.asset = country, asset
            self.local.provider_data = {'latest': {'funding_instructions': instruction}}
            self.local.save()
            sync_verified_rail(self.local)
            self.assertEqual(self.local.payin_rail, rail)

    def test_queue_is_idempotent_and_does_not_scan_old_deposits(self):
        old = self.credit(self.local)
        entry = self.credit(self.local)
        row = enqueue(entry)
        self.assertEqual(enqueue(entry).pk, row.pk)
        self.assertFalse(AutomaticPayin.objects.filter(entry=old).exists())

    def test_detection_uses_locked_latest_snapshot_and_preserves_other_metadata(self):
        from payment_accounts.models import FinancialAccount
        self.local.country, self.local.asset = 'BRA', 'BRL'
        self.local.save()
        FinancialAccount.objects.filter(pk=self.local.pk).update(provider_data={
            'unrelated': 'keep', 'latest': {'funding_instructions': {'pix_key': 'key'}}})
        sync_verified_rail(self.local)
        self.local.refresh_from_db()
        self.assertEqual(self.local.payin_rail, 'PIX')
        self.assertEqual(self.local.provider_data['unrelated'], 'keep')
        self.assertEqual(self.local.provider_data['receiving_rail_detection']['status'], 'verified')
        self.local.provider_data['latest'] = {}
        self.local.save()
        sync_verified_rail(self.local)
        self.assertEqual(self.local.payin_rail, '')

    def test_inferred_rail_does_not_unlock_admission(self):
        from payment_accounts.payin_admission import decision
        self.local.country, self.local.asset = 'USA', 'USD'
        self.local.provider_data = {'latest': {'funding_instructions': {
            'type': 'fiat', 'account_number': '12345678', 'bank_code': '021000021'}}}
        self.local.save()
        sync_verified_rail(self.local)
        self.assertEqual(self.local.payin_rail, '')
        entry = self.credit(self.local)
        self.assertEqual(decision(entry)[1], 'unverified_rail')

    def test_allowed_deposit_creates_exactly_one_direct_journey(self):
        entry = self.credit(self.local)
        row = enqueue(entry)
        with mock.patch('payment_accounts.local_money._active_pair', return_value=(self.local, self.crypto)), \
             mock.patch('payment_accounts.local_money.deposit_quote', return_value={
                 'minimum_fx_output': '2', 'minimum_wallet_output': '2.4'}) as quote:
            process(row.pk)
            process(row.pk)
        quote.assert_called_once()
        journey = InfiniaJourney.objects.get(funding_credit=entry)
        self.assertEqual(journey.wallet_address, self.owner.bsc_address.lower())
        self.assertEqual(str(journey.minimum_wallet_output), '2.400000000000000000')
        self.assertTrue(journey.money_flow.metadata['automatic_payin'])
        self.submit.assert_not_called()  # Only the existing journey worker moves funds.

    def test_revoked_admission_never_quotes_or_creates_journey(self):
        entry = self.credit(self.local, provider_data={'third_party': {'type': 'FIAT', 'full_name': 'Other', 'document_number': 'other'}})
        row = enqueue(entry)
        with mock.patch('payment_accounts.local_money.deposit_quote') as quote:
            result = process(row.pk)
        self.assertEqual(result.status, 'pending')
        self.assertEqual(result.reason, 'country_not_enabled')
        quote.assert_not_called()
        self.assertFalse(InfiniaJourney.objects.filter(funding_credit=entry).exists())

    def test_credit_with_later_debit_is_not_replayed(self):
        entry = self.credit(self.local)
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local,
            provider_entry_id='spent', direction='debit', asset=self.local.asset,
            amount='10', occurred_at=timezone.now())
        result = process(enqueue(entry).pk)
        self.assertEqual((result.status, result.reason), ('review', 'subsequent_debit_requires_review'))
        self.assertFalse(InfiniaJourney.objects.filter(funding_credit=entry).exists())

    def allocated_debit(self):
        from payment_accounts.models import MoneyOperation
        journey = self.inbound()
        entry = self.credit(self.local)
        op = MoneyOperation.objects.create(provider='infinia', money_flow=journey.money_flow,
            operation_type='conversion', source_account=self.local, destination_account=self.crypto,
            source_asset=self.local.asset, target_asset=self.crypto.asset, source_amount='10',
            status='succeeded', provider_operation_id='prior-conversion', idempotency_key='prior-conversion')
        journey.fx_operation, journey.stage = op, 'completed'
        journey.save()
        debit = LedgerEntry.objects.create(provider='infinia', financial_account=self.local,
            provider_entry_id='allocated-debit', direction='debit', asset=self.local.asset,
            amount='10', occurred_at=timezone.now(), operation=op,
            provider_data={'operation': {'type': 'INTERNAL_TRANSFER', 'operation_id': op.provider_operation_id}})
        return entry, debit

    def test_second_receipt_can_start_after_first_receipts_own_conversion(self):
        entry, _ = self.allocated_debit()
        with mock.patch('payment_accounts.local_money._active_pair', return_value=(self.local, self.crypto)), \
             mock.patch('payment_accounts.local_money.deposit_quote', return_value={
                 'minimum_fx_output': '2', 'minimum_wallet_output': '2.4'}):
            result = process(enqueue(entry).pk)
        self.assertEqual(result.status, 'started')
        self.assertTrue(InfiniaJourney.objects.filter(funding_credit=entry).exists())

    def test_second_receipt_waits_for_inflight_debit_before_allocation_review(self):
        from payment_accounts.services import PaymentAccountError
        entry, debit = self.allocated_debit()
        op = debit.operation
        op.status = 'processing'
        op.save(update_fields=['status'])
        row = enqueue(entry)
        with mock.patch('payment_accounts.auto_payin.has_unallocated_debit') as proof:
            with self.assertRaises(PaymentAccountError):
                process(row.pk)
            proof.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
        op.status = 'succeeded'
        op.save(update_fields=['status'])
        with mock.patch('payment_accounts.local_money._active_pair', return_value=(self.local, self.crypto)), \
             mock.patch('payment_accounts.local_money.deposit_quote', return_value={
                 'minimum_fx_output': '2', 'minimum_wallet_output': '2.4'}):
            result = process(row.pk)
        self.assertEqual(result.status, 'started')

    def test_debit_allocation_requires_complete_provider_and_amount_proof(self):
        from payment_accounts.auto_payin import has_unallocated_debit
        entry, debit = self.allocated_debit()
        self.assertFalse(has_unallocated_debit(entry))
        for data, amount in [({}, '10'), ({'operation': {'operation_id': 'wrong'}}, '10'),
                (debit.provider_data, '11'), (debit.provider_data, '9')]:
            with self.subTest(data=data, amount=amount):
                LedgerEntry.objects.filter(pk=debit.pk).update(provider_data=data, amount=amount)
                self.assertTrue(has_unallocated_debit(entry))

    def test_manual_journey_wins_without_duplicate_conversion(self):
        journey = self.inbound()
        result = process(enqueue(journey.funding_credit).pk)
        self.assertEqual(result.status, 'started')
        self.assertEqual(InfiniaJourney.objects.count(), 1)

    def test_conversion_proceeds_are_not_enqueued(self):
        entry = self.credit(self.crypto)
        self.assertIsNone(enqueue(entry))

    def test_linked_provider_legs_are_not_automatic_payins_without_raw_operation_id(self):
        from payment_accounts.models import MoneyOperation, MoneyFlow
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='fund',
            source_asset=self.local.asset, source_amount='10', target_asset=self.local.asset)
        for kind in ['conversion', 'internal_transfer', 'payout']:
            with self.subTest(kind=kind):
                op = MoneyOperation.objects.create(provider='infinia', money_flow=flow,
                    operation_type=kind, source_account=self.crypto, destination_account=self.local,
                    source_asset=self.crypto.asset, target_asset=self.local.asset,
                    source_amount='10', status='succeeded', idempotency_key='provenance-' + kind)
                entry = self.credit(self.local, operation=op)
                self.assertIsNone(enqueue(entry))
                # Also cover a queued credit later correlated to its operation.
                row = AutomaticPayin.objects.create(entry=entry)
                with mock.patch('payment_accounts.local_money.deposit_quote') as quote:
                    result = process(row.pk)
                self.assertEqual((result.status, result.reason), ('review', 'not_external_payin'))
                quote.assert_not_called()
                self.assertFalse(InfiniaJourney.objects.filter(funding_credit=entry).exists())

    def test_voucher_correlated_provider_leg_is_excluded_before_full_settlement_proof(self):
        from payment_accounts.models import MoneyOperation, MoneyFlow
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='fund',
            source_asset=self.local.asset, source_amount='10', target_asset=self.local.asset)
        for kind in ['conversion', 'internal_transfer']:
            with self.subTest(kind=kind):
                voucher = 'correlated-' + kind
                entry = self.credit(self.local, provider_data={'operation': None,
                    'third_party': {'type': 'FIAT', 'full_name': 'Holder', 'document_number': '123',
                        'document_type': 'DNI', 'voucher_id': voucher}})
                row = enqueue(entry)
                self.assertIsNotNone(row)
                op = MoneyOperation.objects.create(provider='infinia', money_flow=flow,
                    operation_type=kind, source_account=self.crypto, destination_account=self.crypto,
                    source_asset=self.crypto.asset, target_asset=self.local.asset, source_amount='10',
                    status='succeeded', idempotency_key=voucher, provider_data={'voucher_ids': [voucher]})
                self.assertIsNotNone(enqueue(entry))  # Another destination does not correlate.
                op.destination_account = self.local
                op.save(update_fields=['destination_account'])
                self.assertIsNone(enqueue(entry))
                with mock.patch('payment_accounts.local_money.deposit_quote') as quote:
                    result = process(row.pk)
                self.assertEqual((result.status, result.reason), ('review', 'not_external_payin'))
                quote.assert_not_called()
                self.assertFalse(InfiniaJourney.objects.filter(funding_credit=entry).exists())

    def test_authenticated_movement_enqueues_once_and_repairs_clabe_rail(self):
        from payment_accounts.models import ProviderWebhookEvent
        from payment_accounts.webhooks import _record_ledger_entry
        self.local.country, self.local.asset, self.local.payin_rail = 'MEX', 'MXN', ''
        self.local.provider_data = {'latest': {'funding_instructions': {
            'type': 'fiat', 'account_number': '032180000118359719'}}}
        self.local.save()
        event = ProviderWebhookEvent.objects.create(provider='infinia', event_id='mx-payin', payload={})
        normalized = {'resource_id': 'mx-credit', 'payload': {'id': 'mx-credit', 'amount': '32.51',
            'currency': 'MXN', 'balance': '32.51', 'created_at': timezone.now().isoformat(),
            'operation': {'type': 'CREDIT', 'operation_id': None},
            'third_party': {'type': 'FIAT', 'full_name': 'Other', 'document_number': '456'}}}
        _record_ledger_entry(event, normalized, self.local, None)
        _record_ledger_entry(event, normalized, self.local, None)
        self.local.refresh_from_db()
        self.assertEqual(self.local.payin_rail, 'SPEI')
        self.assertEqual(AutomaticPayin.objects.count(), 1)
        self.assertEqual(AutomaticPayin.objects.get().entry.amount, Decimal('32.51'))

    def test_quote_outage_keeps_deposit_pending_without_partial_journey(self):
        from payment_accounts.auto_payin import reconcile
        row = enqueue(self.credit(self.local))
        with mock.patch('payment_accounts.local_money._active_pair', return_value=(self.local, self.crypto)), \
             mock.patch('payment_accounts.local_money.deposit_quote', side_effect=RuntimeError('offline')):
            reconcile()
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
        self.assertEqual(row.reason, 'waiting_for_safe_quote_or_account')
        self.assertFalse(InfiniaJourney.objects.exists())
