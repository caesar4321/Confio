"""
Test command to verify achievement system is working
"""
from django.core.management.base import BaseCommand
from users.models import AchievementType, UserAchievement, User


class Command(BaseCommand):
    help = 'Test achievement system'

    def handle(self, *args, **options):
        # Show all active achievements
        self.stdout.write("\n=== Active Achievements ===")
        for achievement in AchievementType.objects.filter(is_active=True).order_by('display_order'):
            self.stdout.write(
                f"{achievement.slug}: {achievement.name} - {achievement.confio_reward} CONFIO"
            )
            
            # Count how many users have this achievement
            count = UserAchievement.objects.filter(
                achievement_type=achievement
            ).count()
            self.stdout.write(f"  -> Awarded to {count} users\n")
        
        # Check a specific user's achievements
        try:
            test_user = User.objects.filter(username='julian').first()
            if test_user:
                self.stdout.write(f"\n=== Achievements for user: {test_user.username} ===")
                user_achievements = UserAchievement.objects.filter(user=test_user)
                for ua in user_achievements:
                    self.stdout.write(
                        f"- {ua.achievement_type.name}: {ua.status} "
                        f"(earned: {ua.earned_at}, claimed: {ua.claimed_at})"
                    )
        except Exception as e:
            self.stdout.write(f"Error checking user achievements: {e}")
        
        self.stdout.write("\n=== Achievement Triggers ===")
        self.stdout.write("✓ Pionero Beta: Awarded on user signup")
        self.stdout.write("✓ Conexión Exitosa: Awarded when setting referrer")
        self.stdout.write("✓ Primera Compra P2P: Awarded on first P2P trade")
        self.stdout.write("✓ 10 Intercambios: Awarded after 10 P2P trades")
        self.stdout.write("✓ Referido Exitoso: Awarded when referred user completes first trade")
        self.stdout.write("✓ Hodler 30 días: Run 'check_hodler_achievements' command daily")