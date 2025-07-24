from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Avg, Q
from .models import P2PTrade, P2PTradeRating, P2PUserStats

@receiver(post_save, sender=P2PTrade)
def update_user_stats_on_trade(sender, instance, created, **kwargs):
    """Update user stats when a trade status changes"""
    if instance.status == 'COMPLETED':
        # Update seller stats
        if instance.seller:
            update_stats_for_user(instance.seller)
        elif instance.seller_business:
            update_stats_for_business(instance.seller_business)
            
        # Update buyer stats  
        if instance.buyer:
            update_stats_for_user(instance.buyer)
        elif instance.buyer_business:
            update_stats_for_business(instance.buyer_business)

def update_stats_for_user(user):
    """Update stats for a user"""
    stats, created = P2PUserStats.objects.get_or_create(
        stats_user=user,
        defaults={'stats_user': user}
    )
    
    # Count trades where user is buyer or seller
    from django.db.models import Q
    trades = P2PTrade.objects.filter(
        Q(buyer=user) | Q(seller=user)
    )
    
    stats.total_trades = trades.count()
    stats.completed_trades = trades.filter(status='COMPLETED').count()
    stats.cancelled_trades = trades.filter(status='CANCELLED').count()
    stats.disputed_trades = trades.filter(status='DISPUTED').count()
    
    # Calculate success rate
    if stats.total_trades > 0:
        stats.success_rate = (stats.completed_trades / stats.total_trades) * 100
    else:
        stats.success_rate = 0
        
    # Calculate average rating
    ratings = P2PTradeRating.objects.filter(ratee_user=user)
    if ratings.exists():
        avg_rating = ratings.aggregate(avg=Avg('overall_rating'))['avg']
        stats.avg_rating = avg_rating or 0
    
    stats.save()

def update_stats_for_business(business):
    """Update stats for a business"""
    stats, created = P2PUserStats.objects.get_or_create(
        stats_business=business,
        defaults={'stats_business': business}
    )
    
    # Similar logic but for business
    from django.db.models import Q
    trades = P2PTrade.objects.filter(
        Q(buyer_business=business) | Q(seller_business=business)
    )
    
    stats.total_trades = trades.count()
    stats.completed_trades = trades.filter(status='COMPLETED').count()
    stats.cancelled_trades = trades.filter(status='CANCELLED').count()
    stats.disputed_trades = trades.filter(status='DISPUTED').count()
    
    if stats.total_trades > 0:
        stats.success_rate = (stats.completed_trades / stats.total_trades) * 100
    else:
        stats.success_rate = 0
    
    # Calculate average rating for business
    ratings = P2PTradeRating.objects.filter(ratee_business=business)
    if ratings.exists():
        avg_rating = ratings.aggregate(avg=Avg('overall_rating'))['avg']
        stats.avg_rating = avg_rating or 0
        
    stats.save()

@receiver(post_save, sender=P2PTradeRating)
def update_user_stats_on_rating(sender, instance, created, **kwargs):
    """Update average rating when a new rating is added"""
    if created:
        if instance.ratee_user:
            update_stats_for_user(instance.ratee_user)
        elif instance.ratee_business:
            update_stats_for_business(instance.ratee_business)