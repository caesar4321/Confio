from celery import shared_task


@shared_task(name='security.purge_face_check_evidence')
def purge_face_check_evidence():
    """Daily: drop frames of passed Confío Face checks past their retention."""
    from .face_step_up import purge_expired_evidence
    return purge_expired_evidence()
