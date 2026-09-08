from django.db import connection
from django.test import TransactionTestCase, override_settings

from billing.identity_tokens import (
    InvalidInstitutionToken, consume_identity_token, create_identity_session,
    issue_identity_token,
)
from billing.models import (
    InstitutionConnection, InstitutionDataRequirement, ObligationSubject,
    SubjectIdentityValue,
)
from users.models import Business


@override_settings(
    BILLING_INSTITUTION_TOKEN_KEY='test-institution-signing-key',
    CONFIO_GLOBAL_WALLET_MASTER_KEY=(
        'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='),
)
class InstitutionIdentityTests(TransactionTestCase):
    def setUp(self):
        self.business = Business.objects.create(name='CIP', category='services')
        self.subject = ObligationSubject.objects.create(
            business=self.business, mode='test', external_id='cip:member:42',
            subject_type='membership', masked_reference='CIP ••••0042')
        self.connection = InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='test', status='sandbox')
        InstitutionDataRequirement.objects.create(
            connection=self.connection, field_name='dni',
            purpose='Match the member record', retention_days=30)

    def test_signed_token_is_short_lived_context_bound_and_one_time(self):
        session = create_identity_session(
            connection=self.connection, subject=self.subject,
            requested_fields=['dni'], obligation_references=['obl_opaque'])
        token = issue_identity_token(session)
        consumed, claims = consume_identity_token(token, provider='cip')
        self.assertEqual(consumed.id, session.id)
        self.assertEqual(claims['sub'], self.subject.public_id)
        self.assertNotIn('dni', claims)
        self.assertNotIn('email', claims)
        self.assertLessEqual(claims['exp'] - claims['iat'], 600)
        with self.assertRaisesRegex(InvalidInstitutionToken, 'already used'):
            consume_identity_token(token, provider='cip')

    def test_token_rejects_wrong_audience_and_unapproved_fields(self):
        with self.assertRaisesRegex(ValueError, 'approved manifest'):
            create_identity_session(
                connection=self.connection, subject=self.subject,
                requested_fields=['phone'])
        session = create_identity_session(
            connection=self.connection, subject=self.subject,
            requested_fields=['dni'])
        with self.assertRaisesRegex(InvalidInstitutionToken, 'audience'):
            consume_identity_token(issue_identity_token(session), provider='another')

    def test_identity_value_is_encrypted_at_rest(self):
        value = SubjectIdentityValue.objects.create(
            subject=self.subject, field_name='dni', encrypted_value='12345678')
        value.refresh_from_db()
        self.assertEqual(value.encrypted_value, '12345678')
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT encrypted_value FROM billing_subjectidentityvalue WHERE id = %s',
                [value.id])
            stored = cursor.fetchone()[0]
        self.assertNotEqual(stored, '12345678')
        self.assertNotIn('12345678', stored)

    def test_disabled_connection_invalidates_unconsumed_link(self):
        session = create_identity_session(
            connection=self.connection, subject=self.subject, requested_fields=['dni'])
        token = issue_identity_token(session)
        self.connection.status = 'disabled'
        self.connection.save()
        with self.assertRaisesRegex(InvalidInstitutionToken, 'no longer active'):
            consume_identity_token(token, provider='cip')
        session.refresh_from_db()
        self.assertIsNone(session.token_used_at)

    def test_session_cannot_cross_tenant_or_mode(self):
        other = Business.objects.create(name='Other', category='services')
        self.subject.business = other
        with self.assertRaisesRegex(ValueError, 'context mismatch'):
            create_identity_session(connection=self.connection, subject=self.subject,
                                    requested_fields=[])

    def test_removed_manifest_field_invalidates_link(self):
        session = create_identity_session(
            connection=self.connection, subject=self.subject, requested_fields=['dni'])
        self.connection.data_requirements.all().delete()
        with self.assertRaisesRegex(InvalidInstitutionToken, 'manifest changed'):
            consume_identity_token(issue_identity_token(session), provider='cip')
