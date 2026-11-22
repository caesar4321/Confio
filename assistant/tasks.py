from celery import shared_task


@shared_task(name='assistant.enforce_voice_sessions')
def enforce_voice_sessions():
    """Cut realtime calls that stopped heartbeating or ran out of minutes."""
    from .voice import enforce_sessions
    return enforce_sessions()


# Queued on the analytics worker by assistant/memory.py: never on the money queue.
@shared_task(name='assistant.summarize_context', soft_time_limit=60, time_limit=90, ignore_result=True)
def summarize_context(conversation_id):
    """Pick which older messages of a thread stay as context."""
    from .memory import summarize
    return summarize(conversation_id)


@shared_task(name='assistant.tag_needs')
def tag_needs():
    """Nightly: tag what people asked for (product evidence), and empty the
    memory of deleted accounts (assistant/memory.py)."""
    import logging

    from .needs import tag_recent
    try:
        from .memory import sweep
        sweep()
    except Exception as exc:  # noqa: BLE001 - the tagger still runs
        logging.getLogger(__name__).warning('assistant memory sweep failed (%s)', type(exc).__name__)
    return tag_recent()


# Both run on the analytics worker (CELERY_TASK_ROUTES): mail must never hold the money queue.
@shared_task(name='assistant.gmail_sweep', soft_time_limit=240, time_limit=280, ignore_result=True)
def gmail_sweep():
    """Gmail pilot: erase what must not stay, then (pilot on) nudge and queue due syncs."""
    from .gmail import sync
    sync.cleanup()
    sync.nudge()
    ids = sync.due_connection_ids()
    for connection_id in ids:
        # Not started by the next sweep: dropped, and that sweep queues it again.
        gmail_sync.apply_async((connection_id,), expires=14 * 60)
    return len(ids)


@shared_task(name='assistant.gmail_sync', soft_time_limit=90, time_limit=120, ignore_result=True)
def gmail_sync(connection_id):
    from .gmail import sync
    sync.sync(connection_id)
