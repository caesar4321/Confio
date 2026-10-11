"""Do new users who ask Confío IA put money in more? (read-only, aggregate counts only)

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/assistant_funding.py

Cohort = real users who joined since the assistant launched (2026-10-04), split
three ways: asked the assistant something (an AssistantTurn), saw the bubble
but never asked (an AssistantProfile only), never opened it (old builds,
mostly). Funded = users.funding.has_funded (a confirmed incoming row), the same
definition the paid-offer probes use. "First 7 days" only counts users who are
at least 7 days old, so fresh signups don't drag it down.

Correlation, not cause: people who ask may already be the motivated ones.
Compare each re-run with the one before, not across cohorts alone.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db.models import Min
from django.utils import timezone

from assistant.models import AssistantProfile, AssistantTurn
from users.analytics import get_real_users_queryset
from users.models_unified import UnifiedTransactionTable

NOW = timezone.now()
LAUNCH = datetime(2026, 10, 4, tzinfo=dt_timezone.utc)

users = {u['id']: u for u in get_real_users_queryset().filter(is_active=True, is_staff=False, date_joined__gte=LAUNCH)
         .values('id', 'phone_country', 'date_joined')}
ids = list(users)

first_in = dict(UnifiedTransactionTable.objects.filter(
    counterparty_user_id__in=ids, status='CONFIRMED', deleted_at__isnull=True,
).exclude(is_invitation=True, invitation_claimed=False)
    .values('counterparty_user_id').annotate(first=Min('created_at')).values_list('counterparty_user_id', 'first'))
first_q = dict(AssistantTurn.objects.filter(user_id__in=ids)
               .values('user_id').annotate(first=Min('created_at')).values_list('user_id', 'first'))
opened = set(AssistantProfile.objects.filter(user_id__in=ids).values_list('user_id', flat=True))


def cohort(uid):
    if uid in first_q:
        return 'asked the assistant'
    if uid in opened:
        return 'saw the bubble, never asked'
    return 'never opened it'


def pct(a, b):
    return f"{100.0 * a / b:5.1f}%" if b else "   n/a"


def table(title, pool):
    print(f"\n=== {title} ===")
    print(f"  {'cohort':<30}{'users':>7}{'funded':>8}{'%':>8}{'7d-old':>8}{'f≤7d':>6}{'%':>8}")
    for name in ('asked the assistant', 'saw the bubble, never asked', 'never opened it'):
        group = [u for u in pool if cohort(u['id']) == name]
        funded = [u for u in group if u['id'] in first_in]
        aged = [u for u in group if u['date_joined'] <= NOW - timedelta(days=7)]
        early = [u for u in aged if u['id'] in first_in and first_in[u['id']] <= u['date_joined'] + timedelta(days=7)]
        print(f"  {name:<30}{len(group):>7}{len(funded):>8}{pct(len(funded), len(group)):>8}"
              f"{len(aged):>8}{len(early):>6}{pct(len(early), len(aged)):>8}")


pool = list(users.values())
print(f"Real users joined since {LAUNCH:%Y-%m-%d}: {len(pool)}   asked: {len(first_q)}   funded: {len(first_in)}")
table('All countries', pool)
for cc in ('BO', 'VE', 'AR', 'PE'):
    table(f'{cc} only', [u for u in pool if (u['phone_country'] or '').upper() == cc])

askers_funded = [uid for uid in first_q if uid in first_in]
after = sum(first_in[uid] > first_q[uid] for uid in askers_funded)
print(f"\nAskers who funded: {len(askers_funded)}   first deposit came after their first question: {after}")
print("funded = confirmed incoming row (users.funding.has_funded); f≤7d = funded within 7 days of signup")
print("Done.")
