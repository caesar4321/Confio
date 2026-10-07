"""GraphQL mutation for client-originated funnel events.

Allowed event names are whitelisted — clients can only emit events we've
declared as safe to accept from untrusted input. Server-emitted events
(invite_submitted, invite_claimed, first_deposit) MUST NOT be in this list
so they cannot be forged from the client.
"""

from __future__ import annotations

import logging
import json
import ipaddress

import graphene

logger = logging.getLogger(__name__)


# Client-emittable events. Keep this tight.
CLIENT_EMITTABLE_EVENTS = frozenset({
    'whatsapp_share_tapped',
    'referral_whatsapp_share_tapped',
    'invite_share_dismissed',
    'claim_entry_viewed',
    'signup_completed',
    'financiera_whatsapp_tapped',
    'receive_rail_interest',
    'local_rail_interest',
    'local_rail_blocked_interest',
    # "Tu mes" month summary + category chips (design R15)
    'tu_mes_opened',
    'hero_cashflow_tapped',
    'category_chip_shown',
    'category_chip_answered',
    'category_chip_skipped',
    'category_chip_dismissed',
    # Paid-offer probes (Confío IA+, Cuenta inteligente); `stage` in properties.
    'paid_offer_interest',
})


def _cached_ip_country(meta):
    """Best-effort country enrichment; analytics must not make network calls."""
    from security.geo import normalize_country
    from security.models import IPAddress
    from security.request_utils import extract_client_ip_from_meta

    meta = meta or {}
    country = normalize_country(meta.get('HTTP_CF_IPCOUNTRY'))
    if country:
        return country
    client_ip = extract_client_ip_from_meta(meta)
    if not client_ip:
        return ''
    try:
        if not ipaddress.ip_address(client_ip).is_global:
            return ''
    except ValueError:
        return ''
    country = IPAddress.objects.filter(ip_address=client_ip).values_list(
        'country_code', flat=True).first()
    return normalize_country(country) or ''


def _client_paid_offer_stage(properties):
    stage = properties.get('stage')
    if stage == 'door_shown':
        return properties.get('door') in ('billeteras', 'assistant_header')
    return stage in ('detail_opened', 'solo_miraba')


class TrackFunnelEvent(graphene.Mutation):
    """Record a client-originated funnel event.

    Safe for unauthenticated callers (session_id carries pre-signup identity).
    Returns success even on validation failure so analytics never breaks UX;
    the `recorded` flag tells the client whether the event was actually
    persisted.
    """

    class Arguments:
        event_name = graphene.String(required=True)
        session_id = graphene.String(required=False)
        platform = graphene.String(required=False)
        country = graphene.String(required=False)
        source_type = graphene.String(required=False)
        channel = graphene.String(required=False)
        properties = graphene.JSONString(required=False)

    success = graphene.Boolean()
    recorded = graphene.Boolean()

    @classmethod
    def mutate(
        cls,
        root,
        info,
        event_name: str,
        session_id: str = '',
        platform: str = '',
        country: str = '',
        source_type: str = '',
        channel: str = '',
        properties=None,
    ):
        # Reject unknown events silently — success=True, recorded=False.
        # Keeps analytics reliable: we never want a legitimate mutation
        # failure to bubble to the user because of a typo in an event name.
        if event_name not in CLIENT_EMITTABLE_EVENTS:
            logger.info('[funnel] rejected client event %r', event_name)
            return cls(success=True, recorded=False)

        # Bound property payload size to avoid abuse.
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except Exception:
                properties = {}

        if isinstance(properties, dict):
            try:
                if len(json.dumps(properties)) > 2048:
                    properties = {'_truncated': True}
            except Exception:
                properties = {}
        elif properties is None:
            properties = {}
        else:
            properties = {}

        if event_name == 'paid_offer_interest' and not _client_paid_offer_stage(properties):
            # Joins, answers and chip impressions are written by the server
            # (with the waitlist row as the authority); a client can't add them.
            logger.info('[funnel] rejected client paid_offer_interest stage %r', properties.get('stage'))
            return cls(success=True, recorded=False)

        user = getattr(info.context, 'user', None)
        if user is not None and not getattr(user, 'is_authenticated', False):
            user = None

        if (event_name == 'paid_offer_interest' and user is not None and properties.get('door') == 'chip'
                and not properties.get('trigger')):
            # The app doesn't carry a chip's reason; the server logged it when
            # it showed the chip ('' = chip, reason unknown).
            try:
                from users.product_waitlist_schema import _last_chip_trigger
                properties['trigger'] = _last_chip_trigger(
                    user, str(source_type or properties.get('offer', '')).lower())
            except Exception:  # noqa: BLE001 - analytics never fail the request
                logger.warning('[funnel] paid offer chip trigger lookup failed', exc_info=True)
                properties['trigger'] = ''

        # If authenticated and country not provided, fall back to user's phone_country.
        if not country and user is not None:
            country = getattr(user, 'phone_country', '') or ''

        # Estimated request country for demand analytics; VPNs/proxies can
        # differ from physical location. Store only the country, never the IP.
        try:
            ip_country = _cached_ip_country(getattr(info.context, 'META', {}))
        except Exception:
            logger.warning('[funnel] ip country lookup failed')
            ip_country = ''

        try:
            from users.funnel import emit_event, emit_once
            dedupe_key = str(properties.get('dedupe_key') or '') if isinstance(properties, dict) else ''
            if dedupe_key:
                emit_once(
                    event_name,
                    user=user,
                    session_id=session_id or '',
                    country=country or '',
                    ip_country=ip_country,
                    platform=platform or '',
                    source_type=source_type or '',
                    channel=channel or '',
                    properties=properties,
                    dedupe_key=dedupe_key,
                )
            else:
                emit_event(
                    event_name,
                    user=user,
                    session_id=session_id or '',
                    country=country or '',
                    ip_country=ip_country,
                    platform=platform or '',
                    source_type=source_type or '',
                    channel=channel or '',
                    properties=properties,
                )
        except Exception:
            logger.exception('[funnel] TrackFunnelEvent dispatch failed')
            return cls(success=True, recorded=False)

        return cls(success=True, recorded=True)


class FunnelMutations(graphene.ObjectType):
    track_funnel_event = TrackFunnelEvent.Field()
