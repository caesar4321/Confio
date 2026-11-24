"""Settings of the WhatsApp link, read lazily so tests can override them.

The person's own WhatsApp, linked as one more device (WhatsApp Web) in a
cloud browser that is theirs alone. Open to everyone; WHATSAPP_LINK_ENABLED
is the kill switch.
"""
from django.conf import settings

DEFAULTS = {
    'WHATSAPP_LINK_ENABLED': True,
    'WHATSAPP_LINK_REGION': 'eu-central-1',
    # A desktop screen: WhatsApp Web sends a phone-sized browser to the app store.
    'WHATSAPP_LINK_VIEWPORT': {'width': 1280, 'height': 900},
    # How long a pairing browser stays open for the person to type the code.
    'WHATSAPP_LINK_PAIRING_SECONDS': 600,
    # Founder 2026-11-23: every two hours at most, to keep the browser bill small.
    # Opening Confío IA also asks for a read, at most every REFRESH minutes.
    'WHATSAPP_LINK_SYNC_MINUTES': 120,
    'WHATSAPP_LINK_REFRESH_MINUTES': 15,
    'WHATSAPP_LINK_SYNC_SECONDS': 240,
    # One read at a time fits the plan: the sweep starts one, and each finished read starts the next.
    'WHATSAPP_LINK_SYNCS_PER_SWEEP': 1,
    # The vendor plan's browsers at once (Browserbase project concurrency, read 2026-11-24: 3), shared with
    # the shopping agent. WhatsApp yields: it holds at most MAX_SESSIONS, opens only while the plan has room,
    # and a background read always leaves one browser free.
    'WHATSAPP_LINK_PLAN_CONCURRENCY': 3,
    'WHATSAPP_LINK_MAX_SESSIONS': 1,
    # Only what the person approved, one at a time, at a person's pace.
    'WHATSAPP_LINK_SENDS_PER_DAY': 20,
    'WHATSAPP_LINK_NEW_NUMBERS_PER_DAY': 5,
    'WHATSAPP_LINK_KEEP_DAYS': 7,
    'WHATSAPP_LINK_MODEL': 'gpt-6-luna',
}


def get(name):
    return getattr(settings, name, DEFAULTS[name])
