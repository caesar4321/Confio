"""Celery tasks. Browser work runs on the `browser` queue beside the shopping agent: WhatsApp runs at most two
of its three processes at once (service._slot), so a purchase always has one."""
from celery import shared_task


@shared_task(name='whatsapp_link.pair', ignore_result=True, soft_time_limit=150, time_limit=195)
def pair(link_id, grant, tries=0):
    from . import service
    service.pair(link_id, grant, tries)


@shared_task(name='whatsapp_link.watch', ignore_result=True, soft_time_limit=150, time_limit=195)
def watch(link_id, grant):
    from . import service
    service.watch(link_id, grant)


@shared_task(name='whatsapp_link.sync', ignore_result=True, soft_time_limit=170, time_limit=215)
def sync(link_id):
    from . import service
    service.sync(link_id)


@shared_task(name='whatsapp_link.send', ignore_result=True, soft_time_limit=240, time_limit=285)
def send(draft_id, tries=0):
    from . import service
    service.send(draft_id, tries)


@shared_task(name='whatsapp_link.forget', ignore_result=True, soft_time_limit=110, time_limit=155)
def forget(link_id, tries=0):
    from . import service
    service.forget(link_id, tries)


@shared_task(name='whatsapp_link.drop_profile', bind=True, ignore_result=True, soft_time_limit=50, time_limit=60,
             max_retries=48, default_retry_delay=1800)  # a day: a profile may hold a live session
def drop_profile(self, provider_name, context_id, session_id=''):
    from agent_tasks.browsers import BrowserUnavailable

    from . import service
    try:
        service.profile_orphaned(provider_name, context_id, session_id)
    except BrowserUnavailable as exc:
        if self.request.retries >= self.max_retries:
            import logging
            # The context id is useless without the vendor key: it is what lets ops delete it by hand.
            logging.getLogger(__name__).error('WhatsApp profile %s (%s) still not deleted after a day',
                                              context_id, provider_name)
        raise self.retry(exc=exc)


@shared_task(name='whatsapp_link.sweep_vendor', ignore_result=True, soft_time_limit=80, time_limit=125)
def sweep_vendor():
    from . import service
    service.sweep_vendor()


@shared_task(name='whatsapp_link.sweep', ignore_result=True, soft_time_limit=100, time_limit=110)
def sweep():
    from . import service
    service.sweep()
