from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0019_unifiedtransactiontable_ramp_transaction'),
        ('inbox', '0008_remove_seeded_editorial_content'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentPlatformClick',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('surface', models.CharField(choices=[('CHANNEL', 'Channel'), ('DISCOVER', 'Discover'), ('HOME_HIGHLIGHT', 'Home Highlight')], max_length=24)),
                ('platform', models.CharField(choices=[('TIKTOK', 'TikTok'), ('INSTAGRAM', 'Instagram'), ('YOUTUBE', 'YouTube')], max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_platform_clicks', to='users.account')),
                ('business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_platform_clicks', to='users.business')),
                ('content_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='platform_clicks', to='inbox.contentitem')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_platform_clicks', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name='contentplatformclick',
            index=models.Index(fields=['content_item', 'platform', '-created_at'], name='inbox_click_item_platform_idx'),
        ),
        migrations.AddIndex(
            model_name='contentplatformclick',
            index=models.Index(fields=['user', '-created_at'], name='inbox_click_user_idx'),
        ),
        migrations.AddIndex(
            model_name='contentplatformclick',
            index=models.Index(fields=['surface', 'platform', '-created_at'], name='inbox_click_surface_idx'),
        ),
        migrations.AddConstraint(
            model_name='contentplatformclick',
            constraint=models.CheckConstraint(
                condition=(Q(account__isnull=False, business__isnull=True) | Q(account__isnull=True, business__isnull=False)),
                name='inbox_platform_click_context_valid',
            ),
        ),
    ]
