from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('inbox', '0011_contentitem_push_claimed_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='ContentPollVote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('option_id', models.CharField(max_length=64)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('content_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='poll_votes', to='inbox.contentitem')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_poll_votes', to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('content_item', 'user'), name='inbox_poll_item_user_uniq')]},
        ),
    ]
