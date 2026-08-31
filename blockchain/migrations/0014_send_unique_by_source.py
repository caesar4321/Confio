from django.db import migrations, models


SEND_KINDS = (
    'send_cusd_plus', 'send_redeem', 'send_usdt', 'send_confio',
    'send_unwrap_cusd', 'send_wrap_cusd', 'send_cusd',
    'send_cusd_redeem', 'send_mixed_wrap_cusd', 'send_mixed_cusd',
    'send_mixed_cusd_redeem',
)


def assert_no_active_send_duplicates(apps, schema_editor):
    """Fail before DDL with the exact conflicting source ids.

    Silently choosing a winner would be unsafe for money movement.  An
    operator must reconcile the chain receipts and terminalize the losing
    rows before retrying this migration.
    """
    SponsoredBatch = apps.get_model('blockchain', 'SponsoredBatch')
    duplicates = list(
        SponsoredBatch.objects.filter(
            kind__in=SEND_KINDS,
            source_id__isnull=False,
            status__in=('signed', 'sent', 'confirmed'),
        )
        .values('source_id')
        .annotate(row_count=models.Count('id'))
        .filter(row_count__gt=1)
        .order_by('source_id')[:50]
    )
    if duplicates:
        detail = ', '.join(
            f"source_id={row['source_id']} ({row['row_count']} rows)"
            for row in duplicates
        )
        raise RuntimeError(
            'Cannot add cpsb_unique_active_send until active duplicate '
            f'SponsoredBatch rows are reconciled: {detail}'
        )


class Migration(migrations.Migration):
    dependencies = [('blockchain', '0013_sponsoredbatch_idempotency')]

    operations = [
        migrations.RunPython(
            assert_no_active_send_duplicates,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='sponsoredbatch',
            constraint=models.UniqueConstraint(
                fields=('source_id',),
                condition=models.Q(
                    kind__in=SEND_KINDS,
                    source_id__isnull=False,
                    status__in=('signed', 'sent', 'confirmed'),
                ),
                name='cpsb_unique_active_send',
            ),
        ),
    ]
