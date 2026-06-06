"""Builds the context the Telegram bot reasons over: Confío's knowledge base
(the ConfioAI markdown repo) plus the system prompt that tells the model what it
can and cannot see (so it stops guessing)."""
from __future__ import annotations

import glob
import os
import re
import unicodedata
from dataclasses import dataclass

from django.conf import settings

# Cache the corpus keyed by the set of files and their mtimes, so we only re-read
# the ConfioAI repo when something actually changed.
_CACHE: dict = {'sig': None, 'corpus': ''}
_INDEX_CACHE: dict = {'sig': None, 'chunks': []}

CANONICAL_CATEGORY_WEIGHTS = {
    'content-rules': 5.0,
    'preferences': 4.5,
    'decisions': 4.0,
    'facts': 4.0,
    'strategy': 2.5,
    'legal': 2.5,
    'social-stats': 2.0,
    'weekly-reports': 1.5,
    'user-reports': 1.5,
    'meeting-notes': 1.0,
    'decision-log': 1.0,
    'videos': 0.5,
}


@dataclass(frozen=True)
class MemoryChunk:
    path: str
    category: str
    title: str
    heading: str
    text: str
    score: float = 0.0


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


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', value.lower()).strip()


def _query_terms(query: str) -> list[str]:
    normalized = _normalize_text(query)
    terms = re.findall(r'[a-z0-9][a-z0-9_-]{2,}|[\uac00-\ud7a3]{2,}', normalized)
    stop = {
        'the', 'and', 'for', 'con', 'que', 'una', 'uno', 'por', 'para', 'como',
        'this', 'that', 'from', 'what', 'when', 'write', 'please', 'quiero',
        'vamos', 'hacer', '해줘', '작성', '기반으로',
    }
    return [term for term in terms if term not in stop]


def _markdown_title(text: str, fallback: str) -> str:
    in_frontmatter = False
    for idx, line in enumerate((text or '').splitlines()[:80]):
        stripped = line.strip()
        if idx == 0 and stripped == '---':
            in_frontmatter = True
            continue
        if in_frontmatter and stripped == '---':
            in_frontmatter = False
            continue
        if in_frontmatter:
            key, sep, value = stripped.partition(':')
            if sep and key.strip().lower() == 'title':
                return value.strip().strip('"').strip("'") or fallback
        if stripped.startswith('# '):
            return stripped[2:].strip() or fallback
    return fallback


def _split_markdown_chunks(text: str, *, path: str, category: str) -> list[MemoryChunk]:
    title = _markdown_title(text, os.path.splitext(os.path.basename(path))[0].replace('-', ' ').title())
    chunks = []
    heading = title
    body: list[str] = []
    in_frontmatter = False

    def flush():
        content = '\n'.join(body).strip()
        if content:
            chunks.append(MemoryChunk(path, category, title, heading, content))

    for idx, line in enumerate((text or '').splitlines()):
        stripped = line.strip()
        if idx == 0 and stripped == '---':
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == '---':
                in_frontmatter = False
            continue
        if re.match(r'^#{1,3}\s+', stripped):
            flush()
            body = []
            heading = re.sub(r'^#{1,3}\s+', '', stripped).strip() or title
            continue
        body.append(line)
    flush()
    return chunks


def _memory_chunks() -> list[MemoryChunk]:
    docs = _docs_dir()
    if not docs or not os.path.isdir(docs):
        return []
    files = [
        path for path in glob.glob(os.path.join(docs, '**', '*.md'), recursive=True)
        if f'{os.sep}conversations{os.sep}' not in path and os.path.basename(path) != '.gitkeep'
    ]
    sig = tuple(sorted((path, os.path.getmtime(path), os.path.getsize(path)) for path in files))
    if _INDEX_CACHE['sig'] == sig:
        return _INDEX_CACHE['chunks']

    chunks = []
    for path in files:
        relative = os.path.relpath(path, docs)
        parts = relative.split(os.sep)
        if not parts:
            continue
        try:
            text = open(path, encoding='utf-8').read()
        except OSError:
            continue
        chunks.extend(_split_markdown_chunks(text, path=relative, category=parts[0]))
    _INDEX_CACHE['sig'] = sig
    _INDEX_CACHE['chunks'] = chunks
    return chunks


def retrieve_knowledge(
    query: str,
    *,
    max_chunks: int | None = None,
    max_chars: int | None = None,
    categories: set[str] | None = None,
) -> list[MemoryChunk]:
    """Return bounded, authority-aware Markdown chunks relevant to the request."""
    max_chunks = max_chunks or getattr(settings, 'CONFIO_AI_RETRIEVAL_MAX_CHUNKS', 8)
    max_chars = max_chars or getattr(settings, 'CONFIO_AI_RETRIEVAL_MAX_CHARS', 9000)
    terms = _query_terms(query)
    phrase = _normalize_text(query)
    ranked = []

    for chunk in _memory_chunks():
        if categories is not None and chunk.category not in categories:
            continue
        haystack = _normalize_text(f'{chunk.title} {chunk.heading} {chunk.text}')
        path_text = _normalize_text(chunk.path)
        category_weight = CANONICAL_CATEGORY_WEIGHTS.get(chunk.category, 0.25)
        score = category_weight
        matches = 0
        for term in set(terms):
            count = haystack.count(term)
            if count:
                matches += 1
                score += min(count, 4) * 1.5
                if term in _normalize_text(chunk.title):
                    score += 3.0
                if term in _normalize_text(chunk.heading):
                    score += 2.0
                if term in path_text:
                    score += 1.0
        if terms:
            score += (matches / len(set(terms))) * 8.0
        if phrase and len(phrase) <= 160 and phrase in haystack:
            score += 10.0
        if matches or chunk.category in {'preferences', 'facts', 'decisions', 'content-rules'}:
            ranked.append(MemoryChunk(
                chunk.path, chunk.category, chunk.title, chunk.heading, chunk.text, score
            ))

    ranked.sort(key=lambda item: (-item.score, item.path, item.heading))
    selected = []
    total = 0
    per_file: dict[str, int] = {}
    for chunk in ranked:
        if len(selected) >= max_chunks:
            break
        if per_file.get(chunk.path, 0) >= 2:
            continue
        rendered_len = len(chunk.path) + len(chunk.heading) + len(chunk.text) + 40
        if selected and total + rendered_len > max_chars:
            continue
        selected.append(chunk)
        per_file[chunk.path] = per_file.get(chunk.path, 0) + 1
        total += rendered_len
    return selected


def render_retrieved_knowledge(
    query: str,
    *,
    max_chars: int | None = None,
    categories: set[str] | None = None,
) -> str:
    chunks = retrieve_knowledge(query, max_chars=max_chars, categories=categories)
    blocks = []
    for chunk in chunks:
        blocks.append(
            f'SOURCE: docs/{chunk.path}\n'
            f'TITLE: {chunk.title}\n'
            f'SECTION: {chunk.heading}\n'
            f'{chunk.text}'
        )
    return '\n\n'.join(blocks)


def search_knowledge(query: str, max_chars: int = 4000) -> str:
    """Retrieve bounded canonical-memory sections relevant to the query."""
    result = render_retrieved_knowledge(query, max_chars=max_chars)
    if not _memory_chunks():
        return 'La base de conocimiento de Confío está vacía (repo no disponible).'
    return result or 'Sin coincidencias relevantes en la memoria canónica.'


def build_system_prompt(query: str = '') -> str:
    """System prompt with bounded memory retrieved for the current request."""
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
        '"qué memorias tenemos", "lista docs", "catálogo de strategy/legal/social-stats", '
        'usa list_memory_docs. Para inventario específico de videos como '
        '"cuántos videos tenemos", "lista los videos", "qué videos hay" o "catálogo de videos", '
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
        'Jerarquía de memoria: preferences, facts, decisions y content-rules son memoria '
        'canónica aprobada y tienen prioridad sobre strategy, reports, videos, meeting-notes '
        'y conversaciones. Los chats y borradores aportan contexto, pero no deben contradecir '
        'una regla o hecho canónico sin señalar explícitamente el conflicto. '
        'Para memorias de video, las subcarpetas bajo docs/videos representan playlists '
        'explícitas, no categorías inventadas por el modelo. No crees carpetas nuevas ni '
        'uses "Vida y filosofía" como comodín. Si el video viene como clip comprimido de '
        'Telegram y el usuario no dio una playlist explícita, usa folder: Instagram. '
        'Si el usuario sí dio una playlist/carpeta concreta, respétala literalmente. '
        'No guardes memorias por cada mensaje casual: solo decisiones, estrategias, '
        'learnings importantes, reportes, análisis de video o notas que el equipo pida '
        'preservar. Si te falta un dato, usa una '
        'herramienta o dilo claramente en lugar de inventar o dar instrucciones '
        'genéricas. Responde en el idioma del usuario (normalmente español), de forma '
        'concisa y práctica.'
    )

    parts = [base, capabilities]
    retrieved = render_retrieved_knowledge(
        query,
        categories={
            'preferences', 'facts', 'decisions', 'content-rules', 'strategy',
            'legal', 'social-stats', 'weekly-reports', 'user-reports',
            'meeting-notes', 'decision-log', 'videos',
        },
    )
    if retrieved:
        parts.append(
            '## Memoria canónica recuperada para esta solicitud\n'
            'Prioriza estas fuentes sobre borradores del chat. No asumas que documentos '
            'no recuperados dicen algo distinto.\n' + retrieved
        )
    return '\n\n'.join(p for p in parts if p)


def build_media_system_prompt(query: str = '') -> str:
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
        'para Confío y para la narrativa de Julian. No escribas análisis genéricos tipo '
        '"alto potencial", "conecta emocionalmente" o "top of funnel" sin evidencia '
        'observable y acciones concretas. Para videos, entrega un memo accionable con: '
        '1) Observaciones reales por segmento o timestamp aproximado; 2) diagnóstico del '
        'hook 0-3s y 3-10s; 3) riesgos de retención; 4) lista concreta de edición '
        '(cortes, subtítulos, b-roll, reordenamiento); 5) 3 hooks alternativos; '
        '6) 2-3 CTAs/captions; 7) recomendación por plataforma; 8) huecos/incertidumbre. '
        'Si no puedes ver u oír algo con suficiente confianza, dilo. Responde SOLO en '
        'texto, en español, concreto y útil. Si luego se guarda como memoria, recuerda que '
        'las subcarpetas de docs/videos son playlists explícitas; para clips comprimidos '
        'de Telegram sin playlist indicada, usa Instagram. No intentes llamar funciones '
        'ni herramientas.'
    )
    parts = [base, persona]
    retrieved = render_retrieved_knowledge(
        query,
        categories={
            'preferences', 'facts', 'decisions', 'content-rules', 'strategy',
            'social-stats', 'videos',
        },
    )
    if retrieved:
        parts.append('## Memoria canónica relevante\n' + retrieved)
    return '\n\n'.join(p for p in parts if p)


def build_script_system_prompt(query: str = '') -> str:
    """System prompt for long-form creator scripts.

    This mode intentionally avoids tool instructions and the generic "be concise"
    chat behavior. It treats the latest user prompt as the production brief and
    previous weak drafts in the chat as negative examples, not templates.
    """
    base = (getattr(settings, 'CONFIO_AI_SYSTEM_PROMPT', '') or '').strip()
    persona = (
        'Eres el script doctor senior de Julian para TikTok/Reels en español. '
        'Tu trabajo es producir guiones finales, no explicar teoría. El mensaje actual '
        'del usuario es el contrato de producción: obedece literalmente sus restricciones '
        'sobre hook, rehook, tono, metáforas, CTA, duración y estructura. Si el historial '
        'contiene borradores anteriores que contradicen el mensaje actual, trátalos como '
        'ejemplos negativos y no los imites. No uses plantillas con encabezados, timestamps, '
        'listas de actos, prefacios, disclaimers ni resumen final salvo que el usuario lo '
        'pida explícitamente. Entrega SOLO el guion en español natural, listo para decirse '
        'en cámara. Para scripts de Confío: Confío debe aparecer tarde como cierre de '
        'worldview, no como definición de producto; no listes features ni UX; no mezcles '
        'las tres fases si el brief dice que cada video encarna una sola fase. Si el brief '
        'no especifica fase y habla de la confianza volviendo de instituciones a personas, '
        'usa la fase Trust Layer como eje dominante. Mantén la palabra confianza/confiar '
        'bajo control; no la repitas como muletilla.'
    )
    parts = [base, persona]
    retrieved = render_retrieved_knowledge(
        query,
        categories={'preferences', 'facts', 'decisions', 'content-rules', 'strategy'},
    )
    if retrieved:
        parts.append(
            '## Reglas y memoria canónica relevantes\n'
            'Estas reglas son autoritativas y tienen prioridad sobre borradores anteriores.\n'
            + retrieved
        )
    return '\n\n'.join(p for p in parts if p)
