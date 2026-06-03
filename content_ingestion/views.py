import json

from django.conf import settings
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import AIContextCategory, AIContextDocument
from .tasks import commit_ai_context_document_task, sync_telegram_chat_media_task


def _authorized(request):
    secret = getattr(settings, 'CONTENT_INGESTION_API_SECRET', '')
    if not secret:
        return settings.DEBUG
    auth = request.headers.get('Authorization', '')
    token = auth.removeprefix('Bearer ').strip() if auth.startswith('Bearer ') else ''
    return token == secret or request.headers.get('X-Content-Ingestion-Secret') == secret


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


@csrf_exempt
@require_POST
def enqueue_telegram_sync(request):
    if not _authorized(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    body = _json_body(request)
    if body is None:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    chat_identifier = (body.get('chat_identifier') or '').strip()
    if not chat_identifier:
        return JsonResponse({'error': 'chat_identifier is required'}, status=400)
    limit = int(body.get('limit') or 100)
    task = sync_telegram_chat_media_task.delay(
        chat_identifier,
        min(max(limit, 1), 1000),
        bool(body.get('download', False)),
    )
    return JsonResponse({'task_id': task.id})


@csrf_exempt
@require_POST
def enqueue_ai_context_commit(request):
    if not _authorized(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    body = _json_body(request)
    if body is None:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    title = (body.get('title') or '').strip()
    content = (body.get('body') or body.get('content') or '').strip()
    category = (body.get('category') or AIContextCategory.DECISION_LOG).strip()
    if not title:
        return JsonResponse({'error': 'title is required'}, status=400)
    if not content:
        return JsonResponse({'error': 'body is required'}, status=400)
    if category not in AIContextCategory.values:
        return JsonResponse({'error': f'Unsupported category: {category}'}, status=400)

    document = AIContextDocument.objects.create(
        category=category,
        title=title,
        slug=(body.get('slug') or slugify(title)[:100] or 'untitled'),
        body=content,
        metadata=body.get('metadata') or {},
    )
    task = commit_ai_context_document_task.delay(document.pk, bool(body.get('push', True)))
    return JsonResponse({'document_id': document.pk, 'task_id': task.id})
