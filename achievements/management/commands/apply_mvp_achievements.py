"""
Reusable one-shot command to (re)apply the MVP achievements set
and ensure the referral pair (invitee + inviter) are active.

Idempotent: safe to run multiple times across environments.
"""
from django.core.management.base import BaseCommand
from decimal import Decimal

from achievements.models import AchievementType, PioneroBetaTracker


MVP_ACHIEVEMENTS = [
    # 1) Pionero Beta (on signup window)
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
    # 2) Referral (invitee): Conexión Exitosa
    {
        'slug': 'llegaste_por_influencer',
        'name': 'Conexión Exitosa',
        'description': 'Te uniste por invitación y completaste tu primera transacción',
        'category': 'social',
        'confio_reward': Decimal('4'),  # $1.00
        'display_order': 2,
        'is_active': True,
        'icon_emoji': '🎯',
    },
    # 3) First P2P trade
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
    # 4) Hodler 30 días
    {
        'slug': 'hodler_30_dias',
        'name': 'Hodler',
        'description': 'Mantén saldo por 30 días',
        'category': 'onboarding',
        'confio_reward': Decimal('12'),  # $3.00
        'display_order': 4,
        'is_active': True,
        'icon_emoji': '💎',
    },
    # 5) Ten P2P trades
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
    # 6) Referral (inviter): Referido Exitoso
    {
        'slug': 'successful_referral',
        'name': 'Referido Exitoso',
        'description': 'Invitaste a alguien que completó su primera transacción',
        'category': 'social',
        'confio_reward': Decimal('4'),  # $1.00
        'display_order': 15,
        'is_active': True,
        'icon_emoji': '🤝',
    },
]


class Command(BaseCommand):
    help = 'Reapply MVP achievements + referral pair (idempotent)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--deactivate-others', action='store_true', default=False,
            help='If set, deactivates all other achievements not in the MVP list.'
        )

    def handle(self, *args, **options):
        deactivate_others = options['deactivate_others']

        # Ensure tracker exists (do not reset counters)
        PioneroBetaTracker.get_instance()

        created, updated = 0, 0

        # Create/update the MVP set
        for data in MVP_ACHIEVEMENTS:
            slug = data['slug']
            obj, was_created = AchievementType.objects.update_or_create(
                slug=slug,
                defaults=data,
            )
            if was_created:
                created += 1
            else:
                updated += 1

        # Optionally deactivate all other achievements
        if deactivate_others:
            AchievementType.objects.exclude(slug__in=[a['slug'] for a in MVP_ACHIEVEMENTS]).update(is_active=False)

        active_count = AchievementType.objects.filter(is_active=True).count()
        total_count = AchievementType.objects.count()

        self.stdout.write(self.style.SUCCESS('=== MVP achievements applied ==='))
        self.stdout.write(f'Created: {created}, Updated: {updated}')
        self.stdout.write(f'Active now: {active_count}, Total: {total_count}')
        self.stdout.write('Slugs: ' + ', '.join(a['slug'] for a in MVP_ACHIEVEMENTS))

