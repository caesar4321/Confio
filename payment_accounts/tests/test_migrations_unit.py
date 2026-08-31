import importlib
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase


migration = importlib.import_module(
    'payment_accounts.migrations.0004_remove_duplicate_confio_fee_fields'
)


class _QuerySet:
    def __init__(self, records):
        self.records = records

    def iterator(self):
        return iter(self.records)


class _Manager:
    def __init__(self, records, json_field):
        self.records = records
        self.json_field = json_field

    def exclude(self, **kwargs):
        expected = kwargs['confio_fee']
        return _QuerySet([
            record for record in self.records if record.confio_fee != expected
        ])

    def filter(self, **kwargs):
        key = kwargs[f'{self.json_field}__has_key']
        return _QuerySet([
            record for record in self.records
            if key in (getattr(record, self.json_field) or {})
        ])


class _Record(SimpleNamespace):
    def save(self, *, update_fields):
        self.saved_fields = update_fields


class LegacyFeeMigrationTests(SimpleTestCase):
    def _apps(self, flows, operations):
        models = {
            'MoneyFlow': SimpleNamespace(
                objects=_Manager(flows, 'metadata')
            ),
            'MoneyOperation': SimpleNamespace(
                objects=_Manager(operations, 'provider_data')
            ),
        }
        return SimpleNamespace(
            get_model=lambda app_label, model_name: models[model_name]
        )

    def test_archive_preserves_nonzero_fees_and_other_json(self):
        flow = _Record(confio_fee=Decimal('1.25'), metadata={'keep': True})
        operation = _Record(
            confio_fee=Decimal('0.90'), provider_data={'provider': 'value'}
        )
        zero_flow = _Record(confio_fee=Decimal('0'), metadata={})
        apps = self._apps([flow, zero_flow], [operation])

        migration.archive_legacy_confio_fees(apps, None)

        self.assertEqual(flow.metadata, {
            'keep': True,
            migration.LEGACY_FEE_KEY: '1.25',
        })
        self.assertEqual(flow.saved_fields, ['metadata'])
        self.assertFalse(hasattr(zero_flow, 'saved_fields'))
        self.assertEqual(operation.provider_data, {
            'provider': 'value',
            migration.LEGACY_FEE_KEY: '0.90',
        })
        self.assertEqual(operation.saved_fields, ['provider_data'])

    def test_reverse_restores_fees_and_removes_archive_keys(self):
        flow = _Record(
            confio_fee=Decimal('0'),
            metadata={'keep': True, migration.LEGACY_FEE_KEY: '1.25'},
        )
        operation = _Record(
            confio_fee=Decimal('0'),
            provider_data={
                'provider': 'value',
                migration.LEGACY_FEE_KEY: '0.90',
            },
        )
        apps = self._apps([flow], [operation])

        migration.restore_legacy_confio_fees(apps, None)

        self.assertEqual(flow.confio_fee, '1.25')
        self.assertEqual(flow.metadata, {'keep': True})
        self.assertEqual(flow.saved_fields, ['confio_fee', 'metadata'])
        self.assertEqual(operation.confio_fee, '0.90')
        self.assertEqual(operation.provider_data, {'provider': 'value'})
        self.assertEqual(
            operation.saved_fields, ['confio_fee', 'provider_data']
        )
