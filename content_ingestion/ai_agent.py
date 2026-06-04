"""The tool-use loop behind the Telegram agent.

Primary path: native function-calling. The model emits structured tool calls with
JSON arguments (no fragile `TOOL ...` text parsing). Default backend is OpenAI's
Responses API with a cheap model (gpt-4.1-mini) for cost; Claude is available as
an optional escalation via CONFIO_AI_AGENT_BACKEND=claude.

Each tool keeps its simple `callable(args: str) -> str` interface and is exposed
with a single string `input` argument; the tool's docstring documents the format.

Fallback: when no native-capable key is configured, the original text-protocol
loop (`TOOL <name> <args>`) drives whatever provider was requested.

Note: Gemini handles vision/video/YouTube via direct routing in the listener — it
is intentionally NOT a second "final answer writer" here. The same model that
calls the tools writes the final reply, so reasoning and prose stay coherent.
"""
from __future__ import annotations

import json
import logging
import re

import requests
from django.conf import settings

from content_ingestion.ai_client import complete_text

logger = logging.getLogger(__name__)


class AgentError(Exception):
    pass


_TOOL_LINE = re.compile(r'^TOOL[:\s]+([a-zA-Z_]\w*)\s*(.*)$', re.IGNORECASE)

DEFAULT_MAX_STEPS = 5

_TOOL_INPUT_DESC = (
    'Argumentos o contenido para la herramienta, siguiendo el formato indicado en '
    'su descripción. Cadena vacía si la herramienta no requiere argumentos.'
)


def run_with_tools(prompt, provider, system, tools, *, max_steps=DEFAULT_MAX_STEPS, backend=None):
    """Answer `prompt`, letting the model call `tools` (name -> callable(str) -> str).

    `backend` overrides CONFIO_AI_AGENT_BACKEND for this call (e.g. memory writes
    use a robust backend that doesn't mangle large function-call arguments).

    Native function-calling. Backend = CONFIO_AI_AGENT_BACKEND (default 'gemini'):
    'gemini'/'grok'/'deepseek' via their OpenAI-compatible /chat/completions,
    'openai' via the Responses API, 'claude' via the Messages API. Falls back to the
    next available backend, then to the text-protocol loop on `provider`.
    """
    if not tools:
        return complete_text(prompt, provider, system=system)

    primary = (backend or getattr(settings, 'CONFIO_AI_AGENT_BACKEND', 'gemini') or 'gemini').strip().lower()
    # Try the chosen backend first, then other configured ones. Robust backends first
    # in the fallback (a fallback usually means the primary's API key is missing).
    order = [primary] + [b for b in ('claude', 'openai', 'gemini', 'grok', 'deepseek') if b != primary]
    for candidate in order:
        runner = _agent_runner(candidate)
        if runner is not None:
            return runner(prompt, system, tools, max_steps=max_steps)
    return _run_text_protocol(prompt, provider, system, tools, max_steps=max_steps)


# OpenAI-compatible chat-completions backends: native function tools via /chat/completions.
_CHAT_COMPLETIONS_BACKENDS = {
    'gemini': {
        'name': 'Gemini', 'key': 'GEMINI_API_KEY', 'model': 'GEMINI_MODEL',
        'model_default': 'gemini-2.5-flash',
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
    },
    'grok': {
        'name': 'Grok', 'key': 'GROK_API_KEY', 'model': 'GROK_MODEL',
        'model_default': 'grok-4.3', 'base_url': 'https://api.x.ai/v1',
    },
    'deepseek': {
        'name': 'DeepSeek', 'key': 'DEEPSEEK_API_KEY', 'model': 'DEEPSEEK_MODEL',
        'model_default': 'deepseek-chat', 'base_url': 'https://api.deepseek.com',
    },
}


def _agent_runner(backend):
    """Callable(prompt, system, tools, *, max_steps) for `backend`, or None when its
    API key isn't configured."""
    if backend == 'openai' and getattr(settings, 'OPENAI_API_KEY', ''):
        return lambda p, s, t, *, max_steps: _run_native_openai(p, s, t, max_steps=max_steps)
    if backend == 'claude' and getattr(settings, 'CLAUDE_API_KEY', ''):
        return lambda p, s, t, *, max_steps: _run_native_claude(p, s, t, max_steps=max_steps)
    cfg = _CHAT_COMPLETIONS_BACKENDS.get(backend)
    if cfg:
        api_key = getattr(settings, cfg['key'], '')
        if api_key:
            model = (getattr(settings, 'CONFIO_AI_AGENT_MODEL', '')
                     or getattr(settings, cfg['model'], cfg['model_default']))
            return lambda p, s, t, *, max_steps: _run_chat_completions(
                p, s, t, base_url=cfg['base_url'], api_key=api_key, model=model,
                provider_name=cfg['name'], max_steps=max_steps,
            )
    return None


def _tool_description(fn) -> str:
    return ' '.join((getattr(fn, '__doc__', '') or '').split()) or 'tool'


def _tool_arg(args) -> str:
    """Extract the single string `input` argument from a parsed JSON args object."""
    if isinstance(args, dict):
        value = args.get('input', '')
    else:
        value = args
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# OpenAI-compatible Chat Completions (Gemini / Grok / DeepSeek)
# --------------------------------------------------------------------------- #

def _chat_tool_specs(tools):
    specs = []
    for name, fn in tools.items():
        specs.append({
            'type': 'function',
            'function': {
                'name': name,
                'description': _tool_description(fn)[:1500],
                'parameters': {
                    'type': 'object',
                    'properties': {'input': {'type': 'string', 'description': _TOOL_INPUT_DESC}},
                    'required': ['input'],
                },
            },
        })
    return specs


def _chat_message_text(message) -> str:
    content = message.get('content')
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return '\n'.join(
            part.get('text', '') for part in content if isinstance(part, dict) and part.get('text')
        ).strip()
    return ''


def _chat_post(url, api_key, payload, provider_name):
    response = requests.post(
        url,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=180,
    )
    if response.status_code >= 400:
        raise AgentError(f'{provider_name} agent request failed: {response.status_code} {response.text[:300]}')
    return response.json()


def _run_chat_completions(prompt, system, tools, *, base_url, api_key, model, provider_name, max_steps):
    max_tokens = getattr(settings, 'CONFIO_AI_AGENT_MAX_TOKENS', 8000)
    specs = _chat_tool_specs(tools)
    url = f'{base_url.rstrip("/")}/chat/completions'
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
    for _ in range(max_steps):
        data = _chat_post(url, api_key, {
            'model': model, 'messages': messages, 'tools': specs, 'max_tokens': max_tokens,
        }, provider_name)
        message = ((data.get('choices') or [{}])[0]).get('message') or {}
        tool_calls = message.get('tool_calls') or []
        if not tool_calls:
            return _chat_message_text(message) or '(respuesta vacía)'
        messages.append(message)  # assistant turn carrying the tool_calls
        for call in tool_calls:
            fn_block = call.get('function') or {}
            name = fn_block.get('name')
            try:
                args = json.loads(fn_block.get('arguments') or '{}')
            except (ValueError, TypeError):
                args = {}
            arg = _tool_arg(args)
            logger.info('AI tool call: %s %r', name, arg[:80])
            fn = tools.get(name)
            try:
                result = fn(arg) if fn else f'(herramienta desconocida: {name})'
            except Exception as exc:  # noqa: BLE001 - a failing tool must not crash the reply
                logger.exception('Tool %s failed', name)
                result = f'(error ejecutando {name}: {exc})'
            messages.append({'role': 'tool', 'tool_call_id': call.get('id'), 'content': (result or '')[:16000]})

    data = _chat_post(url, api_key, {
        'model': model,
        'messages': messages + [{'role': 'user', 'content': 'Responde ahora al usuario con lo que tengas, sin más herramientas.'}],
        'max_tokens': max_tokens,
    }, provider_name)
    message = ((data.get('choices') or [{}])[0]).get('message') or {}
    return _chat_message_text(message) or '(respuesta vacía)'


# --------------------------------------------------------------------------- #
# OpenAI Responses API
# --------------------------------------------------------------------------- #

def _openai_tool_specs(tools):
    specs = []
    for name, fn in tools.items():
        specs.append({
            'type': 'function',
            'name': name,
            'description': _tool_description(fn)[:1500],
            'parameters': {
                'type': 'object',
                'properties': {'input': {'type': 'string', 'description': _TOOL_INPUT_DESC}},
                'required': ['input'],
                'additionalProperties': False,
            },
            'strict': True,
        })
    return specs


def _openai_text(data) -> str:
    text = data.get('output_text')
    if isinstance(text, str) and text.strip():
        return text.strip()
    chunks = []
    for item in data.get('output', []) or []:
        if item.get('type') == 'message':
            for part in item.get('content', []) or []:
                if part.get('type') in {'output_text', 'text'} and part.get('text'):
                    chunks.append(part['text'])
    return '\n'.join(chunks).strip()


def _openai_post(api_key, payload):
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=180,
    )
    if response.status_code >= 400:
        raise AgentError(f'OpenAI agent request failed: {response.status_code} {response.text[:300]}')
    return response.json()


def _run_native_openai(prompt, system, tools, *, max_steps):
    api_key = settings.OPENAI_API_KEY
    model = getattr(settings, 'CONFIO_AI_AGENT_MODEL', '') or getattr(settings, 'OPENAI_MODEL', 'gpt-4.1-mini')
    max_tokens = getattr(settings, 'CONFIO_AI_AGENT_MAX_TOKENS', 8000)
    specs = _openai_tool_specs(tools)

    payload = {
        'model': model,
        'instructions': system,
        'input': [{'role': 'user', 'content': prompt}],
        'tools': specs,
        'max_output_tokens': max_tokens,
    }
    for _ in range(max_steps):
        data = _openai_post(api_key, payload)
        calls = [it for it in (data.get('output') or []) if it.get('type') == 'function_call']
        if not calls:
            return _openai_text(data) or '(respuesta vacía)'
        outputs = []
        for call in calls:
            name = call.get('name')
            call_id = call.get('call_id') or call.get('id')
            try:
                args = json.loads(call.get('arguments') or '{}')
            except (ValueError, TypeError):
                args = {}
            arg = _tool_arg(args)
            logger.info('AI tool call: %s %r', name, arg[:80])
            fn = tools.get(name)
            try:
                result = fn(arg) if fn else f'(herramienta desconocida: {name})'
            except Exception as exc:  # noqa: BLE001 - a failing tool must not crash the reply
                logger.exception('Tool %s failed', name)
                result = f'(error ejecutando {name}: {exc})'
            outputs.append({
                'type': 'function_call_output',
                'call_id': call_id,
                'output': (result or '')[:16000],
            })
        payload = {
            'model': model,
            'tools': specs,
            'previous_response_id': data.get('id'),
            'input': outputs,
            'max_output_tokens': max_tokens,
        }

    final = _openai_post(api_key, {
        'model': model,
        'previous_response_id': payload.get('previous_response_id'),
        'input': [{'role': 'user', 'content': 'Responde ahora al usuario con lo que tengas, sin más herramientas.'}],
        'max_output_tokens': max_tokens,
    })
    return _openai_text(final) or '(respuesta vacía)'


# --------------------------------------------------------------------------- #
# Claude Messages API (optional escalation)
# --------------------------------------------------------------------------- #

def _claude_tool_specs(tools):
    specs = []
    for name, fn in tools.items():
        specs.append({
            'name': name,
            'description': _tool_description(fn)[:1500],
            'input_schema': {
                'type': 'object',
                'properties': {'input': {'type': 'string', 'description': _TOOL_INPUT_DESC}},
            },
        })
    return specs


def _claude_text(content) -> str:
    return '\n'.join(b.get('text', '') for b in content if b.get('type') == 'text').strip()


def _claude_post(system, messages, specs, *, max_tokens):
    body = {
        'model': getattr(settings, 'CONFIO_AI_AGENT_MODEL', '') or getattr(settings, 'CLAUDE_MODEL', 'claude-sonnet-4-6'),
        'max_tokens': max_tokens,
        'system': system,
        'messages': messages,
    }
    if specs:
        body['tools'] = specs
    response = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers={
            'x-api-key': settings.CLAUDE_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        },
        json=body,
        timeout=180,
    )
    if response.status_code >= 400:
        raise AgentError(f'Claude agent request failed: {response.status_code} {response.text[:300]}')
    return response.json()


def _run_native_claude(prompt, system, tools, *, max_steps):
    max_tokens = getattr(settings, 'CONFIO_AI_AGENT_MAX_TOKENS', 8000)
    specs = _claude_tool_specs(tools)
    messages = [{'role': 'user', 'content': prompt}]
    for _ in range(max_steps):
        data = _claude_post(system, messages, specs, max_tokens=max_tokens)
        content = data.get('content', []) or []
        if data.get('stop_reason') != 'tool_use':
            return _claude_text(content) or '(respuesta vacía)'
        messages.append({'role': 'assistant', 'content': content})
        results = []
        for block in content:
            if block.get('type') != 'tool_use':
                continue
            name = block.get('name')
            arg = _tool_arg(block.get('input'))
            logger.info('AI tool call: %s %r', name, arg[:80])
            fn = tools.get(name)
            try:
                result = fn(arg) if fn else f'(herramienta desconocida: {name})'
            except Exception as exc:  # noqa: BLE001
                logger.exception('Tool %s failed', name)
                result = f'(error ejecutando {name}: {exc})'
            results.append({
                'type': 'tool_result',
                'tool_use_id': block.get('id'),
                'content': (result or '')[:16000],
            })
        messages.append({'role': 'user', 'content': results})

    messages.append({'role': 'user', 'content': 'Responde ahora al usuario con lo que tengas, sin más herramientas.'})
    data = _claude_post(system, messages, None, max_tokens=max_tokens)
    return _claude_text(data.get('content', [])) or '(respuesta vacía)'


# --------------------------------------------------------------------------- #
# Text-protocol fallback (no native key configured)
# --------------------------------------------------------------------------- #

def _run_text_protocol(prompt, provider, system, tools, *, max_steps=DEFAULT_MAX_STEPS):
    full_system = f'{system}\n\n{_tool_instructions(tools)}'
    transcript = prompt
    for _ in range(max_steps):
        reply = complete_text(transcript, provider, system=full_system)
        calls = _parse_tool_calls(reply, tools)
        if not calls:
            return reply
        results = []
        for name, args in calls:
            logger.info('AI tool call: %s %r', name, args[:80])
            try:
                result = tools[name](args)
            except Exception as exc:  # noqa: BLE001
                logger.exception('Tool %s failed', name)
                result = f'(error ejecutando {name}: {exc})'
            results.append(f'[Resultado de la herramienta {name}:]\n{result}')
        transcript = (
            f'{transcript}\n\n' + '\n\n'.join(results) + '\n\n'
            'Si ya puedes responder al usuario, hazlo en lenguaje natural (sin TOOL). '
            'Si necesitas otra herramienta, pídela con otra línea TOOL.'
        )

    return complete_text(
        f'{transcript}\n\nResponde ahora al usuario sin usar más herramientas.',
        provider,
        system=full_system,
    )


def _tool_instructions(tools) -> str:
    lines = [
        'Tienes herramientas para consultar o escribir información que NO está en el contexto.',
        'Para usar una herramienta corta, responde EXCLUSIVAMENTE con una sola línea:',
        'TOOL <nombre> <argumentos>',
        'Para herramientas de escritura larga usa el formato multilinea documentado en su descripción:',
        'TOOL <nombre>',
        '<contenido en varias líneas>',
        'Puedes emitir varios bloques TOOL seguidos; se ejecutan en orden. No mezcles texto final dentro de los bloques TOOL.',
        'Herramientas disponibles:',
    ]
    for name, fn in tools.items():
        lines.append(f'- {name}: {_tool_description(fn)}')
    lines.append('Cuando tengas suficiente información, responde al usuario normalmente (sin TOOL).')
    return '\n'.join(lines)


def _parse_tool_call(reply, tools):
    calls = _parse_tool_calls(reply, tools)
    return calls[0] if calls else None


def _parse_tool_calls(reply, tools):
    if not reply:
        return []
    lines = _strip_code_fence(reply).strip().splitlines()
    start_idx = None
    preamble_chars = 0
    for idx, line in enumerate(lines):
        stripped = line.strip().strip('`').strip()
        if not stripped:
            continue
        match = _TOOL_LINE.match(stripped)
        if match and match.group(1) in tools:
            start_idx = idx
            break
        preamble_chars += len(stripped)
        if preamble_chars > 400:
            return []
    if start_idx is None:
        return []

    calls = []
    current_name = None
    current_args = []
    for line in lines[start_idx:]:
        stripped = line.strip().strip('`').strip()
        match = _TOOL_LINE.match(stripped)
        if match and match.group(1) in tools:
            if current_name is not None:
                calls.append((current_name, _strip_code_fence('\n'.join(current_args)).strip()))
            current_name = match.group(1)
            current_args = [match.group(2).strip()] if match.group(2).strip() else []
            continue
        if current_name is not None:
            current_args.append(line)
    if current_name is not None:
        calls.append((current_name, _strip_code_fence('\n'.join(current_args)).strip()))
    return calls


def _strip_code_fence(text: str) -> str:
    stripped = (text or '').strip()
    if stripped.startswith('```') and stripped.endswith('```'):
        lines = stripped.splitlines()
        return '\n'.join(lines[1:-1])
    return text
