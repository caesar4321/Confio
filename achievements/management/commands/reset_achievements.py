from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import User, Business
from users.models_employee import BusinessEmployee
from achievements.models import UserAchievement, AchievementType
from p2p_exchange.models import P2PTrade

class Command(BaseCommand):
    help = 'Reset specific achievements for testing purposes'

    def handle(self, *args, **options):
        # Define the users and achievement slugs to reset
        achievement_slugs = ['pionero_beta', 'primera_compra']
        
        with transaction.atomic():
            # Get Julian's user (ID 1240 based on recent query)
            users = User.objects.filter(id__in=[1240, 8])  # Julian's accounts
            
            # Also try to find by business names
            business_employees = BusinessEmployee.objects.filter(
                business__name__in=['Salud de Julian', 'Sabor de Chicha']
            ).select_related('user', 'business')
            
            # Add business owners to users list
            for be in business_employees:
                if be.role == 'owner':
                    users = users | User.objects.filter(id=be.user.id)
            
            self.stdout.write(f"Found {users.count()} users")
            
            for user in users:
                self.stdout.write(f"\nProcessing user: {user.username} ({user.email})")
                
                # Delete the achievements for this user
                deleted = UserAchievement.objects.filter(
                    user=user,
                    achievement_type__slug__in=achievement_slugs
                ).delete()
                
                self.stdout.write(f"  - Deleted {deleted[0]} achievements")
                
                # Also check if they have business accounts
                business_count = BusinessEmployee.objects.filter(user=user).count()
                if business_count > 0:
                    self.stdout.write(f"  - User is part of {business_count} business(es)")
        
        # Show current P2P trade count for users to help with testing
        self.stdout.write("\n--- P2P Trade Counts ---")
        for user in users:
            from django.db.models import Q
            trade_count = P2PTrade.objects.filter(
                Q(buyer_user=user) | Q(seller_user=user),
                status='COMPLETED',
                deleted_at__isnull=True
            ).count()
            self.stdout.write(f"{user.username}: {trade_count} completed trades")
        
        # Check Pionero Beta description
        self.stdout.write("\n--- Achievement Descriptions ---")
        try:
            pionero = AchievementType.objects.get(slug='pionero_beta')
            self.stdout.write(f"Pionero Beta: {pionero.description}")
            
            primera_compra = AchievementType.objects.get(slug='primera_compra')
            self.stdout.write(f"Primera Compra: {primera_compra.description}")
        except AchievementType.DoesNotExist:
            self.stdout.write("Some achievement types not found")
        
        self.stdout.write(self.style.SUCCESS('\nAchievements reset successfully!'))