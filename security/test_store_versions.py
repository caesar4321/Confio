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

    def android(self, published, track=()):
        """published: [(name, codes)] as releases.list reports PUBLISHED;
        track: the edits production track's releases."""
        service = play_service(list(track))
        with mock.patch('security.store_versions._play_service', return_value=service), \
                mock.patch('security.store_versions.published_releases', return_value=published):
            version = store_versions.android_store_version()
        edits = service.edits.return_value
        edits.tracks.return_value.get.assert_called_once_with(
            packageName='com.Confio.Confio', editId='edit-1', track='production')
        edits.delete.assert_called_once_with(packageName='com.Confio.Confio', editId='edit-1')
        return version

    def test_android_release_in_review_is_not_live(self):
        # Managed publishing off: a submitted full rollout reads 'completed'
        # on the track while Play still reviews it, and the live release
        # drops off the track (5.2.5, 2026-10-17). Nothing qualifies, so the
        # policy stays where it was.
        self.assertIsNone(self.android(
            [('169 (5.2.4)', {'169'})],
            track=[{'name': '170 (5.2.5)', 'status': 'completed', 'versionCodes': ['170']}]))

    def test_android_published_and_full_rollout(self):
        self.assertEqual(self.android(
            [('169 (5.2.4)', {'169'})],
            track=[{'name': '169 (5.2.4)', 'status': 'completed', 'versionCodes': ['169']}]), '5.2.4')

    def test_android_staged_or_halted_rollout_is_not_live(self):
        self.assertEqual(self.android(
            [('169 (5.2.4)', {'169'}), ('168 (5.2.3)', {'168'})],
            track=[{'name': '169 (5.2.4)', 'status': 'inProgress', 'userFraction': 0.2, 'versionCodes': ['169']},
                   {'name': '168 (5.2.3)', 'status': 'completed', 'versionCodes': ['168']}]), '5.2.3')
        self.assertIsNone(self.android(
            [('169 (5.2.4)', {'169'})],
            track=[{'name': '169 (5.2.4)', 'status': 'halted', 'versionCodes': ['169']}]))

    def test_android_published_but_off_the_track_is_not_live(self):
        # Published can mean a staged rollout that a newer submission pushed
        # off the track: no positive evidence of 100%, so not live.
        self.assertIsNone(self.android([('169 (5.2.4)', {'169'})]))

    def test_android_release_name_without_version_is_skipped(self):
        track = [{'name': 'x', 'status': 'completed', 'versionCodes': ['168']}]
        self.assertIsNone(self.android([('Octubre', {'168'})], track=track))
        self.assertIsNone(self.android([('5.2.3 / 5.2.4', {'168'})], track=track))
        self.assertIsNone(self.android([('5.2.3', set())], track=track))
        self.assertEqual(self.android([('5.2.3', {'168'})], track=track), '5.2.3')

    def test_published_releases_reads_lifecycle_state(self):
        response = mock.Mock()
        response.json.return_value = {'releases': [
            {'releaseName': '170 (5.2.5)', 'activeArtifacts': [{'versionCode': 170}],
             'releaseLifecycleState': 'RELEASE_LIFECYCLE_STATE_IN_REVIEW'},
            {'releaseName': '169 (5.2.4)', 'activeArtifacts': [{'versionCode': 169}],
             'releaseLifecycleState': 'RELEASE_LIFECYCLE_STATE_PUBLISHED'},
        ]}
        with mock.patch('security.store_versions._play_credentials'), \
                mock.patch('google.auth.transport.requests.AuthorizedSession') as session:
            session.return_value.get.return_value = response
            self.assertEqual(store_versions.published_releases(), [('169 (5.2.4)', {'169'})])

    def test_android_edit_deleted_when_track_read_fails(self):
        service = play_service([])
        edits = service.edits.return_value
        edits.tracks.return_value.get.return_value.execute.side_effect = RuntimeError('403')
        with mock.patch('security.store_versions._play_service', return_value=service), \
                mock.patch('security.store_versions.published_releases', return_value=[]):
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

    @mock.patch('security.store_versions.published_releases', side_effect=RuntimeError('Play API disabled'))
    @mock.patch('security.store_versions.requests.get')
    def test_one_store_failing_does_not_stop_the_other(self, get, _service):
        get.return_value = lookup_response({'results': [{'version': '5.2.3'}]})
        with self.assertLogs('security.store_versions', 'WARNING'):
            changed = store_versions.sync_store_versions()
        self.assertEqual(changed, {'ios': True})
        self.assertEqual(AppVersionPolicy.objects.get(platform='ios').latest_version, '5.2.3')
        self.assertEqual(AppVersionPolicy.objects.get(platform='android').latest_version, '5.2.1')

    @mock.patch('security.store_versions.published_releases', return_value=[('168 (5.2.3)', {'168'})])
    @mock.patch('security.store_versions._play_service')
    @mock.patch('security.store_versions.requests.get', side_effect=OSError('timeout'))
    def test_android_raised_while_ios_down(self, _get, service, _published):
        service.return_value = play_service(
            [{'name': '168 (5.2.3)', 'status': 'completed', 'versionCodes': ['168']}])
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
