"""Wallet recovery diagnostics: what a device reports when sign-in recovery fails.

User 2785 (2026-10-14) retried sign-in eight times in 35 minutes and left no
server-side evidence beyond a repeated login, because recovery runs entirely
on the device. These tests pin what the server accepts: shapes only, capped,
and never file contents.
"""
import json
import threading
import time
from types import SimpleNamespace
from unittest import mock

from django.db import connections, transaction
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase

from django.views.decorators.csrf import csrf_exempt

from config.urls import LoggingGraphQLView
from users.models import User, WalletRecoveryDiagnostic
from users.schema import ReportWalletRecoveryDiagnostic


def info_for(user):
    return SimpleNamespace(context=SimpleNamespace(user=user))


class ReportWalletRecoveryDiagnosticTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='diag-user', email='diag@example.com')

    def test_requires_authentication(self):
        anon = SimpleNamespace(is_authenticated=False)
        result = ReportWalletRecoveryDiagnostic.mutate(None, info_for(anon), code='unreadable')
        self.assertFalse(result.success)
        self.assertEqual(WalletRecoveryDiagnostic.objects.count(), 0)

    def test_rejects_an_unknown_code(self):
        result = ReportWalletRecoveryDiagnostic.mutate(None, info_for(self.user), code='whatever')
        self.assertFalse(result.success)
        self.assertEqual(WalletRecoveryDiagnostic.objects.count(), 0)

    def test_stores_the_shape_and_never_the_contents(self):
        result = ReportWalletRecoveryDiagnostic.mutate(
            None, info_for(self.user), code='unreadable',
            found_any=True, found_decryptable=False,
            inventory=json.dumps([{
                'shape': 'payload', 'format': 'v2_envelope', 'outcome': 'auth_failed',
                'bytes': 512, 'trashed': False,
                # Anything a client should never send is dropped here.
                'ciphertext': 'U2FsdGVkX1+secretpayload',
                'name': 'confio_wallet_v2_abc.enc',
            }]),
        )
        self.assertTrue(result.success, result.error)
        row = WalletRecoveryDiagnostic.objects.get()
        self.assertEqual(row.inventory, [{
            'shape': 'payload', 'format': 'v2_envelope',
            'outcome': 'auth_failed', 'bytes': 512, 'trashed': False,
        }])
        stored = str(row.inventory)
        self.assertNotIn('U2FsdGVkX1', stored)
        self.assertNotIn('confio_wallet_v2_abc', stored)
        self.assertEqual(row.candidate_count, 1)
        self.assertTrue(row.found_any)
        self.assertFalse(row.found_decryptable)

    def test_unknown_values_degrade_instead_of_being_stored(self):
        ReportWalletRecoveryDiagnostic.mutate(
            None, info_for(self.user), code='mismatch',
            inventory=json.dumps([{'shape': 'evil', 'format': 'evil', 'outcome': 'evil', 'bytes': -5}]),
        )
        entry = WalletRecoveryDiagnostic.objects.get().inventory[0]
        self.assertEqual(entry['shape'], 'other')
        self.assertEqual(entry['format'], 'unknown')
        self.assertEqual(entry['outcome'], 'unknown')
        self.assertIsNone(entry['bytes'])

    def test_caps_entries_and_keeps_history_bounded(self):
        ReportWalletRecoveryDiagnostic.mutate(
            None, info_for(self.user), code='unreadable',
            inventory=json.dumps([{'shape': 'payload'} for _ in range(60)]),
        )
        self.assertEqual(WalletRecoveryDiagnostic.objects.get().candidate_count, 25)
        # A locked-out user retries in a loop. The hourly limit stops most of
        # that; pruning is the backstop for whatever gets through over time,
        # so raise the limit here to exercise it.
        with mock.patch.object(ReportWalletRecoveryDiagnostic, 'RATE_LIMIT_PER_HOUR', 1000):
            for _ in range(25):
                ReportWalletRecoveryDiagnostic.mutate(None, info_for(self.user), code='unreadable')
        self.assertEqual(WalletRecoveryDiagnostic.objects.filter(user=self.user).count(), 20)

    def test_a_bad_inventory_type_is_ignored_not_fatal(self):
        result = ReportWalletRecoveryDiagnostic.mutate(
            None, info_for(self.user), code='drive_access', inventory=json.dumps({'not': 'a list'}),
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(WalletRecoveryDiagnostic.objects.get().inventory, [])


class DiagnosticHardeningTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='diag-hard', email='hard@example.com')

    def test_nested_json_types_do_not_discard_the_report(self):
        """A list where a string belongs used to raise and lose everything."""
        result = ReportWalletRecoveryDiagnostic.mutate(
            None, info_for(self.user), code='unreadable',
            inventory=json.dumps([
                {'shape': [], 'format': {}, 'outcome': [], 'bytes': True},
                {'shape': 'payload', 'format': 'v2_envelope', 'outcome': 'auth_failed', 'bytes': 10},
            ]),
        )
        self.assertTrue(result.success, result.error)
        entries = WalletRecoveryDiagnostic.objects.get().inventory
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0], {
            'shape': 'other', 'format': 'unknown', 'outcome': 'unknown',
            'bytes': None, 'trashed': False,
        })
        self.assertEqual(entries[1]['outcome'], 'auth_failed')

    def test_rejects_an_oversized_inventory_before_parsing_it(self):
        result = ReportWalletRecoveryDiagnostic.mutate(
            None, info_for(self.user), code='unreadable', inventory='x' * 9000,
        )
        self.assertFalse(result.success)
        self.assertEqual(WalletRecoveryDiagnostic.objects.count(), 0)

    def test_rate_limits_a_device_stuck_in_a_retry_loop(self):
        # Admission is decided in the database, so this holds regardless of
        # which cache (if any) a worker happens to have.
        accepted = 0
        for _ in range(20):
            if ReportWalletRecoveryDiagnostic.mutate(
                None, info_for(self.user), code='unreadable',
            ).success:
                accepted += 1
        self.assertEqual(accepted, ReportWalletRecoveryDiagnostic.RATE_LIMIT_PER_HOUR)


class ConcurrentAdmissionTest(TransactionTestCase):
    """Two workers must not both take the last slot.

    Sequential tests pass with or without the row lock, and racing two
    threads from a barrier does not prove anything either: the first worker
    can finish its whole admission before the second even counts, so the
    unlocked resolver still goes green often enough to be useless. So this
    test holds the user row itself and takes the last slot while a real
    second connection is in flight.

    With the lock, the contender cannot count until we release, so it sees a
    full hour and refuses. Without it, the contender counts the stale total
    first and writes the thirteenth row. The ordering comes from the
    database, not from a sleep.
    """

    @staticmethod
    def _backend_pid():
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()')
            return cursor.fetchone()[0]

    @classmethod
    def _wait_until_blocked_by_us(cls, contender_pid, timeout=30):
        """Return once THAT backend is waiting on a lock THIS one holds.

        Not "some backend is blocked": unrelated contention elsewhere in the
        database would satisfy that, let the main thread take the last slot
        early, and hand an unlocked resolver a false pass.
        """
        mine = cls._backend_pid()
        deadline = time.time() + timeout
        with connections['default'].cursor() as cursor:
            while time.time() < deadline:
                cursor.execute('SELECT pg_blocking_pids(%s)', [contender_pid])
                if mine in (cursor.fetchone()[0] or []):
                    return True
                time.sleep(0.02)
        return False

    def test_admission_cannot_read_while_the_row_is_held(self):
        user = User.objects.create(username='diag-race', email='race@example.com')
        limit = ReportWalletRecoveryDiagnostic.RATE_LIMIT_PER_HOUR
        for _ in range(limit - 1):
            WalletRecoveryDiagnostic.objects.create(user=user, code='unreadable')

        started = threading.Event()
        results = []
        contender_pid = []

        def contender():
            try:
                # Pay for this thread's connection BEFORE the race: setup is
                # not admission.
                connections['default'].ensure_connection()
                contender_pid.append(self._backend_pid())
                started.set()
                results.append(
                    ReportWalletRecoveryDiagnostic.mutate(
                        None, info_for(user), code='unreadable',
                    ).success
                )
            finally:
                started.set()
                connections.close_all()

        thread = threading.Thread(target=contender)
        with transaction.atomic():
            # Exactly what the resolver does first.
            User.objects.select_for_update().filter(pk=user.pk).first()
            thread.start()
            self.assertTrue(started.wait(30), 'contender never opened a connection')
            self.assertTrue(contender_pid, 'contender never reported its backend')
            # The contender is now parked on the row we hold: on its own
            # SELECT ... FOR UPDATE if it takes the lock, on the foreign key
            # of its INSERT if it does not. Either way it has gone as far as
            # it can without us, which is the moment to take the last slot.
            self.assertTrue(
                self._wait_until_blocked_by_us(contender_pid[0]),
                'contender never contended for the row this test holds',
            )
            WalletRecoveryDiagnostic.objects.create(user=user, code='unreadable')

        thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        self.assertEqual(
            results, [False],
            'the contender decided on a count it took before the last slot was filled',
        )
        self.assertEqual(WalletRecoveryDiagnostic.objects.filter(user=user).count(), limit)


class UrlCarriedOperationTest(SimpleTestCase):
    """A GraphQL operation in the URL is refused before it is logged.

    Graphene accepts one there, and nothing downstream of the request line
    can unsee it: nginx's access log, its error log when the upstream is
    down, the Referer the browser sends onward. Our clients always POST a
    body, so the only sender is one trying to get text into those logs.

    Driven straight at the view, so this pins the view's own rule rather
    than whatever the middleware stack happens to do first.
    """

    def setUp(self):
        self.factory = RequestFactory()
        # Matches the URLconf: csrf_exempt wraps the view there too.
        self.view = csrf_exempt(LoggingGraphQLView.as_view(graphiql=True))

    def _post(self, path, body='{}'):
        request = self.factory.post(path, data=body, content_type='application/json')
        request.user = SimpleNamespace(is_authenticated=False)
        # CSRF_USE_SESSIONS: graphene's view asks for a CSRF cookie, and a
        # bare RequestFactory request has no session to hold one.
        request.session = {}
        return self.view(request)

    # A VALID operation in both cases: a malformed one would be refused by
    # Graphene itself, and the test would pass with the guard removed.
    URL_QUERY = 'query%20SENTINEL%20%7B%20__typename%20%7D'
    URL_VARIABLES = '%7B%22inventory%22%3A%20%22SENTINEL%22%7D'

    def test_url_carried_operation_is_refused(self):
        with self.settings(DEBUG=False):
            response = self._post(f'/graphql/?query={self.URL_QUERY}')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'request body', response.content)

    def test_url_carried_variables_are_refused_too(self):
        # A perfectly ordinary body; the arguments ride in the URL beside it.
        with self.settings(DEBUG=False):
            response = self._post(
                f'/graphql/?variables={self.URL_VARIABLES}',
                json.dumps({'query': '{ __typename }'}),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'request body', response.content)

    def test_development_keeps_graphiql_working(self):
        with self.settings(DEBUG=True):
            response = self._post(f'/graphql/?query={self.URL_QUERY}')
        self.assertNotEqual(response.status_code, 400)

    def test_an_ordinary_body_request_still_reaches_graphene(self):
        with self.settings(DEBUG=False):
            response = self._post('/graphql/', json.dumps({'query': '{ __typename }'}))
        self.assertNotEqual(response.status_code, 400)
