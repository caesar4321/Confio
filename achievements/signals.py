from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from .models import AchievementType, UserAchievement, InfluencerReferral, PioneroBetaTracker
from p2p_exchange.models import P2PTrade
from security.models import DeviceFingerprint, IPAddress, UserDevice

import logging

User = get_user_model()
logger = logging.getLogger(__name__)


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
    
    # Get both buyer and seller
    users_to_check = []
    if instance.buyer_user:
        users_to_check.append(instance.buyer_user)
    if instance.seller_user and instance.seller_user != instance.buyer_user:
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
                
                # Check if this user was referred and award referrer achievement
                check_referral_achievement(user)
            
            # Check for "10 Intercambios" achievement (only COMPLETED trades)
            trades_count = P2PTrade.objects.filter(
                Q(buyer_user=user) | Q(seller_user=user),
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


def check_referral_achievement(user):
    """
    Check if the user's referrer should get the successful referral achievement
    """
    try:
        # Find if this user was referred
        referral = InfluencerReferral.objects.filter(
            referred_user=user,
            status='pending'
        ).first()
        
        if referral:
            # Update referral status
            referral.mark_as_converted()
            
            # Award achievement to the referrer if they exist in the system
            if referral.influencer_user:
                successful_referral = AchievementType.objects.get(slug='successful_referral')
                if not UserAchievement.objects.filter(
                    user=referral.influencer_user,
                    achievement_type=successful_referral
                ).exists():
                    UserAchievement.objects.create(
                        user=referral.influencer_user,
                        achievement_type=successful_referral,
                        status='earned',
                        earned_at=timezone.now()
                    )
            
            # Award the referee their achievement (already handled in SetReferrer mutation)
            # but update the referral status
            referral.first_transaction_at = timezone.now()
            referral.save(update_fields=['first_transaction_at'])
            
    except AchievementType.DoesNotExist:
        pass