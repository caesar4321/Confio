import logging
from typing import Dict, List, Tuple

from django.db.models import Q
from django.utils import timezone

from notifications.fcm_service import send_batch_notifications
from notifications.models import FCMDeviceToken, NotificationPreference

from .models import (
    ChannelScope,
    ChannelMembership,
    ContentItem,
    ContentNotificationPriority,
    ContentStatus,
    ContentSurfaceType,
    NotificationLevel,
    OwnerType,
    SupportMessage,
)

logger = logging.getLogger(__name__)

CHANNEL_ID_MESSAGES = 'messages'
CHANNEL_ID_DISCOVER = 'discover'
MAX_PUSH_CONTENT_BODY_CHARS = 240
DISCOVER_TAG_COLORS = {
    'VIDEO': '#FF4444',
    'NEWS': '#F59E0B',
    'TEXT': '#1DB587',
}


def _content_push_body_preview(item: ContentItem) -> str:
    text = (item.body or '').strip()
    if not text:
        return ''
    if len(text) <= MAX_PUSH_CONTENT_BODY_CHARS:
        return text
    return f"{text[:MAX_PUSH_CONTENT_BODY_CHARS - 1].rstrip()}…"


def _is_push_allowed_for_membership(membership: ChannelMembership, item: ContentItem) -> bool:
    if not membership.is_subscribed:
        return False
    if membership.push_level == NotificationLevel.NONE:
        return False
    if (
        membership.push_level == NotificationLevel.IMPORTANT_ONLY
        and item.notification_priority != ContentNotificationPriority.IMPORTANT
    ):
        return False
    return True


def _get_user_push_enabled_map(user_ids: List[int]) -> Dict[int, bool]:
    prefs_by_user = {
        pref.user_id: pref
        for pref in NotificationPreference.objects.filter(user_id__in=user_ids)
    }
    result: Dict[int, bool] = {}
    for user_id in user_ids:
        pref = prefs_by_user.get(user_id)
        result[user_id] = pref.push_enabled if pref else True
    return result


def _get_user_announcement_enabled_map(user_ids: List[int]) -> Dict[int, bool]:
    prefs_by_user = {
        pref.user_id: pref
        for pref in NotificationPreference.objects.filter(user_id__in=user_ids)
    }
    result: Dict[int, bool] = {}
    for user_id in user_ids:
        pref = prefs_by_user.get(user_id)
        result[user_id] = pref.push_enabled and pref.push_announcements if pref else True
    return result


def _collect_active_tokens_for_users(user_ids: List[int]) -> Dict[int, List[Tuple[str, int]]]:
    tokens_by_user: Dict[int, List[Tuple[str, int]]] = {}
    token_rows = FCMDeviceToken.objects.filter(
        user_id__in=user_ids,
        is_active=True,
    ).values_list('user_id', 'token', 'id')
    for user_id, token, token_id in token_rows:
        tokens_by_user.setdefault(user_id, []).append((token, token_id))
    return tokens_by_user


def _collect_unique_tokens_for_users(
    user_ids: List[int],
    tokens_by_user: Dict[int, List[Tuple[str, int]]],
) -> List[Tuple[str, int]]:
    unique_tokens: List[Tuple[str, int]] = []
    seen_tokens = set()
    for user_id in user_ids:
        for token, token_id in tokens_by_user.get(user_id, []):
            dedupe_key = (user_id, token_id)
            if dedupe_key in seen_tokens:
                continue
            seen_tokens.add(dedupe_key)
            unique_tokens.append((token, token_id))
    return unique_tokens


def _build_context_payload(*, account_id=None, account_type=None, account_index=None, business_id=None, business_name=None):
    if business_id is not None:
        return {
            'account_context': 'business',
            'business_id': str(business_id),
            'business_name': business_name or '',
        }

    return {
        'account_context': 'personal',
        'account_id': str(account_id) if account_id is not None else '',
        'account_type': account_type or 'personal',
        'account_index': str(account_index if account_index is not None else 0),
    }


def _channel_push_requires_context(item: ContentItem) -> bool:
    metadata = item.metadata or {}
    if 'push_requires_context' in metadata:
        return bool(metadata['push_requires_context'])

    return (
        item.channel.channel_scope in {ChannelScope.BUSINESS, ChannelScope.ACCOUNT}
        or item.channel.owner_type in {OwnerType.BUSINESS, OwnerType.USER}
    )


def _discover_push_requires_context(item: ContentItem) -> bool:
    metadata = item.metadata or {}
    if 'push_requires_context' in metadata:
        return bool(metadata['push_requires_context'])

    return (
        item.owner_type in {OwnerType.BUSINESS, OwnerType.USER}
        and metadata.get('discover_scope') in {'BUSINESS', 'ACCOUNT'}
    )


def _discover_item_type(item: ContentItem) -> str:
    if item.item_type == 'VIDEO':
        return 'video'
    if item.item_type == 'NEWS':
        return 'news'
    return 'product'


def _build_channel_action_url(item: ContentItem) -> str:
    return f'confio://messages/{item.channel.slug}'


def _build_discover_action_url(item: ContentItem) -> str:
    return f'confio://discover/post/{item.id}'


def _build_support_action_url() -> str:
    return 'confio://messages/soporte'


def _get_support_sender_name(message: SupportMessage) -> str:
    if message.sender_user_id:
        full_name = f'{message.sender_user.first_name or ""} {message.sender_user.last_name or ""}'.strip()
        if full_name:
            return full_name
        if message.sender_user.username:
            return message.sender_user.username
    return 'Soporte de Confío'


def _build_channel_push_payload(item: ContentItem, membership: ChannelMembership) -> Dict[str, str]:
    payload = {
        'action_url': _build_channel_action_url(item),
        'content_item_id': str(item.id),
        'channel_id': item.channel.slug,
        'data_channel_id': item.channel.slug,
        'data_content_item_id': str(item.id),
        'data_title': item.title or '',
        'data_body': _content_push_body_preview(item),
        'data_tag': item.tag or '',
        'data_item_type': item.item_type.lower(),
    }
    if _channel_push_requires_context(item):
        payload.update(
            _build_context_payload(
                account_id=membership.account_id,
                account_type=membership.account.account_type if membership.account_id else None,
                account_index=membership.account.account_index if membership.account_id else None,
                business_id=membership.business_id,
                business_name=membership.business.name if membership.business_id else None,
            )
        )
    return payload


def _build_discover_push_payload(item: ContentItem, membership: ChannelMembership | None = None) -> Dict[str, str]:
    tag_color = str((item.metadata or {}).get('tag_color') or DISCOVER_TAG_COLORS.get(item.item_type, '#1DB587'))
    payload = {
        'action_url': _build_discover_action_url(item),
        'content_item_id': str(item.id),
        'data_content_item_id': str(item.id),
        'data_title': item.title or '',
        'data_body': _content_push_body_preview(item),
        'data_tag': item.tag or '',
        'data_item_type': _discover_item_type(item),
        'data_tag_color': tag_color,
        'data_thumbnail': 'true' if item.item_type == 'VIDEO' else 'false',
    }
    if _discover_push_requires_context(item) and membership is not None:
        payload.update(
            _build_context_payload(
                account_id=membership.account_id,
                account_type=membership.account.account_type if membership.account_id else None,
                account_index=membership.account.account_index if membership.account_id else None,
                business_id=membership.business_id,
                business_name=membership.business.name if membership.business_id else None,
            )
        )
    return payload


def _build_support_push_payload(message: SupportMessage) -> Dict[str, str]:
    conversation = message.conversation
    payload = {
        'action_url': _build_support_action_url(),
        'conversation_id': str(conversation.id),
        'data_channel_id': 'soporte',
        'data_conversation_id': str(conversation.id),
        'data_message_id': str(message.id),
        'data_sender_type': message.sender_type.lower(),
        'data_sender_name': _get_support_sender_name(message),
        'data_body': message.body or '',
    }
    payload.update(
        _build_context_payload(
            account_id=conversation.account_id,
            account_type=conversation.account.account_type if conversation.account_id else None,
            account_index=conversation.account.account_index if conversation.account_id else None,
            business_id=conversation.business_id,
            business_name=conversation.business.name if conversation.business_id else None,
        )
    )
    return payload


def _get_push_surface(item: ContentItem) -> str:
    requested_surface = (item.metadata or {}).get('push_surface')
    if requested_surface in {
        ContentSurfaceType.CHANNEL,
        ContentSurfaceType.DISCOVER,
    }:
        return requested_surface

    surfaces = set(item.surfaces.values_list('surface', flat=True))
    # Shared posts should notify from the channel thread by default.
    if ContentSurfaceType.CHANNEL in surfaces:
        return ContentSurfaceType.CHANNEL
    if ContentSurfaceType.DISCOVER in surfaces:
        return ContentSurfaceType.DISCOVER
    return ContentSurfaceType.CHANNEL


def _send_channel_push(item: ContentItem) -> Dict[str, int]:
    memberships = list(
        ChannelMembership.objects.select_related('account', 'business', 'channel')
        .filter(channel=item.channel)
        .exclude(
            Q(account__deleted_at__isnull=False) | Q(business__deleted_at__isnull=False)
        )
    )
    memberships = [membership for membership in memberships if _is_push_allowed_for_membership(membership, item)]

    if not memberships:
        return {'sent': 0, 'failed': 0}

    user_ids = sorted({membership.user_id for membership in memberships})
    push_enabled_map = _get_user_push_enabled_map(user_ids)
    tokens_by_user = _collect_active_tokens_for_users(user_ids)

    if not _channel_push_requires_context(item):
        eligible_user_ids = [
            user_id for user_id in user_ids
            if push_enabled_map.get(user_id, True)
        ]
        tokens = _collect_unique_tokens_for_users(eligible_user_ids, tokens_by_user)
        if not tokens:
            return {'sent': 0, 'failed': 0}

        body = item.title or item.body or item.channel.title
        return send_batch_notifications(
            tokens=tokens,
            title=item.channel.title,
            body=body[:180],
            data={
                'action_url': _build_channel_action_url(item),
                'content_item_id': str(item.id),
                'channel_id': item.channel.slug,
                'data_channel_id': item.channel.slug,
                'data_content_item_id': str(item.id),
                'data_title': item.title or '',
                'data_body': _content_push_body_preview(item),
                'data_tag': item.tag or '',
                'data_item_type': item.item_type.lower(),
            },
            badge_count=None,
            notification=None,
            channel_id=CHANNEL_ID_MESSAGES,
        )

    total_sent = 0
    total_failed = 0
    seen_tokens = set()
    for membership in memberships:
        if not push_enabled_map.get(membership.user_id, True):
            continue
        tokens = []
        for token, token_id in tokens_by_user.get(membership.user_id, []):
            dedupe_key = (membership.user_id, token_id)
            if dedupe_key in seen_tokens:
                continue
            seen_tokens.add(dedupe_key)
            tokens.append((token, token_id))
        if not tokens:
            continue

        body = item.title or item.body or item.channel.title
        result = send_batch_notifications(
            tokens=tokens,
            title=item.channel.title,
            body=body[:180],
            data=_build_channel_push_payload(item, membership),
            badge_count=None,
            notification=None,
            channel_id=CHANNEL_ID_MESSAGES,
        )
        total_sent += result.get('sent', 0)
        total_failed += result.get('failed', 0)

    return {'sent': total_sent, 'failed': total_failed}


def _send_discover_push(item: ContentItem) -> Dict[str, int]:
    if _discover_push_requires_context(item):
        memberships = list(
            ChannelMembership.objects.select_related('account', 'business')
            .filter(channel=item.channel)
            .exclude(Q(account__deleted_at__isnull=False) | Q(business__deleted_at__isnull=False))
        )
        memberships = [membership for membership in memberships if _is_push_allowed_for_membership(membership, item)]
        if not memberships:
            return {'sent': 0, 'failed': 0}

        user_ids = sorted({membership.user_id for membership in memberships})
        announcement_enabled_map = _get_user_announcement_enabled_map(user_ids)
        tokens_by_user = _collect_active_tokens_for_users(user_ids)

        total_sent = 0
        total_failed = 0
        seen_tokens = set()
        for membership in memberships:
            if not announcement_enabled_map.get(membership.user_id, True):
                continue
            tokens = []
            for token, token_id in tokens_by_user.get(membership.user_id, []):
                dedupe_key = (membership.user_id, token_id)
                if dedupe_key in seen_tokens:
                    continue
                seen_tokens.add(dedupe_key)
                tokens.append((token, token_id))
            if not tokens:
                continue

            result = send_batch_notifications(
                tokens=tokens,
                title='Descubrir en Confío',
                body=(item.title or item.body or 'Nueva publicación en Descubrir')[:180],
                data=_build_discover_push_payload(item, membership),
                badge_count=None,
                notification=None,
                channel_id=CHANNEL_ID_DISCOVER,
            )
            total_sent += result.get('sent', 0)
            total_failed += result.get('failed', 0)

        return {'sent': total_sent, 'failed': total_failed}

    user_ids = list(
        FCMDeviceToken.objects.filter(is_active=True, user__is_active=True)
        .values_list('user_id', flat=True)
        .distinct()
    )
    if not user_ids:
        return {'sent': 0, 'failed': 0}

    announcement_enabled_map = _get_user_announcement_enabled_map(user_ids)
    tokens_by_user = _collect_active_tokens_for_users(user_ids)

    total_sent = 0
    total_failed = 0
    for user_id in user_ids:
        if not announcement_enabled_map.get(user_id, True):
            continue
        tokens = tokens_by_user.get(user_id, [])
        if not tokens:
            continue
        result = send_batch_notifications(
            tokens=tokens,
            title='Descubrir en Confío',
            body=(item.title or item.body or 'Nueva publicación en Descubrir')[:180],
            data=_build_discover_push_payload(item),
            badge_count=None,
            notification=None,
            channel_id=CHANNEL_ID_DISCOVER,
        )
        total_sent += result.get('sent', 0)
        total_failed += result.get('failed', 0)

    return {'sent': total_sent, 'failed': total_failed}


def send_content_item_push(content_item_id: int) -> Dict[str, int]:
    item = (
        ContentItem.objects.select_related('channel')
        .prefetch_related('surfaces')
        .filter(id=content_item_id)
        .first()
    )
    if item is None:
        raise ValueError('Content item not found')
    if item.status != ContentStatus.PUBLISHED:
        raise ValueError('Content item is not published')
    if not item.send_push:
        raise ValueError('Content item is not configured for push delivery')
    if item.push_sent_at is not None:
        return {'sent': 0, 'failed': 0}

    push_surface = _get_push_surface(item)
    if push_surface == ContentSurfaceType.DISCOVER:
        result = _send_discover_push(item)
    else:
        result = _send_channel_push(item)

    if result.get('sent', 0) == 0 and result.get('failed', 0) > 0:
        raise RuntimeError(f'Push delivery failed for content item {item.id}')

    item.push_sent_at = timezone.now()
    item.save(update_fields=['push_sent_at', 'updated_at'])
    logger.info(
        'Inbox content push sent',
        extra={
            'content_item_id': item.id,
            'surface': push_surface,
            'sent': result.get('sent', 0),
            'failed': result.get('failed', 0),
        },
    )
    return result


def send_support_staff_push(support_message_id: int) -> Dict[str, int]:
    """Send push notification to all staff users when a user sends a support message."""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    message = (
        SupportMessage.objects.select_related(
            'conversation__user',
            'conversation__account',
            'conversation__business',
            'sender_user',
        )
        .filter(id=support_message_id, sender_type='USER')
        .first()
    )
    if message is None:
        raise ValueError('Support user message not found')

    conversation = message.conversation
    customer_name = ''
    if message.sender_user:
        customer_name = (
            f'{message.sender_user.first_name or ""} {message.sender_user.last_name or ""}'.strip()
            or message.sender_user.username
            or message.sender_user.email
            or ''
        )

    staff_user_ids = list(
        User.objects.filter(is_staff=True, is_active=True)
        .exclude(id=message.sender_user_id)
        .values_list('id', flat=True)
    )
    if not staff_user_ids:
        return {'sent': 0, 'failed': 0}

    tokens = list(
        FCMDeviceToken.objects.filter(
            user_id__in=staff_user_ids,
            is_active=True,
        ).values_list('token', 'id')
    )
    if not tokens:
        return {'sent': 0, 'failed': 0}

    title = f'Nuevo mensaje de soporte'
    body_text = f'{customer_name}: {(message.body or "")[:140]}'

    result = send_batch_notifications(
        tokens=tokens,
        title=title,
        body=body_text,
        data={
            'action_url': 'confio://portal/support',
            'conversation_id': str(conversation.id),
            'data_channel_id': 'soporte',
            'data_conversation_id': str(conversation.id),
            'data_message_id': str(message.id),
            'data_sender_type': 'user',
            'data_sender_name': customer_name,
            'data_body': message.body or '',
            'tag': f'support-staff-{conversation.id}',
        },
        badge_count=None,
        notification=None,
        channel_id=CHANNEL_ID_MESSAGES,
    )
    logger.info(
        'Support staff push sent',
        extra={
            'support_message_id': message.id,
            'conversation_id': conversation.id,
            'staff_count': len(staff_user_ids),
            'sent': result.get('sent', 0),
            'failed': result.get('failed', 0),
        },
    )
    return result


def send_support_reply_push(support_message_id: int) -> Dict[str, int]:
    message = (
        SupportMessage.objects.select_related(
            'conversation__user',
            'conversation__account',
            'conversation__business',
            'sender_user',
        )
        .filter(id=support_message_id, sender_type='AGENT')
        .first()
    )
    if message is None:
        raise ValueError('Support reply message not found')

    conversation = message.conversation
    pref = NotificationPreference.objects.filter(user=conversation.user).first()
    if pref and not pref.push_enabled:
        return {'sent': 0, 'failed': 0}

    tokens = list(
        FCMDeviceToken.objects.filter(user=conversation.user, is_active=True).values_list('token', 'id')
    )
    if not tokens:
        return {'sent': 0, 'failed': 0}

    result = send_batch_notifications(
        tokens=tokens,
        title='Soporte de Confío',
        body=(message.body or '')[:180],
        data=_build_support_push_payload(message),
        badge_count=None,
        notification=None,
        channel_id=CHANNEL_ID_MESSAGES,
    )
    logger.info(
        'Support reply push sent',
        extra={
            'support_message_id': message.id,
            'conversation_id': conversation.id,
            'sent': result.get('sent', 0),
            'failed': result.get('failed', 0),
        },
    )
    return result
