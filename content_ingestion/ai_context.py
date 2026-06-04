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
        'los resultados de las herramientas que puedes invocar (listar los archivos y '
        'videos del chat, buscar en el historial, buscar en la base de conocimiento). '
        'Regla por defecto: cuando Julian o Susy pregunte por videos existentes, '
        'memoria actual, docs actuales, catálogo, "más videos", "current videos" o '
        'algo ya registrado, primero consulta la memoria Git de ConfioAI con '
        'search_knowledge/read_memory_docs antes de pedirle títulos o links. No pidas '
        'al usuario una lista que probablemente ya vive en Git; usa Git como fuente '
        'canónica de memoria/contexto y solo pregunta si la búsqueda no encuentra nada '
        'o si faltan datos externos concretos. Para preguntas de inventario como '
        '"cuántos videos tenemos", "lista los videos", "qué videos hay" o "catálogo", '
        'usa list_video_memories y responde con el total y los títulos canónicos, no '
        'con resúmenes ni temas inferidos. '
        'Importante: los videos ORIGINALES se comparten como archivos (documentos), no '
        'como videos de Telegram (esos suelen ser solo clips de prueba); para el '
        'catálogo de videos usa la herramienta de archivos (get_chat_files). NO puedes '
        'ver el contenido interno ni descargar los videos (pesan más de 1 GB), solo sus '
        'nombres y captions. Sí puedes analizar videos públicos de YouTube cuando el '
        'usuario pega una URL: el sistema enruta automáticamente esos casos a Gemini con '
        'el video real como entrada visual/auditiva. Para videos privados, no listados o '
        'archivos dentro de Telegram, necesitas que el archivo esté disponible mediante '
        'una ruta compatible o una carga explícita. También puedes analizar imágenes, '
        'screenshots y fotos adjuntas en Telegram cuando el usuario las envía o responde '
        'a una imagen: el sistema enruta esos casos a Gemini con la imagen real como '
        'entrada visual. Cuando el usuario pida explícitamente guardar, registrar, '
        'archivar, escribir en memoria o pushear a Git, debes usar las herramientas '
        'write_memory o write_video_memory para crear una memoria curada en ConfioAI; '
        'no afirmes que guardaste algo si no usaste una herramienta y recibiste éxito. '
        'No guardes memorias por cada mensaje casual: solo decisiones, estrategias, '
        'learnings importantes, reportes, análisis de video o notas que el equipo pida '
        'preservar. Si te falta un dato, usa una '
        'herramienta o dilo claramente en lugar de inventar o dar instrucciones '
        'genéricas. Responde en el idioma del usuario (normalmente español), de forma '
        'concisa y práctica.'
    )

    parts = [base, capabilities]
    corpus = load_knowledge_corpus()
    if corpus:
        parts.append('## Base de conocimiento de Confío\n' + corpus)
    return '\n\n'.join(p for p in parts if p)


def build_media_system_prompt() -> str:
    """System prompt for DIRECT Gemini media analysis (video/image/YouTube).

    Deliberately has NO tool-calling instructions. These are plain generateContent calls
    with no function declarations; if the system prompt talks about tools, Gemini tries to
    call one and returns finishReason=MALFORMED_FUNCTION_CALL with no text. So keep this
    purely about analyzing the media in text."""
    base = (getattr(settings, 'CONFIO_AI_SYSTEM_PROMPT', '') or '').strip()
    persona = (
        'Eres Confío AI, asistente del equipo interno de Confío. Estás analizando el '
        'contenido multimedia (video/imagen) incluido. Describe lo que realmente ves y '
        'escuchas: tema, hook, estructura, ritmo, tono, escenas, CTA y puntos clave útiles '
        'para Confío y para la narrativa de Julian. Responde SOLO en texto, en español, '
        'concreto y útil. No intentes llamar funciones ni herramientas.'
    )
    parts = [base, persona]
    corpus = load_knowledge_corpus()
    if corpus:
        parts.append('## Base de conocimiento de Confío\n' + corpus)
    return '\n\n'.join(p for p in parts if p)
