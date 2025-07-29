"""
Final simplification of achievements based on AI consensus
MVP: Only 5 core achievements
"""
from django.core.management.base import BaseCommand
from achievements.models import AchievementType, UserAchievement
from decimal import Decimal


class Command(BaseCommand):
    help = 'Final simplification - only 5 MVP achievements'

    def handle(self, *args, **options):
        # Deactivate ALL achievements first
        AchievementType.objects.update(is_active=False)
        
        # MVP Phase 1: Only 5 achievements
        mvp_achievements = [
            {
                'slug': 'pionero_beta',
                'name': 'Pionero Beta',
                'description': 'Únete durante la fase beta',
                'category': 'onboarding',
                'confio_reward': Decimal('1'),  # $0.25
                'display_order': 1,
                'is_active': True,
                'icon_emoji': '🚀',
            },
            {
                'slug': 'llegaste_por_influencer', 
                'name': 'Llegaste por Influencer',
                'description': 'Registrado a través de un influencer (ambos ganan)',
                'category': 'social',
                'confio_reward': Decimal('4'),  # $1.00 both sides
                'display_order': 2,
                'is_active': True,
                'icon_emoji': '🎯',
            },
            {
                'slug': 'primera_compra',
                'name': 'Primera Compra P2P',
                'description': 'Completa tu primera compra/venta P2P',
                'category': 'trading',
                'confio_reward': Decimal('8'),  # $2.00
                'display_order': 3,
                'is_active': True,
                'icon_emoji': '🔄',
            },
            {
                'slug': 'hodler_30_dias',
                'name': 'Hodler',
                'description': 'Mantén saldo por 30 días',
                'category': 'onboarding',  # Changed from retention
                'confio_reward': Decimal('12'),  # $3.00
                'display_order': 4,
                'is_active': True,
                'icon_emoji': '💎',
            },
            {
                'slug': '10_intercambios',
                'name': '10 Intercambios',
                'description': 'Completa 10 transacciones P2P',
                'category': 'trading',
                'confio_reward': Decimal('20'),  # $5.00
                'display_order': 5,
                'is_active': True,
                'icon_emoji': '📈',
            },
        ]
        
        # Phase 2 achievements (for future reference, not activated)
        phase2_achievements = [
            {
                'slug': 'trader_frecuente',
                'name': 'Trader Frecuente',
                'description': '50 transacciones completadas',
                'category': 'trading',
                'confio_reward': Decimal('0'),  # Badge only
                'display_order': 10,
                'is_active': False,
                'icon_emoji': '⭐',
                'metadata': {'phase': 2, 'reward_type': 'badge'},
            },
            {
                'slug': 'trader_1000',
                'name': 'Trader $1,000',
                'description': 'Volumen de $1,000 en transacciones',
                'category': 'trading',
                'confio_reward': Decimal('0'),  # Fee discount
                'display_order': 11,
                'is_active': False,
                'icon_emoji': '💰',
                'metadata': {'phase': 2, 'reward_type': 'fee_discount'},
            },
            {
                'slug': 'veterano',
                'name': 'Veterano',
                'description': '6 meses activo en la plataforma',
                'category': 'onboarding',
                'confio_reward': Decimal('20'),  # $5.00
                'display_order': 12,
                'is_active': False,
                'icon_emoji': '🎖️',
                'metadata': {'phase': 2},
            },
        ]
        
        # Create/update MVP achievements
        self.stdout.write(self.style.WARNING('\n=== MVP PHASE 1 (ACTIVE) ==='))
        for achievement_data in mvp_achievements:
            slug = achievement_data['slug']
            achievement, created = AchievementType.objects.update_or_create(
                slug=slug,
                defaults=achievement_data
            )
            
            action = 'Created' if created else 'Updated'
            reward_text = f"{achievement.confio_reward} CONFIO (${float(achievement.confio_reward) * 0.25})"
            self.stdout.write(
                self.style.SUCCESS(
                    f'{action}: {achievement.icon_emoji} {achievement.name} - {reward_text}'
                )
            )
        
        # Create Phase 2 achievements (inactive)
        self.stdout.write(self.style.WARNING('\n=== PHASE 2 (FUTURE - INACTIVE) ==='))
        for achievement_data in phase2_achievements:
            slug = achievement_data['slug']
            metadata = achievement_data.pop('metadata', {})
            achievement, created = AchievementType.objects.update_or_create(
                slug=slug,
                defaults=achievement_data
            )
            
            if metadata.get('reward_type') == 'badge':
                reward_text = "Badge only"
            elif metadata.get('reward_type') == 'fee_discount':
                reward_text = "Fee discount + Badge"
            else:
                reward_text = f"{achievement.confio_reward} CONFIO"
                
            self.stdout.write(
                self.style.NOTICE(
                    f'Prepared: {achievement.icon_emoji} {achievement.name} - {reward_text}'
                )
            )
        
        # Summary
        active_count = AchievementType.objects.filter(is_active=True).count()
        total_count = AchievementType.objects.count()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n=== FINAL SIMPLIFICATION COMPLETE ===\n'
                f'Active achievements: {active_count} (MVP only)\n'
                f'Total in database: {total_count}\n\n'
                f'Expected CAC: $2-3 per user\n'
                f'Max potential reward per user: 45 CONFIO ($11.25)\n'
                f'Average expected: 20 CONFIO ($5.00)\n\n'
                f'Key principle: Less is More!'
            )
        )