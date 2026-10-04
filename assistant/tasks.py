from celery import shared_task


@shared_task(name='assistant.enforce_voice_sessions')
def enforce_voice_sessions():
    """Cut realtime calls that stopped heartbeating or ran out of minutes."""
    from .voice import enforce_sessions
    return enforce_sessions()
