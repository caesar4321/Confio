"""Fee referral: half of the cUSD border fee to the referrer, on-chain.

Covers who gets an arm (eligible_arm), how the sponsor checks it
(strip_arm / strip_stored_arm), and how finalized ReferralPaid logs become
FeeReferralPayout rows plus one push each.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from eth_utils import keccak

from cusd_plus import fee_referral
from cusd_plus.sponsor_7702 import SEL_ARM_REFERRAL, SEL_CUSD_MINT, PolicyError

CUSD = '0x' + '77' * 20
REFEREE_ADDR = '0x' + '11' * 20
REFERRER_ADDR = '0x' + '22' * 20
WAD = 10 ** 18

ON = dict(FEE_REFERRAL_ENABLED=True, CUSD_VAULT_ADDRESS=CUSD, FEE_REFERRAL_SHARE_BPS=5_000,
          FEE_REFERRAL_DAYS=365, FEE_REFERRAL_LAUNCH_AT='2024-01-01T00:00:00Z')


def _word(value) -> str:
    return format(value, 'x').rjust(64, '0') if isinstance(value, int) else value[2:].lower().rjust(64, '0')


def _arm(referrer=REFERRER_ADDR, bps=5_000, to=CUSD):
    return {'to': to, 'value': '0', 'data': '0x' + SEL_ARM_REFERRAL + _word(referrer) + _word(bps)}


MINT = {'to': CUSD, 'value': '0', 'data': '0x' + SEL_CUSD_MINT + _word(10 ** 20) + _word(0) + _word(REFEREE_ADDR)}


@override_settings(**ON)
class FeeReferralFixture(TestCase):
    _n = 0

    def make_user(self, address, verified=True):
        from security.models import IdentityVerification
        from users.models import Account, User

        FeeReferralFixture._n += 1
        n = FeeReferralFixture._n
        user = User.objects.create_user(username=f'feeref-{n}', password='x', firebase_uid=f'feeref-{n}')
        Account.objects.update_or_create(
            user=user, account_type='personal', account_index=0,
            defaults={'bsc_address': address},
        )
        if verified:
            IdentityVerification.objects.create(
                user=user, status='verified', verified_date_of_birth=date(1990, 1, 1),
                verified_first_name='Ana', verified_last_name='Perez', verified_nationality='VEN',
                verified_address='x', verified_city='x', verified_state='x', verified_country='VEN',
                document_type='national_id', document_number=f'V-FEEREF-{n}', document_issuing_country='VEN')
        return user

    def setUp(self):
        from achievements.models import UserReferral

        self.referee = self.make_user(REFEREE_ADDR)
        self.referrer = self.make_user(REFERRER_ADDR)
        self.referral = UserReferral.objects.create(
            referred_user=self.referee, referrer_user=self.referrer, referrer_identifier='amigo')
        patcher = mock.patch('cusd_plus.fee_referral._is_banned', return_value=False)
        self.banned = patcher.start()
        self.addCleanup(patcher.stop)
        self.ready_patcher = mock.patch('cusd_plus.fee_referral.onchain_ready', return_value=True)
        self.ready = self.ready_patcher.start()
        self.addCleanup(mock.patch.stopall)


class EligibilityTests(FeeReferralFixture):
    def test_both_verified_gets_half_to_referrer_personal_address(self):
        arm = fee_referral.eligible_arm(self.referee, REFEREE_ADDR)
        self.assertEqual(arm.referrer_address, REFERRER_ADDR)
        self.assertEqual(arm.share_bps, 5_000)
        self.assertEqual(fee_referral.arm_call(arm), _arm())

    def test_off_until_the_contract_upgrade(self):
        with override_settings(FEE_REFERRAL_ENABLED=False):
            self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_unverified_referee_or_referrer_gets_nothing(self):
        from security.models import IdentityVerification

        IdentityVerification.all_documents.filter(user=self.referee).update(status='expired')
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))
        IdentityVerification.all_documents.filter(user=self.referee).update(status='verified')
        IdentityVerification.all_documents.filter(user=self.referrer).update(status='pending')
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_window_closes_after_the_configured_days(self):
        from achievements.models import UserReferral

        UserReferral.objects.filter(pk=self.referral.pk).update(
            created_at=timezone.now() - timedelta(days=366))
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))
        with override_settings(FEE_REFERRAL_DAYS=400):
            self.assertIsNotNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_banned_side_gets_nothing(self):
        self.banned.return_value = True
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_no_live_referral_gets_nothing(self):
        self.referral.delete()
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_only_from_the_referees_personal_address(self):
        self.assertIsNone(fee_referral.eligible_arm(self.referee, '0x' + '99' * 20))

    def test_same_person_behind_both_accounts_gets_nothing(self):
        from security.models import IdentityVerification

        # A shared KYC'd document ties the two accounts to one person.
        doc = IdentityVerification.all_objects.filter(user=self.referrer).first()
        IdentityVerification.all_objects.filter(user=self.referee).update(
            document_number=doc.document_number, document_number_normalized=doc.document_number_normalized)
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_duplicated_face_either_direction_gets_nothing(self):
        from security.models import IdentityVerification

        IdentityVerification.all_objects.filter(user=self.referrer).update(
            risk_factors={'duplicated_face': {'matched_user_ids': [self.referee.pk]}})
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))
        IdentityVerification.all_objects.filter(user=self.referrer).update(risk_factors={})
        self.assertIsNotNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))
        IdentityVerification.all_objects.filter(user=self.referee).update(
            risk_factors={'duplicated_face': {'matched_user_ids': [str(self.referrer.pk)]}})
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_share_setting_is_clamped_to_half(self):
        with override_settings(FEE_REFERRAL_SHARE_BPS=9_000):
            self.assertEqual(fee_referral.eligible_arm(self.referee, REFEREE_ADDR).share_bps, 5_000)


class SponsorPolicyTests(FeeReferralFixture):
    def test_no_arm_passes_through(self):
        self.assertEqual(fee_referral.strip_arm([MINT], self.referee, REFEREE_ADDR), [MINT])

    def test_exact_arm_first_is_stripped(self):
        self.assertEqual(fee_referral.strip_arm([_arm(), MINT], self.referee, REFEREE_ADDR), [MINT])

    def test_arm_anywhere_else_or_twice_is_refused(self):
        for calls in ([MINT, _arm()], [_arm(), _arm(), MINT]):
            with self.assertRaises(PolicyError) as ctx:
                fee_referral.strip_arm(calls, self.referee, REFEREE_ADDR)
            self.assertEqual(ctx.exception.code, 'referral_arm_not_first')

    def test_other_referrer_share_or_target_is_refused(self):
        for bad in (_arm(referrer='0x' + '33' * 20), _arm(bps=4_000), _arm(to='0x' + '44' * 20)):
            with self.assertRaises(PolicyError) as ctx:
                fee_referral.strip_arm([bad, MINT], self.referee, REFEREE_ADDR)
            self.assertEqual(ctx.exception.code, 'referral_not_allowed')

    def test_arm_for_an_ineligible_member_is_refused(self):
        with override_settings(FEE_REFERRAL_ENABLED=False):
            with self.assertRaises(PolicyError):
                fee_referral.strip_arm([_arm(), MINT], self.referee, REFEREE_ADDR)

    def test_stored_arm_is_shape_checked_not_re_decided(self):
        # Prepare stored it; eligibility lapsing before submit must not fail the send.
        self.referral.delete()
        self.assertEqual(fee_referral.strip_stored_arm([_arm(), MINT]), [MINT])
        with self.assertRaises(PolicyError):
            fee_referral.strip_stored_arm([_arm(bps=6_000), MINT])
        with self.assertRaises(PolicyError):
            fee_referral.strip_stored_arm([MINT, _arm()])

    def test_never_on_a_delegating_batch(self):
        with self.assertRaises(PolicyError) as ctx:
            fee_referral.strip_arm([_arm(), MINT], self.referee, REFEREE_ADDR, delegating=True)
        self.assertEqual(ctx.exception.code, 'referral_not_delegated')

    def test_only_on_fee_bearing_batches(self):
        transfer = {'to': CUSD, 'value': '0', 'data': '0xa9059cbb' + '00' * 64}
        with self.assertRaises(PolicyError) as ctx:
            fee_referral.strip_arm([_arm(), transfer], self.referee, REFEREE_ADDR)
        self.assertEqual(ctx.exception.code, 'referral_not_needed')

    def test_refused_while_the_vault_is_not_ready(self):
        self.ready.return_value = False
        with self.assertRaises(PolicyError) as ctx:
            fee_referral.strip_arm([_arm(), MINT], self.referee, REFEREE_ADDR)
        self.assertEqual(ctx.exception.code, 'referral_not_allowed')

    def test_server_built_batches_skip_undelegated_or_unready(self):
        with mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=False):
            self.assertEqual(fee_referral.arm_calls_for(self.referee, REFEREE_ADDR), [])
        with mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=True):
            self.assertEqual(fee_referral.arm_calls_for(self.referee, REFEREE_ADDR), [_arm()])
            self.ready.return_value = False
            self.assertEqual(fee_referral.arm_calls_for(self.referee, REFEREE_ADDR), [])

    def test_readiness_reads_the_vault_and_fails_closed(self):
        self.ready_patcher.stop()
        from django.core.cache import cache

        cache.delete('fee_referral:onchain_ready')
        delegate = '0x' + 'dd' * 20
        answers = {'batchDelegate()': int(delegate, 16), 'referralShareCapBps()': 5000, 'paused()': 0}

        def fake_call(selector, value=None, words=1):
            from cusd_plus.cusd_vault import _sel
            for sig, val in answers.items():
                if _sel(sig) == selector:
                    return (val,)
            raise AssertionError(selector)

        with mock.patch('cusd_plus.cusd_vault._uint_call', side_effect=fake_call), \
                mock.patch('cusd_plus.sponsor_7702.delegate_address', return_value=delegate):
            self.assertTrue(fee_referral.onchain_ready())
            cache.delete('fee_referral:onchain_ready')
            answers['paused()'] = 1
            self.assertFalse(fee_referral.onchain_ready())
        cache.delete('fee_referral:onchain_ready')
        with mock.patch('cusd_plus.cusd_vault._uint_call', side_effect=RuntimeError('rpc')):
            self.assertFalse(fee_referral.onchain_ready())
        cache.delete('fee_referral:onchain_ready')

    def test_stored_arm_survives_a_lowered_share_setting(self):
        # A recorded replay / prepared send keeps the arm it was decided with;
        # only the contract's fixed 50% ceiling bounds it.
        with override_settings(FEE_REFERRAL_SHARE_BPS=2_500, FEE_REFERRAL_ENABLED=False):
            self.assertEqual(fee_referral.strip_stored_arm([_arm(bps=5_000), MINT]), [MINT])
            with self.assertRaises(PolicyError):
                fee_referral.strip_stored_arm([_arm(bps=5_001), MINT])

    def test_replay_matching_ignores_only_a_leading_arm(self):
        import json
        from types import SimpleNamespace

        from cusd_plus.sponsor_7702 import batch_matches_calls

        recorded = SimpleNamespace(kind='mint_cusd', calls_json=json.dumps([_arm(), MINT]))
        self.assertTrue(batch_matches_calls(recorded, 'mint_cusd', [MINT]))
        self.assertTrue(batch_matches_calls(recorded, 'mint_cusd', [_arm(), MINT]))
        other = dict(MINT, data=MINT['data'][:-1] + '2')
        self.assertFalse(batch_matches_calls(recorded, 'mint_cusd', [_arm(), other]))
        self.assertFalse(batch_matches_calls(recorded, 'redeem', [MINT]))

    def test_fee_bearing_detection(self):
        self.assertTrue(fee_referral.has_fee_bearing_call([MINT]))
        self.assertFalse(fee_referral.has_fee_bearing_call([{'to': CUSD, 'value': '0', 'data': '0xa9059cbb'}]))


def _paid_log(fee=9 * 10 ** 17, share=45 * 10 ** 16, bps=5_000, index=3, address=CUSD):
    return {
        'address': address,
        'topics': [
            '0x' + keccak(text='ReferralPaid(address,address,uint256,uint256,uint256)').hex(),
            '0x' + _word(REFEREE_ADDR), '0x' + _word(REFERRER_ADDR),
        ],
        'data': '0x' + _word(fee) + _word(share) + _word(bps),
        'logIndex': hex(index), 'blockNumber': hex(100),
    }


class RecordingTests(FeeReferralFixture):
    def test_records_once_and_pushes_once_with_month_total(self):
        from conversion.models import FeeReferralPayout

        with mock.patch('notifications.utils.create_notification') as push:
            rows = fee_referral.record_referral_payouts('0xABC', [_paid_log()], {})
            again = fee_referral.record_referral_payouts('0xabc', [_paid_log()], {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(again, [])
        row = FeeReferralPayout.objects.get()
        self.assertEqual(row.referrer_user, self.referrer)
        self.assertEqual(row.referee_user, self.referee)
        self.assertEqual(int(row.share_wei), 45 * 10 ** 16)
        self.assertIsNotNone(row.notified_at)
        push.assert_called_once()
        kwargs = push.call_args.kwargs
        self.assertEqual(kwargs['user'], self.referrer)
        self.assertIn('+US$0.45', kwargs['message'])
        self.assertIn('Este mes: US$0.45', kwargs['message'])
        self.assertNotIn(self.referee.username, kwargs['message'])

    def test_month_total_follows_payout_time_not_scan_time(self):
        from conversion.models import FeeReferralPayout

        last_month = timezone.localtime().replace(day=1) - timedelta(days=1)
        with mock.patch('notifications.utils.create_notification'):
            fee_referral.record_referral_payouts('0x01', [_paid_log(index=1)], {100: last_month})
            fee_referral.record_referral_payouts('0x02', [_paid_log(index=2)], {})
        self.assertEqual(FeeReferralPayout.objects.count(), 2)
        self.assertEqual(fee_referral.month_total(self.referrer), Decimal('0.45'))

    def test_one_wallet_row_per_day_sums_that_days_commissions(self):
        from users.models_unified import UnifiedTransactionTable

        with mock.patch('notifications.utils.create_notification') as push:
            fee_referral.record_referral_payouts('0xAA', [_paid_log(index=4)], {})
            fee_referral.record_referral_payouts('0xaa', [_paid_log(index=4)], {})  # replay
            fee_referral.record_referral_payouts('0xab', [_paid_log(index=5, share=9 * 10 ** 16)], {})
        rows = UnifiedTransactionTable.objects.filter(transaction_type='commission')
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(Decimal(str(row.amount)), Decimal('0.54'))
        self.assertEqual(row.description, 'Comisiones por invitar · 2 pagos')
        self.assertEqual(row.transaction_hash, '')
        self.assertEqual(row.counterparty_user, self.referrer)
        self.assertEqual(row.token_type, 'CUSD_BSC')
        self.assertEqual(row.to_address.lower(), REFERRER_ADDR)
        self.assertEqual(row.get_direction_for_address(REFERRER_ADDR), 'received')
        self.assertTrue(row.internal_id.startswith(f'feeref:{self.referrer.pk}:'))
        self.assertLessEqual(len(row.internal_id), 32)
        self.assertNotIn(self.referee.username, f'{row.description} {row.sender_display_name}')
        self.assertEqual(push.call_args.kwargs['action_url'], 'confio://achievements')

    def test_a_failed_history_row_rolls_back_and_a_rescan_repairs_it(self):
        from conversion.models import FeeReferralPayout
        from users.models_unified import UnifiedTransactionTable

        with mock.patch('cusd_plus.fee_referral.record_history', side_effect=RuntimeError('db')), \
                mock.patch('notifications.utils.create_notification') as push:
            with self.assertRaises(RuntimeError):
                fee_referral.record_referral_payouts('0xbb', [_paid_log()], {})
        # Nothing half-written: the scanner retries this range.
        self.assertEqual(FeeReferralPayout.objects.count(), 0)
        push.assert_not_called()
        with mock.patch('notifications.utils.create_notification'):
            fee_referral.record_referral_payouts('0xbb', [_paid_log()], {})
        self.assertEqual(UnifiedTransactionTable.objects.filter(transaction_type='commission').count(), 1)

    def test_a_ledger_row_without_its_card_is_repaired_on_replay(self):
        from users.models_unified import UnifiedTransactionTable

        with mock.patch('notifications.utils.create_notification') as push:
            fee_referral.record_referral_payouts('0xdd', [_paid_log()], {})
            UnifiedTransactionTable.objects.filter(transaction_type='commission').delete()
            fee_referral.record_referral_payouts('0xdd', [_paid_log()], {})
        self.assertEqual(UnifiedTransactionTable.objects.filter(transaction_type='commission').count(), 1)
        push.assert_called_once()  # the push is never repeated

    def test_another_day_is_another_row(self):
        from datetime import datetime, timezone as dt_tz

        from users.models_unified import UnifiedTransactionTable

        with mock.patch('notifications.utils.create_notification'):
            fee_referral.record_referral_payouts('0x01', [_paid_log(index=1)], {100: datetime(2026, 11, 1, 12, tzinfo=dt_tz.utc)})
            fee_referral.record_referral_payouts('0x02', [_paid_log(index=2)], {100: datetime(2026, 11, 3, 12, tzinfo=dt_tz.utc)})
        self.assertEqual(UnifiedTransactionTable.objects.filter(transaction_type='commission').count(), 2)

    def test_counts_in_tu_mes_as_its_own_income_line(self):
        from users import cashflow

        self.assertIn('commission', cashflow.INCOME_KINDS)

    def test_ignores_other_contracts_and_malformed_logs(self):
        logs = [_paid_log(address='0x' + '55' * 20), _paid_log(share=10 ** 18, fee=1)]
        self.assertEqual(fee_referral.referral_paid_events(logs), [])

    def test_a_failed_push_still_records(self):
        from conversion.models import FeeReferralPayout

        with mock.patch('notifications.utils.create_notification', side_effect=RuntimeError('fcm')):
            fee_referral.record_referral_payouts('0xdef', [_paid_log()], {})
        self.assertEqual(FeeReferralPayout.objects.count(), 1)


class FormatTests(TestCase):
    def test_sub_cent_is_never_shown_as_zero(self):
        self.assertEqual(fee_referral.format_usd(Decimal('0.45')), 'US$0.45')
        self.assertEqual(fee_referral.format_usd(Decimal('1234.5')), 'US$1,234.50')
        self.assertEqual(fee_referral.format_usd(Decimal('0.0046')), 'US$0.005')
        self.assertEqual(fee_referral.format_usd(Decimal('0.0002')), 'menos de US$0.001')


class FriendStatusTests(FeeReferralFixture):
    def status(self):
        return fee_referral.friend_statuses(self.referrer)[0]['status']

    def test_earning_when_both_verified(self):
        self.assertEqual(self.status(), 'earning')

    def test_waiting_on_the_friend_or_on_you(self):
        from security.models import IdentityVerification

        IdentityVerification.all_documents.filter(user=self.referee).update(status='pending')
        self.assertEqual(self.status(), 'needs_friend_verification')
        IdentityVerification.all_documents.filter(user=self.referrer).update(status='pending')
        self.assertEqual(self.status(), 'needs_your_verification')

    def test_ended_after_the_window(self):
        from achievements.models import UserReferral

        UserReferral.objects.filter(pk=self.referral.pk).update(created_at=timezone.now() - timedelta(days=400))
        self.assertEqual(self.status(), 'ended')

    def test_no_per_friend_amount_and_public_handle_only(self):
        friend = fee_referral.friend_statuses(self.referrer)[0]
        self.assertNotIn('earned', friend)
        self.assertEqual(friend['display_name'], f'@{self.referee.username}')

    def test_same_person_and_banned_friends_are_unavailable(self):
        from security.models import IdentityVerification

        IdentityVerification.all_objects.filter(user=self.referee).update(
            risk_factors={'duplicated_face': {'matched_user_ids': [self.referrer.pk]}})
        self.assertEqual(self.status(), 'unavailable')

    def test_bounded_queries_for_many_friends(self):
        from achievements.models import UserReferral

        for i in range(15):
            friend = self.make_user('0x' + format(0x500 + i, 'x').rjust(40, '0'))
            UserReferral.objects.create(referred_user=friend, referrer_user=self.referrer, referrer_identifier='amigo')
        with self.assertNumQueries(7):  # fixed, whatever the friend count
            statuses = fee_referral.friend_statuses(self.referrer)
        self.assertEqual(len(statuses), 16)


class SummaryQueryTests(FeeReferralFixture):
    QUERY = '{ feeReferralSummary { enabled shareBps feeBps windowDays viewerVerified monthTotalUsd totalEarnedUsd friends { displayName status endsAt } } }'

    def run_query(self, user):
        from types import SimpleNamespace

        from config.schema import schema

        return schema.execute(self.QUERY, context_value=SimpleNamespace(user=user, META={}))

    def test_summary_for_the_referrer(self):
        result = self.run_query(self.referrer)
        self.assertIsNone(result.errors)
        data = result.data['feeReferralSummary']
        self.assertTrue(data['enabled'])
        self.assertEqual((data['shareBps'], data['feeBps'], data['windowDays']), (5000, 90, 365))
        self.assertEqual(data['friends'][0]['status'], 'earning')

    def test_reports_disabled_so_the_app_keeps_old_copy(self):
        with override_settings(FEE_REFERRAL_ENABLED=False):
            self.assertFalse(self.run_query(self.referrer).data['feeReferralSummary']['enabled'])


class LaunchTests(FeeReferralFixture):
    def test_old_referrals_get_a_full_year_from_launch(self):
        from achievements.models import UserReferral

        UserReferral.objects.filter(pk=self.referral.pk).update(created_at=timezone.now() - timedelta(days=500))
        self.referral.refresh_from_db()
        self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))
        launch = timezone.now() - timedelta(days=10)
        with override_settings(FEE_REFERRAL_LAUNCH_AT=launch.isoformat()):
            self.assertIsNotNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))
            self.assertEqual(fee_referral.window_ends_at(self.referral), launch + timedelta(days=365))

    def test_new_referrals_count_from_signup(self):
        launch = timezone.now() - timedelta(days=400)
        with override_settings(FEE_REFERRAL_LAUNCH_AT=launch.isoformat()):
            self.assertEqual(fee_referral.window_start(self.referral), self.referral.created_at)

    def test_confio_bonus_stops_at_launch_only_when_live(self):
        past = (timezone.now() - timedelta(minutes=1)).isoformat()
        future = (timezone.now() + timedelta(days=1)).isoformat()
        with override_settings(FEE_REFERRAL_LAUNCH_AT=None):
            self.assertFalse(fee_referral.confio_bonus_ended())  # no launch date: program off
        with override_settings(FEE_REFERRAL_LAUNCH_AT=future):
            self.assertFalse(fee_referral.confio_bonus_ended())
        with override_settings(FEE_REFERRAL_LAUNCH_AT=past):
            self.assertTrue(fee_referral.confio_bonus_ended())
        with override_settings(FEE_REFERRAL_LAUNCH_AT=past, FEE_REFERRAL_ENABLED=False):
            self.assertFalse(fee_referral.confio_bonus_ended())

    def test_no_new_bonus_after_launch(self):
        from achievements.models import ReferralRewardEvent
        from achievements.services.referral_rewards import EventContext, sync_referral_reward_for_event

        before = ReferralRewardEvent.objects.count()
        with override_settings(FEE_REFERRAL_LAUNCH_AT=(timezone.now() - timedelta(minutes=1)).isoformat()):
            result = sync_referral_reward_for_event(
                self.referee, EventContext(event='top_up', amount=Decimal('50'), metadata={}))
        self.assertIsNone(result)
        self.assertEqual(ReferralRewardEvent.objects.count(), before)

    def test_friend_joined_after_launch_promises_commission_not_bonus(self):
        from achievements.services.referral_rewards import _notify_referral_joined

        with override_settings(FEE_REFERRAL_LAUNCH_AT=(timezone.now() - timedelta(minutes=1)).isoformat()), \
                mock.patch('achievements.services.referral_rewards.create_notification') as push:
            _notify_referral_joined(self.referral)
        texts = ' '.join(c.kwargs['message'] for c in push.call_args_list)
        self.assertEqual(push.call_count, 2)
        self.assertIn('50%', texts)
        self.assertNotIn('US$5', texts)
        self.assertIn('no le mostramos tus operaciones', texts)  # the friend's privacy notice


class ReminderTests(FeeReferralFixture):
    def setUp(self):
        super().setUp()
        from security.models import IdentityVerification

        IdentityVerification.all_documents.filter(user=self.referee).update(status='pending')

    def test_reminds_once_a_week(self):
        with mock.patch('notifications.utils.create_notification') as push:
            fee_referral.remind_friend(self.referrer, self.referral.pk)
            with self.assertRaises(fee_referral.ReminderError) as ctx:
                fee_referral.remind_friend(self.referrer, self.referral.pk)
        self.assertEqual(ctx.exception.code, 'too_soon')
        push.assert_called_once()
        self.assertEqual(push.call_args.kwargs['user'], self.referee)
        self.assertIn(f'@{self.referrer.username}', push.call_args.kwargs['message'])
        self.assertFalse(fee_referral.friend_statuses(self.referrer)[0]['can_remind'])

    def test_only_the_referrer_and_only_unverified_friends(self):
        from security.models import IdentityVerification

        with self.assertRaises(fee_referral.ReminderError) as ctx:
            fee_referral.remind_friend(self.referee, self.referral.pk)
        self.assertEqual(ctx.exception.code, 'not_found')
        IdentityVerification.all_documents.filter(user=self.referee).update(status='verified')
        with self.assertRaises(fee_referral.ReminderError) as ctx:
            fee_referral.remind_friend(self.referrer, self.referral.pk)
        self.assertEqual(ctx.exception.code, 'already_verified')


class PayoutsPageTests(FeeReferralFixture):
    def test_own_payouts_newest_first_without_friend_or_hash(self):
        with mock.patch('notifications.utils.create_notification'):
            for i in range(3):
                fee_referral.record_referral_payouts(f'0x0{i}', [_paid_log(index=i)], {})
        page = fee_referral.payouts_page(self.referrer, limit=2, offset=0)
        self.assertEqual(len(page), 2)
        self.assertEqual(set(page[0]), {'id', 'amount', 'paid_at'})
        self.assertEqual(len(fee_referral.payouts_page(self.referrer, limit=2, offset=2)), 1)
        self.assertEqual(fee_referral.payouts_page(self.referee, limit=10, offset=0), [])


class ConfigurationTests(FeeReferralFixture):
    def test_enabled_without_a_valid_launch_stays_off(self):
        for bad in (None, '', 'not-a-date'):
            with override_settings(FEE_REFERRAL_LAUNCH_AT=bad):
                self.assertFalse(fee_referral.enabled())
                self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_string_false_is_off(self):
        with override_settings(FEE_REFERRAL_ENABLED='False'):
            self.assertFalse(fee_referral.enabled())
        with override_settings(FEE_REFERRAL_ENABLED='true'):
            self.assertTrue(fee_referral.enabled())

    def test_history_amount_is_plain_decimal(self):
        from users.models_unified import UnifiedTransactionTable

        with mock.patch('notifications.utils.create_notification'):
            fee_referral.record_referral_payouts('0xee', [_paid_log(fee=90 * 10 ** 18 * 2, share=90 * 10 ** 18)], {})
        row = UnifiedTransactionTable.objects.get(transaction_type='commission')
        self.assertEqual(row.amount, '90')

    def test_day_follows_the_referrers_time_zone(self):
        from datetime import datetime, timezone as dt_tz

        from users.models import User

        User.objects.filter(pk=self.referrer.pk).update(country='VE')  # UTC-4
        self.referrer.refresh_from_db()
        with mock.patch('notifications.utils.create_notification'):
            rows = fee_referral.record_referral_payouts(
                '0xff', [_paid_log()], {100: datetime(2026, 11, 1, 1, tzinfo=dt_tz.utc)})
        # 01:00 UTC on Nov 1 is still Oct 31 in Caracas.
        self.assertEqual(str(fee_referral.payout_day(rows[0])), '2026-10-31')

    def test_reminder_refused_outside_needs_verification(self):
        from achievements.models import UserReferral
        from security.models import IdentityVerification

        IdentityVerification.all_documents.filter(user=self.referee).update(status='pending')
        UserReferral.objects.filter(pk=self.referral.pk).update(created_at=timezone.now() - timedelta(days=800))
        with override_settings(FEE_REFERRAL_LAUNCH_AT=None, FEE_REFERRAL_ENABLED=False), \
                self.assertRaises(fee_referral.ReminderError) as ctx:
            fee_referral.remind_friend(self.referrer, self.referral.pk)
        self.assertEqual(ctx.exception.code, 'not_allowed')

    def test_no_pending_bonus_after_launch(self):
        from users.schema import _referral_reward_totals

        type(self.referral).objects.filter(pk=self.referral.pk).update(
            reward_referee_confio=Decimal('20'), referee_reward_status='pending')
        with override_settings(FEE_REFERRAL_LAUNCH_AT=(timezone.now() - timedelta(minutes=1)).isoformat()):
            pending, _earned = _referral_reward_totals(self.referee)
        self.assertEqual(pending, Decimal('0'))
        with override_settings(FEE_REFERRAL_LAUNCH_AT=None):
            pending, _earned = _referral_reward_totals(self.referee)
        self.assertEqual(pending, Decimal('20'))


class BadgeCountTests(FeeReferralFixture):
    def test_only_verified_friends_with_a_deposit_raise_the_badge(self):
        from achievements.models import UserReferral
        from security.models import IdentityVerification
        from users.status_badges import badges_for

        UserReferral.objects.filter(pk=self.referral.pk).update(status='converted')
        self.assertEqual(self.referrer.referral_count, 1)
        self.assertEqual(badges_for([self.referrer.pk])[self.referrer.pk], ('early_supporter', True))
        # A dust deposit from an unverified account buys no badge.
        IdentityVerification.all_documents.filter(user=self.referee).update(status='pending')
        self.assertEqual(self.referrer.referral_count, 0)
        self.assertEqual(badges_for([self.referrer.pk])[self.referrer.pk], ('member', False))
        # Badges earned under the old bonus are kept.
        UserReferral.objects.filter(pk=self.referral.pk).update(referrer_reward_status='eligible')
        self.assertEqual(self.referrer.referral_count, 1)


class FinalAuditTests(FeeReferralFixture):
    def test_scheduled_launch_pays_nothing_before_the_instant(self):
        future = (timezone.now() + timedelta(days=1)).isoformat()
        with override_settings(FEE_REFERRAL_LAUNCH_AT=future):
            self.assertFalse(fee_referral.enabled())
            self.assertFalse(fee_referral.confio_bonus_ended())
            self.assertIsNone(fee_referral.eligible_arm(self.referee, REFEREE_ADDR))

    def test_naive_launch_timestamp_is_utc(self):
        with override_settings(FEE_REFERRAL_LAUNCH_AT='2024-01-01T00:00:00'):
            launched = fee_referral.launch_at()
        self.assertIsNotNone(launched.tzinfo)
        self.assertEqual(launched.utcoffset(), timedelta(0))

    def test_settings_are_loaded_from_config(self):
        from django.conf import settings as dj

        for name in ('FEE_REFERRAL_ENABLED', 'FEE_REFERRAL_LAUNCH_AT', 'FEE_REFERRAL_SHARE_BPS', 'FEE_REFERRAL_DAYS'):
            self.assertTrue(hasattr(dj, name), name)

    def test_all_invitations_counted_and_the_oldest_can_be_reminded(self):
        from achievements.models import UserReferral
        from security.models import IdentityVerification

        IdentityVerification.all_documents.filter(user=self.referee).update(status='pending')
        UserReferral.objects.filter(pk=self.referral.pk).update(created_at=timezone.now() - timedelta(days=30))
        with mock.patch.object(fee_referral, 'FRIENDS_LIST_MAX', 3):
            for i in range(4):
                friend = self.make_user('0x' + format(0x900 + i, 'x').rjust(40, '0'), verified=False)
                UserReferral.objects.create(referred_user=friend, referrer_user=self.referrer,
                                            referrer_identifier='amigo')
            statuses = fee_referral.friend_statuses(self.referrer)
            self.assertEqual(len(statuses), 5)
            self.assertEqual(statuses[-1]['referral_id'], self.referral.pk)  # oldest, beyond the cap
            with mock.patch('notifications.utils.create_notification') as push:
                fee_referral.remind_friend(self.referrer, self.referral.pk)
            push.assert_called_once()
