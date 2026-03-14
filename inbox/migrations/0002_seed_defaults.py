from django.db import migrations


REACTIONS = [
    ('🔥', 'Fire', 10),
    ('🙌', 'Celebrate', 20),
    ('😍', 'Love It', 30),
    ('🤯', 'Mind Blown', 40),
    ('💡', 'Insightful', 50),
    ('😎', 'Cool', 60),
    ('💪', 'Strong', 70),
    ('👀', 'Watching', 80),
    ('😢', 'Sad', 90),
    ('❤️', 'Heart', 100),
]


def seed_defaults(apps, schema_editor):
    Channel = apps.get_model('inbox', 'Channel')
    ReactionType = apps.get_model('inbox', 'ReactionType')
    Account = apps.get_model('users', 'Account')
    ChannelMembership = apps.get_model('inbox', 'ChannelMembership')

    julian_channel, _ = Channel.objects.update_or_create(
        slug='julian',
        defaults={
            'kind': 'FOUNDER',
            'title': 'Julian Moon',
            'subtitle': 'Founder · @julianmoonluna',
            'avatar_type': 'EMOJI',
            'avatar_value': '🇰🇷',
            'subscription_mode': 'REQUIRED',
            'channel_scope': 'GLOBAL',
            'owner_type': 'SYSTEM',
            'is_active': True,
            'sort_order': 10,
        },
    )
    confio_news_channel, _ = Channel.objects.update_or_create(
        slug='confio-news',
        defaults={
            'kind': 'NEWS',
            'title': 'Confío News',
            'subtitle': 'Novedades del producto',
            'avatar_type': 'EMOJI',
            'avatar_value': '💚',
            'subscription_mode': 'REQUIRED',
            'channel_scope': 'GLOBAL',
            'owner_type': 'SYSTEM',
            'is_active': True,
            'sort_order': 20,
        },
    )

    for emoji, label, sort_order in REACTIONS:
        ReactionType.objects.update_or_create(
            emoji=emoji,
            defaults={
                'label': label,
                'is_active': True,
                'is_selectable': True,
                'sort_order': sort_order,
            },
        )

    required_channels = [julian_channel, confio_news_channel]
    for account in Account.objects.select_related('user', 'business').all():
        membership_kwargs = {'user': account.user}
        if account.account_type == 'business' and account.business_id:
            membership_kwargs['business'] = account.business
        else:
            membership_kwargs['account'] = account

        for channel in required_channels:
            ChannelMembership.objects.get_or_create(
                channel=channel,
                **membership_kwargs,
                defaults={'is_subscribed': True},
            )


def reverse_seed_defaults(apps, schema_editor):
    Channel = apps.get_model('inbox', 'Channel')
    ReactionType = apps.get_model('inbox', 'ReactionType')

    Channel.objects.filter(slug__in=['julian', 'confio-news']).delete()
    ReactionType.objects.filter(emoji__in=[emoji for emoji, _, _ in REACTIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_defaults, reverse_seed_defaults),
    ]
