class MailRefused(Exception):
    """A refusal with copy for the person."""

    def __init__(self, code, message):
        super().__init__(code)
        self.code, self.message = code, message


class GmailError(Exception):
    """A failed Google call. Carries a status, never a response body (it can quote mail)."""

    def __init__(self, status=0):
        super().__init__(f'Google request failed ({status})')
        self.status = status

    @property
    def definitive(self):
        """Google refused: nothing happened on its side."""
        return 400 <= self.status < 500 and self.status != 408


class GrantEnded(GmailError):
    """The refresh token no longer works (revoked, or the 7-day test grant ended)."""
