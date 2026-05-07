from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ramps', '0008_rampuseraddress_auth_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='rampuseraddress',
            name='address_neighborhood',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='rampuseraddress',
            name='economic_activity',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
