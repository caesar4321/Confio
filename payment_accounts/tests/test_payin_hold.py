from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from payment_accounts import payin_hold
from payment_accounts.auto_payin import enqueue, process
from payment_accounts.models import AutomaticPayin, InfiniaJourney, LedgerEntry
from security.models import FaceCheck
from . import test_infinia_journeys as journeys  # module import: no re-run of its tests

QUOTE = {'minimum_fx_output': '2', 'minimum_wallet_output': '2.4'}


@override_settings(INFINIA_THIRD_PARTY_PAYIN_DEFAULT_ENABLED=False, INFINIA_JOURNEYS_ENABLED=True,
    INFINIA_PAYMENT_ACCOUNTS_ENABLED=True, PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
    PAYMENT_BRIDGE_POLYGON_ENABLED=True, CUSD_PLUS_7702_ENABLED=True, FACE_STEP_UP_ENABLED=True)
class PayinHoldTests(TestCase):
    setUp_journeys = journeys.JourneyTests.setUp
    credit = journeys.JourneyTests.credit
    inbound = journeys.JourneyTests.inbound
    quote = journeys.JourneyTests.quote
    prepared = journeys.JourneyTests.prepared

    def setUp(self):
        self.setUp_journeys()
        self.owner.account_type = 'personal'
        self.owner.save(update_fields=['account_type'])
        patches = [
            mock.patch('payment_accounts.local_money._active_pair', return_value=(self.local, self.crypto)),
            mock.patch('payment_accounts.local_money.deposit_quote', return_value=QUOTE),
        ]
        self.quote_mock = patches[1].start()
        patches[0].start()
        for p in patches:
            self.addCleanup(p.stop)

    def _face(self, minutes_ago=0, status='passed'):
        return FaceCheck.objects.create(
            user=self.owner.user, purpose='payin_release', liveness_session_id=f's-{FaceCheck.objects.count()}',
            status=status, completed_at=timezone.now() - timedelta(minutes=minutes_ago))

    def _held(self):
        entry = self.credit(self.local)
        row = enqueue(entry)
        with mock.patch('notifications.utils.create_notification') as notify, \
             self.captureOnCommitCallbacks(execute=True):
            process(row.pk)
        row.refresh_from_db()
        return entry, row, notify

    # Hold

    def test_personal_payin_waits_for_the_face_without_quoting(self):
        entry, row, notify = self._held()
        self.assertEqual(row.status, 'awaiting_face')
        self.assertIsNotNone(row.awaiting_since)
        self.quote_mock.assert_not_called()
        self.assertFalse(InfiniaJourney.objects.filter(funding_credit=entry).exists())
        self.assertEqual(notify.call_args.kwargs['action_url'], 'confio://pending-incoming')

    def test_an_open_face_window_converts_straight_away(self):
        self._face()
        entry = self.credit(self.local)
        row = process(enqueue(entry).pk)
        self.assertEqual(row.status, 'started')
        self.assertTrue(InfiniaJourney.objects.filter(funding_credit=entry).exists())

    def test_business_accounts_are_never_held(self):
        self.owner.account_type = 'business'
        self.owner.save(update_fields=['account_type'])
        entry = self.credit(self.local)
        row = process(enqueue(entry).pk)
        self.assertEqual(row.status, 'started')

    @override_settings(FACE_STEP_UP_ENABLED=False)
    def test_nothing_is_held_while_enforcement_is_off(self):
        entry = self.credit(self.local)
        self.assertEqual(process(enqueue(entry).pk).status, 'started')

    # Release

    def test_release_needs_a_passed_face(self):
        _, row, _ = self._held()
        self.assertEqual(payin_hold.release_for(self.owner), [])
        self._face(status='failed')
        self.assertEqual(payin_hold.release_for(self.owner), [])
        row.refresh_from_db()
        self.assertEqual(row.status, 'awaiting_face')

    def test_one_face_releases_the_whole_queue(self):
        first, _, _ = self._held()
        second, _, _ = self._held()
        self._face()
        released = payin_hold.release_for(self.owner)
        # One conversion per account at a time: the first starts now, the second
        # leaves the hold as 'pending' and reconcile converts it after the first.
        self.assertEqual([r.status for r in released], ['started', 'pending'])
        self.assertTrue(InfiniaJourney.objects.filter(funding_credit=first).exists())
        self.assertFalse(AutomaticPayin.objects.filter(status='awaiting_face').exists())
        self.assertEqual(payin_hold.serialize(released[1])['state'], 'releasing')

    def test_a_face_passed_elsewhere_releases_in_reconcile(self):
        entry, _, _ = self._held()
        self._face()  # e.g. a withdrawal check a minute ago
        payin_hold.release_open_windows()
        self.assertTrue(InfiniaJourney.objects.filter(funding_credit=entry).exists())

    # Return after 24 hours

    def _expire(self, entry):
        LedgerEntry.objects.filter(pk=entry.pk).update(occurred_at=timezone.now() - timedelta(hours=25))

    def test_unconfirmed_payin_is_refunded_in_full_once(self):
        entry, row, _ = self._held()
        self._expire(entry)
        with mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit',
                        return_value={'id': 'r1', 'status': 'PENDING'}) as refund:
            payin_hold.start_expired_returns()
            payin_hold.start_expired_returns()
        refund.assert_called_once()
        kwargs = refund.call_args.kwargs
        self.assertEqual(str(kwargs['movement_id']), str(entry.provider_entry_id))
        self.assertEqual(kwargs['idempotency_key'], f'confio-payin-return-{entry.internal_id}')
        row.refresh_from_db()
        self.assertEqual((row.status, row.return_method, row.return_provider_id),
                         ('returning', 'provider_refund', 'r1'))
        self.assertEqual(row.return_details['returned'], str(row.entry.amount))

    def test_not_yet_24_hours_stays_held(self):
        entry, row, _ = self._held()
        with mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit') as refund:
            payin_hold.start_expired_returns()
        refund.assert_not_called()

    def test_a_face_before_expiry_wins_over_the_return(self):
        entry, row, _ = self._held()
        self._face()
        payin_hold.release_for(self.owner)
        self._expire(entry)
        with mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit') as refund:
            payin_hold.start_expired_returns()
        refund.assert_not_called()

    def test_refund_outcomes_are_tracked_including_a_late_failure(self):
        entry, row, _ = self._held()
        self._expire(entry)
        with mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit',
                        return_value={'id': 'r1', 'status': 'SUCCESS'}):
            payin_hold.start_expired_returns()
        row.refresh_from_db()
        self.assertEqual(row.status, 'returned')
        AutomaticPayin.objects.filter(pk=row.pk).update(updated_at=timezone.now() - timedelta(minutes=20))
        with mock.patch('payment_accounts.clients.InfiniaClient.find_deposit_refund',
                        return_value={'id': 'r1', 'status': 'FAILED', 'failure_reason': 'closed account'}):
            payin_hold.sync_returns()
        row.refresh_from_db()
        self.assertEqual((row.status, row.return_details['failure_reason']), ('return_failed', 'closed account'))

    def test_a_refund_that_never_reached_infinia_is_resubmitted_with_the_same_key(self):
        entry, row, _ = self._held()
        self._expire(entry)
        with mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit', side_effect=RuntimeError('timeout')):
            payin_hold.start_expired_returns()
        row.refresh_from_db()
        self.assertEqual(row.status, 'returning')
        AutomaticPayin.objects.filter(pk=row.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
        with mock.patch('payment_accounts.clients.InfiniaClient.find_deposit_refund', return_value=None), \
             mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit',
                        return_value={'id': 'r2', 'status': 'PENDING'}) as refund:
            payin_hold.sync_returns()
        self.assertEqual(refund.call_args.kwargs['idempotency_key'], row.return_idempotency_key)

    # GraphQL

    def _info(self):
        return SimpleNamespace(context=SimpleNamespace(user=self.owner.user))

    def test_query_lists_held_payins_for_the_personal_account(self):
        from payment_accounts.pending_payin_schema import PendingPayinQuery
        entry, row, _ = self._held()
        with mock.patch('payment_accounts.schema._active_account', return_value=self.owner):
            items = PendingPayinQuery().resolve_pending_incoming_payins(self._info())
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].state, items[0].id), ('awaiting_face', str(entry.internal_id)))
        self.assertEqual(items[0].returns_at - items[0].received_at, timedelta(hours=24))

    def test_release_mutation_asks_for_a_face_first(self):
        from payment_accounts.pending_payin_schema import ReleasePendingPayins
        self._held()
        with mock.patch('payment_accounts.schema._active_account', return_value=self.owner):
            result = ReleasePendingPayins().mutate(self._info())
            self.assertEqual((result.success, result.next_step), (False, 'face_check'))
            self._face()
            result = ReleasePendingPayins().mutate(self._info())
        self.assertTrue(result.success)
        self.assertEqual(len(result.released), 1)

    # Round-1 audit fixes

    def _manual(self, entry):
        import uuid
        from payment_accounts.infinia_journeys import create_journey
        return create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
            request_id=uuid.uuid4(), minimum_fx_output='2', minimum_wallet_output='2.4',
            direction='to_wallet', credit=entry)

    def test_a_manual_conversion_cannot_skip_the_hold(self):
        from payment_accounts.services import PaymentAccountError
        entry, _, _ = self._held()
        with self.assertRaises(PaymentAccountError):
            self._manual(entry)
        AutomaticPayin.objects.filter(entry=entry).update(released_at=timezone.now())
        self.assertIsNotNone(self._manual(entry).pk)

    def test_a_returned_deposit_cannot_be_converted(self):
        from payment_accounts.services import PaymentAccountError
        entry, row, _ = self._held()
        AutomaticPayin.objects.filter(pk=row.pk).update(status='returning')
        self._face()
        with self.assertRaises(PaymentAccountError):
            self._manual(entry)

    def test_no_refund_once_a_journey_exists(self):
        entry, row, _ = self._held()
        AutomaticPayin.objects.filter(pk=row.pk).update(released_at=timezone.now())
        self._manual(entry)
        AutomaticPayin.objects.filter(pk=row.pk).update(released_at=None)
        self._expire(entry)
        with mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit') as refund:
            payin_hold.start_expired_returns()
        refund.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, 'started')

    def test_consent_survives_the_window_so_a_retry_is_never_re_held(self):
        entry, row, _ = self._held()
        face = self._face()
        payin_hold.release_for(self.owner)
        FaceCheck.objects.filter(pk=face.pk).update(completed_at=timezone.now() - timedelta(hours=2))
        AutomaticPayin.objects.filter(pk=row.pk).update(status='pending')  # e.g. a failed attempt retried
        InfiniaJourney.objects.filter(funding_credit=entry).delete()
        row = process(row.pk)
        self.assertNotEqual(row.status, 'awaiting_face')

    def test_our_refund_of_one_deposit_does_not_send_another_to_review(self):
        from payment_accounts.auto_payin import has_unallocated_debit
        first, first_row, _ = self._held()
        second, _, _ = self._held()
        AutomaticPayin.objects.filter(pk=first_row.pk).update(
            status='returning', return_details={'debit_movement_id': 'mv-refund'})
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local, provider_entry_id='mv-refund',
            direction='debit', asset=first.asset, amount=first.amount, occurred_at=timezone.now())
        self.assertFalse(has_unallocated_debit(second))
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local, provider_entry_id='mv-other',
            direction='debit', asset=first.asset, amount=first.amount, occurred_at=timezone.now())
        self.assertTrue(has_unallocated_debit(second))

    def test_turning_enforcement_off_drains_holds_and_returns_nothing(self):
        entry, row, _ = self._held()
        self._expire(entry)
        with override_settings(FACE_STEP_UP_ENABLED=False), \
             mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit') as refund:
            payin_hold.start_expired_returns()
            payin_hold.release_open_windows()
        refund.assert_not_called()
        row.refresh_from_db()
        self.assertEqual((row.status, row.reason), ('pending', 'face_enforcement_off'))
        self.assertIsNotNone(row.released_at)

    def test_reconcile_starts_from_confirmed_people_not_from_the_queue(self):
        for _ in range(3):
            self._held()
        with mock.patch.object(payin_hold, 'release_for') as release:
            payin_hold.release_open_windows(limit=1)
            release.assert_not_called()  # nobody confirmed: the queue is not scanned
            self._face()
            payin_hold.release_open_windows(limit=1)
        release.assert_called_once_with(self.owner)

    # Round-2 audit fixes

    def test_a_payin_is_held_even_while_another_journey_holds_the_account(self):
        face = self._face()
        self.inbound()  # active conversion reserves the account
        face.delete()
        _, row, _ = self._held()
        self.assertEqual(row.status, 'awaiting_face')
        self.assertIsNotNone(row.awaiting_since)

    def test_an_unnamed_refund_debit_defers_other_conversions_instead_of_review(self):
        from payment_accounts.auto_payin import has_unallocated_debit
        from payment_accounts.services import PaymentAccountError
        first, first_row, _ = self._held()
        second, _, _ = self._held()
        AutomaticPayin.objects.filter(pk=first_row.pk).update(status='returning', return_details={},
            updated_at=timezone.now() - timedelta(minutes=2))
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local, provider_entry_id='mv-refund',
            direction='debit', asset=first.asset, amount=first.amount, occurred_at=timezone.now())
        with self.assertRaises(PaymentAccountError):  # retryable: stays pending
            has_unallocated_debit(second)
        # Infinia names it: ours. A same-amount debit it did not name is not.
        with mock.patch('payment_accounts.clients.InfiniaClient.find_deposit_refund',
                        return_value={'id': 'r1', 'status': 'PENDING', 'debit_movement_id': 'mv-refund'}):
            payin_hold.sync_returns()
        self.assertFalse(has_unallocated_debit(second))
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local, provider_entry_id='mv-reversal',
            direction='debit', asset=first.asset, amount=first.amount, occurred_at=timezone.now())
        self.assertTrue(has_unallocated_debit(second))

    def test_consent_from_an_open_window_outlives_a_busy_account(self):
        face = self._face()
        self.inbound()  # busy: the next conversion must wait
        entry = self.credit(self.local)
        row = enqueue(entry)
        with self.assertRaises(Exception):
            process(row.pk)
        face.delete()  # the window closes before the account frees up
        row.refresh_from_db()
        self.assertIsNotNone(row.released_at)
        self.assertEqual(row.status, 'pending')

    # Round-4 audit fixes

    def test_a_webhook_refund_debit_with_its_unsolicited_operation_is_recognised(self):
        from payment_accounts.auto_payin import has_unallocated_debit
        from payment_accounts.models import MoneyFlow, MoneyOperation
        first, first_row, _ = self._held()
        second, _, _ = self._held()
        AutomaticPayin.objects.filter(pk=first_row.pk).update(
            status='returning', return_details={'debit_movement_id': 'mv-refund'})
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='withdraw', status='needs_review',
            source_asset=first.asset, source_amount=first.amount, target_asset=first.asset, target_amount=first.amount,
            gross_amount=first.amount, net_amount=first.amount, metadata={'unsolicited': True})
        op = MoneyOperation.objects.create(money_flow=flow, provider='infinia', operation_type='payout',
            source_account=self.local, idempotency_key='ledger-x', status='needs_review',
            source_asset=first.asset, source_amount=first.amount, target_asset=first.asset, target_amount=first.amount)
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local, provider_entry_id='mv-refund',
            operation=op, direction='debit', asset=first.asset, amount=first.amount, occurred_at=timezone.now())
        self.assertFalse(has_unallocated_debit(second))

    def test_a_refund_rejected_outright_fails_instead_of_retrying_forever(self):
        from payment_accounts.clients import ProviderAPIError
        entry, row, _ = self._held()
        self._expire(entry)
        with mock.patch('payment_accounts.clients.InfiniaClient.refund_deposit',
                        side_effect=ProviderAPIError('not refundable', status_code=422)):
            payin_hold.start_expired_returns()
        row.refresh_from_db()
        self.assertEqual(row.status, 'return_failed')
        self.assertIn('422', row.return_details['failure_reason'])

    # Round-6 audit fixes

    def test_money_consented_in_a_window_is_listed_while_it_waits(self):
        from payment_accounts.pending_payin_schema import PendingPayinQuery
        face = self._face()
        self.inbound()  # busy account: the new deposit waits as pending
        entry = self.credit(self.local)
        row = enqueue(entry)
        with self.assertRaises(Exception):
            process(row.pk)
        face.delete()
        with mock.patch('payment_accounts.schema._active_account', return_value=self.owner):
            items = PendingPayinQuery().resolve_pending_incoming_payins(self._info())
        self.assertEqual([(i.id, i.state) for i in items], [(str(entry.internal_id), 'releasing')])

    def test_a_stale_success_never_undoes_a_failed_refund(self):
        entry, row, _ = self._held()
        AutomaticPayin.objects.filter(pk=row.pk).update(status='return_failed', return_details={'failure_reason': 'x'})
        payin_hold._apply_refund_status(row.pk, {'id': 'r1', 'status': 'SUCCESS'})
        row.refresh_from_db()
        self.assertEqual(row.status, 'return_failed')
