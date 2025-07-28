from django.core.management.base import BaseCommand
from users.models import AchievementType


class Command(BaseCommand):
    help = 'Clean up old achievements and keep only the refined set'

    def handle(self, *args, **options):
        # List of achievement slugs we want to KEEP
        keep_slugs = [
            # Onboarding
            'welcome_signup',
            'identity_verified',
            # Trading
            'first_p2p_trade',
            'trading_10',
            'frequent_trader',
            'volume_trader_1k',
            'volume_trader_10k',
            # Payments
            'first_send',
            'first_receive',
            'first_payment',
            'traveler',
            'merchant_10',
            # Community
            'ambassador_5',
            'community_helper',
            'hodler_30',
            'veteran_6months',
            # TikTok Viral
            'influencer_referred',
            'primera_viral',
            'explosion_viral',
            'mega_viral',
            'tendencia_nacional',
            # Influencer Tiers
            'nano_influencer',
            'micro_influencer',
            'macro_influencer',
            'confio_ambassador',
        ]
        
        # Delete achievements not in our keep list
        deleted = AchievementType.objects.exclude(slug__in=keep_slugs).delete()
        
        self.stdout.write(
            self.style.SUCCESS(f'Deleted {deleted[0]} old achievements')
        )
        
        # Show remaining achievements
        remaining = AchievementType.objects.all().order_by('category', 'confio_reward')
        self.stdout.write('\nRemaining achievements:')
        for achievement in remaining:
            self.stdout.write(f'{achievement.category} | {achievement.name} | {achievement.confio_reward} CONFIO')