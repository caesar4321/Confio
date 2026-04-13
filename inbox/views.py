from django.http import Http404
from django.shortcuts import render
from django.utils.text import slugify

from .models import ContentItem, ContentStatus, ContentSurfaceType


def _get_discover_queryset():
    return (
        ContentItem.objects.select_related('channel')
        .prefetch_related('surfaces')
        .filter(
            status=ContentStatus.PUBLISHED,
            published_at__isnull=False,
            surfaces__surface=ContentSurfaceType.DISCOVER,
        )
        .distinct()
        .order_by('-surfaces__is_pinned', 'surfaces__rank', '-published_at', '-created_at')
    )


def discover_feed(request):
    items = _get_discover_queryset()[:50]
    posts = []
    for item in items:
        metadata = item.metadata or {}
        blocks = metadata.get('blocks') or []
        preview_image = metadata.get('image') or next(
            (
                block.get('image')
                for block in blocks
                if block.get('type') == 'image'
                and isinstance(block.get('image'), dict)
                and block.get('image', {}).get('url')
            ),
            {},
        )
        posts.append({
            'id': item.id,
            'title': item.title or '',
            'body': item.body or '',
            'tag': item.tag or item.channel.title or '',
            'item_type': item.item_type,
            'published_at': item.published_at,
            'image_url': preview_image.get('url', '') if isinstance(preview_image, dict) else '',
            'slug': slugify(item.title or f'post-{item.id}'),
        })

    return render(request, 'discover/feed.html', {
        'posts': posts,
    })


def discover_post_detail(request, post_id, slug=None):
    try:
        item = (
            ContentItem.objects.select_related('channel')
            .prefetch_related('surfaces')
            .filter(
                id=post_id,
                status=ContentStatus.PUBLISHED,
                published_at__isnull=False,
                surfaces__surface=ContentSurfaceType.DISCOVER,
            )
            .distinct()
            .first()
        )
    except (ValueError, TypeError):
        raise Http404

    if item is None:
        raise Http404

    metadata = item.metadata or {}
    blocks = metadata.get('blocks') or []
    preview_image = metadata.get('image') or next(
        (
            block.get('image')
            for block in blocks
            if block.get('type') == 'image'
            and isinstance(block.get('image'), dict)
            and block.get('image', {}).get('url')
        ),
        {},
    )
    image_url = preview_image.get('url', '') if isinstance(preview_image, dict) else ''

    platform_links = []
    for platform, url in (metadata.get('platform_links') or {}).items():
        if url:
            platform_links.append({'platform': platform, 'url': url})

    # Build rendered blocks for the template
    rendered_blocks = []
    for block in blocks:
        block_type = block.get('type', '')
        if block_type == 'title':
            rendered_blocks.append({'type': 'title', 'text': block.get('text', '')})
        elif block_type == 'paragraph':
            rendered_blocks.append({'type': 'paragraph', 'text': block.get('text', '')})
        elif block_type == 'quote':
            rendered_blocks.append({'type': 'quote', 'text': block.get('text', '')})
        elif block_type == 'image':
            img = block.get('image', {})
            if isinstance(img, dict) and img.get('url'):
                rendered_blocks.append({
                    'type': 'image',
                    'url': img['url'],
                    'caption': img.get('caption', ''),
                })

    canonical_slug = slugify(item.title or f'post-{item.id}')
    tag = item.tag or item.channel.title or ''

    return render(request, 'discover/post_detail.html', {
        'post': {
            'id': item.id,
            'title': item.title or '',
            'body': item.body or '',
            'tag': tag,
            'item_type': item.item_type,
            'published_at': item.published_at,
            'image_url': image_url,
            'slug': canonical_slug,
            'blocks': rendered_blocks,
            'platform_links': platform_links,
        },
    })
