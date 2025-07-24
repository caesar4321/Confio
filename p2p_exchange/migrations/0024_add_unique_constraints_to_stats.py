# Generated manually
from django.db import migrations, models

def remove_duplicate_stats(apps, schema_editor):
    """Remove duplicate stats keeping the one with most trades"""
    P2PUserStats = apps.get_model('p2p_exchange', 'P2PUserStats')
    
    # Handle duplicates for stats_user
    from django.db.models import Count, Max
    
    # Find users with duplicate stats
    duplicates = P2PUserStats.objects.values('stats_user').annotate(
        count=Count('id')
    ).filter(count__gt=1, stats_user__isnull=False)
    
    for dup in duplicates:
        user_id = dup['stats_user']
        # Keep the one with most total_trades
        stats = P2PUserStats.objects.filter(stats_user=user_id).order_by('-total_trades')
        keep = stats.first()
        # Delete the rest
        P2PUserStats.objects.filter(stats_user=user_id).exclude(id=keep.id).delete()
    
    # Handle duplicates for stats_business
    duplicates = P2PUserStats.objects.values('stats_business').annotate(
        count=Count('id')
    ).filter(count__gt=1, stats_business__isnull=False)
    
    for dup in duplicates:
        business_id = dup['stats_business']
        # Keep the one with most total_trades
        stats = P2PUserStats.objects.filter(stats_business=business_id).order_by('-total_trades')
        keep = stats.first()
        # Delete the rest
        P2PUserStats.objects.filter(stats_business=business_id).exclude(id=keep.id).delete()
    
    # Handle old 'user' field duplicates
    duplicates = P2PUserStats.objects.values('user').annotate(
        count=Count('id')
    ).filter(count__gt=1, user__isnull=False)
    
    for dup in duplicates:
        user_id = dup['user']
        # Keep the one with most total_trades
        stats = P2PUserStats.objects.filter(user=user_id).order_by('-total_trades')
        keep = stats.first()
        # Delete the rest
        P2PUserStats.objects.filter(user=user_id).exclude(id=keep.id).delete()

def reverse_remove_duplicates(apps, schema_editor):
    """This migration is not reversible"""
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0023_add_unique_constraint_to_user_stats'),
    ]

    operations = [
        # First remove duplicates
        migrations.RunPython(remove_duplicate_stats, reverse_remove_duplicates),
        
        # Then add unique constraints
        migrations.AddConstraint(
            model_name='p2puserstats',
            constraint=models.UniqueConstraint(
                fields=['stats_user'],
                condition=models.Q(stats_user__isnull=False),
                name='unique_stats_per_user'
            ),
        ),
        migrations.AddConstraint(
            model_name='p2puserstats',
            constraint=models.UniqueConstraint(
                fields=['stats_business'],
                condition=models.Q(stats_business__isnull=False),
                name='unique_stats_per_business'
            ),
        ),
        # Also add unique constraint for old user field to prevent issues
        migrations.AddConstraint(
            model_name='p2puserstats',
            constraint=models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(user__isnull=False),
                name='unique_stats_per_old_user'
            ),
        ),
    ]