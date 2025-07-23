# Generated manually to populate currency_code for existing offers

from django.db import migrations

def populate_offer_currency(apps, schema_editor):
    """Populate currency_code for existing offers based on country_code"""
    P2POffer = apps.get_model('p2p_exchange', 'P2POffer')
    
    # Country to currency mapping
    COUNTRY_TO_CURRENCY = {
        'VE': 'VES',  # Venezuela
        'CO': 'COP',  # Colombia
        'AR': 'ARS',  # Argentina
        'PE': 'PEN',  # Peru
        'CL': 'CLP',  # Chile
        'BR': 'BRL',  # Brazil
        'MX': 'MXN',  # Mexico
        'US': 'USD',  # United States
        'DO': 'DOP',  # Dominican Republic
        'PA': 'USD',  # Panama (uses USD)
        'EC': 'USD',  # Ecuador (uses USD)
        'SV': 'USD',  # El Salvador (uses USD)
        'BO': 'BOB',  # Bolivia
        'UY': 'UYU',  # Uruguay
        'PY': 'PYG',  # Paraguay
        'GT': 'GTQ',  # Guatemala
        'HN': 'HNL',  # Honduras
        'NI': 'NIO',  # Nicaragua
        'CR': 'CRC',  # Costa Rica
        'CU': 'CUP',  # Cuba
        'JM': 'JMD',  # Jamaica
        'TT': 'TTD',  # Trinidad and Tobago
    }
    
    # Update all offers
    for offer in P2POffer.objects.all():
        currency = COUNTRY_TO_CURRENCY.get(offer.country_code, 'USD')
        offer.currency_code = currency
        offer.save()
        print(f"Updated offer {offer.id}: {offer.country_code} -> {currency}")

def reverse_populate_offer_currency(apps, schema_editor):
    """Reverse migration - clear currency_code"""
    P2POffer = apps.get_model('p2p_exchange', 'P2POffer')
    P2POffer.objects.update(currency_code='')

class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0017_add_currency_to_offer'),
    ]

    operations = [
        migrations.RunPython(
            populate_offer_currency,
            reverse_populate_offer_currency
        ),
    ]