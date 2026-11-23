"""The App-wide budget for Relay's GET /requests/v3, shared by every worker.

Only the first lookup of a deposit needs that endpoint: the request it finds
is then followed by /intents/status/v3. Normally nobody waits here
(RELAY_REQUESTS_PER_MINUTE, 60 by default, well under the documented 200).
After a 429 every worker falls back to FALLBACK_PER_MINUTE for a while.
Whenever there are fewer turns than transfers waiting, whoever waited
longest goes first, whichever task polls it. Without a turn, or without the
cache, nothing is sent.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import cache

from .relay import RelayError

logger = logging.getLogger(__name__)

STATE, MUTEX = 'relay:requests:state', 'relay:requests:mutex'
WINDOW_SECONDS = 61
DEFAULT_PER_MINUTE = 60
FALLBACK_PER_MINUTE = 2     # the least the dashboard shows
FALLBACK_SECONDS = 300
# A waiter that stopped asking (settled, closed) gives up its place. Every
# worker asks again within a minute.
WAITER_SECONDS = 150


class Held(RelayError):
    """A question not asked or not answered because of a rate limit: no
    evidence about the transfer, so it never parks or fails one."""

    def __init__(self, message='Relay lookup is waiting for its turn'):
        super().__init__(message)


@contextmanager
def _shared():
    """The shared state, or None when it cannot be had safely."""
    got, state = False, None
    try:
        for _ in range(50):
            if cache.add(MUTEX, 1, 5):
                got, state = True, cache.get(STATE) or {'sent': [], 'waiting': {}, 'slow_until': 0}
                break
            time.sleep(0.01)
    except Exception:  # noqa: BLE001 — no shared budget, no request
        logger.warning('Relay lookup budget unavailable', exc_info=True)
        state = None
    try:
        yield state
    finally:
        if got:
            try:
                if state is not None:
                    cache.set(STATE, state, 3600)
                cache.delete(MUTEX)
            except Exception:  # noqa: BLE001 — the mutex expires by itself
                logger.warning('Relay lookup budget not saved', exc_info=True)


def take(who: str) -> bool:
    """Whether `who` may send one GET now. Asking puts it in line."""
    with _shared() as state:
        if state is None:
            return False
        now = time.time()
        limit = int(getattr(settings, 'RELAY_REQUESTS_PER_MINUTE', DEFAULT_PER_MINUTE))
        if now < state['slow_until']:
            limit = min(limit, FALLBACK_PER_MINUTE)
        state['sent'] = [at for at in state['sent'] if at > now - WINDOW_SECONDS]
        waiting = {key: at for key, at in state['waiting'].items() if at[1] > now - WAITER_SECONDS}
        waiting[who] = (waiting.get(who, (now,))[0], now)       # (waiting since, last asked)
        state['waiting'] = waiting
        free = max(limit - len(state['sent']), 0)
        if who not in sorted(waiting, key=lambda key: waiting[key][0])[:free]:
            return False
        state['sent'].append(now)
        return True


def done(who: str) -> None:
    """Answered (or no longer asking): the next one's turn."""
    with _shared() as state:
        if state is not None:
            state['waiting'].pop(who, None)


def refused(who: str) -> None:
    """A 429: nobody asks for a minute, then slowly. `who` keeps its place."""
    with _shared() as state:
        if state is not None:
            now = time.time()
            state['slow_until'] = now + FALLBACK_SECONDS
            # The fallback's whole window counts as used.
            state['sent'] = state['sent'] + [now] * FALLBACK_PER_MINUTE
