"""Celery tasks, on the `browser` queue (settings: whatsapp_link.*): short calls to whatsapp-bridge and the
classifier. The sweep runs on `analytics`."""
from celery import shared_task


@shared_task(name='whatsapp_link.sync', ignore_result=True, soft_time_limit=90, time_limit=120)
def sync(link_id):
    from . import service
    service.sync(link_id)


@shared_task(name='whatsapp_link.send', ignore_result=True, soft_time_limit=130, time_limit=150)
def send(draft_id, tries=0):
    from . import service
    service.send(draft_id, tries)


@shared_task(name='whatsapp_link.forget', ignore_result=True, soft_time_limit=60, time_limit=80)
def forget(link_id, tries=0):
    from . import service
    service.forget(link_id, tries)


@shared_task(name='whatsapp_link.logout', bind=True, ignore_result=True, soft_time_limit=60, time_limit=80,
             max_retries=48, default_retry_delay=1800)  # a day: a device that must go
def logout(self, link_id, grant=''):
    from . import service
    try:
        service.logout(link_id, grant)
    except Exception as exc:  # noqa: BLE001 - the bridge may be restarting
        raise self.retry(exc=exc)


@shared_task(name='whatsapp_link.warn_self', ignore_result=True, soft_time_limit=130, time_limit=150)
def warn_self(link_id, grant, tries=0, _opened=0):
    from . import service
    service.warn_self(link_id, grant, tries)


@shared_task(name='whatsapp_link.drop_profile', bind=True, ignore_result=True, soft_time_limit=50, time_limit=60,
             max_retries=48, default_retry_delay=1800)  # a day: a Browserbase profile from before whatsmeow
def drop_profile(self, provider_name, context_id, session_id=''):
    from agent_tasks.browsers import BrowserUnavailable

    from . import service
    try:
        service.profile_orphaned(provider_name, context_id, session_id)
    except BrowserUnavailable as exc:
        if self.request.retries >= self.max_retries:
            import logging
            logging.getLogger(__name__).error('WhatsApp profile %s (%s) still not deleted after a day',
                                              context_id, provider_name)
        raise self.retry(exc=exc)


@shared_task(name='whatsapp_link.sweep', ignore_result=True, soft_time_limit=100, time_limit=110)
def sweep():
    from . import service
    service.sweep()
