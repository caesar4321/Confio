from django.core.management.base import BaseCommand
from users.models import AchievementType


class Command(BaseCommand):
    help = 'Create initial achievement types for the Confío achievement system'

    def handle(self, *args, **options):
        achievements_data = [
            # 🏠 BIENVENIDA (ONBOARDING) - Priority 1 - Keep total under $1
            {
                'slug': 'welcome_signup',
                'name': 'Pionero Beta',
                'description': 'Únete a Confío durante la fase beta - Exclusivo para los primeros usuarios',
                'category': 'onboarding',
                'icon_emoji': '🚀',
                'confio_reward': 1,  # $0.25 - Minimal for beta users
                'display_order': 1
            },
            {
                'slug': 'identity_verified',
                'name': 'Verificado',
                'description': 'Completa la verificación de identidad',
                'category': 'verification',
                'icon_emoji': '🛡️',
                'confio_reward': 2,  # $0.50 - Blockchain reduces need
                'display_order': 2
            },
            
            # 💱 INTERCAMBIOS (TRADING) - Priority 2 - HIGHEST VALUE ACTIONS
            {
                'slug': 'first_p2p_trade',
                'name': 'Primera Compra',
                'description': 'Completa tu primer intercambio P2P exitoso',
                'category': 'trading',
                'icon_emoji': '🔄',
                'confio_reward': 8,  # $2 - Critical for business, high reward
                'display_order': 10
            },
            {
                'slug': 'trading_10',
                'name': '10 Intercambios',
                'description': 'Completa 10 intercambios P2P exitosos',
                'category': 'trading',
                'icon_emoji': '📊',
                'confio_reward': 20,  # $5 - Power user, generates fees
                'display_order': 11
            },
            {
                'slug': 'frequent_trader',
                'name': 'Trader Frecuente',
                'description': 'Completa 50 intercambios P2P exitosos',
                'category': 'trading',
                'icon_emoji': '📈',
                'confio_reward': 40,  # $10 - Very valuable user
                'display_order': 12
            },
            {
                'slug': 'volume_trader_1k',
                'name': 'Trader $1,000',
                'description': 'Alcanza $1,000 USD en volumen total de intercambios',
                'category': 'trading',
                'icon_emoji': '💰',
                'confio_reward': 50,  # $12.50 - High volume = high fees collected
                'display_order': 13
            },
            {
                'slug': 'volume_trader_10k',
                'name': 'Trader $10,000',
                'description': 'Alcanza $10,000 USD en volumen total de intercambios',
                'category': 'trading',
                'icon_emoji': '💎',
                'confio_reward': 200,  # $50 - Whale user, extremely valuable
                'display_order': 14
            },
            
            # 💸 PAGOS Y TRANSACCIONES (PAYMENTS) - Priority 3 - Keep simple actions minimal
            {
                'slug': 'first_send',
                'name': 'Primer Envío',
                'description': 'Envía cUSD por primera vez',
                'category': 'payments',
                'icon_emoji': '📤',
                'confio_reward': 1,  # $0.25 - Very easy action
                'display_order': 20
            },
            {
                'slug': 'first_receive',
                'name': 'Primera Recepción',
                'description': 'Recibe cUSD por primera vez',
                'category': 'payments',
                'icon_emoji': '📥',
                'confio_reward': 1,  # $0.25 - Passive action
                'display_order': 21
            },
            {
                'slug': 'first_payment',
                'name': 'Primer Pago',
                'description': 'Realiza tu primer pago a un comercio',
                'category': 'payments',
                'icon_emoji': '🛍️',
                'confio_reward': 2,  # $0.50 - Merchant adoption
                'display_order': 22
            },
            {
                'slug': 'traveler',
                'name': 'Viajero',
                'description': 'Envía dinero a 3 países diferentes',
                'category': 'payments',
                'icon_emoji': '🌍',
                'confio_reward': 10,  # $2.50 - International usage valuable
                'display_order': 23
            },
            {
                'slug': 'merchant_10',
                'name': 'Comerciante',
                'description': 'Acepta 10 pagos como negocio',
                'category': 'payments',
                'icon_emoji': '🏪',
                'confio_reward': 20,  # $5 - Merchants drive adoption
                'display_order': 24
            },
            
            # 🤝 COMUNIDAD (COMMUNITY) - Priority 4
            {
                'slug': 'hodler_30',
                'name': 'Hodler',
                'description': 'Mantén cUSD en tu cuenta por 30 días',
                'category': 'social',
                'icon_emoji': '💎',
                'confio_reward': 12,  # $3 - Liquidity valuable
                'display_order': 30
            },
            {
                'slug': 'veteran_6months',
                'name': 'Veterano',
                'description': 'Mantén tu cuenta activa por 6 meses',
                'category': 'social',
                'icon_emoji': '🎖️',
                'confio_reward': 40,  # $10 - Long-term retention
                'display_order': 31
            },
            
            # 🎯 TIKTOK VIRAL - Priority 5 - SCALED DOWN
            {
                'slug': 'influencer_referred',
                'name': 'Llegaste por Influencer',
                'description': 'Te registraste siguiendo a un influencer de TikTok',
                'category': 'social',
                'icon_emoji': '🎯',
                'confio_reward': 4,  # $1 - Part of CPI strategy
                'display_order': 32
            },
            {
                'slug': 'primera_viral',
                'name': 'Primera Viral',
                'description': 'Tu TikTok sobre Confío alcanzó 1,000 visualizaciones',
                'category': 'social',
                'icon_emoji': '🎬',
                'confio_reward': 4,  # $1 - Scaled down from $5
                'display_order': 33
            },
            {
                'slug': 'explosion_viral',
                'name': 'Explosión Viral',
                'description': 'Tu TikTok sobre Confío alcanzó 10,000 visualizaciones',
                'category': 'social',
                'icon_emoji': '💥',
                'confio_reward': 20,  # $5 - Scaled down from $25
                'display_order': 34
            },
            {
                'slug': 'mega_viral',
                'name': 'Mega Viral',
                'description': 'Tu TikTok sobre Confío alcanzó 100,000 visualizaciones',
                'category': 'social',
                'icon_emoji': '🚀',
                'confio_reward': 80,  # $20 - Major reach
                'display_order': 35
            },
            {
                'slug': 'tendencia_nacional',
                'name': 'Tendencia Nacional',
                'description': 'Tu TikTok sobre Confío alcanzó 1,000,000 visualizaciones',
                'category': 'social',
                'icon_emoji': '🏆',
                'confio_reward': 250,  # $62.50 - Massive viral impact
                'display_order': 36
            },
            
            # 👑 INFLUENCER TIERS - Priority 6 (Least common)
            {
                'slug': 'nano_influencer',
                'name': 'Nano-Influencer',
                'description': 'Trae entre 1-10 referidos que completen su registro',
                'category': 'ambassador',
                'icon_emoji': '🌱',
                'confio_reward': 4,  # $1 - Per influencer referral already
                'display_order': 40
            },
            {
                'slug': 'micro_influencer',
                'name': 'Micro-Influencer',
                'description': 'Trae entre 11-100 referidos activos - Badge especial desbloqueado',
                'category': 'ambassador',
                'icon_emoji': '⭐',
                'confio_reward': 8,  # $2 - Bonus for scale
                'display_order': 41
            },
            {
                'slug': 'macro_influencer',
                'name': 'Macro-Influencer',
                'description': 'Trae entre 101-1000 referidos - Perks exclusivos',
                'category': 'ambassador',
                'icon_emoji': '💫',
                'confio_reward': 20,  # $5 - Major growth driver
                'display_order': 42
            },
            {
                'slug': 'confio_ambassador',
                'name': 'Embajador Confío',
                'description': 'Trae 1000+ referidos - Programa de partnership personalizado',
                'category': 'ambassador',
                'icon_emoji': '👑',
                'confio_reward': 0,  # Custom deal at this level
                'display_order': 43
            }
        ]

        created_count = 0
        updated_count = 0

        for achievement_data in achievements_data:
            achievement_type, created = AchievementType.objects.get_or_create(
                slug=achievement_data['slug'],
                defaults=achievement_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created achievement: {achievement_type.name}')
                )
            else:
                # Update existing achievement if data has changed
                updated = False
                for field, value in achievement_data.items():
                    if field != 'slug' and getattr(achievement_type, field) != value:
                        setattr(achievement_type, field, value)
                        updated = True
                
                if updated:
                    achievement_type.save()
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'Updated achievement: {achievement_type.name}')
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nCompleted! Created {created_count} new achievements, updated {updated_count} existing achievements.'
            )
        )