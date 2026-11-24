from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('assistant', '0015_gmail_calendar_and_kinds')]

    operations = [
        migrations.CreateModel(
            name='GmailGrant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=64, unique=True)),
                ('granted_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
