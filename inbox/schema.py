import graphene
import logging
import os
from django.db import transaction
from .polls import validate_poll_metadata
from django.db.models import Case, Count, F, IntegerField, Q, Value, When, Window
from django.db.models.functions import RowNumber
from django.conf import settings
from django.utils import timezone
from graphql import GraphQLError
from graphql_jwt.decorators import login_required

from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account, Business
from security.s3_utils import build_s3_key, generate_presigned_post, public_s3_url

from .models import (
    AvatarType,
    Channel,
    ChannelKind,
    ChannelScope,
    ChannelMembership,
    ContentReaction,
    ContentPollVote,
    ContentPlatformClick,
    ContentItem,
    ContentPlatformType,
    ContentSurfaceType,
    OwnerType,
    ContentStatus,
    CommunityComment,
    CommunityCommentReport,
    CommunityPostReport,
    CommunityReviewStatus,
    ReactionType,
    SupportConversation,
    SupportConversationState,
    SupportMessage,
    VisibilityPolicy,
)
from . import community, profile_pictures
from .community import author_display_name
from .official import all_official_channel_ids, official_channel_ids
from .push_service import send_support_reply_push, send_support_staff_push

logger = logging.getLogger(__name__)

# Descubrir's three feeds (Para ti / Oficial / Comunidad). "for_you" mixes
# everything; "official" is institutional posts in channels passing the live
# Oficial rule (inbox.official); "community" is anything a user wrote — empty
# until user posting ships.
DISCOVER_FEED_SECTIONS = ('for_you', 'official', 'community')
# Publisher-type filters from 2df03d94. Installed builds may still send them
# (a chip picked before the deploy), so they keep filtering by channel kind.
LEGACY_DISCOVER_SECTION_KINDS = {
    'confio': (ChannelKind.FOUNDER, ChannelKind.NEWS, ChannelKind.SYSTEM),
    'institutions': (ChannelKind.INSTITUTION,),
    'businesses': (ChannelKind.BUSINESS,),
}
# A user's post never borrows its channel's verification, even inside an
# Oficial channel (e.g. a member post on an institution's board).
USER_AUTHORED = Q(owner_type=OwnerType.USER) | Q(channel__owner_type=OwnerType.USER)

# Publisher type on each item, independent of which feed it was read from.
DISCOVER_KIND_SECTION = {
    ChannelKind.FOUNDER: 'confio',
    ChannelKind.NEWS: 'confio',
    ChannelKind.SYSTEM: 'confio',
    ChannelKind.INSTITUTION: 'institutions',
    ChannelKind.BUSINESS: 'businesses',
}

DISCOVER_TAG_COLOR_MAP = {
    'producto': '#1DB587',
    'kyc': '#7C3AED',
    'preventa': '#F97316',
    'mercado': '#F59E0B',
    'video': '#FF4444',
}


def humanize_relative(dt):
    if not dt:
        return ''

    delta = timezone.now() - dt
    if delta.total_seconds() < 300:
        return 'Ahora'
    if delta.total_seconds() < 3600:
        minutes = max(int(delta.total_seconds() // 60), 1)
        return f'Hace {minutes} min'
    if delta.total_seconds() < 86400:
        hours = max(int(delta.total_seconds() // 3600), 1)
        return f'Hace {hours}h'
    if delta.total_seconds() < 172800:
        return 'Ayer'
    return f'Hace {delta.days} dias'


def get_context_models(info):
    user = info.context.user
    jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
    if not jwt_context:
        raise GraphQLError('No valid account context found')

    business_id = jwt_context.get('business_id')
    if jwt_context.get('account_type') == 'business' and business_id:
        business = Business.objects.filter(id=business_id, deleted_at__isnull=True).first()
        if business is None:
            raise GraphQLError('Business context could not be resolved')
        return user, None, business, jwt_context

    account = Account.objects.filter(
        user=user,
        account_type=jwt_context.get('account_type', 'personal'),
        account_index=jwt_context.get('account_index', 0),
        deleted_at__isnull=True,
    ).first()
    if account is None:
        raise GraphQLError('Account context could not be resolved')
    return user, account, None, jwt_context


def require_staff_user(info):
    user = getattr(info.context, 'user', None)
    if not (user and user.is_authenticated and user.is_staff):
        raise GraphQLError('Staff access required')
    is_verified = getattr(user, 'is_verified', None)
    if not callable(is_verified) or not is_verified():
        raise GraphQLError('OTP verification required for portal access')
    return user


def get_visible_content_queryset(membership: ChannelMembership):
    queryset = membership.channel.content_items.filter(
        community.READABLE,
        Q(published_at__gte=membership.joined_at)
        | Q(visibility_policy__in=[VisibilityPolicy.BACKLOG, VisibilityPolicy.PINNED]),
        status=ContentStatus.PUBLISHED,
        published_at__isnull=False,
    ).annotate(
        pinned_rank=Case(
            When(visibility_policy=VisibilityPolicy.PINNED, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    )
    return queryset.order_by('pinned_rank', '-published_at', '-created_at')


# The support thread is answered by Confio Assistant first; the team takes over on
# handoff (assistant/service.py). Same thread, same history.
SUPPORT_CHANNEL_NAME = 'Confio Assistant'
SUPPORT_CHANNEL_SUBTITLE = 'Tu asistente · Disponible 24/7'
SUPPORT_CHANNEL_PREVIEW = '¿En qué te ayudo hoy?'
SUPPORT_GREETING = (
    'Hola, soy Confio Assistant. Pregúntame sobre tu dinero o sobre la app, por escrito o con un audio. '
    'Si hace falta, te paso con el equipo de Confío.'
)


def get_or_create_support_conversation(user, account, business):
    conversation_defaults = {'status': 'OPEN'}
    if business is not None:
        conversation, created = SupportConversation.objects.get_or_create(
            user=user,
            business=business,
            account__isnull=True,
            status='OPEN',
            defaults=conversation_defaults,
        )
    else:
        conversation, created = SupportConversation.objects.get_or_create(
            user=user,
            account=account,
            business__isnull=True,
            status='OPEN',
            defaults=conversation_defaults,
        )

    if created and not conversation.messages.exists():
        message = SupportMessage.objects.create(
            conversation=conversation,
            sender_type='SYSTEM',
            message_type='TEXT',
            body=SUPPORT_GREETING,
            metadata={},
        )
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=['last_message_at', 'updated_at'])

    return conversation


class ContentPollOptionType(graphene.ObjectType):
    id = graphene.ID(required=True)
    label = graphene.String(required=True)
    count = graphene.Int(required=True)


class ContentPollType(graphene.ObjectType):
    id = graphene.ID(required=True)
    question = graphene.String(required=True)
    options = graphene.List(ContentPollOptionType, required=True)
    total_votes = graphene.Int(required=True)
    viewer_option_id = graphene.ID()
    closed = graphene.Boolean(required=True)


def build_poll_payloads(items, user_id=None):
    """Read totals and the viewer's answers in one database snapshot per page."""
    polls = {item.id: item.metadata['poll'] for item in items if (item.metadata or {}).get('poll')}
    if not polls:
        return {}
    counts = {item_id: {} for item_id in polls}
    viewer_options = {}
    votes = ContentPollVote.objects.filter(content_item_id__in=polls).values(
        'content_item_id', 'option_id', 'content_item__metadata__poll',
    ).annotate(count=Count('id'), viewer_count=Count('id', filter=Q(user_id=user_id)))
    for vote in votes:
        item_id, option_id = vote['content_item_id'], vote['option_id']
        # A first vote may arrive after an editor changes an unvoted poll.
        # Read its configuration in the same snapshot as its counted answers.
        polls[item_id] = vote['content_item__metadata__poll']
        counts[item_id][option_id] = vote['count']
        if vote['viewer_count']:
            viewer_options[item_id] = option_id
    return {
        item_id: ContentPollType(
            id=str(item_id), question=poll['question'],
            options=[ContentPollOptionType(id=option['id'], label=option['label'], count=counts[item_id].get(option['id'], 0))
                     for option in poll['options']],
            total_votes=sum(counts[item_id].values()), viewer_option_id=viewer_options.get(item_id),
            closed=poll.get('closed', False),
        )
        for item_id, poll in polls.items()
    }


def build_poll_payload(item, user_id=None):
    return build_poll_payloads([item], user_id).get(item.id)


class MessageThreadItemType(graphene.ObjectType):
    poll = graphene.Field(ContentPollType)
    id = graphene.ID(required=True)
    type = graphene.String(required=True)
    is_pinned = graphene.Boolean(required=True)
    occurred_at = graphene.DateTime(required=True)
    tag = graphene.String()
    title = graphene.String()
    body = graphene.String()
    text = graphene.String()
    time = graphene.String(required=True)
    link = graphene.String()
    platforms = graphene.List(graphene.String)
    platform_links = graphene.List(lambda: PlatformLinkType)
    image_url = graphene.String()
    reaction_summary = graphene.List(lambda: MessageReactionType)
    viewer_reaction = graphene.String()
    can_react = graphene.Boolean(required=True)
    sender_type = graphene.String()
    sender_name = graphene.String()


class MessageChannelType(graphene.ObjectType):
    id = graphene.String(required=True)
    name = graphene.String(required=True)
    subtitle = graphene.String(required=True)
    preview = graphene.String(required=True)
    time = graphene.String(required=True)
    unread_count = graphene.Int(required=True)
    is_muted = graphene.Boolean(required=True)
    messages = graphene.List(MessageThreadItemType, required=True)


class MessageInboxType(graphene.ObjectType):
    total_unread_count = graphene.Int(required=True)
    channels = graphene.List(MessageChannelType, required=True)


class MessageChannelThreadPageType(graphene.ObjectType):
    channel = graphene.Field(MessageChannelType, required=True)
    has_more = graphene.Boolean(required=True)


class PlatformLinkType(graphene.ObjectType):
    platform = graphene.String(required=True)
    url = graphene.String(required=True)


class MessageReactionType(graphene.ObjectType):
    emoji = graphene.String(required=True)
    count = graphene.Int(required=True)


class DiscoverFeedItemType(graphene.ObjectType):
    poll = graphene.Field(ContentPollType)
    id = graphene.ID(required=True)
    type = graphene.String(required=True)
    tag = graphene.String(required=True)
    tag_color = graphene.String(required=True)
    title = graphene.String(required=True)
    body = graphene.String(required=True)
    time = graphene.String(required=True)
    thumbnail = graphene.Boolean(required=True)
    platform_links = graphene.List(lambda: PlatformLinkType, required=True)
    image_url = graphene.String()
    blocks = graphene.JSONString()
    reaction_summary = graphene.List(MessageReactionType, required=True)
    viewer_reaction = graphene.String()
    can_react = graphene.Boolean(required=True)
    source_name = graphene.String(required=True)
    source_section = graphene.String(required=True)
    is_official = graphene.Boolean(required=True)
    # Byline: the channel's uploaded logo/photo, else its emoji; the app
    # falls back to an initial when both are empty.
    source_avatar_url = graphene.String()
    source_avatar_emoji = graphene.String()
    published_at = graphene.DateTime()


class DiscoverFeedPageType(graphene.ObjectType):
    items = graphene.List(DiscoverFeedItemType, required=True)
    has_more = graphene.Boolean(required=True)


class DiscoverSectionType(graphene.ObjectType):
    key = graphene.String(required=True)
    label = graphene.String(required=True)


class PortalContentItemType(graphene.ObjectType):
    poll = graphene.Field(ContentPollType)
    id = graphene.ID(required=True)
    channel_slug = graphene.String(required=True)
    channel_title = graphene.String(required=True)
    item_type = graphene.String(required=True)
    status = graphene.String(required=True)
    title = graphene.String()
    body = graphene.String()
    tag = graphene.String()
    published_at = graphene.DateTime()
    visibility_policy = graphene.String(required=True)
    send_push = graphene.Boolean(required=True)
    send_in_app = graphene.Boolean(required=True)
    push_sent_at = graphene.DateTime()
    surfaces = graphene.List(graphene.String, required=True)
    metadata = graphene.JSONString()


class PortalSupportMessageType(graphene.ObjectType):
    id = graphene.ID(required=True)
    sender_type = graphene.String(required=True)
    sender_name = graphene.String(required=True)
    body = graphene.String(required=True)
    created_at = graphene.DateTime(required=True)


class PortalSupportConversationType(graphene.ObjectType):
    id = graphene.ID(required=True)
    customer_name = graphene.String(required=True)
    customer_email = graphene.String()
    context_label = graphene.String(required=True)
    status = graphene.String(required=True)
    assigned_to_name = graphene.String()
    last_message_at = graphene.DateTime()
    last_preview = graphene.String(required=True)
    unread_count = graphene.Int(required=True)
    messages = graphene.List(PortalSupportMessageType, required=True)


class PublicationImageUploadType(graphene.ObjectType):
    url = graphene.String(required=True)
    key = graphene.String(required=True)
    method = graphene.String(required=True)
    fields = graphene.JSONString()
    expires_in = graphene.Int(required=True)
    public_url = graphene.String(required=True)


def get_support_sender_name(message: SupportMessage):
    if message.sender_type == 'USER':
        user = message.conversation.user
        full_name = f'{user.first_name or ""} {user.last_name or ""}'.strip()
        return full_name or user.username or 'Usuario'
    if message.sender_type == 'AGENT':
        if (message.metadata or {}).get('ai'):
            return 'Confio Assistant'
        if message.sender_user_id:
            full_name = f'{message.sender_user.first_name or ""} {message.sender_user.last_name or ""}'.strip()
            return full_name or message.sender_user.username or 'Agente Confío'
        return 'Agente Confío'
    return 'Soporte de Confío'


def build_portal_support_conversation_payload(conversation: SupportConversation):
    recent_messages_desc = list(conversation.messages.select_related('sender_user').order_by('-created_at')[:50])
    latest_message = recent_messages_desc[0] if recent_messages_desc else None
    ordered_messages = list(reversed(recent_messages_desc))
    context_label = (
        f'Negocio · {conversation.business.name}'
        if conversation.business_id
        else 'Cuenta personal'
    )
    customer = conversation.user
    customer_name = f'{customer.first_name or ""} {customer.last_name or ""}'.strip() or customer.username or 'Usuario'
    assigned_to_name = None
    if conversation.assigned_to_id:
        assigned_to_name = (
            f'{conversation.assigned_to.first_name or ""} {conversation.assigned_to.last_name or ""}'.strip()
            or conversation.assigned_to.username
        )

    # Awaiting the team: Confio Assistant answers first, so only threads handed to
    # people count, and the AI's own replies never mark a thread as answered.
    from assistant.service import awaiting_team
    unread_count = 1 if awaiting_team(conversation, recent_messages_desc) else 0

    return PortalSupportConversationType(
        id=str(conversation.id),
        customer_name=customer_name,
        customer_email=customer.email or '',
        context_label=context_label,
        status=conversation.status,
        assigned_to_name=assigned_to_name,
        last_message_at=conversation.last_message_at,
        last_preview=latest_message.body if latest_message else '',
        unread_count=unread_count,
        messages=[
            PortalSupportMessageType(
                id=str(message.id),
                sender_type=message.sender_type,
                sender_name=get_support_sender_name(message),
                body=message.body,
                created_at=message.created_at,
            )
            for message in ordered_messages
        ],
    )


def build_portal_content_payload(item: ContentItem, poll_payloads=None):
    return PortalContentItemType(
        id=str(item.id),
        channel_slug=item.channel.slug,
        channel_title=item.channel.title,
        item_type=item.item_type,
        status=item.status,
        title=item.title or '',
        body=item.body or '',
        tag=item.tag or '',
        published_at=item.published_at,
        visibility_policy=item.visibility_policy,
        send_push=item.send_push,
        send_in_app=item.send_in_app,
        push_sent_at=item.push_sent_at,
        surfaces=list(item.surfaces.values_list('surface', flat=True)),
        metadata=item.metadata or {},
        poll=build_poll_payload(item) if poll_payloads is None else poll_payloads.get(item.id),
    )


def build_discover_feed_item_payload(
    item: ContentItem, user, account, business, poll_payloads=None, official_ids=None, avatar_urls=None,
):
    if official_ids is None:
        official_ids = official_channel_ids([item.channel])
    metadata = item.metadata or {}
    blocks = metadata.get('blocks') or []
    preview_image = metadata.get('image') or next(
        (
            block.get('image')
            for block in blocks
            if block.get('type') == 'image' and isinstance(block.get('image'), dict) and block.get('image', {}).get('url')
        ),
        {},
    )
    reaction_counts = {}
    viewer_reaction = ''
    for reaction in item.reactions.select_related('reaction_type').all():
        emoji = reaction.reaction_type.emoji
        reaction_counts[emoji] = reaction_counts.get(emoji, 0) + 1
        if business is not None:
            if reaction.business_id == business.id and reaction.user_id == user.id:
                viewer_reaction = emoji
        elif account is not None:
            if reaction.account_id == account.id and reaction.user_id == user.id:
                viewer_reaction = emoji

    tag_label = item.tag or item.channel.title or ''
    normalized_tag = tag_label.strip().lower()
    tag_color = str(
        metadata.get('tag_color')
        or DISCOVER_TAG_COLOR_MAP.get(normalized_tag)
        or {
            'VIDEO': '#FF4444',
            'NEWS': '#F59E0B',
            'TEXT': '#1DB587',
        }.get(item.item_type, '#1DB587')
    )
    item_type = 'product'
    if item.item_type == 'VIDEO':
        item_type = 'video'
    elif item.item_type == 'NEWS':
        item_type = 'news'

    if item.owner_type == OwnerType.USER:
        # A member speaks as themselves, never as the channel that hosts the
        # post; the app draws their initial.
        byline = {
            'source_name': author_display_name(item.owner_user),
            'source_section': 'community',
            'is_official': False,
            'source_avatar_url': (
                avatar_urls if avatar_urls is not None else profile_pictures.picture_urls([item.owner_user_id])
            ).get(item.owner_user_id),
            'source_avatar_emoji': None,
        }
    else:
        byline = {
            'source_name': item.channel.title or '',
            'source_section': DISCOVER_KIND_SECTION.get(item.channel.kind, 'confio'),
            'is_official': item.channel_id in official_ids,
            'source_avatar_url': item.channel.avatar_value if item.channel.avatar_type == AvatarType.IMAGE_URL else None,
            'source_avatar_emoji': item.channel.avatar_value if item.channel.avatar_type == AvatarType.EMOJI else None,
        }

    return DiscoverFeedItemType(
        id=str(item.id),
        type=item_type,
        tag=tag_label,
        tag_color=tag_color,
        title=item.title or '',
        body=item.body or '',
        time=humanize_relative(item.published_at or item.created_at),
        thumbnail=item.item_type == 'VIDEO',
        platform_links=[
            PlatformLinkType(platform=platform, url=url)
            for platform, url in (metadata.get('platform_links') or {}).items()
            if url
        ],
        image_url=preview_image.get('url') or '',
        blocks=blocks,
        poll=build_poll_payload(item, user.id) if poll_payloads is None else poll_payloads.get(item.id),
        reaction_summary=[
            MessageReactionType(emoji=emoji, count=count)
            for emoji, count in sorted(reaction_counts.items(), key=lambda reaction_item: reaction_item[1], reverse=True)
        ],
        viewer_reaction=viewer_reaction,
        can_react=True,
        **byline,
        published_at=item.published_at or item.created_at,
    )


def published_discover_items():
    return ContentItem.objects.filter(
        community.READABLE,
        status=ContentStatus.PUBLISHED,
        published_at__isnull=False,
        surfaces__surface=ContentSurfaceType.DISCOVER,
    )


def get_accessible_content_item(info, content_item_id):
    user, account, business, _ = get_context_models(info)
    item = (
        ContentItem.objects.select_related('channel')
        .prefetch_related('reactions__reaction_type', 'surfaces')
        .filter(community.READABLE, id=content_item_id, status=ContentStatus.PUBLISHED, published_at__isnull=False)
        .first()
    )
    if item is None:
        raise GraphQLError('Content item not found')

    has_discover_surface = item.surfaces.filter(surface=ContentSurfaceType.DISCOVER).exists()
    if has_discover_surface:
        return item, user, account, business

    membership_filter = {'channel': item.channel, 'user': user, 'is_subscribed': True}
    if business is not None:
        membership_filter.update({'business': business, 'account__isnull': True})
    else:
        membership_filter.update({'account': account, 'business__isnull': True})

    membership = ChannelMembership.objects.filter(**membership_filter).first()
    if membership is None or not get_visible_content_queryset(membership).filter(id=item.id).exists():
        raise GraphQLError('Content item not available in this context')

    return item, user, account, business


def build_editorial_channel_payload(membership: ChannelMembership):
    visible_items = list(
        get_visible_content_queryset(membership).prefetch_related('reactions__reaction_type')[:20]
    )
    latest_item = visible_items[0] if visible_items else None

    if latest_item:
        preview = latest_item.title or latest_item.body or ''
        time_label = humanize_relative(latest_item.published_at or latest_item.created_at)
    else:
        preview = membership.channel.subtitle or membership.channel.title
        time_label = ''

    if membership.last_seen_at:
        unread_count = get_visible_content_queryset(membership).filter(
            published_at__gt=membership.last_seen_at
        ).count()
    else:
        unread_count = get_visible_content_queryset(membership).count()

    poll_payloads = build_poll_payloads(visible_items, membership.user_id)
    messages = []
    for item in visible_items:
        metadata = item.metadata or {}
        blocks = metadata.get('blocks') or []
        preview_image = metadata.get('image') or next(
            (
                block.get('image')
                for block in blocks
                if block.get('type') == 'image' and isinstance(block.get('image'), dict) and block.get('image', {}).get('url')
            ),
            {},
        )
        item_type = item.item_type.lower()
        message_payload = {
            'id': str(item.id),
            'type': item_type,
            'is_pinned': item.visibility_policy == VisibilityPolicy.PINNED,
            'occurred_at': item.published_at or item.created_at,
            'tag': item.tag or '',
            'title': item.title or '',
            'body': item.body or '',
            'text': item.body or item.title or '',
            'time': humanize_relative(item.published_at or item.created_at),
            'link': '',
            'platforms': metadata.get('platforms') or [],
            'platform_links': [
                PlatformLinkType(platform=platform, url=url)
                for platform, url in (metadata.get('platform_links') or {}).items()
                if url
            ],
            'image_url': preview_image.get('url') or '',
            'reaction_summary': [],
            'viewer_reaction': '',
            'can_react': True,
        }
        reaction_counts = {}
        viewer_reaction = ''
        for reaction in item.reactions.all():
            emoji = reaction.reaction_type.emoji
            reaction_counts[emoji] = reaction_counts.get(emoji, 0) + 1
            if membership.business_id:
                if reaction.business_id == membership.business_id and reaction.user_id == membership.user_id:
                    viewer_reaction = emoji
            elif membership.account_id:
                if reaction.account_id == membership.account_id and reaction.user_id == membership.user_id:
                    viewer_reaction = emoji
        message_payload['reaction_summary'] = [
            MessageReactionType(emoji=emoji, count=count)
            for emoji, count in sorted(reaction_counts.items(), key=lambda item: item[1], reverse=True)
        ]
        message_payload['poll'] = poll_payloads.get(item.id)
        message_payload['viewer_reaction'] = viewer_reaction
        messages.append(MessageThreadItemType(**message_payload))

    return MessageChannelType(
        id=membership.channel.slug,
        name=membership.channel.title,
        subtitle=membership.channel.subtitle or '',
        preview=preview,
        time=time_label,
        unread_count=unread_count,
        is_muted=membership.push_level == 'NONE',
        messages=messages,
    )


def build_editorial_message_payload(item: ContentItem, membership: ChannelMembership, poll_payloads=None):
    metadata = item.metadata or {}
    blocks = metadata.get('blocks') or []
    preview_image = metadata.get('image') or next(
        (
            block.get('image')
            for block in blocks
            if block.get('type') == 'image' and isinstance(block.get('image'), dict) and block.get('image', {}).get('url')
        ),
        {},
    )
    item_type = item.item_type.lower()
    message_payload = {
        'id': str(item.id),
        'type': item_type,
        'is_pinned': item.visibility_policy == VisibilityPolicy.PINNED,
        'occurred_at': item.published_at or item.created_at,
        'tag': item.tag or '',
        'title': item.title or '',
        'body': item.body or '',
        'text': item.body or item.title or '',
        'time': humanize_relative(item.published_at or item.created_at),
        'link': '',
        'platforms': metadata.get('platforms') or [],
        'platform_links': [
            PlatformLinkType(platform=platform, url=url)
            for platform, url in (metadata.get('platform_links') or {}).items()
            if url
        ],
        'image_url': preview_image.get('url') or '',
        'reaction_summary': [],
        'viewer_reaction': '',
        'can_react': True,
    }
    reaction_counts = {}
    viewer_reaction = ''
    for reaction in item.reactions.all():
        emoji = reaction.reaction_type.emoji
        reaction_counts[emoji] = reaction_counts.get(emoji, 0) + 1
        if membership.business_id:
            if reaction.business_id == membership.business_id and reaction.user_id == membership.user_id:
                viewer_reaction = emoji
        elif membership.account_id:
            if reaction.account_id == membership.account_id and reaction.user_id == membership.user_id:
                viewer_reaction = emoji
    message_payload['reaction_summary'] = [
        MessageReactionType(emoji=emoji, count=count)
        for emoji, count in sorted(reaction_counts.items(), key=lambda item: item[1], reverse=True)
    ]
    message_payload['poll'] = (build_poll_payload(item, membership.user_id)
                               if poll_payloads is None else poll_payloads.get(item.id))
    message_payload['viewer_reaction'] = viewer_reaction
    return MessageThreadItemType(**message_payload)


def build_editorial_channel_thread_page(membership: ChannelMembership, offset=0, limit=20):
    offset = max(offset or 0, 0)
    limit = min(max(limit or 20, 1), 50)
    queryset = get_visible_content_queryset(membership).prefetch_related('reactions__reaction_type')
    page_items = list(queryset[offset:offset + limit + 1])
    has_more = len(page_items) > limit
    if has_more:
        page_items = page_items[:limit]

    poll_payloads = build_poll_payloads(page_items, membership.user_id)
    base_channel = build_editorial_channel_payload(membership)
    return MessageChannelThreadPageType(
        channel=MessageChannelType(
            id=base_channel.id,
            name=base_channel.name,
            subtitle=base_channel.subtitle,
            preview=base_channel.preview,
            time=base_channel.time,
            unread_count=base_channel.unread_count,
            is_muted=base_channel.is_muted,
            messages=[build_editorial_message_payload(item, membership, poll_payloads) for item in page_items],
        ),
        has_more=has_more,
    )


def build_support_channel_payload(user, account, business):
    conversation = get_or_create_support_conversation(user, account, business)
    state, _ = SupportConversationState.objects.get_or_create(conversation=conversation, user=user)
    recent_messages_desc = list(conversation.messages.select_related('sender_user').order_by('-created_at')[:50])
    latest_message = recent_messages_desc[0] if recent_messages_desc else None
    messages_qs = list(reversed(recent_messages_desc))

    if state.last_seen_at:
        unread_count = conversation.messages.filter(created_at__gt=state.last_seen_at).exclude(
            sender_type='USER'
        ).count()
    else:
        unread_count = conversation.messages.exclude(sender_type='USER').count()

    thread_messages = [
        MessageThreadItemType(
            id=str(message.id),
            type='support',
            is_pinned=False,
            occurred_at=message.created_at,
            tag='',
            title='',
            body=message.body,
            text=message.body,
            time=humanize_relative(message.created_at),
            link='',
            platforms=[],
            platform_links=[],
            reaction_summary=[],
            viewer_reaction='',
            can_react=False,
            sender_type=message.sender_type,
            sender_name=get_support_sender_name(message),
        )
        for message in messages_qs
    ]

    return MessageChannelType(
        id='soporte',
        name=SUPPORT_CHANNEL_NAME,
        subtitle=SUPPORT_CHANNEL_SUBTITLE,
        preview=latest_message.body if latest_message else SUPPORT_CHANNEL_PREVIEW,
        time=humanize_relative(latest_message.created_at) if latest_message else 'Ahora',
        unread_count=unread_count,
        is_muted=False,
        messages=thread_messages,
    )


def build_support_channel_thread_page(user, account, business, offset=0, limit=50):
    offset = max(offset or 0, 0)
    limit = min(max(limit or 20, 1), 50)
    conversation = get_or_create_support_conversation(user, account, business)
    state, _ = SupportConversationState.objects.get_or_create(conversation=conversation, user=user)
    recent_messages_desc = list(
        conversation.messages.select_related('sender_user').order_by('-created_at')[offset:offset + limit + 1]
    )
    has_more = len(recent_messages_desc) > limit
    if has_more:
        recent_messages_desc = recent_messages_desc[:limit]
    messages_qs = list(reversed(recent_messages_desc))
    latest_message = conversation.messages.order_by('-created_at').first()

    if state.last_seen_at:
        unread_count = conversation.messages.filter(created_at__gt=state.last_seen_at).exclude(
            sender_type='USER'
        ).count()
    else:
        unread_count = conversation.messages.exclude(sender_type='USER').count()

    thread_messages = [
        MessageThreadItemType(
            id=str(message.id),
            type='support',
            is_pinned=False,
            occurred_at=message.created_at,
            tag='',
            title='',
            body=message.body,
            text=message.body,
            time=humanize_relative(message.created_at),
            link='',
            platforms=[],
            platform_links=[],
            reaction_summary=[],
            viewer_reaction='',
            can_react=False,
            sender_type=message.sender_type,
            sender_name=get_support_sender_name(message),
        )
        for message in messages_qs
    ]

    return MessageChannelThreadPageType(
        channel=MessageChannelType(
            id='soporte',
            name=SUPPORT_CHANNEL_NAME,
            subtitle=SUPPORT_CHANNEL_SUBTITLE,
            preview=latest_message.body if latest_message else SUPPORT_CHANNEL_PREVIEW,
            time=humanize_relative(latest_message.created_at) if latest_message else 'Ahora',
            unread_count=unread_count,
            is_muted=False,
            messages=thread_messages,
        ),
        has_more=has_more,
    )


def build_message_inbox_payload(info):
    user, account, business, _ = get_context_models(info)

    membership_filter = {'user': user, 'is_subscribed': True}
    if business is not None:
        membership_filter.update({'business': business, 'account__isnull': True})
    else:
        membership_filter.update({'account': account, 'business__isnull': True})

    memberships = (
        ChannelMembership.objects.select_related('channel')
        .filter(**membership_filter)
        .order_by('channel__sort_order', 'channel__title')
    )

    channels = [build_editorial_channel_payload(membership) for membership in memberships]
    channels.append(build_support_channel_payload(user, account, business))
    total_unread_count = sum(channel.unread_count for channel in channels)

    return MessageInboxType(total_unread_count=total_unread_count, channels=channels)


class CommunityPostingStatusType(graphene.ObjectType):
    can_post = graphene.Boolean(required=True)
    # disabled | business_context | banned | not_verified | daily_limit
    block_code = graphene.String()
    block_message = graphene.String()
    max_chars = graphene.Int(required=True)


class CommunityPostType(graphene.ObjectType):
    """The author's own view of a post, including its review outcome."""
    id = graphene.ID(required=True)
    body = graphene.String(required=True)
    image_url = graphene.String()
    has_image = graphene.Boolean(required=True)
    # PENDING | APPROVED | REJECTED | FAILED | REMOVED
    status = graphene.String(required=True)
    reason = graphene.String()
    created_at = graphene.DateTime(required=True)
    published_at = graphene.DateTime()
    comment_count = graphene.Int(required=True)


class CommunityPostViewerType(graphene.ObjectType):
    is_community = graphene.Boolean(required=True)
    is_own = graphene.Boolean(required=True)
    can_report = graphene.Boolean(required=True)
    viewer_reported = graphene.Boolean(required=True)
    can_comment = graphene.Boolean(required=True)
    # Why not, when can_comment is false (e.g. "Verifica tu identidad…").
    comment_block_message = graphene.String()
    comment_max_chars = graphene.Int(required=True)


class CommunityParticipantType(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String(required=True)
    is_post_author = graphene.Boolean(required=True)
    avatar_url = graphene.String()


class CommunityCommentType(graphene.ObjectType):
    id = graphene.ID(required=True)
    parent_id = graphene.ID()
    body = graphene.String(required=True)
    author_id = graphene.ID(required=True)
    author_name = graphene.String(required=True)
    is_post_author = graphene.Boolean(required=True)
    is_own = graphene.Boolean(required=True)
    can_delete = graphene.Boolean(required=True)
    can_report = graphene.Boolean(required=True)
    # Others only ever see APPROVED; the author also sees their own
    # PENDING / REJECTED / FAILED comments.
    status = graphene.String(required=True)
    reason = graphene.String()
    time = graphene.String(required=True)
    created_at = graphene.DateTime(required=True)
    mentions = graphene.List(graphene.NonNull(CommunityParticipantType), required=True)
    replies = graphene.List(graphene.NonNull(lambda: CommunityCommentType), required=True)
    # Visible replies in the thread; more than `replies` holds means the app
    # can expand it (expandedThreadIds).
    reply_count = graphene.Int(required=True)
    author_avatar_url = graphene.String()
    reaction_summary = graphene.List(graphene.NonNull(MessageReactionType), required=True)
    viewer_reaction = graphene.String()


class CommunityCommentPageType(graphene.ObjectType):
    items = graphene.List(graphene.NonNull(CommunityCommentType), required=True)
    has_more = graphene.Boolean(required=True)
    total_count = graphene.Int(required=True)


class CommunityCommentCountType(graphene.ObjectType):
    content_item_id = graphene.ID(required=True)
    count = graphene.Int(required=True)


def reaction_maps(comment_ids, viewer):
    """Reaction counts per comment, aggregated in SQL, plus the viewer's own
    reaction: never one row per reaction, however popular a comment is."""
    from .models import CommunityCommentReaction

    ids = list(comment_ids)
    counts = {}
    for row in (
        CommunityCommentReaction.objects.filter(comment_id__in=ids)
        .values('comment_id', 'reaction_type__emoji')
        .annotate(total=Count('id'))
    ):
        counts.setdefault(row['comment_id'], []).append((row['reaction_type__emoji'], row['total']))
    viewer_reactions = dict(
        CommunityCommentReaction.objects.filter(comment_id__in=ids, user=viewer)
        .values_list('comment_id', 'reaction_type__emoji')
    )
    return counts, viewer_reactions


def reaction_payload(comment_id, maps):
    counts, viewer_reactions = maps
    summary = [
        MessageReactionType(emoji=emoji, count=count)
        for emoji, count in sorted(counts.get(comment_id, []), key=lambda entry: entry[1], reverse=True)
    ]
    return summary, viewer_reactions.get(comment_id)


def build_community_comment_payload(
    comment, viewer, post_author_id, reported_ids, replies=None, avatars=None, reactions=None, reply_count=0,
):
    is_own = comment.author_id == viewer.id
    avatars = avatars if avatars is not None else profile_pictures.picture_urls(
        [comment.author_id, *[user.id for user in comment.mentions.all()]]
    )
    reaction_summary, viewer_reaction = reaction_payload(
        comment.id, reactions if reactions is not None else reaction_maps([comment.id], viewer),
    )
    return CommunityCommentType(
        id=str(comment.id),
        parent_id=str(comment.parent_id) if comment.parent_id else None,
        body=comment.body,
        author_id=str(comment.author_id),
        author_name=community.author_display_name(comment.author),
        is_post_author=comment.author_id == post_author_id,
        is_own=is_own,
        can_delete=is_own or viewer.id == post_author_id,
        can_report=(
            not is_own
            and comment.status == CommunityReviewStatus.APPROVED
            and comment.id not in reported_ids
        ),
        status=comment.status,
        reason=(comment.reason or None) if is_own else None,
        time=humanize_relative(comment.created_at),
        created_at=comment.created_at,
        mentions=[
            CommunityParticipantType(
                id=str(user.id),
                name=community.author_display_name(user),
                is_post_author=user.id == post_author_id,
                avatar_url=avatars.get(user.id),
            )
            for user in comment.mentions.all()
        ],
        replies=replies or [],
        reply_count=reply_count,
        author_avatar_url=avatars.get(comment.author_id),
        reaction_summary=reaction_summary,
        viewer_reaction=viewer_reaction,
    )


COMMENT_THREADS_MAX = 100
REPLIES_PER_THREAD = 50
# An expanded thread (the app's "Ver todas las respuestas").
REPLIES_EXPANDED_MAX = 500
UNREVIEWED = [CommunityReviewStatus.PENDING, CommunityReviewStatus.REJECTED, CommunityReviewStatus.FAILED]


def first_replies(queryset, cap):
    """The first `cap` replies of each thread in one bounded query."""
    return queryset.annotate(
        thread_rank=Window(RowNumber(), partition_by=F('parent_id'), order_by=[F('created_at').asc(), F('id').asc()]),
    ).filter(thread_rank__lte=cap)


def comments_seen_by(viewer, content_item_id):
    """Approved comments plus the viewer's own, still-standing ones."""
    return (
        CommunityComment.objects.filter(content_item_id=content_item_id)
        .filter(
            Q(status=CommunityReviewStatus.APPROVED)
            | (
                Q(author=viewer)
                & Q(status__in=[
                    CommunityReviewStatus.PENDING,
                    CommunityReviewStatus.REJECTED,
                    CommunityReviewStatus.FAILED,
                ])
            )
        )
        .exclude(parent__status=CommunityReviewStatus.REMOVED)
        .select_related('author')
        .prefetch_related('mentions')
        .order_by('created_at', 'id')
    )


def build_community_post_payload(item: ContentItem, comment_count=None):
    review = item.community_review
    return CommunityPostType(
        id=str(item.id),
        body=item.body or '',
        image_url=(item.metadata or {}).get('image', {}).get('url') or None,
        has_image=bool(review.pending_image_key),
        status=review.status,
        reason=review.reason or None,
        created_at=item.created_at,
        published_at=item.published_at,
        comment_count=(
            0 if review.status != CommunityReviewStatus.APPROVED
            else comment_count if comment_count is not None
            else community.visible_comments(item.id).count()
        ),
    )


def own_community_items(user):
    return (
        ContentItem.objects.filter(owner_user=user, community_review__isnull=False)
        .select_related('community_review')
        .order_by('-created_at')
    )


class RequestCommunityImageUpload(graphene.Mutation):
    class Arguments:
        content_type = graphene.String(required=False)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    upload = graphene.Field(PublicationImageUploadType)

    @classmethod
    @login_required
    def mutate(cls, root, info, content_type='image/jpeg'):
        user, account, business, _ = get_context_models(info)
        block = community.posting_block(user, business)
        if block:
            return RequestCommunityImageUpload(success=False, error=community.BLOCK_MESSAGES[block], upload=None)
        if content_type not in community.ALLOWED_IMAGE_TYPES:
            return RequestCommunityImageUpload(success=False, error='Formato de imagen no permitido.', upload=None)
        if not community.take_upload_ticket(user, 'community-post'):
            return RequestCommunityImageUpload(success=False, error=community.TICKET_LIMIT_MESSAGE, upload=None)
        extension = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}[content_type]
        key = build_s3_key(community.pending_image_prefix(user), f'upload{extension}')
        try:
            presigned = generate_presigned_post(
                key=key,
                content_type=content_type,
                metadata={'uploaded-by': str(user.id), 'uploaded-for': 'community'},
                conditions=[['content-length-range', 1, settings.COMMUNITY_IMAGE_MAX_BYTES]],
                expires_in_seconds=600,
                bucket=settings.AWS_COMMUNITY_UPLOAD_BUCKET,
            )
        except Exception:
            logger.exception('Failed to presign community image upload', extra={'user_id': user.id})
            return RequestCommunityImageUpload(success=False, error='No pudimos preparar la subida. Inténtalo de nuevo.', upload=None)
        return RequestCommunityImageUpload(
            success=True,
            error=None,
            upload=PublicationImageUploadType(
                url=presigned['url'],
                key=presigned['key'],
                method=presigned['method'],
                fields=presigned.get('fields'),
                expires_in=presigned['expires_in'],
                # Private until approved; there is nothing public to show yet.
                public_url='',
            ),
        )


class CreateCommunityPost(graphene.Mutation):
    class Arguments:
        body = graphene.String(required=True)
        image_key = graphene.String(required=False)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    error_code = graphene.String()
    post = graphene.Field(CommunityPostType)

    @classmethod
    @login_required
    def mutate(cls, root, info, body, image_key=None):
        user, account, business, _ = get_context_models(info)
        try:
            item = community.create_community_post(user, business, body, image_key)
        except community.CommunityPostError as error:
            return CreateCommunityPost(success=False, error=error.message, error_code=error.code, post=None)
        item = own_community_items(user).get(id=item.id)
        return CreateCommunityPost(success=True, error=None, error_code=None, post=build_community_post_payload(item))


class DeleteCommunityPost(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, content_item_id):
        user = info.context.user
        return DeleteCommunityPost(success=community.delete_own_post(user, content_item_id))


class ReportCommunityPost(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=True)
        reason = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, content_item_id, reason):
        user = info.context.user
        try:
            community.report_post(user, content_item_id, reason)
        except community.CommunityPostError as error:
            return ReportCommunityPost(success=False, error=error.message)
        return ReportCommunityPost(success=True, error=None)


class CreateCommunityComment(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=True)
        body = graphene.String(required=True)
        parent_id = graphene.ID(required=False)
        mention_user_ids = graphene.List(graphene.NonNull(graphene.ID), required=False)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    error_code = graphene.String()
    comment = graphene.Field(CommunityCommentType)

    @classmethod
    @login_required
    def mutate(cls, root, info, content_item_id, body, parent_id=None, mention_user_ids=None):
        user, account, business, _ = get_context_models(info)
        try:
            comment = community.create_comment(user, business, content_item_id, body, parent_id, mention_user_ids)
        except community.CommunityPostError as error:
            return CreateCommunityComment(success=False, error=error.message, error_code=error.code, comment=None)
        comment = CommunityComment.objects.select_related('author', 'content_item').prefetch_related('mentions').get(id=comment.id)
        return CreateCommunityComment(
            success=True,
            error=None,
            error_code=None,
            comment=build_community_comment_payload(comment, user, comment.content_item.owner_user_id, set()),
        )


class DeleteCommunityComment(graphene.Mutation):
    class Arguments:
        comment_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, comment_id):
        return DeleteCommunityComment(success=community.delete_comment(info.context.user, comment_id))


class ReportCommunityComment(graphene.Mutation):
    class Arguments:
        comment_id = graphene.ID(required=True)
        reason = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, comment_id, reason):
        try:
            community.report_comment(info.context.user, comment_id, reason)
        except community.CommunityPostError as error:
            return ReportCommunityComment(success=False, error=error.message)
        return ReportCommunityComment(success=True, error=None)


class ReactToCommunityComment(graphene.Mutation):
    class Arguments:
        comment_id = graphene.ID(required=True)
        emoji = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    reaction_summary = graphene.List(graphene.NonNull(MessageReactionType), required=True)
    viewer_reaction = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, comment_id, emoji):
        user = info.context.user
        try:
            comment = community.react_to_comment(user, comment_id, emoji)
        except community.CommunityPostError as error:
            return ReactToCommunityComment(success=False, error=error.message, reaction_summary=[], viewer_reaction=None)
        summary, viewer_reaction = reaction_payload(comment.id, reaction_maps([comment.id], user))
        return ReactToCommunityComment(
            success=True, error=None, reaction_summary=summary, viewer_reaction=viewer_reaction,
        )


class MyProfilePictureType(graphene.ObjectType):
    # The picture everyone sees now (None: the initial is shown).
    url = graphene.String()
    # The latest change: PENDING while being reviewed, REJECTED / FAILED with
    # a reason, or the same ACTIVE / REMOVED as the current picture.
    latest_status = graphene.String()
    latest_reason = graphene.String()
    # Why this context cannot change it right now, if so.
    block_message = graphene.String()


def build_my_profile_picture(user, business):
    current = profile_pictures.picture_urls([user.id]).get(user.id)
    latest = profile_pictures.latest_submission(user)
    return MyProfilePictureType(
        url=current or None,
        latest_status=latest.status if latest else None,
        latest_reason=(latest.reason or None) if latest else None,
        block_message=profile_pictures.upload_block(user, business),
    )


class RequestProfilePictureUpload(graphene.Mutation):
    class Arguments:
        content_type = graphene.String(required=False)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    upload = graphene.Field(PublicationImageUploadType)

    @classmethod
    @login_required
    def mutate(cls, root, info, content_type='image/jpeg'):
        user, account, business, _ = get_context_models(info)
        try:
            presigned = profile_pictures.request_upload(user, business, content_type)
        except community.CommunityPostError as error:
            return RequestProfilePictureUpload(success=False, error=error.message, upload=None)
        except Exception:
            logger.exception('Failed to presign profile picture upload', extra={'user_id': user.id})
            return RequestProfilePictureUpload(
                success=False, error='No pudimos preparar la subida. Inténtalo de nuevo.', upload=None,
            )
        return RequestProfilePictureUpload(
            success=True,
            error=None,
            upload=PublicationImageUploadType(
                url=presigned['url'],
                key=presigned['key'],
                method=presigned['method'],
                fields=presigned.get('fields'),
                expires_in=presigned['expires_in'],
                public_url='',
            ),
        )


class SubmitProfilePicture(graphene.Mutation):
    class Arguments:
        image_key = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    picture = graphene.Field(MyProfilePictureType)

    @classmethod
    @login_required
    def mutate(cls, root, info, image_key):
        user, account, business, _ = get_context_models(info)
        try:
            profile_pictures.submit_picture(user, business, image_key)
        except community.CommunityPostError as error:
            return SubmitProfilePicture(success=False, error=error.message, picture=None)
        return SubmitProfilePicture(success=True, error=None, picture=build_my_profile_picture(user, business))


class RemoveProfilePicture(graphene.Mutation):
    success = graphene.Boolean(required=True)
    picture = graphene.Field(MyProfilePictureType)

    @classmethod
    @login_required
    def mutate(cls, root, info):
        user, account, business, _ = get_context_models(info)
        if business is not None:
            return RemoveProfilePicture(success=False, picture=build_my_profile_picture(user, business))
        removed = profile_pictures.remove_picture(user, removed_by=user)
        return RemoveProfilePicture(success=removed, picture=build_my_profile_picture(user, business))


class Query(graphene.ObjectType):
    message_inbox = graphene.Field(MessageInboxType, context_key=graphene.String(required=False))
    message_inbox_unread_count = graphene.Int(context_key=graphene.String(required=False))
    message_channel_thread = graphene.Field(
        MessageChannelThreadPageType,
        channel_id=graphene.String(required=True),
        offset=graphene.Int(required=False),
        limit=graphene.Int(required=False),
        context_key=graphene.String(required=False),
    )
    discover_post = graphene.Field(
        DiscoverFeedItemType,
        content_item_id=graphene.ID(required=True),
    )
    discover_feed = graphene.Field(
        DiscoverFeedPageType,
        offset=graphene.Int(required=False),
        limit=graphene.Int(required=False),
        section=graphene.String(required=False),
    )
    # Kept for app builds from 2df03d94, which query it for publisher-type
    # chips. Never remove a field a built app queries: an unknown field fails
    # that build's whole request. Empty = those builds show no chips.
    discover_sections = graphene.List(
        graphene.NonNull(DiscoverSectionType),
        required=True,
        deprecation_reason='Descubrir feeds are fixed: for_you, official, community.',
    )
    # Comunidad fields are their own queries in the app (an older server
    # rejects an unknown field and would fail any query that carries it).
    community_posting_status = graphene.Field(CommunityPostingStatusType, required=True)
    my_community_posts = graphene.List(
        graphene.NonNull(CommunityPostType),
        required=True,
        offset=graphene.Int(required=False),
        limit=graphene.Int(required=False),
    )
    my_community_post = graphene.Field(CommunityPostType, content_item_id=graphene.ID(required=True))
    community_post_viewer = graphene.Field(
        CommunityPostViewerType,
        required=True,
        content_item_id=graphene.ID(required=True),
    )
    community_comments = graphene.Field(
        CommunityCommentPageType,
        required=True,
        content_item_id=graphene.ID(required=True),
        offset=graphene.Int(required=False),
        limit=graphene.Int(required=False),
        expanded_thread_ids=graphene.List(graphene.NonNull(graphene.ID), required=False),
    )
    community_post_participants = graphene.List(
        graphene.NonNull(CommunityParticipantType),
        required=True,
        content_item_id=graphene.ID(required=True),
    )
    my_profile_picture = graphene.Field(MyProfilePictureType, required=True)
    community_comment_counts = graphene.List(
        graphene.NonNull(CommunityCommentCountType),
        required=True,
        content_item_ids=graphene.List(graphene.NonNull(graphene.ID), required=True),
    )
    portal_support_conversations = graphene.List(
        PortalSupportConversationType,
        status=graphene.String(required=False),
        search=graphene.String(required=False),
    )
    portal_support_conversation = graphene.Field(
        PortalSupportConversationType,
        conversation_id=graphene.ID(required=True),
    )
    portal_content_items = graphene.List(
        PortalContentItemType,
        channel_slug=graphene.String(required=False),
        status=graphene.String(required=False),
    )

    @login_required
    def resolve_message_inbox(self, info, context_key=None):
        return build_message_inbox_payload(info)

    @login_required
    def resolve_message_inbox_unread_count(self, info, context_key=None):
        inbox = build_message_inbox_payload(info)
        return inbox.total_unread_count

    @login_required
    def resolve_message_channel_thread(self, info, channel_id, offset=0, limit=20, context_key=None):
        user, account, business, _ = get_context_models(info)

        normalized_channel_id = 'confio-news' if channel_id == 'confio' else channel_id
        if normalized_channel_id == 'soporte':
            return build_support_channel_thread_page(user, account, business, offset=offset, limit=limit)

        membership_filter = {'user': user, 'is_subscribed': True, 'channel__slug': normalized_channel_id}
        if business is not None:
            membership_filter.update({'business': business, 'account__isnull': True})
        else:
            membership_filter.update({'account': account, 'business__isnull': True})

        membership = (
            ChannelMembership.objects.select_related('channel')
            .filter(**membership_filter)
            .first()
        )
        if membership is None:
            raise GraphQLError('Channel not found')

        return build_editorial_channel_thread_page(membership, offset=offset, limit=limit)

    @login_required
    def resolve_discover_post(self, info, content_item_id):
        item, user, account, business = get_accessible_content_item(info, content_item_id)
        return build_discover_feed_item_payload(item, user, account, business)

    @login_required
    def resolve_discover_feed(self, info, offset=0, limit=10, section=None):
        user, account, business, _ = get_context_models(info)
        offset = max(offset or 0, 0)
        limit = min(max(limit or 10, 1), 20)

        queryset = (
            published_discover_items()
            .select_related('channel', 'owner_user')
            .prefetch_related('reactions__reaction_type', 'surfaces')
            .distinct()
            .order_by('-surfaces__is_pinned', 'surfaces__rank', '-published_at', '-created_at')
        )
        section = section or 'for_you'
        if section in LEGACY_DISCOVER_SECTION_KINDS:
            queryset = queryset.filter(channel__kind__in=LEGACY_DISCOVER_SECTION_KINDS[section])
        elif section not in DISCOVER_FEED_SECTIONS:
            raise GraphQLError('Unknown Discover section')
        elif section == 'official':
            queryset = queryset.filter(channel_id__in=all_official_channel_ids()).exclude(USER_AUTHORED)
        elif section == 'community':
            queryset = queryset.filter(USER_AUTHORED)
        page_items = list(queryset[offset:offset + limit + 1])
        has_more = len(page_items) > limit
        if has_more:
            page_items = page_items[:limit]

        poll_payloads = build_poll_payloads(page_items, user.id)
        official_ids = official_channel_ids(item.channel for item in page_items)
        avatar_urls = profile_pictures.picture_urls(
            item.owner_user_id for item in page_items if item.owner_type == OwnerType.USER
        )
        return DiscoverFeedPageType(
            items=[
                build_discover_feed_item_payload(
                    item, user, account, business, poll_payloads, official_ids, avatar_urls,
                )
                for item in page_items
            ],
            has_more=has_more,
        )

    @login_required
    def resolve_discover_sections(self, info):
        return []

    @login_required
    def resolve_community_posting_status(self, info):
        user, account, business, _ = get_context_models(info)
        block = community.posting_block(user, business)
        return CommunityPostingStatusType(
            can_post=block is None,
            block_code=block,
            block_message=community.BLOCK_MESSAGES.get(block) if block else None,
            max_chars=settings.COMMUNITY_POST_MAX_CHARS,
        )

    @login_required
    def resolve_my_community_posts(self, info, offset=0, limit=20):
        offset = max(offset or 0, 0)
        # The app re-reads its whole loaded range (offset 0, growing limit).
        limit = min(max(limit or 20, 1), 500)
        items = list(own_community_items(info.context.user)[offset:offset + limit])
        counts = dict(
            community.visible_comments_any_post()
            .filter(content_item_id__in=[item.id for item in items])
            .values('content_item_id')
            .annotate(total=Count('id'))
            .values_list('content_item_id', 'total')
        )
        return [build_community_post_payload(item, counts.get(item.id, 0)) for item in items]

    @login_required
    def resolve_my_community_post(self, info, content_item_id):
        item = own_community_items(info.context.user).filter(id=content_item_id).first()
        return build_community_post_payload(item) if item else None

    @login_required
    def resolve_community_post_viewer(self, info, content_item_id):
        user = info.context.user
        item = ContentItem.objects.filter(id=content_item_id).select_related('community_review').first()
        review = getattr(item, 'community_review', None) if item else None
        max_chars = settings.COMMUNITY_COMMENT_MAX_CHARS
        if review is None:
            return CommunityPostViewerType(
                is_community=False, is_own=False, can_report=False, viewer_reported=False,
                can_comment=False, comment_block_message=None, comment_max_chars=max_chars,
            )
        is_own = item.owner_user_id == user.id
        reported = CommunityPostReport.objects.filter(content_item=item, reporter=user).exists()
        live = review.status == CommunityReviewStatus.APPROVED and item.status == ContentStatus.PUBLISHED
        _, _, business, _ = get_context_models(info)
        block = community.commenting_block(user, business) if live else None
        return CommunityPostViewerType(
            is_community=True,
            is_own=is_own,
            can_report=not is_own and not reported and live,
            viewer_reported=reported,
            can_comment=live and block is None,
            comment_block_message=community.BLOCK_MESSAGES.get(block) if block else None,
            comment_max_chars=max_chars,
        )

    @login_required
    def resolve_community_comments(self, info, content_item_id, offset=0, limit=20, expanded_thread_ids=None):
        user = info.context.user
        item = community.published_community_post(content_item_id)
        if item is None:
            return CommunityCommentPageType(items=[], has_more=False, total_count=0)
        offset = max(offset or 0, 0)
        # The app re-reads everything it has loaded (offset 0, growing limit)
        # so polling and deletes never leave a stale later page.
        limit = min(max(limit or 20, 1), COMMENT_THREADS_MAX)
        seen = comments_seen_by(user, item.id)
        top_level = list(seen.filter(parent__isnull=True)[offset:offset + limit + 1])
        has_more = len(top_level) > limit
        top_level = top_level[:limit]
        # The author always sees the outcome of their own comment, even past
        # the loaded window.
        shown = {c.id for c in top_level}
        top_level += list(
            seen.filter(parent__isnull=True, author=user, status__in=UNREVIEWED).exclude(id__in=shown)
            .order_by('-created_at', '-id')[:20]
        )
        thread_ids = [c.id for c in top_level]
        expanded = set()
        for raw in (expanded_thread_ids or [])[:5]:
            try:
                expanded.add(int(raw))
            except (TypeError, ValueError):
                continue
        expanded &= set(thread_ids)
        # Bounded however long a thread grows: the first replies of each
        # thread, more for an expanded one, plus the viewer's own unreviewed.
        replies = list(first_replies(seen.filter(parent_id__in=set(thread_ids) - expanded), REPLIES_PER_THREAD))
        if expanded:
            replies += list(first_replies(seen.filter(parent_id__in=expanded), REPLIES_EXPANDED_MAX))
        reply_ids = {r.id for r in replies}
        replies += [
            r for r in seen.filter(parent_id__in=thread_ids, author=user, status__in=UNREVIEWED)
            .order_by('-created_at', '-id')[:20]
            if r.id not in reply_ids
        ]
        replies.sort(key=lambda r: (r.created_at, r.id))
        replies_by_parent = {}
        for reply in replies:
            replies_by_parent.setdefault(reply.parent_id, []).append(reply)
        reply_counts = dict(
            community.visible_comments(item.id).filter(parent_id__in=thread_ids)
            .values('parent_id').annotate(total=Count('id')).values_list('parent_id', 'total')
        )
        page_ids = thread_ids + [r.id for r in replies]
        reactions = reaction_maps(page_ids, user)
        reported_ids = set(
            CommunityCommentReport.objects.filter(reporter=user, comment_id__in=page_ids)
            .values_list('comment_id', flat=True)
        )
        post_author_id = item.owner_user_id
        everyone = top_level + [r for rs in replies_by_parent.values() for r in rs]
        avatars = profile_pictures.picture_urls(
            {c.author_id for c in everyone} | {u.id for c in everyone for u in c.mentions.all()}
        )
        items = [
            build_community_comment_payload(
                comment, user, post_author_id, reported_ids,
                replies=[
                    build_community_comment_payload(
                        reply, user, post_author_id, reported_ids, avatars=avatars, reactions=reactions,
                    )
                    for reply in replies_by_parent.get(comment.id, [])
                ],
                avatars=avatars,
                reactions=reactions,
                reply_count=reply_counts.get(comment.id, 0),
            )
            for comment in top_level
        ]
        return CommunityCommentPageType(
            items=items,
            has_more=has_more,
            total_count=community.visible_comments(item.id).count(),
        )

    @login_required
    def resolve_community_post_participants(self, info, content_item_id):
        item = community.published_community_post(content_item_id)
        if item is None:
            return []
        participants = community.post_participants(item.id, exclude_user=info.context.user)
        avatars = profile_pictures.picture_urls([user.id for user in participants])
        return [
            CommunityParticipantType(
                id=str(user.id),
                name=community.author_display_name(user),
                is_post_author=user.id == item.owner_user_id,
                avatar_url=avatars.get(user.id),
            )
            for user in participants
        ]

    @login_required
    def resolve_my_profile_picture(self, info):
        user, account, business, _ = get_context_models(info)
        return build_my_profile_picture(user, business)

    @login_required
    def resolve_community_comment_counts(self, info, content_item_ids):
        ids = []
        # One aggregate query; enough for every card a feed session loads.
        for raw in content_item_ids[:200]:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        counts = dict(
            community.visible_comments_any_post()
            .filter(content_item_id__in=ids)
            .values('content_item_id')
            .annotate(total=Count('id'))
            .values_list('content_item_id', 'total')
        )
        return [CommunityCommentCountType(content_item_id=str(i), count=counts.get(i, 0)) for i in ids]

    @login_required
    def resolve_portal_support_conversations(self, info, status=None, search=None):
        require_staff_user(info)
        queryset = SupportConversation.objects.select_related(
            'user', 'account', 'business', 'assigned_to'
        ).prefetch_related('messages__sender_user').order_by('-last_message_at', '-updated_at')
        if status:
            queryset = queryset.filter(status=status)
        normalized_search = (search or '').strip()
        if normalized_search:
            queryset = queryset.filter(
                Q(user__username__icontains=normalized_search)
                | Q(user__email__icontains=normalized_search)
                | Q(user__first_name__icontains=normalized_search)
                | Q(user__last_name__icontains=normalized_search)
                | Q(business__name__icontains=normalized_search)
                | Q(assigned_to__username__icontains=normalized_search)
                | Q(assigned_to__email__icontains=normalized_search)
                | Q(assigned_to__first_name__icontains=normalized_search)
                | Q(assigned_to__last_name__icontains=normalized_search)
                | Q(messages__body__icontains=normalized_search)
            ).distinct()
        payloads = [build_portal_support_conversation_payload(conversation) for conversation in queryset[:100]]
        # Awaiting staff reply (unread) first, then by most recent
        payloads.sort(key=lambda c: (-c.unread_count, c.last_message_at is None, -(c.last_message_at.timestamp() if c.last_message_at else 0)))
        return payloads

    @login_required
    def resolve_portal_support_conversation(self, info, conversation_id):
        require_staff_user(info)
        conversation = (
            SupportConversation.objects.select_related('user', 'account', 'business', 'assigned_to')
            .prefetch_related('messages__sender_user')
            .filter(id=conversation_id)
            .first()
        )
        if conversation is None:
            raise GraphQLError('Support conversation not found')
        return build_portal_support_conversation_payload(conversation)

    @login_required
    def resolve_portal_content_items(self, info, channel_slug=None, status=None):
        require_staff_user(info)
        queryset = (
            ContentItem.objects.filter(community.EDITORIAL)
            .select_related('channel').prefetch_related('surfaces').order_by('-published_at', '-created_at')
        )
        if channel_slug:
            queryset = queryset.filter(channel__slug=channel_slug)
        if status:
            queryset = queryset.filter(status=status)
        items = list(queryset[:200])
        poll_payloads = build_poll_payloads(items)
        return [build_portal_content_payload(item, poll_payloads) for item in items]


class MarkMessageChannelSeen(graphene.Mutation):
    class Arguments:
        channel_id = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    total_unread_count = graphene.Int(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, channel_id):
        user, account, business, _ = get_context_models(info)

        if channel_id == 'soporte':
            conversation = get_or_create_support_conversation(user, account, business)
            latest_message = conversation.messages.order_by('-created_at').first()
            state, _ = SupportConversationState.objects.get_or_create(conversation=conversation, user=user)
            state.last_seen_message = latest_message
            state.last_seen_at = latest_message.created_at if latest_message else timezone.now()
            state.save(update_fields=['last_seen_message', 'last_seen_at', 'updated_at'])
        else:
            membership_filter = {'channel__slug': channel_id, 'user': user}
            if business is not None:
                membership_filter.update({'business': business, 'account__isnull': True})
            else:
                membership_filter.update({'account': account, 'business__isnull': True})

            membership = ChannelMembership.objects.select_related('channel').filter(**membership_filter).first()
            if membership is None:
                raise GraphQLError('Message channel not found')

            newest_visible_item = (
                get_visible_content_queryset(membership)
                .order_by('-published_at', '-created_at')
                .first()
            )
            membership.last_seen_content_item = newest_visible_item
            membership.last_seen_at = newest_visible_item.published_at if newest_visible_item else timezone.now()
            membership.save(update_fields=['last_seen_content_item', 'last_seen_at', 'updated_at'])

        inbox = build_message_inbox_payload(info)
        return MarkMessageChannelSeen(success=True, total_unread_count=inbox.total_unread_count)


class VoteOnContentPoll(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=True)
        option_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)
    poll = graphene.Field(ContentPollType, required=True)

    @classmethod
    @login_required
    @transaction.atomic
    def mutate(cls, root, info, content_item_id, option_id):
        # Serialize votes with Portal edits/closure and reject inaccessible content.
        locked = ContentItem.objects.select_for_update().filter(id=content_item_id).first()
        if locked is None:
            raise GraphQLError('Publicación no encontrada')
        item, user, account, business = get_accessible_content_item(info, content_item_id)
        now = timezone.now()
        if item.published_at > now or not item.channel.is_active:
            raise GraphQLError('Encuesta no disponible')
        # An expired/future Discover placement does not authorize voting on its own.
        discover_available = item.surfaces.filter(surface=ContentSurfaceType.DISCOVER).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now)
        ).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now)).exists()
        if not discover_available:
            membership = ChannelMembership.objects.filter(
                channel=item.channel, user=user, account=account, business=business, is_subscribed=True,
            ).first()
            if membership is None or not get_visible_content_queryset(membership).filter(pk=item.pk).exists():
                raise GraphQLError('Encuesta no disponible')
        poll = (locked.metadata or {}).get('poll')
        if not poll or poll.get('closed', False):
            raise GraphQLError('La encuesta está cerrada o no está disponible')
        if option_id not in [option['id'] for option in poll['options']]:
            raise GraphQLError('Opción inválida')
        ContentPollVote.objects.update_or_create(
            content_item=locked, user=user, defaults={'option_id': option_id},
        )
        return VoteOnContentPoll(success=True, poll=build_poll_payload(locked, user.id))


class ReactToMessageContent(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=True)
        emoji = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    content_item_id = graphene.ID(required=True)
    reaction_summary = graphene.List(MessageReactionType, required=True)
    viewer_reaction = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, content_item_id, emoji):
        user, account, business, _ = get_context_models(info)

        reaction_type = ReactionType.objects.filter(
            emoji=emoji,
            is_active=True,
            is_selectable=True,
        ).first()
        if reaction_type is None:
            raise GraphQLError('Reaction type not found')

        # Same reach as reading it: anything on Descubrir, otherwise only
        # through a channel this context follows. Comunidad posts live in a
        # channel nobody subscribes to.
        item, user, account, business = get_accessible_content_item(info, content_item_id)

        reaction_filter = {'content_item': item, 'user': user}
        if business is not None:
            reaction_filter.update({'business': business, 'account__isnull': True})
        else:
            reaction_filter.update({'account': account, 'business__isnull': True})

        existing_reaction = ContentReaction.objects.filter(**reaction_filter).first()
        if existing_reaction and existing_reaction.reaction_type_id == reaction_type.id:
            existing_reaction.delete()
            viewer_reaction = ''
        else:
            if existing_reaction:
                existing_reaction.reaction_type = reaction_type
                existing_reaction.save(update_fields=['reaction_type'])
            else:
                create_kwargs = {
                    'content_item': item,
                    'reaction_type': reaction_type,
                    'user': user,
                }
                if business is not None:
                    create_kwargs['business'] = business
                else:
                    create_kwargs['account'] = account
                ContentReaction.objects.create(**create_kwargs)
            viewer_reaction = reaction_type.emoji

        reaction_counts = {}
        for reaction in item.reactions.select_related('reaction_type').all():
            reaction_counts[reaction.reaction_type.emoji] = reaction_counts.get(reaction.reaction_type.emoji, 0) + 1

        reaction_summary = [
            MessageReactionType(emoji=reaction_emoji, count=count)
            for reaction_emoji, count in sorted(reaction_counts.items(), key=lambda item: item[1], reverse=True)
        ]

        return ReactToMessageContent(
            success=True,
            content_item_id=str(item.id),
            reaction_summary=reaction_summary,
            viewer_reaction=viewer_reaction,
        )


class TrackContentPlatformClick(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=True)
        platform = graphene.String(required=True)
        surface = graphene.String(required=True)

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, content_item_id, platform, surface):
        user, account, business, _ = get_context_models(info)

        normalized_platform = (platform or '').upper()
        normalized_surface = (surface or '').upper()

        if normalized_platform not in ContentPlatformType.values:
            raise GraphQLError('Unsupported platform')
        if normalized_surface not in ContentSurfaceType.values:
            raise GraphQLError('Unsupported surface')

        item = ContentItem.objects.filter(id=content_item_id, status=ContentStatus.PUBLISHED).first()
        if item is None:
            raise GraphQLError('Content item not found')

        membership_filter = {'channel': item.channel, 'user': user, 'is_subscribed': True}
        if business is not None:
            membership_filter.update({'business': business, 'account__isnull': True})
        else:
            membership_filter.update({'account': account, 'business__isnull': True})

        membership = ChannelMembership.objects.filter(**membership_filter).first()
        if membership is None or not get_visible_content_queryset(membership).filter(id=item.id).exists():
            raise GraphQLError('Content item not available in this context')

        create_kwargs = {
            'content_item': item,
            'user': user,
            'platform': normalized_platform,
            'surface': normalized_surface,
        }
        if business is not None:
            create_kwargs['business'] = business
        else:
            create_kwargs['account'] = account

        ContentPlatformClick.objects.create(**create_kwargs)
        return TrackContentPlatformClick(success=True)


class SendSupportMessage(graphene.Mutation):
    class Arguments:
        body = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    message = graphene.Field(MessageThreadItemType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, body):
        # Lazy: assistant.service imports this module.
        from assistant import service as assistant_service

        user, account, business, jwt_context = get_context_models(info)
        clean_body = (body or '').strip()
        if not clean_body:
            raise GraphQLError('Message body is required')

        # Older builds send here and poll the thread: Confio Assistant answers inline
        # (or the team is pushed when the thread is in human mode).
        outcome = assistant_service.ask(user, account, business, jwt_context, clean_body, can_navigate=False)
        message = outcome.user_message

        return SendSupportMessage(
            success=True,
            message=MessageThreadItemType(
                id=str(message.id),
                type='support',
                occurred_at=message.created_at,
                tag='',
                title='',
                body=message.body,
                text=message.body,
                time=humanize_relative(message.created_at),
                link='',
                platforms=[],
                platform_links=[],
                reaction_summary=[],
                viewer_reaction='',
                can_react=False,
                sender_type=message.sender_type,
                sender_name=get_support_sender_name(message),
            ),
        )


class UpdateMessageChannelMute(graphene.Mutation):
    class Arguments:
        channel_id = graphene.String(required=True)
        is_muted = graphene.Boolean(required=True)

    success = graphene.Boolean(required=True)
    channel_id = graphene.String(required=True)
    is_muted = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, channel_id, is_muted):
        if channel_id == 'soporte':
            raise GraphQLError('Support channel cannot be muted')

        user, account, business, _ = get_context_models(info)
        membership_filter = {'channel__slug': channel_id, 'user': user}
        if business is not None:
            membership_filter.update({'business': business, 'account__isnull': True})
        else:
            membership_filter.update({'account': account, 'business__isnull': True})

        membership = ChannelMembership.objects.select_related('channel').filter(**membership_filter).first()
        if membership is None:
            raise GraphQLError('Message channel not found')

        membership.push_level = 'NONE' if is_muted else 'DEFAULT'
        membership.save(update_fields=['push_level', 'updated_at'])

        return UpdateMessageChannelMute(
            success=True,
            channel_id=channel_id,
            is_muted=is_muted,
        )


class PortalSendSupportReply(graphene.Mutation):
    class Arguments:
        conversation_id = graphene.ID(required=True)
        body = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    conversation = graphene.Field(PortalSupportConversationType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, conversation_id, body):
        staff_user = require_staff_user(info)
        clean_body = (body or '').strip()
        if not clean_body:
            raise GraphQLError('Reply body is required')

        conversation = SupportConversation.objects.select_related(
            'user', 'account', 'business', 'assigned_to'
        ).prefetch_related('messages__sender_user').filter(id=conversation_id).first()
        if conversation is None:
            raise GraphQLError('Support conversation not found')

        reply = SupportMessage.objects.create(
            conversation=conversation,
            sender_type='AGENT',
            sender_user=staff_user,
            message_type='TEXT',
            body=clean_body,
            metadata={},
        )
        conversation.assigned_to = staff_user
        conversation.last_message_at = timezone.now()
        conversation.save(update_fields=['assigned_to', 'last_message_at', 'updated_at'])
        try:
            send_support_reply_push(reply.id)
        except Exception:
            logger.exception('Failed to send support reply push', extra={'conversation_id': conversation.id, 'message_id': reply.id})
        conversation.refresh_from_db()
        return PortalSendSupportReply(
            success=True,
            conversation=build_portal_support_conversation_payload(conversation),
        )


class PortalSetSupportConversationStatus(graphene.Mutation):
    class Arguments:
        conversation_id = graphene.ID(required=True)
        status = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    conversation = graphene.Field(PortalSupportConversationType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, conversation_id, status):
        require_staff_user(info)
        if status not in {'OPEN', 'CLOSED'}:
            raise GraphQLError('Invalid support conversation status')
        conversation = SupportConversation.objects.select_related(
            'user', 'account', 'business', 'assigned_to'
        ).prefetch_related('messages__sender_user').filter(id=conversation_id).first()
        if conversation is None:
            raise GraphQLError('Support conversation not found')
        conversation.status = status
        conversation.save(update_fields=['status', 'updated_at'])
        return PortalSetSupportConversationStatus(
            success=True,
            conversation=build_portal_support_conversation_payload(conversation),
        )


class PortalSaveContentItem(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=False)
        channel_slug = graphene.String(required=True)
        item_type = graphene.String(required=True)
        title = graphene.String(required=False)
        body = graphene.String(required=False)
        tag = graphene.String(required=False)
        status = graphene.String(required=True)
        published_at = graphene.DateTime(required=False)
        visibility_policy = graphene.String(required=False)
        send_push = graphene.Boolean(required=False)
        send_in_app = graphene.Boolean(required=False)
        metadata = graphene.JSONString(required=False)
        surfaces = graphene.List(graphene.String, required=False)

    success = graphene.Boolean(required=True)
    content_item = graphene.Field(PortalContentItemType, required=True)

    @classmethod
    @login_required
    @transaction.atomic
    def mutate(
        cls,
        root,
        info,
        channel_slug,
        item_type,
        status,
        content_item_id=None,
        title=None,
        body=None,
        tag=None,
        published_at=None,
        visibility_policy=None,
        send_push=False,
        send_in_app=True,
        metadata=None,
        surfaces=None,
    ):
        staff_user = require_staff_user(info)
        channel = Channel.objects.filter(slug=channel_slug).first()
        if channel is None:
            raise GraphQLError('Channel not found')
        if item_type not in {'TEXT', 'NEWS', 'VIDEO'}:
            raise GraphQLError('Invalid content item type')
        if status not in {'DRAFT', 'SCHEDULED', 'PUBLISHED', 'ARCHIVED'}:
            raise GraphQLError('Invalid content item status')
        if visibility_policy is not None and visibility_policy not in {
            VisibilityPolicy.FROM_PUBLISH_TIME,
            VisibilityPolicy.BACKLOG,
            VisibilityPolicy.PINNED,
        }:
            raise GraphQLError('Invalid visibility policy')

        # Member posts are never edited or published editorially: each
        # revision would skip the AI review. Staff moderate them in the admin.
        if channel.slug == community.COMMUNITY_CHANNEL_SLUG:
            raise GraphQLError('Comunidad posts are moderated in the admin, not written here')
        if content_item_id:
            item = ContentItem.objects.select_for_update().filter(id=content_item_id).first()
            if item is None:
                raise GraphQLError('Content item not found')
            if community.is_member_content(item):
                raise GraphQLError('Comunidad posts are moderated in the admin, not edited here')
        else:
            item = ContentItem(channel=channel, author_user=staff_user)

        validate_poll_metadata(metadata if metadata is not None else {}, item.metadata, bool(item.pk and item.poll_votes.exists()))

        item.channel = channel
        item.author_user = staff_user
        item.item_type = item_type
        item.status = status
        item.title = title or ''
        item.body = body or ''
        item.tag = tag or ''
        item.published_at = published_at or (timezone.now() if status == 'PUBLISHED' else None)
        if visibility_policy is not None:
            item.visibility_policy = visibility_policy
        item.send_push = bool(send_push)
        item.send_in_app = bool(send_in_app)
        item.metadata = metadata or {}
        item.save()

        if surfaces is not None:
            normalized_surfaces = [surface for surface in surfaces if surface in {'CHANNEL', 'DISCOVER', 'HOME_HIGHLIGHT'}]
            item.surfaces.exclude(surface__in=normalized_surfaces).delete()
            for surface in normalized_surfaces:
                item.surfaces.update_or_create(surface=surface, defaults={'is_pinned': False})

        item.refresh_from_db()
        return PortalSaveContentItem(
            success=True,
            content_item=build_portal_content_payload(item),
        )


class PortalDeleteContentItem(graphene.Mutation):
    class Arguments:
        content_item_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)
    deleted_content_item_id = graphene.ID(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, content_item_id):
        require_staff_user(info)
        item = ContentItem.objects.filter(id=content_item_id).first()
        if item is None:
            raise GraphQLError('Content item not found')
        if community.is_member_content(item):
            raise GraphQLError('Comunidad posts are taken down in the admin, not deleted here')

        deleted_content_item_id = str(item.id)
        item.delete()
        return PortalDeleteContentItem(
            success=True,
            deleted_content_item_id=deleted_content_item_id,
        )


class RequestPublicationImageUpload(graphene.Mutation):
    class Arguments:
        filename = graphene.String(required=False)
        content_type = graphene.String(required=False, default_value='image/webp')

    success = graphene.Boolean(required=True)
    error = graphene.String()
    upload = graphene.Field(PublicationImageUploadType)

    @classmethod
    @login_required
    def mutate(cls, root, info, filename=None, content_type='image/webp'):
        staff_user = require_staff_user(info)
        allowed_content_types = {'image/webp', 'image/jpeg', 'image/png'}
        if content_type not in allowed_content_types:
            return RequestPublicationImageUpload(
                success=False,
                error='Unsupported content type',
                upload=None,
            )

        publications_bucket = getattr(settings, 'AWS_PUBLICATIONS_BUCKET', None)
        if not publications_bucket:
            return RequestPublicationImageUpload(
                success=False,
                error='AWS_PUBLICATIONS_BUCKET is not configured',
                upload=None,
            )

        prefix = getattr(settings, 'AWS_S3_PUBLICATIONS_PREFIX', 'publications/images/')
        dated_prefix = timezone.now().strftime('%Y/%m')
        extension = os.path.splitext(filename or '')[1] or '.webp'
        key = build_s3_key(
            f"{prefix.rstrip('/')}/{dated_prefix}",
            filename or f'publication{extension}',
        )

        metadata = {
            'uploaded-by': str(staff_user.id),
            'uploaded-for': 'publication',
        }

        try:
            presigned = generate_presigned_post(
                key=key,
                content_type=content_type,
                metadata=metadata,
                bucket=publications_bucket,
            )
        except Exception as error:
            logger.exception('Failed to generate publication image upload', extra={'staff_user_id': staff_user.id})
            return RequestPublicationImageUpload(success=False, error=str(error), upload=None)

        return RequestPublicationImageUpload(
            success=True,
            error=None,
            upload=PublicationImageUploadType(
                url=presigned['url'],
                key=presigned['key'],
                method=presigned['method'],
                fields=presigned.get('fields'),
                expires_in=presigned['expires_in'],
                public_url=public_s3_url(
                    presigned['key'],
                    bucket=publications_bucket,
                ),
            ),
        )


class Mutation(graphene.ObjectType):
    vote_on_content_poll = VoteOnContentPoll.Field()
    mark_message_channel_seen = MarkMessageChannelSeen.Field()
    react_to_message_content = ReactToMessageContent.Field()
    track_content_platform_click = TrackContentPlatformClick.Field()
    send_support_message = SendSupportMessage.Field()
    update_message_channel_mute = UpdateMessageChannelMute.Field()
    portal_send_support_reply = PortalSendSupportReply.Field()
    portal_set_support_conversation_status = PortalSetSupportConversationStatus.Field()
    portal_save_content_item = PortalSaveContentItem.Field()
    portal_delete_content_item = PortalDeleteContentItem.Field()
    request_publication_image_upload = RequestPublicationImageUpload.Field()
    request_community_image_upload = RequestCommunityImageUpload.Field()
    create_community_post = CreateCommunityPost.Field()
    delete_community_post = DeleteCommunityPost.Field()
    report_community_post = ReportCommunityPost.Field()
    create_community_comment = CreateCommunityComment.Field()
    delete_community_comment = DeleteCommunityComment.Field()
    report_community_comment = ReportCommunityComment.Field()
    react_to_community_comment = ReactToCommunityComment.Field()
    request_profile_picture_upload = RequestProfilePictureUpload.Field()
    submit_profile_picture = SubmitProfilePicture.Field()
    remove_profile_picture = RemoveProfilePicture.Field()
