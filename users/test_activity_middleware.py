from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from graphql import parse
from graphql.pyutils import Path

from users.graphql_middleware import ActivityTrackingMiddleware

User = get_user_model()

ROOT = Path(None, 'ping', 'Mutation')
NESTED = ROOT.add_key('success', 'PingPayload')


def _info(source, user, path=ROOT):
    operation = parse(source).definitions[0]
    return mock.Mock(operation=operation, path=path, context=mock.Mock(user=user))


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                       'LOCATION': 'activity-middleware-tests'}})
class ActivityTrackingMiddlewareTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.joined = timezone.now() - timedelta(days=2)
        self.user = User.objects.create_user(username='activity_mw', firebase_uid='activity_mw')
        User.objects.filter(id=self.user.id).update(last_activity_at=self.joined)

    def _run(self, source, path=ROOT):
        info = _info(source, self.user, path)
        result = ActivityTrackingMiddleware().resolve(lambda root, info, **kw: 'ok', None, info)
        self.assertEqual(result, 'ok')
        self.user.refresh_from_db()

    def test_authenticated_mutation_touches_last_activity(self):
        self._run('mutation { ping }')
        self.assertGreater(self.user.last_activity_at, self.joined + timedelta(days=1))

    def test_query_does_not_touch_last_activity(self):
        self._run('query { ping }')
        self.assertEqual(self.user.last_activity_at, self.joined)

    def test_nested_mutation_field_does_not_touch(self):
        with mock.patch('users.graphql_middleware.touch_last_activity') as touch:
            self._run('mutation { ping { success } }', path=NESTED)
        touch.assert_not_called()

    def test_anonymous_user_is_ignored(self):
        anon = mock.Mock(is_authenticated=False)
        with mock.patch('users.graphql_middleware.touch_last_activity') as touch:
            ActivityTrackingMiddleware().resolve(lambda root, info, **kw: 'ok', None,
                                                 _info('mutation { ping }', anon))
        touch.assert_not_called()
