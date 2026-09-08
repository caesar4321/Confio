from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('security', '0009_registrationrestriction'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AlterField(
            model_name='integrityverdict', name='user',
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE,
                related_name='integrity_verdicts', null=True, blank=True,
                help_text='User being verified'),
        ),
    ]
