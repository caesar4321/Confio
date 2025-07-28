from django.core.management.base import BaseCommand
from users.models import AchievementType


class Command(BaseCommand):
    help = 'Reorder achievements by reward amount within each category'

    def handle(self, *args, **options):
        # Define proper ordering by category and reward amount
        ordering = [
            # Onboarding (1-9)
            ('welcome_signup', 1),      # 1 CONFIO
            
            # Verification (10-19) 
            ('identity_verified', 10),  # 2 CONFIO
            
            # Trading (20-29) - Ordered by reward
            ('first_p2p_trade', 20),    # 8 CONFIO
            ('trading_10', 21),         # 20 CONFIO
            ('frequent_trader', 22),    # 40 CONFIO
            ('volume_trader_1k', 23),   # 50 CONFIO
            ('volume_trader_10k', 24),  # 200 CONFIO
            
            # Payments (30-39) - Ordered by reward
            ('first_receive', 30),      # 1 CONFIO
            ('first_send', 31),         # 1 CONFIO
            ('first_payment', 32),      # 2 CONFIO
            ('traveler', 33),           # 10 CONFIO
            ('merchant_10', 34),        # 20 CONFIO
            
            # Community/Social (40-59) - Ordered by reward
            ('influencer_referred', 40), # 4 CONFIO
            ('primera_viral', 41),       # 4 CONFIO
            ('community_helper', 42),    # 8 CONFIO
            ('ambassador_5', 43),        # 10 CONFIO
            ('hodler_30', 44),          # 12 CONFIO
            ('explosion_viral', 45),     # 20 CONFIO
            ('veteran_6months', 46),     # 40 CONFIO
            ('mega_viral', 47),          # 80 CONFIO
            ('tendencia_nacional', 48),  # 250 CONFIO
            
            # Ambassador/Influencer Tiers (60-69) - Ordered by tier
            ('nano_influencer', 60),     # 4 CONFIO
            ('micro_influencer', 61),    # 8 CONFIO
            ('macro_influencer', 62),    # 20 CONFIO
            ('confio_ambassador', 63),   # 0 CONFIO (custom deal)
        ]
        
        updated = 0
        for slug, order in ordering:
            try:
                achievement = AchievementType.objects.get(slug=slug)
                if achievement.display_order != order:
                    achievement.display_order = order
                    achievement.save()
                    updated += 1
                    self.stdout.write(f'Updated {achievement.name} to order {order}')
            except AchievementType.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'Achievement {slug} not found')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'\nUpdated {updated} achievement orders')
        )
        
        # Display final ordering
        self.stdout.write('\nFinal achievement ordering:')
        categories = {
            'onboarding': 'Bienvenida',
            'verification': 'Verificación', 
            'trading': 'Intercambios',
            'payments': 'Pagos y Transacciones',
            'social': 'Comunidad',
            'ambassador': 'Embajador'
        }
        
        for cat_key, cat_name in categories.items():
            achievements = AchievementType.objects.filter(
                category=cat_key
            ).order_by('display_order')
            
            if achievements:
                self.stdout.write(f'\n{cat_name}:')
                for a in achievements:
                    self.stdout.write(f'  {a.display_order}. {a.name} - {a.confio_reward} CONFIO (${a.confio_reward/4})')