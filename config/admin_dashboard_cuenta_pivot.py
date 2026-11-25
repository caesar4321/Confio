"""Cuenta inteligente after the pivot: the account as Confío IA's paid hands.

The Cuenta tab's first section (admin_dashboard_smart_account.py) is the
subscription business: billing, rules, payouts, inheritance, the relayer.
This one is what v2 added and what the pivot needs to watch:

- how people get there (the offer in the chat → subscribed → on v2 → a cap
  signed → a first hands-off job);
- what the account does for them (hands-off trades, Comprar purchases, store
  purchases pulled by the purchase spender), with failures and waits;
- the caps people sign, Confío IA+ (proposals, alerts, target splits);
- one row per account, so a subscriber can be looked at as a person.

Team accounts (staff, founders, preview, banned) are shown apart, not
dropped: today they are most of the usage, and ops still needs to see it.
Every figure reads Postgres mirrors; nothing here reads the chain.
"""
import logging
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Max, Q

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
ACCOUNT_ROWS = 50
OFFER_ACTIONS = {'trade_offer', 'purchase_offer', 'offers'}
CAP_ACTIONS = {'trade_cap', 'purchase_cap'}
MOVE_ACTIONS = {'trade_move', 'purchase_move'}
MIGRATION_ACTIONS = {'account_migration'}
WAD = Decimal(10) ** 18


def _pct(part, whole):
    return part / whole * 100 if whole else None


def _url(model, **params):
    from urllib.parse import urlencode

    from django.urls import NoReverseMatch, reverse
    try:
        base = reverse(f'confio_admin:smart_account_{model}_changelist')
    except NoReverseMatch:
        return ''
    return f'{base}?{urlencode(params)}' if params else base


def _user_url(user_id):
    from django.urls import NoReverseMatch, reverse
    try:
        return reverse('confio_admin:users_user_change', args=[user_id])
    except NoReverseMatch:
        return ''


def cuenta_pivot(w):
    """The section's context. Never raises into the page."""
    try:
        return {'sap': _build(w)}
    except Exception:  # noqa: BLE001 - one broken query must not take the admin down
        logger.exception('cuenta pivot dashboard failed')
        return {'sap': {'unavailable': True}}


def _generations():
    """{account address: 'v1' | 'v2'} from the factory's own events: an account made after the first
    ImplementationAdded, or the target of an AccountMigrated, runs v2."""
    from smart_account.models import SmartAccountEvent

    added = SmartAccountEvent.objects.filter(name='ImplementationAdded').aggregate(b=Max('block_number'))['b']
    out = {}
    for args, block in SmartAccountEvent.objects.filter(name='AccountCreated').values_list('args', 'block_number'):
        account = str((args or {}).get('account') or '').lower()
        if account:
            out[account] = 'v2' if added is not None and block >= added else 'v1'
    migrated = []
    for args, at in SmartAccountEvent.objects.filter(name='AccountMigrated').values_list('args', 'block_time'):
        args = args or {}
        for key, generation in (('from', 'v1'), ('to', 'v2')):
            address = str(args.get(key) or '').lower()
            if address:
                out.setdefault(address, generation)
                if key == 'to':
                    out[address] = 'v2'
        migrated.append(at)
    return out, migrated


def _build(w):
    from assistant.models import AssistantTurn
    from blockchain.models import Balance
    from smart_account.models import (SmartAccount, SmartAccountCardPull, SmartAccountEvent, SmartAccountPreparedAction,
                                      SmartAccountRule, SmartAccountTargetAllocation, SmartAccountWatch,
                                      SmartRelayPurchase, SmartRelayTrade)

    from config.admin_dashboard_assistant import excluded_user_ids

    since = w.now - timedelta(days=WINDOW_DAYS)
    team = excluded_user_ids()

    def split(user_ids):
        ids = set(user_ids)
        return {'all': len(ids), 'real': len(ids - team), 'team': len(ids & team)}

    accounts = list(SmartAccount.all_objects.filter(deleted_at__isnull=True).values(
        'id', 'account_id', 'owner_user_id', 'contract_address', 'status', 'plan', 'billing_status', 'paid_until',
        'subscription_epoch', 'created_at'))
    generation, migrations = _generations()
    by_owner = {a['owner_user_id']: a for a in accounts}
    live = [a for a in accounts if a['status'] in ('active', 'cancel_pending')]

    # ── How people get there ────────────────────────────────────────────
    offered, capped, moved, migrated_cards = set(), set(), set(), set()
    for user, actions in AssistantTurn.objects.filter(created_at__gte=since).order_by().values_list(
            'user_id', 'actions'):
        kinds = {a.get('type') for a in actions or [] if isinstance(a, dict)}
        if kinds & OFFER_ACTIONS:
            offered.add(user)
        if kinds & CAP_ACTIONS:
            capped.add(user)
        if kinds & MOVE_ACTIONS:
            moved.add(user)
        if kinds & MIGRATION_ACTIONS:
            migrated_cards.add(user)
    subscribed_30 = {e for e in SmartAccountEvent.objects.filter(
        name='Subscribed', block_time__gte=since).values_list('smart_account__owner_user_id', flat=True) if e}
    on_v2 = {a['owner_user_id'] for a in live if generation.get(a['contract_address'].lower()) == 'v2'}
    rules = SmartAccountRule.objects.filter(deleted_at__isnull=True)
    trade_rule_owners = set(rules.filter(kind='trade', active=True).values_list('smart_account__owner_user_id',
                                                                                flat=True))
    purchase_rule_owners = set(rules.filter(kind='purchase', active=True).values_list(
        'smart_account__owner_user_id', flat=True))
    card_rule_owners = set(rules.filter(kind='card', active=True).values_list('smart_account__owner_user_id',
                                                                              flat=True))
    handsoff_users = (set(SmartRelayTrade.objects.filter(status='done').values_list('user_id', flat=True))
                      | set(SmartRelayPurchase.objects.filter(status='done').values_list('user_id', flat=True))
                      | set(SmartAccountCardPull.objects.values_list('smart_account__owner_user_id', flat=True)))
    funnel = [
        {'label': 'Saw the offer in the chat (30 days)', **split(offered)},
        {'label': 'Subscribed (30 days)', **split(subscribed_30)},
        {'label': 'Live accounts', **split(a['owner_user_id'] for a in live)},
        {'label': 'On v2 (hands-off capable)', **split(on_v2)},
        {'label': 'Signed a trade cap', **split(trade_rule_owners)},
        {'label': 'Signed a Comprar purchase cap', **split(purchase_rule_owners)},
        {'label': 'Signed a store purchase rule (card)', **split(card_rule_owners)},
        {'label': 'Had a hands-off job done (ever)', **split(handsoff_users)},
    ]
    chat_cards = [
        {'label': 'Offer cards (subscribe / do it yourself)', **split(offered)},
        {'label': 'Cap cards (pick a weekly limit)', **split(capped)},
        {'label': 'Move cards (dollars into the account)', **split(moved)},
        {'label': 'Update-to-v2 cards', **split(migrated_cards)},
    ]

    # ── What the account did ────────────────────────────────────────────
    trades = list(SmartRelayTrade.objects.order_by().values(
        'user_id', 'status', 'side', 'asset_kind', 'ticker', 'amount_usd', 'error_code', 'created_at', 'updated_at',
        'notified_at'))
    trades_30 = [t for t in trades if t['created_at'] >= since]
    done = [t for t in trades_30 if t['status'] == 'done']
    seconds = sorted((t['updated_at'] - t['created_at']).total_seconds() for t in done)
    trade_summary = {
        'by_status': Counter(t['status'] for t in trades_30).most_common(),
        'by_side': Counter(f"{t['side']} {t['asset_kind']}" for t in done).most_common(),
        'tickers': Counter(t['ticker'].removesuffix('on') for t in done).most_common(8),
        'usd': sum((t['amount_usd'] or Decimal(0) for t in done), Decimal(0)),
        'done': len(done),
        'people': split(t['user_id'] for t in done),
        'errors': Counter(t['error_code'] for t in trades_30 if t['status'] == 'failed' and t['error_code']
                          ).most_common(6),
        'median_s': seconds[len(seconds) // 2] if seconds else None,
        'unnotified': sum(1 for t in done if not t['notified_at']),
        'ever': len([t for t in trades if t['status'] == 'done']),
    }
    purchases = list(SmartRelayPurchase.objects.filter(created_at__gte=since).order_by().values(
        'user_id', 'status', 'amount_usd', 'error_code', 'store_name'))
    pdone = [p for p in purchases if p['status'] == 'done']
    purchase_summary = {
        'by_status': Counter(p['status'] for p in purchases).most_common(),
        'done': len(pdone),
        'usd': sum((p['amount_usd'] or Decimal(0) for p in pdone), Decimal(0)),
        'stores': Counter(p['store_name'] or '—' for p in pdone).most_common(6),
        'errors': Counter(p['error_code'] for p in purchases if p['status'] == 'failed' and p['error_code']
                          ).most_common(6),
        'people': split(p['user_id'] for p in pdone),
    }
    pulls = list(SmartAccountCardPull.objects.filter(pulled_at__gte=since).order_by().values(
        'smart_account__owner_user_id', 'usd_spent'))
    store_summary = {
        'pulls': len(pulls),
        'usd': sum((Decimal(p['usd_spent'] or 0) for p in pulls), Decimal(0)),
        'people': split(p['smart_account__owner_user_id'] for p in pulls),
    }
    paused = (SmartAccountEvent.objects.filter(name='TradePausedSet').order_by('-block_number', '-log_index')
              .values_list('args', flat=True).first())

    # ── The caps people sign ────────────────────────────────────────────
    def caps(kind):
        amounts = sorted(Decimal(a) for a in rules.filter(kind=kind, active=True).values_list('amount', flat=True))
        if not amounts:
            return {'n': 0}
        return {'n': len(amounts), 'min': amounts[0], 'median': amounts[len(amounts) // 2], 'max': amounts[-1],
                'total': sum(amounts, Decimal(0))}
    cap_rows = [dict(caps('trade'), label='Weekly trade cap'), dict(caps('purchase'), label='Comprar purchase cap'),
                dict(caps('card'), label='Store purchase rule (per 28 days)')]

    # ── Confío IA+ ──────────────────────────────────────────────────────
    prepared = SmartAccountPreparedAction.objects.filter(created_at__gte=since)
    ia_plus = {
        'prepared': list(prepared.values('kind').annotate(
            n=Count('id'), used=Count('id', filter=Q(consumed=True))).order_by('-n')[:10]),
        'watches': SmartAccountWatch.objects.filter(deleted_at__isnull=True).count(),
        'targets': SmartAccountTargetAllocation.objects.filter(deleted_at__isnull=True).count(),
    }

    # ── One row per account ─────────────────────────────────────────────
    account_ids = [a['id'] for a in accounts]
    active_rules = defaultdict(Counter)
    for account, kind in rules.filter(active=True, smart_account_id__in=account_ids).values_list(
            'smart_account_id', 'kind'):
        active_rules[account][kind] += 1
    jobs = Counter(t['user_id'] for t in trades_30 if t['status'] == 'done')
    jobs.update(p['user_id'] for p in pdone)
    jobs.update(p['smart_account__owner_user_id'] for p in pulls)
    dollars = defaultdict(Decimal)
    try:
        from config.admin_dashboard_smart_account import DOLLAR_TOKENS
        mirror = {a['account_id']: a['id'] for a in accounts if a['account_id']}
        for account, amount in Balance.objects.order_by().filter(
                account_id__in=list(mirror), token__in=DOLLAR_TOKENS).values_list('account_id', 'amount'):
            dollars[mirror[account]] += Decimal(amount or 0)
    except Exception:  # noqa: BLE001 - the mirror's shape differs: the column stays empty
        logger.info('cuenta pivot: account balances unavailable', exc_info=True)
    rows = []
    for a in sorted(accounts, key=lambda a: a['created_at'], reverse=True)[:ACCOUNT_ROWS]:
        rows.append({
            'user_id': a['owner_user_id'], 'user_url': _user_url(a['owner_user_id']),
            'team': a['owner_user_id'] in team, 'status': a['status'], 'plan': a['plan'] or '—',
            'billing': a['billing_status'], 'paid_until': a['paid_until'],
            'generation': generation.get(a['contract_address'].lower(), '?'),
            'rules': ', '.join(f'{k} {n}' for k, n in sorted(active_rules[a['id']].items())) or '—',
            'jobs_30': jobs.get(a['owner_user_id'], 0), 'dollars': dollars.get(a['id']),
            'since': a['created_at'],
        })

    return {
        'window_days': WINDOW_DAYS,
        'funnel': funnel,
        'chat_cards': chat_cards,
        'generations': Counter(generation.get(a['contract_address'].lower(), '?') for a in live).most_common(),
        'migrations': len(migrations),
        'last_migration': max(migrations) if migrations else None,
        'trade_paused': None if paused is None else bool((paused or {}).get('paused')),
        'trades': trade_summary,
        'purchases': purchase_summary,
        'store': store_summary,
        'caps': cap_rows,
        'ia_plus': ia_plus,
        'accounts': rows,
        'accounts_total': len(accounts),
        'links': {'trades': _url('smartrelaytrade'), 'purchases': _url('smartrelaypurchase'),
                  'pulls': _url('smartaccountcardpull'), 'rules': _url('smartaccountrule')},
    }
