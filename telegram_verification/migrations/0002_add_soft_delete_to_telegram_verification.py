# Generated by Django 4.2.20 on 2025-07-02 18:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('telegram_verification', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramverification',
            name='deleted_at',
            field=models.DateTimeField(blank=True, help_text='Soft delete timestamp', null=True),
        ),
        migrations.AddField(
            model_name='telegramverification',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
