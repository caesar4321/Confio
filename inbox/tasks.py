from celery import shared_task

from .click_tracking import rollup_and_cleanup_content_platform_clicks
from .push_service import send_content_item_push


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=5, retry_kwargs={'max_retries': 3})
def send_content_item_push_task(self, content_item_id: int):
    return send_content_item_push(content_item_id)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_kwargs={'max_retries': 3})
def rollup_content_platform_clicks_task(self, retention_days: int = 90):
    return rollup_and_cleanup_content_platform_clicks(retention_days=retention_days)
