import base64
from django.test import SimpleTestCase
from payment_accounts.breb_location import _certificate_diagnostic


class CertificateDiagnosticTests(SimpleTestCase):
    def test_equal_bytes_with_different_padding(self):
        digest = base64.urlsafe_b64encode(bytes(range(32))).decode()
        self.assertEqual(_certificate_diagnostic([digest], [digest.rstrip('=')]), (1, 1, 1, True))

    def test_different_certificates(self):
        first = base64.urlsafe_b64encode(bytes(range(32))).decode()
        other = base64.urlsafe_b64encode(b'x' * 32).decode()
        self.assertEqual(_certificate_diagnostic([first], [other]), (1, 1, 1, False))

    def test_missing_malformed_and_wrong_length(self):
        self.assertEqual(_certificate_diagnostic([], []), (0, 0, 0, False))
        self.assertEqual(_certificate_diagnostic(['!' * 43, None, 'aGVsbG8='], []), (3, 0, 0, False))
        self.assertEqual(_certificate_diagnostic(None, None), (-1, 0, 0, False))
