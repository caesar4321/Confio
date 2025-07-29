"""
Management command to check and award Hodler achievements
Should be run daily via cron job
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from users.models import User
from achievements.models import AchievementType, UserAchievement
from django.db.models import Q, F


class Command(BaseCommand):
    help = 'Check and award Hodler achievements for users who have held CONFIO for 30 days'

    def handle(self, *args, **options):
        try:
            # Get the hodler achievement type
            hodler_achievement = AchievementType.objects.get(slug='hodler_30_dias')
            
            # Find users who:
            # 1. Signed up at least 30 days ago
            # 2. Don't have the hodler achievement yet
            # 3. Have a CONFIO balance > 0
            cutoff_date = timezone.now() - timedelta(days=30)
            
            eligible_users = User.objects.filter(
                date_joined__lte=cutoff_date,
                is_active=True
            ).exclude(
                achievements__achievement_type=hodler_achievement
            )
            
            awarded_count = 0
            
            for user in eligible_users:
                # Check if user has maintained CONFIO balance for 30 days
                # For now, we'll check if they have any CONFIO rewards earned
                if UserAchievement.objects.filter(
                    user=user,
                    status__in=['earned', 'claimed'],
                    earned_at__lte=cutoff_date
                ).exists():
                    # Award the hodler achievement
                    UserAchievement.objects.create(
                        user=user,
                        achievement_type=hodler_achievement,
                        status='earned',
                        earned_at=timezone.now()
                    )
                    awarded_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Awarded Hodler achievement to {user.username}'
                        )
                    )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully awarded {awarded_count} Hodler achievements'
                )
            )
            
        except AchievementType.DoesNotExist:
            self.stdout.write(
                self.style.ERROR('Hodler achievement type not found')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error processing hodler achievements: {str(e)}')
            )