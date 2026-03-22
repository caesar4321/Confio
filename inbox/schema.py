import graphene
import logging
import os
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.conf import settings
from django.utils import timezone
from graphql import GraphQLError
from graphql_jwt.decorators import login_required

from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account, Business
from security.s3_utils import build_s3_key, generate_presigned_post, public_s3_url

from .models import (
    Channel,
    ChannelScope,
    ChannelMembership,
    ContentReaction,
    ContentItem,
    ContentSurfaceType,
    OwnerType,
    ContentStatus,
    ReactionType,
    SupportConversation,
    SupportConversationState,
    SupportMessage,
    VisibilityPolicy,
)
from .push_service import send_support_reply_push, send_support_staff_push
from .tasks import send_content_item_push_task

logger = logging.getLogger(__name__)

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
            body='Hola, somos el equipo de Confío. ¿En qué podemos ayudarte hoy?',
            metadata={},
        )
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=['last_message_at', 'updated_at'])

    return conversation


class MessageThreadItemType(graphene.ObjectType):
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


class PlatformLinkType(graphene.ObjectType):
    platform = graphene.String(required=True)
    url = graphene.String(required=True)


class MessageReactionType(graphene.ObjectType):
    emoji = graphene.String(required=True)
    count = graphene.Int(required=True)


class DiscoverFeedItemType(graphene.ObjectType):
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


class DiscoverFeedPageType(graphene.ObjectType):
    items = graphene.List(DiscoverFeedItemType, required=True)
    has_more = graphene.Boolean(required=True)


class PortalContentItemType(graphene.ObjectType):
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

    # Unread if the last message is from the user (awaiting staff reply)
    unread_count = 1 if latest_message and latest_message.sender_type == 'USER' else 0

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


def build_portal_content_payload(item: ContentItem):
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
    )


def build_discover_feed_item_payload(item: ContentItem, user, account, business):
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
        reaction_summary=[
            MessageReactionType(emoji=emoji, count=count)
            for emoji, count in sorted(reaction_counts.items(), key=lambda reaction_item: reaction_item[1], reverse=True)
        ],
        viewer_reaction=viewer_reaction,
        can_react=True,
    )


def get_accessible_content_item(info, content_item_id):
    user, account, business, _ = get_context_models(info)
    item = (
        ContentItem.objects.select_related('channel')
        .prefetch_related('reactions__reaction_type', 'surfaces')
        .filter(id=content_item_id, status=ContentStatus.PUBLISHED, published_at__isnull=False)
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
        name='Soporte',
        subtitle='Equipo Confío · Respuesta en ~2h',
        preview=latest_message.body if latest_message else 'En que podemos ayudarte hoy?',
        time=humanize_relative(latest_message.created_at) if latest_message else 'Ahora',
        unread_count=unread_count,
        is_muted=False,
        messages=thread_messages,
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


class Query(graphene.ObjectType):
    message_inbox = graphene.Field(MessageInboxType, context_key=graphene.String(required=False))
    message_inbox_unread_count = graphene.Int(context_key=graphene.String(required=False))
    discover_post = graphene.Field(
        DiscoverFeedItemType,
        content_item_id=graphene.ID(required=True),
    )
    discover_feed = graphene.Field(
        DiscoverFeedPageType,
        offset=graphene.Int(required=False),
        limit=graphene.Int(required=False),
    )
    portal_support_conversations = graphene.List(
        PortalSupportConversationType,
        status=graphene.String(required=False),
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
    def resolve_discover_post(self, info, content_item_id):
        item, user, account, business = get_accessible_content_item(info, content_item_id)
        return build_discover_feed_item_payload(item, user, account, business)

    @login_required
    def resolve_discover_feed(self, info, offset=0, limit=10):
        user, account, business, _ = get_context_models(info)
        offset = max(offset or 0, 0)
        limit = min(max(limit or 10, 1), 20)

        queryset = (
            ContentItem.objects.select_related('channel')
            .prefetch_related('reactions__reaction_type', 'surfaces')
            .filter(
                status=ContentStatus.PUBLISHED,
                published_at__isnull=False,
                surfaces__surface=ContentSurfaceType.DISCOVER,
            )
            .distinct()
            .order_by('-surfaces__is_pinned', 'surfaces__rank', '-published_at', '-created_at')
        )
        page_items = list(queryset[offset:offset + limit + 1])
        has_more = len(page_items) > limit
        if has_more:
            page_items = page_items[:limit]

        return DiscoverFeedPageType(
            items=[build_discover_feed_item_payload(item, user, account, business) for item in page_items],
            has_more=has_more,
        )

    @login_required
    def resolve_portal_support_conversations(self, info, status=None):
        require_staff_user(info)
        queryset = SupportConversation.objects.select_related(
            'user', 'account', 'business', 'assigned_to'
        ).prefetch_related('messages__sender_user').order_by('-last_message_at', '-updated_at')
        if status:
            queryset = queryset.filter(status=status)
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
        queryset = ContentItem.objects.select_related('channel').prefetch_related('surfaces').order_by('-published_at', '-created_at')
        if channel_slug:
            queryset = queryset.filter(channel__slug=channel_slug)
        if status:
            queryset = queryset.filter(status=status)
        return [build_portal_content_payload(item) for item in queryset[:200]]


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


class SendSupportMessage(graphene.Mutation):
    class Arguments:
        body = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    message = graphene.Field(MessageThreadItemType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, body):
        user, account, business, _ = get_context_models(info)
        clean_body = (body or '').strip()
        if not clean_body:
            raise GraphQLError('Message body is required')

        conversation = get_or_create_support_conversation(user, account, business)
        message = SupportMessage.objects.create(
            conversation=conversation,
            sender_type='USER',
            sender_user=user,
            message_type='TEXT',
            body=clean_body,
            metadata={},
        )
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=['last_message_at', 'updated_at'])

        try:
            send_support_staff_push(message.id)
        except Exception:
            logger.exception('Failed to send support staff push', extra={'conversation_id': conversation.id, 'message_id': message.id})

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

        if content_item_id:
            item = ContentItem.objects.select_related('channel').prefetch_related('surfaces').filter(id=content_item_id).first()
            if item is None:
                raise GraphQLError('Content item not found')
        else:
            item = ContentItem(channel=channel, author_user=staff_user)

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

        should_send_push_now = (
            item.status == ContentStatus.PUBLISHED
            and item.send_push
            and item.published_at is not None
            and item.push_sent_at is None
        )
        if should_send_push_now:
            def _send_portal_publish_push():
                try:
                    send_content_item_push_task.delay(item.id)
                except Exception:
                    logger.exception(
                        'Failed to send portal publication push',
                        extra={'content_item_id': item.id},
                    )

            transaction.on_commit(_send_portal_publish_push)

        item.refresh_from_db()
        return PortalSaveContentItem(
            success=True,
            content_item=build_portal_content_payload(item),
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
    mark_message_channel_seen = MarkMessageChannelSeen.Field()
    react_to_message_content = ReactToMessageContent.Field()
    send_support_message = SendSupportMessage.Field()
    update_message_channel_mute = UpdateMessageChannelMute.Field()
    portal_send_support_reply = PortalSendSupportReply.Field()
    portal_set_support_conversation_status = PortalSetSupportConversationStatus.Field()
    portal_save_content_item = PortalSaveContentItem.Field()
    request_publication_image_upload = RequestPublicationImageUpload.Field()
