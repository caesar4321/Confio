"""A person's additional documents never leak into the primary-identity readers."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from payment_accounts import local_money
from payment_accounts.eligibility import context_from_identity
from payment_accounts.models import ProviderProfile
from security.didit import DiditConfigurationError, _review_additional_document, normalize_document_request
from security.models import IdentityVerification
from users.models import Account, User

FLAGS = dict(INFINIA_PAYMENT_ACCOUNTS_ENABLED=True, INFINIA_JOURNEYS_ENABLED=True)
LIVE = ('live', '')


def document(user, number, **overrides):
    values = dict(
        user=user, status='verified', verified_first_name='Ana Maria', verified_last_name='Perez Soto',
        verified_date_of_birth=date(1990, 1, 1), verified_country='VEN', verified_nationality='VEN',
        document_type='national_id', document_number=number, document_issuing_country='VEN',
        risk_factors={'provider': 'didit', 'didit': {'session_id': f'session-{number}'}},
        verified_at=timezone.now(),
    )
    values.update(overrides)
    return IdentityVerification.all_documents.create(**values)


class DocumentRequestTests(SimpleTestCase):
    def test_request_is_normalized(self):
        self.assertEqual(normalize_document_request('co', ['p', 'P']), {'id_country': 'COL', 'document_types': ['P']})
        self.assertEqual(normalize_document_request('ARG', ['ID', 'P']), {'id_country': 'ARG', 'document_types': ['ID', 'P']})
        self.assertEqual(normalize_document_request(None, None), {'id_country': '', 'document_types': []})
        for country, types in (('ZZZ', ['P']), ('CO', ['VISA'])):
            with self.assertRaises(DiditConfigurationError):
                normalize_document_request(country, types)

    def test_any_national_id_or_passport_except_venezuelan(self):
        def doc(kind, country):
            return SimpleNamespace(document_type=kind, document_issuing_country=country)
        for account in ('COL', 'MEX', 'BRA', 'ARG'):
            self.assertTrue(local_money.accepts_identity(doc('national_id', account), account))
            self.assertTrue(local_money.accepts_identity(doc('national_id', 'PRY'), account))
            self.assertTrue(local_money.accepts_identity(doc('passport', 'KOR'), account))
            self.assertFalse(local_money.accepts_identity(doc('national_id', 'VEN'), account))
            self.assertFalse(local_money.accepts_identity(doc('passport', 'VEN'), account))
            self.assertEqual(local_money.document_requirement(account), {'id_country': '', 'document_types': ['ID', 'P']})
        # The CNH is Brazilian-only; a driver's license is never an ID elsewhere.
        self.assertTrue(local_money.accepts_identity(doc('drivers_license', 'BRA'), 'BRA'))
        self.assertFalse(local_money.accepts_identity(doc('drivers_license', 'BRA'), 'COL'))
        self.assertFalse(local_money.accepts_identity(doc('drivers_license', 'PRY'), 'BRA'))
        self.assertFalse(local_money.accepts_identity(None, 'COL'))


class AdditionalDocumentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='two-documents', firebase_uid='two-documents')
        self.owner = Account.objects.create(user=self.user, account_type='personal')

    def test_document_list_returns_rejection_reason_only_for_own_rejected_documents(self):
        from security.schema import SecurityQuery
        reason = 'El documento no coincide con tu identidad verificada.'
        rejected = document(self.user, 'REJECTED', status='rejected', rejected_reason=reason)
        other = User.objects.create_user(username='other-document-owner', firebase_uid='other-document-owner')
        document(other, 'OTHER-REJECTED', status='rejected', rejected_reason='Private reason')
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        rows = SecurityQuery.resolve_my_identity_documents(None, info)
        self.assertEqual([(r.id, r.rejected_reason) for r in rows], [(str(rejected.pk), reason)])
        IdentityVerification.all_documents.filter(pk=rejected.pk).update(status='verified')
        rows = SecurityQuery.resolve_my_identity_documents(None, info)
        self.assertIsNone(rows[0].rejected_reason)

    def test_additional_documents_are_invisible_to_existing_readers(self):
        from ramps.schema import _get_latest_personal_verification
        primary = document(self.user, 'V-1', verified_at=timezone.now() - timedelta(days=30))
        passport = document(self.user, 'P-1', document_type='passport', is_additional_document=True)
        self.assertEqual(list(IdentityVerification.objects.filter(user=self.user)), [primary])
        self.assertEqual(set(IdentityVerification.all_documents.filter(user=self.user)), {primary, passport})
        self.assertEqual(self.user.security_verifications.count(), 1)
        # Koywe keeps reading the primary document even though the passport is newer.
        self.assertEqual(_get_latest_personal_verification(self.user), primary)
        self.assertTrue(self.user.is_identity_verified)

    def test_a_passport_only_person_is_not_koywe_verified(self):
        from ramps.schema import _get_latest_personal_verification
        document(self.user, 'P-2', document_type='passport', is_additional_document=True)
        self.assertIsNone(_get_latest_personal_verification(self.user))
        self.assertFalse(self.user.is_identity_verified)

    def pending(self, request):
        return document(self.user, 'P-3', status='pending', document_type='passport', is_additional_document=True,
                        risk_factors={'provider': 'didit', 'document_request': request})

    def extracted(self, **overrides):
        values = dict(document_issuing_country='VEN', document_type='passport', verified_first_name='ANA',
                      verified_last_name='PEREZ', verified_date_of_birth=date(1990, 1, 1))
        values.update(overrides)
        return values

    def test_extra_document_must_be_what_the_rail_asked_for(self):
        document(self.user, 'V-2')
        row = self.pending({'id_country': 'ARG', 'document_types': ['ID', 'P']})
        self.assertEqual(_review_additional_document(row, self.extracted(), {})[0], 'rejected')
        row = self.pending({'id_country': '', 'document_types': ['P']})
        self.assertEqual(_review_additional_document(row, self.extracted(document_type='drivers_license'), {})[0],
                         'rejected')

    def test_extra_document_must_be_the_same_person(self):
        document(self.user, 'V-3')
        row = self.pending({'id_country': '', 'document_types': ['P']})
        # A passport prints fewer names than the cédula: token overlap is enough.
        self.assertEqual(_review_additional_document(row, self.extracted(), {}), ('verified', ''))
        self.assertEqual(_review_additional_document(
            row, self.extracted(verified_date_of_birth=date(1991, 1, 1)), {})[0], 'rejected')
        self.assertEqual(_review_additional_document(row, self.extracted(verified_last_name='GOMEZ'), {})[0],
                         'rejected')

    def test_same_person_reads_any_script_and_one_letter_names(self):
        from security.didit import _same_person

        def on_file(first, last, born):
            return SimpleNamespace(verified_first_name=first, verified_last_name=last, verified_date_of_birth=born)

        def read(first, last, born):
            return {'verified_first_name': first, 'verified_last_name': last, 'verified_date_of_birth': born}
        born = date(1985, 2, 2)
        self.assertTrue(_same_person(on_file('Иван', 'Петров', born), read('ИВАН', 'ПЕТРОВ', born)))
        self.assertTrue(_same_person(on_file('Min', 'O', born), read('MIN', 'O', born)))
        self.assertFalse(_same_person(on_file('Min', 'O', born), read('MIN', 'LEE', born)))
        self.assertFalse(_same_person(on_file('Иван', 'Петров', born), read('ИВАН', 'ПЕТРОВ', date(1985, 2, 3))))
        # A vowel sign is part of its word: Ram and Raj never match on a shared र.
        self.assertTrue(_same_person(on_file('राम', 'शर्मा', born), read('राम', 'शर्मा', born)))
        self.assertFalse(_same_person(on_file('राम', 'शर्मा', born), read('राज', 'शर्मा', born)))
        self.assertTrue(_same_person(on_file('José', 'Núñez', born), read('JOSE', 'NUNEZ', born)))

    def test_a_passport_shared_across_accounts_is_flagged_even_as_an_extra_document(self):
        from security.models import SuspiciousActivity
        for case, other_is_extra in (('extra-to-extra', True), ('extra-to-primary', False)):
            with self.subTest(case=case):
                IdentityVerification.all_documents.all().delete()
                SuspiciousActivity.objects.all().delete()
                other = User.objects.create_user(username=f'holder-{case}', firebase_uid=f'holder-{case}')
                document(other, 'M1234567', document_type='passport', document_issuing_country='KOR',
                         is_additional_document=other_is_extra)
                with self.captureOnCommitCallbacks(execute=True):
                    mine = document(self.user, 'M1234567', document_type='passport', document_issuing_country='KOR',
                                    is_additional_document=True)
                row = IdentityVerification.all_documents.get(pk=mine.pk)
                self.assertEqual(row.risk_factors['duplicate_identity']['related_user_ids'], [other.pk])
                self.assertTrue(SuspiciousActivity.objects.filter(
                    user=self.user, activity_type='multiple_accounts').exists())

    @override_settings(COBRE_PAYMENT_ACCOUNTS_ENABLED=False)
    def test_the_verification_screen_lists_every_document_the_same_way(self):
        from security.schema import SecurityQuery
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        document(self.user, 'V-LIST')  # Venezuelan cédula, the phone country's document
        document(self.user, 'P-LIST', document_type='passport', document_issuing_country='PRY',
                 is_additional_document=True)
        rows = {row.document_type: row for row in SecurityQuery.resolve_my_identity_documents(None, info)}
        self.assertEqual((rows['national_id'].issuing_country, rows['national_id'].is_additional,
                          rows['national_id'].local_countries), ('VE', False, []))
        self.assertEqual((rows['passport'].issuing_country, rows['passport'].is_additional,
                          rows['passport'].local_countries), ('PY', True, ['AR', 'BR', 'CO', 'MX']))
        # A newer extra document still in review shows up; the old verified ones stay.
        document(self.user, 'P-NEW', status='pending', document_type='passport', document_issuing_country='KOR',
                 is_additional_document=True)
        statuses = sorted(row.status for row in SecurityQuery.resolve_my_identity_documents(None, info))
        self.assertEqual(statuses, ['pending', 'verified', 'verified'])

    def test_rewards_accept_a_verified_document_from_another_country(self):
        from achievements.referral_security import get_referrer_claim_verification_error
        document(self.user, 'P-RW', document_type='passport', document_issuing_country='PRY',
                 is_additional_document=True)
        self.assertTrue(self.user.has_verified_identity_document)
        # Recargar and Retirar still need the phone country's document.
        self.assertFalse(self.user.is_identity_verified)
        referral = SimpleNamespace(referred_user=self.user, referred_user_id=self.user.pk)
        self.assertIsNone(get_referrer_claim_verification_error(referral))

    def test_without_a_primary_the_document_stands_alone(self):
        row = self.pending({'id_country': '', 'document_types': ['P']})
        self.assertEqual(_review_additional_document(row, self.extracted(), {}), ('verified', ''))

    @override_settings(**FLAGS)
    def test_rail_asks_for_another_document_when_the_venezuelan_cedula_does_not_fit(self):
        primary = document(self.user, 'V-4')
        with mock.patch.object(local_money, 'method_status', return_value=LIVE):
            status, reason, requirement = local_money.rail_status(self.owner, primary, local_money.METHODS['co_breb'])
            self.assertEqual((status, requirement), ('needs_document', {'id_country': '', 'document_types': ['ID', 'P']}))
            document(self.user, 'P-4', document_type='passport', document_issuing_country='KOR',
                     is_additional_document=True)
            self.assertEqual(local_money.rail_status(self.owner, primary, local_money.METHODS['co_breb'])[0], 'live')

    @override_settings(**FLAGS)
    def test_blocked_eligibility_never_asks_for_a_document(self):
        primary = document(self.user, 'V-5')
        with mock.patch.object(local_money, 'method_status', return_value=('unavailable', 'nationality')):
            self.assertEqual(local_money.rail_status(self.owner, primary, local_money.METHODS['co_breb']),
                             ('unavailable', 'nationality', None))

    def test_the_owner_document_is_fixed_once_created(self):
        cnh = document(self.user, 'CNH-9', document_type='drivers_license', document_issuing_country='BRA')
        document(self.user, 'P-9', document_type='passport', document_issuing_country='KOR',
                 is_additional_document=True)
        ProviderProfile.objects.create(confio_account=self.owner, provider='infinia', owner_type='individual',
                                       status='active', identity_verification=cnh)
        self.assertEqual(local_money.document_for(self.owner, 'BRA'), cnh)
        # A CNH does not satisfy Argentina, and the owner cannot switch to the passport.
        self.assertIsNone(local_money.document_for(self.owner, 'ARG'))

    def test_residence_comes_from_ip_with_the_document_as_fallback(self):
        primary = document(self.user, 'V-6')
        with mock.patch('security.geo.residence_country_for', return_value='COL'):
            self.assertEqual(context_from_identity(primary).residence_country, 'COL')
        with mock.patch('security.geo.residence_country_for', return_value=None):
            self.assertEqual(context_from_identity(primary).residence_country, 'VEN')

    @override_settings(DIDIT_EDD_WORKFLOW_ID='wf-edd', DIDIT_ADDITIONAL_DOCUMENT_WORKFLOW_ID='wf-extra')
    def test_session_purpose_comes_from_the_workflow_didit_ran(self):
        from security.didit import didit_session_purpose
        self.assertEqual(didit_session_purpose({'workflow_id': 'wf-edd'}), 'edd')
        self.assertEqual(didit_session_purpose({'workflow_id': 'wf-extra'}), 'additional')
        self.assertEqual(didit_session_purpose({'workflow_id': 'wf-kyc'}), 'identity')
        self.assertEqual(didit_session_purpose({}), 'identity')

    def test_late_registration_turns_a_webhook_placeholder_into_an_additional_document(self):
        from security.didit import ensure_pending_didit_verification
        early = ensure_pending_didit_verification(user=self.user, session_id='s-race')  # the webhook came first
        self.assertFalse(early.is_additional_document)
        late = ensure_pending_didit_verification(user=self.user, session_id='s-race',
                                                 document_request={'id_country': '', 'document_types': ['ID', 'P']})
        self.assertEqual(late.pk, early.pk)
        self.assertTrue(late.is_additional_document)
        self.assertEqual(late.risk_factors['document_request'], {'id_country': '', 'document_types': ['ID', 'P']})

    def test_a_failed_owner_less_profile_does_not_pin_the_document(self):
        cnh = document(self.user, 'CNH-8', document_type='drivers_license', document_issuing_country='BRA')
        passport = document(self.user, 'P-8', document_type='passport', document_issuing_country='KOR',
                            is_additional_document=True)
        profile = ProviderProfile.objects.create(confio_account=self.owner, provider='infinia',
                                                 owner_type='individual', status='failed', identity_verification=cnh)
        self.assertEqual(local_money.document_for(self.owner, 'COL'), passport)
        profile.status = 'pending'  # a creation attempt may have landed: stay pinned
        profile.save(update_fields=['status'])
        self.assertIsNone(local_money.document_for(self.owner, 'COL'))

    def test_residence_weighs_sessions_not_ip_device_pairs(self):
        from security.geo import residence_country_for
        from security.models import DeviceFingerprint, IPAddress, IPDeviceUser

        def seen(ip, country, sessions, device):
            address = IPAddress.objects.create(ip_address=ip, country_code=country)
            fingerprint = DeviceFingerprint.objects.create(fingerprint=device)
            IPDeviceUser.objects.create(ip_address=address, device_fingerprint=fingerprint, user=self.user,
                                        total_sessions=sessions)
        seen('190.0.0.1', 'CO', 100, 'home-phone')
        seen('200.0.0.1', 'VE', 1, 'hotel-a')
        seen('200.0.0.2', 'VE', 1, 'hotel-b')
        self.assertEqual(residence_country_for(self.user), 'COL')

    def test_one_visit_to_an_old_home_ip_counts_as_one_visit(self):
        from security.geo import residence_country_for
        from security.models import DeviceFingerprint, IPAddress, IPDeviceUser
        today = timezone.now().date()

        def seen(ip, country, device, total, daily):
            address = IPAddress.objects.create(ip_address=ip, country_code=country)
            fingerprint = DeviceFingerprint.objects.create(fingerprint=device)
            IPDeviceUser.objects.create(ip_address=address, device_fingerprint=fingerprint, user=self.user,
                                        total_sessions=total, daily_sessions=daily)
        # Years at the old home, then a move: one visit back yesterday.
        seen('200.0.0.9', 'VE', 'old-phone', 1000, {(today - timedelta(days=1)).isoformat(): 1,
                                                    (today - timedelta(days=100)).isoformat(): 999})
        seen('190.0.0.9', 'CO', 'new-phone', 100,
             {(today - timedelta(days=d)).isoformat(): 2 for d in range(50)})
        self.assertEqual(residence_country_for(self.user), 'COL')

    def test_late_registration_never_reverts_a_decision_committed_meanwhile(self):
        from security import didit
        placeholder = didit.ensure_pending_didit_verification(user=self.user, session_id='s-race2')
        stale = IdentityVerification.all_documents.get(pk=placeholder.pk)  # read before the webhook landed
        IdentityVerification.all_documents.filter(pk=placeholder.pk).update(
            status='verified', risk_factors={'provider': 'didit', 'didit': {'session_id': 's-race2', 'status': 'Approved'}})
        with mock.patch.object(didit, '_find_existing_verification', return_value=stale):
            didit.ensure_pending_didit_verification(
                user=self.user, session_id='s-race2', document_request={'id_country': '', 'document_types': ['ID', 'P']})
        row = IdentityVerification.all_documents.get(pk=placeholder.pk)
        self.assertEqual(row.status, 'verified')
        self.assertEqual(row.risk_factors['didit']['status'], 'Approved')

    def test_late_registration_records_the_rails_request_over_a_webhook_default(self):
        from security import didit
        placeholder = didit.ensure_pending_didit_verification(
            user=self.user, session_id='s-default', document_request={'id_country': '', 'document_types': ['ID', 'P']})
        IdentityVerification.all_documents.filter(pk=placeholder.pk).update(  # the webhook decided first
            status='verified', document_issuing_country='COL', document_type='national_id')
        row = didit.ensure_pending_didit_verification(
            user=self.user, session_id='s-default', document_request={'id_country': 'COL', 'document_types': ['ID']})
        self.assertEqual((row.status, row.risk_factors['document_request']['id_country']), ('verified', 'COL'))
        # A request the verified document does not meet is recorded and decides it.
        stricter = didit.ensure_pending_didit_verification(
            user=self.user, session_id='s-default', document_request={'id_country': 'ARG', 'document_types': ['ID']})
        self.assertEqual(stricter.status, 'rejected')

    def test_a_webhook_default_never_replaces_the_rails_request(self):
        from security import didit
        didit.ensure_pending_didit_verification(  # the rail registered first
            user=self.user, session_id='s-rail', document_request={'id_country': 'COL', 'document_types': ['ID']})
        row = didit.ensure_pending_didit_verification(  # then the webhook path, with its default
            user=self.user, session_id='s-rail', document_request={'id_country': '', 'document_types': ['ID', 'P']},
            request_is_default=True)
        self.assertEqual(row.risk_factors['document_request'], {'id_country': 'COL', 'document_types': ['ID']})

    def test_a_primary_verified_after_an_extra_document_must_be_the_same_person(self):
        from security.didit import _bind_to_person
        document(self.user, 'P-X', document_type='passport', document_issuing_country='KOR',
                 is_additional_document=True)  # Ana verified an extra passport first
        primary = document(self.user, 'CC-X', status='pending', document_issuing_country='COL')
        bob = self.extracted(verified_first_name='BOB', verified_last_name='SMITH',
                             verified_date_of_birth=date(1985, 5, 5))
        self.assertEqual(_bind_to_person(primary, bob)[0], 'rejected')
        self.assertEqual(_bind_to_person(primary, self.extracted()), ('verified', ''))

    def test_registration_and_webhook_share_one_row_per_session(self):
        from security import didit
        first = didit.ensure_pending_didit_verification(user=self.user, session_id='s-one')
        again = didit.ensure_pending_didit_verification(
            user=self.user, session_id='s-one', document_request={'id_country': '', 'document_types': ['ID', 'P']})
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(IdentityVerification.all_documents.filter(risk_factors__didit__session_id='s-one').count(), 1)

    def test_a_didit_sync_holds_its_session_lock_from_fetch_to_save(self):
        from django.db import connection
        from security import didit
        approved = {
            'session_id': 's-lock', 'status': 'Approved',
            'vendor_data': f'{{"user_id":{self.user.id},"account_type":"personal"}}',
            'first_name': 'Ana', 'last_name': 'Perez', 'date_of_birth': '1990-01-01',
            'id_verifications': [{'nationality': 'VEN', 'document_type': 'passport', 'document_number': 'P-LOCK',
                                  'issuing_state': 'VEN', 'expiration_date': '2030-12-31'}],
        }
        row = document(self.user, 'P-LOCK', status='pending',
                       risk_factors={'provider': 'didit', 'didit': {'session_id': 's-lock'}})
        held = []

        def fetch(**kwargs):
            # Overlapping syncs of one session queue on this lock, so a slower
            # answer can never land after a newer one.
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                               "AND pid = pg_backend_pid() AND granted")
                held.append(cursor.fetchone()[0])
            return approved

        with mock.patch('security.didit.retrieve_didit_decision', side_effect=fetch), \
                mock.patch('security.didit._notify_verification_status_change'):
            didit.sync_didit_session(session_id='s-lock', expected_user=self.user)
        self.assertEqual(len(held), 1)
        self.assertGreaterEqual(held[0], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, 'verified')

    def test_a_company_verification_copy_is_never_the_persons_anchor(self):
        from security.didit import _bind_to_person
        company = dict(verified_first_name='Acme', verified_last_name='SA', verified_date_of_birth=date(2015, 3, 3))
        document(self.user, 'RIF-1', risk_factors={'provider': 'didit', 'account_type': 'business',
                                                    'didit': {'session_id': 's-kyb'}}, **company)
        document(self.user, 'RIF-1', risk_factors={}, **company)  # the personal copy the post_save signal makes
        primary = document(self.user, 'V-ANA', status='pending')
        self.assertEqual(_bind_to_person(primary, self.extracted()), ('verified', ''))

    def test_without_a_primary_a_second_document_must_match_the_first(self):
        document(self.user, 'P-A', document_type='passport', document_issuing_country='KOR',
                 is_additional_document=True)  # Ana's passport; she has no primary document
        row = self.pending({'id_country': '', 'document_types': ['ID', 'P']})
        bob = self.extracted(verified_first_name='BOB', verified_last_name='SMITH',
                             verified_date_of_birth=date(1985, 5, 5))
        self.assertEqual(_review_additional_document(row, bob, {})[0], 'rejected')
        self.assertEqual(_review_additional_document(row, self.extracted(), {}), ('verified', ''))

    def test_a_company_domicile_is_its_own_country_not_the_representatives(self):
        from payment_accounts.services import _declared_address_country
        with mock.patch('ramps.schema._build_effective_ramp_address_snapshot',
                        return_value=SimpleNamespace(address_country='USA')):
            company = SimpleNamespace(risk_factors={'account_type': 'business'}, verified_country='col', user=None)
            self.assertEqual(_declared_address_country(company), 'COL')
            person = SimpleNamespace(risk_factors={'provider': 'didit'}, verified_country='VEN', user=self.user)
            self.assertEqual(_declared_address_country(person), 'USA')
