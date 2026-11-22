"""Cuenta inteligente (smart_account/): its own dashboard tab. Who pays and
how much recurs, what was charged or force-sold, what rules and payouts
ran, who inherits, what IA+ proposed, and what ops must act on (relay
transactions not final, events not applied, claims executable).

Counts read the Postgres mirrors written by smart_account/reconcile.py. The
few chain facts (head block, proxy implementation, sponsor BNB, factory
prices) are one snapshot behind _admin_cached, like every other chain
section: never a read per account. The section never raises into the page:
a failed build renders as "unavailable".
"""
import logging
from collections import Counter, defaultdict
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Count, Min, Q, Sum
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from config.admin_dashboard_sections import _admin_cached, _url

logger = logging.getLogger(__name__)

# Relay transactions are written before broadcast; one still not mined and
# final after this long needs a look (the batch watcher normally settles
# them within a couple of minutes).
RELAY_STUCK_MINUTES = 15
# reconcile._alert_stuck_events alerts the team at the same age. The event
# scanner writes its cursor every run, so a cursor older than this is idle.
EVENT_STUCK_MINUTES = 30
WAD = Decimal(10 ** 18)
NOT_FINAL_RELAY = ('signed', 'sent')
BAD_RELAY = ('reverted', 'reorged', 'dropped')
PAID_WITH = (('cusd', 'cUSD'), ('cusd_plus', 'cUSD+'), ('mixed', 'cUSD + cUSD+'), ('sale', 'Paid by forced sale'))
PLANS = (('annual', 'Annual'), ('monthly', 'Monthly'))
# SmartAccountPayout.status as payouts.py writes it, in lifecycle order.
PAYOUT_STATUSES = (
    ('reserving', 'Reserving'), ('prepared', 'Prepared'), ('pending', 'Pending'),
    ('onchain_sent', 'Sent on chain'), ('funded', 'Funded'), ('review', 'In review'),
    ('paid', 'Paid'), ('cancelled', 'Cancelled'), ('failed', 'Failed'),
)
PAYOUT_ALARM = ('review', 'failed')
PAYOUT_OPEN = ('reserving', 'prepared', 'pending', 'onchain_sent', 'funded', 'review')
RAIL_LABELS = {'ve_pagomovil': 'Pago Móvil (Pago ASAP)'}
DOLLAR_TOKENS = ('CUSD_BSC', 'USDT_BSC')
CLAIM_LIST_LIMIT = 25
# EIP-1967 implementation slot: keccak('eip1967.proxy.implementation') - 1.
EIP1967_IMPL_SLOT = '0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc'


def _q(**params):
    """Querystring for a changelist filter; datetimes carry their UTC offset
    so the list filters on exactly the instant the count used."""
    out = {}
    for key, value in params.items():
        if hasattr(value, 'tzinfo'):
            value = value.astimezone(dt_timezone.utc).isoformat(timespec='seconds')
        out[key] = value
    return urlencode(out)


def _link(model, **params):
    return _url(f'smart_account_{model}_changelist', _q(**params))


def _change_url(model, pk):
    try:
        return reverse(f'confio_admin:smart_account_{model}_change', args=[pk])
    except NoReverseMatch:
        return None


def _wei_usd(values):
    total = 0
    for value in values:
        try:
            total += int(value or 0)
        except (TypeError, ValueError):
            continue
    return Decimal(total) / WAD


def _id_count(setting):
    raw = str(getattr(settings, setting, '') or '')
    if raw.strip() == '*':
        return 'everyone'
    return len({p.strip() for p in raw.split(',') if p.strip()})


def _reasons(queryset, field='error', limit=3):
    counts = Counter(((text or '').strip().splitlines() or ['no reason recorded'])[0][:70] or 'no reason recorded'
                     for text in queryset.values_list(field, flat=True))
    return counts.most_common(limit)


def _explorer(address):
    if not address:
        return None
    host = 'testnet.bscscan.com' if int(getattr(settings, 'BSC_CHAIN_ID', 56) or 56) == 97 else 'bscscan.com'
    return f'https://{host}/address/{address}'


def _money(agg):
    return {'n': agg.get('n') or 0, 'usd': agg.get('usd') or Decimal('0')}


# ── chain snapshot (cached) ──────────────────────────────────────────────

def _chain_snapshot(use_cache=True):
    """Head block, proxy implementation, sponsor BNB and factory prices in
    one read. Each fact is None when unreadable; source is 'unavailable'
    only when nothing could be read (then it is never cached)."""
    from smart_account import chain, offer

    factory = chain.factory_address()
    out = {'source': 'unconfigured' if not factory else 'chain', 'head_block': None, 'implementation': None,
           'account_implementation': None, 'sponsor_bnb': None, 'prices': None}
    if not factory:
        return out
    reads = 0

    def attempt(key, fn):
        nonlocal reads
        try:
            out[key] = fn()
            reads += 1
        except Exception:  # noqa: BLE001 — one unreadable fact is "unknown", never zero
            logger.warning('smart account dashboard: %s unreadable', key, exc_info=True)

    attempt('head_block', chain.head_block)

    def implementation():
        raw = chain.rpc('eth_getStorageAt', [factory, EIP1967_IMPL_SLOT, 'latest'])
        value = int(raw, 16)
        return ('0x' + format(value, '040x')) if value else ''

    attempt('implementation', implementation)

    def account_implementation():
        return '0x' + chain.eth_call(factory, '0x' + chain.abi.selector('implementation()'))[-20:].hex()

    attempt('account_implementation', account_implementation)
    sponsor = (getattr(settings, 'BSC_SPONSOR_ADDRESS', None) or '').strip()
    if sponsor:
        attempt('sponsor_bnb', lambda: Decimal(int(chain.rpc('eth_getBalance', [sponsor, 'latest']), 16)) / WAD)
    prices = offer.factory_prices(fresh=not use_cache)
    if prices:
        out['prices'] = {plan: Decimal(int(row['price_wei'])) / WAD for plan, row in prices.items()}
        reads += 1
    if not reads:
        out['source'] = 'unavailable'
    return out


def chain_snapshot(w, refresh=False):
    try:
        return _admin_cached('smart_account_chain', _chain_snapshot, w, refresh=refresh)
    except Exception:  # noqa: BLE001
        logger.warning('smart account chain snapshot failed', exc_info=True)
        return {'source': 'unavailable', 'head_block': None, 'implementation': None,
                'account_implementation': None, 'sponsor_bnb': None, 'prices': None}


def _p_plus(w, refresh):
    """cUSD+ share price from the Invest page's cached vault read."""
    try:
        from cusd_plus.metrics import get_cusd_plus_platform_metrics
        metrics = _admin_cached('cusd_plus', get_cusd_plus_platform_metrics, w, refresh=refresh)
        return getattr(metrics, 'p_plus', None)
    except Exception:  # noqa: BLE001
        logger.warning('smart account dashboard: cUSD+ price unreadable', exc_info=True)
        return None


# ── flags and contracts ──────────────────────────────────────────────────

def _feature(w):
    """Switches, read with getattr so a missing setting reads as off."""
    configured = [r.strip() for r in str(getattr(settings, 'SMART_ACCOUNT_PAYOUT_RAILS', '') or '').split(',')
                  if r.strip()]
    verified = bool(getattr(settings, 'SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED', False))
    try:
        from smart_account.offer import payout_rails
        offered = payout_rails()
    except Exception:  # noqa: BLE001 — unknown, never "off"
        logger.warning('smart account payout rails unreadable', exc_info=True)
        offered = None
    return {
        'enabled': bool(getattr(settings, 'SMART_ACCOUNT_ENABLED', False)),
        'factory': str(getattr(settings, 'SMART_ACCOUNT_FACTORY_ADDRESS', '') or ''),
        'fee_collector': str(getattr(settings, 'SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS', '') or ''),
        'beneficiary_enabled': bool(getattr(settings, 'SMART_ACCOUNT_BENEFICIARY_ENABLED', False)),
        'require_cancel_claim': bool(getattr(settings, 'SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM', False)),
        'probe_enabled': bool(getattr(settings, 'SMART_ACCOUNT_PROBE_ENABLED', False)),
        'card_rules_enabled': bool(getattr(settings, 'SMART_ACCOUNT_CARD_RULES_ENABLED', False)),
        'referral_enabled': bool(getattr(settings, 'SMART_ACCOUNT_RELAYER_REFERRAL_ENABLED', False)),
        'canary': _id_count('SMART_ACCOUNT_ALLOWED_USER_IDS'),
        'beneficiary_canary': _id_count('SMART_ACCOUNT_BENEFICIARY_ALLOWED_USER_IDS'),
        'min_app_version': str(getattr(settings, 'SMART_ACCOUNT_MIN_APP_VERSION', '') or ''),
        'ia_plus_min_app_version': str(getattr(settings, 'SMART_ACCOUNT_IA_PLUS_MIN_APP_VERSION', '') or ''),
        'rails_configured': configured,
        'adapter_verified': verified,
        'verified_adapters': [a.strip() for a in str(
            getattr(settings, 'SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS', '') or '').split(',') if a.strip()],
        'rails_offered': offered,
    }


def _flags(feature):
    def on(value):
        return 'on' if value else 'off'

    canary = feature['canary']
    rails = feature['rails_offered']
    return [
        {'label': 'Cuenta inteligente', 'setting': 'SMART_ACCOUNT_ENABLED', 'state': on(feature['enabled']),
         'detail': ''},
        {'label': 'Canary list', 'setting': 'SMART_ACCOUNT_ALLOWED_USER_IDS',
         'state': 'on' if canary == 'everyone' or canary else 'off',
         'detail': 'everyone' if canary == 'everyone' else f'{canary} user{"" if canary == 1 else "s"}'},
        {'label': 'Beneficiaries', 'setting': 'SMART_ACCOUNT_BENEFICIARY_ENABLED',
         'state': on(feature['beneficiary_enabled']),
         'detail': f'canary {feature["beneficiary_canary"]}'
                   + ('' if feature['require_cancel_claim'] else ' · cancelClaim not required')},
        {'label': 'Payout rails', 'setting': 'SMART_ACCOUNT_PAYOUT_RAILS',
         'state': 'unknown' if rails is None else on(rails),
         'detail': ('unreadable' if rails is None else ', '.join(RAIL_LABELS.get(r, r) for r in rails) or 'none offered')
                   + (f' · listed: {", ".join(feature["rails_configured"])}' if feature['rails_configured'] else '')},
        {'label': 'Payout adapter verified', 'setting': 'SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED',
         'state': on(feature['adapter_verified']),
         'detail': ', '.join(feature['verified_adapters'])},
        {'label': 'Card rules', 'setting': 'SMART_ACCOUNT_CARD_RULES_ENABLED',
         'state': on(feature['card_rules_enabled']), 'detail': ''},
        {'label': 'Fake-door probe', 'setting': 'SMART_ACCOUNT_PROBE_ENABLED',
         'state': on(feature['probe_enabled']), 'detail': ''},
        {'label': 'Relayer referral', 'setting': 'SMART_ACCOUNT_RELAYER_REFERRAL_ENABLED',
         'state': on(feature['referral_enabled']), 'detail': ''},
        {'label': 'Minimum app version', 'setting': 'SMART_ACCOUNT_MIN_APP_VERSION',
         'state': 'on' if feature['min_app_version'] else 'off',
         'detail': feature['min_app_version'] or 'not set: no build is supported'},
        {'label': 'IA+ minimum app version', 'setting': 'SMART_ACCOUNT_IA_PLUS_MIN_APP_VERSION',
         'state': 'on' if feature['ia_plus_min_app_version'] else 'off',
         'detail': feature['ia_plus_min_app_version'] or 'not set'},
    ]


def _contracts(feature, snap):
    sponsor = (getattr(settings, 'BSC_SPONSOR_ADDRESS', None) or '').strip()
    readable = snap.get('source') == 'chain'
    rows = [
        ('Factory (proxy)', feature['factory'], 'SMART_ACCOUNT_FACTORY_ADDRESS'),
        ('Factory implementation', snap.get('implementation') if readable else None, 'EIP-1967 slot of the proxy'),
        ('Account implementation', snap.get('account_implementation') if readable else None,
         'factory.implementation()'),
        ('Fee collector', feature['fee_collector'], 'SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS'),
        ('Relayer / sponsor (KMS)', sponsor, 'BSC_SPONSOR_ADDRESS'),
    ]
    return [{'label': label, 'address': address or '', 'url': _explorer(address), 'source': source,
             'unknown': address is None and bool(feature['factory'])}
            for label, address, source in rows]


# ── the section ──────────────────────────────────────────────────────────

def _build(w, snap=None):
    from smart_account.models import (
        SmartAccount, SmartAccountBeneficiary, SmartAccountCardPause, SmartAccountCardPull, SmartAccountCardSpender,
        SmartAccountCharge, SmartAccountClaim, SmartAccountEvent, SmartAccountForcedSale, SmartAccountForcedSaleLeg,
        SmartAccountPagoMovilDestination, SmartAccountPayout, SmartAccountRelayTx, SmartAccountRule,
        SmartAccountRuleRun, SmartAccountScanCursor, SmartAccountStandingAuthorization, SmartAccountTargetAllocation,
        SmartAccountWatch)

    snap = snap or {'source': 'unconfigured'}
    now, since, since_30 = w.now, w.last_7_start, w.rolling_30_start
    feature = _feature(w)

    # ── Accounts ─────────────────────────────────────────────────────────
    accounts = SmartAccount.objects.order_by()
    by_status = dict(accounts.values_list('status').annotate(n=Count('id')))
    subscribers = accounts.filter(status__in=('active', 'cancel_pending'))
    by_plan = dict(subscribers.values_list('plan').annotate(n=Count('id')))
    by_billing = dict(subscribers.values_list('billing_status').annotate(n=Count('id')))
    status_labels = dict(SmartAccount.STATUS_CHOICES)
    billing_labels = dict(SmartAccount.BILLING_CHOICES)
    events = SmartAccountEvent.objects.order_by()
    account_rows = [
        {'key': s, 'label': status_labels[s], 'n': by_status.get(s, 0),
         'url': _link('smartaccount', status__exact=s)}
        for s in ('active', 'cancel_pending', 'expired', 'inherited', 'none')
    ]
    plan_rows = [
        {'key': key, 'label': label, 'n': by_plan.get(key, 0), 'url': _link('smartaccount', plan__exact=key)}
        for key, label in PLANS
    ]
    billing_rows = [
        {'key': key, 'label': billing_labels[key], 'n': by_billing.get(key, 0),
         'url': _link('smartaccount', billing_status__exact=key), 'alarm': key in ('notice', 'sale_allowed')}
        for key, _label in SmartAccount.BILLING_CHOICES
    ]
    new_subs = events.filter(name='Subscribed', block_time__gte=since)
    cancels = events.filter(name='SubscriptionCancelled', block_time__gte=since)
    undone = events.filter(name='CancelUndone', block_time__gte=since)
    epochs = dict(accounts.values_list('subscription_epoch').annotate(n=Count('id')))
    epoch_rows = [
        {'label': 'Never subscribed (epoch 0)', 'n': epochs.get(0, 0)},
        {'label': 'First subscription (epoch 1)', 'n': epochs.get(1, 0)},
        {'label': 'Subscribed again (epoch 2+)', 'n': sum(n for e, n in epochs.items() if e >= 2)},
    ]
    later_generation = accounts.exclude(status='inherited').filter(
        owner_user_id__in=accounts.filter(status='inherited').values('inherited_from_user_id')).count()

    # ── Recurring revenue at current prices ──────────────────────────────
    prices = snap.get('prices')
    price_source = 'factory'
    if not prices:
        from smart_account.offer import settings_price
        prices = {plan: Decimal(settings_price(plan)) for plan, _l in PLANS}
        price_source = 'settings'
    renewing = dict(accounts.filter(status='active').values_list('plan').annotate(n=Count('id')))
    mrr = (prices['monthly'] * renewing.get('monthly', 0)
           + prices['annual'] * renewing.get('annual', 0) / Decimal(12)).quantize(Decimal('0.01'))
    recurring = {
        'mrr': mrr, 'arr': (mrr * 12).quantize(Decimal('0.01')),
        'renewing': sum(renewing.values()), 'renewing_monthly': renewing.get('monthly', 0),
        'renewing_annual': renewing.get('annual', 0), 'prices': prices, 'price_source': price_source,
    }

    # ── Billing ──────────────────────────────────────────────────────────
    charges = SmartAccountCharge.objects.order_by()

    def revenue(start):
        rows = charges.filter(charged_at__gte=start) if start else charges
        agg = rows.aggregate(n=Count('id'), usd=Sum('fee_usd'))
        split = {r['paid_with']: r for r in rows.values('paid_with').annotate(n=Count('id'), usd=Sum('fee_usd'))}
        return {'n': agg['n'], 'usd': agg['usd'] or Decimal('0'),
                'url': _link('smartaccountcharge', charged_at__gte=start) if start else _link('smartaccountcharge'),
                'split': {key: {'n': split.get(key, {}).get('n', 0),
                                'usd': split.get(key, {}).get('usd') or Decimal('0')} for key, _l in PAID_WITH}}

    revenue_7d, revenue_30d, revenue_all = revenue(since), revenue(since_30), revenue(None)
    paid_with = [{'label': label, 'url': _link('smartaccountcharge', paid_with__exact=key),
                  'window': revenue_7d['split'][key], 'rolling_30': revenue_30d['split'][key],
                  'all': revenue_all['split'][key]}
                 for key, label in PAID_WITH]
    plan_charges = []
    for key, label in PLANS:
        rows = charges.filter(plan=key)
        plan_charges.append({
            'label': label, 'url': _link('smartaccountcharge', plan__exact=key),
            'window': _money(rows.filter(charged_at__gte=since).aggregate(n=Count('id'), usd=Sum('fee_usd'))),
            'rolling_30': _money(rows.filter(charged_at__gte=since_30).aggregate(n=Count('id'), usd=Sum('fee_usd'))),
            'all': _money(rows.aggregate(n=Count('id'), usd=Sum('fee_usd'))),
        })
    sales_all = SmartAccountForcedSale.objects.order_by()
    sales = sales_all.filter(updated_at__gte=since)
    sale_counts = dict(sales.values_list('status').annotate(n=Count('id')))
    sale_counts_all = dict(sales_all.values_list('status').annotate(n=Count('id')))
    forced = {
        'n': sum(sale_counts.values()),
        'succeeded': sale_counts.get('succeeded', 0),
        'failed': sale_counts.get('failed', 0),
        'in_flight': sale_counts.get('pending', 0) + sale_counts.get('sent', 0),
        'dollars': _wei_usd(sales.filter(status='succeeded').values_list('dollars_out', flat=True)),
        'all_n': sum(sale_counts_all.values()),
        'all_succeeded': sale_counts_all.get('succeeded', 0),
        'all_failed': sale_counts_all.get('failed', 0),
        'all_in_flight': sale_counts_all.get('pending', 0) + sale_counts_all.get('sent', 0),
        'all_dollars': _wei_usd(sales_all.filter(status='succeeded').values_list('dollars_out', flat=True)),
        'legs': SmartAccountForcedSaleLeg.objects.filter(forced_sale__updated_at__gte=since).count(),
        'all_legs': SmartAccountForcedSaleLeg.objects.count(),
        'attempts': sales_all.aggregate(n=Sum('attempts'))['n'] or 0,
        'fail_reasons': _reasons(sales_all.filter(status='failed'), field='last_error'),
        'url': _link('smartaccountforcedsale'),
        'failed_url': _link('smartaccountforcedsale', status__exact='failed'),
    }
    notices = {
        'due_reminders': accounts.filter(last_due_notice_at__gte=since).count(),
        'sale_eve': accounts.filter(sale_eve_notified_for__isnull=False, billing_status__in=(
            'notice', 'sale_allowed')).count(),
        'returned': accounts.filter(returned_notified_at__gte=since).count(),
        'price_change': accounts.filter(renewal_price_notified_for__isnull=False,
                                        status__in=('active', 'cancel_pending')).count(),
        'in_notice': by_billing.get('notice', 0),
        'sale_allowed': by_billing.get('sale_allowed', 0),
        'payment_due': by_billing.get('payment_due', 0),
    }

    # ── Rules and payouts ────────────────────────────────────────────────
    rules = SmartAccountRule.objects.order_by().filter(active=True)
    rule_grid = {(r['kind'], r['frequency']): r['n'] for r in rules.values('kind', 'frequency').annotate(n=Count('id'))}
    frequencies = SmartAccountRule.FREQUENCY_CHOICES
    rule_rows = [
        {'key': kind, 'label': label, 'url': _link('smartaccountrule', kind__exact=kind, active__exact=1),
         'cells': [rule_grid.get((kind, f), 0) for f, _l in frequencies],
         'total': sum(rule_grid.get((kind, f), 0) for f, _l in frequencies)}
        for kind, label in SmartAccountRule.KIND_CHOICES
    ]
    rule_states = dict(SmartAccountRule.objects.order_by().values_list('state').annotate(n=Count('id')))
    runs = SmartAccountRuleRun.objects.order_by().filter(scheduled_for__gte=since, scheduled_for__lte=now)
    run_counts = dict(runs.values_list('status').annotate(n=Count('id')))
    run_rows = [
        {'key': key, 'label': label, 'n': run_counts.get(key, 0),
         'url': _link('smartaccountrulerun', status__exact=key, scheduled_for__gte=since)}
        for key, label in SmartAccountRuleRun.STATUS_CHOICES
    ]
    runs_by_kind = defaultdict(Counter)
    for kind, status, n in runs.values_list('rule__kind', 'status').annotate(n=Count('id')):
        runs_by_kind[kind][status] += n
    run_kind_rows = [
        {'label': label, 'cells': [runs_by_kind[kind][key] for key, _l in SmartAccountRuleRun.STATUS_CHOICES]}
        for kind, label in SmartAccountRule.KIND_CHOICES if kind != 'card'
    ]
    payouts = SmartAccountPayout.objects.order_by()
    payout_grid = defaultdict(Counter)
    for rail, status, n in payouts.values_list('rail', 'status').annotate(n=Count('id')):
        payout_grid[rail][status] += n
    known = [key for key, _l in PAYOUT_STATUSES]
    extra = sorted({s for counts in payout_grid.values() for s in counts} - set(known))
    payout_columns = [(key, label) for key, label in PAYOUT_STATUSES] + [(s, s) for s in extra]
    rails = sorted(set(payout_grid) | ({'ve_pagomovil'} if 've_pagomovil' in (feature['rails_configured'] or [])
                                       else set()))
    payout_rows = [
        {'label': RAIL_LABELS.get(rail, rail), 'url': _link('smartaccountpayout', rail__exact=rail),
         'cells': [{'n': payout_grid[rail][key], 'alarm': key in PAYOUT_ALARM and payout_grid[rail][key]}
                   for key, _l in payout_columns],
         'total': sum(payout_grid[rail].values())}
        for rail in rails
    ]
    payout_window = payouts.filter(created_at__gte=since).aggregate(
        n=Count('id'), paid=Count('id', filter=Q(status='paid')), fiat=Sum('fiat_amount', filter=Q(status='paid')))
    authorizations = dict(SmartAccountStandingAuthorization.objects.order_by().filter(
        revoked_at__isnull=True).values_list('kind').annotate(n=Count('id')))
    card_window = SmartAccountCardPull.objects.order_by().filter(pulled_at__gte=since).aggregate(
        n=Count('id'), usd=Sum('usd_spent'))
    card_30 = SmartAccountCardPull.objects.order_by().filter(pulled_at__gte=since_30).aggregate(
        n=Count('id'), usd=Sum('usd_spent'))
    cards = {
        'pulls': card_window['n'],
        'pulls_usd': card_window['usd'] or Decimal('0'),
        'pulls_30': card_30['n'],
        'pulls_30_usd': card_30['usd'] or Decimal('0'),
        'pulls_url': _link('smartaccountcardpull', pulled_at__gte=since),
        'unmatched': SmartAccountCardPull.objects.filter(rule__isnull=True).count(),
        'spenders_allowed': SmartAccountCardSpender.objects.filter(allowed=True).count(),
        'spenders_removed': SmartAccountCardSpender.objects.filter(allowed=False).count(),
        'spenders_url': _link('smartaccountcardspender'),
        'paused': SmartAccountCardPause.is_paused(),
        'card_rules': sum(n for (kind, _f), n in rule_grid.items() if kind == 'card'),
    }

    # ── Inheritance ──────────────────────────────────────────────────────
    beneficiaries = SmartAccountBeneficiary.objects.order_by()
    designations = dict(beneficiaries.values_list('state').annotate(n=Count('id')))
    state_labels = dict(SmartAccountBeneficiary.STATE_CHOICES)
    designation_rows = [
        {'key': key, 'label': state_labels[key], 'n': designations.get(key, 0),
         'url': _link('smartaccountbeneficiary', state__exact=key)}
        for key in ('pending_acceptance', 'active', 'declined', 'lapsed', 'stale_address')
    ]
    claims = SmartAccountClaim.objects.order_by()
    pending = claims.filter(state='pending')
    claim_agg = pending.aggregate(
        waiting=Count('id', filter=Q(executable_at__gt=now)),
        executable=Count('id', filter=Q(executable_at__lte=now)),
        soonest=Min('executable_at', filter=Q(executable_at__gt=now)))
    claim_list = []
    for claim in pending.select_related(
            'beneficiary_row__smart_account__owner_user', 'beneficiary_row__beneficiary_user').order_by(
            'executable_at')[:CLAIM_LIST_LIMIT]:
        row = claim.beneficiary_row
        executable = claim.executable_at <= now
        claim_list.append({
            'account': row.smart_account.contract_address,
            'owner': row.smart_account.owner_user,
            'beneficiary': row.beneficiary_user,
            'initiated_at': claim.initiated_at,
            'executable_at': claim.executable_at,
            'executable': executable,
            'days_left': None if executable else (claim.executable_at - now).days,
            'owner_notices': claim.owner_notices_sent,
            'url': _change_url('smartaccountclaim', claim.pk),
        })
    claim_info = {
        **claim_agg,
        'pending': claim_agg['waiting'] + claim_agg['executable'],
        'list': claim_list,
        'list_more': max(0, claim_agg['waiting'] + claim_agg['executable'] - len(claim_list)),
        'pending_url': _link('smartaccountclaim', state__exact='pending'),
        'cancelled': claims.filter(state='cancelled', cancelled_at__gte=since).count(),
        'executed': claims.filter(state='executed', executed_at__gte=since).count(),
        'cancelled_all': claims.filter(state='cancelled').count(),
        'executed_all': claims.filter(state='executed').count(),
        'cancelled_url': _link('smartaccountclaim', state__exact='cancelled'),
        'executed_url': _link('smartaccountclaim', state__exact='executed'),
    }

    # ── Relayer and sync ─────────────────────────────────────────────────
    relay = SmartAccountRelayTx.objects.order_by()
    stuck_cutoff = now - timedelta(minutes=RELAY_STUCK_MINUTES)
    stuck_relay = relay.filter(status__in=NOT_FINAL_RELAY, created_at__lt=stuck_cutoff)
    bad_relay = relay.filter(status__in=BAD_RELAY, updated_at__gte=since)
    relay_all = dict(relay.values_list('status').annotate(n=Count('id')))
    relay_window = dict(relay.filter(created_at__gte=since).values_list('status').annotate(n=Count('id')))
    relay_rows = [
        {'key': key, 'label': label, 'window': relay_window.get(key, 0), 'all': relay_all.get(key, 0),
         'alarm': key in BAD_RELAY, 'url': _link('smartaccountrelaytx', status__exact=key)}
        for key, label in SmartAccountRelayTx.STATUS_CHOICES
    ]
    oldest_open = relay.filter(status__in=NOT_FINAL_RELAY).aggregate(at=Min('created_at'))['at']
    relay_kinds = list(relay.filter(created_at__gte=since).values('kind').annotate(n=Count('id')).order_by('-n')[:6])
    unapplied = events.filter(applied_at__isnull=True)
    unapplied_agg = unapplied.aggregate(n=Count('id'), oldest=Min('created_at'))
    event_cutoff = now - timedelta(minutes=EVENT_STUCK_MINUTES)
    try:
        from smart_account.reconcile import backfill_pending
        backfilling = len(backfill_pending())
    except Exception:  # noqa: BLE001 — unknown, never zero
        logger.warning('smart account backfill state unreadable', exc_info=True)
        backfilling = None
    cursor = SmartAccountScanCursor.objects.filter(key='events').first()
    oldest = unapplied_agg['oldest']
    head = snap.get('head_block')
    cursor_idle = bool(feature['enabled'] and feature['factory'] and cursor and cursor.updated_at < event_cutoff)
    ops = {
        'stuck_relay': stuck_relay.count(),
        'stuck_relay_url': _link('smartaccountrelaytx', status__in=','.join(NOT_FINAL_RELAY),
                                 created_at__lt=stuck_cutoff),
        'bad_relay': bad_relay.count(),
        'bad_relay_by_status': list(bad_relay.values('status').annotate(n=Count('id')).order_by('-n')),
        'bad_relay_url': _link('smartaccountrelaytx', status__in=','.join(BAD_RELAY), updated_at__gte=since),
        'relay_rows': relay_rows,
        'relay_kinds': relay_kinds,
        'relay_window_total': sum(relay_window.values()),
        'oldest_open_relay': oldest_open,
        'oldest_open_relay_minutes': int((now - oldest_open).total_seconds() // 60) if oldest_open else None,
        'unapplied': unapplied_agg['n'],
        'unapplied_old': unapplied.filter(created_at__lt=event_cutoff).count(),
        # Accounts whose events wait behind a failed or unreadable one: the
        # reconciler blocks per account in memory, so the mirror's trace is
        # an address with old unapplied events.
        'blocked_accounts': unapplied.filter(created_at__lt=event_cutoff).values('address').distinct().count(),
        'oldest_unapplied': oldest,
        'oldest_unapplied_minutes': int((now - oldest).total_seconds() // 60) if oldest else None,
        'unapplied_url': _link('smartaccountevent', applied_at__isempty=1),
        'events_window': events.filter(block_time__gte=since).count(),
        'events_all': events.count(),
        'backfilling': backfilling,
        'cursor_block': cursor.block_number if cursor else None,
        'cursor_at': cursor.updated_at if cursor else None,
        'cursor_idle': cursor_idle,
        'head_block': head,
        'lag_blocks': (head - cursor.block_number) if (head is not None and cursor) else None,
        'sponsor_bnb': snap.get('sponsor_bnb'),
        'chain_source': snap.get('source'),
        'failed_sales': SmartAccountForcedSale.objects.filter(status='failed').count(),
        'failed_sales_url': forced['failed_url'],
        'relay_stuck_minutes': RELAY_STUCK_MINUTES,
        'event_stuck_minutes': EVENT_STUCK_MINUTES,
    }
    ops['needs_action'] = bool(ops['stuck_relay'] or ops['unapplied_old'] or ops['failed_sales'])

    # ── Money in the accounts (mirrored balances, never a chain read) ────
    from blockchain.models import Balance, CryptoHoldings, StockHoldings
    account_ids = accounts.exclude(account_id=None).values('account_id')
    balances = dict(Balance.objects.order_by().filter(account_id__in=account_ids).values_list('token').annotate(
        s=Sum('amount')))
    dollars = sum((balances.get(t) or Decimal('0')) for t in DOLLAR_TOKENS)
    shares = balances.get('CUSD_PLUS') or Decimal('0')
    # cUSD+ shares are priced by smart_account() from the cached vault read.
    shares_usd = Decimal('0') if not shares else None
    money = {
        'dollars': dollars,
        'cusd': balances.get('CUSD_BSC') or Decimal('0'),
        'usdt': balances.get('USDT_BSC') or Decimal('0'),
        'shares': shares,
        'shares_usd': shares_usd,
        'total': dollars + shares_usd if shares_usd is not None else None,
        'stock_accounts': StockHoldings.objects.filter(account_id__in=account_ids).exclude(held={}).count(),
        'crypto_accounts': CryptoHoldings.objects.filter(account_id__in=account_ids).exclude(held={}).count(),
        'synced': Balance.objects.filter(account_id__in=account_ids).aggregate(at=Min('last_synced'))['at'],
    }

    # ── IA+ (assistant ops) ──────────────────────────────────────────────
    ia = _ia_plus(w)
    watches = SmartAccountWatch.objects.order_by()
    ia.update({
        'watches_active': watches.filter(active=True).count(),
        'watches_with_action': watches.filter(active=True).exclude(action={}).count(),
        'watches_triggered': watches.filter(last_triggered_at__gte=since).count(),
        'watches_triggered_30': watches.filter(last_triggered_at__gte=since_30).count(),
        'watches_by_kind': [{'label': dict(SmartAccountWatch.KIND_CHOICES).get(k, k), 'n': n}
                            for k, n in watches.filter(active=True).values_list('kind').annotate(
                                n=Count('id')).order_by('-n')],
        'watches_url': _link('smartaccountwatch', active__exact=1),
        'allocations': SmartAccountTargetAllocation.objects.count(),
        'allocations_url': _link('smartaccounttargetallocation'),
    })

    # ── Funnel and demand ────────────────────────────────────────────────
    from config import admin_dashboard_growth as growth
    preview = growth.preview_user_ids()
    funnel = growth.smart_account_funnel(w, preview)
    top = max([r['people'] for r in funnel] or [0])
    for row in funnel:
        row['pct'] = round(100 * row['people'] / top) if top else 0
    door = next(iter(growth.paid_offer_doors(w, preview, product='smart_account')), None) or {}
    doors = {
        'stages': [{'label': label, 'n': n} for label, n in zip(
            growth.PAID_OFFER_STAGE_LABELS, door.get('stages') or [0] * len(growth.PAID_OFFER_STAGE_LABELS))],
        'waitlist': door.get('waitlist', 0), 'would_pay': door.get('would_pay', 0),
        'waitlist_funded': door.get('waitlist_funded', 0),
    }

    return {
        'window_label': '7 days',
        'feature': feature,
        'flags': _flags(feature),
        'contracts': _contracts(feature, snap),
        'chain_source': snap.get('source'),
        'accounts': {
            'rows': account_rows,
            'own': sum(by_status.get(s, 0) for s in ('active', 'cancel_pending', 'expired')),
            'total': sum(by_status.values()),
            'subscribers': sum(by_plan.values()),
            'cancel_pending': by_status.get('cancel_pending', 0),
            'plans': plan_rows,
            'billing': billing_rows,
            'epochs': epoch_rows,
            'later_generation': later_generation,
            'new_subscriptions': new_subs.count(),
            'new_subscribers': new_subs.values('address').distinct().count(),
            'cancellations': cancels.count(),
            'cancels_undone': undone.count(),
            'events_url': _link('smartaccountevent'),
            'all_url': _link('smartaccount'),
        },
        'recurring': recurring,
        'money': money,
        'revenue': {'window': revenue_7d, 'rolling_30': revenue_30d, 'all': revenue_all, 'paid_with': paid_with,
                    'plans': plan_charges, 'forced': forced, 'notices': notices},
        'automation': {
            'frequencies': [label for _key, label in frequencies],
            'rules': rule_rows,
            'rules_total': sum(r['total'] for r in rule_rows),
            'drafts': rule_states.get('draft', 0),
            'cancelled': rule_states.get('cancelled', 0),
            'runs': run_rows,
            'runs_total': sum(r['n'] for r in run_rows),
            'run_statuses': [label for _key, label in SmartAccountRuleRun.STATUS_CHOICES],
            'run_kinds': run_kind_rows,
            'skip_reasons': _reasons(runs.filter(status='skipped')),
            'fail_reasons': _reasons(runs.filter(status='failed')),
            'cards': cards,
            'payout_columns': [label for _key, label in payout_columns],
            'payouts': payout_rows,
            'payouts_open': payouts.filter(status__in=PAYOUT_OPEN).count(),
            'payouts_review': payouts.filter(status='review').count(),
            'payouts_review_url': _link('smartaccountpayout', status__exact='review'),
            'payouts_window': {'n': payout_window['n'], 'paid': payout_window['paid']},
            'authorizations': [{'label': label, 'n': authorizations.get(key, 0)}
                               for key, label in SmartAccountStandingAuthorization.KIND_CHOICES],
            'pagomovil_destinations': SmartAccountPagoMovilDestination.objects.count(),
        },
        'beneficiaries': {
            'rows': designation_rows,
            'claims': claim_info,
            'inherited': by_status.get('inherited', 0),
            'inherited_window': accounts.filter(inherited_at__gte=since).count(),
        },
        'ops': ops,
        'ia': ia,
        'funnel': funnel,
        'doors': doors,
    }


def _ia_plus(w):
    """Confío IA+ on the Cuenta inteligente: rule proposals in replies and
    alert notes, how many the owner went on to sign, and the monthly
    review notes. Proposals live in the support thread's metadata; a signed
    one is a consumed prepared action that names its proposal."""
    from inbox.models import SupportMessage
    from smart_account.models import SmartAccountPreparedAction

    since, since_30 = w.last_7_start, w.rolling_30_start
    proposals = SupportMessage.objects.order_by().filter(metadata__has_key='rule_proposal')
    from_alerts = Q(metadata__notice__startswith='smart_account_watch:')
    signed = SmartAccountPreparedAction.objects.order_by().filter(payload__has_key='proposal', consumed=True)
    notes = SupportMessage.objects.order_by().filter(metadata__notice__startswith='smart_account_monthly_review:')

    def proposal_counts(start):
        rows = proposals.filter(created_at__gte=start)
        return {'made': rows.count(), 'from_alerts': rows.filter(from_alerts).count(),
                'accepted': signed.filter(created_at__gte=start).values('payload__proposal__message_id').distinct().count(),
                'people': rows.values('conversation__user_id').distinct().count()}

    return {
        'window': proposal_counts(since),
        'rolling_30': proposal_counts(since_30),
        'notes_30': notes.filter(created_at__gte=since_30).count(),
        'notes_all': notes.count(),
        'last_note': notes.order_by('-created_at').values_list('created_at', flat=True).first(),
    }


def _attention(data):
    """Only what is wrong right now, each with the list that fixes it."""
    ops, b, au, f = data['ops'], data['beneficiaries'], data['automation'], data['feature']
    notices = data['revenue']['notices']
    items = []

    def add(level, title, detail='', url=None, count=None):
        items.append({'level': level, 'title': title, 'detail': detail, 'url': url, 'count': count})

    if ops['stuck_relay']:
        add('critical', 'Relay transactions not final',
            f'Signed or sent over {ops["relay_stuck_minutes"]} min ago and still not mined.',
            ops['stuck_relay_url'], ops['stuck_relay'])
    if ops['unapplied_old']:
        add('critical', 'Chain events not applied',
            f'Unapplied for over {ops["event_stuck_minutes"]} min; {ops["blocked_accounts"]} account(s) held back.',
            ops['unapplied_url'], ops['unapplied_old'])
    if ops['failed_sales']:
        add('critical', 'Forced sales failed', 'They retry on their own; check the last error.',
            ops['failed_sales_url'], ops['failed_sales'])
    if ops['bad_relay']:
        add('warning', 'Relay transactions reverted, reorged or dropped', 'In the last 7 days.',
            ops['bad_relay_url'], ops['bad_relay'])
    if b['claims']['executable']:
        add('warning', 'Inheritance claims executable now',
            'The challenge window ended without the owner cancelling.', b['claims']['pending_url'],
            b['claims']['executable'])
    if notices['sale_allowed']:
        add('warning', 'Accounts where a forced sale is allowed', 'Notice ran out; the fee will be sold for.',
            _link('smartaccount', billing_status__exact='sale_allowed'), notices['sale_allowed'])
    if au['payouts_review']:
        add('warning', 'Payouts in review', 'Sent on chain, the provider order needs a look.',
            au['payouts_review_url'], au['payouts_review'])
    if ops['cursor_idle']:
        add('warning', 'Event scanner idle', f'Cursor not written for over {ops["event_stuck_minutes"]} min.',
            _link('smartaccountscancursor'))
    if f['enabled'] and f['factory'] and data['chain_source'] == 'unavailable':
        add('warning', 'Chain read unavailable', 'Head block, implementation and sponsor balance are unknown.')
    if f['enabled'] and not f['factory']:
        add('critical', 'Enabled without a factory', 'SMART_ACCOUNT_ENABLED is on but no factory address is set.')
    return items


def _tools():
    groups = (
        ('Accounts', (('Accounts', 'smartaccount'), ('Events', 'smartaccountevent'),
                      ('Scan cursors', 'smartaccountscancursor'))),
        ('Billing', (('Charges', 'smartaccountcharge'), ('Forced sales', 'smartaccountforcedsale'))),
        ('Rules', (('Rules', 'smartaccountrule'), ('Rule runs', 'smartaccountrulerun'),
                   ('Payouts', 'smartaccountpayout'), ('Standing authorizations', 'smartaccountstandingauthorization'),
                   ('Pago Móvil destinations', 'smartaccountpagomovildestination'),
                   ('Target allocations', 'smartaccounttargetallocation'))),
        ('Card', (('Card spenders', 'smartaccountcardspender'), ('Card pulls', 'smartaccountcardpull'),
                  ('Card pause', 'smartaccountcardpause'))),
        ('Inheritance', (('Beneficiaries', 'smartaccountbeneficiary'), ('Claims', 'smartaccountclaim'))),
        ('Relayer', (('Relay transactions', 'smartaccountrelaytx'), ('Prepared actions', 'smartaccountpreparedaction'))),
        ('IA+', (('Alerts (watches)', 'smartaccountwatch'),)),
    )
    out = []
    for title, links in groups:
        items = [{'label': label, 'url': url} for label, model in links if (url := _link(model))]
        if items:
            out.append({'title': title, 'links': items})
    return out


def smart_account(w, refresh=False):
    try:
        snap = chain_snapshot(w, refresh=refresh)
        data = _build(w, snap)
        if data['money']['shares'] and data['money']['shares_usd'] is None:
            p_plus = _p_plus(w, refresh)
            if p_plus is not None:
                shares_usd = data['money']['shares'] * p_plus
                data['money'].update(shares_usd=shares_usd, total=data['money']['dollars'] + shares_usd)
        data['attention'] = _attention(data)
        data['tools'] = _tools()
        return {'smart_account': data}
    except Exception:  # noqa: BLE001 — one section must never take the page down
        logger.exception('smart account dashboard section failed')
        return {'smart_account': None}
