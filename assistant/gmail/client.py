"""The few Google calls the pilot makes. Response bodies never reach an exception or a log."""
import json
from datetime import date, datetime, timedelta, timezone as tz
from zoneinfo import ZoneInfo

import requests

from . import config
from .errors import GmailError, GrantEnded

TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
API = 'https://gmail.googleapis.com/gmail/v1/users/me'
CALENDAR_API = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
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


class Calendar:
    """The person's own Google calendar, read when asked. Nothing from it is stored."""

    FIELDS = ('timeZone,nextPageToken,items(summary,status,eventType,start,end,organizer(self),'
              'attendees(self,responseStatus))')
    PAGE, MAX_PAGES = 250, 4

    def __init__(self, token):
        self._headers = {'Authorization': f'Bearer {token}'}

    def events(self, now, days, offset, limit=50) -> list:
        """[{title, day, starts_at, all_day}] for `days` days from today, on the calendar's own clock.

        `offset` (hours) is only the fallback when Google names no usable timezone.
        """
        # A day wider on each side: which day is "today" is known only once Google names the zone.
        params = {'timeMin': (now - timedelta(days=1)).isoformat(), 'singleEvents': 'true', 'orderBy': 'startTime',
                  'timeMax': (now + timedelta(days=days + 1)).isoformat(), 'maxResults': self.PAGE,
                  # Only the person's own entry among the guests: nobody else's, and no huge answers.
                  'maxAttendees': 1,
                  'fields': self.FIELDS}
        items, zone = [], None
        for _page in range(self.MAX_PAGES):
            data = _call('GET', CALENDAR_API, headers=self._headers, params=params)
            zone = zone or _zone(data.get('timeZone'))
            items.extend(item for item in data.get('items') or [] if isinstance(item, dict))
            if not data.get('nextPageToken'):
                break
            params = {**params, 'pageToken': data['nextPageToken']}
        zone = zone or tz(timedelta(hours=offset))
        first_day = now.astimezone(zone).date()
        last_day = first_day + timedelta(days=days - 1)
        found = []
        for item in items:
            if not _mine(item):
                continue
            begins, ends = item.get('start') or {}, item.get('end') or {}
            try:
                if begins.get('dateTime'):
                    moment = _moment(begins['dateTime']).astimezone(zone)
                    day, all_day = moment.date(), False
                    midnight = datetime(first_day.year, first_day.month, first_day.day, tzinfo=zone)
                    if day < first_day and _moment(ends.get('dateTime')) > midnight:
                        day = first_day  # began earlier and is still running
                else:
                    day, moment, all_day = date.fromisoformat(str(begins.get('date'))), None, True
                    if day < first_day < date.fromisoformat(str(ends.get('date'))):
                        day = first_day  # a longer all-day event that covers today
            except (TypeError, ValueError):
                continue
            if first_day <= day <= last_day:
                found.append({'title': str(item.get('summary') or ''), 'day': day, 'starts_at': moment,
                              'all_day': all_day})
        return found[:limit]


def _zone(name):
    try:
        return ZoneInfo(str(name)) if name else None
    except Exception:  # noqa: BLE001 - an unknown name: the fallback offset
        return None


def _moment(value) -> datetime:
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('no offset')
    return moment


def _mine(item) -> bool:
    """Made by the person, or an invitation they said yes or maybe to. Anyone can send an invitation."""
    if item.get('status') == 'cancelled':
        return False
    if item.get('eventType') not in (None, 'default'):
        return False  # birthdays, out of office, focus time, working location, and what Gmail made from a mail
    own = [guest for guest in item.get('attendees') or [] if isinstance(guest, dict) and guest.get('self')]
    if own:
        return all(guest.get('responseStatus') in ('accepted', 'tentative') for guest in own)
    # Not among the guests: theirs only if Google says they organize it. Anything else is left out.
    return bool((item.get('organizer') or {}).get('self'))
