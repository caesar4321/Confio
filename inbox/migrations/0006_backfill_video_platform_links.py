from django.db import migrations


FIRST_VIDEO_TITLE = 'Argentina tiene uno de los Big Mac mas caros. Y eso no significa que Argentina sea rica.'
SECOND_VIDEO_TITLE = 'Confío x Didit - demo video. Ahora verificación de identidad en tiempo real'


def backfill_video_platform_links(apps, schema_editor):
    ContentItem = apps.get_model('inbox', 'ContentItem')

    first_video = ContentItem.objects.filter(title=FIRST_VIDEO_TITLE, item_type='VIDEO').first()
    if first_video:
        metadata = dict(first_video.metadata or {})
        metadata['platforms'] = ['TikTok']
        metadata['platform_links'] = {
            'TikTok': 'https://vt.tiktok.com/ZSuh2oDTr/',
        }
        metadata.pop('link', None)
        first_video.metadata = metadata
        first_video.save(update_fields=['metadata', 'updated_at'])

    second_video = ContentItem.objects.filter(title=SECOND_VIDEO_TITLE, item_type='VIDEO').first()
    if second_video:
        metadata = dict(second_video.metadata or {})
        metadata['platforms'] = ['TikTok', 'Instagram', 'YouTube']
        metadata['platform_links'] = {}
        metadata.pop('link', None)
        second_video.metadata = metadata
        second_video.save(update_fields=['metadata', 'updated_at'])


def reverse_backfill_video_platform_links(apps, schema_editor):
    ContentItem = apps.get_model('inbox', 'ContentItem')

    first_video = ContentItem.objects.filter(title=FIRST_VIDEO_TITLE, item_type='VIDEO').first()
    if first_video:
        metadata = dict(first_video.metadata or {})
        metadata['platforms'] = ['TikTok']
        metadata['link'] = 'https://vt.tiktok.com/ZSuh2oDTr/'
        metadata.pop('platform_links', None)
        first_video.metadata = metadata
        first_video.save(update_fields=['metadata', 'updated_at'])

    second_video = ContentItem.objects.filter(title=SECOND_VIDEO_TITLE, item_type='VIDEO').first()
    if second_video:
        metadata = dict(second_video.metadata or {})
        metadata['platforms'] = ['TikTok', 'Instagram', 'YouTube']
        metadata.pop('platform_links', None)
        metadata.pop('link', None)
        second_video.metadata = metadata
        second_video.save(update_fields=['metadata', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0005_update_julian_channel_branding'),
    ]

    operations = [
        migrations.RunPython(backfill_video_platform_links, reverse_backfill_video_platform_links),
    ]
