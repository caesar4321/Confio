from decimal import Decimal

from django.test import SimpleTestCase

from ramps import schema as ramps_schema
from ramps.koywe_client import KoyweClient
from ramps.koywe_sync import build_koywe_instruction_snapshot, _merge_koywe_metadata


class KoyweInstructionSnapshotTests(SimpleTestCase):
    def test_build_snapshot_extracts_generic_instruction_fields(self):
        payload = {
            'status': 'WAITING',
            'statusDetails': '',
            'symbolIn': 'ARS',
            'symbolOut': 'USDC Algorand',
            'amountIn': 30000,
            'amountOut': 20.4,
            'paymentMethodId': 'wirear-id',
            'providedAddress': 'Alias 30718280229.KOYWE1\nCBU 0000053600000017871248\nCUIT 30718280229',
            'beneficiaryName': 'Alerce Argentina SRL',
            'bankName': 'Agil Pagos',
            'reference': 'WY7ZEPN6...002Q0M51',
        }

        snapshot = build_koywe_instruction_snapshot(order_payload=payload, next_action_url=None)

        self.assertEqual(snapshot['provider_status'], 'WAITING')
        self.assertEqual(snapshot['fields']['beneficiary_name'], 'Alerce Argentina SRL')
        self.assertEqual(snapshot['fields']['bank_name'], 'Agil Pagos')
        self.assertEqual(snapshot['fields']['reference'], 'WY7ZEPN6...002Q0M51')
        self.assertEqual(snapshot['provided_address'], 'Alias 30718280229.KOYWE1\nCBU 0000053600000017871248\nCUIT 30718280229')
        self.assertTrue(any(row['value'] == '30718280229.KOYWE1' for row in snapshot['address_rows']))

    def test_merge_metadata_preserves_created_snapshots(self):
        original_payload = {
            'status': 'WAITING',
            'providedAddress': 'Alias original.koywe',
        }
        initial = _merge_koywe_metadata(
            existing_metadata=None,
            payment_method_code='WIREAR',
            payment_method_display='WIREAR',
            next_action_url=None,
            auth_email='user@example.com',
            order_payload=original_payload,
        )

        updated_payload = {
            'status': 'REJECTED',
            'providedAddress': 'Alias changed.koywe',
        }
        merged = _merge_koywe_metadata(
            existing_metadata=initial,
            payment_method_code='WIREAR',
            payment_method_display='WIREAR',
            next_action_url='https://provider.example/redirect',
            auth_email='user@example.com',
            order_payload=updated_payload,
        )

        self.assertEqual(
            merged['instruction_snapshot_created']['provided_address'],
            'Alias original.koywe',
        )
        self.assertEqual(
            merged['instruction_snapshot_latest']['provided_address'],
            'Alias changed.koywe',
        )
        self.assertEqual(
            merged['provider_payload_created']['providedAddress'],
            'Alias original.koywe',
        )
        self.assertEqual(
            merged['provider_payload_latest']['providedAddress'],
            'Alias changed.koywe',
        )


class KoyweClientProviderMergeTests(SimpleTestCase):
    def test_merge_payment_provider_details_promotes_provider_instructions(self):
        client = KoyweClient()
        order = {
            'orderId': 'abc',
            'status': 'WAITING',
        }
        provider = {
            '_id': 'provider-id',
            'name': 'WIREAR',
            'details': 'Alias 30718280229.KOYWE1\nCBU 0000053600000017871248',
            'image': 'https://rampa.koywe.com/paymentProviders/wire-ar.png',
        }

        enriched = client._merge_payment_provider_details(order=order, payment_provider=provider)

        self.assertEqual(enriched['providedAddress'], provider['details'])
        self.assertEqual(enriched['providedAction'], provider['image'])
        self.assertEqual(enriched['paymentMethodId'], 'provider-id')
        self.assertEqual(enriched['paymentMethodDisplay'], 'WIREAR')
        self.assertEqual(enriched['paymentProvider']['details'], provider['details'])


class KoyweEmailSelectionTests(SimpleTestCase):
    def test_previous_emails_do_not_include_duende_test_accounts(self):
        emails = ramps_schema._get_koywe_previous_emails(
            country_code='AR',
            document_number='',
        )

        self.assertNotIn('duende-argentina@koywe-test.com', emails)

    def test_test_user_auth_email_still_uses_duende_override(self):
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
        })()

        email = ramps_schema._get_koywe_auth_email(user=user, country_code='MX')

        self.assertEqual(email, 'duende-mexico@koywe-test.com')


class KoyweAccountProfileTests(SimpleTestCase):
    def test_chile_rut_format_difference_satisfies_existing_profile(self):
        client = KoyweClient()
        existing = {
            'document': {
                'documentNumber': '123456785',
                'documentType': 'RUT',
                'country': 'CHL',
            },
            'personalInfo': {
                'names': 'Juan',
                'firstLastname': 'Perez',
                'phoneNumber': '56912345678',
                'dob': '1980-01-01',
            },
            'address': {
                'addressStreet': 'Apoquindo 123',
                'addressCountry': 'CHL',
                'addressZipCode': '7550000',
                'addressCity': 'Santiago',
                'addressState': 'RM',
            },
        }
        payload = {
            'document': {
                'documentNumber': '12345678-5',
                'documentType': 'RUT',
                'country': 'CHL',
            },
            'personalInfo': {
                'names': 'Juan',
                'firstLastname': 'Perez',
                'phoneNumber': '56912345678',
                'dob': '1980-01-01',
            },
            'address': {
                'addressStreet': 'Apoquindo 123',
                'addressCountry': 'CHL',
                'addressZipCode': '7550000',
                'addressCity': 'Santiago',
                'addressState': 'RM',
            },
        }

        self.assertTrue(client._account_profile_satisfies_payload(existing, payload))

    def test_chile_rut_format_difference_does_not_request_document_update(self):
        client = KoyweClient()
        payload = client._build_migration_payload(
            existing={
                'document': {
                    'documentNumber': '123456785',
                    'documentType': 'RUT',
                    'country': 'CHL',
                },
            },
            target_payload={
                'document': {
                    'documentNumber': '12345678-5',
                    'documentType': 'RUT',
                    'country': 'CHL',
                },
            },
            country_code='CL',
            current_email='user@example.com',
            new_email=None,
        )

        self.assertNotIn('updateDocumentNumber', payload)
        self.assertEqual(payload['document']['documentNumber'], '123456785')


class KoyweQuoteLimitPreflightTests(SimpleTestCase):
    def test_on_ramp_preflight_rejects_below_cached_minimum(self):
        client = type('Client', (), {
            'get_public_ramp_limits': lambda self, *, fiat_symbol: {
                'on_ramp_min_amount': Decimal('24000'),
                'on_ramp_max_amount': Decimal('8500000'),
            },
        })()

        with self.assertRaises(ramps_schema.KoyweMinimumAmountError) as ctx:
            ramps_schema._validate_koywe_on_ramp_quote_limits(
                client=client,
                amount=Decimal('25'),
                fiat_symbol='ARS',
            )

        self.assertEqual(ctx.exception.minimum, '24000')
        self.assertEqual(ctx.exception.actual, '25')

    def test_on_ramp_preflight_allows_amount_inside_limits(self):
        client = type('Client', (), {
            'get_public_ramp_limits': lambda self, *, fiat_symbol: {
                'on_ramp_min_amount': Decimal('24000'),
                'on_ramp_max_amount': Decimal('8500000'),
            },
        })()

        ramps_schema._validate_koywe_on_ramp_quote_limits(
            client=client,
            amount=Decimal('25000'),
            fiat_symbol='ARS',
        )
