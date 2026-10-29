"""Copy the readings Bre-B and Comprar already kept into LocationReading, so
residence by device location starts from the evidence on hand. Chunked:
memory stays bounded whatever the history size."""
from django.db import migrations

CHUNK = 500


def _flush(LocationReading, rows, stamps):
    created = LocationReading.objects.bulk_create(rows)
    # created_at is auto_now_add: put each reading back on its own day.
    for reading, stamp in zip(created, stamps):
        reading.created_at = stamp
    LocationReading.objects.bulk_update(created, ['created_at'])


def backfill(apps, schema_editor):
    from security.location import country_at
    LocationReading = apps.get_model('security', 'LocationReading')
    BrebLocationCheck = apps.get_model('payment_accounts', 'BrebLocationCheck')
    MarketplaceLocationCheck = apps.get_model('marketplace', 'MarketplaceLocationCheck')
    rows, stamps = [], []

    def add(reading, stamp):
        rows.append(reading)
        stamps.append(stamp)
        if len(rows) >= CHUNK:
            _flush(LocationReading, rows, stamps)
            rows.clear()
            stamps.clear()

    breb = (BrebLocationCheck.objects.select_related('confio_account')
            .exclude(latitude=None).exclude(longitude=None).order_by('pk'))
    for check in breb.iterator(chunk_size=CHUNK):
        user_id = getattr(check.confio_account, 'user_id', None)
        if not user_id:
            continue
        # A refused attempt keeps verified=False: residence never counts it.
        add(LocationReading(
            user_id=user_id, purpose='breb', latitude=check.latitude, longitude=check.longitude,
            accuracy_m=check.accuracy_m, country=country_at(check.latitude, check.longitude),
            mocked=False if check.passed else None, verified=bool(check.passed), platform=check.platform or '',
            reading_at=check.reading_at, ip_address=check.ip_address, ip_country=check.ip_country or ''),
            check.created_at)
    for check in MarketplaceLocationCheck.objects.order_by('pk').iterator(chunk_size=CHUNK):
        # Its IP country was stored from CF-IPCountry unchecked: kept as
        # evidence, but blank here so an old row never corroborates residence.
        add(LocationReading(
            user_id=check.user_id, purpose='comprar_city', latitude=check.latitude, longitude=check.longitude,
            accuracy_m=check.accuracy_m, country=country_at(check.latitude, check.longitude),
            ip_address=check.ip_address, ip_country=''), check.created_at)
    if rows:
        _flush(LocationReading, rows, stamps)


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0029_location_readings'),
        ('payment_accounts', '0031_agenda_backfill_bank_info'),
        ('marketplace', '0013_alcohol_rules'),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
