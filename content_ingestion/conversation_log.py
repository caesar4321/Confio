"""Logs Telegram conversations into the ConfioAI repo so the bot's history is
durable and versioned. Turns are appended to per-chat/day markdown files
immediately (cheap, local); a periodic flush commits + pushes them in batches.

Coordinates with the confioai-pull.timer via an flock(2) lockfile so the puller
and this writer never run git at the same time."""
from __future__ import annotations

import fcntl
import logging
import os
import subprocess
import threading
from datetime import datetime, timezone

from django.conf import settings

logger = logging.getLogger(__name__)

# Serializes file appends within this process.
_APPEND_LOCK = threading.Lock()
# Shared with confioai-pull.service (also flock'd) to serialize git operations.
GIT_LOCKFILE = '/tmp/confioai-git.lock'


def _repo() -> str:
    return getattr(settings, 'CONFIO_AI_REPO_PATH', '') or ''


def enabled() -> bool:
    if not getattr(settings, 'CONFIO_AI_LOG_CONVERSATIONS', True):
        return False
    repo = _repo()
    return bool(repo) and os.path.isdir(os.path.join(repo, '.git'))


def _clip(text: str, limit: int = 2000) -> str:
    text = ' '.join((text or '').split())
    return text[:limit] + ('…' if len(text) > limit else '')


def append_turn(chat_id, user_name: str, user_text: str, reply_text: str) -> None:
    """Append one user→bot turn to docs/conversations/<chat>/<YYYY-MM-DD>.md."""
    if not enabled():
        return
    now = datetime.now(timezone.utc)
    day = now.strftime('%Y-%m-%d')
    ts = now.strftime('%H:%M')
    path = os.path.join(_repo(), 'docs', 'conversations', str(chat_id), f'{day}.md')
    lines = [
        f'- **{ts}** {user_name}: {_clip(user_text)}',
        f'- **{ts}** Confío AI: {_clip(reply_text)}',
        '',
    ]
    try:
        with _APPEND_LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            new = not os.path.exists(path)
            with open(path, 'a', encoding='utf-8') as fh:
                if new:
                    fh.write(f'# Conversación {chat_id} — {day}\n\n')
                fh.write('\n'.join(lines) + '\n')
    except OSError:
        logger.exception('Could not append conversation turn for chat %s', chat_id)


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=repo, check=False, capture_output=True, text=True)


def commit_and_push() -> str:
    """Commit + push any pending conversation logs. Safe to call on a timer.

    Returns a short status string for logging. Always pulls (rebase) so the local
    clone stays fresh even when there's nothing to push."""
    if not enabled():
        return 'disabled'
    repo = _repo()
    lock_fd = open(GIT_LOCKFILE, 'w')
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 'skipped (git busy)'

        _git(repo, 'add', 'docs/conversations')
        has_changes = _git(repo, 'diff', '--cached', '--quiet').returncode != 0
        if has_changes:
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            _git(repo, 'commit', '-m', f'Log conversations ({ts})')

        _git(repo, 'pull', '--rebase', '--autostash')

        if not has_changes:
            return 'no changes'

        push = _git(repo, 'push', 'origin', 'HEAD')
        if push.returncode != 0:
            logger.warning('Conversation log push failed: %s', (push.stderr or '').strip()[:300])
            return 'push failed'
        return 'pushed'
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()
