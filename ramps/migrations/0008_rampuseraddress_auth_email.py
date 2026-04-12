from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ramps', '0007_rampuseraddress'),
    ]

    operations = [
        migrations.AddField(
            model_name='rampuseraddress',
            name='auth_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
    ]
