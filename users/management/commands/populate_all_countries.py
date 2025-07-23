from django.core.management.base import BaseCommand
from users.models import Country

class Command(BaseCommand):
    help = 'Populate all LATAM countries, Brazil, US, and Spain'

    def handle(self, *args, **options):
        self.stdout.write('Populating all countries...')
        
        # Comprehensive list of countries
        countries_data = [
            # South America
            ('AR', 'Argentina', '🇦🇷', 'ARS', '$', True, 'DNI', r'^\d{7,8}$'),
            ('BO', 'Bolivia', '🇧🇴', 'BOB', 'Bs', True, 'CI', r'^\d{6,8}[-\w]?$'),
            ('BR', 'Brazil', '🇧🇷', 'BRL', 'R$', True, 'CPF', r'^\d{11}$'),
            ('CL', 'Chile', '🇨🇱', 'CLP', '$', True, 'RUT', r'^\d{7,8}-[\dkK]$'),
            ('CO', 'Colombia', '🇨🇴', 'COP', '$', True, 'CC', r'^\d{8,10}$'),
            ('EC', 'Ecuador', '🇪🇨', 'USD', '$', True, 'CI', r'^\d{10}$'),
            ('PY', 'Paraguay', '🇵🇾', 'PYG', '₲', True, 'CI', r'^\d{6,8}$'),
            ('PE', 'Peru', '🇵🇪', 'PEN', 'S/', True, 'DNI', r'^\d{8}$'),
            ('UY', 'Uruguay', '🇺🇾', 'UYU', '$', True, 'CI', r'^\d{7,8}$'),
            ('VE', 'Venezuela', '🇻🇪', 'VES', 'Bs', True, 'CI', r'^[VE]\d{7,8}$'),
            
            # Central America
            ('CR', 'Costa Rica', '🇨🇷', 'CRC', '₡', True, 'Cédula', r'^\d{9,10}$'),
            ('SV', 'El Salvador', '🇸🇻', 'USD', '$', True, 'DUI', r'^\d{8}-\d$'),
            ('GT', 'Guatemala', '🇬🇹', 'GTQ', 'Q', True, 'DPI', r'^\d{13}$'),
            ('HN', 'Honduras', '🇭🇳', 'HNL', 'L', True, 'DNI', r'^\d{4}-\d{4}-\d{5}$'),
            ('NI', 'Nicaragua', '🇳🇮', 'NIO', 'C$', True, 'Cédula', r'^\d{13}[A-Z]$'),
            ('PA', 'Panama', '🇵🇦', 'PAB', 'B/', True, 'Cédula', r'^[\d-]+$'),
            
            # Caribbean
            ('DO', 'Dominican Republic', '🇩🇴', 'DOP', 'RD$', True, 'Cédula', r'^\d{11}$'),
            ('PR', 'Puerto Rico', '🇵🇷', 'USD', '$', False, '', ''),
            
            # North America
            ('MX', 'Mexico', '🇲🇽', 'MXN', '$', True, 'CURP', r'^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$'),
            ('US', 'United States', '🇺🇸', 'USD', '$', False, '', ''),
            
            # Europe
            ('ES', 'Spain', '🇪🇸', 'EUR', '€', True, 'DNI/NIE', r'^[XYZ]?\d{7,8}[A-Z]$'),
            ('PT', 'Portugal', '🇵🇹', 'EUR', '€', True, 'CC/BI', r'^\d{8,9}$'),
            
            # Africa - High stablecoin adoption
            ('NG', 'Nigeria', '🇳🇬', 'NGN', '₦', True, 'NIN', r'^\d{11}$'),
            ('KE', 'Kenya', '🇰🇪', 'KES', 'KSh', True, 'National ID', r'^\d{7,8}$'),
            ('ZA', 'South Africa', '🇿🇦', 'ZAR', 'R', True, 'ID Number', r'^\d{13}$'),
            ('GH', 'Ghana', '🇬🇭', 'GHS', '₵', True, 'Ghana Card', r'^GHA-\d{9}-\d$'),
            
            # Asia - High stablecoin adoption
            ('PH', 'Philippines', '🇵🇭', 'PHP', '₱', True, 'UMID', r'^\d{12}$'),
            ('IN', 'India', '🇮🇳', 'INR', '₹', True, 'Aadhaar', r'^\d{12}$'),
            ('ID', 'Indonesia', '🇮🇩', 'IDR', 'Rp', True, 'KTP', r'^\d{16}$'),
            ('VN', 'Vietnam', '🇻🇳', 'VND', '₫', True, 'CMND', r'^\d{9,12}$'),
            ('TH', 'Thailand', '🇹🇭', 'THB', '฿', True, 'ID Card', r'^\d{13}$'),
            ('TR', 'Turkey', '🇹🇷', 'TRY', '₺', True, 'TC Kimlik', r'^\d{11}$'),
            ('AE', 'United Arab Emirates', '🇦🇪', 'AED', 'د.إ', True, 'Emirates ID', r'^\d{15}$'),
            
            # Eastern Europe - Growing crypto adoption
            ('UA', 'Ukraine', '🇺🇦', 'UAH', '₴', True, 'Passport', r'^[А-Я]{2}\d{6}$'),
            ('PL', 'Poland', '🇵🇱', 'PLN', 'zł', True, 'PESEL', r'^\d{11}$'),
        ]
        
        created_count = 0
        updated_count = 0
        
        for code, name, flag, currency_code, currency_symbol, requires_id, id_name, id_format in countries_data:
            country, created = Country.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'flag_emoji': flag,
                    'currency_code': currency_code,
                    'currency_symbol': currency_symbol,
                    'requires_identification': requires_id,
                    'identification_name': id_name,
                    'identification_format': id_format,
                    'account_number_length': 20,  # Default
                    'supports_phone_payments': True,
                    'is_active': True,
                    'display_order': 100  # Default order
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(f'Created: {name} ({code})')
            else:
                # Update existing country data
                country.name = name
                country.flag_emoji = flag
                country.currency_code = currency_code
                country.currency_symbol = currency_symbol
                country.requires_identification = requires_id
                country.identification_name = id_name
                country.identification_format = id_format
                country.is_active = True
                country.save()
                updated_count += 1
                self.stdout.write(f'Updated: {name} ({code})')
        
        # Set display order for common countries
        priority_countries = {
            'VE': 1,   # Venezuela
            'CO': 2,   # Colombia
            'AR': 3,   # Argentina
            'MX': 4,   # Mexico
            'PE': 5,   # Peru
            'CL': 6,   # Chile
            'BR': 7,   # Brazil
            'EC': 8,   # Ecuador
            'US': 9,   # United States
            'ES': 10,  # Spain
            'NG': 11,  # Nigeria - High stablecoin adoption
            'PH': 12,  # Philippines - High crypto adoption
            'IN': 13,  # India - Large market
            'KE': 14,  # Kenya - M-Pesa pioneer
            'TR': 15,  # Turkey - High inflation, crypto adoption
            'DO': 16,  # Dominican Republic
            'PA': 17,  # Panama
            'CR': 18,  # Costa Rica
            'UY': 19,  # Uruguay
            'PT': 20,  # Portugal
        }
        
        for code, order in priority_countries.items():
            Country.objects.filter(code=code).update(display_order=order)
        
        self.stdout.write(self.style.SUCCESS(
            f'\nSuccessfully populated countries: {created_count} created, {updated_count} updated'
        ))
        
        # Show total
        total_countries = Country.objects.filter(is_active=True).count()
        self.stdout.write(f'Total active countries in database: {total_countries}')