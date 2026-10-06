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


COMMUNITY_REVIEW_MAX_RETRIES = 3


@shared_task(bind=True, max_retries=COMMUNITY_REVIEW_MAX_RETRIES)
def review_community_post_task(self, review_id: int):
    from .community import ReviewUnavailable, mark_review_failed, run_community_review

    try:
        return run_community_review(review_id)
    except ReviewUnavailable as exc:
        if self.request.retries >= COMMUNITY_REVIEW_MAX_RETRIES:
            # Out of retries: tell the author to try again. Never publish.
            # Only this attempt's claim may fail it, never a newer attempt.
            mark_review_failed(review_id, str(exc), claim=getattr(exc, 'claim', None))
            return 'FAILED'
        raise self.retry(exc=exc, countdown=5 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def rereview_community_post_task(self, review_id: int):
    from .community import ReviewUnavailable, allow_rereview, rereview_reported_post
    from .models import CommunityPostReview

    try:
        return rereview_reported_post(review_id)
    except ReviewUnavailable as exc:
        if self.request.retries >= self.max_retries:
            allow_rereview(CommunityPostReview, review_id)
            return 'UNDECIDED'
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=COMMUNITY_REVIEW_MAX_RETRIES)
def review_community_comment_task(self, comment_id: int):
    from .community import ReviewUnavailable, mark_comment_failed, run_comment_review

    try:
        return run_comment_review(comment_id)
    except ReviewUnavailable as exc:
        if self.request.retries >= COMMUNITY_REVIEW_MAX_RETRIES:
            mark_comment_failed(comment_id, str(exc), claim=getattr(exc, 'claim', None))
            return 'FAILED'
        raise self.retry(exc=exc, countdown=5 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def rereview_community_comment_task(self, comment_id: int):
    from .community import ReviewUnavailable, allow_rereview, rereview_reported_comment
    from .models import CommunityComment

    try:
        return rereview_reported_comment(comment_id)
    except ReviewUnavailable as exc:
        if self.request.retries >= self.max_retries:
            allow_rereview(CommunityComment, comment_id)
            return 'UNDECIDED'
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=COMMUNITY_REVIEW_MAX_RETRIES)
def review_profile_picture_task(self, submission_id: int):
    from .community import ReviewUnavailable
    from .profile_pictures import mark_picture_failed, run_picture_review

    try:
        return run_picture_review(submission_id)
    except ReviewUnavailable as exc:
        if self.request.retries >= COMMUNITY_REVIEW_MAX_RETRIES:
            mark_picture_failed(submission_id, str(exc), claim=getattr(exc, 'claim', None))
            return 'FAILED'
        raise self.retry(exc=exc, countdown=5 * (2 ** self.request.retries))


@shared_task
def sweep_stuck_community_reviews_task():
    from .community import (
        mark_comment_failed, mark_review_failed, stuck_comment_ids, stuck_review_ids,
    )

    # Each failure re-checks staleness under the row lock: a worker that just
    # picked the row up is left alone.
    retry, exhausted, cutoff = stuck_review_ids()
    for review_id in exhausted:
        mark_review_failed(review_id, 'Out of review attempts', stale_before=cutoff)
    for review_id in retry:
        review_community_post_task.delay(review_id)
    comment_retry, comment_exhausted, comment_cutoff = stuck_comment_ids()
    for comment_id in comment_exhausted:
        mark_comment_failed(comment_id, 'Out of review attempts', stale_before=comment_cutoff)
    for comment_id in comment_retry:
        review_community_comment_task.delay(comment_id)
    from .profile_pictures import mark_picture_failed, stuck_picture_ids

    picture_retry, picture_exhausted, picture_cutoff = stuck_picture_ids()
    for submission_id in picture_exhausted:
        mark_picture_failed(submission_id, 'Out of review attempts', stale_before=picture_cutoff)
    for submission_id in picture_retry:
        review_profile_picture_task.delay(submission_id)
    # Durable image cleanup: whatever the database says should no longer be
    # public is retried here until the delete lands, even if a fast-path task
    # was never queued or ran out of retries.
    from .community import posts_with_public_images_owed
    from .profile_pictures import pictures_owed_deletion

    for review_id in posts_with_public_images_owed():
        hide_community_post_image_task.delay(review_id)
    for submission_id in pictures_owed_deletion():
        delete_profile_picture_public_task.delay(submission_id)
    from .public_objects import owed

    for object_id in owed():
        delete_public_object_task.delay(object_id)
    from .community import lost_rereview_ids
    from .models import CommunityComment, CommunityPostReview

    for review_id in lost_rereview_ids(CommunityPostReview):
        rereview_community_post_task.delay(review_id)
    for comment_id in lost_rereview_ids(CommunityComment):
        rereview_community_comment_task.delay(comment_id)
    return {
        'requeued': len(retry) + len(comment_retry) + len(picture_retry),
        'failed': len(exhausted) + len(comment_exhausted) + len(picture_exhausted),
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_kwargs={'max_retries': 8})
def hide_community_post_image_task(self, review_id: int):
    from .community import hide_post_image

    return hide_post_image(review_id)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_kwargs={'max_retries': 8})
def delete_profile_picture_public_task(self, submission_id: int):
    from .profile_pictures import delete_public_picture

    return delete_public_picture(submission_id)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_kwargs={'max_retries': 8})
def delete_public_object_task(self, object_id: int):
    from .public_objects import delete_owed

    return delete_owed(object_id)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_kwargs={'max_retries': 5})
def remove_member_content_task(self, user_id: int, kind: str):
    """A deleted or banned account's Comunidad content comes down for good."""
    from .community import remove_member_content

    reasons = {
        'deleted': ('account_deleted', 'Cuenta eliminada.'),
        'banned': ('account_banned', 'Cuenta suspendida.'),
    }
    category, reason = reasons.get(kind, ('account_removed', 'Contenido retirado.'))
    return remove_member_content(user_id, category=category, reason=reason)
