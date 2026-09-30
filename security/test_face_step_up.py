import os
from io import StringIO
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from security import face_step_up as fsu
from security.models import FaceCheck, FaceReference, IdentityVerification

SIGNED_URL = 'https://didit.example/selfie.jpg?X-Amz-Signature=secret'


def _decision(url=SIGNED_URL):
    return {'liveness_checks': [{'reference_image': url}]}


def _download(status=200, body=b'kyc-selfie', content_type='image/jpeg'):
    return SimpleNamespace(status_code=status, content=body, headers={'Content-Type': content_type})


class FaceRegionTests(SimpleTestCase):
    def test_runtime_and_both_iam_policies_use_supported_ireland_region(self):
        from scripts.security import setup_face_liveness_iam as iam
        self.assertEqual(fsu.REKOGNITION_REGION, 'eu-west-1')
        self.assertEqual(iam.REKOGNITION_REGION, fsu.REKOGNITION_REGION)
        for policy in (iam.client_permissions_policy(),
                       iam.backend_policy('arn:aws:iam::123456789012:role/client', 'test-bucket')):
            self.assertEqual(policy['Statement'][0]['Condition']['StringEquals']
                             ['aws:RequestedRegion'], 'eu-west-1')
        with mock.patch.object(fsu, '_setting', side_effect=lambda name, default: default), \
                mock.patch.object(fsu.boto3, 'client') as client:
            fsu._rekognition()
        client.assert_called_once_with('rekognition', region_name='eu-west-1')


class FaceStepUpTests(TestCase):
    def test_backfill_includes_additional_personal_documents(self):
        from django.core.management import call_command
        self.verification.is_additional_document = True
        self.verification.risk_factors = {'didit': {'session_id': 'additional-session'}}
        self.verification.save()
        module = 'security.management.commands.backfill_face_references'
        with mock.patch(f'{module}._didit_request', return_value=_decision()) as fetch, \
                mock.patch(f'{module}.store_face_reference_from_didit', return_value=True) as store, \
                mock.patch(f'{module}.time.sleep'):
            call_command('backfill_face_references', dry_run=True, stdout=StringIO())
            fetch.assert_not_called()
            call_command('backfill_face_references', stdout=StringIO())
            fetch.assert_called_once_with('GET', '/v3/session/additional-session/decision/')
            self.assertEqual(store.call_args.args[0].pk, self.verification.pk)

    def test_backfill_reports_missing_sessions_and_excludes_business(self):
        from django.core.management import call_command
        out = StringIO()
        call_command('backfill_face_references', dry_run=True, stdout=out)
        self.assertIn('1 verified users without a reference or usable Didit session', out.getvalue())
        self.verification.risk_factors = {'account_type': 'business', 'didit': {'session_id': 'business'}}
        self.verification.save()
        out = StringIO()
        call_command('backfill_face_references', dry_run=True, stdout=out)
        self.assertIn('0 verified users without a face reference', out.getvalue())

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_app_unlock_never_authorizes_money_movement(self):
        FaceCheck.objects.create(user=self.user, purpose='app_unlock', status='passed',
            liveness_session_id='unlock-only', completed_at=timezone.now())
        self.assertEqual(fsu.missing_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)
        self.assertEqual(fsu.missing_face_step_up(self.user, 'on_ramp'), fsu.FACE_STEP_UP_MESSAGE)

    @override_settings(FACE_STEP_UP_ENABLED=True, FACE_MIN_APP_VERSION='5.1.5', FACE_MIN_ANDROID_BUILD=157)
    def test_supported_client_headers_cannot_replace_rekognition_approval(self):
        from security.face_client import FaceClientCompatibilityMiddleware
        mutation_type = object()
        info = SimpleNamespace(
            field_name='submitBscSend', parent_type=mutation_type,
            schema=SimpleNamespace(mutation_type=mutation_type),
            context=SimpleNamespace(user=self.user, headers={
                'X-Confio-Platform': 'android', 'X-Confio-Version': '5.1.5',
                'X-Confio-Build': '157', 'X-Confio-Face-Capable': '1',
                'X-Confio-Face-Passed': 'true',
            }))
        result = FaceClientCompatibilityMiddleware().resolve(
            lambda root, info: fsu.require_face_step_up(self.user, 'withdrawal'), None, info)
        self.assertEqual(result, fsu.FACE_STEP_UP_MESSAGE)

    def setUp(self):
        self.user = get_user_model().objects.create(
            username='face-user', email='face@example.com', firebase_uid='face-user-uid')
        self.other = get_user_model().objects.create(
            username='face-other', email='other@example.com', firebase_uid='face-other-uid')
        self.verification = self._verification(verified_at=timezone.now())
        self.s3 = mock.Mock()
        self.s3.get_object.return_value = {'Body': SimpleNamespace(read=lambda: b'kyc-selfie')}
        self.rek = mock.Mock()
        self.rek.create_face_liveness_session.return_value = {'SessionId': 'sess-1'}
        patches = [
            mock.patch.object(fsu, '_s3', return_value=self.s3),
            mock.patch.object(fsu, '_rekognition', return_value=self.rek),
            mock.patch.object(fsu, '_resolve_bucket', return_value='confio-verification'),
            mock.patch.object(fsu, '_client_credentials', return_value={
                'access_key_id': 'AK', 'secret_access_key': 'SK', 'session_token': 'ST',
                'expiration': 'soon', 'region': 'eu-west-1'}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _verification(self, verified_at, document_number='1065000001'):
        return IdentityVerification.all_documents.create(
            user=self.user, verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth='1994-07-21', verified_nationality='COL', verified_address='-',
            verified_city='-', verified_state='-', verified_country='COL', document_type='national_id',
            document_number=document_number, document_issuing_country='COL', status='verified',
            verified_at=verified_at)

    def _store_reference(self, verification=None):
        with mock.patch.object(fsu.requests, 'get', return_value=_download()):
            return fsu.store_face_reference_from_didit(verification or self.verification, _decision())

    def _liveness(self, status='SUCCEEDED', confidence=97, similarity=98.5):
        self.rek.get_face_liveness_session_results.return_value = {
            'Status': status, 'Confidence': confidence, 'ReferenceImage': {'Bytes': b'live-frame'}}
        self.rek.compare_faces.return_value = {'FaceMatches': [{'Similarity': similarity}]}

    def _passed(self, purpose, minutes_ago=0, consumed=False, session='s-x'):
        return FaceCheck.objects.create(
            user=self.user, purpose=purpose, liveness_session_id=session, status='passed',
            completed_at=timezone.now() - timedelta(minutes=minutes_ago),
            consumed_at=timezone.now() if consumed else None)

    # Reference selfie

    def test_reference_is_copied_encrypted_and_idempotent(self):
        first = self._store_reference()
        again = self._store_reference()
        self.assertEqual(first.pk, again.pk)
        put = self.s3.put_object.call_args.kwargs
        self.assertEqual(put['ServerSideEncryption'], 'AES256')
        self.assertTrue(put['Key'].startswith(f'face-references/{self.user.id}/'))
        self.assertEqual(self.s3.put_object.call_count, 1)

    def test_newer_approval_retires_the_old_reference(self):
        old = self._store_reference()
        newer = self._verification(verified_at=timezone.now() + timedelta(days=1), document_number='P1234567')
        current = self._store_reference(newer)
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        self.assertTrue(current.is_active)

    def test_replayed_older_approval_never_displaces_the_current_reference(self):
        newer = self._verification(verified_at=timezone.now() + timedelta(days=1), document_number='P1234567')
        current = self._store_reference(newer)
        replay = self._store_reference(self.verification)
        self.assertEqual(replay.pk, current.pk)
        self.assertEqual(FaceReference.objects.filter(user=self.user, is_active=True).count(), 1)

    def test_download_failure_never_carries_the_signed_url(self):
        with mock.patch.object(fsu.requests, 'get', return_value=_download(status=403)):
            with self.assertRaises(fsu.FaceStepUpError) as ctx:
                fsu.store_face_reference_from_didit(self.verification, _decision())
        self.assertNotIn('didit.example', str(ctx.exception))
        self.assertNotIn('Signature', str(ctx.exception))
        with mock.patch.object(fsu.requests, 'get', side_effect=fsu.requests.ConnectionError(SIGNED_URL)):
            with self.assertRaises(fsu.FaceStepUpError) as ctx:
                fsu.store_face_reference_from_didit(self.verification, _decision())
        self.assertNotIn('secret', str(ctx.exception))

    # Start / complete

    def test_start_is_closed_until_rollout(self):
        self._store_reference()
        with self.assertRaises(fsu.FaceStepUpError):
            fsu.start_face_check(self.user, 'on_ramp')
        self.rek.create_face_liveness_session.assert_not_called()

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_start_requires_a_reference(self):
        with self.assertRaises(fsu.FaceStepUpError):
            fsu.start_face_check(self.user, 'on_ramp')

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_passing_check(self):
        self._store_reference()
        data = fsu.start_face_check(self.user, 'on_ramp')
        self.assertEqual(data['session_id'], 'sess-1')
        self.assertEqual(self.rek.create_face_liveness_session.call_args.kwargs['Settings'], {'AuditImagesLimit': 4})
        self._liveness()
        self.assertTrue(fsu.complete_face_check(self.user, 'sess-1'))
        compare = self.rek.compare_faces.call_args.kwargs
        self.assertEqual(compare['SourceImage'], {'Bytes': b'live-frame'})
        self.assertEqual(compare['TargetImage'], {'Bytes': b'kyc-selfie'})

    # Device attestation: recorded on every Rekognition call, never enforced

    def _verdict(self, passed):
        from security.models import IntegrityVerdict
        return IntegrityVerdict.objects.create(
            user=self.user, app_recognition='FIREBASE_APP_CHECK', passed=passed,
            trigger_action='face_check_start')

    def test_app_check_is_recorded_on_the_check_at_start_and_grading(self):
        self._store_reference()
        start_v, done_v = self._verdict(True), self._verdict(True)
        with mock.patch('security.integrity_service.app_check_service.verify_and_record',
                        side_effect=[{'verdict_id': start_v.id}, {'verdict_id': done_v.id}]) as verify:
            fsu.start_face_check(self.user, 'on_ramp', app_check_token='tok')
            self._liveness()
            self.assertTrue(fsu.complete_face_check(self.user, 'sess-1', app_check_token='tok'))
        check = FaceCheck.objects.get(liveness_session_id='sess-1')
        self.assertEqual((check.start_integrity_id, check.complete_integrity_id), (start_v.id, done_v.id))
        self.assertEqual([c.kwargs['action'] for c in verify.call_args_list],
                         ['face_check_start', 'face_check_complete'])
        self.assertTrue(all(c.kwargs['should_enforce'] is False for c in verify.call_args_list))

    def test_a_failed_or_missing_attestation_never_blocks_a_face_check(self):
        self._store_reference()
        failed = self._verdict(False)
        with mock.patch('security.integrity_service.app_check_service.verify_and_record',
                        return_value={'success': True, 'passed': False, 'verdict_id': failed.id}):
            fsu.start_face_check(self.user, 'on_ramp', app_check_token='')
            self._liveness()
            self.assertTrue(fsu.complete_face_check(self.user, 'sess-1', app_check_token=''))
        with mock.patch('security.integrity_service.app_check_service.verify_and_record',
                        side_effect=RuntimeError('firebase down')):
            self.rek.create_face_liveness_session.return_value = {'SessionId': 'sess-2'}
            fsu.start_face_check(self.user, 'on_ramp', app_check_token='tok')

    def test_a_failed_face_attestation_is_not_a_reward_violation(self):
        from security.models import IntegrityVerdict
        self._verdict(False)  # trigger_action='face_check_start'
        self.assertFalse(IntegrityVerdict.has_historical_violation(self.user))
        IntegrityVerdict.objects.create(user=self.user, passed=False, trigger_action='login')
        self.assertTrue(IntegrityVerdict.has_historical_violation(self.user))

    def test_grading_polls_record_the_attestation_once(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'on_ramp')
        self.rek.get_face_liveness_session_results.return_value = {'Status': 'IN_PROGRESS'}
        done_v = self._verdict(True)
        with mock.patch('security.integrity_service.app_check_service.verify_and_record',
                        return_value={'verdict_id': done_v.id}) as verify:
            for _ in range(3):
                with self.assertRaises(fsu.FaceStepUpPending):
                    fsu.complete_face_check(self.user, 'sess-1', app_check_token='tok')
        self.assertEqual(verify.call_count, 1)

    def test_cost_report_counts_sessions_and_compares_by_purpose(self):
        from io import StringIO
        from django.core.management import call_command
        now = timezone.now()
        FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id='c-1',
                                 status='passed', similarity=99, completed_at=now)
        FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id='c-2',
                                 status='failed', completed_at=now)  # failed before the face match
        out = StringIO()
        with override_settings(FACE_LIVENESS_UNIT_USD='0.015', FACE_COMPARE_UNIT_USD='0.001'):
            call_command('face_check_costs', months=1, stdout=out)
        line = next(l for l in out.getvalue().splitlines() if ' withdrawal ' in l)
        # 2 sessions x 0.015 + 1 compare x 0.001
        self.assertIn(' 2 ', line)
        self.assertTrue(line.rstrip().endswith('0.03'), line)

    # Evidence for abuse investigations

    def _finished_with_frames(self, status='SUCCEEDED', similarity=98.5):
        self._store_reference()
        fsu.start_face_check(self.user, 'withdrawal')
        self._liveness(status=status, similarity=similarity)
        self.rek.get_face_liveness_session_results.return_value['AuditImages'] = [
            {'Bytes': b'audit-a'}, {'Bytes': b'audit-b'}]
        self.s3.put_object.reset_mock()
        return fsu.complete_face_check(self.user, 'sess-1')

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_frames_of_each_check_are_kept_encrypted_in_our_bucket(self):
        self.assertTrue(self._finished_with_frames())
        check = FaceCheck.objects.get()
        prefix = f'face-checks/{self.user.pk}/{check.pk}/'
        self.assertEqual(check.evidence_keys, [prefix + 'reference.jpg', prefix + 'audit-0.jpg', prefix + 'audit-1.jpg'])
        stored = {c.kwargs['Key']: c.kwargs for c in self.s3.put_object.call_args_list}
        self.assertEqual(stored[prefix + 'audit-1.jpg']['Body'], b'audit-b')
        self.assertTrue(all(c['ServerSideEncryption'] == 'AES256' for c in stored.values()))

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_failed_checks_keep_their_frames_too(self):
        self.assertFalse(self._finished_with_frames(similarity=30))
        self.assertEqual(len(FaceCheck.objects.get().evidence_keys), 3)

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_frames_that_did_upload_are_still_recorded(self):
        self.s3.put_object.side_effect = [None, RuntimeError('s3 down'), None]
        self._store_reference = lambda: FaceReference.objects.create(
            user=self.user, identity_verification=self.verification, s3_key='k', sha256='x', source='test')
        self.assertTrue(self._finished_with_frames())
        self.assertEqual([k.rsplit('/', 1)[-1] for k in FaceCheck.objects.get().evidence_keys], ['reference.jpg'])

    def test_a_failed_deletion_never_blocks_later_checks(self):
        old = timezone.now() - fsu.EVIDENCE_RETENTION - timedelta(days=1)
        for i in range(3):
            FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id=f'b{i}',
                status='passed', completed_at=old, evidence_keys=[f'face-checks/b{i}.jpg'])
        self.s3.delete_objects.side_effect = [{'Errors': [{'Key': 'face-checks/b0.jpg'}]}, {}, {}]
        self.assertEqual(fsu.purge_expired_evidence(batch=1), 2)

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_frames_stay_recorded_when_grading_fails_after_storing_them(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'withdrawal')
        self._liveness()
        self.rek.compare_faces.side_effect = RuntimeError('rekognition down')
        with self.assertRaises(RuntimeError):
            fsu.complete_face_check(self.user, 'sess-1')
        check = FaceCheck.objects.get()
        self.assertEqual((check.status, len(check.evidence_keys)), ('created', 1))

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_a_retry_never_drops_frames_an_earlier_attempt_stored(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'withdrawal')
        self._liveness()
        self.rek.get_face_liveness_session_results.return_value['AuditImages'] = [{'Bytes': b'audit-a'}]
        self.rek.compare_faces.side_effect = RuntimeError('rekognition down')
        with self.assertRaises(RuntimeError):
            fsu.complete_face_check(self.user, 'sess-1')
        self.rek.compare_faces.side_effect = None
        self.s3.put_object.side_effect = RuntimeError('s3 down')  # retry stores nothing new
        self.assertTrue(fsu.complete_face_check(self.user, 'sess-1'))
        self.assertEqual([k.rsplit('/', 1)[-1] for k in FaceCheck.objects.get().evidence_keys],
                         ['reference.jpg', 'audit-0.jpg'])

    def test_purge_retries_objects_s3_failed_to_delete(self):
        old = timezone.now() - fsu.EVIDENCE_RETENTION - timedelta(days=1)
        check = FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id='p',
            status='passed', completed_at=old, evidence_keys=['face-checks/x/reference.jpg', 'face-checks/x/audit-0.jpg'])
        self.s3.delete_objects.return_value = {'Errors': [{'Key': 'face-checks/x/audit-0.jpg', 'Code': 'InternalError'}]}
        self.assertEqual(fsu.purge_expired_evidence(), 0)
        check.refresh_from_db()
        self.assertEqual((check.evidence_keys, check.evidence_purged_at), (['face-checks/x/audit-0.jpg'], None))
        self.s3.delete_objects.return_value = {}
        self.assertEqual(fsu.purge_expired_evidence(), 1)

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_storage_trouble_never_changes_the_outcome(self):
        self.s3.put_object.side_effect = RuntimeError('s3 down')
        self._store_reference = lambda: FaceReference.objects.create(
            user=self.user, identity_verification=self.verification, s3_key='k', sha256='x', source='test')
        self.assertTrue(self._finished_with_frames())
        self.assertEqual(FaceCheck.objects.get().evidence_keys, [])

    def test_purge_keeps_failed_and_banned_and_recent(self):
        from security.models import UserBan
        old = timezone.now() - fsu.EVIDENCE_RETENTION - timedelta(days=1)
        make = lambda user, status, when, session: FaceCheck.objects.create(
            user=user, purpose='withdrawal', liveness_session_id=session, status=status,
            completed_at=when, evidence_keys=[f'face-checks/{session}.jpg'])
        expired = make(self.user, 'passed', old, 'a')
        failed = make(self.user, 'failed', old, 'b')
        recent = make(self.user, 'passed', timezone.now(), 'c')
        banned = make(self.other, 'passed', old, 'd')
        UserBan.all_objects.create(user=self.other, ban_type='permanent', reason='fraud')
        self.assertEqual(fsu.purge_expired_evidence(), 1)
        self.s3.delete_objects.assert_called_once()
        self.assertEqual(self.s3.delete_objects.call_args.kwargs['Delete']['Objects'], [{'Key': 'face-checks/a.jpg'}])
        for row, kept in ((expired, False), (failed, True), (recent, True), (banned, True)):
            row.refresh_from_db()
            self.assertEqual(bool(row.evidence_keys), kept, row.liveness_session_id)
        self.assertIsNotNone(expired.evidence_purged_at)

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_unfinished_session_stays_retryable(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'on_ramp')
        self._liveness(status='IN_PROGRESS')
        with self.assertRaises(fsu.FaceStepUpPending):
            fsu.complete_face_check(self.user, 'sess-1')
        self.assertEqual(FaceCheck.objects.get().status, 'created')
        self._liveness()
        self.assertTrue(fsu.complete_face_check(self.user, 'sess-1'))

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_someone_else_fails_on_similarity(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'withdrawal')
        self._liveness(similarity=41)
        self.assertFalse(fsu.complete_face_check(self.user, 'sess-1'))
        self.assertEqual(FaceCheck.objects.get().failure_reason, 'face_mismatch')

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_spoof_fails_on_liveness_before_any_compare(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'withdrawal')
        self._liveness(confidence=40)
        self.assertFalse(fsu.complete_face_check(self.user, 'sess-1'))
        self.rek.compare_faces.assert_not_called()

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_expired_session_fails(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'on_ramp')
        FaceCheck.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        self._liveness()
        self.assertFalse(fsu.complete_face_check(self.user, 'sess-1'))

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_another_user_cannot_complete_the_session(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'on_ramp')
        with self.assertRaises(fsu.FaceStepUpError):
            fsu.complete_face_check(self.other, 'sess-1')

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_repeated_failures_cool_down(self):
        self._store_reference()
        for i in range(fsu.MAX_FAILURES_PER_WINDOW):
            FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id=f'f-{i}',
                                     status='failed', completed_at=timezone.now())
        with self.assertRaises(fsu.FaceStepUpError):
            fsu.start_face_check(self.user, 'withdrawal')
        self.rek.create_face_liveness_session.assert_not_called()

    @override_settings(FACE_STEP_UP_AVAILABLE=True)
    def test_open_sessions_are_bounded(self):
        self._store_reference()
        for i in range(fsu.MAX_OPEN_SESSIONS):
            FaceCheck.objects.create(user=self.user, purpose='on_ramp', liveness_session_id=f'o-{i}')
        with self.assertRaises(fsu.FaceStepUpError):
            fsu.start_face_check(self.user, 'on_ramp')

    # Configuration

    def test_flag_is_read_from_the_environment(self):
        with mock.patch.dict(os.environ, {'FACE_STEP_UP_ENABLED': 'true'}):
            self.assertTrue(fsu.step_up_enabled())
        with mock.patch.dict(os.environ, {'FACE_STEP_UP_ENABLED': 'false'}):
            self.assertFalse(fsu.step_up_enabled())

    # Enforcement

    def test_disabled_flag_never_blocks(self):
        self.assertEqual(fsu.missing_face_step_up(self.user, 'on_ramp'), '')
        self.assertEqual(fsu.claim_on_ramp_check(self.user, 'order'), (True, None))
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), '')

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_each_deposit_order_spends_its_own_check(self):
        self.assertEqual(fsu.missing_face_step_up(self.user, 'on_ramp'), fsu.FACE_STEP_UP_MESSAGE)
        self.assertEqual(fsu.claim_on_ramp_check(self.user, 'order-0'), (False, None))
        check = self._passed('on_ramp')
        self.assertEqual(fsu.missing_face_step_up(self.user, 'on_ramp'), '')
        self.assertEqual(fsu.claim_on_ramp_check(self.user, 'order-1'), (True, check.pk))
        self.assertEqual(fsu.claim_on_ramp_check(self.user, 'order-2'), (False, None))

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_released_claim_can_be_used_again(self):
        check = self._passed('on_ramp')
        _, claim = fsu.claim_on_ramp_check(self.user, 'order-1')
        fsu.release_on_ramp_check(claim)
        self.assertEqual(fsu.claim_on_ramp_check(self.user, 'order-2'), (True, check.pk))

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_withdrawal_window(self):
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)
        check = self._passed('withdrawal')
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), '')
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), '')
        FaceCheck.objects.filter(pk=check.pk).update(completed_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_outgoing_approval_is_single_use_with_exact_retry(self):
        check = self._passed('withdrawal')
        key = fsu.withdrawal_action_key('send', 1, {'amount': '10', 'to': 'alice'})
        changed = fsu.withdrawal_action_key('send', 1, {'amount': '20', 'to': 'alice'})
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal', action_key=key, consume=True), '')
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal', action_key=key, consume=True), '')
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal', action_key=changed, consume=True), fsu.FACE_STEP_UP_MESSAGE)
        self.assertEqual(fsu.missing_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)
        check.refresh_from_db()
        self.assertEqual(check.consumed_by, key)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_other_purpose_approvals_cannot_authorize_outgoing(self):
        self._passed('on_ramp', session='deposit-proof')
        self._passed('emergency_exit', session='exit-proof')
        key = fsu.withdrawal_action_key('send', 1, [])
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal', action_key=key, consume=True), fsu.FACE_STEP_UP_MESSAGE)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_retry_does_not_spend_a_second_approval(self):
        self._passed('withdrawal', session='first')
        key = fsu.withdrawal_action_key('send', 1, [])
        fsu.require_face_step_up(self.user, 'withdrawal', action_key=key, consume=True)
        second = self._passed('withdrawal', session='second')
        fsu.require_face_step_up(self.user, 'withdrawal', action_key=key, consume=True)
        second.refresh_from_db()
        self.assertIsNone(second.consumed_at)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_failed_check_never_counts(self):
        FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id='s-c',
                                 status='failed', completed_at=timezone.now())
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_users_who_never_did_kyc_are_never_asked(self):
        IdentityVerification.all_documents.filter(user=self.user).update(status='rejected')
        self.assertFalse(fsu.step_up_applies(self.user))
        self.assertEqual(fsu.missing_face_step_up(self.user, 'withdrawal'), '')
        self.assertEqual(fsu.claim_on_ramp_check(self.user, 'order-1'), (True, None))

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_an_additional_document_alone_still_counts_as_kyc(self):
        # A passport verified for a local-money rail opens that rail by itself.
        IdentityVerification.all_documents.filter(user=self.user).update(is_additional_document=True)
        self.assertFalse(self.user.is_identity_verified)
        self.assertTrue(fsu.step_up_applies(self.user))
        self.assertEqual(fsu.missing_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_kycd_user_without_a_stored_selfie_is_not_waved_through(self):
        # No FaceReference was stored for self.user in setUp.
        self.assertEqual(fsu.missing_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)
        with self.assertRaises(fsu.FaceStepUpError) as ctx:
            fsu.start_face_check(self.user, 'withdrawal')
        self.assertEqual(str(ctx.exception), fsu.NO_REFERENCE_MESSAGE)

    def test_deposit_orders_cannot_use_the_non_spending_gate(self):
        with self.assertRaises(ValueError):
            fsu.require_face_step_up(self.user, 'on_ramp')


@override_settings(FACE_STEP_UP_ENABLED=True)
class WithdrawalClaimConcurrencyTests(TransactionTestCase):
    def test_only_one_distinct_operation_can_claim_a_single_approval(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        user = get_user_model().objects.create(username='concurrent-face', firebase_uid='concurrent-face')
        FaceCheck.objects.create(user=user, purpose='withdrawal', liveness_session_id='concurrent',
                                 status='passed', completed_at=timezone.now())
        barrier = Barrier(2)

        def claim(identifier):
            try:
                barrier.wait(timeout=10)
                return fsu.require_face_step_up(user, 'withdrawal', consume=True,
                    action_key=fsu.withdrawal_action_key('send', identifier, []))
            finally:
                connections['default'].close()

        with mock.patch.object(fsu, 'step_up_applies', return_value=True):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(claim, [1, 2]))
        self.assertCountEqual(outcomes, ['', fsu.FACE_STEP_UP_MESSAGE])


class SendStepUpTests(TestCase):
    """Who must show a face before a BSC send."""

    def setUp(self):
        self.user = get_user_model().objects.create(
            username='send-user', email='send@example.com', firebase_uid='send-user-uid')
        IdentityVerification.all_documents.create(
            user=self.user, verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth='1994-07-21', verified_nationality='COL', verified_address='-',
            verified_city='-', verified_state='-', verified_country='COL', document_type='national_id',
            document_number='1065000009', document_issuing_country='COL', status='verified',
            verified_at=timezone.now())

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_every_personal_send_needs_a_recent_face(self):
        from send.bsc_flow import _send_step_up
        # Confío recipients too: pooling into a ring's own accounts is the first hop.
        self.assertEqual(_send_step_up(self.user, None, None), fsu.FACE_STEP_UP_MESSAGE)
        FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id='w-1',
                                 status='passed', completed_at=timezone.now())
        self.assertEqual(_send_step_up(self.user, None, None), '')

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_exempt_sends(self):
        from send.bsc_flow import _send_step_up
        # From a business, or the server-only activation fee.
        self.assertEqual(_send_step_up(self.user, object(), None), '')
        self.assertEqual(_send_step_up(self.user, None, 'activation-1'), '')

    def test_nothing_is_asked_while_enforcement_is_off(self):
        from send.bsc_flow import _send_step_up
        self.assertEqual(_send_step_up(self.user, None, None), '')

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_users_without_kyc_keep_sending(self):
        from send.bsc_flow import _send_step_up
        IdentityVerification.all_documents.filter(user=self.user).delete()
        self.assertEqual(_send_step_up(self.user, None, None), '')


class FaceStepUpStatusQueryTests(TestCase):
    def test_status_mirrors_the_flags(self):
        from security.schema import SecurityQuery
        status = SecurityQuery().resolve_face_step_up_status(None)
        self.assertEqual((status.enabled, status.available, status.required), (False, False, None))
        with override_settings(FACE_STEP_UP_ENABLED=True):
            status = SecurityQuery().resolve_face_step_up_status(None)
            self.assertEqual((status.enabled, status.available), (True, True))

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_required_is_per_user(self):
        from security.schema import SecurityQuery
        user = get_user_model().objects.create(
            username='status-user', email='status@example.com', firebase_uid='status-user-uid')
        info = SimpleNamespace(context=SimpleNamespace(user=user))
        self.assertFalse(SecurityQuery().resolve_face_step_up_status(info).required)
        IdentityVerification.all_documents.create(
            user=user, verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth='1994-07-21', verified_nationality='COL', verified_address='-',
            verified_city='-', verified_state='-', verified_country='COL', document_type='national_id',
            document_number='1065000010', document_issuing_country='COL', status='verified',
            verified_at=timezone.now())
        self.assertTrue(SecurityQuery().resolve_face_step_up_status(info).required)
