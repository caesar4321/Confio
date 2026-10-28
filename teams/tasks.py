from celery import shared_task


@shared_task(bind=True, max_retries=0, soft_time_limit=20 * 60, time_limit=25 * 60)
def compute_league_task(self):
    """After the nightly returns snapshots: each team's last 31 days, then
    attribution for copy play. Idempotent, so it simply runs hourly
    through the early UTC morning with the snapshots."""
    from .data import link_copies
    from .league import compute_recent_days

    counts = compute_recent_days()
    counts['copies_linked'] = link_copies()
    return counts


@shared_task(bind=True, max_retries=0, soft_time_limit=8 * 60, time_limit=9 * 60)
def warm_rolling_league_task(self):
    """The 24 h tables, right after the value snapshots."""
    from .league import warm_rolling

    return warm_rolling()


@shared_task(bind=True, max_retries=0)
def award_month_task(self):
    """Monthly champion for the month that just ended (written once)."""
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


@shared_task(bind=True, max_retries=3, default_retry_delay=60, soft_time_limit=10 * 60, time_limit=12 * 60)
def recompute_member_history_task(self, user_id):
    """Someone hid or showed their profile again: every team day they were
    part of, recomputed from who may be shown now (all time reaches far past
    the nightly window). Until it runs, reads already leave out anyone hidden."""
    from users.models import User

    from .league import recompute_member_history

    # all_objects: a deleted account's days must be recomputed without it too.
    user = User.all_objects.filter(id=user_id).first()
    if user is None:
        return 0
    try:
        return recompute_member_history(user)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc)
