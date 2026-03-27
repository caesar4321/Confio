from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .models import ContentPlatformClick, ContentPlatformClickDailyStat


def aggregate_content_platform_clicks_for_date(target_date: date) -> dict[str, int | str]:
    rows = list(
        ContentPlatformClick.objects.filter(created_at__date=target_date)
        .values('content_item_id', 'surface', 'platform')
        .annotate(
            click_count=Count('id'),
            unique_user_count=Count('user_id', distinct=True),
        )
    )

    updated = 0
    with transaction.atomic():
        for row in rows:
            ContentPlatformClickDailyStat.objects.update_or_create(
                date=target_date,
                content_item_id=row['content_item_id'],
                surface=row['surface'],
                platform=row['platform'],
                defaults={
                    'click_count': row['click_count'],
                    'unique_user_count': row['unique_user_count'],
                },
            )
            updated += 1

        if not rows:
            ContentPlatformClickDailyStat.objects.filter(date=target_date).delete()

    return {
        'date': target_date.isoformat(),
        'groups': len(rows),
        'stats_written': updated,
    }


def aggregate_pending_content_platform_clicks(*, through_date: date | None = None) -> dict[str, object]:
    cutoff_date = through_date or (timezone.now().date() - timedelta(days=1))
    pending_dates = list(
        ContentPlatformClick.objects.filter(created_at__date__lte=cutoff_date)
        .dates('created_at', 'day')
    )

    results = [aggregate_content_platform_clicks_for_date(target_date) for target_date in pending_dates]

    return {
        'through_date': cutoff_date.isoformat(),
        'dates_processed': len(results),
        'results': results,
    }


def purge_old_content_platform_clicks(*, retention_days: int = 90) -> dict[str, object]:
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = ContentPlatformClick.objects.filter(created_at__lt=cutoff).delete()
    return {
        'retention_days': retention_days,
        'cutoff': cutoff.isoformat(),
        'deleted_rows': deleted,
    }


def rollup_and_cleanup_content_platform_clicks(*, retention_days: int = 90) -> dict[str, object]:
    aggregation_result = aggregate_pending_content_platform_clicks()
    purge_result = purge_old_content_platform_clicks(retention_days=retention_days)
    return {
        'aggregation': aggregation_result,
        'purge': purge_result,
    }
