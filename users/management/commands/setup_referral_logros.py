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
        # Update the existing achievement to be more generic
        achievement, created = AchievementType.objects.update_or_create(
            slug='llegaste_por_influencer',
            defaults={
                'name': 'Conexión Exitosa',
                'description': 'Fuiste invitado y completaste tu primera transacción',
                'category': 'social',
                'confio_reward': Decimal('4'),  # Both sides get 4 CONFIO
                'display_order': 2,
                'is_active': True,
                'icon_emoji': '🎯',
            }
        )
        
        # Also create/update a hidden achievement for the referrer
        referrer_achievement, _ = AchievementType.objects.update_or_create(
            slug='successful_referral',
            defaults={
                'name': 'Referido Exitoso',
                'description': 'Tu invitado completó su primera transacción',
                'category': 'social',
                'confio_reward': Decimal('4'),  # Referrer also gets 4 CONFIO
                'display_order': 100,  # Hidden from main list
                'is_active': True,
                'icon_emoji': '🤝',
            }
        )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Referral system integrated with Logros!\n\n'
                f'How it works:\n'
                f'1. New user enters TikTok username OR friend code during onboarding\n'
                f'2. System tracks referral relationship (one-time only)\n'
                f'3. When new user completes first transaction:\n'
                f'   - New user gets "Conexión Exitosa" + 4 CONFIO\n'
                f'   - Referrer gets automatic 4 CONFIO reward\n\n'
                f'Benefits:\n'
                f'- Single unified flow (no separate paths)\n'
                f'- Quality control (requires real transaction)\n'
                f'- Network effect (both sides rewarded)\n'
                f'- Data tracking (influencer vs friend metrics)\n\n'
                f'Total CAC impact: $1 per successful referral (both sides)'
            )
        )