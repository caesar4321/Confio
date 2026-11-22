"""A key of its own: a leak of the wallet master key must not open mailboxes, nor the reverse."""
import hashlib
import hmac
import json

from cryptography.fernet import Fernet

from . import config


def _fernet():
    key = config.value('GMAIL_TOKEN_KEY')
    if not key:
        raise RuntimeError('GMAIL_TOKEN_KEY is not configured')
    return Fernet(key.encode())


def seal(data) -> str:
    return _fernet().encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()


def unseal(blob):
    return json.loads(_fernet().decrypt(blob.encode()))


def opaque(value: str) -> str:
    return hmac.new(config.value('GMAIL_TOKEN_KEY').encode(), value.encode(), hashlib.sha256).hexdigest()
