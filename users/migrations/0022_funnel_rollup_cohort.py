from django.db import migrations, models


def backfill_rollup_cohort(apps, schema_editor):
    FunnelDailyRollup = apps.get_model('users', 'FunnelDailyRollup')

    FunnelDailyRollup.objects.filter(source_type='send_invite').update(
        cohort='send_invite',
    )
    FunnelDailyRollup.objects.filter(source_type='referral_link').update(
        cohort='unknown',
    )
    FunnelDailyRollup.objects.filter(source_type='').update(
        cohort='unknown',
    )
    FunnelDailyRollup.objects.exclude(
        source_type__in=['', 'send_invite', 'referral_link'],
    ).update(
        cohort=models.F('source_type'),
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0021_funnel_event_attribution_split'),
    ]

    operations = [
        migrations.AddField(
            model_name='funneldailyrollup',
            name='cohort',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text=(
                    "Low-cardinality funnel cohort, e.g. 'creator_julianmoonluna', "
                    "'user_driven', 'send_invite', or 'unknown'."
                ),
                max_length=32,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_rollup_cohort, noop_reverse),
        migrations.RemoveConstraint(
            model_name='funneldailyrollup',
            name='unique_funnel_rollup',
        ),
        migrations.AddConstraint(
            model_name='funneldailyrollup',
            constraint=models.UniqueConstraint(
                fields=('date', 'event_name', 'country', 'platform', 'source_type', 'channel', 'cohort'),
                name='unique_funnel_rollup',
            ),
        ),
        migrations.AddIndex(
            model_name='funneldailyrollup',
            index=models.Index(
                fields=['event_name', 'source_type', 'cohort', '-date'],
                name='users_funne_ev_so_co_5c6_idx',
            ),
        ),
    ]
