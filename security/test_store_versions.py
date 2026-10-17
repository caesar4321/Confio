from unittest import mock

from django.test import TestCase

from security import store_versions
from security.models import AppVersionPolicy


def lookup_response(payload):
    response = mock.Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def play_service(releases):
    service = mock.MagicMock()
    edits = service.edits.return_value
    edits.insert.return_value.execute.return_value = {'id': 'edit-1'}
    edits.tracks.return_value.get.return_value.execute.return_value = {
        'track': 'production', 'releases': releases}
    return service


class StoreVersionReadTests(TestCase):
    @mock.patch('security.store_versions.requests.get')
    def test_ios_reads_lookup_version(self, get):
        get.return_value = lookup_response({'resultCount': 1, 'results': [{'version': '5.2.3'}]})
        self.assertEqual(store_versions.ios_store_version(), '5.2.3')
        self.assertEqual(get.call_args.kwargs['params'], {'id': '6472662314'})

    @mock.patch('security.store_versions.requests.get')
    def test_ios_empty_lookup(self, get):
        get.return_value = lookup_response({'resultCount': 0, 'results': []})
        self.assertIsNone(store_versions.ios_store_version())

    def android(self, releases):
        service = play_service(releases)
        with mock.patch('security.store_versions._play_service', return_value=service):
            version = store_versions.android_store_version()
        edits = service.edits.return_value
        edits.tracks.return_value.get.assert_called_once_with(
            packageName='com.Confio.Confio', editId='edit-1', track='production')
        edits.delete.assert_called_once_with(packageName='com.Confio.Confio', editId='edit-1')
        return version

    def test_android_takes_completed_release_only(self):
        self.assertEqual(self.android([
            {'name': '169 (5.2.4)', 'status': 'inProgress', 'userFraction': 0.2, 'versionCodes': ['169']},
            {'name': '168 (5.2.3)', 'status': 'completed', 'versionCodes': ['168']},
        ]), '5.2.3')

    def test_android_staged_rollout_alone_is_no_version(self):
        self.assertIsNone(self.android([
            {'name': '169 (5.2.4)', 'status': 'inProgress', 'userFraction': 0.5},
            {'name': '5.2.5', 'status': 'halted'},
            {'name': '5.2.6', 'status': 'draft'},
        ]))

    def test_android_release_name_without_version_is_skipped(self):
        self.assertIsNone(self.android([{'name': 'Octubre', 'status': 'completed'}]))
        self.assertIsNone(self.android([{'name': '5.2.3 / 5.2.4', 'status': 'completed'}]))
        self.assertEqual(self.android([{'name': '5.2.3', 'status': 'completed'}]), '5.2.3')

    def test_android_edit_deleted_when_track_read_fails(self):
        service = play_service([])
        edits = service.edits.return_value
        edits.tracks.return_value.get.return_value.execute.side_effect = RuntimeError('403')
        with mock.patch('security.store_versions._play_service', return_value=service):
            with self.assertRaises(RuntimeError):
                store_versions.android_store_version()
        edits.delete.assert_called_once()


class RaiseLatestVersionTests(TestCase):
    def setUp(self):
        for platform, version in (('ios', '5.2.3'), ('android', '')):
            AppVersionPolicy.objects.update_or_create(
                platform=platform, defaults={'latest_version': version, 'message': 'Novedades'})

    def policy(self, platform):
        return AppVersionPolicy.objects.get(platform=platform)

    def test_raises(self):
        self.assertTrue(store_versions.raise_latest_version('ios', '5.2.10'))
        self.assertEqual(self.policy('ios').latest_version, '5.2.10')
        self.assertEqual(self.policy('ios').message, 'Novedades')

    def test_never_lowers_or_rewrites_equal(self):
        self.assertFalse(store_versions.raise_latest_version('ios', '5.2.2'))
        self.assertFalse(store_versions.raise_latest_version('ios', '5.2.3'))
        self.assertEqual(self.policy('ios').latest_version, '5.2.3')

    def test_fills_blank(self):
        self.assertTrue(store_versions.raise_latest_version('android', '5.2.3'))
        self.assertEqual(self.policy('android').latest_version, '5.2.3')

    def test_ignores_malformed_store_version(self):
        self.assertFalse(store_versions.raise_latest_version('ios', '6.0'))
        self.assertFalse(store_versions.raise_latest_version('ios', None))
        self.assertEqual(self.policy('ios').latest_version, '5.2.3')


class SyncStoreVersionsTests(TestCase):
    def setUp(self):
        for platform in ('ios', 'android'):
            AppVersionPolicy.objects.update_or_create(
                platform=platform, defaults={'latest_version': '5.2.1', 'message': ''})

    @mock.patch('security.store_versions._play_service', side_effect=RuntimeError('Play API disabled'))
    @mock.patch('security.store_versions.requests.get')
    def test_one_store_failing_does_not_stop_the_other(self, get, _service):
        get.return_value = lookup_response({'results': [{'version': '5.2.3'}]})
        with self.assertLogs('security.store_versions', 'WARNING'):
            changed = store_versions.sync_store_versions()
        self.assertEqual(changed, {'ios': True})
        self.assertEqual(AppVersionPolicy.objects.get(platform='ios').latest_version, '5.2.3')
        self.assertEqual(AppVersionPolicy.objects.get(platform='android').latest_version, '5.2.1')

    @mock.patch('security.store_versions._play_service')
    @mock.patch('security.store_versions.requests.get', side_effect=OSError('timeout'))
    def test_android_raised_while_ios_down(self, _get, service):
        service.return_value = play_service([{'name': '168 (5.2.3)', 'status': 'completed'}])
        with self.assertLogs('security.store_versions', 'WARNING'):
            changed = store_versions.sync_store_versions()
        self.assertEqual(changed, {'android': True})
        self.assertEqual(AppVersionPolicy.objects.get(platform='android').latest_version, '5.2.3')

    def test_task_is_scheduled(self):
        from config.celery import app
        from security import tasks
        entry = app.conf.beat_schedule['security-sync-store-versions']
        self.assertEqual(entry['task'], 'security.sync_store_versions')
        self.assertEqual(tasks.sync_store_versions.name, entry['task'])
