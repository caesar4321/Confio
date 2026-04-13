from django.contrib.sitemaps import Sitemap
from django.utils.text import slugify

from .models import ContentItem, ContentStatus, ContentSurfaceType


class DiscoverSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7
    protocol = 'https'

    def items(self):
        return (
            ContentItem.objects.filter(
                status=ContentStatus.PUBLISHED,
                published_at__isnull=False,
                surfaces__surface=ContentSurfaceType.DISCOVER,
            )
            .distinct()
            .order_by('-published_at')
        )

    def lastmod(self, obj):
        return obj.updated_at or obj.published_at

    def location(self, obj):
        slug = slugify(obj.title or f'post-{obj.id}')
        return f'/discover/{obj.id}/{slug}/'
