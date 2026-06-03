"""Builds the context the Telegram bot reasons over: Confío's knowledge base
(the ConfioAI markdown repo) plus the system prompt that tells the model what it
can and cannot see (so it stops guessing)."""
from __future__ import annotations

import glob
import os

from django.conf import settings

# Cache the corpus keyed by the set of files and their mtimes, so we only re-read
# the ConfioAI repo when something actually changed.
_CACHE: dict = {'sig': None, 'corpus': ''}


def _docs_dir() -> str:
    repo = getattr(settings, 'CONFIO_AI_REPO_PATH', '') or ''
    root = getattr(settings, 'CONFIO_AI_CONTEXT_ROOT', 'docs') or 'docs'
    return os.path.join(repo, root) if repo else ''


def load_knowledge_corpus(max_chars: int | None = None) -> str:
    """Concatenate ConfioAI knowledge docs (newest first), capped to max_chars.

    Returns '' when the repo isn't present — knowledge is optional, never fatal.
    The conversations/ subtree is excluded so the bot's own logs don't feed back in.
    """
    if max_chars is None:
        max_chars = getattr(settings, 'CONFIO_AI_KNOWLEDGE_MAX_CHARS', 16000)

    docs = _docs_dir()
    if not docs or not os.path.isdir(docs):
        return ''

    files = [
        p for p in glob.glob(os.path.join(docs, '**', '*.md'), recursive=True)
        if f'{os.sep}conversations{os.sep}' not in p
    ]
    files.sort(key=os.path.getmtime, reverse=True)

    sig = tuple((p, os.path.getmtime(p)) for p in files)
    if _CACHE['sig'] == sig:
        return _CACHE['corpus']

    chunks: list[str] = []
    total = 0
    for path in files:
        try:
            text = open(path, encoding='utf-8').read().strip()
        except OSError:
            continue
        if not text:
            continue
        block = f'# {os.path.relpath(path, docs)}\n{text}'
        if total + len(block) > max_chars:
            chunks.append(block[: max(0, max_chars - total)])
            break
        chunks.append(block)
        total += len(block)

    corpus = '\n\n'.join(chunks).strip()
    _CACHE['sig'] = sig
    _CACHE['corpus'] = corpus
    return corpus


def search_knowledge(query: str, max_chars: int = 2500) -> str:
    """Keyword search over the ConfioAI knowledge corpus. Returns matching sections."""
    corpus = load_knowledge_corpus()
    if not corpus:
        return 'La base de conocimiento de Confío está vacía (repo no disponible).'
    terms = [t for t in (query or '').lower().split() if len(t) > 2]
    if not terms:
        return corpus[:max_chars]
    hits = [block for block in corpus.split('\n\n') if any(t in block.lower() for t in terms)]
    result = '\n\n'.join(hits) if hits else 'Sin coincidencias en la base de conocimiento.'
    return result[:max_chars]


def build_system_prompt() -> str:
    """System prompt: base instructions + accurate capabilities + knowledge base."""
    base = (getattr(settings, 'CONFIO_AI_SYSTEM_PROMPT', '') or '').strip()
    capabilities = (
        'Eres Confío AI, el asistente del equipo interno de Confío en Telegram. '
        'Razonas con base en el contexto que recibes: los últimos mensajes de este '
        'chat (con los videos y archivos marcados como [video: ...] o [archivo: ...]), '
        'la base de conocimiento de Confío incluida abajo y, cuando estén disponibles, '
        'los resultados de las herramientas que puedes invocar (listar videos del chat, '
        'buscar en el historial, buscar en la base de conocimiento). NO puedes ver el '
        'contenido interno de los videos. Si te falta un dato, usa una herramienta o '
        'dilo claramente en lugar de inventar o dar instrucciones genéricas. Responde '
        'en el idioma del usuario (normalmente español), de forma concisa y práctica.'
    )

    parts = [base, capabilities]
    corpus = load_knowledge_corpus()
    if corpus:
        parts.append('## Base de conocimiento de Confío\n' + corpus)
    return '\n\n'.join(p for p in parts if p)
