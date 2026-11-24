"""Cloud-browser vendors behind one small interface.

Nothing outside this package knows a vendor. A vendor must be able to open an
isolated browser we reach over CDP, keep a per-person, per-site profile, hand
out a live view the person can type in, and close both.
"""
from dataclasses import dataclass
from datetime import datetime

from .. import conf


class BrowserUnavailable(Exception):
    """The vendor could not do it. `code`: quota | busy | unavailable."""

    def __init__(self, message, code='unavailable'):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Session:
    id: str
    connect_url: str  # controls a browser that may be signed in: never logged, never shown
    expires_at: datetime


class BrowserProvider:
    name = ''

    def create_profile(self) -> str:
        raise NotImplementedError

    def delete_profile(self, profile_id: str) -> None:
        raise NotImplementedError

    def open(self, *, profile_id: str, country: str, seconds: int, viewport: dict | None = None,
             region: str | None = None, solve_captchas: bool = True) -> Session:
        """`viewport` and `region` default to the shopping agent's (a phone screen, the vendor's region)."""
        raise NotImplementedError

    def close(self, session_id: str) -> None:
        raise NotImplementedError

    def live_view(self, session_id: str, *, seconds: int) -> tuple[str, str, str]:
        """(screen URL, the address that screen is showing, the CDP target id of that tab)."""
        raise NotImplementedError


def provider(name=None) -> BrowserProvider:
    name = name or conf.get('AGENT_TASKS_BROWSER')
    if name == 'browserbase':
        from .browserbase import Browserbase
        return Browserbase()
    raise BrowserUnavailable(f'unknown browser provider {name}')
