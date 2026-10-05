"""Operator alerts to the team's Telegram group (where Confio Brain lives).

Sent by a dedicated Telegram BOT through the Bot API — never through the
Confio Brain user session: a second Telethon client on that session kills the
live listener (AuthKeyDuplicated).

Secret (Secrets Manager, eu-central-2), name from settings.OPS_ALERT_TELEGRAM_SECRET
(default 'prod/ops-alert-telegram'), JSON: {"bot_token": "...", "chat_id": "-100..."}.
Read at send time (cached per process once found), so adding the secret needs
no restart. Missing secret or a Telegram failure never raises: the alert is
also always logged, and callers are monitors that must keep running.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.cache import cache

from .secrets import get_secret

logger = logging.getLogger(__name__)

TELEGRAM_TIMEOUT_S = 10


def _credentials() -> tuple[str, str] | None:
    name = getattr(settings, 'OPS_ALERT_TELEGRAM_SECRET', 'prod/ops-alert-telegram')
    try:
        secret = get_secret(name)
    except Exception as exc:  # noqa: BLE001 — no secret = log-only alerts
        logger.warning('ops alert: Telegram secret %s unavailable: %s', name, exc)
        return None
    if not isinstance(secret, dict) or not secret.get('bot_token') or not secret.get('chat_id'):
        logger.warning('ops alert: Telegram secret %s must be JSON with bot_token and chat_id', name)
        return None
    return str(secret['bot_token']), str(secret['chat_id'])


def send_ops_alert(text: str, *, dedupe_key: str | None = None, dedupe_seconds: int = 0) -> bool:
    """Post `text` to the ops Telegram group. Returns True if Telegram accepted it.

    With `dedupe_key`, at most one alert per key per `dedupe_seconds` (shared
    cache, so concurrent workers don't double-post).
    """
    slot = f'ops_alert:{dedupe_key}' if dedupe_key and dedupe_seconds > 0 else None
    if slot:
        try:
            if not cache.add(slot, 1, timeout=dedupe_seconds):
                return False
        except Exception as exc:  # noqa: BLE001 — a cache outage must not swallow the alert
            logger.warning('ops alert: dedupe cache unavailable, sending anyway: %s', exc)
            slot = None
    ok = _send(text)
    if not ok and slot:
        # A failed send must not use up the window: the next run retries.
        try:
            cache.delete(slot)
        except Exception:  # noqa: BLE001
            pass
    return ok


def _send(text: str) -> bool:
    creds = _credentials()
    if not creds:
        return False
    token, chat_id = creds
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True},
            timeout=TELEGRAM_TIMEOUT_S,
        )
        ok = resp.ok and resp.json().get('ok') is True
    except Exception as exc:  # noqa: BLE001
        # Never log str(exc): requests puts the URL — and so the bot token — in it.
        logger.error('ops alert: Telegram send failed: %s', type(exc).__name__)
        return False
    if not ok:
        logger.error('ops alert: Telegram rejected the alert: HTTP %s %s',
                     resp.status_code, resp.text[:300].replace(token, '***'))
    return ok
