from celery import shared_task


@shared_task(bind=True, max_retries=0, soft_time_limit=20 * 60, time_limit=25 * 60)
def compute_league_task(self):
    """After the nightly returns snapshots: each team's last 31 days, then
    attribution for Copiar jugada. Idempotent, so it simply runs hourly
    through the early UTC morning with the snapshots."""
    from .data import link_copies
    from .league import compute_recent_days

    counts = compute_recent_days()
    counts['copies_linked'] = link_copies()
    return counts


@shared_task(bind=True, max_retries=0)
def award_month_task(self):
    """Campeón del mes for the month that just ended (written once)."""
    from datetime import timedelta

    from .league import award_month, compute_recent_days, utc_today

    compute_recent_days()
    today = utc_today()
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    # The last scheduled retry decides with what is proven by then.
    return [a.id for a in award_month(last_month, force=today.day >= 7)]


@shared_task(bind=True, max_retries=0)
def refresh_goals_task(self):
    from .data import refresh_all_goals

    return refresh_all_goals()
