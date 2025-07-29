"""
Custom admin views for the users app
"""
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from .models import (
    User, AchievementType, UserAchievement, 
    PioneroBetaTracker, ConfioRewardBalance
)


@staff_member_required
def achievement_dashboard(request):
    """Custom dashboard for achievement system analytics"""
    
    # Get Pionero Beta stats
    pionero_tracker = PioneroBetaTracker.objects.first()
    if not pionero_tracker:
        pionero_tracker = PioneroBetaTracker.objects.create()
    
    pionero_count = pionero_tracker.count
    pionero_remaining = pionero_tracker.get_remaining_slots()
    pionero_percentage = (pionero_count / 10000) * 100
    
    # Calculate days to full (simple projection)
    days_since_launch = max(1, (timezone.now() - User.objects.earliest('date_joined').date_joined).days)
    rate_per_day = pionero_count / days_since_launch if days_since_launch > 0 else 1
    days_to_full = (10000 - pionero_count) / rate_per_day if rate_per_day > 0 else 999
    
    # Get overall stats
    total_users = User.objects.filter(is_active=True).count()
    users_with_achievements = UserAchievement.objects.values('user').distinct().count()
    achievement_penetration = (users_with_achievements / total_users * 100) if total_users > 0 else 0
    
    # Calculate total CONFIO distributed
    total_confio_distributed = UserAchievement.objects.filter(
        status='claimed'
    ).aggregate(
        total=Sum('achievement_type__confio_reward')
    )['total'] or 0
    
    total_usd_value = float(total_confio_distributed) / 4  # 4 CONFIO = $1
    
    # Get achievement stats
    total_achievements_earned = UserAchievement.objects.filter(
        status__in=['earned', 'claimed']
    ).count()
    
    unclaimed_achievements = UserAchievement.objects.filter(
        status='earned'
    ).count()
    
    # Get most popular achievement
    popular = UserAchievement.objects.values(
        'achievement_type__name',
        'achievement_type__icon_emoji'
    ).annotate(
        count=Count('id')
    ).order_by('-count').first()
    
    most_popular = {
        'name': popular['achievement_type__name'] if popular else 'N/A',
        'emoji': popular['achievement_type__icon_emoji'] if popular else '🏆',
        'count': popular['count'] if popular else 0
    }
    
    # Get detailed achievement data
    achievements = []
    for achievement in AchievementType.objects.filter(is_active=True).order_by('display_order'):
        user_count = UserAchievement.objects.filter(
            achievement_type=achievement,
            status__in=['earned', 'claimed']
        ).count()
        
        total_distributed = user_count * float(achievement.confio_reward)
        
        achievements.append({
            'name': achievement.name,
            'slug': achievement.slug,
            'emoji': achievement.icon_emoji or '🏆',
            'reward': achievement.confio_reward,
            'user_count': user_count,
            'total_distributed': total_distributed,
            'usd_value': total_distributed / 4,
            'is_active': achievement.is_active
        })
    
    context = {
        'title': 'Achievement Dashboard',
        'pionero_count': pionero_count,
        'pionero_remaining': pionero_remaining,
        'pionero_percentage': pionero_percentage,
        'days_to_full': days_to_full,
        'total_confio_distributed': total_confio_distributed,
        'total_usd_value': total_usd_value,
        'users_with_achievements': users_with_achievements,
        'achievement_penetration': achievement_penetration,
        'total_achievements_earned': total_achievements_earned,
        'unclaimed_achievements': unclaimed_achievements,
        'most_popular': most_popular,
        'achievements': achievements,
    }
    
    return render(request, 'admin/users/achievement_dashboard.html', context)