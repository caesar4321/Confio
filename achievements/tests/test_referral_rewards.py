from decimal import Decimal
from unittest.mock import patch

from algosdk import account
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from achievements.models import ReferralRewardEvent, UserReferral
from achievements.services.referral_rewards import (
    EventContext,
    sync_referral_reward_for_event,
)
from blockchain.rewards_service import RewardSyncResult
from notifications.models import Notification, NotificationType as NotificationTypeChoices
from users.models import Account


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
    def test_send_event_triggers_reward(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="TEST-TX",
            confirmed_round=123,
            referee_confio_micro=8_000_000,
            referrer_confio_micro=2_000_000,
            box_name="deadbeef",
        )

        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="send", amount=Decimal("25")),
        )

        self.referral.refresh_from_db()
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="send")
        self.assertEqual(self.referral.reward_status, "eligible")
        self.assertEqual(self.referral.reward_event, "send")
        self.assertEqual(self.referral.reward_tx_id, "TEST-TX")
        self.assertEqual(event.reward_status, "eligible")
        self.assertEqual(event.reward_tx_id, "TEST-TX")
        mock_instance.mark_eligibility.assert_called_once()
        call_kwargs = mock_instance.mark_eligibility.call_args.kwargs
        self.assertEqual(call_kwargs["referee_confio_micro"], 8_000_000)
        self.assertEqual(call_kwargs["referrer_confio_micro"], 2_000_000)
        notif_count = Notification.objects.filter(notification_type=NotificationTypeChoices.REFERRAL_EVENT_SEND).count()
        self.assertEqual(notif_count, 2)

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
            EventContext(event="send", amount=Decimal("30")),
        )
        self.assertIsNone(result)
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="send")
        self.assertIsNone(event.referral)
        self.assertEqual(event.reward_status, "pending")
        mock_service.assert_not_called()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_pending_event_processed_after_referral_created(self, mock_service):
        # remove referral and log event
        self.referral.delete()
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="send", amount=Decimal("25")),
        )
        self.assertFalse(mock_service.called)

        # Configure service for when referral is recreated
        mock_instance = mock_service.return_value
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="PENDING-TO-ELIGIBLE",
            confirmed_round=456,
            referee_confio_micro=8_000_000,
            referrer_confio_micro=2_000_000,
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
            ReferralRewardEvent.objects.filter(user=self.referred, trigger="send").count(),
            1
        )
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="send")
        event.refresh_from_db()
        self.assertEqual(event.reward_status, "eligible")
        self.assertEqual(event.referral_id, new_referral.id)
        mock_instance.mark_eligibility.assert_called_once()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_claimed_event_is_not_resynced(self, mock_service):
        ReferralRewardEvent.objects.create(
            referral=self.referral,
            user=self.referred,
            trigger="send",
            actor_role="referee",
            amount=Decimal("25"),
            occurred_at=timezone.now(),
            reward_status="claimed",
            referee_confio=Decimal("80"),
            referrer_confio=Decimal("20"),
        )

        result = sync_referral_reward_for_event(
            self.referred,
            EventContext(event="send", amount=Decimal("30")),
        )

        self.assertEqual(result, self.referral)
        mock_service.assert_not_called()

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_referrer_event_uses_referrer_role(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="REFERRER-TX",
            confirmed_round=321,
            referee_confio_micro=12_000_000,
            referrer_confio_micro=3_000_000,
            box_name="cafebabe",
        )

        sync_referral_reward_for_event(
            self.referrer,
            EventContext(event="p2p_trade", amount=Decimal("60")),
        )

        event = ReferralRewardEvent.objects.get(user=self.referrer, trigger="p2p_trade")
        self.assertEqual(event.actor_role, "referrer")
        self.assertEqual(event.reward_status, "eligible")
        self.assertEqual(event.reward_tx_id, "REFERRER-TX")

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_service_failure_marks_event_failed(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.mark_eligibility.side_effect = RuntimeError("algorand error")

        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="payment", amount=Decimal("30")),
        )

        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="payment")
        self.referral.refresh_from_db()
        self.assertEqual(event.reward_status, "failed")
        self.assertEqual(self.referral.reward_status, "pending")
        self.assertIn("algorand error", event.error)

    @patch("achievements.services.referral_rewards.ConfioRewardsService")
    def test_duplicate_trigger_does_not_repeat_sync(self, mock_service):
        mock_instance = mock_service.return_value
        mock_instance.mark_eligibility.return_value = RewardSyncResult(
            tx_id="UNIQUE-TX",
            confirmed_round=789,
            referee_confio_micro=8_000_000,
            referrer_confio_micro=2_000_000,
            box_name="1234abcd",
        )

        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="send", amount=Decimal("25")),
        )
        sync_referral_reward_for_event(
            self.referred,
            EventContext(event="send", amount=Decimal("40")),
        )

        mock_instance.mark_eligibility.assert_called_once()
        event = ReferralRewardEvent.objects.get(user=self.referred, trigger="send")
        self.assertEqual(event.amount, Decimal("25"))
        self.assertEqual(event.reward_tx_id, "UNIQUE-TX")

    def test_friend_joined_notifications_created(self):
        new_referral = UserReferral.objects.create(
            referred_user=self.referred,
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
