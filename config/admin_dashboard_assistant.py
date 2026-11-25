"""Confío IA (the AI-first pivot): its own dashboard tab.

The question: do people let Confío IA do a money job for them, and do they
come back and let it do one again? The north star is the share of people
whose first paid job through Confío IA is followed by another within 30
days.

Everything here is people, not events, unless a heading says otherwise.
People are real users (users.analytics: finished signup, no platform test
accounts) minus staff, founder accounts and anyone ever banned: the same
rule as the YC metrics, so a founder's canary or a fraud ring never reads
as traction.

Sources, all already written by the product (nothing new is tracked):
- AssistantTurn: one per answered message, with its modality and the tools
  it called ("name" or "name:denied"). Its tools say what was asked.
- PaymentIntent: the payment cards in the chat (any rail), with outcome.
- SponsoredBatch with a chat-trade-… request id: stock trades signed on a
  chat card (assistant/trades.py).
- SmartRelayTrade / SmartRelayPurchase: hands-off trades and Comprar
  purchases executed by a Cuenta inteligente.
- AgentTask: the shopping agent's store tasks.
"""
import logging
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Min, Q

from config.admin_dashboard_sections import ARG_TZ

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
REPEAT_DAYS = 30
DAILY_DAYS = 30
TOP_COUNTRIES = 12
TOP_REASONS = 8
# Founder accounts (users 4 and 5): left out of every count, like the YC metrics.
FOUNDER_USER_IDS_DEFAULT = '4,5'

# What a tool call says the person asked for. Tools are recorded as "name"
# or "name:outcome" (denied, answered, confirmed): the part before ":".
CATEGORIES = (
    ('payment', 'Pay someone or a QR'),
    ('shopping', 'Buy at a store'),
    ('trade', 'Buy or sell stocks, gold, bitcoin'),
    ('comprar', 'Comprar marketplace'),
    ('cuenta', 'Cuenta inteligente rules'),
    ('guide', 'Show me where / how'),
    ('human', 'Talk to the team'),
    ('info', 'Questions about their money or Confío'),
)
MONEY_CATEGORIES = ('payment', 'shopping', 'trade', 'comprar', 'cuenta')
_PAYMENT_TOOLS = {'prepare_payment', 'withdraw_payment_card', 'notify_rail'}
_TRADE_TOOLS = {'propose_stock_trade', 'trade'}
_CUENTA_TOOLS = {'propose_smart_account_rule', 'propose_target_allocation'}
_GUIDE_TOOLS = {'navigate', 'show_steps', 'act_here'}
# Cards a reply can carry that ask the person to approve something.
APPROVAL_ACTIONS = {'trade', 'relay_trade', 'trade_cap', 'trade_move', 'relay_purchase', 'purchase_cap',
                    'purchase_move', 'purchase_offer', 'comprar_purchase'}
PAID_KINDS = (
    ('card', 'Payment card in the chat'),
    ('store', 'Store purchase (shopping agent)'),
    ('chat_trade', 'Trade signed on a chat card'),
    ('handsoff_trade', 'Hands-off trade (Cuenta inteligente)'),
    ('handsoff_purchase', 'Hands-off Comprar purchase'),
)
TASK_STOPS_PAID = 'paid'


def tool_name(entry):
    """The tool's name from one AssistantTurn.tools entry ('' when unreadable)."""
    if isinstance(entry, dict):
        entry = entry.get('name') or ''
    return str(entry or '')


def tool_category(name):
    """The category of one recorded tool call ('info' for anything not money, guide or human)."""
    base = name.split(':', 1)[0]
    if base in _PAYMENT_TOOLS:
        return 'payment'
    if base in _TRADE_TOOLS:
        return 'trade'
    if base.startswith('start_store_task') or base.startswith('store_'):
        return 'shopping'
    if 'comprar' in base:
        return 'comprar'
    if base in _CUENTA_TOOLS:
        return 'cuenta'
    if base in _GUIDE_TOOLS:
        return 'guide'
    if base.startswith('escalate_to_human'):
        return 'human'
    return 'info'


def _pct(part, whole):
    return part / whole * 100 if whole else None


def excluded_user_ids():
    """Staff, founder accounts and anyone ever banned: never counted."""
    from django.contrib.auth import get_user_model

    from security.models import UserBan

    user_model = get_user_model()
    ids = set(user_model.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).values_list('id', flat=True))
    ids |= set(UserBan.objects.values_list('user_id', flat=True))
    raw = str(getattr(settings, 'ADMIN_METRICS_EXCLUDED_USER_IDS', FOUNDER_USER_IDS_DEFAULT) or '')
    ids |= {int(part) for part in raw.split(',') if part.strip().isdigit()}
    try:
        from config.admin_dashboard_growth import preview_user_ids
        ids |= preview_user_ids()
    except Exception:  # noqa: BLE001 - the staff and bans above still apply
        logger.warning('assistant dashboard: preview ids unreadable', exc_info=True)
    return ids


def _real_ids():
    from users.analytics import get_real_users_queryset
    return set(get_real_users_queryset().values_list('id', flat=True))


def paid_actions(counted):
    """Every money job Confío IA completed, all time: [(user_id, at, kind, usd or None)]."""
    from blockchain.models import SponsoredBatch
    from payment_accounts.models import PaymentIntent
    from smart_account.models import SmartRelayPurchase, SmartRelayTrade

    out = []
    for user, at, source, usd in PaymentIntent.objects.filter(outcome='paid').order_by().values_list(
            'user_id', 'updated_at', 'source', 'total_usd'):
        out.append((user, at, 'store' if source == 'agent_checkout' else 'card', usd))
    for user, at in SponsoredBatch.objects.filter(
            client_request_id__startswith='chat-trade-', status='confirmed').order_by().values_list(
            'user_id', 'created_at'):
        out.append((user, at, 'chat_trade', None))
    for user, at, usd in SmartRelayTrade.objects.filter(status='done').order_by().values_list(
            'user_id', 'updated_at', 'amount_usd'):
        out.append((user, at, 'handsoff_trade', usd))
    for user, at, usd in SmartRelayPurchase.objects.filter(status='done').order_by().values_list(
            'user_id', 'updated_at', 'amount_usd'):
        out.append((user, at, 'handsoff_purchase', usd))
    return [row for row in out if row[0] in counted]


def repeat_payers(actions, now):
    """The north star. First-time payers whose first paid job is at least REPEAT_DAYS old (so the answer is
    known), and how many paid again within REPEAT_DAYS of it; plus those still inside their window."""
    by_user = defaultdict(list)
    for user, at, _kind, _usd in actions:
        by_user[user].append(at)
    mature = repeated = young = young_repeated = 0
    for times in by_user.values():
        times.sort()
        first = times[0]
        again = any(first < t <= first + timedelta(days=REPEAT_DAYS) for t in times[1:])
        if first <= now - timedelta(days=REPEAT_DAYS):
            mature += 1
            repeated += again
        else:
            young += 1
            young_repeated += again
    return {'payers': len(by_user), 'mature': mature, 'repeated': repeated, 'pct': _pct(repeated, mature),
            'young': young, 'young_repeated': young_repeated}


def _turns(since, counted):
    from assistant.models import AssistantTurn
    rows = AssistantTurn.objects.filter(created_at__gte=since).order_by().values_list(
        'user_id', 'created_at', 'modality', 'tools', 'actions', 'error', 'latency_ms', 'cost_usd')
    return [row for row in rows if row[0] in counted]


def assistant_pivot(w):
    """The Confío IA tab's context. Never raises into the page."""
    try:
        return {'ia': _build(w)}
    except Exception:  # noqa: BLE001 - one broken query must not take the admin down
        logger.exception('assistant dashboard failed')
        return {'ia': {'unavailable': True}}


def _build(w):
    from agent_tasks.models import AgentTask
    from django.contrib.auth import get_user_model
    from payment_accounts.models import PaymentIntent
    from smart_account.models import SmartAccount, SmartRelayPurchase, SmartRelayTrade

    since = w.now - timedelta(days=WINDOW_DAYS)
    since_7 = w.now - timedelta(days=7)
    excluded = excluded_user_ids()
    counted = _real_ids() - excluded

    turns = _turns(since, counted)
    talked, talked_7 = set(), set()
    asked = defaultdict(set)              # category -> people
    denied = Counter()                    # tool -> refusals
    calls = Counter()                     # category -> calls
    prepared = set()                      # people shown something to approve
    voice = errors = 0
    latencies, cost = [], Decimal(0)
    daily = defaultdict(lambda: {'people': set(), 'turns': 0, 'voice': 0, 'money': set()})
    for user, at, modality, tools, actions, error, latency, turn_cost in turns:
        talked.add(user)
        if at >= since_7:
            talked_7.add(user)
        day = at.astimezone(ARG_TZ).date()
        daily[day]['people'].add(user)
        daily[day]['turns'] += 1
        if str(modality or '').upper() == 'VOICE_NOTE':
            voice += 1
            daily[day]['voice'] += 1
        if error:
            errors += 1
        if latency:
            latencies.append(latency)
        cost += Decimal(turn_cost or 0)
        for entry in tools or []:
            name = tool_name(entry)
            if not name:
                continue
            category = tool_category(name)
            calls[category] += 1
            asked[category].add(user)
            if category in MONEY_CATEGORIES:
                daily[day]['money'].add(user)
            if name.endswith(':denied'):
                denied[name.split(':', 1)[0]] += 1
        if any(isinstance(a, dict) and a.get('type') in APPROVAL_ACTIONS for a in actions or []):
            prepared.add(user)
    money = set().union(*(asked[c] for c in MONEY_CATEGORIES)) if asked else set()

    intents = PaymentIntent.objects.filter(created_at__gte=since).order_by()
    card_rows = [r for r in intents.values_list('user_id', 'created_by', 'source', 'state', 'outcome', 'total_usd')
                 if r[0] in counted]
    prepared |= {r[0] for r in card_rows}
    tasks = [t for t in AgentTask.objects.filter(created_at__gte=since).order_by().values_list(
        'user_id', 'country', 'state', 'reason', 'checkout_at', 'payment_intent_id', 'payment_intent__outcome',
        'cost_usd') if t[0] in counted]
    prepared |= {t[0] for t in tasks}
    relay_trades = [r for r in SmartRelayTrade.objects.filter(created_at__gte=since).order_by().values_list(
        'user_id', 'status', 'amount_usd') if r[0] in counted]
    relay_purchases = [r for r in SmartRelayPurchase.objects.filter(created_at__gte=since).order_by().values_list(
        'user_id', 'status', 'amount_usd') if r[0] in counted]
    prepared |= {r[0] for r in relay_trades} | {r[0] for r in relay_purchases}
    # A QR scanned or a code pasted in the chat is a money job asked without a tool call.
    money = (money | prepared) & talked if talked else money | prepared

    actions_all = paid_actions(counted)
    actions_30 = [a for a in actions_all if a[1] >= since]
    paid_30 = {a[0] for a in actions_30}
    per_user_30 = Counter(a[0] for a in actions_30)
    for user, at, _kind, _usd in actions_30:
        daily[at.astimezone(ARG_TZ).date()].setdefault('paid', 0)
        daily[at.astimezone(ARG_TZ).date()]['paid'] += 1
    paid_usd_30 = sum((Decimal(a[3]) for a in actions_30 if a[3] is not None), Decimal(0))
    north = repeat_payers(actions_all, w.now)

    # Each step is a subset of the one before: people who talked to Confío IA in the window.
    funnel_steps = [
        ('Talked to Confío IA', talked),
        ('Asked it for a money job', money),
        ('Got something to approve', prepared & money),
        ('Confío IA paid for them', paid_30 & money),
        ('Paid 2+ times', {u for u, n in per_user_30.items() if n >= 2} & money),
    ]
    top = len(talked) or 1
    funnel = []
    previous = None
    for label, people in funnel_steps:
        count = len(people)
        funnel.append({'label': label, 'count': count, 'of_top': _pct(count, top) if talked else None,
                       'of_previous': _pct(count, previous) if previous else None,
                       'bar': min(100, round(count / top * 100)) if talked else 0})
        previous = count

    # New signups: does Confío IA reach them, and does it do a money job for them?
    user_model = get_user_model()
    signups = [(pk, at) for pk, at in user_model.objects.filter(onboarded_at__gte=since).order_by().values_list(
        'id', 'onboarded_at') if pk in counted]
    from assistant.models import AssistantTurn
    first_turn = dict(AssistantTurn.objects.filter(user_id__in=[pk for pk, _ in signups]).order_by().values(
        'user_id').annotate(first=Min('created_at')).values_list('user_id', 'first'))
    signup_ids = {pk for pk, _ in signups}
    talked_first_day = {pk for pk, at in signups if pk in first_turn and first_turn[pk] - at <= timedelta(days=1)}
    cohort = {
        'signups': len(signups),
        'talked': len(signup_ids & set(first_turn)),
        'talked_first_day': len(talked_first_day),
        'money': len(signup_ids & money),
        'paid': len(signup_ids & {a[0] for a in actions_all}),
    }
    for key in ('talked', 'talked_first_day', 'money', 'paid'):
        cohort[f'{key}_pct'] = _pct(cohort[key], cohort['signups'])

    days = []
    for offset in range(DAILY_DAYS - 1, -1, -1):
        day = (w.now - timedelta(days=offset)).astimezone(ARG_TZ).date()
        row = daily.get(day) or {'people': set(), 'turns': 0, 'voice': 0, 'money': set()}
        days.append({'day': day, 'people': len(row['people']), 'turns': row['turns'], 'voice': row['voice'],
                     'money': len(row['money']), 'paid': row.get('paid', 0)})
    peak = max((d['people'] for d in days), default=0) or 1
    for d in days:
        d['bar'] = round(d['people'] / peak * 100)

    intents_mix = [{'key': key, 'label': label, 'people': len(asked.get(key, ())), 'calls': calls.get(key, 0),
                    'money': key in MONEY_CATEGORIES} for key, label in CATEGORIES]

    def card_group(rows):
        return {
            'created': len(rows),
            'signed': sum(1 for r in rows if r[3] == 'submitted'),
            'paid': sum(1 for r in rows if r[4] == 'paid'),
            'failed': sum(1 for r in rows if r[4] in ('failed', 'refunded')),
            'dropped': sum(1 for r in rows if r[3] in ('expired', 'cancelled')),
            'paid_usd': sum((Decimal(r[5]) for r in rows if r[4] == 'paid' and r[5] is not None), Decimal(0)),
            'people': len({r[0] for r in rows}),
        }
    card_kinds = (('assistant', 'Prepared by Confío IA'), ('scan', 'Scanned QR'), ('share', 'Shared QR'),
                  ('paste', 'Pasted code'))
    cards = [dict(card_group([r for r in card_rows if r[1] == key and r[2] != 'agent_checkout']), label=label)
             for key, label in card_kinds]
    cards.append(dict(card_group([r for r in card_rows if r[2] == 'agent_checkout']), label='Store checkouts'))
    cards_total = dict(card_group(card_rows), label='All payment cards')

    task_countries = Counter(t[1] or '—' for t in tasks)
    shopping = {
        'started': len(tasks),
        'people': len({t[0] for t in tasks}),
        'checkout': sum(1 for t in tasks if t[4]),
        'card': sum(1 for t in tasks if t[5]),
        'paid': sum(1 for t in tasks if t[6] == 'paid'),
        'active': sum(1 for t in tasks if t[2] in AgentTask.ACTIVE),
        'cost': sum((Decimal(t[7] or 0) for t in tasks), Decimal(0)),
        'countries': [{'country': c, 'tasks': n,
                       'checkout': sum(1 for t in tasks if (t[1] or '—') == c and t[4]),
                       'paid': sum(1 for t in tasks if (t[1] or '—') == c and t[6] == 'paid')}
                      for c, n in task_countries.most_common()],
        'reasons': Counter(t[3] or t[2] for t in tasks if t[2] in ('stopped', 'cancelled')).most_common(TOP_REASONS),
    }
    shopping['cost_per_task'] = (shopping['cost'] / shopping['started']) if shopping['started'] else None

    trade_status = Counter(r[1] for r in relay_trades)
    purchase_status = Counter(r[1] for r in relay_purchases)
    chat_trades_30 = sum(1 for a in actions_30 if a[2] == 'chat_trade')
    trades = {
        'asked_people': len(asked.get('trade', ())),
        'proposals': calls.get('trade', 0),
        'denied': denied.get('propose_stock_trade', 0),
        'chat_signed': chat_trades_30,
        'handsoff': sorted(trade_status.items()),
        'handsoff_done': trade_status.get('done', 0),
        'handsoff_failed': trade_status.get('failed', 0),
        'handsoff_waiting': sum(n for s, n in trade_status.items() if s.startswith('waiting')),
    }
    cuenta = {
        'active': SmartAccount.objects.filter(status__in=('active', 'cancel_pending')).exclude(
            owner_user_id__in=excluded).count(),
        'purchases': sorted(purchase_status.items()),
        'purchases_done': purchase_status.get('done', 0),
    }

    latencies.sort()

    def percentile(p):
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))] if latencies else None
    quality = {
        'turns': len(turns),
        'voice': voice,
        'voice_pct': _pct(voice, len(turns)),
        'errors': errors,
        'error_pct': _pct(errors, len(turns)),
        'handoffs': calls.get('human', 0),
        'p50_s': (percentile(0.5) or 0) / 1000 if latencies else None,
        'p95_s': (percentile(0.95) or 0) / 1000 if latencies else None,
        'cost': cost,
        'cost_per_person': (cost / len(talked)) if talked else None,
        'denied': denied.most_common(TOP_REASONS),
    }

    countries = Counter()
    country_of = dict(user_model.objects.filter(id__in=talked).values_list('id', 'country'))
    by_country = defaultdict(lambda: {'talked': 0, 'money': 0, 'paid': 0})
    for user in talked:
        row = by_country[country_of.get(user) or '—']
        row['talked'] += 1
        row['money'] += user in money
        row['paid'] += user in paid_30
    for code, row in by_country.items():
        countries[code] = row['talked']
    country_rows = [dict(by_country[c], country=c, paid_pct=_pct(by_country[c]['paid'], by_country[c]['talked']))
                    for c, _n in countries.most_common(TOP_COUNTRIES)]

    kinds_30 = Counter(a[2] for a in actions_30)
    return {
        'window_days': WINDOW_DAYS,
        'repeat_days': REPEAT_DAYS,
        'talked_30': len(talked),
        'talked_7': len(talked_7),
        'money_30': len(money),
        'money_pct': _pct(len(money), len(talked)),
        'paid_people_30': len(paid_30),
        'paid_actions_30': len(actions_30),
        'paid_usd_30': paid_usd_30,
        'north': north,
        'funnel': funnel,
        'cohort': cohort,
        'days': days,
        'intents': intents_mix,
        'cards': cards,
        'cards_total': cards_total,
        'shopping': shopping,
        'trades': trades,
        'cuenta': cuenta,
        'quality': quality,
        'countries': country_rows,
        'paid_kinds': [{'label': label, 'count': kinds_30.get(key, 0)} for key, label in PAID_KINDS],
        'excluded': len(excluded),
    }
