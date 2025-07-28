"""
Simplify achievement types to focus on core behaviors
"""
from django.core.management.base import BaseCommand
from users.models import AchievementType, UserAchievement


class Command(BaseCommand):
    help = 'Simplify achievement types to focus on core behaviors'

    def handle(self, *args, **options):
        # Deactivate all existing achievements first
        AchievementType.objects.update(is_active=False)
        
        # Core achievements to keep/create
        core_achievements = [
            # Onboarding (Essential)
            {
                'slug': 'first_transaction',
                'name': 'Primera Transacción',
                'description': 'Completa tu primera transacción',
                'category': 'onboarding',
                'confio_reward': 4,
                'display_order': 1,
                'is_active': True,
            },
            {
                'slug': 'dollar_milestone',
                'name': 'Transacción de $1',
                'description': 'Envía o recibe al menos $1',
                'category': 'onboarding', 
                'confio_reward': 4,
                'display_order': 2,
                'is_active': True,
            },
            
            # Viral (Essential)
            {
                'slug': 'friend_referral',
                'name': 'Invita un Amigo',
                'description': 'Tu amigo completa su primera transacción',
                'category': 'viral',
                'confio_reward': 4,
                'display_order': 3,
                'is_active': True,
            },
            
            # Trading (Essential for P2P)
            {
                'slug': 'first_p2p_offer',
                'name': 'Primera Oferta P2P',
                'description': 'Publica tu primera oferta de compra/venta',
                'category': 'trading',
                'confio_reward': 10,
                'display_order': 4,
                'is_active': True,
            },
            
            # Ambassador Path (For serious users)
            {
                'slug': 'influencer_path',
                'name': 'Camino de Influencer',
                'description': 'Alcanza 10 referidos activos',
                'category': 'ambassador',
                'confio_reward': 100,
                'display_order': 5,
                'is_active': True,
            },
        ]
        
        # Update or create simplified achievements
        for achievement_data in core_achievements:
            slug = achievement_data['slug']
            achievement, created = AchievementType.objects.update_or_create(
                slug=slug,
                defaults=achievement_data
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created achievement: {achievement.name}')
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f'Updated achievement: {achievement.name}')
                )
        
        # Show summary
        active_count = AchievementType.objects.filter(is_active=True).count()
        inactive_count = AchievementType.objects.filter(is_active=False).count()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nSimplification complete!'
                f'\nActive achievements: {active_count}'
                f'\nInactive achievements: {inactive_count}'
                f'\n\nFocus is now on:'
                f'\n- First transaction (4 CONFIO both sides)'
                f'\n- $1 milestone (4 CONFIO)'
                f'\n- Friend referral (4 CONFIO)'
                f'\n- First P2P offer (10 CONFIO)'
                f'\n- Influencer path (100 CONFIO)'
            )
        )