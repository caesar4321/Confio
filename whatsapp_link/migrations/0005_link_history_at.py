from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp_link', '0004_inbox_context'),
    ]

    operations = [
        migrations.AddField(
            model_name='whatsapplink',
            name='history_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
