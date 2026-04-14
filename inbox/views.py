import re

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from .models import ContentItem, ContentStatus, ContentSurfaceType

TOP_REACTIONS_LIMIT = 3
DEFAULT_DISCOVER_AUTHOR = {
    'type': 'Organization',
    'name': 'Confío News',
    'url': 'https://confio.lat/about/confio-news/',
}
DEFAULT_DISCOVER_PUBLISHER = {
    'name': 'Confío',
    'url': 'https://confio.lat',
    'logo_url': 'https://confio.lat/images/$CONFIO.png',
}


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


def _build_author_schema(item):
    metadata = item.metadata or {}
    author_type = str(metadata.get('schema_author_type') or '').strip().lower()
    author_name = str(metadata.get('schema_author_name') or '').strip()
    author_url = str(metadata.get('schema_author_url') or '').strip()
    author_job_title = str(metadata.get('schema_author_job_title') or '').strip()

    if author_name == 'Confío News' and author_url in {'', 'https://confio.lat/discover/'}:
        author_url = DEFAULT_DISCOVER_AUTHOR['url']
    elif author_name == 'Julian Moon' and author_url in {'', 'https://confio.lat/'}:
        author_url = 'https://confio.lat/about/julian-moon/'

    if author_type == 'person' and author_name:
        return {
            'type': 'Person',
            'name': author_name,
            'url': author_url or 'https://confio.lat/about/julian-moon/',
            'job_title': author_job_title or 'Founder',
            'works_for_name': 'Confío',
            'works_for_url': 'https://confio.lat',
        }

    if author_type == 'organization' and author_name:
        return {
            'type': 'Organization',
            'name': author_name,
            'url': author_url or DEFAULT_DISCOVER_AUTHOR['url'],
        }

    if item.channel.kind == 'FOUNDER':
        return {
            'type': 'Person',
            'name': 'Julian Moon',
            'url': 'https://confio.lat/about/julian-moon/',
            'job_title': 'Founder',
            'works_for_name': 'Confío',
            'works_for_url': 'https://confio.lat',
        }

    if item.channel.kind == 'NEWS':
        return DEFAULT_DISCOVER_AUTHOR.copy()

    if item.author_user_id:
        full_name = f'{item.author_user.first_name} {item.author_user.last_name}'.strip()
        display_name = full_name or item.author_user.username or ''
        if display_name:
            return {
                'type': 'Person',
                'name': display_name,
                'url': author_url or 'https://confio.lat/about/julian-moon/',
            }

    return DEFAULT_DISCOVER_AUTHOR.copy()

FEED_PAGE_SIZE = 12


def _get_discover_queryset():
    return (
        ContentItem.objects.select_related('channel', 'author_user')
        .prefetch_related('surfaces', 'reactions__reaction_type')
        .filter(
            status=ContentStatus.PUBLISHED,
            published_at__isnull=False,
            surfaces__surface=ContentSurfaceType.DISCOVER,
        )
        .distinct()
        .order_by('-surfaces__is_pinned', 'surfaces__rank', '-published_at', '-created_at')
    )


def _build_reaction_summary(item):
    reaction_counts = {}
    for reaction in item.reactions.all():
        emoji = reaction.reaction_type.emoji
        reaction_counts[emoji] = reaction_counts.get(emoji, 0) + 1

    return [
        {'emoji': emoji, 'count': count}
        for emoji, count in sorted(
            reaction_counts.items(),
            key=lambda reaction_item: reaction_item[1],
            reverse=True,
        )[:TOP_REACTIONS_LIMIT]
    ]


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
        'reaction_summary': _build_reaction_summary(item),
        'author_schema': _build_author_schema(item),
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
            ContentItem.objects.select_related('channel', 'author_user')
            .prefetch_related('surfaces', 'reactions__reaction_type')
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

    schema_type = 'NewsArticle' if item.item_type == 'NEWS' else 'Article'

    return render(request, 'discover/post_detail.html', {
        'post': {
            'id': item.id,
            'title': item.title or '',
            'body': item.body or '',
            'tag': tag,
            'tag_color': tag_color,
            'item_type': item.item_type,
            'schema_type': schema_type,
            'published_at': item.published_at,
            'updated_at': item.updated_at,
            'image_url': image_url,
            'slug': canonical_slug,
            'blocks': rendered_blocks,
            'platform_links': platform_links,
            'reaction_summary': _build_reaction_summary(item),
            'author_schema': _build_author_schema(item),
        },
        'publisher_schema': DEFAULT_DISCOVER_PUBLISHER,
    })
