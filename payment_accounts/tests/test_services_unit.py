from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from payment_accounts.schema import _destination_details
from payment_accounts.services import (
    PaymentAccountError,
    _validate_infinia_destination,
    provision_payment_account,
)


class DestinationValidationTests(SimpleTestCase):
    def test_typed_graphql_destination_maps_to_provider_camel_case(self):
        details = _destination_details({
            'type': 'BREB_KEY',
            'breb_key': '@persona',
            'accepts_retries': False,
        })
        self.assertEqual(details['brebKey'], '@persona')
        self.assertIs(details['acceptsRetries'], False)

    def test_infinia_breb_requires_colombia_and_key(self):
        details = {'type': 'BREB_KEY', 'brebKey': '@persona'}
        _validate_infinia_destination(
            kind='breb_key', country='COL', details=details
        )
        with self.assertRaises(PaymentAccountError):
            _validate_infinia_destination(
                kind='breb_key', country='VEN', details=dict(details)
            )

    def test_infinia_destination_reports_missing_required_fields(self):
        with self.assertRaisesRegex(PaymentAccountError, 'accountNumber'):
            _validate_infinia_destination(
                kind='bank_account',
                country='COL',
                details={
                    'type': 'ACCOUNT_COLOMBIA',
                    'fullName': 'Persona',
                    'documentType': 'CC',
                    'documentNumber': '1',
                    'bankCode': '1007',
                    'accountType': 'SAVINGS',
                },
            )


@override_settings(COBRE_PAYMENT_ACCOUNTS_ENABLED=True)
class ProviderShapeTests(SimpleTestCase):
    def test_cobre_rejects_non_cop_account_before_provider_or_db_access(self):
        with self.assertRaises(PaymentAccountError):
            provision_payment_account(
                confio_account=SimpleNamespace(),
                provider='cobre',
                identity=SimpleNamespace(),
                country='COL',
                asset='USD',
                ownership_structure='omnibus_subledger',
            )

    def test_provider_ownership_structure_cannot_be_misrepresented(self):
        with self.assertRaises(PaymentAccountError):
            provision_payment_account(
                confio_account=SimpleNamespace(),
                provider='cobre',
                identity=SimpleNamespace(),
                country='COL',
                asset='COP',
                ownership_structure='provider_named',
            )
