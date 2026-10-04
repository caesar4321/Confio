from celery import shared_task


@shared_task(name='security.sync_face_blocklist', bind=True, max_retries=5)
def sync_face_blocklist(self, user_id):
    """Put a permanently banned user's faces on Didit's blocklist, or take
    them off once the ban is lifted."""
    from .didit import DiditAPIError
    from .didit_blocklist import sync_face_blocklist as sync
    try:
        sync(user_id)
    except DiditAPIError as exc:
        raise self.retry(exc=exc, countdown=60 * 2 ** self.request.retries)


@shared_task(name='security.reconcile_face_blocklist')
def reconcile_face_blocklist():
    """Hourly: whatever the per-ban sync missed (broker down, Didit down)."""
    from .didit_blocklist import reconcile_face_blocklist as reconcile
    return reconcile()


@shared_task(name='security.retry_pending_same_face')
def retry_pending_same_face():
    """Hourly: documents left pending because their face comparison could not
    run (AWS or Didit unreachable); Didit sends the decision webhook once."""
    from .didit import retry_duplicated_face_search, retry_pending_same_face as retry
    synced = retry()
    try:
        synced += retry_duplicated_face_search()
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Duplicate-face search retries failed')
    return synced


@shared_task(name='security.purge_face_check_evidence')
def purge_face_check_evidence():
    """Daily: drop frames of passed Confío Face checks past their retention."""
    from .face_step_up import purge_expired_evidence
    return purge_expired_evidence()
