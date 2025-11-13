from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from .models import (
    AchievementType,
    UserAchievement,
    UserReferral,
    PioneroBetaTracker,
    ReferralRewardEvent,
)
from achievements.services.referral_rewards import (
    EventContext,
    sync_referral_reward_for_event,
    DEFAULT_EVENT_REWARD_CONFIG,
    notify_referral_joined,
)
from p2p_exchange.models import P2PTrade
from security.models import DeviceFingerprint, IPAddress, UserDevice
from notifications.utils import create_notification
from notifications.models import NotificationType as NotificationTypeChoices

import logging

User = get_user_model()
logger = logging.getLogger(__name__)


def send_achievement_notification(user_achievement):
    """
    Send push notification when an achievement is earned
    """
    try:
        # Create notification for achievement earned
        notification = create_notification(
            user=user_achievement.user,
            notification_type=NotificationTypeChoices.ACHIEVEMENT_EARNED,
            title=f"¡Logro Desbloqueado! {user_achievement.achievement_type.icon_emoji}",
            message=f"Has ganado el logro: {user_achievement.achievement_type.name}",
            data={
                'achievement_id': str(user_achievement.id),
                'achievement_slug': user_achievement.achievement_type.slug,
                'achievement_name': user_achievement.achievement_type.name,
                'confio_reward': str(user_achievement.achievement_type.confio_reward),
                'icon_emoji': user_achievement.achievement_type.icon_emoji or '',
            },
            related_object_type='UserAchievement',
            related_object_id=str(user_achievement.id),
            action_url=f'confio://achievements/{user_achievement.achievement_type.slug}',
            send_push=True
        )
        logger.info(f"Achievement notification sent for user {user_achievement.user.id}, achievement {user_achievement.achievement_type.slug}")
    except Exception as e:
        logger.error(f"Error sending achievement notification: {e}", exc_info=True)


@receiver(post_save, sender=UserAchievement)
def handle_achievement_earned(sender, instance, created, **kwargs):
    """
    Handle when a user achievement is created or updated
    """
    # Only send notification when achievement is newly earned
    if instance.status == 'earned' and created:
        send_achievement_notification(instance)


@receiver(post_save, sender=User)
def create_welcome_achievement(sender, instance, created, **kwargs):
    """
    Automatically award the Pionero Beta achievement to new users
    Only for the first 10,000 users
    Now with device fingerprint fraud prevention
    """
    if created:
        try:
            # Get device fingerprint and IP from the current request context
            device_fingerprint_hash = None
            ip_address = None
            security_metadata = {}
            
            # Try to get the device fingerprint from the user's session
            # This would be set during the authentication process
            if hasattr(instance, '_device_fingerprint_hash'):
                device_fingerprint_hash = instance._device_fingerprint_hash
                
                # Check if this device has already claimed Pionero Beta
                existing_achievement = UserAchievement.objects.filter(
                    achievement_type__slug='pionero_beta',
                    device_fingerprint_hash=device_fingerprint_hash,
                    status__in=['earned', 'claimed']
                ).exists()
                
                if existing_achievement:
                    logger.warning(
                        f"Device fingerprint {device_fingerprint_hash} already claimed Pionero Beta. "
                        f"Blocking achievement for user {instance.id}"
                    )
                    security_metadata['fraud_detected'] = 'duplicate_device'
                    security_metadata['blocked_reason'] = 'Device already claimed Pionero Beta'
                    return
            
            # Get IP address if available
            if hasattr(instance, '_registration_ip'):
                ip_address = instance._registration_ip
                
                # Check for suspicious IP patterns
                recent_registrations = User.objects.filter(
                    date_joined__gte=timezone.now() - timezone.timedelta(hours=1)
                ).count()
                
                if recent_registrations > 10:
                    logger.warning(
                        f"Suspicious registration rate from IP {ip_address}. "
                        f"{recent_registrations} registrations in last hour."
                    )
                    security_metadata['suspicious_ip'] = True
                    security_metadata['recent_registrations'] = recent_registrations
            
            # Use atomic counter to check if we can award Pionero Beta
            can_award, current_count = PioneroBetaTracker.increment_and_check()
            
            if can_award:
                pionero_achievement = AchievementType.objects.get(slug='pionero_beta')
                UserAchievement.objects.create(
                    user=instance,
                    achievement_type=pionero_achievement,
                    status='earned',
                    earned_at=instance.date_joined,
                    device_fingerprint_hash=device_fingerprint_hash,
                    claim_ip_address=ip_address,
                    security_metadata=security_metadata
                )
                
                # Update tracker with user ID
                tracker = PioneroBetaTracker.objects.get(pk=1)
                tracker.last_user_id = instance.id
                tracker.save(update_fields=['last_user_id'])
                
                logger.info(
                    f"Pionero Beta awarded to user {instance.id} "
                    f"(#{current_count}/10,000) "
                    f"Device: {device_fingerprint_hash[:8] if device_fingerprint_hash else 'Unknown'}"
                )
            else:
                # Log that we've reached the limit
                logger.info(f"Pionero Beta limit reached: {current_count}/10,000")
                
        except AchievementType.DoesNotExist:
            # Achievement type doesn't exist yet, skip
            # Decrement the counter since we didn't actually award
            tracker = PioneroBetaTracker.objects.get(pk=1)
            if tracker.count > 0:
                tracker.count -= 1
                tracker.save(update_fields=['count'])
            pass


@receiver(post_save, sender=P2PTrade)
def handle_p2p_trade_achievements(sender, instance, created, **kwargs):
    """
    Handle achievements related to P2P trades
    """
    # Only process fully completed trades
    if instance.status != 'COMPLETED':
        return
    
    # Skip if soft deleted
    if instance.deleted_at is not None:
        return
    
    # Get both buyer and seller - but ONLY if they're trading with personal accounts
    users_to_check = []
    
    # Only add buyer_user if they're NOT using a business account
    if instance.buyer_user and not instance.buyer_business:
        users_to_check.append(instance.buyer_user)
    
    # Only add seller_user if they're NOT using a business account
    if instance.seller_user and not instance.seller_business and instance.seller_user != instance.buyer_user:
        users_to_check.append(instance.seller_user)
    
    for user in users_to_check:
        try:
            # Check for "Primera Compra P2P" achievement
            primera_compra = AchievementType.objects.get(slug='primera_compra')
            if not UserAchievement.objects.filter(
                user=user,
                achievement_type=primera_compra
            ).exists():
                # Award achievement for first P2P trade
                UserAchievement.objects.create(
                    user=user,
                    achievement_type=primera_compra,
                    status='earned',
                    earned_at=timezone.now()
                )
                
                # Check referral and award both sides if applicable
                _award_referral_pair(user)
            
            # Check for "10 Intercambios" achievement (only COMPLETED trades with personal accounts)
            trades_count = P2PTrade.objects.filter(
                (
                    Q(buyer_user=user, buyer_business__isnull=True) | 
                    Q(seller_user=user, seller_business__isnull=True)
                ),
                status='COMPLETED',  # Only count fully completed trades
                deleted_at__isnull=True
            ).count()
            
            if trades_count >= 10:
                diez_intercambios = AchievementType.objects.get(slug='10_intercambios')
                if not UserAchievement.objects.filter(
                    user=user,
                    achievement_type=diez_intercambios
                ).exists():
                    UserAchievement.objects.create(
                        user=user,
                        achievement_type=diez_intercambios,
                        status='earned',
                        earned_at=timezone.now()
                    )
        except AchievementType.DoesNotExist:
            pass


def _award_referral_pair(user):
    """
    Award referral achievements for both sides when the referred user completes
    their first transaction (of any type). Safe to call multiple times.
    """
    try:
        # Find if this user was referred
        referral = UserReferral.objects.filter(
            referred_user=user,
            status='pending'
        ).first()
        
        if not referral:
            return

        # Update referral conversion timestamp and status
        referral.first_transaction_at = referral.first_transaction_at or timezone.now()
        try:
            # Some environments may not have this helper; update inline
            if hasattr(referral, 'mark_as_converted'):
                referral.mark_as_converted()
            else:
                referral.status = 'converted'
                referral.save(update_fields=['status', 'first_transaction_at'])
        except Exception:
            referral.status = 'converted'
            referral.save(update_fields=['status', 'first_transaction_at'])

        # Award INVITER achievement
        if referral.referrer_user:
            try:
                successful_referral = AchievementType.objects.get(slug='successful_referral')
                if not UserAchievement.objects.filter(
                    user=referral.referrer_user,
                    achievement_type=successful_referral
                ).exists():
                    UserAchievement.objects.create(
                        user=referral.referrer_user,
                        achievement_type=successful_referral,
                        status='earned',
                        earned_at=timezone.now()
                    )
            except AchievementType.DoesNotExist:
                pass

        # Award INVITEE achievement
        try:
            invited_ach = AchievementType.objects.get(slug='llegaste_por_influencer')
            if not UserAchievement.objects.filter(
                user=user,
                achievement_type=invited_ach
            ).exists():
                UserAchievement.objects.create(
                    user=user,
                    achievement_type=invited_ach,
                    status='earned',
                    earned_at=timezone.now()
                )
        except AchievementType.DoesNotExist:
            pass

    except AchievementType.DoesNotExist:
        pass


@receiver(post_save, sender=UserReferral)
def sync_pending_reward_events(sender, instance: UserReferral, created, **kwargs):
    """When a referral exists, link and process any pending reward events."""
    if created:
        notify_referral_joined(instance)

    users_to_check = [u for u in [instance.referred_user, instance.referrer_user] if u]
    if not users_to_check:
        return

    pending_events = ReferralRewardEvent.objects.filter(
        user__in=users_to_check,
        referral__isnull=True,
        reward_status='pending',
        trigger__in=DEFAULT_EVENT_REWARD_CONFIG.keys(),
    )

    for event in pending_events:
        event.referral = instance
        event.save(update_fields=['referral', 'updated_at'])
        sync_referral_reward_for_event(
            event.user,
            EventContext(
                event=event.trigger,
                amount=event.amount,
                metadata=event.metadata,
            ),
        )

    # Ensure the referred user sees a placeholder pending reward in the app.
    def ensure_pending_event(user, role: str, stage_meta: str, reward_amount: Decimal):
        if not user:
            return
        defaults = {
            "user": user,
            "referral": instance,
            "trigger": "referral_pending",
            "actor_role": role,
            "amount": Decimal("0"),
            "transaction_reference": "",
            "occurred_at": instance.created_at or timezone.now(),
            "reward_status": "pending",
            "referee_confio": reward_amount if role == "referee" else Decimal("0"),
            "referrer_confio": reward_amount if role == "referrer" else Decimal("0"),
            "metadata": {"stage": stage_meta},
        }
        event, created_flag = ReferralRewardEvent.objects.get_or_create(
            user=user,
            trigger="referral_pending",
            defaults=defaults,
        )
        if not created_flag:
            needs_update = False
            if event.referral_id != instance.id:
                event.referral = instance
                needs_update = True
            if event.reward_status != "pending":
                event.reward_status = "pending"
                needs_update = True
            if needs_update:
                event.save(update_fields=["referral", "reward_status", "updated_at"])

    ensure_pending_event(
        instance.referred_user,
        "referee",
        "pending_first_transaction",
        instance.reward_referee_confio or Decimal("0"),
    )
    ensure_pending_event(
        instance.referrer_user,
        "referrer",
        "pending_referrer_bonus",
        instance.reward_referrer_confio or Decimal("0"),
    )
