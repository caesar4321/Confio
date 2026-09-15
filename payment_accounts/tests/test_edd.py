import json
from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils import timezone

from payment_accounts import edd
from payment_accounts.models import LimitIncreaseRequest, ProviderProfile
from payment_accounts.services import PaymentAccountError
from security.models import IdentityVerification
from users.models import Account, User

ADDRESS = SimpleNamespace(address_street='Calle 1', address_neighborhood='Centro', address_city='Bogota',
                          address_state='Cundinamarca', address_zip_code='110111', address_country='COL')


class EddTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='edd-user', firebase_uid='edd-user')
        self.owner = Account.objects.create(user=self.user, account_type='personal')
        self.identity = IdentityVerification.objects.create(
            user=self.user, status='verified', verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth=date(1990, 1, 1), document_type='national_id', document_number='CC-7',
            document_issuing_country='COL', risk_factors={'provider': 'didit'}, verified_at=timezone.now())
        self.addCleanup(mock.patch.stopall)
        mock.patch('ramps.schema._build_effective_ramp_address_snapshot', return_value=ADDRESS).start()
        self.complete = mock.patch('ramps.schema._is_ramp_address_complete', return_value=True).start()
        self.session_patch = mock.patch('security.didit.create_didit_workflow_session',
                                        return_value={'session_id': 'edd-1', 'session_token': 'token'})
        self.session = self.session_patch.start()

    def start(self, **overrides):
        args = dict(income_type='employed', occupation='Contadora', expected_monthly_usd='25000',
                    source_of_funds='salary')
        args.update(overrides)
        return edd.start(self.owner, **args)

    def test_start_opens_one_proof_of_address_and_questionnaire_session(self):
        row, session = self.start()
        kwargs = self.session.call_args.kwargs
        self.assertEqual(kwargs['workflow_id'], settings.DIDIT_EDD_WORKFLOW_ID)
        self.assertEqual(kwargs['expected_details'], {
            'first_name': 'Ana', 'last_name': 'Perez', 'poa_country': 'COL',
            'address': 'Calle 1, Centro, Bogota, Cundinamarca, 110111'})
        self.assertEqual((row.status, row.didit_session_id, session['session_token']), ('started', 'edd-1', 'token'))

    def test_resuming_reuses_the_started_request(self):
        first, _ = self.start()
        again, _ = self.start(occupation='Comerciante')
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(again.occupation, 'Comerciante')
        self.assertEqual(LimitIncreaseRequest.objects.count(), 1)

    def test_retrying_after_more_info_takes_over_the_resumed_session(self):
        first, _ = self.start()
        first.status = 'needs_more_info'
        first.save(update_fields=['status'])
        again, _ = self.start()  # Didit resumes the same unfinished 'edd-1' session
        self.assertNotEqual(again.pk, first.pk)
        self.assertEqual(again.didit_session_id, 'edd-1')
        first.refresh_from_db()
        self.assertIsNone(first.didit_session_id)
        self.assertEqual(self.start()[0].pk, again.pk)  # retrying again resumes, never fails

    def test_a_delayed_start_never_steals_the_session_from_a_newer_request(self):
        newer = {}

        def ops_closes_it_and_a_newer_request_takes_the_session(**kwargs):
            request = LimitIncreaseRequest.objects.get(confio_account=self.owner)
            request.status = 'needs_more_info'
            request.save(update_fields=['status'])
            newer['row'] = LimitIncreaseRequest.objects.create(
                confio_account=self.owner, provider='infinia', income_type='employed', occupation='Contadora',
                expected_monthly_usd='25000', source_of_funds='salary', didit_session_id='edd-1')
            return {'session_id': 'edd-1', 'session_token': 'token'}
        self.session.side_effect = ops_closes_it_and_a_newer_request_takes_the_session
        with self.assertRaisesRegex(PaymentAccountError, 'cambió'):
            self.start()
        newer['row'].refresh_from_db()
        self.assertEqual(newer['row'].didit_session_id, 'edd-1')

    def test_a_didit_failure_is_explained_and_retrying_resumes_the_request(self):
        from security.didit import DiditAPIError
        self.session.side_effect = DiditAPIError('timeout')
        with self.assertRaisesRegex(PaymentAccountError, 'Intenta de nuevo'):
            self.start()
        first = LimitIncreaseRequest.objects.get(confio_account=self.owner)
        self.session.side_effect = None
        row, _ = self.start()
        self.assertEqual((row.pk, row.didit_session_id), (first.pk, 'edd-1'))

    def test_an_amount_beyond_the_field_is_refused_as_input(self):
        with self.assertRaisesRegex(PaymentAccountError, 'monto válido'):
            self.start(expected_monthly_usd='1000000000000000000')
        self.assertFalse(LimitIncreaseRequest.objects.exists())

    def test_a_request_in_review_blocks_another(self):
        row, _ = self.start()
        row.status = 'in_review'
        row.save(update_fields=['status'])
        with self.assertRaisesRegex(PaymentAccountError, 'en revisión'):
            self.start()

    def test_needs_the_declared_address_and_a_personal_account(self):
        self.complete.return_value = False
        with self.assertRaisesRegex(PaymentAccountError, 'Completa tu dirección'):
            self.start()
        self.owner.account_type = 'business'
        with self.assertRaisesRegex(PaymentAccountError, 'empresas'):
            self.start()
        self.session.assert_not_called()

    def decision(self, status, **extra):
        return {'status': status, 'vendor_data': json.dumps({'user_id': self.user.id, 'account_type': 'personal'}),
                **extra}

    def test_sync_maps_didit_status_and_never_walks_back(self):
        row, _ = self.start()
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.decision('In Review')):
            row = edd.sync_edd_session('edd-1')
        self.assertEqual(row.status, 'in_review')
        self.assertIsNotNone(row.submitted_at)
        row.status = 'forwarded'
        row.save(update_fields=['status'])
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.decision('Declined')):
            self.assertEqual(edd.sync_edd_session('edd-1').status, 'forwarded')

    def test_declined_session_explains_itself(self):
        self.start()
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.decision('Declined')):
            row = edd.sync_edd_session('edd-1')
        self.assertEqual(row.status, 'rejected')
        self.assertIn('No pudimos validar', row.user_message)

    def test_a_passport_only_holder_can_ask_for_more(self):
        self.identity.status = 'pending'  # no verified primary document
        self.identity.save(update_fields=['status'])
        IdentityVerification.all_documents.create(
            user=self.user, status='verified', verified_first_name='Ana', verified_last_name='Perez',
            verified_date_of_birth=date(1990, 1, 1), document_type='passport', document_number='P-7',
            document_issuing_country='KOR', risk_factors={'provider': 'didit'}, verified_at=timezone.now(),
            is_additional_document=True)
        row, _ = self.start()
        self.assertEqual(row.status, 'started')
        self.assertEqual(self.session.call_args.kwargs['expected_details']['first_name'], 'Ana')

    def test_a_late_in_progress_answer_never_reopens_a_submitted_request(self):
        self.start()
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.decision('Approved')):
            row = edd.sync_edd_session('edd-1')
        self.assertEqual(row.status, 'submitted')
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.decision('In Progress')):
            row = edd.sync_edd_session('edd-1')
        self.assertEqual((row.status, row.didit_status), ('submitted', 'Approved'))

    def test_sync_asks_didit_only_while_holding_the_request_lock(self):
        # A reviewer's save locks the same row, so it waits for the sync instead
        # of being overwritten, and a slower sync can never land after a newer one.
        self.start()
        order = []
        queryset = LimitIncreaseRequest.objects.get_queryset

        def lock(*args, **kwargs):
            order.append('lock')
            return queryset().select_for_update(*args, **kwargs)

        def fetch(**kwargs):
            order.append('didit')
            return self.decision('In Review')
        with mock.patch.object(LimitIncreaseRequest.objects, 'select_for_update', side_effect=lock), \
                mock.patch('security.didit.retrieve_didit_decision', side_effect=fetch):
            synced = edd.sync_edd_session('edd-1')
        self.assertEqual(order, ['lock', 'didit'])
        self.assertEqual(synced.status, 'in_review')

    def test_identity_sync_refuses_an_edd_session(self):
        from security.didit import DiditAPIError, sync_didit_session
        self.start()
        with mock.patch('security.didit.retrieve_didit_decision') as retrieve:
            with self.assertRaises(DiditAPIError):
                sync_didit_session(session_id='edd-1', expected_user=self.user)
        retrieve.assert_not_called()
        self.assertEqual(IdentityVerification.all_documents.filter(user=self.user).count(), 1)

    def test_stored_evidence_keeps_no_document_links(self):
        self.start()
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.files_decision()):
            row = edd.sync_edd_session('edd-1')
        self.assertNotIn('http', json.dumps(row.evidence))
        self.assertEqual(row.evidence['poa_verifications'], [{'status': 'Approved'}])

    def files_decision(self):
        return self.decision('Approved', poa_verifications=[{'status': 'Approved', 'document_file': 'https://m/poa.pdf'}],
                             questionnaire_responses=[{'sections': [{'items': [
                                 {'value': 'income_proof', 'answer': {'files': ['https://m/payslip.pdf']}},
                                 {'value': 'bank_statements', 'answer': {'files': ['https://m/statement.pdf']}},
                             ]}]}])

    def test_forward_uploads_address_and_funds_to_the_owner(self):
        row, _ = self.start()
        row.status = 'submitted'
        row.save(update_fields=['status'])
        ProviderProfile.objects.create(confio_account=self.owner, provider='infinia', owner_type='individual',
                                       status='active', identity_verification=self.identity,
                                       provider_owner_id='owner-1')
        client = mock.Mock()
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.files_decision()), \
                mock.patch('payment_accounts.compliance._upload_document',
                           return_value=('doc-address', {'a': 1})) as upload, \
                mock.patch('payment_accounts.compliance._upload_bundle',
                           return_value=('doc-funds', {'b': 2})) as bundle:
            row = edd.forward_to_provider(row, client=client)
        self.assertEqual(upload.call_args.kwargs['front_url'], 'https://m/poa.pdf')
        # Infinia keeps one source-of-funds document: every file goes, as one.
        self.assertEqual(bundle.call_args.kwargs['urls'], ['https://m/payslip.pdf', 'https://m/statement.pdf'])
        client.update_owner.assert_called_once_with('owner-1', {'individual': {
            'proof_of_address_document_id': 'doc-address', 'source_of_funds_document_id': 'doc-funds'}})
        self.assertEqual(row.status, 'forwarded')
        self.assertEqual(row.provider_documents['source_of_funds_files'], 2)

    def test_several_evidence_files_become_one_pdf(self):
        from io import BytesIO

        from PIL import Image
        from pypdf import PdfReader

        from payment_accounts.compliance import EvidenceFile, _combined_pdf

        def blank(fmt):
            out = BytesIO()
            Image.new('RGB', (40, 40), 'white').save(out, fmt)
            return out.getvalue()
        files = [EvidenceFile(url='u1', content=blank('PDF'), content_type='application/pdf', sha256='a'),
                 EvidenceFile(url='u2', content=blank('PNG'), content_type='image/png', sha256='b')]
        self.assertEqual(len(PdfReader(BytesIO(_combined_pdf(files))).pages), 2)

    def test_forward_refuses_a_session_without_the_files(self):
        from payment_accounts.clients import ComplianceHandoffError
        row, _ = self.start()
        row.status = 'submitted'
        row.save(update_fields=['status'])
        ProviderProfile.objects.create(confio_account=self.owner, provider='infinia', owner_type='individual',
                                       status='active', identity_verification=self.identity,
                                       provider_owner_id='owner-2')
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.decision('Approved')):
            with self.assertRaises(ComplianceHandoffError):
                edd.forward_to_provider(row, client=mock.Mock())

    def submitted_with_owner(self, owner_id):
        row, _ = self.start()
        row.status = 'submitted'
        row.save(update_fields=['status'])
        ProviderProfile.objects.create(confio_account=self.owner, provider='infinia', owner_type='individual',
                                       status='active', identity_verification=self.identity,
                                       provider_owner_id=owner_id)
        return row

    def test_forward_stops_if_the_request_was_rejected_meanwhile(self):
        row = self.submitted_with_owner('owner-3')
        client = mock.Mock()

        def reviewer_rejects_during_the_call(**kwargs):
            LimitIncreaseRequest.objects.filter(pk=row.pk).update(status='rejected')
            return self.files_decision()
        with mock.patch('security.didit.retrieve_didit_decision', side_effect=reviewer_rejects_during_the_call), \
                mock.patch('payment_accounts.compliance._upload_document', return_value=('doc', {})), \
                mock.patch('payment_accounts.compliance._upload_bundle', return_value=('doc', {})):
            with self.assertRaisesRegex(PaymentAccountError, 'cambió'):
                edd.forward_to_provider(row, client=client)
        client.update_owner.assert_not_called()
        self.assertEqual(LimitIncreaseRequest.objects.get(pk=row.pk).status, 'rejected')

    def test_an_admin_save_never_undoes_a_forward_done_meanwhile(self):
        from django.contrib import admin as django_admin
        from payment_accounts.admin import LimitIncreaseRequestAdmin
        row = self.submitted_with_owner('owner-5')
        stale = LimitIncreaseRequest.objects.get(pk=row.pk)  # the reviewer's page
        LimitIncreaseRequest.objects.filter(pk=row.pk).update(
            status='forwarded', provider_documents={'proof_of_address_document_id': 'd1'})
        model_admin = LimitIncreaseRequestAdmin(LimitIncreaseRequest, django_admin.site)
        stale.reviewer_note = 'Llamé al usuario.'
        model_admin.save_model(None, stale, SimpleNamespace(changed_data=['reviewer_note'],
                                                            initial={'status': 'submitted'}), True)
        saved = LimitIncreaseRequest.objects.get(pk=row.pk)
        self.assertEqual((saved.status, saved.reviewer_note), ('forwarded', 'Llamé al usuario.'))
        self.assertEqual(saved.provider_documents, {'proof_of_address_document_id': 'd1'})
        # A status decided on the stale page is refused.
        stale.status = 'rejected'
        with mock.patch.object(model_admin, 'message_user') as told:
            model_admin.save_model(None, stale, SimpleNamespace(changed_data=['status'],
                                                                initial={'status': 'submitted'}), True)
        told.assert_called_once()
        self.assertEqual(LimitIncreaseRequest.objects.get(pk=row.pk).status, 'forwarded')

    def test_a_note_saved_from_a_stale_page_never_reverts_the_status(self):
        from django.contrib import admin as django_admin
        from payment_accounts.admin import LimitIncreaseRequestAdmin
        row = self.submitted_with_owner('owner-6')  # the reviewer's page shows 'submitted'
        LimitIncreaseRequest.objects.filter(pk=row.pk).update(status='forwarded')  # a forward lands meanwhile
        posted = LimitIncreaseRequest.objects.get(pk=row.pk)  # the POST re-reads the instance...
        posted.status = 'submitted'  # ...and applies the displayed, untouched status
        posted.reviewer_note = 'Revisado.'
        form = SimpleNamespace(changed_data=['status', 'reviewer_note'], initial={'status': 'forwarded'},
                               shown_status=lambda: 'submitted')
        LimitIncreaseRequestAdmin(LimitIncreaseRequest, django_admin.site).save_model(None, posted, form, True)
        saved = LimitIncreaseRequest.objects.get(pk=row.pk)
        self.assertEqual((saved.status, saved.reviewer_note), ('forwarded', 'Revisado.'))

    def test_the_shown_status_is_signed(self):
        from payment_accounts.admin import LimitIncreaseRequestAdminForm
        row = self.submitted_with_owner('owner-7')
        token = LimitIncreaseRequestAdminForm(instance=row).fields['loaded_status'].initial
        self.assertEqual(LimitIncreaseRequestAdminForm(data={'loaded_status': token}, instance=row).shown_status(),
                         'submitted')
        self.assertIsNone(
            LimitIncreaseRequestAdminForm(data={'loaded_status': token + 'x'}, instance=row).shown_status())

    def test_forward_refuses_a_declined_session(self):
        row = self.submitted_with_owner('owner-4')
        client = mock.Mock()
        with mock.patch('security.didit.retrieve_didit_decision',
                        return_value={**self.files_decision(), 'status': 'Declined'}):
            with self.assertRaisesRegex(PaymentAccountError, 'rechazó'):
                edd.forward_to_provider(row, client=client)
        client.update_owner.assert_not_called()

    def test_webhook_routes_edd_sessions_away_from_identity(self):
        from security.views import didit_webhook
        self.start()
        request = RequestFactory().post('/api/didit/webhook/', data=json.dumps({'session_id': 'edd-1'}),
                                        content_type='application/json')
        with mock.patch('security.views.verify_didit_webhook_signature', return_value=True), \
                mock.patch('payment_accounts.edd.sync_edd_session') as sync_edd, \
                mock.patch('security.views.sync_didit_session') as sync_identity:
            response = didit_webhook(request)
        self.assertEqual(response.status_code, 200)
        sync_edd.assert_called_once_with('edd-1')
        sync_identity.assert_not_called()


    def test_submission_dispatches_after_commit_without_confio_review(self):
        self.start()
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.files_decision()), \
                mock.patch('payment_accounts.tasks.forward_edd.delay') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                row = edd.sync_edd_session('edd-1')
                dispatch.assert_not_called()
            dispatch.assert_called_once_with(row.pk)

    def test_pending_didit_review_is_automatically_forwarded(self):
        row = self.submitted_with_owner('automatic')
        from payment_accounts.tasks import forward_edd
        with mock.patch('security.didit.retrieve_didit_decision',
                        return_value={**self.files_decision(), 'status': 'In Review'}), \
                mock.patch('payment_accounts.compliance._upload_document', return_value=('address', {})), \
                mock.patch('payment_accounts.compliance._upload_bundle', return_value=('funds', {})), \
                mock.patch('payment_accounts.clients.InfiniaClient') as client:
            self.assertEqual(forward_edd.run(row.pk), 'forwarded')
            self.assertEqual(forward_edd.run(row.pk), 'forwarded')
        client.return_value.update_owner.assert_called_once()

    def test_missing_bank_statements_are_not_forwarded(self):
        row = self.submitted_with_owner('incomplete')
        decision = self.files_decision()
        decision['questionnaire_responses'][0]['sections'][0]['items'].pop()
        from payment_accounts.clients import ComplianceHandoffError
        with mock.patch('security.didit.retrieve_didit_decision', return_value=decision):
            with self.assertRaises(ComplianceHandoffError):
                edd.forward_to_provider(row, client=mock.Mock())

    def test_reconciler_recovers_failed_dispatch_and_link(self):
        row = self.submitted_with_owner('retry')
        from payment_accounts.tasks import reconcile_edd
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.files_decision()), \
                mock.patch('payment_accounts.compliance._upload_document', return_value=('address', {})), \
                mock.patch('payment_accounts.compliance._upload_bundle', return_value=('funds', {})), \
                mock.patch('payment_accounts.clients.InfiniaClient') as client, \
                mock.patch('payment_accounts.tasks.forward_edd.delay') as dispatch:
            client.return_value.update_owner.side_effect = RuntimeError('offline')
            self.assertEqual(reconcile_edd(), 0)
            row.refresh_from_db()
            self.assertEqual(row.status, 'submitted')
            client.return_value.update_owner.side_effect = None
            self.assertEqual(reconcile_edd(), 1)
            self.assertEqual(reconcile_edd(), 0)
            dispatch.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, 'forwarded')


    def test_self_declared_owner_receives_requested_monthly_volume(self):
        row = self.submitted_with_owner('volume')
        ProviderProfile.objects.filter(confio_account=self.owner).update(kyc_mode='SELF_DECLARED')
        client = mock.Mock()
        with mock.patch('security.didit.retrieve_didit_decision', return_value=self.files_decision()), \
                mock.patch('payment_accounts.compliance._upload_document', return_value=('address', {})), \
                mock.patch('payment_accounts.compliance._upload_bundle', return_value=('funds', {})):
            edd.forward_to_provider(row, client=client)
        self.assertEqual(client.update_owner.call_args.args[1]['individual']['expected_monthly_volume_usd'], 25000)


    def test_forwarded_request_allows_fresh_evidence_without_manual_closure(self):
        first, _ = self.start()
        first.status = 'forwarded'
        first.save(update_fields=['status'])
        self.session.return_value = {'session_id': 'edd-2', 'session_token': 'new'}
        second, _ = self.start()
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(self.session.call_args.kwargs['session_reference'], str(second.internal_id))
        first.refresh_from_db()
        self.assertEqual(first.didit_session_id, 'edd-1')

    def test_new_request_never_takes_evidence_from_a_forwarded_request(self):
        first, _ = self.start()
        first.status = 'forwarded'
        first.save(update_fields=['status'])
        with self.assertRaises(PaymentAccountError):
            self.start()  # Provider erroneously returns the earlier session.
        first.refresh_from_db()
        self.assertEqual(first.didit_session_id, 'edd-1')

    def test_edd_session_reference_is_stable_and_different_per_request(self):
        # Exercise the real helper after releasing this test's session mock.
        self.session_patch.stop()
        from security.didit import create_didit_workflow_session
        with mock.patch('security.didit._start_session', return_value={}) as create:
            for ref in ('request-a', 'request-a', 'request-b'):
                create_didit_workflow_session(user=self.user, workflow_id='edd', session_reference=ref)
        vendors = [json.loads(call.args[0]['vendor_data']) for call in create.call_args_list]
        self.assertEqual(vendors[0], vendors[1])
        self.assertNotEqual(vendors[0], vendors[2])
        self.assertEqual(str(vendors[0]['user_id']), str(self.user.pk))

    def test_task_errors_do_not_expose_signed_document_urls(self):
        import traceback
        from payment_accounts.tasks import forward_edd
        row = self.submitted_with_owner('private')
        signed = 'https://media.example/document?signature=private-token'
        def fail(_row):
            try:
                raise RuntimeError(signed)
            except RuntimeError as exc:
                raise PaymentAccountError('Download failed') from exc
        with mock.patch('payment_accounts.edd.forward_to_provider', side_effect=fail), \
                mock.patch.object(forward_edd, 'retry', side_effect=lambda **kwargs: (_ for _ in ()).throw(kwargs['exc'])):
            try:
                forward_edd.run(row.pk)
            except PaymentAccountError:
                output = traceback.format_exc()
            else:
                self.fail('Expected upload failure')
        self.assertNotIn(signed, output)
        self.assertIn('retry pending', output)

    def test_reconcile_errors_do_not_log_signed_document_urls(self):
        from payment_accounts.tasks import reconcile_edd
        self.submitted_with_owner('private-logs')
        with mock.patch('payment_accounts.edd.sync_edd_session', side_effect=RuntimeError('https://media/?signature=secret')), \
                self.assertLogs('payment_accounts.tasks', level='WARNING') as logs:
            reconcile_edd()
        self.assertNotIn('signature', str(logs.output))


class EddHandoffMigrationTests(TransactionTestCase):
    def test_migration_allows_completed_history_but_only_one_pending_request(self):
        import importlib
        from django.apps import apps
        from django.db import connection, models, IntegrityError, transaction
        from django.db.migrations.state import ProjectState
        current = next(c for c in LimitIncreaseRequest._meta.constraints if c.name == 'limit_increase_one_open_uniq')
        old = models.UniqueConstraint(fields=('confio_account',),
            condition=models.Q(status__in=['started', 'submitted', 'in_review', 'forwarded']),
            name=current.name)
        with connection.schema_editor() as editor:
            editor.remove_constraint(LimitIncreaseRequest, current)
            editor.add_constraint(LimitIncreaseRequest, old)
        state = ProjectState.from_apps(apps)
        state.models['payment_accounts', 'limitincreaserequest'].options['constraints'] = [old]
        migration = importlib.import_module('payment_accounts.migrations.0022_edd_forwarded_terminal').Migration
        with connection.schema_editor() as editor:
            for operation in migration.operations:
                before = state.clone()
                operation.state_forwards('payment_accounts', state)
                operation.database_forwards('payment_accounts', editor, before, state)
        user = User.objects.create_user(username='edd-migration', firebase_uid='edd-migration')
        owner = Account.objects.create(user=user, account_type='personal')
        args = dict(confio_account=owner, expected_monthly_usd='25000', income_type='employed', source_of_funds='salary')
        LimitIncreaseRequest.objects.create(**args, status='forwarded')
        LimitIncreaseRequest.objects.create(**args, status='forwarded')
        LimitIncreaseRequest.objects.create(**args, status='started')
        with self.assertRaises(IntegrityError), transaction.atomic():
            LimitIncreaseRequest.objects.create(**args, status='submitted')
