import asyncio
from functools import wraps

from celery import shared_task
from django.db import connection

from .context_repo import write_commit_and_push_context
from .models import AIContextDocument
from .telegram_client import sync_chat_media


def _close_connection(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            connection.close()
    return wrapper


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={'max_retries': 2})
@_close_connection
def sync_telegram_chat_media_task(self, chat_identifier: str, limit: int = 100, download: bool = False):
    return asyncio.run(sync_chat_media(chat_identifier, limit=limit, download=download))


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_kwargs={'max_retries': 1})
@_close_connection
def commit_ai_context_document_task(self, document_id: int, push: bool = True):
    document = AIContextDocument.objects.get(pk=document_id)
    try:
        document = write_commit_and_push_context(document, push=push)
    except Exception as exc:
        document.mark_failed(str(exc))
        raise
    return {
        'document_id': document.pk,
        'status': document.status,
        'relative_path': document.relative_path,
        'commit_sha': document.commit_sha,
    }
