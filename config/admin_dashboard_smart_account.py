"""Cuenta inteligente (smart_account/) on the dashboard: who pays, what was
charged, what automation and beneficiaries are doing, and what ops must act
on (relay transactions not final, events not applied, rails off).

Everything here reads the Postgres mirrors written by smart_account/reconcile.py;
there is no chain read, so nothing sits behind _admin_cached. The section
never raises into the page: a failed build renders as "unavailable".
"""
import logging
from collections import Counter
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from config.admin_dashboard_sections import _url

logger = logging.getLogger(__name__)

# Relay transactions are written before broadcast; one still not mined and
# final after this long needs a look (the batch watcher normally settles
# them within a couple of minutes).
RELAY_STUCK_MINUTES = 15
# reconcile._alert_stuck_events alerts the team at the same age.
EVENT_STUCK_MINUTES = 30
WAD = Decimal(10 ** 18)
NOT_FINAL_RELAY = ('signed', 'sent')
BAD_RELAY = ('reverted', 'reorged', 'dropped')
PAID_WITH = (('cusd', 'cUSD'), ('cusd_plus', 'cUSD+'), ('mixed', 'cUSD + cUSD+'), ('sale', 'Paid by forced sale'))


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


def _reasons(queryset, limit=3):
    counts = Counter(((text or '').strip().splitlines() or ['no reason recorded'])[0][:70]
                     for text in queryset.values_list('error', flat=True))
    return counts.most_common(limit)


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
        'canary': _id_count('SMART_ACCOUNT_ALLOWED_USER_IDS'),
        'beneficiary_canary': _id_count('SMART_ACCOUNT_BENEFICIARY_ALLOWED_USER_IDS'),
        'min_app_version': str(getattr(settings, 'SMART_ACCOUNT_MIN_APP_VERSION', '') or ''),
        'rails_configured': configured,
        'adapter_verified': verified,
        'rails_offered': offered,
    }


def _build(w):
    from smart_account.models import (
        SmartAccount, SmartAccountBeneficiary, SmartAccountCharge, SmartAccountClaim, SmartAccountEvent,
        SmartAccountForcedSale, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun, SmartAccountScanCursor)

    now, since = w.now, w.last_7_start

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
        {'label': status_labels[s], 'n': by_status.get(s, 0), 'url': _link('smartaccount', status__exact=s)}
        for s in ('active', 'cancel_pending', 'expired', 'inherited', 'none')
    ]
    plan_rows = [
        {'label': label, 'n': by_plan.get(key, 0), 'url': _link('smartaccount', plan__exact=key)}
        for key, label in (('annual', 'Annual'), ('monthly', 'Monthly'))
    ]
    billing_rows = [
        {'label': billing_labels[key], 'n': by_billing.get(key, 0),
         'url': _link('smartaccount', billing_status__exact=key), 'alarm': key in ('notice', 'sale_allowed')}
        for key, _label in SmartAccount.BILLING_CHOICES
    ]
    new_subs = events.filter(name='Subscribed', block_time__gte=since)
    cancels = events.filter(name='SubscriptionCancelled', block_time__gte=since)
    undone = events.filter(name='CancelUndone', block_time__gte=since)

    # ── Revenue ──────────────────────────────────────────────────────────
    charges = SmartAccountCharge.objects.order_by()

    def revenue(start):
        rows = charges.filter(charged_at__gte=start)
        agg = rows.aggregate(n=Count('id'), usd=Sum('fee_usd'))
        split = {r['paid_with']: r for r in rows.values('paid_with').annotate(n=Count('id'), usd=Sum('fee_usd'))}
        return {'n': agg['n'], 'usd': agg['usd'] or Decimal('0'),
                'url': _link('smartaccountcharge', charged_at__gte=start),
                'split': {key: {'n': split.get(key, {}).get('n', 0),
                                'usd': split.get(key, {}).get('usd') or Decimal('0')} for key, _l in PAID_WITH}}

    revenue_7d, revenue_30d = revenue(since), revenue(w.rolling_30_start)
    paid_with = [{'label': label, 'url': _link('smartaccountcharge', paid_with__exact=key),
                  'window': revenue_7d['split'][key], 'rolling_30': revenue_30d['split'][key]}
                 for key, label in PAID_WITH]
    sales = SmartAccountForcedSale.objects.order_by().filter(updated_at__gte=since)
    sale_counts = dict(sales.values_list('status').annotate(n=Count('id')))
    forced = {
        'n': sum(sale_counts.values()),
        'succeeded': sale_counts.get('succeeded', 0),
        'failed': sale_counts.get('failed', 0),
        'in_flight': sale_counts.get('pending', 0) + sale_counts.get('sent', 0),
        'dollars': _wei_usd(sales.filter(status='succeeded').values_list('dollars_out', flat=True)),
        'url': _link('smartaccountforcedsale'),
        'failed_url': _link('smartaccountforcedsale', status__exact='failed'),
    }

    # ── Automation ───────────────────────────────────────────────────────
    rules = SmartAccountRule.objects.order_by().filter(active=True)
    rule_grid = {(r['kind'], r['frequency']): r['n'] for r in rules.values('kind', 'frequency').annotate(n=Count('id'))}
    frequencies = SmartAccountRule.FREQUENCY_CHOICES
    rule_rows = [
        {'label': label, 'url': _link('smartaccountrule', kind__exact=kind, active__exact=1),
         'cells': [rule_grid.get((kind, f), 0) for f, _l in frequencies],
         'total': sum(rule_grid.get((kind, f), 0) for f, _l in frequencies)}
        for kind, label in SmartAccountRule.KIND_CHOICES
    ]
    runs = SmartAccountRuleRun.objects.order_by().filter(scheduled_for__gte=since, scheduled_for__lte=now)
    run_counts = dict(runs.values_list('status').annotate(n=Count('id')))
    run_rows = [
        {'label': label, 'n': run_counts.get(key, 0),
         'url': _link('smartaccountrulerun', status__exact=key, scheduled_for__gte=since)}
        for key, label in SmartAccountRuleRun.STATUS_CHOICES
    ]
    # Card rules (decision 35): pulled by the issuer, never run by the relayer.
    from smart_account.models import SmartAccountCardPause, SmartAccountCardPull, SmartAccountCardSpender
    card_pulls = SmartAccountCardPull.objects.order_by().filter(pulled_at__gte=since).aggregate(
        n=Count('id'), usd=Sum('usd_spent'))
    cards = {
        'pulls': card_pulls['n'],
        'pulls_usd': card_pulls['usd'] or Decimal('0'),
        'pulls_url': _link('smartaccountcardpull', pulled_at__gte=since),
        'spenders_allowed': SmartAccountCardSpender.objects.filter(allowed=True).count(),
        'spenders_url': _link('smartaccountcardspender'),
        'paused': SmartAccountCardPause.is_paused(),
    }

    # ── Beneficiaries ────────────────────────────────────────────────────
    beneficiaries = SmartAccountBeneficiary.objects.order_by()
    designations = dict(beneficiaries.values_list('state').annotate(n=Count('id')))
    state_labels = dict(SmartAccountBeneficiary.STATE_CHOICES)
    designation_rows = [
        {'label': state_labels[key], 'n': designations.get(key, 0),
         'url': _link('smartaccountbeneficiary', state__exact=key)}
        for key in ('pending_acceptance', 'active', 'declined', 'lapsed', 'stale_address')
    ]
    claims = SmartAccountClaim.objects.order_by()
    pending = claims.filter(state='pending')
    claim_agg = pending.aggregate(
        waiting=Count('id', filter=Q(executable_at__gt=now)),
        executable=Count('id', filter=Q(executable_at__lte=now)),
        soonest=Min('executable_at', filter=Q(executable_at__gt=now)))
    claim_info = {
        **claim_agg,
        'pending_url': _link('smartaccountclaim', state__exact='pending'),
        'cancelled': claims.filter(state='cancelled', cancelled_at__gte=since).count(),
        'executed': claims.filter(state='executed', executed_at__gte=since).count(),
        'cancelled_url': _link('smartaccountclaim', state__exact='cancelled'),
        'executed_url': _link('smartaccountclaim', state__exact='executed'),
    }

    # ── Ops health ───────────────────────────────────────────────────────
    relay = SmartAccountRelayTx.objects.order_by()
    stuck_cutoff = now - timedelta(minutes=RELAY_STUCK_MINUTES)
    stuck_relay = relay.filter(status__in=NOT_FINAL_RELAY, created_at__lt=stuck_cutoff)
    bad_relay = relay.filter(status__in=BAD_RELAY, updated_at__gte=since)
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
    ops = {
        'stuck_relay': stuck_relay.count(),
        'stuck_relay_url': _link('smartaccountrelaytx', status__in=','.join(NOT_FINAL_RELAY),
                                 created_at__lt=stuck_cutoff),
        'bad_relay': bad_relay.count(),
        'bad_relay_by_status': list(bad_relay.values('status').annotate(n=Count('id')).order_by('-n')),
        'bad_relay_url': _link('smartaccountrelaytx', status__in=','.join(BAD_RELAY), updated_at__gte=since),
        'unapplied': unapplied_agg['n'],
        'unapplied_old': unapplied.filter(created_at__lt=event_cutoff).count(),
        # Accounts whose events wait behind a failed or unreadable one: the
        # reconciler blocks per account in memory, so the mirror's trace is
        # an address with old unapplied events.
        'blocked_accounts': unapplied.filter(created_at__lt=event_cutoff).values('address').distinct().count(),
        'oldest_unapplied': oldest,
        'oldest_unapplied_minutes': int((now - oldest).total_seconds() // 60) if oldest else None,
        'unapplied_url': _link('smartaccountevent', applied_at__isempty=1),
        'backfilling': backfilling,
        'cursor_block': cursor.block_number if cursor else None,
        'cursor_at': cursor.updated_at if cursor else None,
        'failed_sales': SmartAccountForcedSale.objects.filter(status='failed').count(),
        'failed_sales_url': forced['failed_url'],
        'relay_stuck_minutes': RELAY_STUCK_MINUTES,
        'event_stuck_minutes': EVENT_STUCK_MINUTES,
    }
    ops['needs_action'] = bool(ops['stuck_relay'] or ops['unapplied_old'] or ops['failed_sales'])

    return {
        'window_label': '7 days',
        'feature': _feature(w),
        'accounts': {
            'rows': account_rows,
            'own': sum(by_status.get(s, 0) for s in ('active', 'cancel_pending', 'expired')),
            'subscribers': sum(by_plan.values()),
            'plans': plan_rows,
            'billing': billing_rows,
            'new_subscriptions': new_subs.count(),
            'new_subscribers': new_subs.values('address').distinct().count(),
            'cancellations': cancels.count(),
            'cancels_undone': undone.count(),
            'events_url': _link('smartaccountevent'),
            'all_url': _link('smartaccount'),
        },
        'revenue': {'window': revenue_7d, 'rolling_30': revenue_30d, 'paid_with': paid_with, 'forced': forced},
        'automation': {
            'frequencies': [label for _key, label in frequencies],
            'rules': rule_rows,
            'rules_total': sum(r['total'] for r in rule_rows),
            'runs': run_rows,
            'skip_reasons': _reasons(runs.filter(status='skipped')),
            'fail_reasons': _reasons(runs.filter(status='failed')),
            'cards': cards,
        },
        'beneficiaries': {'rows': designation_rows, 'claims': claim_info},
        'ops': ops,
    }


def smart_account(w):
    try:
        return {'smart_account': _build(w)}
    except Exception:  # noqa: BLE001 — one section must never take the page down
        logger.exception('smart account dashboard section failed')
        return {'smart_account': None}
