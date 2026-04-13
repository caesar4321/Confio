import re

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from .models import ContentItem, ContentStatus, ContentSurfaceType


def _render_markdown_links(text):
    """Convert markdown links and preserve app-style line spacing."""
    escaped = escape(text)
    # Replace markdown links — we escaped the HTML, so angle brackets in URLs
    # are &lt;/&gt; which won't appear in real URLs. Re-match on the escaped text.
    def _replace(m):
        label = m.group(1)
        url = m.group(2)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'

    linked = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _replace, escaped)
    return mark_safe(linked.replace('\n', '<br><br>'))

FEED_PAGE_SIZE = 12


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


def _build_post_card(item):
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
    tag = item.tag or item.channel.title or ''
    tag_color = str(
        metadata.get('tag_color')
        or {
            'producto': '#1DB587', 'kyc': '#8B5CF6', 'preventa': '#F97316',
            'mercado': '#F59E0B', 'video': '#FF4444',
        }.get(tag.strip().lower())
        or {'VIDEO': '#FF4444', 'NEWS': '#F59E0B', 'TEXT': '#1DB587'}.get(item.item_type, '#1DB587')
    )
    return {
        'id': item.id,
        'title': item.title or '',
        'body': item.body or '',
        'tag': tag,
        'tag_color': tag_color,
        'item_type': item.item_type,
        'published_at': item.published_at,
        'image_url': preview_image.get('url', '') if isinstance(preview_image, dict) else '',
        'slug': slugify(item.title or f'post-{item.id}'),
    }


def discover_feed(request):
    queryset = _get_discover_queryset()
    paginator = Paginator(queryset, FEED_PAGE_SIZE)

    page_number = request.GET.get('page', 1)
    try:
        page_number = int(page_number)
    except (ValueError, TypeError):
        page_number = 1

    page = paginator.get_page(page_number)
    posts = [_build_post_card(item) for item in page]

    return render(request, 'discover/feed.html', {
        'posts': posts,
        'page': page,
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
            platform_links.append({'platform': platform.lower(), 'url': url})

    rendered_blocks = []
    for block in blocks:
        block_type = block.get('type', '')
        if block_type == 'title':
            rendered_blocks.append({'type': 'title', 'text': _render_markdown_links(block.get('text', ''))})
        elif block_type == 'paragraph':
            rendered_blocks.append({'type': 'paragraph', 'text': _render_markdown_links(block.get('text', ''))})
        elif block_type == 'quote':
            rendered_blocks.append({'type': 'quote', 'text': _render_markdown_links(block.get('text', ''))})
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
    tag_color = str(
        metadata.get('tag_color')
        or {
            'producto': '#1DB587', 'kyc': '#8B5CF6', 'preventa': '#F97316',
            'mercado': '#F59E0B', 'video': '#FF4444',
        }.get(tag.strip().lower())
        or {'VIDEO': '#FF4444', 'NEWS': '#F59E0B', 'TEXT': '#1DB587'}.get(item.item_type, '#1DB587')
    )

    return render(request, 'discover/post_detail.html', {
        'post': {
            'id': item.id,
            'title': item.title or '',
            'body': item.body or '',
            'tag': tag,
            'tag_color': tag_color,
            'item_type': item.item_type,
            'published_at': item.published_at,
            'image_url': image_url,
            'slug': canonical_slug,
            'blocks': rendered_blocks,
            'platform_links': platform_links,
        },
    })
