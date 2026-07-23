from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AIClientError(Exception):
    pass


# Canonical provider keys and their human-facing labels.
PROVIDER_LABELS = {
    'openai': 'ChatGPT',
    'claude': 'Claude',
    'grok': 'Grok',
    'gemini': 'Gemini',
    'deepseek': 'DeepSeek',
}

# Accepted aliases (command names, vendor names) -> canonical provider key.
PROVIDER_ALIASES = {
    'openai': 'openai',
    'chatgpt': 'openai',
    'gpt': 'openai',
    'claude': 'claude',
    'anthropic': 'claude',
    'grok': 'grok',
    'xai': 'grok',
    'gemini': 'gemini',
    'google': 'gemini',
    'deepseek': 'deepseek',
}

YOUTUBE_URL_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s<>\]]+|youtu\.be/[^\s<>\]]+|youtube\.com/shorts/[^\s<>\]]+)',
    re.IGNORECASE,
)


def normalize_provider(provider: str | None) -> str:
    key = (provider or '').strip().lower()
    canonical = PROVIDER_ALIASES.get(key)
    if not canonical:
        raise AIClientError(f'Unsupported AI provider: {provider}')
    return canonical


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(normalize_provider(provider), provider)


def _provider_api_key(provider: str) -> str:
    canonical = normalize_provider(provider)
    setting_name = {
        'openai': 'OPENAI_API_KEY',
        'claude': 'CLAUDE_API_KEY',
        'grok': 'GROK_API_KEY',
        'gemini': 'GEMINI_API_KEY',
        'deepseek': 'DEEPSEEK_API_KEY',
    }[canonical]
    return getattr(settings, setting_name, '') or ''


def configured_providers() -> list[str]:
    """Canonical providers that currently have an API key configured."""
    return [key for key in PROVIDER_LABELS if _provider_api_key(key)]


def _trim_prompt(prompt: str) -> str:
    max_chars = getattr(settings, 'CONFIO_AI_MAX_PROMPT_CHARS', 6000)
    prompt = prompt.strip()
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:max_chars] + '\n\n[Prompt truncated.]'


def _system_text(system: str | None) -> str:
    if system is not None:
        return system
    return getattr(settings, 'CONFIO_AI_SYSTEM_PROMPT', '')


def complete_text(prompt: str, provider: str | None = None, *, system: str | None = None) -> str:
    """Run a single completion. `provider` overrides CONFIO_AI_PROVIDER when given;
    `system` overrides the system prompt (e.g. base prompt + knowledge base)."""
    provider = normalize_provider(provider or getattr(settings, 'CONFIO_AI_PROVIDER', 'openai'))
    prompt = _trim_prompt(prompt)
    if not prompt:
        raise AIClientError('Empty prompt.')
    return _DISPATCH[provider](prompt, _system_text(system))


def complete_script(prompt: str, *, system: str | None = None) -> str:
    """Use the configured OpenAI model for long-form creator scripts.

    The normal Telegram agent is optimized for cheap tool use and concise answers.
    Script turns need faithful brief-following and enough output budget, not tools.
    """
    api_key = _provider_api_key('openai')
    if not api_key:
        raise AIClientError('OpenAI script writer requires OPENAI_API_KEY.')

    model = getattr(settings, 'OPENAI_MODEL', 'gpt-5.5')
    max_tokens = getattr(settings, 'CONFIO_AI_SCRIPT_MAX_TOKENS', 7000)
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'instructions': _system_text(system),
            'input': prompt,
            'max_output_tokens': max_tokens,
        },
        timeout=180,
    )
    if response.status_code >= 400:
        raise AIClientError(f'OpenAI script request failed: {response.status_code} {response.text[:500]}')

    data = response.json()
    text = data.get('output_text')
    if text:
        return text.strip()

    chunks = []
    for item in data.get('output', []):
        for content in item.get('content', []):
            if content.get('type') in {'output_text', 'text'} and content.get('text'):
                chunks.append(content['text'])
    if chunks:
        return '\n'.join(chunks).strip()
    raise AIClientError('OpenAI script response did not include text output.')


def extract_youtube_urls(text: str) -> list[str]:
    """Return unique YouTube URLs in order, trimmed for Telegram/Markdown punctuation."""
    urls = []
    seen = set()
    for match in YOUTUBE_URL_RE.findall(text or ''):
        url = match.rstrip(').,;!?"\'')
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def complete_with_youtube_video(prompt: str, *, system: str | None = None) -> str:
    """Analyze public YouTube URLs with Gemini video input plus the user's text/script."""
    prompt = _trim_prompt(prompt)
    urls = extract_youtube_urls(prompt)
    if not urls:
        raise AIClientError('No YouTube URL found.')
    return _complete_gemini(prompt, _system_text(system), youtube_urls=urls[:10])


def complete_with_images(
    prompt: str,
    images: list[tuple[str, bytes]],
    *,
    system: str | None = None,
) -> str:
    """Analyze image bytes with Gemini vision input plus the user's text/context."""
    prompt = _trim_prompt(prompt)
    if not images:
        raise AIClientError('No images provided.')
    return _complete_gemini(prompt, _system_text(system), images=images[:8])


def complete_with_video_files(
    prompt: str,
    videos: list[tuple[str, bytes, str]],
    *,
    system: str | None = None,
) -> str:
    """Upload Telegram video bytes to Gemini Files API and analyze them."""
    prompt = _trim_prompt(prompt)
    if not videos:
        raise AIClientError('No videos provided.')
    api_key = _provider_api_key('gemini')
    if not api_key:
        raise AIClientError('Gemini is selected, but GEMINI_API_KEY is not configured.')

    file_parts = []
    for mime_type, video_bytes, display_name in videos[:2]:
        uploaded = _upload_gemini_file(
            api_key,
            video_bytes,
            mime_type or 'video/mp4',
            display_name or 'telegram-video.mp4',
        )
        uploaded = _wait_for_gemini_file(api_key, uploaded)
        file_parts.append((uploaded.get('mime_type') or uploaded.get('mimeType') or mime_type, uploaded['uri']))
    return _complete_gemini(_video_analysis_prompt(prompt), _system_text(system), file_parts=file_parts)


def debate(prompt: str, *, synthesizer: str | None = None, system: str | None = None) -> str:
    """Ask every configured model the same prompt, then synthesize the discussion."""
    prompt = _trim_prompt(prompt)
    if not prompt:
        raise AIClientError('Empty prompt.')
    system = _system_text(system)

    providers = configured_providers()
    if not providers:
        raise AIClientError('No AI providers are configured.')
    if len(providers) == 1:
        # Nothing to debate; just answer.
        only = providers[0]
        return f'🤖 {provider_label(only)}\n{complete_text(prompt, provider=only, system=system)}'

    answers: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures = {pool.submit(_safe_complete, p, prompt, system): p for p in providers}
        for future in as_completed(futures):
            answers[futures[future]] = future.result()

    # Stable, readable ordering.
    ordered = [p for p in PROVIDER_LABELS if p in answers]

    sections = [f'🗣️ Debate: {prompt}', '']
    for p in ordered:
        sections.append(f'🤖 {provider_label(p)}')
        sections.append(answers[p].strip() or '(no answer)')
        sections.append('')

    # Pick a synthesizer: prefer the requested/Claude, else the first available.
    synth = None
    for candidate in (synthesizer, 'claude'):
        if not candidate:
            continue
        try:
            canonical = normalize_provider(candidate)
        except AIClientError:
            continue
        if canonical in answers:
            synth = canonical
            break
    if synth is None:
        synth = ordered[0]

    synthesis = _safe_complete(synth, _synthesis_prompt(prompt, answers, ordered), system)
    sections.append(f'🧩 Synthesis ({provider_label(synth)})')
    sections.append(synthesis.strip() or '(no synthesis)')

    return '\n'.join(sections).strip()


def _safe_complete(provider: str, prompt: str, system: str | None = None) -> str:
    try:
        return complete_text(prompt, provider=provider, system=system)
    except AIClientError as exc:
        return f'(error: {exc})'
    except Exception as exc:  # noqa: BLE001 - one model failing must not sink the debate
        logger.exception('Debate model %s failed', provider)
        return f'(error: {exc})'


def _synthesis_prompt(prompt: str, answers: dict[str, str], ordered: list[str]) -> str:
    per_answer_cap = 1500
    blocks = []
    for p in ordered:
        text = answers[p].strip()
        if len(text) > per_answer_cap:
            text = text[:per_answer_cap] + ' […]'
        blocks.append(f'{provider_label(p)} said:\n{text}')
    joined = '\n\n'.join(blocks)
    return (
        f'Several AI models answered this question: "{prompt}"\n\n'
        f'{joined}\n\n'
        'Summarize where they agree, call out any meaningful disagreements, '
        'and give the best combined answer. Be concise.'
    )


def _complete_openai(prompt: str, system: str = '') -> str:
    api_key = _provider_api_key('openai')
    if not api_key:
        raise AIClientError('OpenAI is selected, but OPENAI_API_KEY is not configured.')

    model = getattr(settings, 'OPENAI_MODEL', 'gpt-4.1-mini')
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'instructions': system,
            'input': prompt,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise AIClientError(f'OpenAI request failed: {response.status_code} {response.text[:500]}')

    data = response.json()
    text = data.get('output_text')
    if text:
        return text.strip()

    chunks = []
    for item in data.get('output', []):
        for content in item.get('content', []):
            if content.get('type') in {'output_text', 'text'} and content.get('text'):
                chunks.append(content['text'])
    if chunks:
        return '\n'.join(chunks).strip()
    raise AIClientError('OpenAI response did not include text output.')


def _complete_openai_compatible(
    *,
    prompt: str,
    system: str,
    api_key: str,
    model: str,
    base_url: str,
    provider_name: str,
) -> str:
    if not api_key:
        raise AIClientError(f'{provider_name} is selected, but its API key is not configured.')

    response = requests.post(
        f'{base_url.rstrip("/")}/chat/completions',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ],
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise AIClientError(f'{provider_name} request failed: {response.status_code} {response.text[:500]}')

    data = response.json()
    choices = data.get('choices') or []
    if choices:
        content = choices[0].get('message', {}).get('content')
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            chunks = [
                item.get('text', '')
                for item in content
                if isinstance(item, dict) and item.get('text')
            ]
            if chunks:
                return '\n'.join(chunks).strip()
    raise AIClientError(f'{provider_name} response did not include text output.')


def _complete_grok(prompt: str, system: str = '') -> str:
    return _complete_openai_compatible(
        prompt=prompt,
        system=system,
        api_key=_provider_api_key('grok'),
        model=getattr(settings, 'GROK_MODEL', 'grok-4.3'),
        base_url='https://api.x.ai/v1',
        provider_name='Grok',
    )


def _complete_deepseek(prompt: str, system: str = '') -> str:
    return _complete_openai_compatible(
        prompt=prompt,
        system=system,
        api_key=_provider_api_key('deepseek'),
        model=getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-chat'),
        base_url='https://api.deepseek.com',
        provider_name='DeepSeek',
    )


def _complete_gemini(
    prompt: str,
    system: str = '',
    *,
    youtube_urls: list[str] | None = None,
    images: list[tuple[str, bytes]] | None = None,
    file_parts: list[tuple[str, str]] | None = None,
) -> str:
    api_key = _provider_api_key('gemini')
    if not api_key:
        raise AIClientError('Gemini is selected, but GEMINI_API_KEY is not configured.')

    model = getattr(settings, 'GEMINI_MODEL', 'gemini-3.6-flash')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    parts = []
    for video_url in youtube_urls or []:
        parts.append({'file_data': {'file_uri': video_url}})
    for mime_type, file_uri in file_parts or []:
        parts.append({'file_data': {'mime_type': mime_type, 'file_uri': file_uri}})
    for mime_type, image_bytes in images or []:
        import base64

        parts.append({
            'inline_data': {
                'mime_type': mime_type,
                'data': base64.b64encode(image_bytes).decode('ascii'),
            }
        })
    parts.append({'text': prompt})
    response = requests.post(
        url,
        params={'key': api_key},
        json={
            'systemInstruction': {
                'parts': [{'text': system}],
            },
            'contents': [{'role': 'user', 'parts': parts}],
        },
        timeout=180 if (youtube_urls or file_parts) else 60,
    )
    if response.status_code >= 400:
        raise AIClientError(f'Gemini request failed: {response.status_code} {response.text[:500]}')

    data = response.json()
    chunks = []
    for candidate in data.get('candidates', []):
        for part in candidate.get('content', {}).get('parts', []):
            if part.get('text'):
                chunks.append(part['text'])
    if chunks:
        return '\n'.join(chunks).strip()
    raise AIClientError(_gemini_no_text_message(data))


def _video_analysis_prompt(prompt: str) -> str:
    return (
        f'{prompt}\n\n'
        'Analiza el video real con el contexto completo de ConfíoAI cargado en el system prompt. '
        'Evalúalo para TikTok, Instagram Reels y YouTube Shorts. No hagas un resumen positivo '
        'genérico. Devuelve un memo accionable con estas secciones: Observaciones reales por '
        'segmento/timestamp aproximado; Hook 0-3s y 3-10s; riesgos de retención; plan de edición '
        'con cortes/subtítulos/b-roll/reordenamiento; 3 hooks alternativos; CTAs/captions; '
        'recomendación por plataforma; huecos o incertidumbre. Cada recomendación debe estar '
        'atada a algo que viste u oíste en el video.'
    )


def _upload_gemini_file(api_key: str, data: bytes, mime_type: str, display_name: str) -> dict:
    start = requests.post(
        'https://generativelanguage.googleapis.com/upload/v1beta/files',
        params={'key': api_key},
        headers={
            'X-Goog-Upload-Protocol': 'resumable',
            'X-Goog-Upload-Command': 'start',
            'X-Goog-Upload-Header-Content-Length': str(len(data)),
            'X-Goog-Upload-Header-Content-Type': mime_type,
            'Content-Type': 'application/json',
        },
        json={'file': {'display_name': display_name[:120]}},
        timeout=60,
    )
    if start.status_code >= 400:
        raise AIClientError(f'Gemini file upload start failed: {start.status_code} {start.text[:500]}')
    upload_url = start.headers.get('x-goog-upload-url')
    if not upload_url:
        raise AIClientError('Gemini file upload did not return an upload URL.')

    upload = requests.post(
        upload_url,
        headers={
            'Content-Length': str(len(data)),
            'X-Goog-Upload-Offset': '0',
            'X-Goog-Upload-Command': 'upload, finalize',
        },
        data=data,
        timeout=300,
    )
    if upload.status_code >= 400:
        raise AIClientError(f'Gemini file upload failed: {upload.status_code} {upload.text[:500]}')
    file_obj = (upload.json() or {}).get('file') or {}
    if not file_obj.get('uri') or not file_obj.get('name'):
        raise AIClientError('Gemini file upload response missing file uri/name.')
    file_obj.setdefault('mime_type', file_obj.get('mimeType') or mime_type)
    return file_obj


def _wait_for_gemini_file(api_key: str, file_obj: dict) -> dict:
    name = file_obj.get('name', '')
    if not name:
        return file_obj
    for _ in range(24):
        state = file_obj.get('state')
        if state in (None, 'ACTIVE'):
            return file_obj
        if state == 'FAILED':
            raise AIClientError(f'Gemini file processing failed for {name}.')
        time.sleep(5)
        response = requests.get(
            f'https://generativelanguage.googleapis.com/v1beta/{name}',
            params={'key': api_key},
            timeout=30,
        )
        if response.status_code >= 400:
            raise AIClientError(f'Gemini file status failed: {response.status_code} {response.text[:500]}')
        file_obj = response.json() or file_obj
    raise AIClientError(f'Gemini file processing timed out for {name}.')


def _gemini_no_text_message(data: dict) -> str:
    details = []
    prompt_feedback = data.get('promptFeedback') or {}
    block_reason = prompt_feedback.get('blockReason')
    if block_reason:
        details.append(f'prompt blocked: {block_reason}')
    for candidate in data.get('candidates', []):
        finish_reason = candidate.get('finishReason')
        if finish_reason:
            details.append(f'finishReason: {finish_reason}')
        safety = []
        for rating in candidate.get('safetyRatings') or []:
            category = rating.get('category')
            probability = rating.get('probability')
            blocked = rating.get('blocked')
            if category and probability:
                suffix = ' blocked' if blocked else ''
                safety.append(f'{category}={probability}{suffix}')
        if safety:
            details.append('safetyRatings: ' + ', '.join(safety[:4]))
    if not details:
        details.append('no candidates/parts with text')
    return 'Gemini response did not include text output (' + '; '.join(details[:6]) + ').'


def _complete_claude(prompt: str, system: str = '') -> str:
    api_key = _provider_api_key('claude')
    if not api_key:
        raise AIClientError('Claude is selected, but CLAUDE_API_KEY is not configured.')

    model = getattr(settings, 'CLAUDE_MODEL', 'claude-sonnet-4-6')
    response = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'max_tokens': 1200,
            'system': system,
            'messages': [{'role': 'user', 'content': prompt}],
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise AIClientError(f'Claude request failed: {response.status_code} {response.text[:500]}')

    data = response.json()
    chunks = []
    for item in data.get('content', []):
        if item.get('type') == 'text' and item.get('text'):
            chunks.append(item['text'])
    if chunks:
        return '\n'.join(chunks).strip()
    raise AIClientError('Claude response did not include text output.')


_DISPATCH = {
    'openai': _complete_openai,
    'claude': _complete_claude,
    'grok': _complete_grok,
    'gemini': _complete_gemini,
    'deepseek': _complete_deepseek,
}
