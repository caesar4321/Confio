from decimal import Decimal

from django.db import migrations, models


def migrate_legacy_funding(apps, schema_editor):
    Purchase = apps.get_model('presale', 'PresalePurchase')
    SponsoredBatch = apps.get_model('blockchain', 'SponsoredBatch')
    UnifiedTransaction = apps.get_model('users', 'UnifiedTransactionTable')
    old_sources = ('direct_cusd', 'cusd_plus_redeem')
    # Prepared legacy calldata references the superseded funding shapes and
    # must never be submitted after rollout. A signed/sent batch is different:
    # it may already execute, so its domain row must stay processing for the
    # receipt confirmer to settle it. The durable batch ledger, rather than a
    # possibly-empty tx hash on the purchase, is authoritative here.
    candidates = Purchase.objects.filter(
        funding_source__in=old_sources,
        status='processing',
    )
    live_ids = SponsoredBatch.objects.filter(
        kind='presale_buy',
        source_id__in=candidates.values('id'),
        status__in=('signed', 'sent', 'confirmed'),
    ).values_list('source_id', flat=True)
    invalid_ids = list(candidates.exclude(id__in=live_ids).values_list('id', flat=True))
    Purchase.objects.filter(id__in=invalid_ids).update(status='failed')
    UnifiedTransaction.objects.filter(
        presale_purchase_id__in=invalid_ids,
        status__in=('PENDING', 'PENDING_SIG', 'SPONSORING', 'SIGNED', 'SUBMITTED'),
    ).update(
        status='FAILED',
        error_message='La cotización venció durante una actualización. Inténtalo de nuevo.',
    )
    # Terminal/history rows and still-live batches keep their accounting
    # identity, translated to the new vocabulary.
    Purchase.objects.filter(funding_source='direct_cusd').update(
        funding_source='cusd_redeem'
    )
    Purchase.objects.filter(funding_source='cusd_plus_redeem').update(
        funding_source='cusd_plus_via_cusd'
    )
    Purchase.objects.filter(cusd_amount_exact__isnull=True).update(
        cusd_amount_exact=models.F('cusd_amount')
    )


class Migration(migrations.Migration):
    dependencies = [
        ('presale', '0011_update_bsc_funding_sources'),
        ('blockchain', '0013_sponsoredbatch_idempotency'),
        ('users', '0041_add_bsc_cusd_unified_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='presalepurchase',
            name='cusd_amount_exact',
            field=models.DecimalField(
                blank=True,
                decimal_places=18,
                help_text='Exact BSC gross Confío-dollar debit; legacy rows use cusd_amount.',
                max_digits=78,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='userpresalelimit',
            name='total_purchased',
            field=models.DecimalField(
                decimal_places=18,
                default=Decimal('0'),
                max_digits=78,
            ),
        ),
        migrations.RunPython(migrate_legacy_funding, migrations.RunPython.noop),
    ]
