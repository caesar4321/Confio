from celery import shared_task


@shared_task(name='assistant.enforce_voice_sessions')
def enforce_voice_sessions():
    """Cut realtime calls that stopped heartbeating or ran out of minutes."""
    from .voice import enforce_sessions
    return enforce_sessions()


@shared_task(name='assistant.tag_needs')
def tag_needs():
    """Nightly: tag what people asked for (product evidence)."""
    from .needs import tag_recent
    return tag_recent()
