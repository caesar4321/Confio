"""The few Google calls the pilot makes. Response bodies never reach an exception or a log."""
import json

import requests

from . import config
from .errors import GmailError, GrantEnded

TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
API = 'https://gmail.googleapis.com/gmail/v1/users/me'
TIMEOUT = 15
MAX_RESPONSE = 4_000_000


def _call(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=TIMEOUT, allow_redirects=False, stream=True, **kwargs)
        try:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise GmailError(413)
                chunks.append(chunk)
        finally:
            response.close()
    except requests.RequestException:
        raise GmailError() from None
    content = b''.join(chunks)
    if response.status_code != 200:
        if url == TOKEN_URL and response.status_code in (400, 401):
            try:
                reason = json.loads(content).get('error')
            except (ValueError, AttributeError):
                reason = None
            if reason == 'invalid_grant':
                raise GrantEnded(response.status_code)
        raise GmailError(response.status_code)
    try:
        return json.loads(content) if content else {}
    except ValueError:
        raise GmailError() from None


def _client():
    return {'client_id': config.value('GMAIL_OAUTH_CLIENT_ID'),
            'client_secret': config.value('GMAIL_OAUTH_CLIENT_SECRET')}


def exchange_code(code, verifier):
    return _call('POST', TOKEN_URL, data={
        **_client(), 'grant_type': 'authorization_code', 'code': code, 'code_verifier': verifier,
        'redirect_uri': config.value('GMAIL_OAUTH_REDIRECT_URI')})


def access_token(refresh_token):
    data = _call('POST', TOKEN_URL, data={**_client(), 'grant_type': 'refresh_token', 'refresh_token': refresh_token})
    if not data.get('access_token'):
        raise GmailError()
    return data['access_token']


def revoke(token) -> bool:
    try:
        _call('POST', REVOKE_URL, data={'token': token})
    except GmailError as exc:
        # 400 = Google already considers it invalid.
        return exc.status == 400
    return True


class Mailbox:
    def __init__(self, token):
        self._headers = {'Authorization': f'Bearer {token}'}

    def address(self) -> str:
        return str(_call('GET', f'{API}/profile', headers=self._headers).get('emailAddress') or '')

    def search(self, query, limit) -> list:
        data = _call('GET', f'{API}/messages', headers=self._headers, params={'q': query, 'maxResults': limit})
        return [item['id'] for item in (data.get('messages') or []) if item.get('id')][:limit]

    def message(self, message_id) -> dict:
        if not str(message_id).isalnum():
            raise GmailError(400)
        return _call('GET', f'{API}/messages/{message_id}', headers=self._headers, params={'format': 'full'})

    def send(self, raw, thread_id=None):
        body = {'raw': raw, **({'threadId': thread_id} if thread_id else {})}
        return _call('POST', f'{API}/messages/send', headers=self._headers, json=body)
