"""Settings of the WhatsApp link, read lazily so tests can override them.

The person's own WhatsApp, linked as one more device in whatsapp-bridge (whatsapp_bridge/, Go, whatsmeow) on
our own host. Open to everyone; WHATSAPP_LINK_ENABLED is the kill switch.
"""
from django.conf import settings

DEFAULTS = {
    'WHATSAPP_LINK_ENABLED': True,
    # The bridge's socket (systemd RuntimeDirectory). Only the app's user and group may open it.
    'WHATSAPP_LINK_BRIDGE_SOCKET': '/run/whatsapp-bridge/bridge.sock',
    # The token the bridge sends with each delivery, in the parameter store: {"token": ...}. Never the bridge's
    # database: that lives outside /confio/secrets/ (which every Django process loads), read by the bridge alone.
    'WHATSAPP_LINK_BRIDGE_SECRET': 'prod/whatsapp-bridge',
    # How long a pairing code is asked again for the person to type it.
    'WHATSAPP_LINK_PAIRING_SECONDS': 600,
    # Messages that arrive close together are looked at together, this long after the first.
    'WHATSAPP_LINK_BATCH_SECONDS': 30,
    # Founder 2026-11-24: each chat's last 48 hours (both sides) are the context every look reads.
    'WHATSAPP_LINK_CONTEXT_HOURS': 48,
    # Founder 2026-11-26: each chat's last 30 days are kept, sealed, on every link, so the person can ask about
    # older messages; older ones are deleted, and all of it with the link.
    'WHATSAPP_LINK_HISTORY_DAYS': 30,
    # Only what the person approved, one at a time, at a person's pace.
    'WHATSAPP_LINK_SENDS_PER_DAY': 20,
    'WHATSAPP_LINK_NEW_NUMBERS_PER_DAY': 5,
    # None: kept while the WhatsApp stays linked (founder 2026-11-24); unlinking, from Confío or the phone,
    # erases them, as does dismissing one. A number of days sets a limit again.
    'WHATSAPP_LINK_KEEP_DAYS': None,
    'WHATSAPP_LINK_MODEL': 'gpt-6-luna',
}


def get(name):
    return getattr(settings, name, DEFAULTS[name])
