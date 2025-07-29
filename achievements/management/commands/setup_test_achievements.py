from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import User
from achievements.models import UserAchievement, AchievementType


class Command(BaseCommand):
    help = 'Set up test achievements for a user'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Username to set up achievements for',
            required=True
        )
        parser.add_argument(
            '--earned',
            action='store_true',
            help='Mark some achievements as earned (ready to claim)'
        )
        parser.add_argument(
            '--claimed',
            action='store_true',
            help='Mark some achievements as claimed'
        )

    def handle(self, *args, **options):
        username = options['username']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
            return
        
        # Get all achievement types
        achievement_types = AchievementType.objects.filter(is_active=True)
        
        if not achievement_types.exists():
            self.stdout.write(self.style.ERROR('No achievement types found. Run "python manage.py create_achievement_types" first'))
            return
        
        created_count = 0
        earned_count = 0
        claimed_count = 0
        
        for achievement_type in achievement_types:
            user_achievement, created = UserAchievement.objects.get_or_create(
                user=user,
                achievement_type=achievement_type,
                defaults={'status': 'pending'}
            )
            
            if created:
                created_count += 1
                
                # Set some as earned
                if options['earned'] and achievement_type.category in ['bienvenida', 'verificacion']:
                    user_achievement.status = 'earned'
                    user_achievement.earned_at = timezone.now()
                    user_achievement.save()
                    earned_count += 1
                    
                    # Set some as claimed
                    if options['claimed'] and achievement_type.slug in ['welcome_signup', 'kyc_level1']:
                        success = user_achievement.claim_reward()
                        if success:
                            claimed_count += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'  ✅ Claimed: {achievement_type.name} ({achievement_type.confio_reward} CONFIO)'
                                )
                            )
        
        self.stdout.write(self.style.SUCCESS(f'\nSummary for user "{username}":'))
        self.stdout.write(f'  - Created: {created_count} achievements')
        self.stdout.write(f'  - Earned: {earned_count} achievements')
        self.stdout.write(f'  - Claimed: {claimed_count} achievements (rewards distributed)')
        
        # Show balance if any rewards were claimed
        if claimed_count > 0:
            from achievements.models import ConfioRewardBalance
            balance = ConfioRewardBalance.objects.filter(user=user).first()
            if balance:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n💰 User CONFIO Balance: {balance.total_locked} CONFIO (${balance.total_locked / 4})'
                    )
                )