from decimal import Decimal as D

from django.db import migrations

# Known cities with centres for GPS matching. None is live: an admin flips a
# city once its first stores are listed (fake door until then). Delivery
# estimates exist only where the partner is known (Bolivia: Yango Envío,
# ~15 Bs); elsewhere checkout says "a coordinar".
BO = dict(country_code='BO', currency_code='BOB', delivery_estimate=D('15.00'),
          delivery_partner='Yango Envío')
VE = dict(country_code='VE', currency_code='VES', delivery_estimate=None, delivery_partner='')
AR = dict(country_code='AR', currency_code='ARS', delivery_estimate=None, delivery_partner='')

CITIES = [
    (BO, 'La Paz', D('-16.500000'), D('-68.150000'), 30),
    (BO, 'El Alto', D('-16.504700'), D('-68.163300'), 15),
    (BO, 'Santa Cruz de la Sierra', D('-17.783300'), D('-63.182100'), 40),
    (BO, 'Cochabamba', D('-17.393500'), D('-66.157000'), 30),
    (VE, 'Caracas', D('10.480600'), D('-66.903600'), 35),
    (VE, 'Maracaibo', D('10.654500'), D('-71.640600'), 30),
    (VE, 'Valencia', D('10.162000'), D('-68.007700'), 30),
    (VE, 'Barquisimeto', D('10.067800'), D('-69.347400'), 25),
    (VE, 'Maracay', D('10.246900'), D('-67.595800'), 25),
    (VE, 'Ciudad Guayana', D('8.353400'), D('-62.641300'), 30),
    (VE, 'Barcelona', D('10.133300'), D('-64.683300'), 25),
    (VE, 'Maturín', D('9.745700'), D('-63.183200'), 25),
    (VE, 'Mérida', D('8.589700'), D('-71.156100'), 20),
    (VE, 'San Cristóbal', D('7.766900'), D('-72.225000'), 20),
    (VE, 'Cumaná', D('10.456400'), D('-64.167500'), 20),
    (AR, 'Buenos Aires', D('-34.603700'), D('-58.381600'), 40),
    (AR, 'La Plata', D('-34.921400'), D('-57.954400'), 15),
    (AR, 'Córdoba', D('-31.420100'), D('-64.188800'), 30),
    (AR, 'Rosario', D('-32.944200'), D('-60.650500'), 25),
    (AR, 'Mendoza', D('-32.889500'), D('-68.845800'), 25),
    (AR, 'San Miguel de Tucumán', D('-26.808300'), D('-65.217600'), 20),
    (AR, 'Mar del Plata', D('-38.005500'), D('-57.542600'), 20),
    (AR, 'Salta', D('-24.782100'), D('-65.423200'), 20),
    (AR, 'Santa Fe', D('-31.610700'), D('-60.697300'), 20),
    (AR, 'Neuquén', D('-38.951600'), D('-68.059100'), 20),
]


def seed(apps, schema_editor):
    City = apps.get_model('marketplace', 'MarketplaceCity')
    for base, name, lat, lng, radius in CITIES:
        City.objects.get_or_create(
            country_code=base['country_code'], city=name,
            defaults={'currency_code': base['currency_code'], 'is_live': False,
                      'delivery_estimate': base['delivery_estimate'],
                      'delivery_partner': base['delivery_partner'],
                      'latitude': lat, 'longitude': lng, 'radius_km': radius})


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
