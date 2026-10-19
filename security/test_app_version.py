from django.core.exceptions import ValidationError
import json

from django.test import RequestFactory, TestCase
from django.urls import resolve

from security.app_version import app_version, UPDATE_AVAILABLE, UPDATE_REQUIRED, CURRENT
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
        self.assertEqual(body['minimumVersion'], '')
        self.assertEqual(body['latestVersion'], '5.2.3')

    def test_blank_minimum_never_blocks(self):
        self.assertEqual(self.status(platform='ios', version='1.0.0'), UPDATE_AVAILABLE)

    def test_below_minimum_is_required(self):
        AppVersionPolicy.objects.filter(platform='ios').update(minimum_version='5.2.0')
        self.assertEqual(self.status(platform='ios', version='5.1.9'), UPDATE_REQUIRED)
        self.assertEqual(self.status(platform='ios', version='5.2.0'), UPDATE_AVAILABLE)
        self.assertEqual(self.status(platform='ios', version='5.2.3'), CURRENT)
        body = json.loads(self.get({'platform': 'ios', 'version': '5.0.0'}).content)
        self.assertEqual(body['minimumVersion'], '5.2.0')

    def test_unreadable_version_is_never_blocked(self):
        AppVersionPolicy.objects.filter(platform='ios').update(minimum_version='5.2.0')
        self.assertEqual(self.status(platform='ios', version='garbage'), CURRENT)
        self.assertEqual(self.status(platform='ios'), CURRENT)

    def test_minimum_is_per_platform(self):
        AppVersionPolicy.objects.filter(platform='ios').update(minimum_version='5.2.3')
        self.assertEqual(self.status(platform='android', version='1.0.0'), CURRENT)

    def test_minimum_cannot_exceed_latest(self):
        with self.assertRaises(ValidationError):
            AppVersionPolicy(platform='ios', latest_version='5.2.3', minimum_version='5.2.4').clean()
        with self.assertRaises(ValidationError):
            AppVersionPolicy(platform='ios', latest_version='', minimum_version='5.2.0').clean()
        with self.assertRaises(ValidationError):
            AppVersionPolicy(platform='ios', latest_version='5.2.3', minimum_version='5.2').clean()
        AppVersionPolicy(platform='ios', latest_version='5.2.3', minimum_version='5.2.3').clean()

    def test_unknown_platform_is_rejected(self):
        self.assertEqual(self.get({'platform': 'web'}).status_code, 400)

    def test_malformed_version_is_invalid(self):
        with self.assertRaises(ValidationError):
            AppVersionPolicy(platform='ios', latest_version='5.2').clean()
