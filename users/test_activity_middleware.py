from datetime import date, datetime, timedelta, timezone as dt_tz
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from graphql import parse
from graphql.pyutils import Path

from users.activity_tracking import activity_day, record_activity_day, touch_last_activity
from users.graphql_middleware import ActivityTrackingMiddleware
from users.models_analytics import UserActivityDay
from users.utils import touch_user_activity

User = get_user_model()

ROOT = Path(None, 'ping', 'Mutation')
NESTED = ROOT.add_key('success', 'PingPayload')
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'activity-tracking-tests'}}


def _info(source, user, path=ROOT):
    operation = parse(source).definitions[0]
    return mock.Mock(operation=operation, path=path, context=mock.Mock(user=user))


@override_settings(CACHES=LOCMEM)
class ActivityTrackingMiddlewareTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.joined = timezone.now() - timedelta(days=2)
        self.user = User.objects.create_user(username='activity_mw', firebase_uid='activity_mw')
        User.objects.filter(id=self.user.id).update(last_activity_at=self.joined)

    def _run(self, source, path=ROOT, user=None):
        info = _info(source, user or self.user, path)
        result = ActivityTrackingMiddleware().resolve(lambda root, info, **kw: 'ok', None, info)
        self.assertEqual(result, 'ok')
        self.user.refresh_from_db()

    def test_authenticated_mutation_touches_last_activity(self):
        self._run('mutation { ping }')
        self.assertGreater(self.user.last_activity_at, self.joined + timedelta(days=1))

    def test_authenticated_query_touches_last_activity(self):
        self._run('query { ping }')
        self.assertGreater(self.user.last_activity_at, self.joined + timedelta(days=1))
        self.assertTrue(UserActivityDay.objects.filter(user=self.user, day=activity_day(timezone.now())).exists())

    def test_subscription_does_not_touch(self):
        with mock.patch('users.graphql_middleware.touch_last_activity') as touch:
            self._run('subscription { ping }')
        touch.assert_not_called()

    def test_nested_field_does_not_touch(self):
        with mock.patch('users.graphql_middleware.touch_last_activity') as touch:
            self._run('mutation { ping { success } }', path=NESTED)
        touch.assert_not_called()

    def test_several_root_fields_touch_once_per_request(self):
        info = _info('query { a b }', self.user)
        with mock.patch('users.graphql_middleware.touch_last_activity') as touch:
            for name in ('a', 'b'):
                info.path = Path(None, name, 'Query')
                ActivityTrackingMiddleware().resolve(lambda root, info, **kw: 'ok', None, info)
        touch.assert_called_once()

    def test_anonymous_user_is_ignored(self):
        with mock.patch('users.graphql_middleware.touch_last_activity') as touch:
            self._run('query { ping }', user=mock.Mock(is_authenticated=False))
        touch.assert_not_called()


@override_settings(CACHES=LOCMEM)
class UserActivityDayTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='activity_day', firebase_uid='activity_day')

    def test_day_is_la_paz_calendar_day(self):
        # 02:00 UTC on the 30th is still 22:00 on the 29th in Bolivia.
        self.assertEqual(activity_day(datetime(2026, 10, 30, 2, tzinfo=dt_tz.utc)), date(2026, 10, 29))
        self.assertEqual(activity_day(datetime(2026, 10, 30, 4, tzinfo=dt_tz.utc)), date(2026, 10, 30))

    def test_one_row_per_day_keeping_first_visit(self):
        first = datetime(2026, 10, 29, 13, tzinfo=dt_tz.utc)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(record_activity_day(self.user.id, first))
        self.assertFalse(record_activity_day(self.user.id, first + timedelta(hours=3)))
        cache.clear()  # another worker, or the cache expired: the DB still dedupes
        record_activity_day(self.user.id, first + timedelta(hours=5))
        record_activity_day(self.user.id, first + timedelta(days=1))
        rows = list(UserActivityDay.objects.filter(user=self.user).order_by('day').values_list('day', 'first_seen_at'))
        self.assertEqual(rows, [(date(2026, 10, 29), first), (date(2026, 10, 30), first + timedelta(days=1))])

    def test_touch_paths_record_the_day(self):
        touch_last_activity(self.user.id)
        other = User.objects.create_user(username='activity_day_signal', firebase_uid='activity_day_signal')
        touch_user_activity(other.id)
        today = activity_day(timezone.now())
        self.assertEqual(UserActivityDay.objects.filter(day=today, user__in=[self.user, other]).count(), 2)

    def test_failed_insert_neither_raises_nor_poisons_the_transaction_and_retries(self):
        ts = timezone.now()

        def failing_sql(*args, **kwargs):
            # A real failing statement, so PostgreSQL aborts the transaction.
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1/0')

        with mock.patch.object(UserActivityDay.objects, 'bulk_create', side_effect=failing_sql):
            with transaction.atomic():
                self.assertFalse(record_activity_day(self.user.id, ts))
                self.assertTrue(User.objects.filter(id=self.user.id).exists())
        self.assertTrue(record_activity_day(self.user.id, ts))
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_rolled_back_caller_does_not_block_the_day(self):
        ts = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    record_activity_day(self.user.id, ts)
                    raise DatabaseError('caller failed')
            except DatabaseError:
                pass
        self.assertFalse(UserActivityDay.objects.filter(user=self.user).exists())
        self.assertTrue(record_activity_day(self.user.id, ts))
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_midnight_inside_the_cooldown_still_records_the_new_day(self):
        before = datetime(2026, 10, 30, 3, 59, tzinfo=dt_tz.utc)  # 23:59 in La Paz
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(touch_last_activity(self.user.id, ts=before))
            self.assertFalse(touch_last_activity(self.user.id, ts=before + timedelta(minutes=2)))
        days = list(UserActivityDay.objects.filter(user=self.user).order_by('day').values_list('day', flat=True))
        self.assertEqual(days, [date(2026, 10, 29), date(2026, 10, 30)])

    def test_failed_timestamp_write_frees_the_cooldown(self):
        with mock.patch('users.models.User.objects.filter', side_effect=DatabaseError('down')):
            self.assertFalse(touch_last_activity(self.user.id))
        self.assertTrue(touch_last_activity(self.user.id))
