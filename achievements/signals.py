from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from .models import AchievementType, UserAchievement, InfluencerReferral, PioneroBetaTracker
from p2p_exchange.models import P2PTrade

import logging

User = get_user_model()
logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_welcome_achievement(sender, instance, created, **kwargs):
    """
    Automatically award the Pionero Beta achievement to new users
    Only for the first 10,000 users
    """
    if created:
        try:
            # Use atomic counter to check if we can award Pionero Beta
            can_award, current_count = PioneroBetaTracker.increment_and_check()
            
            if can_award:
                pionero_achievement = AchievementType.objects.get(slug='pionero_beta')
                UserAchievement.objects.create(
                    user=instance,
                    achievement_type=pionero_achievement,
                    status='earned',
                    earned_at=instance.date_joined
                )
                
                # Update tracker with user ID
                tracker = PioneroBetaTracker.objects.get(pk=1)
                tracker.last_user_id = instance.id
                tracker.save(update_fields=['last_user_id'])
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