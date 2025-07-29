from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from users.models import User
from achievements.models import UserAchievement, AchievementType, ConfioRewardBalance
import random


class Command(BaseCommand):
    help = 'Populate achievements for specific users'

    def add_arguments(self, parser):
        parser.add_argument(
            'usernames',
            nargs='+',
            type=str,
            help='Usernames to populate achievements for'
        )
        parser.add_argument(
            '--all-earned',
            action='store_true',
            help='Mark all achievements as earned'
        )
        parser.add_argument(
            '--all-claimed',
            action='store_true',
            help='Mark all achievements as claimed (implies --all-earned)'
        )
        parser.add_argument(
            '--realistic',
            action='store_true',
            help='Use realistic distribution of achievements'
        )

    def handle(self, *args, **options):
        usernames = options['usernames']
        all_earned = options['all_earned']
        all_claimed = options['all_claimed']
        realistic = options['realistic']
        
        # If all claimed, then all must be earned
        if all_claimed:
            all_earned = True
        
        # Get all achievement types
        achievement_types = AchievementType.objects.filter(is_active=True)
        
        if not achievement_types.exists():
            self.stdout.write(self.style.ERROR('No achievement types found. Run "python manage.py create_achievement_types" first'))
            return
        
        total_confio_distributed = 0
        
        for username in usernames:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
                continue
            
            self.stdout.write(f'\n{self.style.SUCCESS("="*50)}')
            self.stdout.write(f'Processing user: {self.style.WARNING(username)}')
            
            user_created = 0
            user_earned = 0
            user_claimed = 0
            user_confio = 0
            
            with transaction.atomic():
                for achievement_type in achievement_types:
                    user_achievement, created = UserAchievement.objects.get_or_create(
                        user=user,
                        achievement_type=achievement_type,
                        defaults={'status': 'pending'}
                    )
                    
                    if created:
                        user_created += 1
                        
                        # Determine status based on options
                        if all_earned or all_claimed:
                            should_earn = True
                            should_claim = all_claimed
                        elif realistic:
                            # Realistic distribution based on category
                            category_rates = {
                                'bienvenida': (0.9, 0.8),
                                'verificacion': (0.7, 0.9),
                                'trading': (0.4, 0.95),
                                'viral': (0.2, 0.7),
                                'embajador': (0.05, 1.0),
                                'onboarding': (0.9, 0.8),
                                'payments': (0.3, 0.85),
                                'social': (0.25, 0.75),
                                'ambassador': (0.05, 1.0),
                            }
                            earn_rate, claim_rate = category_rates.get(
                                achievement_type.category, 
                                (0.5, 0.8)
                            )
                            should_earn = random.random() < earn_rate
                            should_claim = should_earn and random.random() < claim_rate
                        else:
                            # Default: earn all welcome/verification, claim some
                            if achievement_type.category in ['bienvenida', 'verificacion', 'onboarding', 'verification']:
                                should_earn = True
                                should_claim = random.random() < 0.7
                            else:
                                should_earn = random.random() < 0.3
                                should_claim = should_earn and random.random() < 0.5
                        
                        if should_earn:
                            user_achievement.status = 'earned'
                            user_achievement.earned_at = timezone.now() - timezone.timedelta(
                                days=random.randint(0, 7),
                                hours=random.randint(0, 23)
                            )
                            user_achievement.save()
                            user_earned += 1
                            
                            self.stdout.write(
                                f'  ✅ Earned: {achievement_type.name} '
                                f'({achievement_type.category})'
                            )
                            
                            if should_claim and achievement_type.confio_reward > 0:
                                success = user_achievement.claim_reward()
                                if success:
                                    user_claimed += 1
                                    user_confio += float(achievement_type.confio_reward)
                                    total_confio_distributed += float(achievement_type.confio_reward)
                                    self.stdout.write(
                                        f'     💰 Claimed: {achievement_type.confio_reward} CONFIO'
                                    )
            
            # Show summary for user
            self.stdout.write(f'\n{self.style.SUCCESS("Summary for " + username + ":")}')
            self.stdout.write(f'  📋 Achievements created: {user_created}')
            self.stdout.write(f'  ⭐ Achievements earned: {user_earned}')
            self.stdout.write(f'  💰 Achievements claimed: {user_claimed}')
            self.stdout.write(f'  🪙 CONFIO earned: {user_confio} (${user_confio/4})')
            
            # Show balance
            balance = ConfioRewardBalance.objects.filter(user=user).first()
            if balance:
                self.stdout.write(
                    f'  💳 Total balance: {balance.total_locked} CONFIO '
                    f'(${float(balance.total_locked)/4})'
                )
        
        # Overall summary
        self.stdout.write(f'\n{self.style.SUCCESS("="*50)}')
        self.stdout.write(self.style.SUCCESS('OVERALL SUMMARY'))
        self.stdout.write(f'Total CONFIO distributed: {total_confio_distributed} (${total_confio_distributed/4})')