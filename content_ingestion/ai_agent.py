"""A small, provider-agnostic tool-use loop.

Instead of each provider's native function-calling API, we instruct the model to
request a tool with a single `TOOL <name> <args>` line, run it, feed the result
back, and let it answer. This reuses complete_text() so every provider (Gemini,
Claude, OpenAI, Grok, DeepSeek) gets tools through the same, already-tested path.
"""
from __future__ import annotations

import logging
import re

from content_ingestion.ai_client import complete_text

logger = logging.getLogger(__name__)

_TOOL_LINE = re.compile(r'^TOOL[:\s]+([a-zA-Z_]\w*)\s*(.*)$', re.IGNORECASE)

DEFAULT_MAX_STEPS = 3


def run_with_tools(prompt, provider, system, tools, *, max_steps=DEFAULT_MAX_STEPS):
    """Run a completion that may call tools.

    `tools` maps name -> callable(args: str) -> str (the result text). Returns the
    model's final natural-language answer. Falls back to a plain completion when no
    tools are provided.
    """
    if not tools:
        return complete_text(prompt, provider, system=system)

    full_system = f'{system}\n\n{_tool_instructions(tools)}'
    transcript = prompt
    for _ in range(max_steps):
        reply = complete_text(transcript, provider, system=full_system)
        call = _parse_tool_call(reply, tools)
        if call is None:
            return reply
        name, args = call
        logger.info('AI tool call: %s %r', name, args[:80])
        try:
            result = tools[name](args)
        except Exception as exc:  # noqa: BLE001 - a failing tool must not crash the reply
            logger.exception('Tool %s failed', name)
            result = f'(error ejecutando {name}: {exc})'
        transcript = (
            f'{transcript}\n\n[Resultado de la herramienta {name}:]\n{result}\n\n'
            'Si ya puedes responder al usuario, hazlo en lenguaje natural (sin TOOL). '
            'Si necesitas otra herramienta, pídela con otra línea TOOL.'
        )

    # Out of tool steps — force a plain answer with what we have.
    return complete_text(
        f'{transcript}\n\nResponde ahora al usuario sin usar más herramientas.',
        provider,
        system=full_system,
    )


def _tool_instructions(tools) -> str:
    lines = [
        'Tienes herramientas para consultar información que NO está en el contexto '
        '(por ejemplo videos del chat, mensajes antiguos, la base de conocimiento, '
        'o escribir memoria curada en ConfioAI cuando el usuario lo pide).',
        'Para usar una herramienta corta, responde EXCLUSIVAMENTE con una sola línea:',
        'TOOL <nombre> <argumentos>',
        'Para herramientas de escritura larga (write_memory, write_video_memory), usa este formato multilinea:',
        'TOOL <nombre>',
        'category: <categoria si aplica>',
        'title: <titulo>',
        '<markdown completo>',
        'Herramientas disponibles:',
    ]
    for name, fn in tools.items():
        doc = (getattr(fn, '__doc__', '') or '').strip().splitlines()
        lines.append(f'- {name}: {doc[0] if doc else ""}')
    lines.append(
        'Si usas una herramienta de escritura de memoria, espera su resultado y luego '
        'reporta el archivo/commit. Cuando tengas suficiente información, responde al '
        'usuario normalmente (sin TOOL).'
    )
    return '\n'.join(lines)


def _parse_tool_call(reply, tools):
    """Return (name, args) if the first meaningful line is a known tool call, else None."""
    if not reply:
        return None
    lines = _strip_code_fence(reply).strip().splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip().strip('`').strip()
        if not stripped:
            continue
        match = _TOOL_LINE.match(stripped)
        if match and match.group(1) in tools:
            inline_args = match.group(2).strip()
            trailing = _strip_code_fence('\n'.join(lines[idx + 1:])).strip()
            args = '\n'.join(part for part in (inline_args, trailing) if part).strip()
            return match.group(1), args
        # First real line isn't a tool call -> treat the whole reply as the answer.
        return None
    return None


def _strip_code_fence(text: str) -> str:
    stripped = (text or '').strip()
    if stripped.startswith('```') and stripped.endswith('```'):
        lines = stripped.splitlines()
        return '\n'.join(lines[1:-1])
    return text
