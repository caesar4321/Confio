from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0019_fundinginstruction_display_value')]

    operations = [
        migrations.AddField('accountactivation', 'opening_failures', models.PositiveIntegerField(default=0)),
        migrations.AddField('accountactivation', 'opening_error', models.CharField(max_length=40, blank=True, default='')),
        migrations.AddField('accountactivation', 'next_opening_retry_at', models.DateTimeField(null=True, blank=True)),
    ]
