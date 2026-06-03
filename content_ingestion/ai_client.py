from __future__ import annotations

import requests
from django.conf import settings


class AIClientError(Exception):
    pass


def _trim_prompt(prompt: str) -> str:
    max_chars = getattr(settings, 'CONFIO_AI_MAX_PROMPT_CHARS', 6000)
    prompt = prompt.strip()
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:max_chars] + '\n\n[Prompt truncated.]'


def complete_text(prompt: str) -> str:
    provider = getattr(settings, 'CONFIO_AI_PROVIDER', 'openai').strip().lower()
    prompt = _trim_prompt(prompt)
    if not prompt:
        raise AIClientError('Usage: /ai your question')

    if provider == 'gemini':
        return _complete_gemini(prompt)
    if provider == 'openai':
        return _complete_openai(prompt)
    raise AIClientError(f'Unsupported CONFIO_AI_PROVIDER: {provider}')


def _complete_openai(prompt: str) -> str:
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
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
            'instructions': getattr(settings, 'CONFIO_AI_SYSTEM_PROMPT', ''),
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


def _complete_gemini(prompt: str) -> str:
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        raise AIClientError('Gemini is selected, but GEMINI_API_KEY is not configured.')

    model = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    response = requests.post(
        url,
        params={'key': api_key},
        json={
            'systemInstruction': {
                'parts': [{'text': getattr(settings, 'CONFIO_AI_SYSTEM_PROMPT', '')}],
            },
            'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        },
        timeout=60,
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
    raise AIClientError('Gemini response did not include text output.')
