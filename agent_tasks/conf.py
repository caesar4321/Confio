"""Settings of the cloud-browser tasks, read lazily so tests can override them.

Open to everyone (founder, 2026-11-22: no tester list). AGENT_TASKS_ENABLED
is the kill switch; the build floor keeps tasks away from apps that cannot
show the live view.
"""
import functools
import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULTS = {
    'AGENT_TASKS_ENABLED': True,
    # The first build with the task and live-view screens.
    'AGENT_TASKS_MIN_APP_VERSION': '5.4.0',
    # Open to everyone whose build has those screens: it says so itself (the
    # X-Confio-Face-Capable pattern), because a version number alone cannot.
    'AGENT_TASKS_CAPABLE_HEADER': 'HTTP_X_CONFIO_BROWSER_TASKS',
    # Where a checkout may be paid today: the country's code rail.
    'AGENT_TASKS_COUNTRIES': ('BR', 'BO', 'MX'),
    # Stores where Confío pays nothing yet: the agent buys and the person pays it from their bank.
    # None until its reading of the order's data is bound to the store's own labels (a marketplace's
    # seller writes on the order page too): countries.ManualRail.
    'AGENT_TASKS_MANUAL_COUNTRIES': (),

    'AGENT_TASKS_BROWSER': 'browserbase',
    'BROWSERBASE_API_URL': 'https://api.browserbase.com/v1',
    'BROWSERBASE_REGION': 'us-east-1',
    # Location only (prices, delivery), never a way around a site's block: a
    # blocked task stops. Needs a paid Browserbase plan (free answers 402).
    'AGENT_TASKS_GEO_PROXY': False,

    'AGENT_TASKS_QUEUE': 'browser',
    'AGENT_TASKS_MODEL': 'gpt-6.1-terra',
    'AGENT_TASKS_MODEL_TIMEOUT_SECONDS': 40,
    # The click judge (agent.judge): '' is the agent's own model.
    'AGENT_TASKS_JUDGE_MODEL': '',
    # USD per 1M tokens: (input, cached input, output).
    'AGENT_TASKS_PRICES': {
        'gpt-6.1-terra': ('1.00', '0.10', '5.00'),
        'gpt-6-luna': ('0.10', '0.01', '0.50'),
        'gpt-6.1-sol': ('2.00', '0.10', '10.00'),
    },

    # Ceilings, enforced here and never by the model.
    'AGENT_TASKS_MAX_STEPS': 45,
    'AGENT_TASKS_MAX_COST_USD': '1.00',
    'AGENT_TASKS_SESSION_SECONDS': 1500,
    # One guarded connection works this long: a late redirect is still checked.
    'AGENT_TASKS_HOLD_SECONDS': 50,
    'AGENT_TASKS_PERSON_WAIT_SECONDS': 300,
    'AGENT_TASKS_CHECKOUT_WAIT_SECONDS': 900,  # the person's checkout
    'AGENT_TASKS_PER_DAY': 5,
    # Cuenta inteligente / IA+ (assistant.billing.has_plus): the shopping assistant is part of what they pay for.
    'AGENT_TASKS_PER_DAY_PLUS': 20,
    'AGENT_TASKS_MAX_CONCURRENT': 3,
    'AGENT_TASKS_ALL_PER_DAY': 300,
    'AGENT_TASKS_KEEP_DAYS': 30,
    'AGENT_TASKS_PROFILE_IDLE_DAYS': 90,
}


def get(name):
    return getattr(settings, name, DEFAULTS[name])


_failed_until = 0.0


@functools.lru_cache(maxsize=1)
def _stored_key():
    from config.secrets import get_secret
    value = get_secret('browserbase-api-key')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('browserbase-api-key is empty')
    return value.strip()


def browserbase_api_key():
    """/confio/secrets/browserbase-api-key, or '' (then nothing starts). A
    failed read is remembered for a minute only."""
    configured = getattr(settings, 'BROWSERBASE_API_KEY', None)
    if configured is not None:
        return configured
    global _failed_until
    if time.monotonic() < _failed_until:
        return ''
    try:
        return _stored_key()
    except Exception:  # noqa: BLE001 - no key means the feature is unavailable
        _failed_until = time.monotonic() + 60
        logger.warning('Browserbase key unavailable', exc_info=True)
        return ''
