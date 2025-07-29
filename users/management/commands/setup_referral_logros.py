"""
Setup referral system integrated with Logros
Based on AI consensus: Single entry point, dual reward
"""
from django.core.management.base import BaseCommand
from users.models import AchievementType
from decimal import Decimal


class Command(BaseCommand):
    help = 'Setup referral achievement that works for both influencer and friend invites'

    def handle(self, *args, **options):
        # Achievement for the INVITED user (referred)
        achievement, created = AchievementType.objects.update_or_create(
            slug='llegaste_por_influencer',
            defaults={
                'name': 'Conexión Exitosa',
                'description': 'Te uniste por invitación y completaste tu primera transacción',
                'category': 'social',
                'confio_reward': Decimal('4'),
                'display_order': 2,
                'is_active': True,
                'icon_emoji': '🎯',
            }
        )
        
        # Achievement for the INVITER (referrer)
        referrer_achievement, _ = AchievementType.objects.update_or_create(
            slug='successful_referral',
            defaults={
                'name': 'Referido Exitoso',
                'description': 'Invitaste a alguien que completó su primera transacción',
                'category': 'social',
                'confio_reward': Decimal('4'),
                'display_order': 15,  # Show after main achievements
                'is_active': True,
                'icon_emoji': '🤝',
            }
        )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Referral system integrated with Logros!\n\n'
                f'How it works:\n'
                f'1. New user enters @username or phone during referral window\n'
                f'2. System tracks referral relationship (one-time only)\n'
                f'3. When new user completes first transaction:\n'
                f'   - INVITED user gets "Conexión Exitosa" (I was invited) + 4 CONFIO\n'
                f'   - INVITER gets "Referido Exitoso" (I invited someone) + 4 CONFIO\n\n'
                f'Clear difference:\n'
                f'• Conexión Exitosa = YOU were invited by someone\n'
                f'• Referido Exitoso = YOU invited someone else\n\n'
                f'Benefits:\n'
                f'- Single unified flow (no separate paths)\n'
                f'- Quality control (requires real transaction)\n'
                f'- Network effect (both sides rewarded)\n'
                f'- Data tracking (influencer vs friend metrics)\n\n'
                f'Total CAC impact: $1 per successful referral (both sides)'
            )
        )