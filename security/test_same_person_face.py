"""Second documents: the same face as the first, whichever was verified first.
Duplicate faces across users, and the Didit face blocklist for bans."""
from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from security import didit
from security.models import DiditFaceBlocklistEntry, FaceReference, IdentityVerification, SuspiciousActivity, UserBan

SELFIE = 'https://didit.example/selfie-new.jpg'
ANCHOR_SELFIE = 'https://didit.example/selfie-anchor.jpg'
MESSAGE = 'Las salidas de tu cuenta están temporalmente restringidas. Contacta con soporte para revisar tu cuenta.'


def _document(user, number, **overrides):
    values = dict(
        user=user, status='verified', verified_first_name='Ana Maria', verified_last_name='Perez Soto',
        verified_date_of_birth=date(1990, 1, 1), verified_country='VEN', verified_nationality='VEN',
        document_type='national_id', document_number=number, document_issuing_country='VEN',
        risk_factors={'provider': 'didit', 'didit': {'session_id': f'session-{number}'}},
        verified_at=timezone.now(),
    )
    values.update(overrides)
    return IdentityVerification.all_documents.create(**values)


def _extracted(**overrides):
    values = {'verified_first_name': 'ANA', 'verified_last_name': 'PEREZ',
              'verified_date_of_birth': date(1990, 1, 1), 'document_issuing_country': 'VEN',
              'document_type': 'passport'}
    values.update(overrides)
    return values


def _decision(url=SELFIE):
    return {'session_id': 'session-new', 'liveness_checks': [{'reference_image': url}]}


class SamePersonFaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='face-docs', firebase_uid='face-docs')
        self.rek = mock.Mock()
        self.similarity(99)
        self.downloads = {SELFIE: b'new-selfie', ANCHOR_SELFIE: b'anchor-selfie'}
        for target, kwargs in (
            ('security.face_step_up._rekognition', {'return_value': self.rek}),
            ('security.face_step_up._download_selfie',
             {'side_effect': lambda url: (self.downloads[url], 'image/jpeg')}),
            ('security.face_step_up._reference_bytes', {'return_value': b'reference-selfie'}),
        ):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def similarity(self, value):
        self.rek.compare_faces.return_value = {'FaceMatches': [{'Similarity': value}]}

    def compared(self):
        kwargs = self.rek.compare_faces.call_args.kwargs
        return kwargs['SourceImage']['Bytes'], kwargs['TargetImage']['Bytes']

    def test_first_document_then_second_compares_with_the_stored_kyc_selfie(self):
        primary = _document(self.user, 'V-1')
        FaceReference.objects.create(user=self.user, identity_verification=primary, s3_key='k', sha256='0' * 64,
                                     source='didit_liveness')
        extra = _document(self.user, 'P-1', status='pending', is_additional_document=True,
                          document_type='passport', risk_factors={'didit': {'session_id': 'session-new'}})
        with mock.patch.object(didit, '_didit_request') as fetch:
            self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision()), ('verified', ''))
        fetch.assert_not_called()  # the stored reference, no Didit call
        self.assertEqual(self.compared(), (b'new-selfie', b'reference-selfie'))
        # The holder's namesake or twin: same data, another face.
        self.similarity(40)
        self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision()),
                         ('rejected', didit.NOT_SAME_PERSON_MESSAGE))

    def test_second_document_first_then_the_first_document_compares_with_that_session(self):
        _document(self.user, 'P-2', is_additional_document=True, document_type='passport')
        primary = _document(self.user, 'V-2', status='pending')
        with mock.patch.object(didit, '_didit_request', return_value=_decision(ANCHOR_SELFIE)) as fetch:
            self.assertEqual(didit._bind_to_person(primary, _extracted(document_type='national_id'), _decision()),
                             ('verified', ''))
        fetch.assert_called_once_with('GET', '/v3/session/session-P-2/decision/')
        self.assertEqual(self.compared(), (b'new-selfie', b'anchor-selfie'))
        self.similarity(40)
        with mock.patch.object(didit, '_didit_request', return_value=_decision(ANCHOR_SELFIE)):
            self.assertEqual(didit._bind_to_person(primary, _extracted(), _decision())[0], 'rejected')

    def test_two_second_documents_without_a_first_compare_with_the_earliest(self):
        _document(self.user, 'P-3', is_additional_document=True, document_type='passport')
        extra = _document(self.user, 'D-3', status='pending', is_additional_document=True)
        with mock.patch.object(didit, '_didit_request', return_value=_decision(ANCHOR_SELFIE)) as fetch:
            self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision()), ('verified', ''))
        fetch.assert_called_once_with('GET', '/v3/session/session-P-3/decision/')

    def test_names_that_do_not_match_reject_before_any_comparison(self):
        _document(self.user, 'V-4')
        extra = _document(self.user, 'P-4', status='pending', is_additional_document=True)
        self.assertEqual(didit._review_additional_document(
            extra, _extracted(verified_last_name='GOMEZ'), _decision())[0], 'rejected')
        self.rek.compare_faces.assert_not_called()

    def test_a_document_that_cannot_be_compared_now_stays_pending(self):
        primary = _document(self.user, 'V-5')
        FaceReference.objects.create(user=self.user, identity_verification=primary, s3_key='k', sha256='0' * 64,
                                     source='didit_liveness')
        extra = _document(self.user, 'P-5', status='pending', is_additional_document=True)
        self.rek.compare_faces.side_effect = RuntimeError('rekognition down')
        self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision()), ('pending', ''))
        self.assertIn(didit.SAME_FACE_RETRY_KEY, extra.risk_factors)  # retried hourly
        self.rek.compare_faces.side_effect = None
        # Nothing a retry of THIS session can fix: a new verification can.
        self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision(url='')),
                         ('rejected', didit.FACE_UNCONFIRMED_MESSAGE))
        from botocore.exceptions import ClientError
        self.rek.compare_faces.side_effect = ClientError(
            {'Error': {'Code': 'InvalidParameterException'}}, 'CompareFaces')
        self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision()),
                         ('rejected', didit.FACE_UNCONFIRMED_MESSAGE))
        self.rek.compare_faces.side_effect = ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision()), ('verified', ''))
        self.assertEqual(extra.risk_factors.get('same_face'), 'no_reference_selfie')

    def test_an_account_with_no_selfie_on_file_is_bound_by_identity_data_and_recorded(self):
        # Verified before selfies were kept, or Didit's media is gone: retrying
        # cannot help, so the rule from before applies, on the record.
        _document(self.user, 'P-6', is_additional_document=True)
        primary = _document(self.user, 'V-6', status='pending')
        with mock.patch.object(didit, '_didit_request', return_value={'liveness_checks': []}):
            self.assertEqual(didit._bind_to_person(primary, _extracted(), _decision()), ('verified', ''))
        self.assertEqual(primary.risk_factors.get('same_face'), 'no_reference_selfie')
        self.rek.compare_faces.assert_not_called()

    def test_the_accounts_kyc_selfie_stands_in_for_an_anchor_without_one(self):
        first = _document(self.user, 'P-13', is_additional_document=True)
        FaceReference.objects.create(user=self.user, identity_verification=_document(self.user, 'V-13'),
                                     s3_key='k', sha256='0' * 64, source='didit_liveness')
        primary = _document(self.user, 'V-14', status='pending')
        with mock.patch.object(didit, '_didit_request') as fetch:
            self.assertEqual(didit._same_face(first, _decision()), didit.FACE_MATCH)
        fetch.assert_not_called()
        self.assertEqual(self.compared(), (b'new-selfie', b'reference-selfie'))
        self.assertIsNotNone(primary)

    def test_waiting_documents_are_retried_for_a_week(self):
        recent = _document(self.user, 'P-15', status='pending', is_additional_document=True,
                           risk_factors={'didit': {'session_id': 's-recent'},
                                         didit.SAME_FACE_RETRY_KEY: timezone.now().isoformat()})
        _document(self.user, 'P-16', status='pending', is_additional_document=True,
                  risk_factors={'didit': {'session_id': 's-old'}, didit.SAME_FACE_RETRY_KEY:
                                (timezone.now() - timezone.timedelta(days=8)).isoformat()})
        _document(self.user, 'P-17', status='pending', is_additional_document=True,
                  risk_factors={'didit': {'session_id': 's-unrelated'}})
        with mock.patch.object(didit, 'sync_didit_session') as sync:
            self.assertEqual(didit.retry_pending_same_face(), 1)
        sync.assert_called_once_with(session_id='s-recent', expected_user=self.user)
        self.assertEqual(recent.status, 'pending')
        old = IdentityVerification.all_documents.get(document_number='P-16')
        # After the window: rejected with a way forward, never pending forever.
        self.assertEqual((old.status, old.rejected_reason), ('rejected', didit.FACE_UNCONFIRMED_MESSAGE))
        self.assertNotIn(didit.SAME_FACE_RETRY_KEY, old.risk_factors)

    def test_a_session_or_selfie_deleted_at_didit_counts_as_no_selfie_on_file(self):
        import requests as http
        _document(self.user, 'P-18', is_additional_document=True)
        primary = _document(self.user, 'V-18', status='pending')
        gone = didit.DiditAPIError('404')
        gone.__cause__ = http.HTTPError(response=SimpleNamespace(status_code=404))
        with mock.patch.object(didit, '_didit_request', side_effect=gone):
            self.assertEqual(didit._bind_to_person(primary, _extracted(), _decision()), ('verified', ''))
        self.assertEqual(primary.risk_factors.get('same_face'), 'no_reference_selfie')
        # A 503 is an outage: retried, never waved through.
        down = didit.DiditAPIError('503')
        down.__cause__ = http.HTTPError(response=SimpleNamespace(status_code=503))
        primary.risk_factors = {}
        with mock.patch.object(didit, '_didit_request', side_effect=down):
            self.assertEqual(didit._bind_to_person(primary, _extracted(), _decision()), ('pending', ''))

    def test_an_already_verified_document_is_not_compared_again(self):
        _document(self.user, 'V-7')
        extra = _document(self.user, 'P-7', is_additional_document=True)  # verified earlier
        self.rek.compare_faces.side_effect = RuntimeError('rekognition down')
        self.assertEqual(didit._review_additional_document(extra, _extracted(), _decision()), ('verified', ''))
        self.rek.compare_faces.assert_not_called()

    def test_a_full_sync_of_a_second_document_runs_the_comparison(self):
        primary = _document(self.user, 'V-8')
        FaceReference.objects.create(user=self.user, identity_verification=primary, s3_key='k', sha256='0' * 64,
                                     source='didit_liveness')
        row = _document(self.user, 'P-8', status='pending', is_additional_document=True,
                        risk_factors={'provider': 'didit', 'didit': {'session_id': 's-extra'},
                                      'document_request': {'id_country': '', 'document_types': ['ID', 'P']}})
        approved = {
            'session_id': 's-extra', 'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Ana', 'last_name': 'Perez', 'date_of_birth': '1990-01-01',
            'id_verifications': [{'nationality': 'VEN', 'document_type': 'Passport', 'document_number': 'P-8',
                                  'issuing_state': 'VEN', 'expiration_date': '2030-12-31'}],
            'liveness_checks': [{'reference_image': SELFIE}],
        }
        self.similarity(20)
        with mock.patch('security.didit.retrieve_didit_decision', return_value=approved), \
                mock.patch('security.didit._notify_verification_status_change'):
            didit.sync_didit_session(session_id='s-extra', expected_user=self.user)
        row.refresh_from_db()
        self.assertEqual((row.status, row.rejected_reason), ('rejected', didit.NOT_SAME_PERSON_MESSAGE))


@override_settings(FACE_STEP_UP_ENABLED=False)
class DuplicatedFaceHoldTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='dup-face', firebase_uid='dup-face')
        self.reviewer = get_user_model().objects.create_user(username='dup-reviewer', firebase_uid='dup-reviewer',
                                                             is_staff=True)

    def check(self):
        from security.identity_reuse import outgoing_identity_restriction
        return outgoing_identity_restriction(self.user)

    def test_the_warning_is_read_from_the_liveness_and_face_match_nodes(self):
        payload = {'liveness_checks': [{'warnings': [{'risk': 'POSSIBLE_DUPLICATED_FACE'}]}],
                   'face_matches': [{'warnings': [{'risk': 'DUPLICATED_FACE'}, {'risk': 'LOW_FACE_MATCH'}]}]}
        self.assertEqual(didit.duplicated_face_risks(payload), ['DUPLICATED_FACE', 'POSSIBLE_DUPLICATED_FACE'])
        self.assertEqual(didit.duplicated_face_risks({'liveness_checks': [{'warnings': []}]}), [])

    def test_a_flag_on_either_document_holds_the_account_until_support_releases_it(self):
        for primary_flagged in (True, False):
            with self.subTest(primary_flagged=primary_flagged):
                IdentityVerification.all_documents.filter(user=self.user).delete()
                SuspiciousActivity.objects.filter(user=self.user).delete()
                flag = {'provider': 'didit', 'duplicated_face': {'risks': ['DUPLICATED_FACE'], 'matched_user_ids': []}}
                _document(self.user, 'V-9', risk_factors=flag if primary_flagged else {'provider': 'didit'})
                _document(self.user, 'P-9', is_additional_document=True,
                          risk_factors={'provider': 'didit'} if primary_flagged else flag)
                self.assertEqual(self.check(), MESSAGE)
                case = SuspiciousActivity.objects.get(user=self.user, detection_data__trigger='didit_duplicated_face')
                case.status, case.investigated_by = 'dismissed', self.reviewer
                case.investigation_notes = 'Twin sibling; separate people.'
                case.save()
                self.assertEqual(self.check(), '')

    def test_an_unverified_or_company_verification_does_not_hold(self):
        flag = {'provider': 'didit', 'duplicated_face': {'risks': ['DUPLICATED_FACE'], 'matched_user_ids': []}}
        _document(self.user, 'V-10', status='rejected', risk_factors=flag)
        _document(self.user, 'J-10', risk_factors={**flag, 'account_type': 'business'})
        self.assertEqual(self.check(), '')

    def sync_with_duplicate(self, others, number='P-11'):
        row = _document(self.user, number, status='pending',
                        risk_factors={'provider': 'didit', 'didit': {'session_id': f's-{number}'}})
        approved = {
            'session_id': f's-{number}', 'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Ana', 'last_name': 'Perez', 'date_of_birth': '1990-01-01',
            'id_verifications': [{'nationality': 'VEN', 'document_type': 'Passport', 'document_number': number,
                                  'issuing_state': 'VEN', 'expiration_date': '2030-12-31'}],
            'liveness_checks': [{'warnings': [{'risk': 'DUPLICATED_FACE', 'log_type': 'information'}]}],
        }
        with mock.patch('security.didit.retrieve_didit_decision', return_value=approved), \
                mock.patch('security.didit._notify_verification_status_change'), \
                mock.patch('security.didit._store_face_reference'), \
                mock.patch('security.didit.other_users_with_face', return_value=others) as search:
            didit.sync_didit_session(session_id=f's-{number}', expected_user=self.user)
            didit.sync_didit_session(session_id=f's-{number}', expected_user=self.user)
        self.assertEqual(search.call_count, 1)  # once per session
        row.refresh_from_db()
        return row

    def test_the_persons_own_kyb_or_edd_sessions_are_not_a_duplicate(self):
        row = self.sync_with_duplicate([])
        self.assertNotIn('duplicated_face', row.risk_factors)
        self.assertEqual(self.check(), '')

    def test_another_users_face_holds_and_links_that_user(self):
        other = get_user_model().objects.create_user(username='dup-other', firebase_uid='dup-other')
        row = self.sync_with_duplicate([other.pk])
        self.assertEqual(row.risk_factors['duplicated_face'],
                         {'risks': ['DUPLICATED_FACE'], 'matched_user_ids': [other.pk]})
        self.assertEqual(self.check(), MESSAGE)
        case = SuspiciousActivity.objects.get(user=self.user, detection_data__trigger='didit_duplicated_face')
        self.assertEqual(list(case.related_users.values_list('pk', flat=True)), [other.pk])

    def test_a_face_search_that_cannot_run_still_holds(self):
        row = self.sync_with_duplicate(None)
        self.assertIn('duplicated_face', row.risk_factors)
        self.assertEqual(self.check(), MESSAGE)

    def test_face_search_leaves_out_the_persons_own_sessions_and_weak_matches(self):
        body = {'face_search': {'matches': [
            {'vendor_data': f'{{"user_id":{self.user.id},"account_type":"business","business_id":"9"}}',
             'similarity_percentage': 99},
            {'vendor_data': '{"user_id":42,"account_type":"personal"}', 'similarity_percentage': 93},
            {'vendor_data': '{"user_id":43,"account_type":"personal"}', 'similarity_percentage': 50},
            {'vendor_data': 'imported-row-7', 'similarity_percentage': 91},
        ]}}
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)
        with override_settings(DIDIT_API_KEY='key'), \
                mock.patch('security.face_step_up._download_selfie', return_value=(b'img', 'image/jpeg')), \
                mock.patch('security.didit.requests.post', return_value=response) as post:
            self.assertEqual(didit.other_users_with_face(self.user, _decision()), [0, 42])
        self.assertNotIn('Content-Type', post.call_args.kwargs['headers'])  # multipart
        with mock.patch('security.face_step_up._download_selfie', side_effect=didit.requests.ConnectionError()):
            self.assertIsNone(didit.other_users_with_face(self.user, _decision()))

    def test_the_sync_records_the_flag_and_keeps_it(self):
        row = _document(self.user, 'P-11', status='pending',
                        risk_factors={'provider': 'didit', 'didit': {'session_id': 's-dup'}})
        approved = {
            'session_id': 's-dup', 'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Ana', 'last_name': 'Perez', 'date_of_birth': '1990-01-01',
            'id_verifications': [{'nationality': 'VEN', 'document_type': 'Passport', 'document_number': 'P-11',
                                  'issuing_state': 'VEN', 'expiration_date': '2030-12-31'}],
            'liveness_checks': [{'warnings': [{'risk': 'DUPLICATED_FACE', 'log_type': 'information'}]}],
        }
        with mock.patch('security.didit.retrieve_didit_decision', return_value=approved), \
                mock.patch('security.didit._notify_verification_status_change'), \
                mock.patch('security.didit._store_face_reference'), \
                mock.patch('security.didit.other_users_with_face', return_value=[0]):
            didit.sync_didit_session(session_id='s-dup', expected_user=self.user)
            approved['liveness_checks'] = [{'warnings': []}]
            didit.sync_didit_session(session_id='s-dup', expected_user=self.user)
        row.refresh_from_db()
        self.assertEqual((row.status, row.risk_factors.get('duplicated_face')),
                         ('verified', {'risks': ['DUPLICATED_FACE'], 'matched_user_ids': [0]}))
        self.assertEqual(self.check(), MESSAGE)

    def test_admin_bulk_dismissal_releases_a_duplicated_face_case_with_notes(self):
        from django.contrib.admin.sites import AdminSite
        from security.admin import SuspiciousActivityAdmin
        _document(self.user, 'V-12', risk_factors={'provider': 'didit', 'duplicated_face': {'risks': ['DUPLICATED_FACE']}})
        self.check()
        cases = SuspiciousActivity.objects.filter(user=self.user, detection_data__trigger='didit_duplicated_face')
        admin = SuspiciousActivityAdmin(SuspiciousActivity, AdminSite())
        with mock.patch.object(admin, 'message_user'):
            cases.update(investigation_notes='Reviewed: different people.')
            admin.mark_as_dismissed(SimpleNamespace(user=self.reviewer), cases)
        self.assertEqual(self.check(), '')


def _response(status=200, body=None):
    import json
    content = b'' if body is None else json.dumps(body).encode()
    return SimpleNamespace(status_code=status, content=content, json=lambda: json.loads(content))


@override_settings(DIDIT_API_KEY='key', DIDIT_API_URL='https://didit.test')
class FaceBlocklistTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='blocked-face', firebase_uid='blocked-face')
        _document(self.user, 'V-20')
        _document(self.user, 'P-20', is_additional_document=True)
        _document(self.user, 'J-20', risk_factors={'account_type': 'business', 'didit': {'session_id': 'kyb'}})
        _document(self.user, 'R-20', status='rejected')
        self.calls = []

        def request(method, url, **kwargs):
            self.calls.append((method, url.replace('https://didit.test', ''), kwargs.get('json')))
            if method == 'GET':
                return _response(body={'results': [{'uuid': 'face-list', 'list_type': 'blocklist',
                                                    'entry_type': 'face'}]})
            if method == 'POST':
                return _response(201, {'uuid': f"entry-{kwargs['json']['reference_session_id']}"})
            return _response(204)
        patcher = mock.patch('security.didit_blocklist.requests.request', side_effect=request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sync(self):
        from security.didit_blocklist import sync_face_blocklist
        sync_face_blocklist(self.user.pk)

    def ban(self, **kwargs):
        with mock.patch('security.tasks.sync_face_blocklist.delay'):
            return UserBan.objects.create(user=self.user, reason='fraud', **{'ban_type': 'permanent', **kwargs})

    def test_a_permanent_ban_blocklists_every_verified_personal_face_once(self):
        self.ban()
        self.sync()
        posts = [call for call in self.calls if call[0] == 'POST']
        self.assertEqual(sorted(call[2]['reference_session_id'] for call in posts), ['session-P-20', 'session-V-20'])
        self.assertTrue(all(call[1] == '/v3/lists/face-list/entries/' for call in posts))
        self.calls.clear()
        self.sync()
        self.assertEqual(self.calls, [])  # nothing missing: no Didit call at all

    def test_lifting_the_ban_removes_the_entries(self):
        ban = self.ban()
        self.sync()
        with mock.patch('security.tasks.sync_face_blocklist.delay'):
            ban.soft_delete()
        self.calls.clear()
        self.sync()
        self.assertEqual(sorted(call[1] for call in self.calls if call[0] == 'DELETE'),
                         ['/v3/lists/face-list/entries/entry-session-P-20/',
                          '/v3/lists/face-list/entries/entry-session-V-20/'])
        self.assertFalse(DiditFaceBlocklistEntry.objects.filter(removed_at__isnull=True).exists())

    def test_temporary_and_partial_bans_do_not_blocklist(self):
        for ban_type in ('temporary', 'trading', 'withdrawal'):
            self.ban(ban_type=ban_type)
        self.sync()
        self.assertEqual(self.calls, [])

    def test_a_ban_queues_the_sync_after_commit(self):
        with mock.patch('security.tasks.sync_face_blocklist.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            UserBan.objects.create(user=self.user, ban_type='permanent', reason='fraud')
        delay.assert_called_once_with(self.user.pk)

    def test_the_reconcile_catches_up_and_reports_failures(self):
        from security.didit_blocklist import reconcile_face_blocklist
        self.ban()
        self.assertEqual(reconcile_face_blocklist(), 0)
        self.assertEqual(DiditFaceBlocklistEntry.objects.filter(removed_at__isnull=True).count(), 2)
        with mock.patch('security.didit_blocklist.sync_face_blocklist', side_effect=didit.DiditAPIError('down')):
            self.assertEqual(reconcile_face_blocklist(), 1)

    def test_a_didit_error_leaves_nothing_recorded(self):
        self.ban()
        with mock.patch('security.didit_blocklist.requests.request', return_value=_response(500)):
            with self.assertRaises(didit.DiditAPIError):
                self.sync()
        self.assertFalse(DiditFaceBlocklistEntry.objects.exists())

    def test_lifting_the_ban_also_removes_an_entry_whose_answer_was_lost(self):
        ban = self.ban()
        with mock.patch('security.tasks.sync_face_blocklist.delay'):
            ban.soft_delete()
        listed = {'results': [{'uuid': 'orphan', 'display_label': f'confio-user-{self.user.pk}'},
                              {'uuid': 'someone-else', 'display_label': 'confio-user-999999'}]}

        def request(method, url, **kwargs):
            self.calls.append((method, url.replace('https://didit.test', ''), kwargs.get('json')))
            if '/entries/?search=' in url:
                return _response(body=listed)
            if method == 'GET':
                return _response(body={'results': [{'uuid': 'face-list'}]})
            return _response(204)
        with mock.patch('security.didit_blocklist.requests.request', side_effect=request):
            self.sync()
        self.assertEqual([call[1] for call in self.calls if call[0] == 'DELETE'],
                         ['/v3/lists/face-list/entries/orphan/'])

    def test_one_refused_session_does_not_keep_the_others_off(self):
        self.ban()

        def request(method, url, **kwargs):
            self.calls.append((method, url, kwargs.get('json')))
            if method == 'GET':
                return _response(body={'results': [{'uuid': 'face-list'}]})
            if kwargs['json']['reference_session_id'] == 'session-P-20':
                return _response(400)
            return _response(201, {'uuid': 'entry-v'})
        with mock.patch('security.didit_blocklist.requests.request', side_effect=request):
            with self.assertRaises(didit.DiditAPIError):
                self.sync()
        self.assertEqual(list(DiditFaceBlocklistEntry.objects.values_list('session_id', flat=True)),
                         ['session-V-20'])

    def test_an_entry_already_removed_in_didit_is_not_an_error(self):
        ban = self.ban()
        self.sync()
        with mock.patch('security.tasks.sync_face_blocklist.delay'):
            ban.soft_delete()
        with mock.patch('security.didit_blocklist.requests.request', return_value=_response(404)):
            self.sync()
        self.assertFalse(DiditFaceBlocklistEntry.objects.filter(removed_at__isnull=True).exists())
