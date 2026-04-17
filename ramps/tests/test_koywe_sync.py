from django.test import SimpleTestCase

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
