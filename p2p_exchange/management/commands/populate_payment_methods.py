from django.core.management.base import BaseCommand
from p2p_exchange.models import P2PPaymentMethod
from users.models import Bank, Country


class Command(BaseCommand):
    help = 'Populate P2P payment methods from banks and add fintech solutions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing payment methods instead of skipping them',
        )

    def handle(self, *args, **options):
        update_existing = options['update_existing']
        created_count = 0
        updated_count = 0
        
        self.stdout.write("🚀 Starting P2P payment method population...")

        # Step 1: Create bank-based payment methods from existing banks
        banks = Bank.objects.filter(is_active=True).select_related('country')
        
        for bank in banks:
            payment_method_name = f"bank_{bank.code.lower()}"
            display_name = bank.name
            country_code = bank.country.code
            
            payment_method, created = P2PPaymentMethod.objects.get_or_create(
                name=payment_method_name,
                country_code=country_code,
                defaults={
                    'display_name': display_name,
                    'provider_type': 'bank',
                    'is_active': True,
                    'icon': 'bank',
                    'bank': bank,
                    'description': f"Transferencia bancaria via {bank.name}",
                    'requires_phone': False,
                    'requires_email': False,
                    'requires_account_number': True,
                    'display_order': 100,  # Banks get lower priority than fintech
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(f"✅ Created bank payment method: {display_name} ({country_code})")
            elif update_existing:
                payment_method.display_name = display_name
                payment_method.bank = bank
                payment_method.save()
                updated_count += 1
                self.stdout.write(f"🔄 Updated bank payment method: {display_name} ({country_code})")

        # Step 2: Add fintech and digital wallet solutions
        fintech_solutions = [
            # Venezuela
            {
                'name': 'pago_movil',
                'display_name': 'Pago Móvil',
                'provider_type': 'fintech',
                'country_code': 'VE',
                'icon': 'smartphone',
                'description': 'Sistema de pagos móviles de Venezuela',
                'requires_phone': True,
                'requires_email': False,
                'requires_account_number': True,
                'display_order': 10,
                'is_active': True,
            },
            # Colombia
            {
                'name': 'nequi',
                'display_name': 'Nequi',
                'provider_type': 'fintech',
                'country_code': 'CO',
                'icon': 'smartphone',
                'description': 'Billetera digital de Bancolombia',
                'requires_phone': True,
                'requires_email': False,
                'requires_account_number': False,
                'display_order': 10,
                'is_active': True,
            },
            {
                'name': 'daviplata',
                'display_name': 'DaviPlata',
                'provider_type': 'fintech',
                'country_code': 'CO',
                'icon': 'smartphone',
                'description': 'Billetera digital del Banco Davivienda',
                'requires_phone': True,
                'requires_email': False,
                'requires_account_number': False,
                'display_order': 11,
                'is_active': True,
            },
            # Peru
            {
                'name': 'yape',
                'display_name': 'Yape',
                'provider_type': 'fintech',
                'country_code': 'PE',
                'icon': 'smartphone',
                'description': 'Billetera digital del BCP',
                'requires_phone': True,
                'requires_email': False,
                'requires_account_number': False,
                'display_order': 10,
                'is_active': True,
            },
            {
                'name': 'plin',
                'display_name': 'Plin',
                'provider_type': 'fintech',
                'country_code': 'PE',
                'icon': 'smartphone',
                'description': 'Billetera digital interbancaria',
                'requires_phone': True,
                'requires_email': False,
                'requires_account_number': False,
                'display_order': 11,
                'is_active': True,
            },
            {
                'name': 'tunki',
                'display_name': 'Tunki',
                'provider_type': 'fintech',
                'country_code': 'PE',
                'icon': 'smartphone',
                'description': 'Billetera digital de Interbank',
                'requires_phone': True,
                'requires_email': False,
                'requires_account_number': False,
                'display_order': 12,
                'is_active': True,
            },
            # Argentina
            {
                'name': 'mercado_pago',
                'display_name': 'Mercado Pago',
                'provider_type': 'fintech',
                'country_code': 'AR',
                'icon': 'smartphone',
                'description': 'Billetera digital y sistema de pagos',
                'requires_phone': False,
                'requires_email': True,
                'requires_account_number': False,
                'display_order': 10,
                'is_active': True,
            },
            {
                'name': 'uala',
                'display_name': 'Ualá',
                'provider_type': 'fintech',
                'country_code': 'AR',
                'icon': 'credit-card',
                'description': 'Tarjeta prepaga y billetera digital',
                'requires_phone': False,
                'requires_email': True,
                'requires_account_number': True,
                'display_order': 11,
                'is_active': True,
            },
            # United States
            {
                'name': 'zelle',
                'display_name': 'Zelle',
                'provider_type': 'fintech',
                'country_code': 'US',
                'icon': 'credit-card',
                'description': 'Digital payment network',
                'requires_phone': True,
                'requires_email': True,
                'requires_account_number': False,
                'display_order': 10,
                'is_active': True,
            },
            {
                'name': 'venmo',
                'display_name': 'Venmo',
                'provider_type': 'fintech',
                'country_code': 'US',
                'icon': 'smartphone',
                'description': 'Digital wallet owned by PayPal',
                'requires_phone': False,
                'requires_email': True,
                'requires_account_number': False,
                'display_order': 11,
                'is_active': True,
            },
            {
                'name': 'cash_app',
                'display_name': 'Cash App',
                'provider_type': 'fintech',
                'country_code': 'US',
                'icon': 'smartphone',
                'description': 'Digital payment app by Square',
                'requires_phone': False,
                'requires_email': True,
                'requires_account_number': False,
                'display_order': 12,
                'is_active': True,
            },
            # Mexico
            {
                'name': 'oxxo_pay',
                'display_name': 'OXXO Pay',
                'provider_type': 'cash',
                'country_code': 'MX',
                'icon': 'dollar-sign',
                'description': 'Pagos en efectivo en tiendas OXXO',
                'requires_phone': False,
                'requires_email': False,
                'requires_account_number': True,
                'display_order': 20,
                'is_active': True,
            },
            {
                'name': 'spei',
                'display_name': 'SPEI',
                'provider_type': 'bank',
                'country_code': 'MX',
                'icon': 'bank',
                'description': 'Sistema de Pagos Electrónicos Interbancarios',
                'requires_phone': False,
                'requires_email': False,
                'requires_account_number': True,
                'display_order': 100,
                'is_active': True,
            },
        ]

        # Note: Global payment methods removed per user requirements
        # All payment methods must be country-specific
        global_methods = []

        # Process fintech solutions (no global methods)
        all_methods = fintech_solutions
        
        for method_data in all_methods:
            payment_method, created = P2PPaymentMethod.objects.get_or_create(
                name=method_data['name'],
                country_code=method_data['country_code'],
                defaults=method_data
            )
            
            if created:
                created_count += 1
                country_label = f" ({method_data['country_code']})" if method_data['country_code'] else " (Global)"
                self.stdout.write(f"✅ Created fintech payment method: {method_data['display_name']}{country_label}")
            elif update_existing:
                for key, value in method_data.items():
                    if key not in ['name', 'country_code']:  # Don't update the unique identifiers
                        setattr(payment_method, key, value)
                payment_method.save()
                updated_count += 1
                country_label = f" ({method_data['country_code']})" if method_data['country_code'] else " (Global)"
                self.stdout.write(f"🔄 Updated fintech payment method: {method_data['display_name']}{country_label}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Payment method population completed!\n"
                f"📊 Summary:\n"
                f"   - Created: {created_count} new payment methods\n"
                f"   - Updated: {updated_count} existing payment methods\n"
                f"   - Total methods in database: {P2PPaymentMethod.objects.count()}\n"
            )
        )

        # Show some statistics
        bank_methods = P2PPaymentMethod.objects.filter(provider_type='bank').count()
        fintech_methods = P2PPaymentMethod.objects.filter(provider_type='fintech').count()
        cash_methods = P2PPaymentMethod.objects.filter(provider_type='cash').count()
        other_methods = P2PPaymentMethod.objects.filter(provider_type='other').count()
        
        self.stdout.write(
            f"📈 Payment method breakdown:\n"
            f"   - Banks: {bank_methods}\n"
            f"   - Fintech/Digital Wallets: {fintech_methods}\n"
            f"   - Cash/Physical: {cash_methods}\n"
            f"   - Other: {other_methods}\n"
        )