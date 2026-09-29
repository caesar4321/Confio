from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from security import face_step_up as fsu
from security.models import FaceCheck, FaceReference, IdentityVerification


def _decision(url='https://didit.example/selfie.jpg'):
    return {'liveness_checks': [{'reference_image': url}]}


class FaceStepUpTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username='face-user', email='face@example.com', firebase_uid='face-user-uid')
        self.other = get_user_model().objects.create(
            username='face-other', email='other@example.com', firebase_uid='face-other-uid')
        self.verification = IdentityVerification.objects.create(
            user=self.user, verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth='1994-07-21', verified_nationality='COL', verified_address='-',
            verified_city='-', verified_state='-', verified_country='COL', document_type='national_id',
            document_number='1065000001', document_issuing_country='COL', status='verified')
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
                'expiration': 'soon', 'region': 'eu-central-1'}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _store_reference(self):
        response = SimpleNamespace(content=b'kyc-selfie', headers={'Content-Type': 'image/jpeg'},
                                   raise_for_status=lambda: None)
        with mock.patch.object(fsu.requests, 'get', return_value=response):
            return fsu.store_face_reference_from_didit(self.verification, _decision())

    def _liveness(self, status='SUCCEEDED', confidence=97, similarity=98.5):
        self.rek.get_face_liveness_session_results.return_value = {
            'Status': status, 'Confidence': confidence, 'ReferenceImage': {'Bytes': b'live-frame'}}
        self.rek.compare_faces.return_value = {'FaceMatches': [{'Similarity': similarity}]}

    # Reference selfie

    def test_reference_is_copied_encrypted_and_idempotent(self):
        first = self._store_reference()
        again = self._store_reference()
        self.assertEqual(first.pk, again.pk)
        put = self.s3.put_object.call_args.kwargs
        self.assertEqual(put['ServerSideEncryption'], 'AES256')
        self.assertTrue(put['Key'].startswith(f'face-references/{self.user.id}/'))
        self.assertEqual(self.s3.put_object.call_count, 1)

    def test_newer_reference_retires_the_old_one(self):
        old = FaceReference.objects.create(user=self.user, s3_key='k', sha256='x', source='didit_liveness')
        self._store_reference()
        old.refresh_from_db()
        self.assertFalse(old.is_active)

    # Start / complete

    def test_start_requires_a_reference(self):
        with self.assertRaises(fsu.FaceStepUpError):
            fsu.start_face_check(self.user, 'on_ramp')

    def test_passing_check(self):
        self._store_reference()
        data = fsu.start_face_check(self.user, 'on_ramp')
        self.assertEqual(data['session_id'], 'sess-1')
        self.assertEqual(self.rek.create_face_liveness_session.call_args.kwargs['Settings'], {'AuditImagesLimit': 0})
        self._liveness()
        self.assertTrue(fsu.complete_face_check(self.user, 'sess-1'))
        compare = self.rek.compare_faces.call_args.kwargs
        self.assertEqual(compare['SourceImage'], {'Bytes': b'live-frame'})
        self.assertEqual(compare['TargetImage'], {'Bytes': b'kyc-selfie'})

    def test_someone_else_fails_on_similarity(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'withdrawal')
        self._liveness(similarity=41)
        self.assertFalse(fsu.complete_face_check(self.user, 'sess-1'))
        self.assertEqual(FaceCheck.objects.get().failure_reason, 'face_mismatch')

    def test_spoof_fails_on_liveness_before_any_compare(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'withdrawal')
        self._liveness(confidence=40)
        self.assertFalse(fsu.complete_face_check(self.user, 'sess-1'))
        self.rek.compare_faces.assert_not_called()

    def test_expired_session_fails(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'on_ramp')
        FaceCheck.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        self._liveness()
        self.assertFalse(fsu.complete_face_check(self.user, 'sess-1'))

    def test_another_user_cannot_complete_the_session(self):
        self._store_reference()
        fsu.start_face_check(self.user, 'on_ramp')
        with self.assertRaises(fsu.FaceStepUpError):
            fsu.complete_face_check(self.other, 'sess-1')

    # Enforcement

    def test_disabled_flag_never_blocks(self):
        self.assertEqual(fsu.require_face_step_up(self.user, 'on_ramp'), '')

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_each_deposit_order_spends_its_own_check(self):
        self.assertEqual(fsu.require_face_step_up(self.user, 'on_ramp'), fsu.FACE_STEP_UP_MESSAGE)
        FaceCheck.objects.create(user=self.user, purpose='on_ramp', liveness_session_id='s-a',
                                 status='passed', completed_at=timezone.now())
        self.assertEqual(fsu.require_face_step_up(self.user, 'on_ramp', consumed_by='order-1'), '')
        self.assertEqual(fsu.require_face_step_up(self.user, 'on_ramp'), fsu.FACE_STEP_UP_MESSAGE)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_withdrawal_window(self):
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)
        check = FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id='s-b',
                                         status='passed', completed_at=timezone.now())
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), '')
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), '')
        FaceCheck.objects.filter(pk=check.pk).update(completed_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_failed_check_never_counts(self):
        FaceCheck.objects.create(user=self.user, purpose='withdrawal', liveness_session_id='s-c',
                                 status='failed', completed_at=timezone.now())
        self.assertEqual(fsu.require_face_step_up(self.user, 'withdrawal'), fsu.FACE_STEP_UP_MESSAGE)
