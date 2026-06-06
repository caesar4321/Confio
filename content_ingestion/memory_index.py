from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

import requests
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

TABLE = 'content_ingestion_memory_chunk'
EMBEDDING_DIMENSIONS = 768


@dataclass(frozen=True)
class IndexedMemoryChunk:
    chunk_key: str
    source_path: str
    category: str
    title: str
    heading: str
    content: str
    similarity: float


def chunk_key(path: str, heading: str, content: str) -> str:
    value = f'{path}\0{heading}\0{content}'.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def _vector_literal(values: list[float]) -> str:
    return '[' + ','.join(f'{float(value):.9g}' for value in values) + ']'


def embed_texts(
    texts: list[str],
    *,
    max_retries: int = 0,
    retry_base_seconds: float = 5.0,
) -> list[list[float]]:
    if not texts:
        return []
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY is not configured for memory embeddings.')
    model = getattr(settings, 'CONFIO_AI_EMBEDDING_MODEL', 'gemini-embedding-2')
    dimensions = getattr(settings, 'CONFIO_AI_EMBEDDING_DIMENSIONS', EMBEDDING_DIMENSIONS)
    url = (
        'https://generativelanguage.googleapis.com/v1beta/models/'
        f'{model}:batchEmbedContents'
    )
    requests_payload = [
        {
            'model': f'models/{model}',
            'content': {'parts': [{'text': text}]},
            'outputDimensionality': dimensions,
        }
        for text in texts
    ]
    response = None
    for attempt in range(max_retries + 1):
        response = requests.post(
            url,
            params={'key': api_key},
            json={'requests': requests_payload},
            timeout=120,
        )
        if response.status_code != 429 or attempt >= max_retries:
            break
        retry_after = response.headers.get('Retry-After')
        try:
            delay = float(retry_after) if retry_after else retry_base_seconds * (2 ** attempt)
        except (TypeError, ValueError):
            delay = retry_base_seconds * (2 ** attempt)
        delay = min(delay, 60.0)
        logger.warning(
            'Gemini embedding quota exceeded; retrying in %.1f seconds (%s/%s).',
            delay,
            attempt + 1,
            max_retries,
        )
        time.sleep(delay)
    assert response is not None
    if response.status_code >= 400:
        raise RuntimeError(
            f'Gemini embedding request failed: {response.status_code} {response.text[:300]}'
        )
    embeddings = [item.get('values') or [] for item in response.json().get('embeddings', [])]
    if len(embeddings) != len(texts) or any(len(values) != dimensions for values in embeddings):
        raise RuntimeError('Gemini embedding response has unexpected dimensions.')
    return embeddings


def semantic_search(
    query: str,
    *,
    categories: set[str] | None = None,
    limit: int = 12,
) -> list[IndexedMemoryChunk]:
    if not query.strip() or not getattr(settings, 'CONFIO_AI_SEMANTIC_RETRIEVAL_ENABLED', True):
        return []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT to_regclass(%s)',
                [TABLE],
            )
            if cursor.fetchone()[0] is None:
                return []
        embedding = embed_texts([query])[0]
        vector = _vector_literal(embedding)
        where = ''
        params: list[object] = [vector]
        if categories:
            where = 'WHERE category = ANY(%s)'
            params.append(sorted(categories))
        params.append(limit)
        with connection.cursor() as cursor:
            cursor.execute(
                f'''
                SELECT chunk_key, source_path, category, title, heading, content,
                       1 - (embedding <=> %s::vector) AS similarity
                  FROM {TABLE}
                  {where}
                 ORDER BY embedding <=> %s::vector
                 LIMIT %s
                ''',
                [vector, *params[1:-1], vector, params[-1]],
            )
            return [
                IndexedMemoryChunk(
                    chunk_key=row[0],
                    source_path=row[1],
                    category=row[2],
                    title=row[3],
                    heading=row[4],
                    content=row[5],
                    similarity=float(row[6] or 0),
                )
                for row in cursor.fetchall()
            ]
    except Exception:
        logger.warning('Semantic memory retrieval unavailable; using lexical fallback.', exc_info=True)
        return []


def sync_chunks(chunks, *, batch_size: int = 20) -> dict:
    desired = {}
    for chunk in chunks:
        key = chunk_key(chunk.path, chunk.heading, chunk.text)
        desired[key] = chunk

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT chunk_key FROM {TABLE}')
        existing = {row[0] for row in cursor.fetchall()}

    missing = [(key, desired[key]) for key in desired.keys() - existing]
    inserted = 0
    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        texts = [
            f'Title: {chunk.title}\nSection: {chunk.heading}\n{chunk.text}'
            for _, chunk in batch
        ]
        embeddings = embed_texts(texts, max_retries=5)
        with connection.cursor() as cursor:
            for (key, chunk), embedding in zip(batch, embeddings):
                cursor.execute(
                    f'''
                    INSERT INTO {TABLE}
                        (chunk_key, source_path, category, title, heading, content, embedding, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector, NOW())
                    ON CONFLICT (chunk_key) DO UPDATE SET
                        source_path = EXCLUDED.source_path,
                        category = EXCLUDED.category,
                        title = EXCLUDED.title,
                        heading = EXCLUDED.heading,
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                    ''',
                    [
                        key, chunk.path, chunk.category, chunk.title, chunk.heading,
                        chunk.text, _vector_literal(embedding),
                    ],
                )
                inserted += 1

    stale = existing - desired.keys()
    if stale:
        with connection.cursor() as cursor:
            cursor.execute(f'DELETE FROM {TABLE} WHERE chunk_key = ANY(%s)', [list(stale)])
    return {
        'total': len(desired),
        'inserted': inserted,
        'deleted': len(stale),
        'unchanged': len(desired) - inserted,
    }
