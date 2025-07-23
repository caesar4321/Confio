from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Country, Bank


class Command(BaseCommand):
    help = 'Populate initial country and bank data for Confío operations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete existing data before creating new data',
        )

    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write('Deleting existing data...')
            Bank.objects.all().delete()
            Country.objects.all().delete()

        with transaction.atomic():
            self.create_countries()
            self.create_banks()

        self.stdout.write(
            self.style.SUCCESS('Successfully populated bank data!')
        )

    def create_countries(self):
        """Create countries with their ID requirements based on research"""
        countries_data = [
            {
                'code': 'VE',
                'name': 'Venezuela',
                'flag_emoji': '🇻🇪',
                'currency_code': 'VES',
                'currency_symbol': 'Bs.',
                'requires_identification': True,
                'identification_name': 'Cédula',
                'identification_format': 'V-12345678',
                'account_number_length': 20,
                'supports_phone_payments': True,
                'display_order': 1,
            },
            {
                'code': 'CO',
                'name': 'Colombia',
                'flag_emoji': '🇨🇴',
                'currency_code': 'COP',
                'currency_symbol': '$',
                'requires_identification': False,  # Not needed per research
                'identification_name': 'Cédula',
                'account_number_length': 16,
                'supports_phone_payments': True,
                'display_order': 2,
            },
            {
                'code': 'AR',
                'name': 'Argentina',
                'flag_emoji': '🇦🇷',
                'currency_code': 'ARS',
                'currency_symbol': '$',
                'requires_identification': True,  # DNI required
                'identification_name': 'DNI',
                'identification_format': '12345678',
                'account_number_length': 22,  # CBU length
                'supports_phone_payments': True,
                'display_order': 3,
            },
            {
                'code': 'PE',
                'name': 'Peru',
                'flag_emoji': '🇵🇪',
                'currency_code': 'PEN',
                'currency_symbol': 'S/',
                'requires_identification': True,  # DNI required
                'identification_name': 'DNI',
                'identification_format': '12345678',
                'account_number_length': 20,
                'supports_phone_payments': True,
                'display_order': 4,
            },
            {
                'code': 'MX',
                'name': 'Mexico',
                'flag_emoji': '🇲🇽',
                'currency_code': 'MXN',
                'currency_symbol': '$',
                'requires_identification': False,  # Not needed per research
                'identification_name': 'CURP',
                'account_number_length': 18,  # CLABE length
                'supports_phone_payments': True,
                'display_order': 5,
            },
            {
                'code': 'CL',
                'name': 'Chile',
                'flag_emoji': '🇨🇱',
                'currency_code': 'CLP',
                'currency_symbol': '$',
                'requires_identification': True,  # RUT sometimes required
                'identification_name': 'RUT',
                'identification_format': '12345678-9',
                'account_number_length': 16,
                'supports_phone_payments': True,
                'display_order': 6,
            },
            {
                'code': 'BO',
                'name': 'Bolivia',
                'flag_emoji': '🇧🇴',
                'currency_code': 'BOB',
                'currency_symbol': 'Bs.',
                'requires_identification': True,  # Often required
                'identification_name': 'CI',
                'identification_format': '12345678',
                'account_number_length': 16,
                'supports_phone_payments': True,
                'display_order': 7,
            },
            {
                'code': 'EC',
                'name': 'Ecuador',
                'flag_emoji': '🇪🇨',
                'currency_code': 'USD',
                'currency_symbol': '$',
                'requires_identification': True,  # Required
                'identification_name': 'Cédula',
                'identification_format': '1234567890',
                'account_number_length': 16,
                'supports_phone_payments': False,
                'display_order': 8,
            },
        ]

        for country_data in countries_data:
            country, created = Country.objects.get_or_create(
                code=country_data['code'],
                defaults=country_data
            )
            if created:
                self.stdout.write(f'Created country: {country}')
            else:
                self.stdout.write(f'Country already exists: {country}')

    def create_banks(self):
        """Create banks for each country"""
        banks_data = {
            'VE': [  # Venezuela
                ('banco_venezuela', 'Banco de Venezuela'),
                ('banesco', 'Banesco'),
                ('mercantil', 'Mercantil'),
                ('banco_bicentenario', 'Banco Bicentenario'),
                ('banplus', 'Banplus'),
                ('banco_provincial', 'Banco Provincial'),
                ('banco_activo', 'Banco Activo'),
                ('banco_caroni', 'Banco Caroní'),
                ('banco_exterior', 'Banco Exterior'),
                ('bancamiga', 'Bancamiga'),
                ('mi_banco', 'Mi Banco'),
                ('banco_sofitasa', 'Banco Sofitasa'),
                ('banco_plaza', 'Banco Plaza'),
                ('banco_fondo_comun', 'Banco Fondo Común'),
                ('banco_agricola', 'Banco Agrícola de Venezuela'),
            ],
            'CO': [  # Colombia
                ('bancolombia', 'Bancolombia'),
                ('banco_bogota', 'Banco de Bogotá'),
                ('banco_popular', 'Banco Popular'),
                ('bbva_colombia', 'BBVA Colombia'),
                ('davivienda', 'Davivienda'),
                ('banco_caja_social', 'Banco Caja Social'),
                ('citibank_colombia', 'Citibank Colombia'),
                ('banco_av_villas', 'Banco AV Villas'),
                ('banco_colpatria', 'Banco Colpatria'),
                ('nequi', 'Nequi'),
                ('daviplata', 'DaviPlata'),
            ],
            'AR': [  # Argentina
                ('banco_nacion', 'Banco de la Nación Argentina'),
                ('banco_provincia', 'Banco Provincia'),
                ('banco_ciudad', 'Banco Ciudad'),
                ('santander_argentina', 'Santander Argentina'),
                ('bbva_argentina', 'BBVA Argentina'),
                ('banco_macro', 'Banco Macro'),
                ('banco_galicia', 'Banco Galicia'),
                ('hsbc_argentina', 'HSBC Argentina'),
                ('icbc_argentina', 'ICBC Argentina'),
                ('mercado_pago', 'Mercado Pago'),
                ('uala', 'Ualá'),
            ],
            'PE': [  # Peru
                ('bcp', 'Banco de Crédito del Perú'),
                ('bbva_peru', 'BBVA Perú'),
                ('scotiabank_peru', 'Scotiabank Perú'),
                ('interbank', 'Interbank'),
                ('banco_nacion_peru', 'Banco de la Nación'),
                ('banbif', 'BanBif'),
                ('citibank_peru', 'Citibank Perú'),
                ('yape', 'Yape'),
                ('plin', 'Plin'),
                ('tunki', 'Tunki'),
            ],
            'MX': [  # Mexico
                ('bbva_mexico', 'BBVA México'),
                ('banamex', 'Banamex'),
                ('santander_mexico', 'Santander México'),
                ('banorte', 'Banorte'),
                ('hsbc_mexico', 'HSBC México'),
                ('scotiabank_mexico', 'Scotiabank México'),
                ('inbursa', 'Inbursa'),
                ('azteca', 'Banco Azteca'),
                ('bancoppel', 'BanCoppel'),
                ('mercado_pago_mx', 'Mercado Pago'),
            ],
            'CL': [  # Chile
                ('banco_chile', 'Banco de Chile'),
                ('bci', 'BCI'),
                ('santander_chile', 'Santander Chile'),
                ('banco_estado', 'BancoEstado'),
                ('scotiabank_chile', 'Scotiabank Chile'),
                ('banco_security', 'Banco Security'),
                ('banco_falabella', 'Banco Falabella'),
                ('banco_consorcio', 'Banco Consorcio'),
                ('itau_chile', 'Itaú Chile'),
            ],
            'BO': [  # Bolivia
                ('banco_union', 'Banco Unión'),
                ('banco_nacional_bolivia', 'Banco Nacional de Bolivia'),
                ('banco_mercantil_santa_cruz', 'Banco Mercantil Santa Cruz'),
                ('banco_bisa', 'Banco BISA'),
                ('banco_sol', 'Banco Sol'),
                ('banco_economico', 'Banco Económico'),
                ('banco_ganadero', 'Banco Ganadero'),
                ('tigo_money', 'Tigo Money'),
            ],
            'EC': [  # Ecuador
                ('banco_pichincha', 'Banco Pichincha'),
                ('banco_pacifico', 'Banco del Pacífico'),
                ('banco_guayaquil', 'Banco de Guayaquil'),
                ('produbanco', 'Produbanco'),
                ('banco_internacional', 'Banco Internacional'),
                ('banco_bolivariano', 'Banco Bolivariano'),
                ('banco_austro', 'Banco del Austro'),
                ('banco_machala', 'Banco de Machala'),
            ],
        }

        for country_code, banks in banks_data.items():
            try:
                country = Country.objects.get(code=country_code)
                for bank_code, bank_name in banks:
                    bank, created = Bank.objects.get_or_create(
                        country=country,
                        code=bank_code,
                        defaults={
                            'name': bank_name,
                            'supports_checking': True,
                            'supports_savings': True,
                            'supports_payroll': False,
                            'is_active': True,
                            'display_order': 1000,
                        }
                    )
                    if created:
                        self.stdout.write(f'Created bank: {bank}')
                    
                self.stdout.write(f'✅ Processed {len(banks)} banks for {country.name}')
                
            except Country.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Country {country_code} not found!')
                )

        self.stdout.write(
            self.style.SUCCESS('✅ Bank data population completed!')
        )