from django.db import migrations, models


def backfill_document_number_normalized(apps, schema_editor):
    IdentityVerification = apps.get_model('security', 'IdentityVerification')
    for verification in IdentityVerification.objects.all().iterator():
        raw = (verification.document_number or '').upper()
        normalized = ''.join(ch for ch in raw if ch.isalnum())
        if verification.document_number_normalized != normalized:
            IdentityVerification.objects.filter(pk=verification.pk).update(
                document_number_normalized=normalized
            )


class Migration(migrations.Migration):
    dependencies = [
        ('security', '0006_alter_integrityverdict_trigger_action'),
    ]

    operations = [
        migrations.AddField(
            model_name='identityverification',
            name='document_number_normalized',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Normalized document number used for duplicate identity detection',
                max_length=64,
            ),
        ),
        migrations.RunPython(backfill_document_number_normalized, migrations.RunPython.noop),
    ]
