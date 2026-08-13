from decimal import Decimal
from unittest.mock import patch

from algosdk import account
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from achievements.models import ReferralRewardEvent, UserReferral
from achievements.referral_security import (
    DUPLICATE_REFEREE_REWARD_ERROR,
    get_referrer_claim_verification_error,
)
from achievements.signals import sync_pending_reward_events
from achievements.services.referral_rewards import (
    EventContext,
    sync_referral_reward_for_event,
)
from blockchain.rewards_service import RewardSyncResult
from notifications.models import Notification, NotificationType as NotificationTypeChoices
from security.models import IdentityVerification
from users.models import Account


@override_settings(BSC_REWARD_ENABLED=False)
class ReferralRewardServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.referrer = user_model.objects.create_user(
            username="referrer",
            email="referrer@example.com",
            password="password",
            firebase_uid="referrer-uid",
        )
        self.referred = user_model.objects.create_user(
            username="referred",
            email="referred@example.com",
            password="password",
            firebase_uid="referred-uid",
        )

        referrer_sk, referrer_addr = account.generate_account()
        referred_sk, referred_addr = account.generate_account()

        # store private keys for completeness (not used)
        self.referrer_private_key = referrer_sk
        self.referred_private_key = referred_sk

        Account.objects.create(
            user=self.referrer,
            account_type="personal",
            account_index=0,
            algorand_address=referrer_addr,
        )
        Account.objects.create(
            user=self.referred,
            account_type="personal",
            account_index=0,
            algorand_address=referred_addr,
        )

        self.referral = UserReferral.objects.create(
            referred_user=self.referred,
            referrer_identifier="@referrer",
            referrer_user=self.referrer,
        )
        Notification.objects.all().delete()
        self.push_patch = patch('notifications.utils.send_push_notification', return_value={'success': True})
        self.push_patch.start()

    def tearDown(self):
        self.push_patch.stop()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_top_up_event_triggers_reward(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.convert_cusd_to_confio.return_value = Decimal("20")
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="TEST-TX",
            confirmed_round=123,
            referee_confio_micro=20_000_000,
            referrer_confio_micro=20_000_000,
            box_name="deadbeef",
        )

        with self.captureOnCommitCallbacks(execute=True):
            sync_referral_reward_for_event(
                self.referred,
                EventContext(event="top_up", amount=Decimal("25")),
            )

        self.referral.refresh_from_db()
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="top_up")
        self.assertEqual(self.referral.reward_status, "eligible")
        self.assertEqual(self.referral.reward_event, "top_up")
        self.assertEqual(self.referral.reward_tx_id, "TEST-TX")
        self.assertEqual(event.reward_status, "eligible")
        self.assertEqual(event.reward_tx_id, "TEST-TX")
        mock_instance.mark_eligibility.assert_called_once()
        call_kwargs = mock_instance.mark_eligibility.call_args.kwargs
        self.assertEqual(call_kwargs["reward_cusd_micro"], 5_000_000)
        self.assertEqual(call_kwargs["referee_confio_micro"], 20_000_000)
        self.assertEqual(call_kwargs["referrer_confio_micro"], 20_000_000)
        notif_count = Notification.objects.filter(notification_type=NotificationTypeChoices.REFERRAL_EVENT_TOP_UP).count()
        self.assertEqual(notif_count, 1)

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_conversion_below_threshold_does_not_trigger(self, mock_service):
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="conversion_usdc_to_cusd", amount=Decimal("10")),
        )
        self.assertFalse(ReferralRewardEvent.objects.filter(user=self.referred, trigger="conversion_usdc_to_cusd").exists())
        mock_service.assert_not_called()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_event_logged_when_no_referral(self, mock_service):
        # Remove referral and ensure event stays pending
        self.referral.delete()

        result = sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("30")),
        )
        self.assertIsNone(result)
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="top_up")
        self.assertIsNone(event.referral)
        self.assertEqual(event.reward_status, "pending")
        mock_service.assert_not_called()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_pending_event_processed_after_referral_created(self, mock_service):
        # remove referral and log event
        self.referral.delete()
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("25")),
        )
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="conversion_usdc_to_cusd", amount=Decimal("25")),
        )
        sync_referral_reward_for_event(
            self.referrer,
            EventContext(event="top_up", amount=Decimal("25")),
        )
        self.assertFalse(mock_service.called)

        # Configure service for when referral is recreated
        mock_instance = mock_service.return_value
        mock_instance.convert_cusd_to_confio.return_value = Decimal("20")
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="PENDING-TO-ELIGIBLE",
            confirmed_round=456,
            referee_confio_micro=20_000_000,
            referrer_confio_micro=20_000_000,
            box_name="beefdead",
        )

        # Re-create referral -> signal should process pending event
        new_referral = UserReferral.objects.create(
            referred_user=self.referred,
            referrer_identifier="@referrer",
            referrer_user=self.referrer,
            status='active',
        )
        self.assertEqual(
            ReferralRewardEvent.objects.filter(user=self.referred, trigger="top_up").count(),
            1
        )
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="top_up")
        event.refresh_from_db()
        self.assertEqual(event.reward_status, "eligible")
        self.assertEqual(event.referral_id, new_referral.id)
        conversion = ReferralRewardEvent.objects.get(
            user=self.referred,
            trigger="conversion_usdc_to_cusd",
        )
        self.assertEqual(conversion.referral_id, new_referral.id)
        self.assertEqual(conversion.reward_status, "skipped")
        unrelated_referrer_event = ReferralRewardEvent.objects.get(
            user=self.referrer,
            trigger="top_up",
        )
        self.assertIsNone(unrelated_referrer_event.referral_id)
        self.assertEqual(unrelated_referrer_event.reward_status, "pending")
        new_referral.refresh_from_db()
        self.assertEqual(new_referral.reward_status, "eligible")
        referrer_event = ReferralRewardEvent.objects.get(
            user=self.referrer,
            trigger="referral_pending",
            referral=new_referral,
        )
        self.assertEqual(referrer_event.reward_status, "eligible")
        self.assertFalse(
            ReferralRewardEvent.objects.filter(
                user=self.referred,
                trigger="referral_pending",
                referral=new_referral,
            ).exists()
        )
        mock_instance.mark_eligibility.assert_called_once()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_claimed_event_is_not_resynced(self, mock_service):
        ReferralRewardEvent.objects.create(
            referral=self.referral,
            user=self.referred,
            trigger="top_up",
            actor_role="referee",
            amount=Decimal("25"),
            occurred_at=timezone.now(),
            reward_status="claimed",
            referee_confio=Decimal("20"),
            referrer_confio=Decimal("20"),
        )

        result = sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("30")),
        )

        self.assertEqual(result, self.referral)
        mock_service.assert_not_called()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_event_before_winner_is_reconciled_after_orphan_processing(self, mock_service):
        self.referral.delete()
        ReferralRewardEvent.objects.create(
            user=self.referred,
            trigger="top_up",
            actor_role="referee",
            amount=Decimal("10"),
            occurred_at=timezone.now(),
            reward_status="pending",
        )
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="conversion_usdc_to_cusd", amount=Decimal("25")),
        )

        mock_instance = mock_service.return_value
        mock_instance.convert_cusd_to_confio.return_value = Decimal("20")
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="CONVERSION-WINS",
            confirmed_round=457,
            referee_confio_micro=20_000_000,
            referrer_confio_micro=20_000_000,
            box_name="conversionbox",
        )

        referral = UserReferral.objects.create(
            referred_user=self.referred,
            referrer_identifier="@referrer",
            referrer_user=self.referrer,
        )

        top_up = ReferralRewardEvent.objects.get(user=self.referred, trigger="top_up")
        conversion = ReferralRewardEvent.objects.get(
            user=self.referred,
            trigger="conversion_usdc_to_cusd",
        )
        referral.refresh_from_db()
        self.assertEqual(referral.reward_event, "conversion_usdc_to_cusd")
        self.assertEqual(top_up.reward_status, "skipped")
        self.assertEqual(conversion.reward_status, "eligible")
        mock_instance.mark_eligibility.assert_called_once()

    @override_settings(BSC_REWARD_ENABLED=True)
    @patch("presale.price_utils.get_confio_current_price", return_value=Decimal("0.25"))
    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_bsc_reward_is_recorded_in_database_without_chain_write(
        self,
        mock_service,
        _mock_price,
    ):
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("25")),
        )

        self.referral.refresh_from_db()
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="top_up")
        self.assertEqual(self.referral.reward_status, "eligible")
        self.assertEqual(self.referral.reward_tx_id, "bsc-db")
        self.assertEqual(self.referral.reward_referee_confio, Decimal("20"))
        self.assertEqual(event.reward_status, "eligible")
        self.assertEqual(event.reward_tx_id, "bsc-db")
        mock_service.assert_not_called()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_referrer_activity_does_not_qualify_the_friend(self, mock_service):
        result = sync_referral_reward_for_event(
            self.referrer,
            EventContext(event="top_up", amount=Decimal("60")),
        )

        event = ReferralRewardEvent.objects.get(user=self.referrer, trigger="top_up")
        self.assertIsNone(result)
        self.assertIsNone(event.referral_id)
        self.assertEqual(event.reward_status, "pending")
        mock_service.assert_not_called()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_service_failure_marks_event_failed(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.convert_cusd_to_confio.return_value = Decimal("20")
        mock_instance.mark_eligibility.side_effect = RuntimeError("algorand error")

        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("30")),
        )

        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="top_up")
        self.referral.refresh_from_db()
        self.assertEqual(event.reward_status, "failed")
        self.assertEqual(self.referral.reward_status, "pending")
        self.assertIn("algorand error", event.error)

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_duplicate_trigger_does_not_repeat_sync(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.convert_cusd_to_confio.return_value = Decimal("20")
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="UNIQUE-TX",
            confirmed_round=789,
            referee_confio_micro=20_000_000,
            referrer_confio_micro=20_000_000,
            box_name="1234abcd",
        )

        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("25")),
        )
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("40")),
        )

        mock_instance.mark_eligibility.assert_called_once()
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="top_up")
        self.assertEqual(event.amount, Decimal("25"))
        self.assertEqual(event.reward_tx_id, "UNIQUE-TX")

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_referrer_event_remains_eligible_after_referee_claim(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.convert_cusd_to_confio.return_value = Decimal("20")
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="REF-ELIGIBLE",
            confirmed_round=111,
            referee_confio_micro=20_000_000,
            referrer_confio_micro=20_000_000,
            box_name="feedface",
        )

        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="top_up", amount=Decimal("25")),
        )

        referrer_event = ReferralRewardEvent.objects.get(
            user=self.referrer,
            trigger="referral_pending",
            actor_role="referrer",
        )
        self.assertEqual(referrer_event.reward_status, "eligible")

        # Simulate referee claiming first while referrer is still pending
        self.referral.refresh_from_db()
        self.referral.reward_claimed_at = timezone.now()
        self.referral.referee_reward_status = "claimed"
        self.referral.save(update_fields=["reward_claimed_at", "referee_reward_status"])

        # Re-run placeholder sync to mimic signal behavior
        sync_pending_reward_events(UserReferral, self.referral, False)

        referrer_event.refresh_from_db()
        self.assertEqual(referrer_event.reward_status, "eligible")

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_duplicate_verified_identity_blocks_later_referee_eligibility(self, mock_service):
        duplicate_user = get_user_model().objects.create_user(
            username="duplicate-referred",
            email="duplicate@example.com",
            password="password",
            firebase_uid="duplicate-uid",
        )
        _, dup_addr = account.generate_account()
        Account.objects.create(
            user=duplicate_user,
            account_type="personal",
            account_index=0,
            algorand_address=dup_addr,
        )
        later_referral = UserReferral.objects.create(
            referred_user=duplicate_user,
            referrer_identifier="@referrer",
            referrer_user=self.referrer,
        )

        IdentityVerification.objects.create(
            user=self.referred,
            verified_first_name="Ana",
            verified_last_name="Perez",
            verified_date_of_birth=timezone.now().date(),
            verified_nationality="VEN",
            verified_address="Main street",
            verified_city="Bogota",
            verified_state="Cundinamarca",
            verified_country="COL",
            document_type="passport",
            document_number="P123456",
            document_issuing_country="VEN",
            status="verified",
            risk_factors={},
        )
        IdentityVerification.objects.create(
            user=duplicate_user,
            verified_first_name="Ana",
            verified_last_name="Perez",
            verified_date_of_birth=timezone.now().date(),
            verified_nationality="VEN",
            verified_address="Main street",
            verified_city="Bogota",
            verified_state="Cundinamarca",
            verified_country="COL",
            document_type="passport",
            document_number="P123456",
            document_issuing_country="VEN",
            status="verified",
            risk_factors={},
        )

        sync_referral_reward_for_event(
            duplicate_user,
            EventContext(event="top_up", amount=Decimal("25")),
        )

        later_referral.refresh_from_db()
        event = ReferralRewardEvent.objects.get(user=duplicate_user, trigger="top_up")
        self.assertEqual(later_referral.reward_status, "failed")
        self.assertEqual(later_referral.referee_reward_status, "failed")
        self.assertEqual(event.reward_status, "failed")
        self.assertEqual(event.error, DUPLICATE_REFEREE_REWARD_ERROR)
        mock_service.assert_not_called()

    def test_referrer_claim_waits_for_referee_verification(self):
        error = get_referrer_claim_verification_error(self.referral)
        self.assertIn("debe completar su verificación de identidad", error)

    def test_referrer_claim_mentions_pending_referee_verification(self):
        IdentityVerification.objects.create(
            user=self.referred,
            verified_first_name="Ana",
            verified_last_name="Perez",
            verified_date_of_birth=timezone.now().date(),
            verified_nationality="VEN",
            verified_address="Main street",
            verified_city="Bogota",
            verified_state="Cundinamarca",
            verified_country="COL",
            document_type="passport",
            document_number="PENDING123",
            document_issuing_country="VEN",
            status="pending",
            risk_factors={},
        )
        error = get_referrer_claim_verification_error(self.referral)
        self.assertIn("todavía debe terminar su verificación", error)

    def test_friend_joined_notifications_created(self):
        # A fresh referee, not self.referred: that user already has a live
        # referral from setUp, and uniq_live_referral_per_referee now enforces
        # one per person. Creating a second was the very race the constraint
        # exists to stop, so the fixture had to stop relying on it.
        new_referee = get_user_model().objects.create_user(
            username="referred_for_notifications",
            password="test-pass",
        )
        with self.captureOnCommitCallbacks(execute=True):
            new_referral = UserReferral.objects.create(
                referred_user=new_referee,
                referrer_identifier="@referrer2",
                referrer_user=self.referrer,
            )
        friend_joined = Notification.objects.filter(
            user=new_referral.referrer_user,
            notification_type=NotificationTypeChoices.REFERRAL_FRIEND_JOINED,
        ).count()
        reminder = Notification.objects.filter(
            user=new_referral.referred_user,
            notification_type=NotificationTypeChoices.REFERRAL_ACTION_REMINDER,
        ).count()
        self.assertEqual(friend_joined, 1)
        self.assertEqual(reminder, 1)

    def test_referral_notifications_are_discarded_when_transaction_rolls_back(self):
        new_referee = get_user_model().objects.create_user(
            username="rolled_back_referee",
            password="test-pass",
        )
        before_count = Notification.objects.count()

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    UserReferral.objects.create(
                        referred_user=new_referee,
                        referrer_identifier="@referrer",
                        referrer_user=self.referrer,
                    )
                    raise RuntimeError("force rollback")
            except RuntimeError:
                pass

        self.assertEqual(callbacks, [])
        self.assertEqual(Notification.objects.count(), before_count)
