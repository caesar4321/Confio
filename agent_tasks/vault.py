"""A person's store sign-ins, and a one-time code on its way to a store.

Encrypted at rest (users.encryption). Read only by the runner, to type into
the store's own sign-in page; never returned by any API, never put in a note,
a log, the chat or a model's input.
"""
import json
import logging

from users.encryption import decrypt_data, encrypt_data

from .models import AgentCredential, AgentTask

logger = logging.getLogger(__name__)
MAX_CHARS = 200


def save(user, site, identifier, password):
    secret = encrypt_data(json.dumps({'identifier': str(identifier)[:MAX_CHARS], 'password': str(password)[:MAX_CHARS]}))
    AgentCredential.objects.update_or_create(user=user, site=site, defaults={'secret': secret})


def get(user, site):
    """{'identifier', 'password'} or None."""
    row = AgentCredential.objects.filter(user=user, site=site).first()
    if row is None:
        return None
    try:
        data = json.loads(decrypt_data(row.secret))
        return data if data.get('identifier') and data.get('password') else None
    except Exception:  # noqa: BLE001 - unreadable is absent
        logger.warning('agent credential could not be read')
        return None


def forget(user, site):
    AgentCredential.objects.filter(user=user, site=site).delete()


def put_code(task, code):
    AgentTask.objects.filter(pk=task.pk).update(secret_once=encrypt_data(str(code)[:20]))


def take_code(task):
    """The code typed for this task, once: it is cleared as it is read."""
    row = AgentTask.objects.filter(pk=task.pk).values_list('secret_once', flat=True).first()
    if not row:
        return ''
    AgentTask.objects.filter(pk=task.pk).update(secret_once='')
    try:
        return decrypt_data(row)
    except Exception:  # noqa: BLE001
        return ''
