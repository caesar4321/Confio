from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0009_contentplatformclick'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentPlatformClickDailyStat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('surface', models.CharField(choices=[('CHANNEL', 'Channel'), ('DISCOVER', 'Discover'), ('HOME_HIGHLIGHT', 'Home Highlight')], max_length=24)),
                ('platform', models.CharField(choices=[('TIKTOK', 'TikTok'), ('INSTAGRAM', 'Instagram'), ('YOUTUBE', 'YouTube')], max_length=16)),
                ('click_count', models.PositiveIntegerField(default=0)),
                ('unique_user_count', models.PositiveIntegerField(default=0)),
                ('aggregated_at', models.DateTimeField(auto_now=True)),
                ('content_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='platform_click_daily_stats', to='inbox.contentitem')),
            ],
        ),
        migrations.AddIndex(
            model_name='contentplatformclickdailystat',
            index=models.Index(fields=['content_item', 'platform', '-date'], name='ibox_clk_day_item_idx'),
        ),
        migrations.AddIndex(
            model_name='contentplatformclickdailystat',
            index=models.Index(fields=['surface', 'platform', '-date'], name='ibox_clk_day_surf_idx'),
        ),
        migrations.AddIndex(
            model_name='contentplatformclickdailystat',
            index=models.Index(fields=['-date', '-click_count'], name='ibox_clk_day_date_idx'),
        ),
        migrations.AddConstraint(
            model_name='contentplatformclickdailystat',
            constraint=models.UniqueConstraint(fields=('date', 'content_item', 'surface', 'platform'), name='ibox_clk_day_unique'),
        ),
    ]
