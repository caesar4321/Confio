from types import SimpleNamespace

from django.contrib import admin
from django.test import RequestFactory
from django.test import TestCase
from unittest import mock

from humanitarian.models import (
    HumanitarianCampaign,
    HumanitarianRelease,
    HumanitarianVolunteerApplication,
)
from humanitarian.admin import HumanitarianReleaseAdmin
from humanitarian.services import HumanitarianReleaseService
from users.models import Account, RetiredWalletAddress, User


class HumanitarianReleaseWalletSafetyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='humanitarian-recipient',
            email='humanitarian-recipient@example.com',
            firebase_uid='humanitarian-recipient-firebase',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            algorand_address='A' * 58,
        )
        self.campaign = HumanitarianCampaign.objects.create(
            slug='wallet-safety',
            title='Wallet safety',
        )
        self.application = HumanitarianVolunteerApplication.objects.create(
            user=self.user,
            campaign=self.campaign,
            status='approved',
        )

    def _release(self, address):
        return HumanitarianRelease.objects.create(
            campaign=self.campaign,
            volunteer_application=self.application,
            amount='10.00',
            purpose='Test aid',
            recipient_address=address,
        )

    def test_linked_release_refuses_address_that_no_longer_matches_account(self):
        release = self._release('B' * 58)
        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)

        with self.assertRaisesRegex(ValueError, 'wallet changed'):
            service._validate_recipient_wallet(release)

    def test_release_refuses_tombstoned_destination(self):
        release = self._release(self.account.algorand_address)
        RetiredWalletAddress.objects.create(
            chain=RetiredWalletAddress.CHAIN_ALGORAND,
            address=self.account.algorand_address,
            account=self.account,
            user=self.user,
        )
        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)

        with self.assertRaisesRegex(ValueError, 'has been retired'):
            service._validate_recipient_wallet(release)

    def test_submission_claim_allows_only_one_broadcast(self):
        release = self._release(self.account.algorand_address)
        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)

        claimed = service._claim_submission(
            release,
            'T' * 52,
            'exact-signed-b64',
            10,
            100,
        )
        self.assertEqual(claimed.status, 'submitted')
        self.assertEqual(claimed.transaction_hash, 'T' * 52)
        self.assertEqual(claimed.signed_transaction_b64, 'exact-signed-b64')
        self.assertEqual(claimed.submitted_first_valid_round, 10)
        self.assertEqual(claimed.submitted_last_valid_round, 100)

        with self.assertRaisesRegex(ValueError, 'Only draft or failed'):
            service._claim_submission(release, 'U' * 52, 'other-signed-b64', 11, 101)

    def _claimed_release(self):
        release = self._release(self.account.algorand_address)
        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)
        return service._claim_submission(
            release,
            'T' * 52,
            'exact-signed-b64',
            10,
            100,
        )

    def test_reconcile_rebroadcasts_only_exact_claimed_bytes_before_expiry(self):
        release = self._claimed_release()

        class Algod:
            sent = []

            def pending_transaction_info(self, txid):
                return {}

            def status(self):
                return {'last-round': 50}

            def send_raw_transaction(self, payload):
                self.sent.append(payload)
                return 'T' * 52

        class Indexer:
            def search_transactions(self, **kwargs):
                return {'current-round': 50, 'transactions': []}

        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)
        service.algod = Algod()
        with mock.patch('humanitarian.services.get_indexer_client', return_value=Indexer()):
            outcome = service.reconcile_submission(release)

        self.assertEqual(outcome, 'submitted')
        self.assertEqual(service.algod.sent, ['exact-signed-b64'])

    def test_reconcile_marks_failed_only_after_expiry_and_indexer_absence(self):
        release = self._claimed_release()

        class Algod:
            def pending_transaction_info(self, txid):
                return {}

            def status(self):
                return {'last-round': 101}

        class Indexer:
            def search_transactions(self, **kwargs):
                return {'current-round': 101, 'transactions': []}

        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)
        service.algod = Algod()
        with mock.patch('humanitarian.services.get_indexer_client', return_value=Indexer()):
            outcome = service.reconcile_submission(release)

        self.assertEqual(outcome, 'failed')
        release.refresh_from_db()
        self.assertEqual(release.status, 'failed')

    def test_reconcile_confirms_indexed_tx_exactly_once(self):
        release = self._claimed_release()

        class Algod:
            pass

        class Indexer:
            def search_transactions(self, **kwargs):
                return {'current-round': 50, 'transactions': [{'id': 'T' * 52}]}

        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)
        service.algod = Algod()
        with mock.patch('humanitarian.services.get_indexer_client', return_value=Indexer()):
            self.assertEqual(service.reconcile_submission(release), 'confirmed')
            self.assertEqual(service.reconcile_submission(release), 'confirmed')

        release.refresh_from_db()
        self.campaign.refresh_from_db()
        self.assertEqual(release.status, 'confirmed')
        self.assertEqual(self.campaign.release_count, 1)


class HumanitarianReleaseAdminStateMachineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='humanitarian-admin-recipient',
            firebase_uid='humanitarian-admin-recipient-uid',
        )
        self.campaign = HumanitarianCampaign.objects.create(
            slug='admin-state-machine',
            title='Admin state machine',
        )
        self.application = HumanitarianVolunteerApplication.objects.create(
            user=self.user,
            campaign=self.campaign,
            status='approved',
        )
        self.model_admin = HumanitarianReleaseAdmin(
            HumanitarianRelease,
            admin.AdminSite(),
        )
        self.model_admin.message_user = mock.Mock()
        self.request = SimpleNamespace(user=self.user)
        self.form_request = RequestFactory().get('/admin/humanitarian/release/')
        self.form_request.user = self.user

    def _release(self, status):
        return HumanitarianRelease.objects.create(
            campaign=self.campaign,
            volunteer_application=self.application,
            amount='10.00',
            status=status,
            purpose='Admin transition test',
            recipient_address='A' * 58,
            transaction_hash=('T' * 52 if status == 'submitted' else ''),
            signed_transaction_b64=('signed' if status == 'submitted' else ''),
            submitted_last_valid_round=(100 if status == 'submitted' else None),
        )

    @mock.patch('humanitarian.admin.get_algod_client', return_value=mock.Mock())
    @mock.patch(
        'humanitarian.admin.HumanitarianReleaseService.reconcile_submission',
        return_value='submitted',
    )
    def test_admin_cannot_force_submitted_release_to_confirmed(
        self, reconcile_mock, _algod_mock
    ):
        release = self._release('submitted')

        self.model_admin.mark_confirmed(
            self.request,
            HumanitarianRelease.objects.filter(pk=release.pk),
        )

        release.refresh_from_db()
        self.assertEqual(release.status, 'submitted')
        reconcile_mock.assert_called_once()

    def test_proof_actions_reject_unconfirmed_release(self):
        release = self._release('submitted')

        self.model_admin.mark_proof_pending(
            self.request,
            HumanitarianRelease.objects.filter(pk=release.pk),
        )
        self.model_admin.mark_proof_published(
            self.request,
            HumanitarianRelease.objects.filter(pk=release.pk),
        )

        release.refresh_from_db()
        self.assertEqual(release.status, 'submitted')

    def test_proof_actions_follow_confirmed_pending_published_order(self):
        release = self._release('confirmed')
        queryset = HumanitarianRelease.objects.filter(pk=release.pk)

        self.model_admin.mark_proof_pending(self.request, queryset)
        release.refresh_from_db()
        self.assertEqual(release.status, 'proof_pending')

        self.model_admin.mark_proof_published(self.request, queryset)
        release.refresh_from_db()
        self.assertEqual(release.status, 'proof_published')

    def test_change_form_cannot_edit_submitted_state_or_payout_identity(self):
        release = self._release('submitted')

        form_class = self.model_admin.get_form(self.form_request, obj=release)

        self.assertNotIn('status', form_class.base_fields)
        for field in self.model_admin.PAYOUT_IDENTITY_FIELDS:
            self.assertNotIn(field, form_class.base_fields)

    def test_failed_form_can_repair_identity_but_cannot_force_status(self):
        release = self._release('failed')

        form_class = self.model_admin.get_form(self.form_request, obj=release)

        self.assertNotIn('status', form_class.base_fields)
        self.assertIn('amount', form_class.base_fields)
        self.assertIn('recipient_address', form_class.base_fields)

    def test_submitted_release_cannot_be_deleted_or_bulk_deleted(self):
        release = self._release('submitted')

        self.assertFalse(self.model_admin.has_delete_permission(self.form_request, release))
        self.assertNotIn('delete_selected', self.model_admin.get_actions(self.form_request))

    def test_stale_draft_form_cannot_erase_concurrent_submission_claim(self):
        release = self._release('draft')
        stale_form_instance = HumanitarianRelease.objects.get(pk=release.pk)
        HumanitarianRelease.objects.filter(pk=release.pk).update(
            status='submitted',
            transaction_hash='T' * 52,
            signed_transaction_b64='exact-signed-b64',
            submitted_first_valid_round=10,
            submitted_last_valid_round=100,
        )
        stale_form_instance.status = 'failed'
        stale_form_instance.amount = '999.00'
        stale_form_instance.recipient_address = 'B' * 58

        self.model_admin.save_model(
            self.form_request,
            stale_form_instance,
            form=mock.Mock(),
            change=True,
        )

        release.refresh_from_db()
        self.assertEqual(release.status, 'submitted')
        self.assertEqual(release.transaction_hash, 'T' * 52)
        self.assertEqual(release.signed_transaction_b64, 'exact-signed-b64')
        self.assertEqual(release.amount, 10)
        self.assertEqual(release.recipient_address, 'A' * 58)
