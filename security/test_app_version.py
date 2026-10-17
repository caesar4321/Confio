from django.core.exceptions import ValidationError
import json

from django.test import RequestFactory, TestCase
from django.urls import resolve

from security.app_version import app_version, UPDATE_AVAILABLE, CURRENT
from security.models import AppVersionPolicy


class AppVersionEndpointTests(TestCase):
    def setUp(self):
        AppVersionPolicy.objects.update_or_create(
            platform='ios', defaults={'latest_version': '5.2.3', 'message': ''})
        AppVersionPolicy.objects.update_or_create(
            platform='android', defaults={'latest_version': '', 'message': ''})

    # The view is called directly: the test client's request signals close
    # the --keepdb connection under this project's settings.
    def get(self, params=None, **headers):
        return app_version(RequestFactory().get('/api/app-version/', params or {}, **headers))

    def status(self, **params):
        response = self.get(params)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)['status']

    def test_route(self):
        self.assertIs(resolve('/api/app-version/').func, app_version)

    def test_older_than_latest_is_available(self):
        self.assertEqual(self.status(platform='ios', version='4.0.0'), UPDATE_AVAILABLE)
        self.assertEqual(self.status(platform='ios', version='5.2.2'), UPDATE_AVAILABLE)

    def test_latest_or_newer_is_current(self):
        self.assertEqual(self.status(platform='ios', version='5.2.3'), CURRENT)
        self.assertEqual(self.status(platform='ios', version='5.10.0'), CURRENT)

    def test_blank_policy_never_prompts(self):
        self.assertEqual(self.status(platform='android', version='1.0.0'), CURRENT)

    def test_unreadable_version_is_never_forced(self):
        self.assertEqual(self.status(platform='ios', version='garbage'), CURRENT)
        self.assertEqual(self.status(platform='ios'), CURRENT)

    def test_reads_mobile_headers(self):
        body = json.loads(self.get(HTTP_X_CONFIO_PLATFORM='ios', HTTP_X_CONFIO_VERSION='4.9.0').content)
        self.assertEqual(body['status'], UPDATE_AVAILABLE)
        self.assertNotIn('minimumVersion', body)
        self.assertEqual(body['latestVersion'], '5.2.3')

    def test_unknown_platform_is_rejected(self):
        self.assertEqual(self.get({'platform': 'web'}).status_code, 400)

    def test_malformed_version_is_invalid(self):
        with self.assertRaises(ValidationError):
            AppVersionPolicy(platform='ios', latest_version='5.2').clean()
