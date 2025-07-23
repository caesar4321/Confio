from django.db import migrations

def populate_payment_method_country(apps, schema_editor):
    """Populate country field for payment methods based on country_code"""
    P2PPaymentMethod = apps.get_model('p2p_exchange', 'P2PPaymentMethod')
    Country = apps.get_model('users', 'Country')
    
    # Map payment methods to their countries
    payment_method_countries = {
        'CO': ['daviplata', 'nequi', 'movii'],  # Colombia
        'VE': ['pago_movil_ve', 'transferencia_ve'],  # Venezuela
        'PE': ['yape', 'plin'],  # Peru
        'PA': ['nequi_pa'],  # Panama
        'AR': ['mercadopago_ar', 'brubank'],  # Argentina
        'MX': ['mercadopago_mx', 'didi'],  # Mexico
        'CL': ['mercadopago_cl', 'mach'],  # Chile
        'UY': ['mercadopago_uy'],  # Uruguay
    }
    
    for country_code, payment_methods in payment_method_countries.items():
        try:
            country = Country.objects.get(code=country_code)
            
            # Update payment methods for this country
            for pm_name in payment_methods:
                P2PPaymentMethod.objects.filter(
                    name__icontains=pm_name,
                    country__isnull=True,  # Only update if country is not set
                    bank__isnull=True  # Only for non-bank payment methods
                ).update(country=country)
                
        except Country.DoesNotExist:
            print(f"Country with code {country_code} not found")

def reverse_populate_payment_method_country(apps, schema_editor):
    """Reverse the migration"""
    P2PPaymentMethod = apps.get_model('p2p_exchange', 'P2PPaymentMethod')
    P2PPaymentMethod.objects.filter(country__isnull=False).update(country=None)

class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0013_add_country_to_payment_method'),
        ('users', '0010_populate_payment_method_for_existing_bankinfo'),
    ]

    operations = [
        migrations.RunPython(
            populate_payment_method_country,
            reverse_populate_payment_method_country
        ),
    ]