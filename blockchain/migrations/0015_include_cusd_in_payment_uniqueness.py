from django.db import migrations, models
from django.db.models import Count


PAYMENT_BATCH_KINDS = (
    'pay_cusd_plus',
    'pay_cusd',
    'pay_usdt',
    'pay_confio',
)
LIVE_STATUSES = ('signed', 'sent', 'confirmed')


def assert_no_live_payment_duplicates(apps, schema_editor):
    """Refuse to hide an ambiguous payment behind the new unique index."""
    SponsoredBatch = apps.get_model('blockchain', 'SponsoredBatch')
    duplicates = list(
        SponsoredBatch.objects.using(schema_editor.connection.alias)
        .filter(
            kind__in=PAYMENT_BATCH_KINDS,
            status__in=LIVE_STATUSES,
            source_id__isnull=False,
        )
        .values('source_id')
        .annotate(batch_count=Count('id'))
        .filter(batch_count__gt=1)
        .order_by('source_id')[:20]
    )
    if duplicates:
        sample = ', '.join(
            f"source_id={row['source_id']} count={row['batch_count']}"
            for row in duplicates
        )
        raise RuntimeError(
            'Cannot enforce cpsb_unique_active_payment: multiple live payment '
            f'batches already exist ({sample}). Reconcile them before retrying.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('blockchain', '0014_send_unique_by_source'),
    ]

    operations = [
        migrations.RunPython(assert_no_live_payment_duplicates, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='sponsoredbatch',
            name='cpsb_unique_active_payment',
        ),
        migrations.AddConstraint(
            model_name='sponsoredbatch',
            constraint=models.UniqueConstraint(
                fields=('source_id',),
                condition=models.Q(
                    kind__in=PAYMENT_BATCH_KINDS,
                    status__in=LIVE_STATUSES,
                ),
                name='cpsb_unique_active_payment',
            ),
        ),
    ]
