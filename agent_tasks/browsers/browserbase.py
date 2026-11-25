"""Browserbase over its REST API (docs.browserbase.com, read 2026-11-22).

The vendor solves CAPTCHAs for the agent (solveCaptchas, founder 2026-11-23:
the person is never sent to a store to prove they are one). Two vendor
defaults stay reversed:
  recordSession  off: store passwords are typed in this browser;
  logSession     off: the same, in network and console logs.
"""
import logging

import requests
from django.utils.dateparse import parse_datetime

from .. import conf
from . import BrowserProvider, BrowserUnavailable, Session

logger = logging.getLogger(__name__)

TIMEOUT = 20
VIEWPORT = {'width': 412, 'height': 915}  # the live view is read on a phone
MIN_SECONDS, MAX_SECONDS = 60, 21600


class Browserbase(BrowserProvider):
    name = 'browserbase'

    def _call(self, method, path, *, body=None, params=None, ok=(200, 201, 204)):
        key = conf.browserbase_api_key()
        if not key:
            raise BrowserUnavailable('Browserbase key is not configured')
        try:
            response = requests.request(
                method, f"{conf.get('BROWSERBASE_API_URL')}{path}", json=body, params=params,
                headers={'X-BB-API-Key': key}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise BrowserUnavailable(f'Browserbase {method} failed: {type(exc).__name__}') from exc
        if response.status_code not in ok:
            code = {402: 'quota', 429: 'busy'}.get(response.status_code, 'unavailable')
            # Status only: a response body can echo a session's connect URL.
            raise BrowserUnavailable(f'Browserbase {method} answered {response.status_code}', code,
                                     status=response.status_code)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise BrowserUnavailable('Browserbase answered something that is not JSON') from exc

    def create_profile(self):
        profile = self._call('POST', '/contexts', body={}).get('id')
        if not profile:
            raise BrowserUnavailable('Browserbase returned no context id')
        return str(profile)

    def delete_profile(self, profile_id):
        self._call('DELETE', f'/contexts/{profile_id}', ok=(200, 204, 404))

    def open(self, *, profile_id, country, seconds, viewport=None, region=None, solve_captchas=True):
        geo = str(country or '').strip().upper()
        geo = geo if len(geo) == 2 and geo.isascii() and geo.isalpha() and geo not in ('XX', 'T1') else ''
        body = {
            'keepAlive': True,  # each step reconnects, so no worker waits on a person
            'timeout': max(MIN_SECONDS, min(int(seconds), MAX_SECONDS)),
            'region': region or conf.get('BROWSERBASE_REGION'),
            'browserSettings': {
                'solveCaptchas': bool(solve_captchas),
                'recordSession': False,
                'logSession': False,
                'viewport': viewport or VIEWPORT,
                'context': {'id': profile_id, 'persist': True},
            },
        }
        if conf.get('AGENT_TASKS_GEO_PROXY'):
            body['proxies'] = ([{'type': 'browserbase', 'geolocation': {'country': geo}}]
                               if geo else True)
        try:
            data = self._call('POST', '/sessions', body=body)
        except BrowserUnavailable as exc:
            if 'proxies' not in body:
                raise
            if exc.code == 'quota':
                # The plan has no proxies (Browserbase's free plan answers 402): the store's own country
                # is a nicety, a browser is not. Opened from Browserbase's own address instead.
                logger.warning('Browserbase refused the %s proxy (plan): opening without it', geo or 'default')
                body = {key: value for key, value in body.items() if key != 'proxies'}
                data = self._call('POST', '/sessions', body=body)
            elif isinstance(body['proxies'], list) and exc.status in (400, 422):
                # An unsupported geolocation country (400/422): fall back to Browserbase's default managed proxy.
                logger.warning('Browserbase refused the %s geolocation (%s): opening with default proxy',
                               geo, exc.status)
                body = {**body, 'proxies': True}
                try:
                    data = self._call('POST', '/sessions', body=body)
                except BrowserUnavailable as inner:
                    if inner.code != 'quota':
                        raise
                    logger.warning('Browserbase refused the default proxy (plan): opening without it')
                    body = {key: value for key, value in body.items() if key != 'proxies'}
                    data = self._call('POST', '/sessions', body=body)
            else:
                raise
        expires = parse_datetime(str(data.get('expiresAt') or ''))
        url = str(data.get('connectUrl') or '')
        if not data.get('id') or not url.startswith('wss://') or expires is None:
            if data.get('id'):
                self.close(str(data['id']))
            raise BrowserUnavailable('Browserbase returned an unusable session')
        return Session(id=str(data['id']), connect_url=url, expires_at=expires)

    def close(self, session_id):
        self._call('POST', f'/sessions/{session_id}', body={'status': 'REQUEST_RELEASE'}, ok=(200, 404, 409))

    def live_view(self, session_id, *, seconds):
        data = self._call('GET', f'/sessions/{session_id}/debug',
                          params={'expiresIn': max(MIN_SECONDS, min(int(seconds), MAX_SECONDS))})
        pages = data.get('pages') or []
        if not pages:
            raise BrowserUnavailable('Browserbase returned no page to show')
        url = str(pages[-1].get('debuggerFullscreenUrl') or '')
        if not url.startswith('https://'):
            raise BrowserUnavailable('Browserbase returned no live view')
        # The navigation bar stays: the person sees the real address where they type a password.
        return url, str(pages[-1].get('url') or ''), str(pages[-1].get('id') or '')
