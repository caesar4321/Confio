from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def seed_message_content(apps, schema_editor):
    Channel = apps.get_model('inbox', 'Channel')
    ContentItem = apps.get_model('inbox', 'ContentItem')
    ContentSurface = apps.get_model('inbox', 'ContentSurface')
    Account = apps.get_model('users', 'Account')
    SupportConversation = apps.get_model('inbox', 'SupportConversation')
    SupportMessage = apps.get_model('inbox', 'SupportMessage')

    now = timezone.now()

    julian_channel = Channel.objects.get(slug='julian')
    confio_news_channel = Channel.objects.get(slug='confio-news')

    seeded_items = [
        (
            julian_channel,
            'VIDEO',
            'Argentina tiene uno de los Big Mac mas caros. Y eso no significa que Argentina sea rica.',
            None,
            None,
            now - timedelta(hours=9),
            {
                'link': 'https://vt.tiktok.com/ZSuh2oDTr/',
                'platforms': ['TikTok'],
            },
        ),
        (
            julian_channel,
            'VIDEO',
            'Confío x Didit - demo video. Ahora verificación de identidad en tiempo real',
            None,
            None,
            now - timedelta(days=1),
            {
                'platforms': ['TikTok', 'Instagram', 'YouTube'],
            },
        ),
        (
            julian_channel,
            'TEXT',
            None,
            'Estamos a punto de cerrar el trato con los bancos locales. Vienen en 2-4 semanas.',
            None,
            now - timedelta(days=3),
            {},
        ),
        (
            confio_news_channel,
            'NEWS',
            'Integracion Koywe completada',
            'On/off-ramp confirmado para Argentina, Bolivia, Colombia, Mexico y Peru. El retiro a cuenta bancaria llega en 2-4 semanas.',
            'Producto',
            now - timedelta(hours=2),
            {},
        ),
        (
            confio_news_channel,
            'NEWS',
            'Confío x Didit: verificación en tiempo real',
            'Verifica tu identidad en menos de 60 segundos. Sin papeles, sin esperas.',
            'KYC',
            now - timedelta(days=1),
            {},
        ),
        (
            confio_news_channel,
            'NEWS',
            'Fase 1-1 activa: $CONFIO a $0.20',
            'La primera fase de preventa esta abierta. Se parte de los primeros 10,000 usuarios fundadores.',
            'Preventa',
            now - timedelta(days=5),
            {},
        ),
    ]

    created_items = []
    for channel, item_type, title, body, tag, published_at, metadata in seeded_items:
        item, _ = ContentItem.objects.update_or_create(
            channel=channel,
            item_type=item_type,
            title=title,
            body=body,
            published_at=published_at,
            defaults={
                'status': 'PUBLISHED',
                'tag': tag,
                'visibility_policy': 'BACKLOG',
                'notification_priority': 'NORMAL',
                'send_in_app': True,
                'send_push': False,
                'metadata': metadata,
                'owner_type': 'SYSTEM',
            },
        )
        created_items.append(item)

    for item in created_items:
        ContentSurface.objects.update_or_create(
            content_item=item,
            surface='CHANNEL',
            defaults={'is_pinned': False},
        )

    for item in created_items[3:]:
        ContentSurface.objects.update_or_create(
            content_item=item,
            surface='DISCOVER',
            defaults={'is_pinned': False},
        )

    for account in Account.objects.select_related('user', 'business').all():
        lookup = {'user': account.user, 'status': 'OPEN'}
        if account.account_type == 'business' and account.business_id:
            lookup.update({'business': account.business, 'account': None})
        else:
            lookup.update({'account': account, 'business': None})

        conversation, _ = SupportConversation.objects.get_or_create(**lookup, defaults={})
        if not conversation.messages.exists():
            message = SupportMessage.objects.create(
                conversation=conversation,
                sender_type='SYSTEM',
                message_type='TEXT',
                body='Hola, somos el equipo de Confío. ¿En qué podemos ayudarte hoy?',
                metadata={},
            )
            conversation.last_message_at = message.created_at
            conversation.save(update_fields=['last_message_at', 'updated_at'])


def reverse_seed_message_content(apps, schema_editor):
    ContentItem = apps.get_model('inbox', 'ContentItem')
    SupportMessage = apps.get_model('inbox', 'SupportMessage')

    ContentItem.objects.filter(
        title__in=[
            'Argentina tiene uno de los Big Mac mas caros. Y eso no significa que Argentina sea rica.',
            'Confío x Didit - demo video. Ahora verificación de identidad en tiempo real',
            'Integracion Koywe completada',
            'Confío x Didit: verificación en tiempo real',
            'Fase 1-1 activa: $CONFIO a $0.20',
        ]
    ).delete()
    ContentItem.objects.filter(
        body='Estamos a punto de cerrar el trato con los bancos locales. Vienen en 2-4 semanas.'
    ).delete()
    SupportMessage.objects.filter(
        body='Hola, somos el equipo de Confío. ¿En qué podemos ayudarte hoy?'
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0003_channelmembership_timestamps'),
    ]

    operations = [
        migrations.RunPython(seed_message_content, reverse_seed_message_content),
    ]
