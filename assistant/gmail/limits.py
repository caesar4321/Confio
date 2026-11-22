import logging

from django.core.cache import cache

from .errors import MailRefused

logger = logging.getLogger(__name__)
PER_DAY = {'ask': 40, 'draft': 40, 'send': 20, 'connect': 10, 'source': 60}


def claim(user, action):
    key = f'assistant-gmail:{action}:{user.pk}'
    try:
        cache.add(key, 0, 86400)
        count = cache.incr(key)
    except Exception:  # noqa: BLE001 - no counter, no call
        logger.warning('Gmail pilot limit unavailable')
        count = None
    if not isinstance(count, int) or count > PER_DAY[action]:
        raise MailRefused('rate_limited', 'Llegaste al límite de hoy con tu correo. Prueba mañana.')
