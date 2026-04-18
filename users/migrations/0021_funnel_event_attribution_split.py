from django.db import migrations, models


def backfill_funnel_attribution(apps, schema_editor):
    FunnelEvent = apps.get_model('users', 'FunnelEvent')
    FunnelDailyRollup = apps.get_model('users', 'FunnelDailyRollup')

    FunnelEvent.objects.filter(event_name='invite_submitted').update(
        source_type='send_invite',
        channel='escrow',
    )
    FunnelEvent.objects.filter(event_name='whatsapp_share_tapped').update(
        source_type='send_invite',
        channel='whatsapp',
    )
    FunnelEvent.objects.filter(event_name='invite_claimed').update(
        source_type='send_invite',
        channel='claim',
    )
    FunnelEvent.objects.filter(event_name='invite_link_clicked').update(
        event_name='referral_link_clicked',
        source_type='referral_link',
    )

    FunnelDailyRollup.objects.filter(event_name='invite_submitted').update(
        source_type='send_invite',
        channel='escrow',
    )
    FunnelDailyRollup.objects.filter(event_name='whatsapp_share_tapped').update(
        source_type='send_invite',
        channel='whatsapp',
    )
    FunnelDailyRollup.objects.filter(event_name='invite_claimed').update(
        source_type='send_invite',
        channel='claim',
    )
    FunnelDailyRollup.objects.filter(event_name='invite_link_clicked').update(
        event_name='referral_link_clicked',
        source_type='referral_link',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0020_funnel_event_tables'),
    ]

    operations = [
        migrations.AddField(
            model_name='funnelevent',
            name='source_type',
            field=models.CharField(blank=True, db_index=True, help_text="Attribution bucket such as 'send_invite', 'referral_link', or 'install_referrer'.", max_length=32),
        ),
        migrations.AddField(
            model_name='funnelevent',
            name='channel',
            field=models.CharField(blank=True, db_index=True, help_text="Acquisition/share channel such as 'whatsapp', 'instagram', 'youtube', or 'tiktok'.", max_length=32),
        ),
        migrations.AddField(
            model_name='funneldailyrollup',
            name='source_type',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='funneldailyrollup',
            name='channel',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddIndex(
            model_name='funnelevent',
            index=models.Index(fields=['source_type', 'event_name', 'created_at'], name='users_funne_source__d89_idx'),
        ),
        migrations.AddIndex(
            model_name='funnelevent',
            index=models.Index(fields=['channel', 'event_name', 'created_at'], name='users_funne_channel_6a0_idx'),
        ),
        migrations.AddIndex(
            model_name='funneldailyrollup',
            index=models.Index(fields=['event_name', 'source_type', 'channel', '-date'], name='users_funne_ev_so__750_idx'),
        ),
        migrations.RunPython(backfill_funnel_attribution, noop_reverse),
        migrations.RemoveConstraint(
            model_name='funneldailyrollup',
            name='unique_funnel_rollup',
        ),
        migrations.AddConstraint(
            model_name='funneldailyrollup',
            constraint=models.UniqueConstraint(
                fields=('date', 'event_name', 'country', 'platform', 'source_type', 'channel'),
                name='unique_funnel_rollup',
            ),
        ),
    ]
