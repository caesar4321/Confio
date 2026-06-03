from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from asgiref.sync import sync_to_async

from .models import IngestionStatus, MediaAsset, MediaPlatform, TelegramChat

logger = logging.getLogger(__name__)


class TelegramIngestionError(Exception):
    pass


def _chat_allowed(identifier: str) -> bool:
    allowlist = getattr(settings, 'TELEGRAM_INGESTION_CHAT_ALLOWLIST', [])
    if not allowlist:
        return True
    normalized = identifier.strip().lower()
    return normalized in {item.strip().lower() for item in allowlist if item.strip()}


def _session():
    try:
        from telethon.sessions import StringSession
    except ImportError as exc:
        raise TelegramIngestionError('Telethon is not installed. Install requirements.txt first.') from exc

    session_string = getattr(settings, 'TELEGRAM_SESSION_STRING', '')
    if session_string:
        return StringSession(session_string)

    session_root = Path(settings.TELEGRAM_SESSION_ROOT)
    session_root.mkdir(parents=True, exist_ok=True)
    return str(session_root / settings.TELEGRAM_SESSION_NAME)


def _entity_identifier(identifier: str):
    value = identifier.strip()
    if value.lstrip('-').isdigit():
        return int(value)
    return value


def get_client():
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise TelegramIngestionError('Telethon is not installed. Install requirements.txt first.') from exc

    api_id = getattr(settings, 'TELEGRAM_API_ID', None)
    api_hash = getattr(settings, 'TELEGRAM_API_HASH', '')
    if not api_id or not api_hash:
        raise TelegramIngestionError('TELEGRAM_API_ID and TELEGRAM_API_HASH must be configured.')
    return TelegramClient(_session(), api_id, api_hash)


async def sync_chat_media(chat_identifier: str, *, limit: int = 100, download: bool = False) -> dict:
    if not _chat_allowed(chat_identifier):
        raise TelegramIngestionError(f'Telegram chat is not allowlisted: {chat_identifier}')

    chat, _ = await sync_to_async(TelegramChat.objects.get_or_create)(
        chat_identifier=chat_identifier,
        defaults={'title': chat_identifier},
    )
    imported = 0
    skipped = 0
    downloaded = 0

    async with get_client() as client:
        entity = await client.get_entity(_entity_identifier(chat_identifier))
        title = getattr(entity, 'title', None) or getattr(entity, 'username', None) or chat_identifier
        chat.title = title
        chat.metadata = {
            **(chat.metadata or {}),
            'telegram_id': getattr(entity, 'id', None),
            'username': getattr(entity, 'username', None),
        }

        async for message in client.iter_messages(entity, limit=limit):
            if chat.last_message_id and message.id <= chat.last_message_id:
                skipped += 1
                continue
            if not message.media:
                skipped += 1
                continue

            asset, created = await sync_to_async(MediaAsset.objects.get_or_create)(
                telegram_chat=chat,
                telegram_message_id=message.id,
                defaults={
                    'platform': MediaPlatform.TELEGRAM,
                    'status': IngestionStatus.FETCHED,
                    'title': (message.text or '')[:500],
                    'description': message.text or '',
                    'published_at': message.date,
                    'fetched_at': timezone.now(),
                },
            )
            if created:
                imported += 1
            asset.platform = MediaPlatform.TELEGRAM
            asset.status = IngestionStatus.FETCHED
            asset.title = asset.title or (message.text or '')[:500]
            asset.description = message.text or asset.description
            asset.published_at = message.date or asset.published_at
            asset.fetched_at = timezone.now()
            asset.file_size_bytes = getattr(getattr(message, 'file', None), 'size', None)
            asset.telegram_file_id = str(getattr(getattr(message, 'file', None), 'id', '') or '')
            asset.metadata = {
                **(asset.metadata or {}),
                'mime_type': getattr(getattr(message, 'file', None), 'mime_type', None),
                'file_name': getattr(getattr(message, 'file', None), 'name', None),
                'duration': getattr(getattr(message, 'file', None), 'duration', None),
                'width': getattr(getattr(message, 'file', None), 'width', None),
                'height': getattr(getattr(message, 'file', None), 'height', None),
            }
            if download:
                target_dir = Path(settings.TELEGRAM_DOWNLOAD_ROOT) / str(chat.pk)
                target_dir.mkdir(parents=True, exist_ok=True)
                downloaded_path = await client.download_media(message, file=str(target_dir))
                if downloaded_path:
                    asset.local_file_path = downloaded_path
                    asset.status = IngestionStatus.DOWNLOADED
                    downloaded += 1
            asset.error = ''
            await sync_to_async(asset.save)()

        latest = await client.get_messages(entity, limit=1)
        if latest:
            chat.last_message_id = latest[0].id
        chat.last_synced_at = timezone.now()
        await sync_to_async(chat.save)()

    return {
        'chat_id': chat.pk,
        'chat_identifier': chat.chat_identifier,
        'imported': imported,
        'skipped': skipped,
        'downloaded': downloaded,
    }
