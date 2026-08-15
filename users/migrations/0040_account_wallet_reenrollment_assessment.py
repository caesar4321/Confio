from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0039_retiredwalletaddress'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='wallet_reenrollment_assessment',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Background chain-safety assessment for legacy wallet reenrollment',
            ),
        ),
        migrations.AddField(
            model_name='account',
            name='wallet_reenrollment_assessed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='wallet_reenrollment_assessment_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='wallet_reenrollment_assessment_lease',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
