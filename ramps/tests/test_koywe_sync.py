from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ramps import schema as ramps_schema
from ramps.koywe_client import KoyweClient, KoyweError
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


class KoyweExistingAccountProfileTests(SimpleTestCase):
    PAYLOAD = {
        'document': {
            'documentNumber': '1234567890',
            'documentType': 'CED_CIU',
            'country': 'COL',
            'isCompany': False,
        },
        'personalInfo': {
            'names': 'Duende',
            'firstLastname': 'Colombia',
            'activity': 'EMPLOYEE',
            'phoneNumber': '999999999',
            'dob': '1900-01-01',
        },
    }

    def test_unknown_email_reports_the_document_conflict(self):
        client = KoyweClient()

        with mock.patch.object(
            client,
            'get_account',
            side_effect=KoyweError('account not found with email: new@example.com'),
        ), mock.patch.object(client, 'update_account') as update_mock:
            with self.assertRaises(KoyweError) as ctx:
                client._ensure_existing_account_profile(
                    email='new@example.com',
                    country_code='CO',
                    payload=dict(self.PAYLOAD),
                    previous_emails=['old@example.com'],
                )

        update_mock.assert_not_called()
        self.assertIn('ya está registrado', str(ctx.exception))

    def test_failed_migration_does_not_update_the_unknown_email(self):
        client = KoyweClient()
        previous_account = {
            'email': 'old@example.com',
            'document': {
                'documentNumber': '1234567890',
                'documentType': 'CED_CIU',
                'country': 'COL',
            },
        }

        def fake_get_account(*, email):
            if email == 'old@example.com':
                return previous_account
            raise KoyweError(f'account not found with email: {email}')

        with mock.patch.object(client, 'get_account', side_effect=fake_get_account), \
                mock.patch.object(
                    client,
                    'update_account',
                    side_effect=KoyweError('email already in use'),
                ) as update_mock:
            with self.assertRaises(KoyweError) as ctx:
                client._ensure_existing_account_profile(
                    email='new@example.com',
                    country_code='CO',
                    payload=dict(self.PAYLOAD),
                    previous_emails=['old@example.com'],
                )

        # Only the migration attempt on the owning email, never a blind update
        # of the email that has no account.
        self.assertEqual(
            [call.kwargs['email'] for call in update_mock.call_args_list],
            ['old@example.com'],
        )
        self.assertIn('ya está registrado', str(ctx.exception))


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

    def test_colombia_uses_real_stored_email_for_test_user(self):
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
            'ramp_user_address': SimpleNamespace(auth_email='pse@example.com'),
        })()

        email = ramps_schema._get_koywe_auth_email(user=user, country_code='CO')

        self.assertEqual(email, 'pse@example.com')

    def test_colombia_ignores_stale_duende_delivery_email(self):
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
            'ramp_user_address': SimpleNamespace(
                auth_email='duende-peru@koywe-test.com',
            ),
        })()

        email = ramps_schema._get_koywe_auth_email(user=user, country_code='CO')

        self.assertEqual(email, 'julian@example.com')

    def test_colombia_profile_migration_includes_duende_account(self):
        user = type('User', (), {
            'username': 'julianm',
        })()

        with mock.patch.object(
            ramps_schema,
            '_get_koywe_previous_emails',
            return_value=['old@example.com'],
        ), mock.patch.object(
            ramps_schema,
            '_get_koywe_test_sibling_emails',
            return_value=[],
        ):
            emails = ramps_schema._get_koywe_profile_previous_emails(
                user=user,
                country_code='CO',
                document_number='1234567890',
                selected_email='pse@example.com',
            )

        self.assertEqual(
            emails,
            ['duende-colombia@koywe-test.com', 'old@example.com'],
        )

    def test_profile_migration_includes_prior_inbox_and_sibling_test_account(self):
        """The shared test identity can only live under one inbox at a time."""
        user = type('User', (), {
            'username': 'julianmoonluna',
        })()

        with mock.patch.object(
            ramps_schema,
            '_get_koywe_previous_emails',
            return_value=['pse@example.com', 'old@example.com'],
        ), mock.patch.object(
            ramps_schema,
            '_get_koywe_test_sibling_emails',
            return_value=['sibling@example.com'],
        ):
            emails = ramps_schema._get_koywe_profile_previous_emails(
                user=user,
                country_code='CO',
                document_number='1234567890',
                selected_email='pse@example.com',
                prior_auth_email='previous@example.com',
            )

        # The email being registered is never its own previous owner.
        self.assertEqual(
            emails,
            [
                'previous@example.com',
                'duende-colombia@koywe-test.com',
                'sibling@example.com',
                'old@example.com',
            ],
        )

    def test_profile_migration_skips_siblings_without_override(self):
        user = type('User', (), {
            'username': 'someoneelse',
        })()

        with mock.patch.object(
            ramps_schema,
            '_get_koywe_previous_emails',
            return_value=['old@example.com'],
        ), mock.patch.object(
            ramps_schema,
            '_get_koywe_test_sibling_emails',
            side_effect=AssertionError('siblings are test-only'),
        ):
            emails = ramps_schema._get_koywe_profile_previous_emails(
                user=user,
                country_code='CO',
                document_number='1234567890',
                selected_email='pse@example.com',
                prior_auth_email='duende-colombia@koywe-test.com',
            )

        # A stale duende inbox is not a real previous owner.
        self.assertEqual(emails, ['old@example.com'])

    @mock.patch.object(ramps_schema, '_get_latest_personal_verification')
    @mock.patch.object(ramps_schema, '_build_effective_ramp_address_snapshot')
    def test_colombia_real_email_keeps_test_identity(
        self,
        effective_address_mock,
        verification_mock,
    ):
        verification_mock.return_value = SimpleNamespace(
            verified_first_name='Real',
            verified_last_name='Person',
            document_number='ARG-DOCUMENT',
            document_type='national_id',
            verified_date_of_birth=None,
        )
        effective_address_mock.return_value = SimpleNamespace(
            address_street='Calle 1',
            address_city='Lima',
            address_neighborhood='',
            address_state='Lima',
            address_zip_code='15001',
            address_country='PER',
            economic_activity='EMPLOYEE',
        )
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
            'phone_country_code': '+51',
            'phone_number': '999999999',
        })()

        profile = ramps_schema._get_koywe_contact_profile(
            user=user,
            country_code='CO',
            email_override='pse@example.com',
        )

        self.assertEqual(profile['email'], 'pse@example.com')
        self.assertEqual(profile['documentType'], 'CED_CIU')
        self.assertEqual(profile['documentNumber'], '1234567890')
        self.assertEqual(profile['addressCountry'], 'COL')


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
