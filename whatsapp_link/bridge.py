"""Django's side of whatsapp-bridge (whatsapp_bridge/, a Go service on the same host, whatsmeow).

Calls go over its Unix socket: only the app's user and group can open it, so the socket is the
authentication. What WhatsApp sends back arrives at views.bridge_events, with a token from the parameter store.
"""
import http.client
import json
import logging
import socket
import time

from . import conf

logger = logging.getLogger(__name__)


class BridgeUnavailable(Exception):
    """The bridge could not be reached: nothing was asked of WhatsApp."""


class BridgeRefused(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__('localhost', timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def _call(method, path, body=None, timeout=30):
    """The bridge's JSON answer. BridgeUnavailable when it could not be asked (socket missing or refused);
    TimeoutError when it was asked and did not answer in time (it may have acted)."""
    connection = _UnixConnection(conf.get('WHATSAPP_LINK_BRIDGE_SOCKET'), timeout)
    started = time.monotonic()
    try:
        try:
            connection.connect()
        except OSError as exc:
            raise BridgeUnavailable(type(exc).__name__) from exc
        payload = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, body=payload, headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = json.loads(response.read() or b'{}')
    except socket.timeout as exc:
        raise TimeoutError(path) from exc
    finally:
        connection.close()
        logger.info('whatsapp-bridge %s %s ms=%d', method, path, (time.monotonic() - started) * 1000)
    if response.status >= 400:
        raise BridgeRefused(str(data.get('error') or 'whatsapp'))
    return data


def pair(link_id, grant, digits, seconds, country=''):
    """The first pairing code. `country` (ISO) picks the proxy route the device connects through."""
    return _call('POST', '/pair', {'link': str(link_id), 'grant': str(grant), 'phone': digits,
                                   'country': country, 'seconds': int(seconds)}, timeout=45)['code']


def send(link_id, grant, message_id, text, *, to='', own_chat=False):
    """{'status': 'sent' | 'not_sent' | 'unknown', 'error': ...}. One message_id is sent at most once."""
    return _call('POST', '/send', {'link': str(link_id), 'grant': str(grant), 'id': str(message_id), 'to': to,
                                   'self': bool(own_chat), 'text': text}, timeout=110)


def logout(link_id, grant=''):
    """With a grant, only that pairing's device (a late logout never touches a newer pairing); without, all."""
    _call('POST', '/logout', {'link': str(link_id), 'grant': str(grant or '')}, timeout=40)
