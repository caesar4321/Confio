from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('users', '0017_bankinfo_provider_metadata'),
    ]

    operations = [
        migrations.CreateModel(
            name='Channel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.CharField(max_length=64, unique=True)),
                ('kind', models.CharField(choices=[('FOUNDER', 'Founder'), ('NEWS', 'News'), ('BUSINESS', 'Business'), ('SYSTEM', 'System')], max_length=32)),
                ('title', models.CharField(max_length=120)),
                ('subtitle', models.CharField(blank=True, max_length=200, null=True)),
                ('avatar_type', models.CharField(choices=[('EMOJI', 'Emoji'), ('IMAGE_URL', 'Image URL'), ('USER', 'User')], default='EMOJI', max_length=16)),
                ('avatar_value', models.CharField(blank=True, max_length=255, null=True)),
                ('subscription_mode', models.CharField(choices=[('REQUIRED', 'Required'), ('DEFAULT_ON', 'Default On'), ('OPTIONAL', 'Optional')], default='REQUIRED', max_length=16)),
                ('channel_scope', models.CharField(choices=[('GLOBAL', 'Global'), ('BUSINESS', 'Business'), ('ACCOUNT', 'Account')], default='GLOBAL', max_length=16)),
                ('owner_type', models.CharField(choices=[('SYSTEM', 'System'), ('USER', 'User'), ('BUSINESS', 'Business')], default='SYSTEM', max_length=16)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner_business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_inbox_channels', to='users.business')),
                ('owner_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_inbox_channels', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['sort_order', 'title'],
            },
        ),
        migrations.CreateModel(
            name='ReactionType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('emoji', models.CharField(max_length=16, unique=True)),
                ('label', models.CharField(max_length=32)),
                ('is_active', models.BooleanField(default=True)),
                ('is_selectable', models.BooleanField(default=True)),
                ('sort_order', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='SupportConversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('OPEN', 'Open'), ('CLOSED', 'Closed')], default='OPEN', max_length=16)),
                ('last_message_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='support_conversations', to='users.account')),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_support_conversations', to=settings.AUTH_USER_MODEL)),
                ('business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='support_conversations', to='users.business')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='support_conversations', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ContentItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('owner_type', models.CharField(choices=[('SYSTEM', 'System'), ('USER', 'User'), ('BUSINESS', 'Business')], default='SYSTEM', max_length=16)),
                ('item_type', models.CharField(choices=[('TEXT', 'Text'), ('NEWS', 'News'), ('VIDEO', 'Video')], max_length=16)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('SCHEDULED', 'Scheduled'), ('PUBLISHED', 'Published'), ('ARCHIVED', 'Archived')], default='DRAFT', max_length=16)),
                ('title', models.CharField(blank=True, max_length=255, null=True)),
                ('body', models.TextField(blank=True, null=True)),
                ('tag', models.CharField(blank=True, max_length=64, null=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('visibility_policy', models.CharField(choices=[('FROM_PUBLISH_TIME', 'From Publish Time'), ('BACKLOG', 'Backlog'), ('PINNED', 'Pinned')], default='FROM_PUBLISH_TIME', max_length=24)),
                ('notification_priority', models.CharField(choices=[('SILENT', 'Silent'), ('NORMAL', 'Normal'), ('IMPORTANT', 'Important')], default='NORMAL', max_length=16)),
                ('send_push', models.BooleanField(default=False)),
                ('send_in_app', models.BooleanField(default=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inbox_authored_content', to=settings.AUTH_USER_MODEL)),
                ('channel', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_items', to='inbox.channel')),
                ('owner_business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inbox_owned_content', to='users.business')),
                ('owner_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inbox_owned_content', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-published_at', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SupportMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sender_type', models.CharField(choices=[('USER', 'User'), ('AGENT', 'Agent'), ('SYSTEM', 'System')], max_length=16)),
                ('message_type', models.CharField(choices=[('TEXT', 'Text'), ('SYSTEM', 'System')], default='TEXT', max_length=16)),
                ('body', models.TextField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='inbox.supportconversation')),
                ('sender_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_messages', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='SupportConversationState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='states', to='inbox.supportconversation')),
                ('last_seen_message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='last_seen_in_states', to='inbox.supportmessage')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='support_conversation_states', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ContentSurface',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('surface', models.CharField(choices=[('CHANNEL', 'Channel'), ('DISCOVER', 'Discover'), ('HOME_HIGHLIGHT', 'Home Highlight')], max_length=24)),
                ('rank', models.IntegerField(blank=True, null=True)),
                ('is_pinned', models.BooleanField(default=False)),
                ('starts_at', models.DateTimeField(blank=True, null=True)),
                ('ends_at', models.DateTimeField(blank=True, null=True)),
                ('content_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='surfaces', to='inbox.contentitem')),
            ],
        ),
        migrations.CreateModel(
            name='ContentReadState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('opened_from_surface', models.CharField(blank=True, choices=[('CHANNEL', 'Channel'), ('DISCOVER', 'Discover'), ('HOME_HIGHLIGHT', 'Home Highlight')], max_length=24, null=True)),
                ('read_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_read_states', to='users.account')),
                ('business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_read_states', to='users.business')),
                ('content_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='read_states', to='inbox.contentitem')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_read_states', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ChannelMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_subscribed', models.BooleanField(default=True)),
                ('is_muted', models.BooleanField(default=False)),
                ('push_level', models.CharField(choices=[('DEFAULT', 'Default'), ('ALL', 'All'), ('IMPORTANT_ONLY', 'Important Only'), ('NONE', 'None')], default='DEFAULT', max_length=16)),
                ('in_app_level', models.CharField(choices=[('DEFAULT', 'Default'), ('ALL', 'All'), ('IMPORTANT_ONLY', 'Important Only'), ('NONE', 'None')], default='DEFAULT', max_length=16)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('unsubscribed_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='channel_memberships', to='users.account')),
                ('business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='channel_memberships', to='users.business')),
                ('channel', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='inbox.channel')),
                ('last_seen_content_item', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='last_seen_by_memberships', to='inbox.contentitem')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='channel_memberships', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ContentReaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_reactions', to='users.account')),
                ('business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_reactions', to='users.business')),
                ('content_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='inbox.contentitem')),
                ('reaction_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='content_reactions', to='inbox.reactiontype')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_reactions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name='channel',
            index=models.Index(fields=['is_active', 'sort_order'], name='inbox_channel_active_idx'),
        ),
        migrations.AddIndex(
            model_name='channel',
            index=models.Index(fields=['kind', 'is_active'], name='inbox_channel_kind_idx'),
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.CheckConstraint(
                condition=(
                    Q(owner_type='SYSTEM', owner_user__isnull=True, owner_business__isnull=True)
                    | Q(owner_type='USER', owner_user__isnull=False, owner_business__isnull=True)
                    | Q(owner_type='BUSINESS', owner_user__isnull=True, owner_business__isnull=False)
                ),
                name='inbox_channel_owner_valid',
            ),
        ),
        migrations.AddIndex(
            model_name='supportconversation',
            index=models.Index(fields=['user', 'status'], name='support_conv_user_idx'),
        ),
        migrations.AddIndex(
            model_name='supportconversation',
            index=models.Index(fields=['assigned_to', 'status'], name='support_conv_agent_idx'),
        ),
        migrations.AddConstraint(
            model_name='supportconversation',
            constraint=models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='support_conversation_context_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='supportconversation',
            constraint=models.UniqueConstraint(
                fields=('user', 'account'),
                condition=Q(account__isnull=False, business__isnull=True, status='OPEN'),
                name='support_open_user_account_uniq',
            ),
        ),
        migrations.AddConstraint(
            model_name='supportconversation',
            constraint=models.UniqueConstraint(
                fields=('user', 'business'),
                condition=Q(account__isnull=True, business__isnull=False, status='OPEN'),
                name='support_open_user_business_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='contentitem',
            index=models.Index(fields=['channel', 'status', '-published_at'], name='inbox_content_channel_idx'),
        ),
        migrations.AddIndex(
            model_name='contentitem',
            index=models.Index(fields=['status', '-published_at'], name='inbox_content_status_idx'),
        ),
        migrations.AddConstraint(
            model_name='contentitem',
            constraint=models.CheckConstraint(
                condition=(
                    Q(owner_type='SYSTEM', owner_user__isnull=True, owner_business__isnull=True)
                    | Q(owner_type='USER', owner_user__isnull=False, owner_business__isnull=True)
                    | Q(owner_type='BUSINESS', owner_user__isnull=True, owner_business__isnull=False)
                ),
                name='inbox_content_owner_valid',
            ),
        ),
        migrations.AddIndex(
            model_name='supportmessage',
            index=models.Index(fields=['conversation', 'created_at'], name='support_message_conv_idx'),
        ),
        migrations.AddConstraint(
            model_name='supportconversationstate',
            constraint=models.UniqueConstraint(fields=('conversation', 'user'), name='support_state_conversation_user_uniq'),
        ),
        migrations.AddConstraint(
            model_name='contentsurface',
            constraint=models.UniqueConstraint(fields=('content_item', 'surface'), name='inbox_surface_unique'),
        ),
        migrations.AddIndex(
            model_name='contentsurface',
            index=models.Index(fields=['surface', 'is_pinned', 'rank'], name='inbox_surface_rank_idx'),
        ),
        migrations.AddIndex(
            model_name='contentreadstate',
            index=models.Index(fields=['user', 'account', 'business', '-read_at'], name='inbox_read_ctx_idx'),
        ),
        migrations.AddIndex(
            model_name='contentreadstate',
            index=models.Index(fields=['content_item', '-read_at'], name='inbox_read_item_idx'),
        ),
        migrations.AddConstraint(
            model_name='contentreadstate',
            constraint=models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='inbox_read_context_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='contentreadstate',
            constraint=models.UniqueConstraint(
                fields=('content_item', 'user', 'account'),
                condition=Q(account__isnull=False, business__isnull=True),
                name='inbox_read_item_user_account_uniq',
            ),
        ),
        migrations.AddConstraint(
            model_name='contentreadstate',
            constraint=models.UniqueConstraint(
                fields=('content_item', 'user', 'business'),
                condition=Q(account__isnull=True, business__isnull=False),
                name='inbox_read_item_user_business_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='channelmembership',
            index=models.Index(fields=['user', 'account', 'business'], name='inbox_membership_ctx_idx'),
        ),
        migrations.AddIndex(
            model_name='channelmembership',
            index=models.Index(fields=['channel', 'is_subscribed'], name='inbox_membership_sub_idx'),
        ),
        migrations.AddIndex(
            model_name='channelmembership',
            index=models.Index(fields=['user', 'channel'], name='inbox_membership_user_idx'),
        ),
        migrations.AddConstraint(
            model_name='channelmembership',
            constraint=models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='inbox_membership_context_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='channelmembership',
            constraint=models.UniqueConstraint(
                fields=('channel', 'user', 'account'),
                condition=Q(account__isnull=False, business__isnull=True),
                name='inbox_membership_channel_user_account_uniq',
            ),
        ),
        migrations.AddConstraint(
            model_name='channelmembership',
            constraint=models.UniqueConstraint(
                fields=('channel', 'user', 'business'),
                condition=Q(account__isnull=True, business__isnull=False),
                name='inbox_membership_channel_user_business_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='contentreaction',
            index=models.Index(fields=['content_item', 'reaction_type'], name='inbox_reaction_item_idx'),
        ),
        migrations.AddConstraint(
            model_name='contentreaction',
            constraint=models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='inbox_reaction_context_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='contentreaction',
            constraint=models.UniqueConstraint(
                fields=('content_item', 'user', 'account'),
                condition=Q(account__isnull=False, business__isnull=True),
                name='inbox_reaction_item_user_account_uniq',
            ),
        ),
        migrations.AddConstraint(
            model_name='contentreaction',
            constraint=models.UniqueConstraint(
                fields=('content_item', 'user', 'business'),
                condition=Q(account__isnull=True, business__isnull=False),
                name='inbox_reaction_item_user_business_uniq',
            ),
        ),
    ]
