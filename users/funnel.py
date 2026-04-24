"""Funnel event emission helper.

Design:
- Fire-and-forget: failures here MUST NOT break the caller (financial paths).
- on_commit semantics: when called inside a transaction, the event is only
  inserted if the transaction commits. This prevents phantom events from
  rolled-back mutations (e.g. a failed SubmitInviteForPhone that would
  otherwise log `invite_submitted` despite no on-chain submission).
- The helper accepts a ready-made dict of fields. No ORM fetches inside the
  hot path; callers pass values they already have in scope.

Usage:
    from users.funnel import emit_event

    emit_event(
        'invite_submitted',
        user=sender_user,
        country=sender_country,
        platform=None,  # server-side event, platform unknown
        properties={'amount': str(amount), 'token': token_type},
    )

If called outside a transaction, inserts immediately. If inside, defers to
on_commit. Either way, exceptions are swallowed and logged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from django.db import transaction

logger = logging.getLogger(__name__)


CREATOR_REFERRAL_CODE = 'JULIANMOONLUNA'


def derive_rollup_cohort(event_name: str, source_type: str, properties: Optional[dict] = None) -> str:
    """Return the durable low-cardinality cohort for funnel rollups."""
    source = (source_type or '').lower()
    props = properties or {}

    if source == 'send_invite':
        return 'send_invite'

    if source == 'referral_link':
        referral_code = str(props.get('referral_code') or '').strip().upper()
        if referral_code == CREATOR_REFERRAL_CODE:
            return 'creator_julianmoonluna'
        if referral_code:
            return 'user_driven'
        return 'unknown'

    if source:
        return source[:32]

    return 'unknown'


def emit_event(
    event_name: str,
    *,
    user: Optional[Any] = None,
    session_id: str = '',
    country: str = '',
    platform: str = '',
    source_type: str = '',
    channel: str = '',
    properties: Optional[dict] = None,
) -> None:
    """Emit a funnel event. Safe to call from any context.

    Never raises. Defers to on_commit when inside an atomic block.
    """

    # Snapshot values now so a later fetch doesn't fail (e.g. user gc'd
    # before the on_commit fires — unlikely but cheap to guard).
    user_id = getattr(user, 'id', None) if user is not None else None
    payload = {
        'event_name': (event_name or '')[:64],
        'user_id': user_id,
        'session_id': (session_id or '')[:64],
        'country': (country or '').upper()[:2],
        'platform': (platform or '').lower()[:16],
        'source_type': (source_type or '').lower()[:32],
        'channel': (channel or '').lower()[:32],
        'properties': properties or {},
    }

    def _insert():
        try:
            # Late import to avoid circulars during app boot.
            from users.models_analytics import FunnelEvent
            FunnelEvent.objects.create(**payload)
        except Exception as exc:  # noqa: BLE001 — never let analytics break callers
            logger.warning('[funnel] emit_event(%s) failed: %s', event_name, exc)

    try:
        conn = transaction.get_connection()
        if conn.in_atomic_block:
            transaction.on_commit(_insert)
        else:
            _insert()
    except Exception as exc:  # noqa: BLE001
        logger.warning('[funnel] emit_event(%s) dispatch failed: %s', event_name, exc)
