from django.contrib.syndication.views import Feed
from django.template.defaultfilters import truncatewords
from django.utils.feedgenerator import Rss201rev2Feed
from django.utils.html import strip_tags
from django.utils.text import slugify

from .models import ContentItem, ContentStatus, ContentSurfaceType


class DiscoverFeed(Feed):
    feed_type = Rss201rev2Feed
    title = 'Confío Descubrir'
    link = '/discover'
    description = 'Noticias, guias y videos sobre dolares digitales, stablecoins y pagos en Latinoamerica.'
    feed_url = '/discover/feed.xml'

    def items(self):
        return (
            ContentItem.objects.filter(
                status=ContentStatus.PUBLISHED,
                published_at__isnull=False,
                surfaces__surface=ContentSurfaceType.DISCOVER,
            )
            .distinct()
            .order_by('-published_at', '-created_at')[:50]
        )

    def item_title(self, item):
        return item.title or f'Confío post {item.id}'

    def item_description(self, item):
        return truncatewords(strip_tags(item.body or ''), 40)

    def item_link(self, item):
        slug = slugify(item.title or f'post-{item.id}')
        return f'/discover/{item.id}/{slug}'

    def item_pubdate(self, item):
        return item.published_at or item.created_at
