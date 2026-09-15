from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('security', '0010_integrityverdict_nullable_user')]

    operations = [
        migrations.AddField(
            model_name='identityverification',
            name='is_additional_document',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    'A second identity document of the same person (e.g. a passport for a '
                    'local-money rail). Hidden from the default manager: every existing KYC '
                    'reader, Koywe included, keeps seeing only the primary document.'
                ),
            ),
        ),
    ]
