from celery import shared_task

from .click_tracking import rollup_and_cleanup_content_platform_clicks
from .push_service import (
    CONTENT_PUSH_CLAIM_TTL,
    ContentPushInProgress,
    send_content_item_push,
)


CONTENT_PUSH_RETRY_DELAY_SECONDS = int(CONTENT_PUSH_CLAIM_TTL.total_seconds()) + 30


@shared_task(
    bind=True,
    queue='push',
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_kwargs={'max_retries': 3},
)
def send_content_item_push_task(self, content_item_id: int):
    try:
        return send_content_item_push(content_item_id)
    except ContentPushInProgress as exc:
        # By the next attempt the first worker has either finalized or its
        # delivery claim is stale and can be recovered.
        raise self.retry(
            exc=exc,
            countdown=CONTENT_PUSH_RETRY_DELAY_SECONDS,
            max_retries=3,
        )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_kwargs={'max_retries': 3})
def rollup_content_platform_clicks_task(self, retention_days: int = 90):
    return rollup_and_cleanup_content_platform_clicks(retention_days=retention_days)
