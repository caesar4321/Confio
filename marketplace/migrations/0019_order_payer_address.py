from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0018_open_everywhere'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='payer_address',
            field=models.CharField(blank=True, default='', max_length=42),
        ),
    ]
