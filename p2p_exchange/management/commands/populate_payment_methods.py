from django.core.management.base import BaseCommand
from p2p_exchange.models import P2PPaymentMethod


class Command(BaseCommand):
    help = 'Populate P2P payment methods with common Venezuelan payment options'

    def handle(self, *args, **options):
        payment_methods = [
            {
                'name': 'banco_venezuela',
                'display_name': 'Banco de Venezuela',
                'icon': 'bank',
                'is_active': True,
            },
            {
                'name': 'mercantil',
                'display_name': 'Mercantil',
                'icon': 'bank',
                'is_active': True,
            },
            {
                'name': 'banesco',
                'display_name': 'Banesco',
                'icon': 'bank',
                'is_active': True,
            },
            {
                'name': 'pago_movil',
                'display_name': 'Pago Móvil',
                'icon': 'smartphone',
                'is_active': True,
            },
            {
                'name': 'efectivo',
                'display_name': 'Efectivo',
                'icon': 'dollar-sign',
                'is_active': True,
            },
            {
                'name': 'zelle',
                'display_name': 'Zelle',
                'icon': 'credit-card',
                'is_active': True,
            },
            {
                'name': 'paypal',
                'display_name': 'PayPal',
                'icon': 'credit-card',
                'is_active': True,
            },
            {
                'name': 'binance_pay',
                'display_name': 'Binance Pay',
                'icon': 'credit-card',
                'is_active': True,
            },
        ]

        created_count = 0
        for method_data in payment_methods:
            payment_method, created = P2PPaymentMethod.objects.get_or_create(
                name=method_data['name'],
                defaults={
                    'display_name': method_data['display_name'],
                    'icon': method_data['icon'],
                    'is_active': method_data['is_active'],
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created payment method: {payment_method.display_name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Payment method already exists: {payment_method.display_name}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} new payment methods')
        )