from django.test import TransactionTestCase
from django.utils import timezone

from billing.imports import promote_import, rows_sha256, stage_import
from billing.models import BillingImportRow, BillingObligation, ObligationSubject
from users.models import Business


class BillingImportTests(TransactionTestCase):
    def setUp(self):
        self.business = Business.objects.create(name='CIP', category='services')

    def _row(self, **overrides):
        row = {
            'external_id': 'cip:42', 'masked_reference': 'CIP ••••0042',
            'obligation_external_id': 'cip:42:2026-09', 'amount_minor': 5000,
            'period_start': '2026-09-01', 'period_end': '2026-09-30',
            'due_at': '2026-09-10T23:59:59-05:00',
        }
        row.update(overrides)
        return row

    def test_checksum_validated_import_promotes_idempotent_business_keys(self):
        rows = [self._row()]
        batch = stage_import(
            business=self.business, rows=rows,
            schema_version='billing-obligations-v1',
            generated_at=timezone.now(), source_sha256=rows_sha256(rows))
        self.assertEqual(batch.status, 'valid')
        self.assertEqual(promote_import(batch.id, chunk_size=1), 1)
        self.assertEqual(ObligationSubject.objects.count(), 1)
        self.assertEqual(BillingObligation.objects.count(), 1)
        self.assertEqual(BillingImportRow.objects.get().status, 'promoted')

    def test_import_rejects_identity_and_formula_injection(self):
        rows = [self._row(dni='12345678'), self._row(
            external_id='=HYPERLINK("evil")', obligation_external_id='other')]
        batch = stage_import(
            business=self.business, rows=rows,
            schema_version='billing-obligations-v1',
            generated_at=timezone.now(), source_sha256=rows_sha256(rows))
        self.assertEqual(batch.status, 'invalid')
        self.assertEqual(set(batch.rows.values_list('error_code', flat=True)),
                         {'identity_field_forbidden', 'formula_injection'})
        with self.assertRaisesRegex(ValueError, 'invalid rows'):
            promote_import(batch.id)

    def test_import_checksum_mismatch_has_no_side_effect(self):
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            stage_import(
                business=self.business, rows=[self._row()],
                schema_version='billing-obligations-v1',
                generated_at=timezone.now(), source_sha256='0' * 64)
        self.assertFalse(BillingImportRow.objects.exists())

    def test_import_rejects_lossy_amounts_and_malformed_typed_fields(self):
        rows = [self._row(**change) for change in (
            {'amount_minor': 50.9}, {'amount_minor': True},
            {'amount_minor': 2**63}, {'due_at': None},
            {'external_id': ''}, {'external_id': {'member': 42}},
            {'masked_reference': 'x' * 81},
        )]
        batch = stage_import(
            business=self.business, rows=rows,
            schema_version='billing-obligations-v1', generated_at=timezone.now(),
            source_sha256=rows_sha256(rows))
        self.assertEqual(batch.invalid_count, len(rows))
        self.assertEqual(batch.valid_count, 0)

    def test_repeated_source_key_requires_identical_debt(self):
        def stage(row):
            return stage_import(
                business=self.business, rows=[row],
                schema_version='billing-obligations-v1', generated_at=timezone.now(),
                source_sha256=rows_sha256([row]))

        promote_import(stage(self._row()).id)
        self.assertEqual(promote_import(stage(self._row()).id), 0)
        for change in ({'external_id': 'another-member'}, {'amount_minor': 6000},
                       {'period_end': '2026-10-01'}):
            batch = stage(self._row(**change))
            with self.assertRaisesRegex(ValueError, 'conflicts with existing debt'):
                promote_import(batch.id)
            batch.refresh_from_db()
            self.assertEqual(batch.promoted_count, 0)
        self.assertEqual(BillingObligation.objects.count(), 1)
        self.assertEqual(ObligationSubject.objects.count(), 1)

    def test_zero_chunk_size_cannot_mark_unpromoted_batch_completed(self):
        rows = [self._row()]
        batch = stage_import(
            business=self.business, rows=rows,
            schema_version='billing-obligations-v1', generated_at=timezone.now(),
            source_sha256=rows_sha256(rows))
        with self.assertRaisesRegex(ValueError, 'positive integer'):
            promote_import(batch.id, chunk_size=0)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'valid')
