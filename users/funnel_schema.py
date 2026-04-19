"""GraphQL mutation for client-originated funnel events.

Allowed event names are whitelisted — clients can only emit events we've
declared as safe to accept from untrusted input. Server-emitted events
(invite_submitted, invite_claimed, first_deposit) MUST NOT be in this list
so they cannot be forged from the client.
"""

from __future__ import annotations

import logging
import json

import graphene

logger = logging.getLogger(__name__)


# Client-emittable events. Keep this tight.
CLIENT_EMITTABLE_EVENTS = frozenset({
    'whatsapp_share_tapped',
    'referral_whatsapp_share_tapped',
    'invite_share_dismissed',
    'claim_entry_viewed',
})


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

        user = getattr(info.context, 'user', None)
        if user is not None and not getattr(user, 'is_authenticated', False):
            user = None

        # If authenticated and country not provided, fall back to user's phone_country.
        if not country and user is not None:
            country = getattr(user, 'phone_country', '') or ''

        try:
            from users.funnel import emit_event
            emit_event(
                event_name,
                user=user,
                session_id=session_id or '',
                country=country or '',
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
