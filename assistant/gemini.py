"""Gemini transport for Confío IA, speaking the Responses shape the engine uses.

The engine builds one OpenAI Responses payload per step. For a `gemini-*`
model, `post` sends that same payload to Gemini's generateContent and hands back
a Responses-shaped result (function_call items, a message with url citations,
usage), so the tool loop, the guards and the fallback to OpenAI stay one code
path. Paid tier only: the key's project is billed (Google Cloud credit), and
free-tier prompts may be used by Google, which customer chats never are.
"""
from __future__ import annotations

import json
import uuid

import requests
from django.conf import settings

URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
_PART_KEY = '_gemini_part'  # the model's own part, thought signature included, replayed on the next step


class GeminiUnavailable(Exception):
    def __init__(self, message, usage=None):
        super().__init__(message)
        self.usage = usage  # tokens Google billed for an answer we could not use


def _parts(content):
    if isinstance(content, str):
        return [{'text': content}]
    parts = []
    for part in content or []:
        kind = part.get('type')
        if kind in ('input_text', 'output_text', 'text'):
            parts.append({'text': part.get('text') or ''})
        elif kind == 'input_image':
            url = str(part.get('image_url') or '')
            if url.startswith('data:') and ';base64,' in url:
                mime, data = url[5:].split(';base64,', 1)
                parts.append({'inlineData': {'mimeType': mime, 'data': data}})
    return parts or [{'text': ''}]


def contents(items):
    """Responses input items -> Gemini contents (user/model turns, merged when consecutive)."""
    if isinstance(items, str):
        items = [{'role': 'user', 'content': items}]
    names, out = {}, []

    def add(role, parts):
        if out and out[-1]['role'] == role:
            out[-1]['parts'].extend(parts)
        else:
            out.append({'role': role, 'parts': list(parts)})

    for item in items or []:
        kind = item.get('type')
        if kind == 'function_call':
            names[item.get('call_id')] = item.get('name')
            try:
                args = json.loads(item.get('arguments') or '{}')
            except (TypeError, ValueError):
                args = {}
            add('model', [item.get(_PART_KEY) or {'functionCall': {'name': item.get('name'), 'args': args}}])
        elif kind == 'function_call_output':
            raw = item.get('output')
            try:
                response = json.loads(raw)
            except (TypeError, ValueError):
                response = raw
            if not isinstance(response, dict):
                response = {'result': response}
            add('user', [{'functionResponse': {'name': names.get(item.get('call_id')) or 'tool',
                                               'response': response}}])
        elif kind == 'reasoning':
            continue  # OpenAI's own; Gemini carries its thinking in the part signatures
        else:
            add('model' if item.get('role') == 'assistant' else 'user', _parts(item.get('content')))
    return out


def request_body(payload):
    body = {'contents': contents(payload.get('input')),
            'generationConfig': {'maxOutputTokens': int(payload.get('max_output_tokens') or 2000)}}
    if payload.get('instructions'):
        body['systemInstruction'] = {'parts': [{'text': payload['instructions']}]}
    effort = (payload.get('reasoning') or {}).get('effort')
    if effort:
        body['generationConfig']['thinkingConfig'] = {
            'thinkingLevel': 'low' if effort in ('minimal', 'low') else 'high'}
    tools = payload.get('tools') or []
    functions = [{'name': tool['name'], 'description': tool.get('description') or '',
                  'parametersJsonSchema': tool.get('parameters') or {'type': 'object', 'properties': {}}}
                 for tool in tools if tool.get('type') == 'function']
    if functions:
        body['tools'] = [{'functionDeclarations': functions}]
        choice = payload.get('tool_choice')
        if choice == 'none':
            body['toolConfig'] = {'functionCallingConfig': {'mode': 'NONE'}}
        elif choice == 'required':
            body['toolConfig'] = {'functionCallingConfig': {'mode': 'ANY'}}
        elif isinstance(choice, dict) and choice.get('name'):
            body['toolConfig'] = {'functionCallingConfig': {'mode': 'ANY', 'allowedFunctionNames': [choice['name']]}}
    return body


def _usage(data):
    usage = data.get('usageMetadata') or {}
    return {'input_tokens': int(usage.get('promptTokenCount') or 0),
            'input_tokens_details': {'cached_tokens': int(usage.get('cachedContentTokenCount') or 0)},
            'output_tokens': int(usage.get('candidatesTokenCount') or 0) + int(usage.get('thoughtsTokenCount') or 0)}


def responses_shape(data):
    """Gemini generateContent result -> the Responses fields the engine reads."""
    candidates = data.get('candidates') or []
    if not candidates:
        reason = (data.get('promptFeedback') or {}).get('blockReason') or 'no candidate'
        raise GeminiUnavailable(f'Gemini gave no answer ({reason})')
    candidate = candidates[0]
    output, texts = [], []
    for part in (candidate.get('content') or {}).get('parts') or []:
        if part.get('thought'):
            continue
        if 'functionCall' in part:
            call = part['functionCall']
            output.append({'type': 'function_call', 'call_id': call.get('id') or f'g_{uuid.uuid4().hex}',
                           'name': call.get('name'), 'arguments': json.dumps(call.get('args') or {}),
                           _PART_KEY: part})
        elif part.get('text'):
            texts.append(part['text'])
    finish = candidate.get('finishReason') or ''
    usage = _usage(data)
    if not output and not ''.join(texts).strip():
        # A stop with nothing in it (it happens on STOP too): the fallback model answers.
        raise GeminiUnavailable(f'Gemini gave an empty answer ({finish or "no reason"})', usage=usage)
    if texts:
        output.append({'type': 'message', 'content': [{'type': 'output_text', 'text': ''.join(texts)}]})
    result = {'output': output, 'status': 'incomplete' if finish == 'MAX_TOKENS' else 'completed', 'usage': usage}
    if finish == 'MAX_TOKENS':
        result['incomplete_details'] = {'reason': 'max_output_tokens'}
    return result


def post(payload, *, timeout):
    key = getattr(settings, 'GEMINI_API_KEY', '')
    if not key:
        raise GeminiUnavailable('GEMINI_API_KEY is not configured')
    body = request_body(payload)
    try:
        response = requests.post(URL.format(model=payload['model']), json=body, timeout=timeout,
                                 headers={'x-goog-api-key': key, 'Content-Type': 'application/json'})
    except requests.RequestException as exc:
        raise GeminiUnavailable(f'Gemini request failed: {type(exc).__name__}') from exc
    if response.status_code >= 400:
        raise GeminiUnavailable(f'Gemini {response.status_code}: {response.text[:300]}')
    try:
        data = response.json()
    except ValueError as exc:
        raise GeminiUnavailable('Gemini sent no JSON') from exc
    return responses_shape(data)


def for_openai(items):
    """Drop Gemini's own fields in place, so the same items continue on OpenAI."""
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item.pop(_PART_KEY, None)
