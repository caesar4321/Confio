from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from users.models import User
from achievements.models import UserAchievement, AchievementType, ConfioRewardBalance
import random


class Command(BaseCommand):
    help = 'Populate mock achievements for zkLogin users'

    def handle(self, *args, **options):
        # Get all zkLogin users (users with accounts that have aptos_address set)
        from users.models import Account
        
        zklogin_accounts = Account.objects.filter(
            aptos_address__isnull=False
        ).exclude(aptos_address='').select_related('user')
        
        zklogin_users = User.objects.filter(
            id__in=zklogin_accounts.values_list('user_id', flat=True)
        ).distinct()
        
        if not zklogin_users.exists():
            self.stdout.write(self.style.ERROR('No zkLogin users found'))
            return
        
        self.stdout.write(f'Found {zklogin_users.count()} zkLogin users')
        
        # Get all achievement types
        achievement_types = AchievementType.objects.filter(is_active=True)
        
        if not achievement_types.exists():
            self.stdout.write(self.style.ERROR('No achievement types found. Run "python manage.py create_achievement_types" first'))
            return
        
        # Categories and their typical completion patterns
        achievement_patterns = {
            'bienvenida': {
                'completion_rate': 0.9,  # 90% complete welcome achievements
                'claim_rate': 0.8,       # 80% of earned are claimed
            },
            'verificacion': {
                'completion_rate': 0.7,  # 70% complete verification
                'claim_rate': 0.9,       # 90% of earned are claimed
            },
            'trading': {
                'completion_rate': 0.4,  # 40% do trading
                'claim_rate': 0.95,      # 95% of earned are claimed (high value)
            },
            'viral': {
                'completion_rate': 0.2,  # 20% participate in viral
                'claim_rate': 0.7,       # 70% of earned are claimed
            },
            'embajador': {
                'completion_rate': 0.05, # 5% become ambassadors
                'claim_rate': 1.0,       # 100% of earned are claimed (exclusive)
            },
            # For old category names
            'onboarding': {
                'completion_rate': 0.9,
                'claim_rate': 0.8,
            },
            'payments': {
                'completion_rate': 0.3,
                'claim_rate': 0.85,
            },
            'social': {
                'completion_rate': 0.25,
                'claim_rate': 0.75,
            },
            'ambassador': {
                'completion_rate': 0.05,
                'claim_rate': 1.0,
            },
        }
        
        total_created = 0
        total_earned = 0
        total_claimed = 0
        total_confio_distributed = 0
        
        with transaction.atomic():
            for user in zklogin_users:
                # Get user's sui address
                user_account = zklogin_accounts.filter(user=user).first()
                aptos_address = user_account.aptos_address if user_account else 'N/A'
                self.stdout.write(f'\nProcessing user: {user.username} (aptos_address: {aptos_address[:20] if aptos_address != "N/A" else "N/A"}...)')
                user_earned = 0
                user_claimed = 0
                user_confio = 0
                
                for achievement_type in achievement_types:
                    # Get pattern for this category
                    pattern = achievement_patterns.get(
                        achievement_type.category, 
                        {'completion_rate': 0.3, 'claim_rate': 0.8}
                    )
                    
                    # Create user achievement
                    user_achievement, created = UserAchievement.objects.get_or_create(
                        user=user,
                        achievement_type=achievement_type,
                        defaults={'status': 'pending'}
                    )
                    
                    if created:
                        total_created += 1
                        
                        # Determine if earned based on completion rate
                        if random.random() < pattern['completion_rate']:
                            user_achievement.status = 'earned'
                            user_achievement.earned_at = timezone.now() - timezone.timedelta(
                                days=random.randint(1, 30),
                                hours=random.randint(0, 23),
                                minutes=random.randint(0, 59)
                            )
                            user_achievement.save()
                            total_earned += 1
                            user_earned += 1
                            
                            # Determine if claimed based on claim rate
                            if random.random() < pattern['claim_rate']:
                                # Claim the reward
                                if achievement_type.confio_reward > 0:
                                    success = user_achievement.claim_reward()
                                    if success:
                                        total_claimed += 1
                                        user_claimed += 1
                                        user_confio += float(achievement_type.confio_reward)
                                        total_confio_distributed += float(achievement_type.confio_reward)
                
                # Add some progress data for pending achievements
                pending_achievements = UserAchievement.objects.filter(
                    user=user,
                    status='pending'
                )
                
                for achievement in pending_achievements.select_related('achievement_type'):
                    # Add random progress for some achievements
                    if random.random() < 0.6:  # 60% have some progress
                        if achievement.achievement_type.category == 'trading':
                            achievement.progress_data = {
                                'trades_completed': random.randint(0, 4),
                                'trades_required': 5
                            }
                        elif achievement.achievement_type.category == 'viral':
                            achievement.progress_data = {
                                'views_achieved': random.randint(0, 900),
                                'views_required': 1000
                            }
                        elif achievement.achievement_type.category == 'verificacion':
                            achievement.progress_data = {
                                'steps_completed': random.randint(1, 2),
                                'steps_required': 3
                            }
                        achievement.save()
                
                self.stdout.write(
                    f'  ✓ Created {total_created} achievements, '
                    f'{user_earned} earned, {user_claimed} claimed '
                    f'({user_confio} CONFIO)'
                )
        
        # Summary
        self.stdout.write(self.style.SUCCESS('\n=== Summary ==='))
        self.stdout.write(f'Users processed: {zklogin_users.count()}')
        self.stdout.write(f'Achievements created: {total_created}')
        self.stdout.write(f'Achievements earned: {total_earned}')
        self.stdout.write(f'Achievements claimed: {total_claimed}')
        self.stdout.write(f'Total CONFIO distributed: {total_confio_distributed} (${total_confio_distributed/4})')
        
        # Show top achievers
        self.stdout.write(self.style.SUCCESS('\n=== Top Achievers ==='))
        top_users = ConfioRewardBalance.objects.filter(
            user__in=zklogin_users
        ).order_by('-total_earned')[:5]
        
        for i, balance in enumerate(top_users, 1):
            self.stdout.write(
                f'{i}. {balance.user.username}: '
                f'{balance.total_earned} CONFIO '
                f'(${float(balance.total_earned)/4})'
            )