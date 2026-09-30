import os
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from security import face_step_up as fsu
from security.models import FaceCheck, FaceReference, IdentityVerification

SIGNED_URL = 'https://didit.example/selfie.jpg?X-Amz-Signature=secret'


def _decision(url=SIGNED_URL):
    return {'liveness_checks': [{'reference_image': url}]}


def _download(status=200, body=b'kyc-selfie', content_type='image/jpeg'):
    return SimpleNamespace(status_code=status, content=body, headers={'Content-Type': content_type})


class FaceStepUpTests(TestCase):
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
                'expiration': 'soon', 'region': 'eu-central-1'}),
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
        self.assertEqual(self.rek.create_face_liveness_session.call_args.kwargs['Settings'], {'AuditImagesLimit': 0})
        self._liveness()
        self.assertTrue(fsu.complete_face_check(self.user, 'sess-1'))
        compare = self.rek.compare_faces.call_args.kwargs
        self.assertEqual(compare['SourceImage'], {'Bytes': b'live-frame'})
        self.assertEqual(compare['TargetImage'], {'Bytes': b'kyc-selfie'})

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
