from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content_ingestion', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aicontextdocument',
            name='category',
            field=models.CharField(
                choices=[
                    ('preferences', 'Preferences'),
                    ('facts', 'Facts'),
                    ('decisions', 'Decisions'),
                    ('content-rules', 'Content rules'),
                    ('decision-log', 'Decision log'),
                    ('meeting-notes', 'Meeting notes'),
                    ('videos', 'Videos'),
                    ('weekly-reports', 'Weekly reports'),
                    ('social-stats', 'Social stats'),
                    ('strategy', 'Strategy'),
                    ('legal', 'Legal'),
                    ('user-reports', 'User reports'),
                    ('other', 'Other'),
                ],
                max_length=32,
            ),
        ),
    ]
