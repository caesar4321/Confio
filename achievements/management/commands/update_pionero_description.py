"""
Update Pionero Beta achievement description to include mystery benefits
"""
from django.core.management.base import BaseCommand
from achievements.models import AchievementType


class Command(BaseCommand):
    help = 'Update Pionero Beta achievement with mystery benefits messaging'

    def handle(self, *args, **options):
        try:
            pionero = AchievementType.objects.get(slug='pionero_beta')
            
            # Update description with mystery benefits
            pionero.name = 'Pionero Beta 🚀'
            pionero.description = 'Primeros 10,000 usuarios - Acceso exclusivo a beneficios futuros 🎁'
            pionero.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated Pionero Beta achievement:\n'
                    f'Name: {pionero.name}\n'
                    f'Description: {pionero.description}'
                )
            )
            
            # Show possible future benefits in comments (for internal reference)
            future_benefits = """
            Possible Future Benefits for Pionero Beta holders:
            - Priority access to presale rounds
            - Exclusive NFT badge (transferable)
            - Early access to new features
            - Special Discord/Telegram channel
            - Governance voting rights
            - Future airdrops eligibility
            - Partner merchant discounts
            - VIP customer support
            """
            
            self.stdout.write(
                self.style.WARNING(future_benefits)
            )
            
        except AchievementType.DoesNotExist:
            self.stdout.write(
                self.style.ERROR('Pionero Beta achievement not found')
            )