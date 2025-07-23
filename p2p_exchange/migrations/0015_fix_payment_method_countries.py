from django.db import migrations

def fix_payment_method_countries(apps, schema_editor):
    """Fix country assignments for all payment methods"""
    P2PPaymentMethod = apps.get_model('p2p_exchange', 'P2PPaymentMethod')
    Country = apps.get_model('users', 'Country')
    
    # More comprehensive mapping based on actual payment method names
    payment_method_mappings = [
        # Venezuela
        ('VE', ['pago_movil', 'pago_móvil', 'transferencia', 'banco_venezuela', 'banesco', 'mercantil', 'provincial']),
        # Colombia  
        ('CO', ['daviplata', 'nequi', 'movii', 'bancolombia', 'davivienda']),
        # Peru
        ('PE', ['yape', 'plin', 'bcp', 'interbank', 'bbva_peru']),
        # Panama
        ('PA', ['nequi_pa', 'banesco_pa']),
        # Argentina
        ('AR', ['mercadopago', 'mercado_pago', 'brubank', 'santander_ar']),
        # Mexico
        ('MX', ['mercadopago_mx', 'didi', 'bbva_mx', 'banamex']),
        # Chile
        ('CL', ['mercadopago_cl', 'mach', 'santander_cl']),
        # Uruguay
        ('UY', ['mercadopago_uy']),
    ]
    
    updates_count = 0
    
    for country_code, payment_method_patterns in payment_method_mappings:
        try:
            country = Country.objects.get(code=country_code)
            
            for pattern in payment_method_patterns:
                # Update payment methods matching the pattern
                updated = P2PPaymentMethod.objects.filter(
                    name__icontains=pattern,
                    country__isnull=True,  # Only update if country is not set
                    bank__isnull=True  # Only for non-bank payment methods
                ).update(country=country)
                
                if updated > 0:
                    print(f"Updated {updated} payment methods matching '{pattern}' with country {country_code}")
                    updates_count += updated
                    
        except Country.DoesNotExist:
            print(f"Country with code {country_code} not found")
    
    # Also update based on country_code field if set
    for pm in P2PPaymentMethod.objects.filter(
        country_code__isnull=False,
        country__isnull=True,
        bank__isnull=True
    ):
        try:
            country = Country.objects.get(code=pm.country_code)
            pm.country = country
            pm.save()
            updates_count += 1
            print(f"Updated {pm.name} with country {pm.country_code} based on country_code field")
        except Country.DoesNotExist:
            print(f"Country with code {pm.country_code} not found for payment method {pm.name}")
    
    print(f"Total payment methods updated: {updates_count}")

def reverse_fix_payment_method_countries(apps, schema_editor):
    """Reverse the migration"""
    P2PPaymentMethod = apps.get_model('p2p_exchange', 'P2PPaymentMethod')
    P2PPaymentMethod.objects.filter(country__isnull=False).update(country=None)

class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0014_populate_payment_method_country'),
    ]

    operations = [
        migrations.RunPython(
            fix_payment_method_countries,
            reverse_fix_payment_method_countries
        ),
    ]