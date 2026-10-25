from django.test import TestCase

from payment_accounts import agenda
from payment_accounts.agenda import AgendaError
from payment_accounts.models import AgendaEntry, PayoutDestination
from security.models import IdentityVerification
from users.models import Account, BankInfo, User


class AgendaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='agenda', firebase_uid='agenda')
        self.owner = Account.objects.create(user=self.user, account_type='personal')
        other = User.objects.create_user(username='agenda-other', firebase_uid='agenda-other')
        self.other = Account.objects.create(user=other, account_type='personal')

    def ve(self, account=None, **overrides):
        values = dict(label='', relationship='third_party', holder_name='María Pérez', cedula='12345678',
                      phone='0414 1234567', bank_code='134')
        values.update(overrides)
        return agenda.save_ve_pagomovil(account or self.owner, **values)

    # ------------------------------------------------------------ VE Pago Móvil

    def test_ve_entry_is_normalized_like_an_order(self):
        entry = self.ve()
        self.assertEqual(entry.details, {'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0134'})
        self.assertEqual((entry.rail, entry.country, entry.relationship), ('ve_pagomovil', 'VE', 'third_party'))
        self.assertEqual(entry.label, 'María Pérez · Banesco')
        view = agenda.view(entry)
        self.assertEqual((view['cedula'], view['bank_code']), ('V12345678', '0134'))

    def test_ve_entry_rejects_bad_fields_and_unnamed_third_parties(self):
        for overrides in ({'cedula': 'x'}, {'phone': '0212 1234567'}, {'bank_code': '9999'}, {'holder_name': ''}):
            with self.subTest(overrides=overrides), self.assertRaises(AgendaError):
                self.ve(**overrides)

    def verify(self, number='12345678', country='VEN', first='María José', last='Pérez Gómez'):
        return IdentityVerification.objects.create(
            user=self.user, status='verified', verified_date_of_birth='1990-01-01', verified_country=country,
            verified_nationality=country, document_type='national_id', document_number=number,
            document_issuing_country=country, verified_first_name=first, verified_last_name=last,
            risk_factors={'provider': 'didit'})

    def test_own_ve_entry_is_the_verified_cedula_never_a_typed_one(self):
        with self.assertRaisesRegex(AgendaError, 'cédula venezolana verificada'):
            self.ve(relationship='own', cedula='87654321')
        self.verify('12.345.678')
        self.assertEqual(agenda.own_ve_cedula(self.owner), 'V12345678')
        entry = self.ve(relationship='own', cedula='87654321', holder_name='Alguien')
        self.assertEqual((entry.relationship, entry.details['cedula'], entry.holder_name), ('own', 'V12345678', ''))

    def test_a_passport_is_not_a_cedula_and_ownership_is_rederived_on_read(self):
        passport = self.verify('12345678')
        passport.document_type = 'passport'
        passport.save()
        self.assertEqual(agenda.own_ve_cedula(self.owner), '')
        entry = self.ve(cedula='12345678')
        self.assertEqual(entry.relationship, 'third_party')
        # A stale or self-declared "own" is corrected the next time entries are read.
        AgendaEntry.objects.filter(pk=entry.pk).update(relationship='own')
        agenda.sync_relationships(self.owner)
        entry.refresh_from_db()
        self.assertEqual(entry.relationship, 'third_party')

    def test_foreign_resident_cedula_keeps_its_e(self):
        document = self.verify('12345678')
        document.document_type = 'foreign_id'
        document.save()
        self.assertEqual(agenda.own_ve_cedula(self.owner), 'E12345678')
        self.assertEqual(self.ve(relationship='own', cedula='').details['cedula'], 'E12345678')

    def test_relationship_follows_the_cedula_not_the_claim(self):
        self.verify('12345678')
        # Saying "someone else" with your own cédula is still yours (E prefix too).
        self.assertEqual(self.ve(relationship='third_party', cedula='E12345678').relationship, 'own')
        self.assertEqual(self.ve(relationship='third_party', cedula='99999999').relationship, 'third_party')

    def test_ve_duplicate_returns_existing_and_edit_stays_scoped(self):
        entry = self.ve()
        self.assertEqual(self.ve().pk, entry.pk)
        edited = self.ve(entry_id=str(entry.internal_id), label='Mamá')
        self.assertEqual((edited.pk, edited.label), (entry.pk, 'Mamá'))
        with self.assertRaises(AgendaError):
            self.ve(account=self.other, entry_id=str(entry.internal_id))
        with self.assertRaises(AgendaError):
            agenda.delete(self.other, str(entry.internal_id))
        with self.assertRaises(AgendaError):
            agenda.owned_entry(self.owner, 'not-a-uuid')

    def test_delete_hides_entry(self):
        entry = self.ve()
        agenda.delete(self.owner, str(entry.internal_id))
        self.assertFalse(agenda.entries(self.owner).exists())

    # ------------------------------------------------------------ Infinia recipients

    def destination(self, account=None, status='SUCCESS', holder='Ana Gómez', method_id='co_breb'):
        return PayoutDestination.objects.create(
            confio_account=account or self.owner, provider='infinia', kind='breb_key', country='COL', asset='COP',
            label='Llave @ana', holder_name=holder, details={'type': 'BREB_KEY', 'brebKey': '@ana'},
            provider_data={'method_id': method_id, 'validation': {'status': status, 'holder_name': holder}})

    def test_recipient_is_own_only_when_the_holder_matches_the_verified_identity(self):
        self.verify('10203040', country='COL', first='Ana María', last='Gómez Ruiz')
        cases = [('ANA MARIA GOMEZ', '', 'own'), ('Pedro Pérez', '•••• 3040', 'own'), ('Pedro Pérez', '•••• 1111', 'third_party'),
                 ('ANA LOPEZ', '', 'third_party')]
        for holder, document, expected in cases:
            destination = self.destination(holder=holder)
            destination.provider_data['validation']['holder_document'] = document
            destination.save(update_fields=['provider_data'])
            entry = agenda.save_destination(self.owner, destination_id=str(destination.internal_id), label='',
                                            relationship='own' if expected == 'third_party' else 'third_party')
            with self.subTest(holder=holder, document=document):
                self.assertEqual(entry.relationship, expected)

    def test_recipient_moves_from_recents_to_agenda_and_back(self):
        destination = self.destination()
        self.assertEqual([r['destination_id'] for r in agenda.recents(self.owner)], [str(destination.internal_id)])
        self.assertEqual(agenda.recents(self.owner)[0]['country'], 'CO')
        entry = agenda.save_destination(self.owner, destination_id=str(destination.internal_id), label='',
                                        relationship='third_party')
        self.assertEqual((entry.rail, entry.country, entry.label), ('co_breb', 'CO', 'Ana Gómez'))
        self.assertEqual(entry.details, {'value': '@ana'})
        self.assertEqual(agenda.recents(self.owner), [])
        agenda.delete(self.owner, str(entry.internal_id))
        self.assertEqual(len(agenda.recents(self.owner)), 1)
        again = agenda.save_destination(self.owner, destination_id=str(destination.internal_id), label='Ana',
                                        relationship='own')
        # No verified identity matches the holder: a claim of "own" changes nothing.
        self.assertEqual((again.pk, again.deleted_at, again.relationship), (entry.pk, None, 'third_party'))

    def test_recipient_holder_follows_destination(self):
        destination = self.destination()
        entry = agenda.save_destination(self.owner, destination_id=str(destination.internal_id), label='',
                                        relationship='third_party')
        PayoutDestination.objects.filter(pk=destination.pk).update(holder_name='')
        entry.refresh_from_db()
        self.assertEqual(agenda.view(entry)['holder_name'], '')

    def test_a_key_reassigned_to_someone_else_leaves_mias(self):
        self.verify('10203040', country='COL', first='Ana', last='Gómez')
        destination = self.destination(holder='ANA GOMEZ')
        entry = agenda.save_destination(self.owner, destination_id=str(destination.internal_id), label='')
        self.assertEqual(entry.relationship, 'own')
        PayoutDestination.objects.filter(pk=destination.pk).update(holder_name='LUIS PEREZ')
        agenda.sync_relationships(self.owner)
        entry.refresh_from_db()
        self.assertEqual(entry.relationship, 'third_party')

    def test_recipient_must_be_ours_known_and_an_account(self):
        foreign = self.destination(account=self.other)
        qr = self.destination(method_id='co_qr')
        for destination_id in (str(foreign.internal_id), str(qr.internal_id), 'nope'):
            with self.subTest(destination_id=destination_id), self.assertRaises(AgendaError):
                agenda.save_destination(self.owner, destination_id=destination_id, label='',
                                        relationship='third_party')

    # ------------------------------------------------------------ Mis cuentas mirror

    def bank_info(self, **overrides):
        values = dict(account=self.owner, account_holder_name='Julián', account_number='0102123456789012')
        values.update(overrides)
        return BankInfo.objects.create(**values)

    def test_bank_info_is_mirrored_own_with_default_and_soft_delete(self):
        first = self.bank_info(is_default=True)
        second = self.bank_info(account_number='99998888')
        entries = {e.bank_info_id: e for e in AgendaEntry.objects.filter(rail='bank_info')}
        self.assertEqual(set(entries), {first.pk, second.pk})
        self.assertTrue(all(e.relationship == 'own' for e in entries.values()))
        self.assertTrue(entries[first.pk].is_default)
        self.assertEqual(entries[second.pk].details['identifier_last4'], '8888')

        second.set_as_default()
        defaults = list(AgendaEntry.objects.filter(rail='bank_info', is_default=True).values_list('bank_info_id', flat=True))
        self.assertEqual(defaults, [second.pk])

        second.soft_delete()
        self.assertEqual([e.bank_info_id for e in agenda.entries(self.owner)], [first.pk])

    def test_bank_info_entries_are_own_only_and_managed_in_mis_cuentas(self):
        entry = self.bank_info().agenda_entry
        with self.assertRaises(AgendaError):
            agenda.delete(self.owner, str(entry.internal_id))
        renamed = agenda.rename(self.owner, str(entry.internal_id), label='Nómina', relationship='third_party')
        self.assertEqual((renamed.label, renamed.relationship), ('Nómina', 'own'))


class AgendaMethodsTests(TestCase):
    def test_methods_say_per_rail_whether_someone_else_can_be_saved(self):
        from ramps.models import RampPaymentMethod
        user = User.objects.create_user(username='agenda-methods', firebase_uid='agenda-methods')
        owner = Account.objects.create(user=user, account_type='personal')
        RampPaymentMethod.objects.create(code='WIREPE', country_code='pe', display_name='Interbank',
                                         supports_off_ramp=True)
        rows = {row['id']: row for row in agenda.methods(owner, None)}
        self.assertTrue(rows['ve_pagomovil']['allows_third_party'])
        bank = next(row for row in rows.values() if row['kind'] == 'bank_info' and row['title'] == 'Interbank')
        self.assertEqual((bank['country'], bank['allows_third_party']), ('PE', False))
        for rail in agenda.INFINIA_RAILS:
            if rail in rows:
                self.assertTrue(rows[rail]['allows_third_party'])
                self.assertEqual(rows[rail]['kind'], 'local')
        self.assertFalse(any(row['id'].endswith('_qr') for row in rows.values()))
