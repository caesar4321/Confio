"""Replay real Confio Assistant conversations through two models and compare.

Every user message the assistant answered is asked again, with the same
earlier messages, to each model under test. A judge that never sees which
model wrote which reply (order shuffled per case) picks the better one against
the approved FAQ. Account data is mocked as a new user's (US$0, no spending),
the same for both models. Costs well under US$1 per 100 cases.

  manage.py assistant_compare --export conversations.json \\
      --models gpt-6-luna:low claude-haiku-5-5:low [--limit 40] [--out results.json]

The export is the JSON the team pulls from prod (conversations[].messages);
it holds customer messages, so keep it out of the repo.
"""
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import override_settings

from assistant import conf
from assistant.engine import AssistantUnavailable, Viewer, run_turn
from assistant.management.commands.assistant_eval import JUDGE_MODEL, NEW_USER_PORTFOLIO
from assistant.prompts import FAQ

NEW_USER_MONTH = {'disponible': True, 'mes': 'octubre 2026', 'mes_en_curso': True,
                  'actual': {'entro_usd': '0.00', 'salio_usd': '0.00', 'recargas_usd': '0.00', 'retiros_usd': '0.00',
                             'ahorro_neto_usd': '0.00', 'inversion_neta_usd': '0.00', 'movimientos': 0},
                  'comparacion': {}, 'principales_contactos': []}
TIMEZONES = {'BO': 'America/La_Paz', 'VE': 'America/Caracas', 'PE': 'America/Lima', 'CO': 'America/Bogota',
             'AR': 'America/Argentina/Buenos_Aires', 'CL': 'America/Santiago', 'MX': 'America/Mexico_City',
             'EC': 'America/Guayaquil', 'PY': 'America/Asuncion', 'GT': 'America/Guatemala'}
# The founder's own test account.
SKIP_USERS = {5}


def cases_from_export(path):
    """(conversation, history up to and including the user message) for every AI-answered user message."""
    data = json.load(open(path, encoding='utf-8'))
    cases = []
    for conv in data['conversations']:
        if conv['user_id'] in SKIP_USERS or conv.get('business'):
            continue
        msgs = [m for m in conv['messages'] if m['sender_type'] != 'SYSTEM' and (m['body'] or '').strip()]
        for i, m in enumerate(msgs):
            nxt = msgs[i + 1] if i + 1 < len(msgs) else None
            if m['sender_type'] == 'USER' and nxt and (nxt['metadata'] or {}).get('ai'):
                cases.append({'conversation': conv['id'], 'country': conv['phone_country'] or 'BO',
                              'first_name': (conv['name'] or '').split(' ')[0] or 'Ana',
                              'history': msgs[max(0, i - 15):i + 1], 'production_reply': nxt['body']})
    return cases


def as_messages(history):
    return [SimpleNamespace(sender_type=m['sender_type'], body=m['body'], metadata=m['metadata'] or {},
                            sender_user_id=m.get('sender_user_id')) for m in history]


def transcript(history):
    who = {'USER': 'Usuario', 'AGENT': 'Asistente'}
    return '\n'.join(f"{who.get(m['sender_type'], m['sender_type'])}: {m['body']}" for m in history)


def judge_pair(case, first, second):
    prompt = (
        'Eres revisor de calidad del asistente de Confío, una billetera de dólares digitales para Latinoamérica. '
        'Abajo están las respuestas aprobadas (FAQ), que son la verdad sobre el producto, una conversación real y '
        'dos respuestas candidatas al último mensaje. Juzga cuál es mejor para esa persona: exacta según la FAQ y '
        'el país, responde lo que preguntó (no un paso anterior), clara y breve, sin relleno ni repetir lo que no '
        'aporta, en buen español. No premies la longitud. Los datos de la cuenta son de un usuario nuevo '
        '(saldo US$0, sin gastos), así que no castigues que lo diga una vez si viene al caso. Las respuestas usan '
        'herramientas en vivo que no ves: el rendimiento anual de hoy de Confío Dollar+ (3,18%) y abrir pantallas de '
        'la app ("abrí Recargar") son reales, no inventos.\n\n'
        f'=== FAQ ===\n{FAQ}\n\n=== País: {case["country"]} ===\n=== Conversación ===\n'
        f'{transcript(case["history"])}\n\n=== Respuesta A ===\n{first}\n\n=== Respuesta B ===\n{second}\n\n'
        'Devuelve solo JSON: {"ganador": "A"|"B"|"empate", '
        '"A": {"error_factual": bool, "no_responde_lo_preguntado": bool, "relleno": bool}, '
        '"B": {"error_factual": bool, "no_responde_lo_preguntado": bool, "relleno": bool}, '
        '"motivo": "una frase"}')
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={'Authorization': f'Bearer {settings.OPENAI_API_KEY}', 'Content-Type': 'application/json'},
        json={'model': JUDGE_MODEL, 'input': [{'role': 'user', 'content': prompt}],
              'text': {'format': {'type': 'json_object'}}, 'max_output_tokens': 3000, 'store': False},
        timeout=120,
    )
    data = response.json()
    text = data.get('output_text') or ''.join(
        p.get('text', '') for it in data.get('output', []) if it.get('type') == 'message'
        for p in it.get('content', []))
    return json.loads(text or '{}')


def answer(case):
    """One reply from whichever model the settings name (set once per arm, never per thread)."""
    viewer = Viewer(user=None, account=None, account_type='personal', business_id=None, is_business_owner=False,
                    tz=ZoneInfo(TIMEZONES.get(case['country'], 'America/La_Paz')), screen='Home')
    started = time.monotonic()
    try:
        result = run_turn(viewer, as_messages(case['history']), first_name=case['first_name'],
                          account_label='personal', country=case['country'], analyses_left=0)
    except AssistantUnavailable as exc:
        return {'reply': f'<sin respuesta: {exc}>', 'error': True, 'seconds': time.monotonic() - started,
                'cost': 0.0, 'actions': [], 'handoff': ''}
    return {'reply': result.reply, 'error': False, 'seconds': time.monotonic() - started,
            'cost': float(result.cost_usd), 'actions': [a.get('destination') for a in result.actions],
            'handoff': result.handoff_reason}


class Command(BaseCommand):
    help = 'Replay real assistant conversations through two models and judge them blind.'

    def add_arguments(self, parser):
        parser.add_argument('--export', required=True)
        parser.add_argument('--models', nargs=2, required=True, metavar='MODEL:EFFORT')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--seed', type=int, default=7)
        parser.add_argument('--workers', type=int, default=6)
        parser.add_argument('--out')

    def handle(self, *args, **opts):
        arms = [tuple((spec.split(':') + [''])[:2]) for spec in opts['models']]
        cases = cases_from_export(opts['export'])
        rng = random.Random(opts['seed'])
        if opts['limit'] and len(cases) > opts['limit']:
            cases = rng.sample(cases, opts['limit'])
        self.stdout.write(f'{len(cases)} cases, arms={arms}, judge={JUDGE_MODEL}\n')

        swaps = [rng.random() < 0.5 for _ in cases]

        def judge_case(item):
            case, replies, swap = item
            first, second = (replies[1], replies[0]) if swap else (replies[0], replies[1])
            try:
                verdict = judge_pair(case, first['reply'], second['reply'])
            except Exception as exc:  # noqa: BLE001 - one bad judge call must not sink the run
                verdict = {'ganador': 'error', 'motivo': str(exc)[:200]}
            # Map A/B back to arm 0/1.
            pos = {'A': 1 if swap else 0, 'B': 0 if swap else 1}
            winner = pos.get(verdict.get('ganador'))
            flags = [verdict.get('B' if swap else 'A') or {}, verdict.get('A' if swap else 'B') or {}]
            return {**case, 'replies': replies, 'winner': winner, 'tie': verdict.get('ganador') == 'empate',
                    'flags': flags, 'why': verdict.get('motivo', '')}

        per_arm = []
        with patch('assistant.engine.month_summary_data', return_value=NEW_USER_MONTH), \
                patch('assistant.engine.movements_data', return_value={'disponible': True, 'movimientos': []}), \
                patch('assistant.engine.portfolio_data', return_value=NEW_USER_PORTFOLIO):
            for model, effort in arms:
                # Settings are process-wide: one arm at a time, its cases in parallel.
                with override_settings(CONFIO_ASSISTANT_MODEL=model, CONFIO_ASSISTANT_REASONING_EFFORT=effort or None), \
                        ThreadPoolExecutor(max_workers=opts['workers']) as pool:
                    per_arm.append(list(pool.map(answer, cases)))
                self.stdout.write(f'answered with {model}\n')
        with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
            results = list(pool.map(judge_case, [(case, [per_arm[0][i], per_arm[1][i]], swaps[i])
                                                 for i, case in enumerate(cases)]))

        names = [f'{m}:{e}' if e else m for m, e in arms]
        self.stdout.write(f"{'':<24}{names[0]:>24}{names[1]:>24}\n")
        wins = [sum(r['winner'] == i for r in results) for i in (0, 1)]
        ties = sum(r['tie'] for r in results)
        rows = [('wins (ties %d)' % ties, wins)]
        for flag in ('error_factual', 'no_responde_lo_preguntado', 'relleno'):
            rows.append((flag, [sum(bool(r['flags'][i].get(flag)) for r in results) for i in (0, 1)]))
        rows.append(('no reply', [sum(r['replies'][i]['error'] for r in results) for i in (0, 1)]))
        rows.append(('handoffs', [sum(bool(r['replies'][i]['handoff']) for r in results) for i in (0, 1)]))
        for label, values in rows:
            self.stdout.write(f'{label:<24}{values[0]:>24}{values[1]:>24}\n')
        for i, label in ((0, names[0]), (1, names[1])):
            ok = [r['replies'][i] for r in results if not r['replies'][i]['error']]
            if ok:
                self.stdout.write(f"{label}: cost/turn US${statistics.mean(x['cost'] for x in ok):.5f}  "
                                  f"latency median {statistics.median(x['seconds'] for x in ok):.1f}s  "
                                  f"p90 {sorted(x['seconds'] for x in ok)[int(0.9 * (len(ok) - 1))]:.1f}s  "
                                  f"words {statistics.mean(len(x['reply'].split()) for x in ok):.0f}\n")
        if opts['out']:
            with open(opts['out'], 'w', encoding='utf-8') as fh:
                json.dump({'arms': names, 'results': results}, fh, ensure_ascii=False, indent=1)
