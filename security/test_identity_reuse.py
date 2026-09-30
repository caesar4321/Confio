from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from security.face_step_up import require_face_step_up
from security.models import IdentityVerification, SuspiciousActivity, UserBan

MESSAGE = 'Las salidas de tu cuenta están temporalmente restringidas. Contacta con soporte para revisar tu cuenta.'


@override_settings(FACE_STEP_UP_ENABLED=False)
class IdentityReuseTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.original = User.objects.create_user(username='original-identity', firebase_uid='original-identity')
        self.recycled = User.objects.create_user(username='recycled-identity', firebase_uid='recycled-identity')
        self.reviewer = User.objects.create_user(username='reviewer', firebase_uid='reviewer', is_staff=True)
        self.first = self.verify(self.original, 'AB-123')
        self.second = self.verify(self.recycled, 'ab123')
        self.ban = UserBan.objects.create(user=self.original, ban_type='permanent', reason='fraud')

    def verify(self, user, number, country='COL', kind='national_id', **extra):
        return IdentityVerification.all_documents.create(
            user=user, document_number=number, document_issuing_country=country,
            document_type=kind, status='verified', verified_date_of_birth='1990-01-01',
            **extra)

    def check(self):
        return require_face_step_up(self.recycled, 'withdrawal')

    def test_matching_banned_identity_denied_even_when_face_disabled(self):
        self.assertEqual(self.check(), MESSAGE)

    def test_expired_or_lifted_ban_does_not_hold_account(self):
        self.ban.expires_at = timezone.now() - timedelta(seconds=1)
        self.ban.save()
        self.assertEqual(self.check(), '')
        self.ban.ban_type = 'temporary'
        self.ban.expires_at = timezone.now() - timedelta(seconds=1)
        self.ban.save()
        self.assertEqual(self.check(), '')
        self.ban.ban_type = 'permanent'
        self.ban.deleted_at = timezone.now()
        self.ban.save()
        self.assertEqual(self.check(), '')

    def test_unrelated_country_or_document_type_is_not_a_match(self):
        self.second.document_issuing_country = 'PER'
        self.second.save()
        self.assertEqual(self.check(), '')
        self.second.document_issuing_country = 'COL'
        self.second.document_type = 'passport'
        self.second.save()
        self.assertEqual(self.check(), '')

    def test_unverified_and_business_documents_do_not_match(self):
        self.second.status = 'pending'
        self.second.save()
        self.assertEqual(self.check(), '')
        self.second.status = 'verified'
        self.second.risk_factors = {'account_type': 'business'}
        self.second.save()
        self.assertEqual(self.check(), '')

    def test_additional_and_soft_deleted_verified_documents_still_match(self):
        self.second.is_additional_document = True
        self.second.deleted_at = timezone.now()
        self.second.save()
        self.first.deleted_at = timezone.now()
        self.first.save()
        self.assertEqual(self.check(), MESSAGE)

    def test_ban_added_after_kyc_takes_effect_without_reverification(self):
        self.ban.soft_delete()
        self.assertEqual(self.check(), '')
        UserBan.objects.create(user=self.original, ban_type='permanent', reason='fraud')
        self.assertEqual(self.check(), MESSAGE)

    def test_manual_release_requires_reviewer_notes_and_is_ban_specific(self):
        self.assertEqual(self.check(), MESSAGE)
        case = SuspiciousActivity.objects.get(
            user=self.recycled, detection_data__trigger='identity_reuse_active_ban')
        case.status = 'dismissed'
        case.save()
        self.assertEqual(self.check(), MESSAGE)
        case.investigated_by = self.reviewer
        case.investigation_notes = 'Identity match investigated; outgoing activity approved.'
        case.save()
        self.assertEqual(self.check(), '')
        UserBan.objects.create(user=self.original, ban_type='permanent', reason='document_fraud')
        self.assertEqual(self.check(), MESSAGE)

    def test_repeated_checks_reuse_review_case(self):
        self.check()
        self.check()
        self.assertEqual(SuspiciousActivity.objects.filter(
            user=self.recycled, detection_data__trigger='identity_reuse_active_ban').count(), 1)

    def test_incoming_funding_face_purpose_is_not_held(self):
        from security.face_step_up import missing_face_step_up
        self.assertEqual(missing_face_step_up(self.recycled, 'on_ramp'), '')

    def test_legacy_outgoing_boundaries_reject_before_preparing_or_broadcasting(self):
        from types import SimpleNamespace
        from graphql import GraphQLError
        from blockchain.payment_mutations import CreateSponsoredPaymentMutation, SubmitSponsoredPaymentMutation
        from blockchain.invite_send_mutations import PrepareInviteForPhone, SubmitInviteForPhone
        from blockchain.p2p_trade_mutations import PrepareP2PCreateTrade, SubmitP2PCreateTrade
        from payroll.schema import PreparePayrollVaultFunding, SubmitPayrollVaultFunding
        info = SimpleNamespace(context=SimpleNamespace(user=self.recycled))
        operations = [
            (CreateSponsoredPaymentMutation, {'amount': 1}),
            (SubmitSponsoredPaymentMutation, {'signed_transactions': []}),
            (PrepareInviteForPhone, {'phone': '123', 'amount': 1}),
            (SubmitInviteForPhone, {'signed_user_txn': '', 'sponsor_transactions': [], 'invitation_id': '1'}),
            (PrepareP2PCreateTrade, {'trade_id': '1', 'amount': 1}),
            (SubmitP2PCreateTrade, {'trade_id': '1', 'signed_user_txns': [], 'sponsor_transactions': []}),
            (PreparePayrollVaultFunding, {'amount': 1}),
            (SubmitPayrollVaultFunding, {'signed_transactions': []}),
        ]
        for mutation, kwargs in operations:
            with self.subTest(mutation=mutation.__name__), self.assertRaises(GraphQLError):
                # Some legacy KYC decorators run first: call their wrapped
                # resolver to isolate the outgoing identity boundary.
                import inspect
                method = inspect.unwrap(mutation.mutate)
                if getattr(method, '__self__', None) is not None:
                    method(None, info, **kwargs)
                else:
                    method(mutation, None, info, **kwargs)

    def test_raw_submit_allows_optin_but_not_solo_transfer_or_rekey(self):
        import base64
        import msgpack
        from graphql import GraphQLError
        from security.identity_reuse import require_identity_for_signed_algorand
        def blob(txn):
            return base64.b64encode(msgpack.packb({'txn': txn}, use_bin_type=True)).decode()
        optin = {'type': 'axfer', 'snd': b'a' * 32, 'arcv': b'a' * 32, 'xaid': 123}
        require_identity_for_signed_algorand(self.recycled, blob(optin))
        for extra in ({'aamt': 1}, {'rekey': b'b' * 32}, {'aclose': b'b' * 32}):
            with self.assertRaises(GraphQLError):
                require_identity_for_signed_algorand(self.recycled, blob({**optin, **extra}))

    @override_settings(ALGORAND_CUSD_APP_ID=123)
    def test_autoswap_allows_internal_burn_but_rejects_appended_outflow(self):
        import msgpack
        from algosdk.encoding import encode_address, decode_address
        from algosdk.logic import get_application_address
        from graphql import GraphQLError
        from security.identity_reuse import require_identity_for_autoswap
        actor = b'a' * 32
        address = encode_address(actor)
        burn = {'type': 'axfer', 'snd': actor,
                'arcv': decode_address(get_application_address(123)), 'aamt': 100}
        def pack(txn):
            return msgpack.packb({'txn': txn}, use_bin_type=True)
        require_identity_for_autoswap(self.recycled, [pack(burn)], address)
        with self.assertRaises(GraphQLError):
            require_identity_for_autoswap(self.recycled, [pack(burn),
                pack({'type': 'axfer', 'snd': actor, 'arcv': b'b' * 32, 'aamt': 100})], address)

    def test_bsc_business_and_merchant_exemptions_do_not_bypass_hold(self):
        from send.bsc_flow import _send_step_up
        from payments.bsc_flow import _payment_step_up
        self.assertEqual(_send_step_up(self.recycled, object(), None), MESSAGE)
        self.assertEqual(_payment_step_up(self.recycled, object(), object()), MESSAGE)

    def test_bank_payout_business_exemption_does_not_bypass_hold(self):
        from types import SimpleNamespace
        from payment_accounts.services import require_outgoing_face, PaymentAccountError
        with self.assertRaises(PaymentAccountError):
            require_outgoing_face(SimpleNamespace(user=self.recycled, account_type='business'),
                                  'payout', 'one', {})

    def test_usdc_deposit_does_not_apply_outgoing_guard(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from usdc_transactions.schema import CreateUSDCDeposit, CreateUSDCWithdrawal
        from graphql import GraphQLError
        info = SimpleNamespace(context=SimpleNamespace(user=self.recycled))
        with patch('security.identity_reuse.require_outgoing_identity', side_effect=GraphQLError('held')) as guard:
            # Stop at context validation; reaching it proves a deposit does
            # not consult the outgoing guard even for a held identity.
            with patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=None), \
                 patch('security.integrity_service.app_check_service.verify_request_header', return_value={'success': True}):
                CreateUSDCDeposit.mutate(None, info, SimpleNamespace())
            guard.assert_not_called()
            with self.assertRaises(GraphQLError):
                CreateUSDCWithdrawal.mutate(None, info, SimpleNamespace())

    def test_payroll_payout_blocked_on_prepare_and_submit(self):
        from payroll.bsc_flow import prepare_bsc_payroll_payout, submit_bsc_payroll_payout
        self.assertEqual(prepare_bsc_payroll_payout(self.recycled, {}, None)['error'], MESSAGE)
        self.assertEqual(submit_bsc_payroll_payout(self.recycled, {}, None, '')['error'], MESSAGE)

    def test_admin_release_requires_notes_and_records_reviewer(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from django.contrib.admin.sites import AdminSite
        from security.admin import SuspiciousActivityAdmin
        self.check()
        cases = SuspiciousActivity.objects.filter(user=self.recycled,
                          detection_data__trigger='identity_reuse_active_ban')
        admin = SuspiciousActivityAdmin(SuspiciousActivity, AdminSite())
        request = SimpleNamespace(user=self.reviewer)
        with patch.object(admin, 'message_user'):
            admin.mark_as_dismissed(request, cases)
            self.assertEqual(self.check(), MESSAGE)
            cases.update(investigation_notes='Document match reviewed and released.')
            admin.mark_as_dismissed(request, cases)
        self.assertEqual(self.check(), '')
        self.assertEqual(cases.get().investigated_by_id, self.reviewer.pk)

    def test_legacy_websocket_money_out_guards(self):
        import inspect
        from types import SimpleNamespace
        from unittest.mock import patch
        from graphql import GraphQLError
        from presale.ws_consumers import PresaleSessionConsumer
        from humanitarian.ws_consumers import HumanitarianSessionConsumer
        from usdc_transactions.ws_consumers import WithdrawSessionConsumer
        cases = [
            (PresaleSessionConsumer, '_prepare', {'amount': 1}),
            (PresaleSessionConsumer, '_submit', {'purchase_id': 'one', 'signed_transactions': [], 'sponsor_transactions': []}),
            (HumanitarianSessionConsumer, '_donation_prepare', {'campaign_slug': 'one', 'amount': 1}),
            (WithdrawSessionConsumer, '_prepare', {'amount': '1', 'destination_address': 'one'}),
            (WithdrawSessionConsumer, '_submit', {'internal_id': 'one', 'signed_transactions': [], 'sponsor_transactions': []}),
        ]
        for consumer_class, name, kwargs in cases:
            consumer = consumer_class()
            consumer.scope = {'user': self.recycled}
            with self.subTest(operation=name, consumer=consumer_class.__name__), self.assertRaises(GraphQLError):
                inspect.getattr_static(consumer_class, name).func(consumer, **kwargs)
        consumer = HumanitarianSessionConsumer()
        consumer.scope = {'user': self.recycled}
        with patch('humanitarian.models.HumanitarianDonation.objects.select_related') as rows:
            rows.return_value.get.return_value = SimpleNamespace(status='pending', transaction_hash='')
            with self.assertRaises(GraphQLError):
                inspect.getattr_static(HumanitarianSessionConsumer, '_donation_submit').func(consumer, 'one', [], [])
            rows.return_value.get.assert_called_once_with(public_id='one', donor_user=self.recycled)

    @override_settings(ALGORAND_CUSD_APP_ID=123, ALGORAND_USDC_ASSET_ID=456, ALGORAND_NETWORK='testnet')
    def test_canonical_algo_autodeposit_allowed_but_other_pool_rejected(self):
        import msgpack
        from algosdk.encoding import encode_address, decode_address
        from algosdk.logic import get_application_address
        from tinyman.v2.constants import TESTNET_VALIDATOR_APP_ID
        from tinyman.v2.contracts import get_pool_logicsig
        from graphql import GraphQLError
        from security.identity_reuse import require_identity_for_autoswap
        actor = b'a' * 32
        pool = decode_address(get_pool_logicsig(TESTNET_VALIDATOR_APP_ID, 0, 456).address())
        txns = [
            {'type': 'pay', 'snd': actor, 'rcv': pool, 'amt': 100},
            {'type': 'appl', 'snd': actor, 'apid': TESTNET_VALIDATOR_APP_ID,
             'apaa': [b'swap', b'fixed-input', b'\x00' * 8], 'apat': [pool], 'apas': [456, 0]},
            {'type': 'axfer', 'snd': actor, 'xaid': 456, 'aamt': 100,
             'arcv': decode_address(get_application_address(123))},
        ]
        def packed():
            return [msgpack.packb({'txn': t}, use_bin_type=True) for t in txns]
        require_identity_for_autoswap(self.recycled, packed(), encode_address(actor))
        txns[0]['rcv'] = b'b' * 32
        with self.assertRaises(GraphQLError):
            require_identity_for_autoswap(self.recycled, packed(), encode_address(actor))

    def test_preflight_preserves_case_after_mutation_rolls_back(self):
        from types import SimpleNamespace
        from django.db import transaction
        from security.identity_reuse import IdentityReviewMiddleware
        mutation_type = object()
        info = SimpleNamespace(context=SimpleNamespace(user=self.recycled),
                               parent_type=mutation_type,
                               schema=SimpleNamespace(mutation_type=mutation_type))
        def rejected(root, info):
            with transaction.atomic():
                self.check()
                raise ValueError('resolver rollback')
        with self.assertRaises(ValueError):
            IdentityReviewMiddleware().resolve(rejected, None, info)
        self.assertEqual(SuspiciousActivity.objects.filter(user=self.recycled,
                         detection_data__trigger='identity_reuse_active_ban').count(), 1)

    def test_preflight_does_not_block_support_or_incoming_mutations(self):
        from types import SimpleNamespace
        from security.identity_reuse import IdentityReviewMiddleware
        mutation_type = object()
        info = SimpleNamespace(context=SimpleNamespace(user=self.recycled),
                               parent_type=mutation_type,
                               schema=SimpleNamespace(mutation_type=mutation_type))
        self.assertEqual(IdentityReviewMiddleware().resolve(lambda *a, **kw: 'allowed', None, info), 'allowed')


@override_settings(FACE_STEP_UP_ENABLED=False)
class BannedPhoneReuseTests(TestCase):
    """A banned account's verified number, verified again by another account."""

    def setUp(self):
        User = get_user_model()
        self.banned = User.objects.create_user(
            username='banned-phone', firebase_uid='banned-phone', phone_number='3001234567', phone_country='CO')
        self.newcomer = User.objects.create_user(username='newcomer-phone', firebase_uid='newcomer-phone')
        self.reviewer = User.objects.create_user(username='phone-reviewer', firebase_uid='phone-reviewer',
                                                 is_staff=True)
        self.ban = UserBan.objects.create(user=self.banned, ban_type='permanent', reason='fraud')

    def take_number(self, previous_owner=None):
        # What users.phone_linking does: the number leaves its old owner.
        if previous_owner is not None:
            previous_owner.phone_number = previous_owner.phone_country = None
            previous_owner.save()
        self.newcomer.phone_number, self.newcomer.phone_country = '3001234567', 'CO'
        self.newcomer.save()

    def check(self):
        return require_face_step_up(self.newcomer, 'withdrawal')

    def test_the_ban_records_a_hash_never_the_number(self):
        self.assertEqual(len(self.ban.phone_hash), 64)
        self.assertNotIn('3001234567', self.ban.phone_hash)

    def test_a_relinked_number_holds_the_new_account(self):
        self.assertEqual(self.check(), '')
        self.take_number(previous_owner=self.banned)
        self.assertEqual(self.check(), MESSAGE)
        case = SuspiciousActivity.objects.get(user=self.newcomer, detection_data__trigger='phone_reuse_active_ban')
        self.assertEqual(list(case.related_users.values_list('pk', flat=True)), [self.banned.pk])

    def test_deleting_the_banned_account_does_not_free_the_number(self):
        self.banned.soft_delete()
        self.take_number()
        self.assertEqual(self.check(), MESSAGE)

    def test_a_lifted_or_expired_ban_releases_the_number(self):
        self.take_number(previous_owner=self.banned)
        self.ban.soft_delete()
        self.assertEqual(self.check(), '')
        UserBan.objects.create(user=self.banned, ban_type='temporary', reason='fraud',
                               expires_at=timezone.now() - timedelta(seconds=1),
                               phone_hash=self.ban.phone_hash)
        self.assertEqual(self.check(), '')

    def test_support_releases_a_recycled_number_with_notes(self):
        # Carriers reassign inactive numbers: the new owner may be innocent.
        self.take_number(previous_owner=self.banned)
        self.assertEqual(self.check(), MESSAGE)
        case = SuspiciousActivity.objects.get(user=self.newcomer, detection_data__trigger='phone_reuse_active_ban')
        case.status, case.investigated_by = 'dismissed', self.reviewer
        case.investigation_notes = 'Carrier-recycled number; unrelated person.'
        case.save()
        self.assertEqual(self.check(), '')

    def test_the_banned_account_itself_is_not_held_twice(self):
        self.assertEqual(require_face_step_up(self.banned, 'withdrawal'), '')

    def test_a_ban_without_a_number_records_nothing(self):
        ban = UserBan.objects.create(user=self.newcomer, ban_type='permanent', reason='fraud')
        self.assertEqual(ban.phone_hash, '')

    def test_existing_bans_are_backfilled(self):
        import importlib
        from django.apps import apps
        UserBan.all_objects.filter(pk=self.ban.pk).update(phone_hash='')
        importlib.import_module('security.migrations.0021_userban_phone_hash').backfill(apps, None)
        self.ban.refresh_from_db()
        self.assertEqual(len(self.ban.phone_hash), 64)
        self.take_number(previous_owner=self.banned)
        self.assertEqual(self.check(), MESSAGE)

    def test_admin_bulk_dismissal_releases_a_phone_case_only_with_notes(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from django.contrib.admin.sites import AdminSite
        from security.admin import SuspiciousActivityAdmin
        self.take_number(previous_owner=self.banned)
        self.check()
        cases = SuspiciousActivity.objects.filter(user=self.newcomer, detection_data__trigger='phone_reuse_active_ban')
        admin = SuspiciousActivityAdmin(SuspiciousActivity, AdminSite())
        request = SimpleNamespace(user=self.reviewer)
        with patch.object(admin, 'message_user'):
            admin.mark_as_dismissed(request, cases)
            self.assertEqual(self.check(), MESSAGE)
            cases.update(investigation_notes='Carrier-recycled number; unrelated person.')
            admin.mark_as_dismissed(request, cases)
        self.assertEqual(self.check(), '')
        self.assertEqual(cases.get().investigated_by_id, self.reviewer.pk)
