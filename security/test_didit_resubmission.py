"""A reviewer's Didit "Resubmitted": the person acts, nobody is reviewing."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from security.didit import (
    SAME_FACE_RETRY_KEY,
    DiditAPIError,
    _NoSelfie,
    _anchor_for,
    _anchor_selfie,
    _extract_verification_payload,
    ensure_pending_didit_verification,
    resume_didit_resubmission,
    retry_pending_same_face,
    sync_didit_session,
)
from security.face_step_up import _active_reference
from security.identity_status import has_ever_passed_kyc, identity_status, is_identity_verified
from security.models import FaceReference, GENERIC_RESUBMISSION_DETAIL, IdentityVerification
from security.schema import SecurityQuery
from security.views import didit_webhook

User = get_user_model()
URL = 'https://verify.didit.me/session/abc123'


class ResubmissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='resub', password='x', firebase_uid='resub-uid')
        self.row = ensure_pending_didit_verification(user=self.user, session_id='sess-1')
        self.status = 'Resubmitted'
        self.reviews = [{'new_status': 'Resubmitted', 'user': 'reviewer@example.com', 'comment': None,
                         'created_at': '2026-10-30T20:00:00Z'}]
        self.resubmissions = []
        patcher = patch('security.didit._didit_request', side_effect=self._didit)
        self.didit = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch('security.didit.create_notification')
        self.notify = patcher.start()
        self.addCleanup(patcher.stop)

    def _didit(self, method, path, **kwargs):
        if 'include=resubmissions' in path:
            return {'resubmissions': self.resubmissions}
        return {'session_id': 'sess-1', 'status': self.status, 'session_url': URL, 'reviews': self.reviews,
                'vendor_data': {'user_id': self.user.id, 'account_type': 'personal'}}

    def _sync(self):
        verification, _ = sync_didit_session(session_id='sess-1')
        return verification

    def test_is_stored_as_waiting_for_the_person_not_as_review(self):
        verification = self._sync()
        self.assertEqual(verification.status, 'pending')
        self.assertTrue(verification.needs_person_action)
        self.assertEqual(verification.status_detail, GENERIC_RESUBMISSION_DETAIL)

    def test_in_review_needs_nothing_from_the_person(self):
        self.status = 'In Review'
        verification = self._sync()
        self.assertFalse(verification.needs_person_action)
        self.assertEqual(verification.action_detail, '')

    def test_pushes_once_however_many_times_didit_repeats_the_webhook(self):
        self._sync()
        self._sync()
        self.assertEqual(self.notify.call_count, 1)
        self.assertEqual(self.notify.call_args.kwargs['action_url'], 'confio://verification')

    def test_a_new_request_after_a_decision_pushes_again(self):
        self._sync()
        self.status = 'In Review'
        self._sync()
        self.status = 'Resubmitted'
        self._sync()
        self.assertEqual(self.notify.call_count, 2)

    def test_business_kyb_gets_no_push_and_keeps_its_copy(self):
        ensure_pending_didit_verification(user=self.user, session_id='sess-1b', account_type='business',
                                          business_id='42')
        response = {'session_id': 'sess-1b', 'status': 'Resubmitted', 'session_kind': 'business',
                    'vendor_data': {'user_id': self.user.id, 'account_type': 'business', 'business_id': '42'}}
        self.didit.side_effect = None
        self.didit.return_value = response
        verification, _ = sync_didit_session(session_id='sess-1b')
        self.notify.assert_not_called()
        self.assertIn('tu negocio', verification.status_detail)

    def test_shows_the_console_reviewers_note(self):
        self.reviews[0]['comment'] = 'Hola, repite la selfie con buena luz.'
        self.assertEqual(self._sync().action_detail, 'Hola, repite la selfie con buena luz.')

    def test_never_shows_a_note_our_own_api_wrote(self):
        self.reviews[0].update(user='API Client', comment='fraud case 12')
        self.assertEqual(self._sync().action_detail, GENERIC_RESUBMISSION_DETAIL)

    def test_shows_a_fixable_reason(self):
        self.resubmissions = [{'number': 1, 'reasons': {'n1': 'DOCUMENT_EXPIRED'}},
                              {'number': 2, 'reasons': {'n1': 'IMAGE_TOO_BLURRY'}}]
        self.assertIn('borrosa', self._sync().action_detail)

    def test_any_reason_outside_the_fixable_list_stays_generic(self):
        # A real prod request: the document step is fixable, the face step is not to be named.
        self.resubmissions = [{'number': 1, 'reasons': {'ocr': 'IMAGE_TOO_BLURRY', 'face_match': 'LOW_FACE_MATCH_SIMILARITY'}}]
        self.assertEqual(self._sync().action_detail, GENERIC_RESUBMISSION_DETAIL)

    def test_a_failed_reason_lookup_never_loses_the_status_change(self):
        def fail_on_reasons(method, path, **kwargs):
            if 'include=resubmissions' in path:
                raise DiditAPIError('down')
            return self._didit(method, path, **kwargs)
        self.didit.side_effect = fail_on_reasons
        verification = self._sync()
        self.assertTrue(verification.needs_person_action)
        self.assertEqual(verification.action_detail, GENERIC_RESUBMISSION_DETAIL)

    def test_finishing_clears_the_action_and_decides(self):
        self._sync()
        self.status = 'Declined'
        verification = self._sync()
        self.assertEqual(verification.status, 'rejected')
        self.assertFalse(verification.needs_person_action)

    def test_resume_returns_the_same_sessions_link(self):
        self._sync()
        self.assertEqual(resume_didit_resubmission(user=self.user, verification_id=str(self.row.pk)), URL)
        self.assertEqual(IdentityVerification.all_documents.filter(user=self.user).count(), 1)

    def test_resume_asks_didit_and_refuses_a_session_that_moved_on(self):
        self._sync()
        self.status = 'In Review'
        with self.assertRaises(DiditAPIError):
            resume_didit_resubmission(user=self.user, verification_id=str(self.row.pk))
        self.row.refresh_from_db()
        self.assertFalse(self.row.needs_person_action)

    def test_resume_refuses_a_link_that_is_not_didits(self):
        self._sync()
        with patch('security.didit._validated_didit_session_url', side_effect=DiditAPIError('unsafe')):
            with self.assertRaises(DiditAPIError):
                resume_didit_resubmission(user=self.user, verification_id=str(self.row.pk))

    def test_resume_refuses_someone_elses_document(self):
        self._sync()
        other = User.objects.create_user(username='other', password='x', firebase_uid='other-uid')
        for verification_id in (str(self.row.pk), 'not-a-number', ''):
            with self.subTest(verification_id=verification_id), self.assertRaises(DiditAPIError):
                resume_didit_resubmission(user=other, verification_id=verification_id)

    def test_resume_refuses_a_document_with_nothing_to_redo(self):
        self.status = 'In Review'
        self._sync()
        with self.assertRaises(DiditAPIError):
            resume_didit_resubmission(user=self.user, verification_id=str(self.row.pk))

    def test_a_verified_person_sent_back_loses_rails_but_stays_bound(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(status='verified', verified_at=timezone.now())
        self.assertTrue(is_identity_verified(self.user))
        self._sync()
        self.assertFalse(is_identity_verified(self.user))
        self.assertEqual(identity_status(self.user), 'pending')
        self.assertTrue(has_ever_passed_kyc(self.user))

    def test_a_sent_back_document_keeps_the_identity_that_was_verified(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            status='verified', verified_at=timezone.now(), verified_first_name='Ana',
            verified_date_of_birth=date(1990, 5, 1), document_issuing_country='ARG')
        verification = self._sync()
        self.assertEqual(verification.verified_first_name, 'Ana')
        self.assertEqual(verification.verified_date_of_birth, date(1990, 5, 1))
        self.assertEqual(verification.document_issuing_country, 'ARG')

    def _sent_back_with_an_approval_of(self, first_name, birth_date, face='match'):
        self._sync()
        self.status = 'Approved'
        extracted = {**_extract_verification_payload({}), 'verified_first_name': first_name,
                     'verified_last_name': 'Perez', 'verified_date_of_birth': birth_date}
        with patch('security.didit._extract_verification_payload', return_value=extracted), \
                patch('security.didit._same_face', return_value=face) as compared:
            verification, _ = sync_didit_session(session_id='sess-1')
        return verification, compared

    def test_reapproval_cannot_replace_the_person(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            status='verified', verified_at=timezone.now(), verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth=date(1990, 5, 1))
        verification, _ = self._sent_back_with_an_approval_of('Bruno', date(1980, 1, 1))
        self.assertEqual(verification.status, 'rejected')

    def test_reapproval_of_the_same_person_stands(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            status='verified', verified_at=timezone.now(), verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth=date(1990, 5, 1))
        verification, face = self._sent_back_with_an_approval_of('Ana', date(1990, 5, 1))
        self.assertEqual(verification.status, 'verified')
        face.assert_called()

    def test_a_row_that_lost_its_identity_is_bound_by_its_face(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(verified_at=timezone.now())
        verification, face = self._sent_back_with_an_approval_of('Ana', date(1990, 5, 1))
        self.assertEqual(verification.status, 'verified')
        face.assert_called()

    def test_the_stored_selfie_stands_while_a_document_is_sent_back(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(status='verified', verified_at=timezone.now())
        reference = FaceReference.objects.create(user=self.user, identity_verification=self.row, s3_key='k',
                                                 is_active=True)
        self._sync()
        self.assertEqual(_active_reference(self.user), reference)

    def test_a_second_sync_of_a_refused_replacement_stays_refused(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            status='verified', verified_at=timezone.now(), verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth=date(1990, 5, 1))
        verification, _ = self._sent_back_with_an_approval_of('Bruno', date(1980, 1, 1))
        self.assertEqual(verification.verified_first_name, 'Ana')
        extracted = {**_extract_verification_payload({}), 'verified_first_name': 'Bruno',
                     'verified_last_name': 'Perez', 'verified_date_of_birth': date(1980, 1, 1)}
        with patch('security.didit._extract_verification_payload', return_value=extracted):
            verification, _ = sync_didit_session(session_id='sess-1')
        self.assertEqual(verification.status, 'rejected')

    def test_a_refused_replacement_cannot_start_over_in_a_new_session(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            status='verified', verified_at=timezone.now(), verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth=date(1990, 5, 1))
        self._sent_back_with_an_approval_of('Bruno', date(1980, 1, 1))
        fresh = ensure_pending_didit_verification(user=self.user, session_id='sess-2')
        self.assertEqual(_anchor_for(fresh), self.row)
        self.assertTrue(has_ever_passed_kyc(self.user))

    def test_any_of_our_own_refusals_keeps_the_document_bound(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            status='verified', verified_at=timezone.now(), verified_date_of_birth=date(1990, 5, 1))
        self._sync()
        self.status = 'Approved'
        with patch('security.didit._enforce_document_capture_holder', return_value=('rejected', 'no')):
            self._sync()
        self.assertTrue(has_ever_passed_kyc(self.user))

    def test_face_retries_running_out_keep_the_document_bound(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            verified_at=timezone.now(), verified_date_of_birth=date(1990, 5, 1), risk_factors={
                'provider': 'didit', 'didit': {'session_id': 'sess-1'}, SAME_FACE_RETRY_KEY: '2020-01-01T00:00:00+00:00'})
        retry_pending_same_face()
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'rejected')
        self.assertTrue(has_ever_passed_kyc(self.user))
        self.status = 'In Review'
        self.assertEqual(self._sync().status, 'rejected')
        self.assertTrue(has_ever_passed_kyc(self.user))

    def test_a_reviewers_decline_still_unbinds_a_borrowed_document(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(status='verified', verified_at=timezone.now())
        self.status = 'Declined'
        self._sync()
        fresh = ensure_pending_didit_verification(user=self.user, session_id='sess-2')
        self.assertIsNone(_anchor_for(fresh))
        self.assertFalse(has_ever_passed_kyc(self.user))

    def test_a_row_that_lost_its_identity_still_anchors_a_new_session(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(verified_at=timezone.now())
        other = ensure_pending_didit_verification(user=self.user, session_id='sess-2')
        self.assertEqual(_anchor_for(other), self.row)

    def test_a_row_with_its_identity_anchors_before_one_without(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(verified_at=timezone.now())
        kept = ensure_pending_didit_verification(user=self.user, session_id='sess-2')
        IdentityVerification.all_documents.filter(pk=kept.pk).update(
            status='verified', verified_at=timezone.now(), verified_date_of_birth=date(1990, 5, 1))
        newest = ensure_pending_didit_verification(user=self.user, session_id='sess-3')
        self.assertEqual(_anchor_for(newest), kept)

    def test_no_identity_and_no_selfie_left_is_refused(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(verified_at=timezone.now())
        verification, _ = self._sent_back_with_an_approval_of('Ana', date(1990, 5, 1), face='no_reference')
        self.assertEqual(verification.status, 'rejected')

    def test_a_reopened_session_that_expired_stays_untrusted(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(status='verified', verified_at=timezone.now())
        self._sync()
        self.status = 'Expired'
        verification = self._sync()
        self.assertEqual(verification.status, 'expired')
        with self.assertRaises(_NoSelfie):
            _anchor_selfie(verification)

    def test_a_session_expiring_after_the_upgrade_is_still_known_as_reopened(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(
            risk_factors={'provider': 'didit', 'didit': {'session_id': 'sess-1', 'raw_status': 'Resubmitted'}})
        self.status = 'Expired'
        with self.assertRaises(_NoSelfie):
            _anchor_selfie(self._sync())

    def test_an_approval_that_stood_trusts_its_session_again(self):
        self._sync()
        self.status = 'Approved'
        verification = self._sync()
        self.assertEqual(verification.status, 'verified')
        self.assertNotIn('session_reopened', verification.risk_factors)

    def test_a_reopened_sessions_selfie_never_speaks_for_the_person(self):
        self.row.risk_factors = {'didit': {'session_id': 'sess-1'}}
        for status in ('pending', 'rejected'):
            self.row.status = status
            with self.subTest(status=status), self.assertRaises(_NoSelfie):
                _anchor_selfie(self.row)

    def test_free_text_alone_stays_generic(self):
        self.resubmissions = [{'number': 1, 'reasons': {'n1': 'Passport photo too blurry'}}]
        self.assertEqual(self._sync().action_detail, GENERIC_RESUBMISSION_DETAIL)

    def test_a_passed_document_sent_back_is_listed_after_a_newer_one(self):
        IdentityVerification.all_documents.filter(pk=self.row.pk).update(status='verified', verified_at=timezone.now())
        self._sync()
        newer = ensure_pending_didit_verification(user=self.user, session_id='sess-2')
        IdentityVerification.all_documents.filter(pk=newer.pk).update(status='verified', verified_at=timezone.now())
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        listed = {doc.id: doc for doc in SecurityQuery().resolve_my_identity_documents(info)}
        self.assertTrue(listed[str(self.row.pk)].action_required)
        self.assertFalse(listed[str(newer.pk)].action_required)

    def test_an_attempt_never_passed_and_since_replaced_gets_no_push(self):
        ensure_pending_didit_verification(user=self.user, session_id='sess-2')
        self._sync()
        self.notify.assert_not_called()

    def test_a_person_never_verified_has_not_passed_kyc(self):
        self._sync()
        self.assertFalse(has_ever_passed_kyc(self.user))


class DiditBrowserReturnTests(TestCase):
    def _get(self, query=''):
        return didit_webhook(RequestFactory().get(f'/api/didit/webhook/{query}'))

    def test_returns_to_the_app_naming_the_session(self):
        response = self._get('?verificationSessionId=abc-123&status=Approved')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'confio://verification?verificationSessionId=abc-123')

    def test_an_unsafe_session_id_never_reaches_the_link(self):
        response = self._get('?verificationSessionId=abc%26x%3D1')
        self.assertEqual(response['Location'], 'confio://verification')

    def test_put_stays_refused(self):
        self.assertEqual(didit_webhook(RequestFactory().put('/api/didit/webhook/')).status_code, 405)
