from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from graphene_django.utils.testing import GraphQLTestCase
from graphql_jwt.testcases import JSONWebTokenTestCase
from graphql_jwt.exceptions import PermissionDenied
from graphql_jwt.utils import jwt_encode
import json
import time
from unittest import mock
from unittest.mock import patch
from users.jwt import jwt_payload_handler, verify_auth_token_version
from users.phone_utils import find_user_by_phone, phone_lookup_key
from users.migration_safety import (
    LEGACY_CONFIO_ASSET_ID,
    MATERIAL_SPENDABLE_ALGO_MICROS,
    classify_sponsored_empty_wallet,
    get_address_reassignment_blocker,
    inspect_address_migration_risk,
    inspect_sponsored_empty_wallet_reenrollment,
    revalidate_sponsored_empty_wallet_reenrollment,
)

User = get_user_model()


class UnifiedRampFeeResolverTestCase(SimpleTestCase):
    @patch('conversion.models.Conversion.objects')
    def test_external_deposit_list_preloads_fee_conversions_once(
            self, conversion_objects):
        from decimal import Decimal
        from types import SimpleNamespace
        from users.graphql_views import (
            _external_deposit_conversion,
            _preload_external_deposit_conversions,
        )

        created_at = timezone.now()
        conversion = SimpleNamespace(
            from_amount=Decimal('100'), created_at=created_at,
            actor_user_id=7, actor_business_id=None,
        )
        query = conversion_objects.filter.return_value
        query.filter.return_value = query
        query.order_by.return_value = [conversion]
        receipt = SimpleNamespace(
            sender_type='external', token_type='USDT',
            amount=Decimal('100'), created_at=created_at,
            recipient_user_id=7, recipient_business_id=None,
        )
        row = SimpleNamespace(
            transaction_type='send', send_transaction=receipt,
        )

        _preload_external_deposit_conversions([row])

        self.assertIs(_external_deposit_conversion(row), conversion)
        self.assertEqual(conversion_objects.filter.call_count, 1)

    @patch('conversion.models.Conversion.objects')
    def test_external_deposit_does_not_guess_between_same_amount_conversions(
            self, conversion_objects):
        from types import SimpleNamespace
        from users.graphql_views import _external_deposit_conversion

        first = SimpleNamespace(conversion_fee_bps=90)
        second = SimpleNamespace(conversion_fee_bps=50)
        query = conversion_objects.filter.return_value
        query.filter.return_value = query
        ordered = query.order_by.return_value
        ordered.__getitem__.return_value = [first, second]
        receipt = SimpleNamespace(
            sender_type='external', token_type='USDT', amount='100.000000',
            created_at=timezone.now(), recipient_business_id=None,
            recipient_user_id=1,
        )
        row = SimpleNamespace(
            transaction_type='send', send_transaction=receipt,
        )

        self.assertIsNone(_external_deposit_conversion(row))

    @patch('users.graphql_views._external_deposit_conversion')
    def test_external_deposit_net_is_authoritative_but_display_stays_legacy_gross(self, lookup):
        from types import SimpleNamespace
        from users.graphql_views import UnifiedTransactionType

        lookup.return_value = SimpleNamespace(
            net_amount_exact='9.91', to_amount='9.910000')
        received = SimpleNamespace(
            transaction_type='send', amount='10.000000',
            _user_address='0xviewer',
            get_direction_for_address=lambda _address: 'received',
        )
        sent = SimpleNamespace(
            transaction_type='send', amount='10.000000',
            _user_address='0xviewer',
            get_direction_for_address=lambda _address: 'sent',
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_net_amount(received, None), '9.91')
        self.assertEqual(
            UnifiedTransactionType.resolve_display_amount(received, None),
            '+10.000000',
        )
        self.assertEqual(
            UnifiedTransactionType.resolve_display_amount(sent, None),
            '-10.000000',
        )

    def test_payment_and_ramp_expose_authoritative_net_amounts(self):
        from types import SimpleNamespace
        from users.graphql_views import UnifiedTransactionType

        payment = SimpleNamespace(
            transaction_type='payment', amount='100.000000',
            _user_address='0xmerchant',
            get_direction_for_address=lambda _address: 'received',
            amount_for_direction=lambda direction: (
                '99.100000' if direction == 'received' else '100.000000'),
        )
        ramp = SimpleNamespace(
            transaction_type='ramp', amount='99.100000',
            ramp_transaction=SimpleNamespace(direction='on_ramp'),
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_net_amount(payment, None),
            '99.100000',
        )
        self.assertEqual(
            UnifiedTransactionType.resolve_net_amount(ramp, None),
            '99.100000',
        )

    def test_cusd_bsc_uses_the_bsc_viewer_address(self):
        from types import SimpleNamespace
        from users.graphql_views import _viewer_address_for

        account = SimpleNamespace(
            bsc_address='0xBSC', algorand_address='ALGORAND')
        row = SimpleNamespace(
            token_type='CUSD_BSC', from_address='', to_address='',
            sender_address='', counterparty_address='',
        )

        self.assertEqual(_viewer_address_for(row, account), '0xBSC')

    def test_aggregate_ramp_uses_its_own_allocated_fee(self):
        from types import SimpleNamespace
        from users.graphql_views import UnifiedTransactionType

        ramp = SimpleNamespace(
            status='COMPLETED',
            metadata={'conversion_allocation': {
                'gross_amount': '100.000000',
                'net_amount': '99.100000',
            }},
            conversion=SimpleNamespace(
                fee_amount_exact='4.50', conversion_fee_bps=90),
        )
        row = SimpleNamespace(
            fee_amount='', transaction_type='ramp',
            ramp_transaction=ramp, amount='99.100000',
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_fee_amount(row, None), '0.9')
        self.assertEqual(
            UnifiedTransactionType.resolve_net_amount(row, None), '99.100000')
        self.assertEqual(
            UnifiedTransactionType.resolve_fee_bps(row, None), 90)

    def test_legacy_single_ramp_uses_linked_conversion_exact_fee(self):
        from types import SimpleNamespace
        from users.graphql_views import UnifiedTransactionType

        ramp = SimpleNamespace(
            status='COMPLETED',
            metadata={},
            conversion=SimpleNamespace(
                fee_amount_exact='0.135000000000000001', fee_amount='0.135000',
                conversion_fee_bps=None),
        )
        row = SimpleNamespace(
            fee_amount='', transaction_type='ramp', ramp_transaction=ramp,
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_fee_amount(row, None),
            '0.135000000000000001',
        )
        self.assertIsNone(
            UnifiedTransactionType.resolve_fee_bps(row, None))

    def test_guardarian_nested_metadata_exposes_stored_fee_snapshot(self):
        from types import SimpleNamespace
        from ramps.signals import _ramp_fee_snapshot
        from users.graphql_views import UnifiedTransactionType

        ramp = SimpleNamespace(
            status='COMPLETED',
            metadata={'confio_fee': {
                'fee_amount': '0.135',
                'fee_bps': 90,
            }},
            conversion=None,
        )
        row = SimpleNamespace(
            fee_amount='', transaction_type='ramp', ramp_transaction=ramp,
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_fee_amount(row, None), '0.135')
        self.assertEqual(
            UnifiedTransactionType.resolve_fee_bps(row, None), 90)
        self.assertEqual(_ramp_fee_snapshot(ramp), ('0.135', 90))

    def test_failed_ramp_does_not_present_quote_as_charged_fee(self):
        from types import SimpleNamespace
        from ramps.signals import _ramp_fee_snapshot
        from users.graphql_views import UnifiedTransactionType

        ramp = SimpleNamespace(
            status='FAILED', conversion=None,
            metadata={'confio_fee': {
                'fee_amount': '0.135', 'fee_bps': 90,
            }},
        )
        row = SimpleNamespace(
            fee_amount='', transaction_type='ramp', ramp_transaction=ramp,
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_fee_amount(row, None), '')
        self.assertIsNone(
            UnifiedTransactionType.resolve_fee_bps(row, None))
        self.assertEqual(_ramp_fee_snapshot(ramp), ('', None))

    @patch('users.graphql_views._external_deposit_conversion')
    def test_external_deposit_receipt_exposes_completed_conversion(self, lookup):
        from types import SimpleNamespace
        from users.graphql_views import UnifiedTransactionType

        lookup.return_value = SimpleNamespace(
            fee_amount_exact='0.090000000000000001',
            fee_amount='0.090000',
            net_amount_exact='9.909999999999999999',
            to_amount='9.910000',
            to_token='CUSD_PLUS',
            conversion_fee_bps=90,
        )
        row = SimpleNamespace(
            fee_amount='', transaction_type='send', amount='10.000000',
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_fee_amount(row, None),
            '0.090000000000000001',
        )
        self.assertEqual(
            UnifiedTransactionType.resolve_net_amount(row, None),
            '9.909999999999999999',
        )
        self.assertEqual(
            UnifiedTransactionType.resolve_to_token(row, None), 'CUSD_PLUS')
        self.assertEqual(
            UnifiedTransactionType.resolve_fee_bps(row, None), 90)

    @patch('users.graphql_views._external_deposit_conversion')
    def test_zero_fee_external_conversion_still_exposes_net_and_destination(self, lookup):
        from types import SimpleNamespace
        from users.graphql_views import UnifiedTransactionType

        lookup.return_value = SimpleNamespace(
            fee_amount_exact=0, fee_amount=0,
            net_amount_exact='10', to_amount='10.000000',
            to_token='CUSD_BSC',
        )
        row = SimpleNamespace(
            fee_amount='', transaction_type='send', amount='10.000000',
        )

        self.assertEqual(
            UnifiedTransactionType.resolve_fee_amount(row, None), '')
        self.assertEqual(
            UnifiedTransactionType.resolve_net_amount(row, None), '10')
        self.assertEqual(
            UnifiedTransactionType.resolve_to_token(row, None), 'CUSD_BSC')

    @patch('users.graphql_views._external_deposit_conversion')
    @patch('send.schema._send_unified_receipt')
    def test_send_detail_query_reuses_unified_external_receipt(
            self, unified_lookup, conversion_lookup):
        from decimal import Decimal
        from types import SimpleNamespace
        from send.schema import SendTransactionType

        conversion_lookup.return_value = SimpleNamespace(
            fee_amount_exact='0.09', fee_amount='0.090000',
            net_amount_exact='9.91', to_amount='9.910000',
            to_token='CUSD_PLUS', conversion_fee_bps=90,
        )
        unified_lookup.return_value = SimpleNamespace(
            fee_amount='', transaction_type='send', amount='10.000000',
        )
        send = SimpleNamespace(
            fee_amount=Decimal(0), net_amount=None, amount=Decimal('10'),
        )

        self.assertEqual(
            SendTransactionType.resolve_fee_amount(send, None), '0.09')
        self.assertEqual(
            SendTransactionType.resolve_net_amount(send, None), '9.91')
        self.assertEqual(
            SendTransactionType.resolve_to_token(send, None), 'CUSD_PLUS')
        self.assertEqual(
            SendTransactionType.resolve_fee_bps(send, None), 90)

    @patch('send.schema._send_unified_receipt')
    def test_pending_send_detail_uses_prepared_fee_snapshot(self, unified_lookup):
        from decimal import Decimal
        from types import SimpleNamespace
        from send.schema import SendTransactionType

        unified_lookup.return_value = None
        send = SimpleNamespace(
            fee_amount=Decimal(0), net_amount=None, amount=Decimal('100'),
            bsc_calls_json=json.dumps({'receipt': {
                'gross': '100', 'fee': '0.9', 'net': '99.1',
                'fee_bps': 90, 'finalized': False,
            }}),
        )

        self.assertEqual(
            SendTransactionType.resolve_fee_amount(send, None), '0.9')
        self.assertEqual(
            SendTransactionType.resolve_net_amount(send, None), '99.1')
        self.assertEqual(
            SendTransactionType.resolve_fee_bps(send, None), 90)
        unified_lookup.assert_not_called()

    @patch('send.schema._send_unified_receipt')
    def test_finalized_zero_fee_beats_older_prepared_snapshot(self, unified_lookup):
        from decimal import Decimal
        from types import SimpleNamespace
        from send.schema import SendTransactionType

        send = SimpleNamespace(
            fee_amount=Decimal(0), net_amount=Decimal('100'),
            amount=Decimal('100'),
            bsc_calls_json=json.dumps({'receipt': {
                'gross': '100', 'fee': '0.9', 'net': '99.1',
                'fee_bps': 90, 'finalized': False,
            }}),
        )

        self.assertEqual(
            SendTransactionType.resolve_fee_amount(send, None), '0')
        self.assertEqual(
            SendTransactionType.resolve_net_amount(send, None), '100')
        self.assertIsNone(
            SendTransactionType.resolve_fee_bps(send, None))
        unified_lookup.assert_not_called()

    @patch('send.schema._send_unified_receipt')
    def test_prepared_receipt_ignores_non_object_json(self, unified_lookup):
        from decimal import Decimal
        from types import SimpleNamespace
        from send.schema import SendTransactionType

        unified_lookup.return_value = None
        send = SimpleNamespace(
            fee_amount=Decimal(0), net_amount=None, amount=Decimal('100'),
            bsc_calls_json='[]',
        )

        self.assertEqual(
            SendTransactionType.resolve_fee_amount(send, None), '')
        self.assertEqual(
            SendTransactionType.resolve_net_amount(send, None), '100')
        self.assertIsNone(
            SendTransactionType.resolve_fee_bps(send, None))


class UserSoftDeleteAuthTestCase(TestCase):
    def test_soft_deleted_users_are_hidden_from_default_manager(self):
        user = User.objects.create_user(
            username='deleteduser',
            email='deleted@example.com',
            password='testpass123',
            firebase_uid='deleted-firebase-uid',
        )

        user.soft_delete()

        self.assertFalse(User.objects.filter(id=user.id).exists())
        self.assertTrue(User.all_objects.filter(id=user.id).exists())

        deleted_user = User.all_objects.get(id=user.id)
        self.assertFalse(deleted_user.is_active)
        self.assertIsNotNone(deleted_user.deleted_at)
        self.assertEqual(deleted_user.auth_token_version, 2)

    def test_soft_delete_invalidates_existing_jwt(self):
        user = User.objects.create_user(
            username='tokenuser',
            email='token@example.com',
            password='testpass123',
            firebase_uid='token-firebase-uid',
        )
        token = jwt_encode(jwt_payload_handler(user))

        user.soft_delete()

        with self.assertRaises(PermissionDenied):
            verify_auth_token_version(token)

class AccountBalanceQueryTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

    def test_account_balance_query(self):
        """The resolver returns safely formatted values from BalanceService."""
        from .schema import Query
        
        # Mock the GraphQL context
        class MockContext:
            def __init__(self, user):
                self.user = user
        
        # Mock the GraphQL info object
        class MockInfo:
            def __init__(self, context):
                self.context = context
        
        context = MockContext(self.user)
        info = MockInfo(context)
        
        # Test the resolver directly
        query = Query()
        
        balances = {
            'CUSD': '2850.3599999',
            'CONFIO': '234.18',
            'USDC': '458.22',
            'UNKNOWN': '0',
        }
        account = mock.Mock(algorand_address='A' * 58)

        with patch(
            'users.jwt_context.get_jwt_business_context_with_validation',
            return_value={
                'account_type': 'personal',
                'account_index': 0,
                'business_id': None,
                'employee_record': None,
            },
        ), patch('users.models.Account.objects.get', return_value=account), patch(
            'blockchain.balance_service.BalanceService.get_balance',
            side_effect=lambda _account, token, force_refresh: {
                'amount': balances[token],
            },
        ):
            self.assertEqual(query.resolve_account_balance(info, 'cUSD'), '2850.359999')
            self.assertEqual(query.resolve_account_balance(info, 'CONFIO'), '234.180000')
            self.assertEqual(query.resolve_account_balance(info, 'USDC'), '458.220000')
            self.assertEqual(query.resolve_account_balance(info, 'UNKNOWN'), '0.000000')

    def test_account_balance_requires_authentication(self):
        """Test that account balance query requires authentication"""
        from .schema import Query
        
        # Mock the GraphQL context with no user
        class MockContext:
            def __init__(self):
                self.user = None
        
        # Mock the GraphQL info object
        class MockInfo:
            def __init__(self, context):
                self.context = context
        
        context = MockContext()
        info = MockInfo(context)
        
        # Test the resolver directly
        query = Query()
        result = query.resolve_account_balance(info, 'cUSD')
        self.assertEqual(result, '0')


class MigrationSafetyTestCase(SimpleTestCase):
    class FakeAlgodClient:
        def __init__(self, responses):
            self.responses = responses

        def account_info(self, address):
            return self.responses[address]

    def test_detects_relevant_asset_balance(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 500000,
                'min-balance': 400000,
                'assets': [
                    {'asset-id': LEGACY_CONFIO_ASSET_ID, 'amount': 123456},
                ],
            }
        })

        risk = inspect_address_migration_risk(algod, 'legacy')
        self.assertTrue(risk['has_material_risk'])
        self.assertEqual(risk['relevant_assets'][LEGACY_CONFIO_ASSET_ID], 123456)

    def test_detects_spendable_algo_even_without_assets(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 400000 + MATERIAL_SPENDABLE_ALGO_MICROS,
                'min-balance': 400000,
                'assets': [],
            }
        })

        risk = inspect_address_migration_risk(algod, 'legacy')
        self.assertTrue(risk['has_material_risk'])
        self.assertEqual(risk['spendable_algo'], MATERIAL_SPENDABLE_ALGO_MICROS)

    def test_blocks_reassignment_when_legacy_wallet_still_holds_value(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 828500,
                'min-balance': 400000,
                'assets': [
                    {'asset-id': 31566704, 'amount': 111850196},
                ],
            }
        })

        blocker = get_address_reassignment_blocker(algod, 'legacy', 'new')
        self.assertIsNotNone(blocker)

    def test_allows_reassignment_when_old_wallet_is_empty(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 0,
                'min-balance': 0,
                'assets': [],
            }
        })

        blocker = get_address_reassignment_blocker(algod, 'legacy', 'new')
        self.assertIsNone(blocker)

    def test_allows_reenrollment_for_sponsor_funding_and_zero_value_opt_ins(self):
        address = 'A' * 58
        sponsor = 'S' * 58
        result = classify_sponsored_empty_wallet(
            {
                'amount': 500000,
                'min-balance': 400000,
                'assets': [
                    {'asset-id': 1, 'amount': 0},
                    {'asset-id': 2, 'amount': 0},
                    {'asset-id': 3, 'amount': 0},
                ],
                'apps-local-state': [],
                'created-apps': [],
                'created-assets': [],
            },
            [
                {
                    'tx-type': 'pay',
                    'sender': sponsor,
                    'payment-transaction': {'receiver': address, 'amount': 500000},
                },
                {
                    'tx-type': 'axfer',
                    'sender': address,
                    'asset-transfer-transaction': {
                        'receiver': address,
                        'asset-id': 1,
                        'amount': 0,
                    },
                },
            ],
            address,
            sponsor,
        )

        self.assertTrue(result['eligible'])
        self.assertEqual(result['reason'], 'sponsor_only_empty_wallet')

    def test_reenrollment_fails_closed_on_any_user_asset_or_payment_activity(self):
        address = 'A' * 58
        sponsor = 'S' * 58
        base_info = {
            'amount': 500000,
            'min-balance': 400000,
            'assets': [{'asset-id': 1, 'amount': 0}],
        }
        sponsor_txn = {
            'tx-type': 'pay',
            'sender': sponsor,
            'payment-transaction': {'receiver': address, 'amount': 500000},
        }

        with_asset = dict(base_info, assets=[{'asset-id': 1, 'amount': 1}])
        self.assertFalse(classify_sponsored_empty_wallet(
            with_asset, [sponsor_txn], address, sponsor
        )['eligible'])

        user_payment = {
            'tx-type': 'pay',
            'sender': address,
            'payment-transaction': {'receiver': 'R' * 58, 'amount': 1},
        }
        self.assertFalse(classify_sponsored_empty_wallet(
            base_info, [sponsor_txn, user_payment], address, sponsor
        )['eligible'])

    def test_reenrollment_reads_complete_paginated_history(self):
        address = 'A' * 58
        sponsor = 'S' * 58

        class FakeIndexer:
            def search_transactions(self, address, limit, next_page, max_round):
                if next_page is None:
                    return {
                        'current-round': max_round,
                        'transactions': [{
                            'tx-type': 'pay',
                            'sender': sponsor,
                            'payment-transaction': {
                                'receiver': address,
                                'amount': 500000,
                            },
                        }],
                        'next-token': 'page-2',
                    }
                return {
                    'current-round': max_round,
                    'transactions': [{
                        'tx-type': 'axfer',
                        'sender': address,
                        'asset-transfer-transaction': {
                            'receiver': address,
                            'asset-id': 1,
                            'amount': 0,
                        },
                    }],
                }

        algod = self.FakeAlgodClient({
            address: {
                'round': 12345,
                'amount': 500000,
                'min-balance': 200000,
                'assets': [{'asset-id': 1, 'amount': 0}],
            },
        })
        result = inspect_sponsored_empty_wallet_reenrollment(
            algod, FakeIndexer(), address, sponsor
        )
        self.assertTrue(result['eligible'])
        self.assertEqual(result['snapshot_round'], 12345)
        self.assertEqual(result['sponsor_funding'], 500000)

    def test_reenrollment_completion_scans_only_rounds_after_preflight(self):
        address = 'A' * 58
        sponsor = 'S' * 58
        calls = []

        class DeltaIndexer:
            def search_transactions(self, **kwargs):
                calls.append(kwargs)
                return {
                    'current-round': kwargs['max_round'],
                    'transactions': [],
                }

        algod = self.FakeAlgodClient({
            address: {
                'round': 12355,
                'amount': 500000,
                'min-balance': 200000,
                'assets': [{'asset-id': 1, 'amount': 0}],
            },
        })
        result = revalidate_sponsored_empty_wallet_reenrollment(
            algod,
            DeltaIndexer(),
            address,
            sponsor,
            snapshot_round=12345,
            sponsor_funding=500000,
        )

        self.assertTrue(result['eligible'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['min_round'], 12346)
        self.assertEqual(calls[0]['max_round'], 12355)

    def test_reenrollment_completion_refuses_any_post_preflight_activity(self):
        address = 'A' * 58
        sponsor = 'S' * 58

        class ActiveIndexer:
            def search_transactions(self, **kwargs):
                return {
                    'current-round': kwargs['max_round'],
                    'transactions': [{'tx-type': 'pay'}],
                }

        algod = self.FakeAlgodClient({
            address: {
                'round': 12355,
                'amount': 500000,
                'min-balance': 200000,
                'assets': [],
            },
        })
        result = revalidate_sponsored_empty_wallet_reenrollment(
            algod,
            ActiveIndexer(),
            address,
            sponsor,
            snapshot_round=12345,
            sponsor_funding=500000,
        )

        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'activity_after_snapshot')

    def test_reenrollment_completion_skips_indexer_when_snapshot_is_current(self):
        address = 'A' * 58
        sponsor = 'S' * 58
        indexer = mock.Mock()
        algod = self.FakeAlgodClient({
            address: {
                'round': 12345,
                'amount': 500000,
                'min-balance': 200000,
                'assets': [],
            },
        })

        result = revalidate_sponsored_empty_wallet_reenrollment(
            algod,
            indexer,
            address,
            sponsor,
            snapshot_round=12345,
            sponsor_funding=500000,
        )

        self.assertTrue(result['eligible'])
        self.assertEqual(result['snapshot_round'], 12345)
        indexer.search_transactions.assert_not_called()

    def test_reenrollment_completion_refuses_regressed_algod_round(self):
        address = 'A' * 58
        algod = self.FakeAlgodClient({
            address: {
                'round': 12344,
                'amount': 500000,
                'min-balance': 200000,
                'assets': [],
            },
        })

        result = revalidate_sponsored_empty_wallet_reenrollment(
            algod,
            mock.Mock(),
            address,
            'S' * 58,
            snapshot_round=12345,
            sponsor_funding=500000,
        )

        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'algod_round_regressed')

    def test_reenrollment_completion_refuses_lagging_indexer(self):
        address = 'A' * 58

        class LaggingDeltaIndexer:
            def search_transactions(self, **kwargs):
                return {
                    'current-round': kwargs['max_round'] - 1,
                    'transactions': [],
                }

        algod = self.FakeAlgodClient({
            address: {
                'round': 12355,
                'amount': 500000,
                'min-balance': 200000,
                'assets': [],
            },
        })
        result = revalidate_sponsored_empty_wallet_reenrollment(
            algod,
            LaggingDeltaIndexer(),
            address,
            'S' * 58,
            snapshot_round=12345,
            sponsor_funding=500000,
        )

        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'indexer_lagging')

    def test_reenrollment_fails_closed_when_indexer_lags_algod_snapshot(self):
        address = 'A' * 58
        sponsor = 'S' * 58

        class LaggingIndexer:
            def search_transactions(self, **kwargs):
                return {
                    'current-round': kwargs['max_round'] - 1,
                    # The omitted latest outbound transaction would otherwise
                    # make this sponsor payment look like complete history.
                    'transactions': [{
                        'tx-type': 'pay',
                        'sender': sponsor,
                        'payment-transaction': {
                            'receiver': address,
                            'amount': 500000,
                        },
                    }],
                }

        algod = self.FakeAlgodClient({
            address: {
                'round': 12345,
                'amount': 400000,
                'min-balance': 100000,
                'assets': [],
            },
        })
        result = inspect_sponsored_empty_wallet_reenrollment(
            algod, LaggingIndexer(), address, sponsor
        )
        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'indexer_lagging')

    def test_reenrollment_fails_closed_when_indexer_is_unavailable(self):
        address = 'A' * 58

        class FailingIndexer:
            def search_transactions(self, **kwargs):
                raise TimeoutError('indexer unavailable')

        algod = self.FakeAlgodClient({
            address: {'round': 12345, 'amount': 0, 'min-balance': 0, 'assets': []},
        })
        result = inspect_sponsored_empty_wallet_reenrollment(
            algod, FailingIndexer(), address, 'S' * 58
        )
        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'inspection_failed')

    def test_reenrollment_blocks_recent_prepared_algorand_inbound(self):
        from types import SimpleNamespace
        from users.web3auth_schema import _inspect_wallet_reenrollment

        reservation_query = mock.Mock()
        reservation_query.filter.return_value = reservation_query
        reservation_query.exists.return_value = True
        account = SimpleNamespace(algorand_address='A' * 58)

        with patch(
            'send.models.SendTransaction.all_objects.filter',
            return_value=reservation_query,
        ), patch('blockchain.algorand_client.get_algod_client') as algod_mock:
            result = _inspect_wallet_reenrollment(account)

        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'pending_inbound_algorand_send')
        algod_mock.assert_not_called()

    def test_reenrollment_blocks_retryable_humanitarian_release(self):
        from types import SimpleNamespace
        from users.web3auth_schema import _inspect_wallet_reenrollment

        empty_send_query = mock.Mock()
        empty_send_query.filter.return_value = empty_send_query
        empty_send_query.exists.return_value = False
        release_query = mock.Mock()
        release_query.exists.return_value = True
        account = SimpleNamespace(algorand_address='A' * 58)

        with patch(
            'send.models.SendTransaction.all_objects.filter',
            return_value=empty_send_query,
        ), patch(
            'humanitarian.models.HumanitarianRelease.objects.filter',
            return_value=release_query,
        ), patch('blockchain.algorand_client.get_algod_client') as algod_mock:
            result = _inspect_wallet_reenrollment(account)

        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'pending_humanitarian_release')
        algod_mock.assert_not_called()


class WalletReenrollmentReservationTestCase(TestCase):
    def setUp(self):
        from users.models import Account

        self.sender = User.objects.create_user(
            username='reservation-sender',
            email='reservation-sender@example.com',
            password='password123',
            firebase_uid='uid-reservation-sender',
        )
        recipient = User.objects.create_user(
            username='reservation-recipient',
            email='reservation-recipient@example.com',
            password='password123',
            firebase_uid='uid-reservation-recipient',
        )
        self.account = Account.objects.create(
            user=recipient,
            account_type='personal',
            account_index=0,
            algorand_address='R' * 58,
        )

    def _send(self, **overrides):
        from send.models import SendTransaction

        values = {
            'sender_user': self.sender,
            'recipient_user': self.account.user,
            'sender_address': 'S' * 58,
            'recipient_address': self.account.algorand_address,
            'amount': '1',
            'token_type': 'CUSD',
            'status': 'PENDING',
            'idempotency_key': f"group-{SendTransaction.all_objects.count()}",
            'bsc_calls_json': '',
            'deleted_at': timezone.now(),
        }
        values.update(overrides)
        return SendTransaction.all_objects.create(**values)

    def test_recent_hidden_prepare_blocks_reenrollment(self):
        from users.web3auth_schema import _wallet_reenrollment_server_blocker

        self._send()

        self.assertEqual(
            _wallet_reenrollment_server_blocker(self.account),
            'pending_inbound_algorand_send',
        )

    def test_old_hidden_prepare_does_not_block_reenrollment(self):
        from datetime import timedelta
        from send.models import SendTransaction
        from users.web3auth_schema import _wallet_reenrollment_server_blocker

        reservation = self._send()
        SendTransaction.all_objects.filter(pk=reservation.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        self.assertIsNone(_wallet_reenrollment_server_blocker(self.account))

    def test_soft_deleted_submitted_send_does_not_block_reenrollment(self):
        from users.web3auth_schema import _wallet_reenrollment_server_blocker

        self._send(status='SUBMITTED')

        self.assertIsNone(_wallet_reenrollment_server_blocker(self.account))

    def test_visible_submitted_send_blocks_reenrollment(self):
        from users.web3auth_schema import _wallet_reenrollment_server_blocker

        self._send(status='SUBMITTED', deleted_at=None)

        self.assertEqual(
            _wallet_reenrollment_server_blocker(self.account),
            'pending_inbound_algorand_send',
        )


class WalletReenrollmentProofTestCase(SimpleTestCase):
    def setUp(self):
        from types import SimpleNamespace
        from eth_account import Account as EvmAccount

        self.private_key = '0x' + ('11' * 32)
        self.address = EvmAccount.from_key(self.private_key).address
        self.google_subject = 'google-subject-123'
        self.google_auth_time = int(time.time())
        self.user = SimpleNamespace(id=123, email='wallet-owner@example.com')
        self.account = SimpleNamespace(
            id=456,
            algorand_address='A' * 58,
            bsc_address=None,
        )

    def _proof(self, google_auth_time=None):
        from eth_account import Account as EvmAccount
        from eth_account.messages import encode_defunct
        from users.web3auth_schema import _issue_wallet_reenrollment_grant

        challenge, grant = _issue_wallet_reenrollment_grant(
            self.user,
            self.account,
            self.google_subject,
            google_auth_time or self.google_auth_time,
            {
                'eligible': True,
                'snapshot_round': 12345,
                'sponsor_funding': 500000,
            },
        )
        signature = EvmAccount.sign_message(
            encode_defunct(text=challenge),
            private_key=self.private_key,
        ).signature.hex()
        return grant, signature

    def test_reenrollment_requires_recent_google_authentication(self):
        from users.web3auth_schema import _is_recent_google_auth

        now = 1_800_000_000
        self.assertTrue(_is_recent_google_auth(now - 30, now=now))
        self.assertFalse(_is_recent_google_auth(now - 601, now=now))
        self.assertFalse(_is_recent_google_auth(None, now=now))
        self.assertFalse(_is_recent_google_auth(now + 61, now=now))

    def test_login_hot_path_contains_no_wallet_chain_inspection(self):
        import inspect
        from users.web3auth_schema import Web3AuthLoginMutation

        source = inspect.getsource(Web3AuthLoginMutation.mutate)
        self.assertNotIn('_inspect_wallet_reenrollment(', source)
        self.assertIn('_wallet_reenrollment_assessment(', source)
        self.assertIn(
            'requires_backup_completion=user.requires_backup_completion',
            source,
        )

    def test_completion_does_not_hold_database_transaction_during_chain_io(self):
        import inspect
        from users.web3auth_schema import CompleteWalletReenrollmentMutation

        source = inspect.getsource(CompleteWalletReenrollmentMutation.mutate)
        chain_check = source.index('inspected_reenrollment = _revalidate_wallet_reenrollment')
        transaction_start = source.index('with transaction.atomic():')
        self.assertLess(chain_check, transaction_start)
        self.assertNotIn('_revalidate_wallet_reenrollment(account,', source)
        self.assertNotIn('_inspect_stale_bsc_reenrollment(account)', source)

    def test_background_assessment_retry_is_not_scheduled_every_minute(self):
        from config.celery import app

        schedule = app.conf.beat_schedule['users-wallet-reenrollment-assessments']['schedule']
        self.assertNotEqual(schedule, 60.0)

    def test_algorand_onboarding_never_runs_for_ordinary_login(self):
        from users.web3auth_schema import _should_run_algorand_onboarding

        self.assertFalse(_should_run_algorand_onboarding(False, None, 'A' * 58))
        self.assertFalse(_should_run_algorand_onboarding(False, 'A' * 58, 'A' * 58))
        self.assertTrue(_should_run_algorand_onboarding(True, 'A' * 58, 'A' * 58))

    def test_preparation_token_is_bound_to_account_and_recent_google_login(self):
        from users.web3auth_schema import (
            _issue_wallet_reenrollment_preparation,
            _verify_wallet_reenrollment_preparation,
        )

        token = _issue_wallet_reenrollment_preparation(
            self.user,
            self.account,
            self.google_subject,
            self.google_auth_time,
        )
        self.assertIsNotNone(_verify_wallet_reenrollment_preparation(
            token, self.user, self.account
        ))
        self.account.algorand_address = 'B' * 58
        self.assertIsNone(_verify_wallet_reenrollment_preparation(
            token, self.user, self.account
        ))

    def test_background_assessment_is_anchor_bound_and_login_read_is_db_only(self):
        from users.web3auth_schema import (
            _store_wallet_reenrollment_assessment,
            _wallet_reenrollment_assessment,
        )

        self.account.wallet_reenrollment_assessment = {}
        self.account.wallet_reenrollment_assessed_at = None
        self.account.wallet_reenrollment_assessment_lease = 'older-worker'
        self.account.wallet_reenrollment_assessment_started_at = timezone.now()
        self.account.save = mock.Mock()
        stored = _store_wallet_reenrollment_assessment(self.account, {
            'eligible': True,
            'reason': 'sponsor_only_empty_wallet',
            'snapshot_round': 12345,
            'sponsor_funding': 500000,
        })

        self.assertEqual(stored['status'], 'eligible')
        self.assertEqual(self.account.wallet_reenrollment_assessment_lease, '')
        self.assertIsNone(self.account.wallet_reenrollment_assessment_started_at)
        self.assertIn(
            'wallet_reenrollment_assessment_lease',
            self.account.save.call_args.kwargs['update_fields'],
        )
        self.assertEqual(
            _wallet_reenrollment_assessment(self.account)['snapshot_round'],
            12345,
        )
        self.account.algorand_address = 'B' * 58
        self.assertIsNone(_wallet_reenrollment_assessment(self.account))

    def test_permanent_refusal_is_stored_while_transient_failure_retries(self):
        from users.web3auth_schema import _store_wallet_reenrollment_assessment

        self.account.save = mock.Mock()
        permanent = _store_wallet_reenrollment_assessment(
            self.account,
            {'eligible': False, 'reason': 'non_sponsor_payment'},
        )
        transient = _store_wallet_reenrollment_assessment(
            self.account,
            {'eligible': False, 'reason': 'inspection_failed'},
        )
        unproven_funding = _store_wallet_reenrollment_assessment(
            self.account,
            {'eligible': False, 'reason': 'unproven_funding'},
        )

        self.assertEqual(permanent['status'], 'ineligible')
        self.assertEqual(transient['status'], 'retry')
        self.assertEqual(unproven_funding['status'], 'ineligible')

    @patch('users.web3auth_schema.Account.objects.filter')
    def test_assessment_lease_is_atomic_and_owner_checked(self, filter_mock):
        from users.web3auth_schema import (
            _acquire_wallet_reenrollment_assessment_lease,
            _release_wallet_reenrollment_assessment_lease,
        )

        acquire_query = mock.Mock()
        acquire_query.filter.return_value = acquire_query
        acquire_query.update.return_value = 1
        release_query = mock.Mock()
        release_query.update.return_value = 1
        filter_mock.side_effect = [acquire_query, release_query]

        lease = _acquire_wallet_reenrollment_assessment_lease(456)
        self.assertTrue(lease)
        self.assertTrue(_release_wallet_reenrollment_assessment_lease(456, lease))
        self.assertEqual(filter_mock.call_args_list[1].kwargs['wallet_reenrollment_assessment_lease'], lease)

    @patch('users.tasks.assess_wallet_reenrollment_account.delay')
    @patch('users.web3auth_schema._acquire_wallet_reenrollment_assessment_lease')
    @patch('users.models.Account.objects.filter')
    def test_background_queue_reassesses_terminal_status_bound_to_old_anchor(
        self,
        filter_mock,
        acquire_mock,
        delay_mock,
    ):
        from users.tasks import queue_wallet_reenrollment_assessments

        self.account.algorand_address = 'B' * 58
        self.account.wallet_reenrollment_assessment = {
            'version': 1,
            'status': 'eligible',
            'eligible': True,
            'reason': 'sponsor_only_empty_wallet',
            'old_algorand_address': 'A' * 58,
            'old_bsc_address': '',
            'snapshot_round': 12345,
            'sponsor_funding': 500000,
        }
        self.account.wallet_reenrollment_assessed_at = timezone.now()
        queryset = mock.Mock()
        queryset.only.return_value = queryset
        queryset.order_by.return_value = queryset
        queryset.iterator.return_value = iter([self.account])
        filter_mock.return_value = queryset
        acquire_mock.return_value = 'lease-token'

        queued = queue_wallet_reenrollment_assessments.run(batch_size=25)

        self.assertEqual(queued, 1)
        acquire_mock.assert_called_once_with(self.account.id)
        delay_mock.assert_called_once_with(self.account.id, 'lease-token')

    @patch('users.tasks.assess_wallet_reenrollment_account.run')
    @patch('users.models.Account.objects.filter')
    def test_prewarm_gate_processes_terminal_status_bound_to_old_anchor(
        self,
        filter_mock,
        run_mock,
    ):
        from users.management.commands.precompute_wallet_reenrollment import Command

        self.account.algorand_address = 'B' * 58
        self.account.wallet_reenrollment_assessment = {
            'version': 1,
            'status': 'eligible',
            'eligible': True,
            'reason': 'sponsor_only_empty_wallet',
            'old_algorand_address': 'A' * 58,
            'old_bsc_address': '',
            'snapshot_round': 12345,
            'sponsor_funding': 500000,
        }
        initial = mock.Mock()
        initial.only.return_value = initial
        initial.order_by.return_value = initial
        initial.iterator.return_value = iter([self.account])
        remaining = mock.Mock()
        remaining.only.return_value = remaining
        remaining.iterator.side_effect = lambda chunk_size: iter([self.account])
        filter_mock.side_effect = [initial, remaining]

        def mark_current(_account_id):
            self.account.wallet_reenrollment_assessment['old_algorand_address'] = 'B' * 58
            return 'eligible'

        run_mock.side_effect = mark_current

        Command().handle(limit=0)

        run_mock.assert_called_once_with(self.account.id)

    @patch('users.tasks.assess_wallet_reenrollment_account.run')
    @patch('users.models.Account.objects.filter')
    def test_prewarm_gate_fails_release_when_any_candidate_remains_unassessed(
        self,
        filter_mock,
        run_mock,
    ):
        from django.core.management.base import CommandError
        from users.management.commands.precompute_wallet_reenrollment import Command

        initial = mock.Mock()
        initial.only.return_value = initial
        initial.order_by.return_value = initial
        initial.iterator.return_value = iter([self.account])
        remaining = mock.Mock()
        remaining.only.return_value = remaining
        remaining.iterator.side_effect = lambda chunk_size: iter([self.account])
        filter_mock.side_effect = [initial, remaining]
        run_mock.return_value = 'already_running'

        with self.assertRaisesMessage(CommandError, 'prewarm is incomplete'):
            Command().handle(limit=0)

    @patch('users.tasks.transaction.atomic')
    @patch('users.web3auth_schema._wallet_reenrollment_assessment')
    @patch('users.web3auth_schema._store_wallet_reenrollment_assessment')
    @patch('users.web3auth_schema._inspect_wallet_reenrollment')
    @patch('users.web3auth_schema._release_wallet_reenrollment_assessment_lease')
    @patch('users.models.Account.objects.select_for_update')
    @patch('users.models.Account.objects.filter')
    def test_background_worker_cannot_publish_after_losing_its_lease(
        self,
        filter_mock,
        select_for_update_mock,
        release_mock,
        inspect_mock,
        store_mock,
        assessment_mock,
        atomic_mock,
    ):
        from contextlib import nullcontext
        from users.tasks import assess_wallet_reenrollment_account

        owned = mock.Mock()
        owned.exists.return_value = True
        candidate = mock.Mock()
        candidate.first.return_value = self.account
        self.account.pk = self.account.id
        locked_account = mock.Mock(
            is_keyless_migrated=False,
            algorand_address=self.account.algorand_address,
            bsc_address=self.account.bsc_address,
            wallet_reenrollment_assessment_lease='newer-worker',
        )
        locked = mock.Mock()
        locked.first.return_value = locked_account
        filter_mock.side_effect = [owned, candidate]
        select_for_update_mock.return_value.filter.return_value = locked
        assessment_mock.return_value = None
        inspect_mock.return_value = {
            'eligible': True,
            'reason': 'sponsor_only_empty_wallet',
            'snapshot_round': 12345,
            'sponsor_funding': 500000,
        }
        atomic_mock.return_value = nullcontext()

        result = assess_wallet_reenrollment_account.run(
            self.account.id,
            lease='older-worker',
        )

        self.assertEqual(result, 'lease_or_account_changed')
        store_mock.assert_not_called()
        release_mock.assert_called_once_with(self.account.id, 'older-worker')

    def test_accepts_signature_from_submitted_bsc_address(self):
        from users.web3auth_schema import _verify_wallet_reenrollment_grant

        grant, signature = self._proof()
        self.assertTrue(_verify_wallet_reenrollment_grant(
            grant, self.user, self.account, self.address, signature
        ))

    def test_rejects_wrong_address_and_changed_legacy_anchor(self):
        from users.web3auth_schema import _verify_wallet_reenrollment_grant

        grant, signature = self._proof()
        self.assertFalse(_verify_wallet_reenrollment_grant(
            grant, self.user, self.account, '0x' + ('2' * 40), signature
        ))
        self.account.algorand_address = 'B' * 58
        self.assertFalse(_verify_wallet_reenrollment_grant(
            grant, self.user, self.account, self.address, signature
        ))

    def test_rejects_grant_when_bsc_anchor_changes(self):
        from users.web3auth_schema import _verify_wallet_reenrollment_grant

        self.account.bsc_address = '0x' + ('3' * 40)
        grant, signature = self._proof()
        self.account.bsc_address = '0x' + ('4' * 40)
        self.assertFalse(_verify_wallet_reenrollment_grant(
            grant, self.user, self.account, self.address, signature
        ))

    @patch('users.web3auth_schema.signing.loads')
    def test_rejects_expired_grant(self, loads_mock):
        from django.core.signing import SignatureExpired
        from users.web3auth_schema import _verify_wallet_reenrollment_grant

        loads_mock.side_effect = SignatureExpired('expired')
        grant, signature = self._proof()
        self.assertFalse(_verify_wallet_reenrollment_grant(
            grant, self.user, self.account, self.address, signature
        ))

    def test_rejects_grant_when_google_auth_is_no_longer_recent(self):
        from users.web3auth_schema import _verify_wallet_reenrollment_grant

        grant, signature = self._proof(google_auth_time=int(time.time()) - 601)
        self.assertFalse(_verify_wallet_reenrollment_grant(
            grant, self.user, self.account, self.address, signature
        ))


@override_settings(BSC_VESTING_VAULT_ADDRESS='0x' + ('9' * 40))
class StaleBscReenrollmentSafetyTestCase(SimpleTestCase):
    def _inspect(
        self,
        *,
        native='0x0',
        nonce='0x0',
        rpc_error=None,
        pending_send=False,
        pending_payroll=False,
        ramp_history=False,
        vesting_allocated=0,
        vesting_claimed=0,
        rpc_calls=None,
    ):
        from types import SimpleNamespace
        from users.web3auth_schema import _inspect_stale_bsc_reenrollment

        account = SimpleNamespace(
            id=456,
            user=SimpleNamespace(id=123),
            bsc_address='0x' + ('3' * 40),
        )
        empty_query = mock.Mock()
        empty_query.exists.return_value = False
        empty_query.exclude.return_value = empty_query
        send_query = mock.Mock()
        send_query.exists.return_value = pending_send
        send_query.exclude.return_value = send_query
        payroll_query = mock.Mock()
        payroll_query.exists.return_value = pending_payroll
        ramp_query = mock.Mock()
        ramp_query.exists.return_value = ramp_history

        def rpc(method, params):
            if rpc_calls is not None:
                rpc_calls.append((method, params))
            if rpc_error:
                raise rpc_error
            if method == 'eth_blockNumber':
                return '0xabc'
            if method == 'eth_getBalance':
                return native
            if method == 'eth_getTransactionCount':
                return nonce
            if (
                method == 'eth_call'
                and (params[0].get('to') or '').lower() == ('0x' + ('9' * 40))
            ):
                words = (vesting_allocated, vesting_claimed, 0, 0)
                return '0x' + ''.join(value.to_bytes(32, 'big').hex() for value in words)
            return '0x0'

        with patch('blockchain.models.SponsoredBatch.objects.filter', return_value=empty_query), \
             patch('conversion.models.Conversion.objects.filter', return_value=empty_query), \
             patch('send.models.SendTransaction.objects.filter', return_value=send_query), \
             patch('send.models.PhoneInvite.objects.filter', return_value=empty_query), \
             patch('payroll.models.PayrollItem.objects.filter', return_value=payroll_query), \
             patch('ramps.models.RampTransaction.objects.filter', return_value=ramp_query), \
             patch('presale.models.PresaleMigrationCredit.objects.filter', return_value=empty_query), \
             patch('cusd_plus.vault._rpc', side_effect=rpc), \
             patch('cusd_plus.vault.erc20_balance_raw', return_value=0), \
             patch('cusd_plus.gm_holdings.audit_registry', return_value={}):
            return _inspect_stale_bsc_reenrollment(account)

    def test_allows_only_zero_state_unused_bsc_anchor(self):
        result = self._inspect()
        self.assertTrue(result['eligible'])
        self.assertEqual(result['reason'], 'unused_bsc_anchor')

    def test_rejects_native_balance_or_transaction_history(self):
        self.assertEqual(self._inspect(native='0x1')['reason'], 'native_balance')
        self.assertEqual(self._inspect(nonce='0x1')['reason'], 'transaction_history')

    def test_rejects_prepared_inbound_value(self):
        self.assertEqual(
            self._inspect(pending_send=True)['reason'],
            'pending_inbound_send',
        )
        self.assertEqual(
            self._inspect(pending_payroll=True)['reason'],
            'pending_inbound_payroll',
        )

    def test_ambiguous_koywe_address_reservation_blocks_reenrollment(self):
        result = self._inspect(ramp_history=True)

        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'ramp_history')

    def test_rejects_contract_held_vesting_grant(self):
        calls = []
        result = self._inspect(
            vesting_allocated=100,
            vesting_claimed=40,
            rpc_calls=calls,
        )
        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'vesting_grant')
        vesting_calls = [
            params for method, params in calls
            if method == 'eth_call'
            and (params[0].get('to') or '').lower() == ('0x' + ('9' * 40))
        ]
        self.assertEqual(len(vesting_calls), 1)
        self.assertEqual(vesting_calls[0][1], '0xabc')

    def test_fully_claimed_vesting_grant_does_not_block(self):
        result = self._inspect(vesting_allocated=100, vesting_claimed=100)
        self.assertTrue(result['eligible'])

    def test_fails_closed_when_bsc_state_is_unavailable(self):
        result = self._inspect(rpc_error=TimeoutError('rpc unavailable'))
        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'], 'inspection_failed')


class WalletReenrollmentMutationTestCase(TestCase):
    OLD_ADDRESS = 'A' * 58

    class Info:
        class Context:
            def __init__(self, user):
                self.user = user

        def __init__(self, user):
            self.context = self.Context(user)

    def setUp(self):
        from users.models import Account
        from eth_account import Account as EvmAccount

        self.bsc_private_key = '0x' + ('11' * 32)
        self.NEW_BSC_ADDRESS = EvmAccount.from_key(self.bsc_private_key).address
        self.google_subject = 'google-subject-123'
        self.google_auth_time = int(time.time())
        self.user = User.objects.create_user(
            username='wallet-reenroll',
            email='wallet-reenroll@example.com',
            password='testpass123',
            firebase_uid='wallet-reenroll-firebase',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            algorand_address=self.OLD_ADDRESS,
            bsc_address=None,
            is_keyless_migrated=False,
        )

    def _reenrollment_proof(self):
        from eth_account import Account as EvmAccount
        from eth_account.messages import encode_defunct
        from users.web3auth_schema import _issue_wallet_reenrollment_grant

        challenge, grant = _issue_wallet_reenrollment_grant(
            self.user,
            self.account,
            self.google_subject,
            self.google_auth_time,
            {
                'eligible': True,
                'snapshot_round': 12345,
                'sponsor_funding': 500000,
            },
        )
        signature = EvmAccount.sign_message(
            encode_defunct(text=challenge),
            private_key=self.bsc_private_key,
        ).signature.hex()
        return grant, signature

    @patch('users.web3auth_schema._inspect_wallet_reenrollment')
    def test_preflight_runs_full_inspection_once_and_returns_snapshot_grant(
        self,
        inspect_mock,
    ):
        from users.web3auth_schema import (
            PrepareWalletReenrollmentMutation,
            _issue_wallet_reenrollment_preparation,
        )

        inspect_mock.return_value = {
            'eligible': True,
            'reason': 'sponsor_only_empty_wallet',
            'snapshot_round': 12345,
            'sponsor_funding': 500000,
        }
        preparation_token = _issue_wallet_reenrollment_preparation(
            self.user,
            self.account,
            self.google_subject,
            self.google_auth_time,
        )
        result = PrepareWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            preparation_token=preparation_token,
        )

        self.assertTrue(result.success)
        self.assertTrue(result.wallet_reenrollment_allowed)
        self.assertTrue(result.wallet_reenrollment_challenge)
        self.assertTrue(result.wallet_reenrollment_grant)
        inspect_mock.assert_called_once_with(self.account)

    @patch('users.web3auth_schema._inspect_wallet_reenrollment')
    def test_preflight_ineligible_wallet_falls_back_without_blocking_login(
        self,
        inspect_mock,
    ):
        from users.web3auth_schema import (
            PrepareWalletReenrollmentMutation,
            _issue_wallet_reenrollment_preparation,
        )

        inspect_mock.return_value = {'eligible': False, 'reason': 'asset_balance'}
        preparation_token = _issue_wallet_reenrollment_preparation(
            self.user,
            self.account,
            self.google_subject,
            self.google_auth_time,
        )
        result = PrepareWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            preparation_token=preparation_token,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.wallet_reenrollment_allowed)
        self.assertIsNone(result.wallet_reenrollment_grant)

    @patch('users.web3auth_schema._revalidate_wallet_reenrollment')
    def test_atomically_retires_old_address_and_registers_bsc(self, inspect_mock):
        from users.models import RetiredWalletAddress
        from users.web3auth_schema import CompleteWalletReenrollmentMutation

        inspect_mock.return_value = {'eligible': True, 'reason': 'sponsor_only_empty_wallet'}
        grant, signature = self._reenrollment_proof()
        result = CompleteWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            bsc_address=self.NEW_BSC_ADDRESS,
            reenrollment_grant=grant,
            bsc_signature=signature,
        )

        self.assertTrue(result.success)
        self.account.refresh_from_db()
        self.assertIsNone(self.account.algorand_address)
        self.assertEqual(self.account.bsc_address, self.NEW_BSC_ADDRESS)
        self.assertTrue(self.account.is_keyless_migrated)
        retired = RetiredWalletAddress.objects.get(
            chain=RetiredWalletAddress.CHAIN_ALGORAND,
            address=self.OLD_ADDRESS,
        )
        self.assertEqual(retired.account, self.account)
        self.assertEqual(retired.user, self.user)

    @patch('users.web3auth_schema._revalidate_wallet_reenrollment')
    def test_leaves_account_unchanged_when_chain_recheck_refuses(self, inspect_mock):
        from users.web3auth_schema import CompleteWalletReenrollmentMutation

        inspect_mock.return_value = {'eligible': False, 'reason': 'asset_balance'}
        grant, signature = self._reenrollment_proof()
        result = CompleteWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            bsc_address=self.NEW_BSC_ADDRESS,
            reenrollment_grant=grant,
            bsc_signature=signature,
        )

        self.assertFalse(result.success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.algorand_address, self.OLD_ADDRESS)
        self.assertIsNone(self.account.bsc_address)
        self.assertFalse(self.account.is_keyless_migrated)
        self.assertEqual(
            self.account.wallet_reenrollment_assessment.get('status'),
            'ineligible',
        )

    @patch('users.web3auth_schema._revalidate_wallet_reenrollment')
    def test_rejects_bsc_address_not_owned_by_challenge_signer(self, inspect_mock):
        from users.web3auth_schema import CompleteWalletReenrollmentMutation

        inspect_mock.return_value = {'eligible': True, 'reason': 'sponsor_only_empty_wallet'}
        grant, signature = self._reenrollment_proof()
        result = CompleteWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            bsc_address='0x' + ('2' * 40),
            reenrollment_grant=grant,
            bsc_signature=signature,
        )

        self.assertFalse(result.success)
        self.assertIn('proof', result.error.lower())
        self.account.refresh_from_db()
        self.assertEqual(self.account.algorand_address, self.OLD_ADDRESS)
        self.assertIsNone(self.account.bsc_address)

    @patch('users.web3auth_schema._revalidate_wallet_reenrollment')
    def test_successful_reenrollment_is_idempotent_after_lost_response(self, inspect_mock):
        from users.web3auth_schema import CompleteWalletReenrollmentMutation

        inspect_mock.return_value = {'eligible': True, 'reason': 'sponsor_only_empty_wallet'}
        grant, signature = self._reenrollment_proof()
        first = CompleteWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            bsc_address=self.NEW_BSC_ADDRESS,
            reenrollment_grant=grant,
            bsc_signature=signature,
        )
        second = CompleteWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            bsc_address=self.NEW_BSC_ADDRESS.lower(),
            reenrollment_grant='already-consumed',
            bsc_signature='already-consumed',
        )

        self.assertTrue(first.success)
        self.assertTrue(second.success)

    @patch('users.web3auth_schema._inspect_stale_bsc_reenrollment')
    @patch('users.web3auth_schema._revalidate_wallet_reenrollment')
    def test_atomically_replaces_proven_unused_stale_bsc(
        self,
        inspect_algo_mock,
        inspect_bsc_mock,
    ):
        from users.models import RetiredWalletAddress
        from users.web3auth_schema import CompleteWalletReenrollmentMutation

        self.account.bsc_address = '0x' + ('3' * 40)
        self.account.save(update_fields=['bsc_address'])
        inspect_algo_mock.return_value = {'eligible': True, 'reason': 'sponsor_only_empty_wallet'}
        inspect_bsc_mock.return_value = {'eligible': True, 'reason': 'unused_bsc_anchor'}
        grant, signature = self._reenrollment_proof()
        result = CompleteWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            bsc_address=self.NEW_BSC_ADDRESS,
            reenrollment_grant=grant,
            bsc_signature=signature,
        )

        self.assertTrue(result.success)
        self.account.refresh_from_db()
        self.assertIsNone(self.account.algorand_address)
        self.assertEqual(self.account.bsc_address, self.NEW_BSC_ADDRESS)
        self.assertTrue(self.account.is_keyless_migrated)
        self.assertSetEqual(
            set(RetiredWalletAddress.objects.filter(account=self.account).values_list(
                'chain', 'address'
            )),
            {
                (RetiredWalletAddress.CHAIN_ALGORAND, self.OLD_ADDRESS),
                (RetiredWalletAddress.CHAIN_BSC, old_bsc.lower()),
            },
        )

    @patch('users.web3auth_schema._inspect_stale_bsc_reenrollment')
    @patch('users.web3auth_schema._revalidate_wallet_reenrollment')
    def test_keeps_stale_bsc_when_it_has_supported_value_or_history(
        self,
        inspect_algo_mock,
        inspect_bsc_mock,
    ):
        from users.web3auth_schema import CompleteWalletReenrollmentMutation

        old_bsc = '0x' + ('3' * 40)
        self.account.bsc_address = old_bsc
        self.account.save(update_fields=['bsc_address'])
        inspect_algo_mock.return_value = {'eligible': True, 'reason': 'sponsor_only_empty_wallet'}
        inspect_bsc_mock.return_value = {'eligible': False, 'reason': 'token_balance'}
        grant, signature = self._reenrollment_proof()
        result = CompleteWalletReenrollmentMutation.mutate(
            None,
            self.Info(self.user),
            bsc_address=self.NEW_BSC_ADDRESS,
            reenrollment_grant=grant,
            bsc_signature=signature,
        )

        self.assertFalse(result.success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.algorand_address, self.OLD_ADDRESS)
        self.assertEqual(self.account.bsc_address, old_bsc)
        self.assertFalse(self.account.is_keyless_migrated)
        self.assertEqual(
            self.account.wallet_reenrollment_assessment.get('status'),
            'ineligible',
        )


class _FakeAlgodHTTPError(Exception):
    """Quacks exactly like AlgodHTTPError — same attributes, same message —
    without being one. Exists so a test can prove the predicate checks the
    TYPE, not just the fields."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class MigrationSafetyInspectionFailureTestCase(TestCase):
    """An address algod cannot be read is UNKNOWN, not empty. Reporting the two
    as the same thing let a node blip authorize moving the account pointer away
    from a wallet that may still hold funds.

    These use the SDK's REAL exception type. A hand-written stand-in passes
    whatever the code under test happens to check, which is how the first
    version of this suite stayed green while the predicate silently dropped its
    status check."""

    ADDRESS = 'A2GJGRKRABIUOCGXQKKR4YBTWUQPATJKNSH2CAUL2GG2U4MRLFSXUPT744'

    class RaisingAlgodClient:
        def __init__(self, exc):
            self.exc = exc

        def account_info(self, address):
            raise self.exc

    def test_algod_404_is_a_confirmed_empty_answer(self):
        from algosdk.error import AlgodHTTPError

        algod = self.RaisingAlgodClient(
            AlgodHTTPError(f'no accounts found for address {self.ADDRESS}', 404)
        )

        risk = inspect_address_migration_risk(algod, self.ADDRESS)
        self.assertFalse(risk['inspection_failed'])
        self.assertFalse(risk['has_material_risk'])
        self.assertIsNone(get_address_reassignment_blocker(algod, self.ADDRESS, 'new'))

    def test_confirmed_empty_requires_type_and_status_and_body(self):
        """Each condition alone admits a different false positive: a wrapper
        exception carrying algod's wording, a 500 whose body happens to match,
        or a proxy 404 that says nothing about the balance. Dropping any one of
        the three restores a fail-open."""
        from algosdk.error import AlgodHTTPError

        cases = {
            'right body, wrong status': AlgodHTTPError('no accounts found for address', 500),
            'right status, wrong body': AlgodHTTPError('404 page not found', 404),
            'right status, empty body': AlgodHTTPError('', 404),
            # Carries BOTH the status and the body, and still must not pass:
            # this is the only case that isolates the type condition. Without
            # it, deleting the isinstance check regresses silently, because
            # every other wrong-type case also lacks `.code`.
            'right body and status, wrong type': _FakeAlgodHTTPError(
                'no accounts found for address', 404
            ),
            'right body, wrong type, no status': Exception('no accounts found for address'),
            'transport error': Exception('HTTPSConnectionPool: Read timed out'),
            'dns failure': Exception('gaierror: host not found'),
        }
        for label, exc in cases.items():
            with self.subTest(case=label):
                algod = self.RaisingAlgodClient(exc)

                self.assertTrue(inspect_address_migration_risk(algod, self.ADDRESS)['inspection_failed'])
                self.assertIsNotNone(get_address_reassignment_blocker(algod, self.ADDRESS, 'new'))

    def test_same_address_noop_survives_an_outage(self):
        algod = self.RaisingAlgodClient(Exception('Read timed out'))

        self.assertIsNone(get_address_reassignment_blocker(algod, self.ADDRESS, self.ADDRESS))

    def test_inspection_failure_does_not_flip_has_material_risk(self):
        """MarkWalletMigrated reads has_material_risk only. Keeping it False on
        an unreadable address leaves those callers on their existing behavior;
        opting them into fail-closed is a separate, deliberate change."""
        algod = self.RaisingAlgodClient(Exception('Read timed out'))

        self.assertFalse(inspect_address_migration_risk(algod, self.ADDRESS)['has_material_risk'])

    def test_emitted_logs_never_contain_a_full_address(self):
        """Captures the real log records rather than testing the helper in
        isolation. algod embeds the queried address in its own error bodies, so
        redacting the address argument while logging the exception text beside
        it leaked the address anyway — a helper-only test passed throughout."""
        from algosdk.error import AlgodHTTPError

        cases = (
            AlgodHTTPError(f'no accounts found for address {self.ADDRESS}', 404),
            AlgodHTTPError(f'failed to read {self.ADDRESS} from ledger', 500),
        )
        for exc in cases:
            with self.subTest(code=exc.code):
                algod = self.RaisingAlgodClient(exc)

                with self.assertLogs('users.migration_safety', level='INFO') as captured:
                    inspect_address_migration_risk(algod, self.ADDRESS)
                self.assertNotIn(self.ADDRESS, '\n'.join(captured.output))

        # The blocker's own log lines carry both addresses.
        algod = self.RaisingAlgodClient(Exception('Read timed out'))
        with self.assertLogs('users.migration_safety', level='WARNING') as captured:
            get_address_reassignment_blocker(algod, self.ADDRESS, 'B' * 58)
        joined = '\n'.join(captured.output)
        self.assertNotIn(self.ADDRESS, joined)
        self.assertNotIn('B' * 58, joined)

    def test_redact_address_shape(self):
        from users.migration_safety import redact_address

        redacted = redact_address(self.ADDRESS)
        self.assertNotEqual(redacted, self.ADDRESS)
        self.assertTrue(self.ADDRESS.startswith(redacted.split('…')[0]))
        self.assertTrue(self.ADDRESS.endswith(redacted.split('…')[1]))
        self.assertEqual(redact_address(None), '(none)')
        self.assertEqual(redact_address(''), '(none)')

    def test_retry_message_is_not_a_funds_message(self):
        """An unreadable address must not tell the user they hold funds they
        may not have; it must tell them to try again."""
        algod = self.RaisingAlgodClient(Exception('HTTPSConnectionPool: Read timed out'))

        blocker = get_address_reassignment_blocker(algod, self.ADDRESS, 'new')
        self.assertIn('verificar', blocker)
        self.assertNotIn('activos pendientes', blocker)


class PhoneLookupTestCase(TestCase):
    """A send identifies its recipient by the FULL number — calling code plus
    subscriber digits. Every spelling of a full number lands on the same user;
    anything less than a full number lands on nobody."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='phoneuser',
            email='phone@example.com',
            password='testpass123',
            firebase_uid='phone-firebase-uid',
            phone_country='CO',
            phone_number='3132587634',
        )

    def test_canonical_key_resolves(self):
        # What `phoneKey` hands the app, and what the transaction list passes
        # through as fromPhone/toPhone.
        self.assertEqual(find_user_by_phone('57:3132587634'), self.user)

    def test_e164_resolves(self):
        self.assertEqual(find_user_by_phone('+573132587634'), self.user)

    def test_formatted_e164_resolves(self):
        self.assertEqual(find_user_by_phone('+57 313 258 7634'), self.user)

    def test_bare_local_digits_never_resolve(self):
        # A local number names no country. "3132587634" is dialable in
        # Colombia and elsewhere, so matching it would pick a country at
        # random. Refusing is correct even though this user's local digits
        # are exactly that.
        self.assertEqual(phone_lookup_key('3132587634'), '')
        self.assertIsNone(find_user_by_phone('3132587634'))

    def test_unknown_number_returns_none(self):
        self.assertIsNone(find_user_by_phone('57:3009998877'))

    def test_blank_input_returns_none(self):
        self.assertIsNone(find_user_by_phone(''))
        self.assertIsNone(find_user_by_phone(None))

    def test_bare_digits_never_guess_a_calling_code(self):
        # "3132587634" also reads as +31 (Netherlands) 32587634. Guessing a
        # split on an unprefixed number could pay the wrong person.
        self.assertEqual(phone_lookup_key('3132587634'), '')

    def test_partial_number_never_matches_a_full_one(self):
        # The wrong-payment path: +57 3009998877 has no Colombian user, but a
        # US user's LOCAL number is 3009998877. Matching on anything less than
        # the full number would pay them.
        us_user = User.objects.create_user(
            username='ususer',
            email='us@example.com',
            password='testpass123',
            firebase_uid='us-firebase-uid',
            phone_country='US',
            phone_number='3009998877',
        )
        self.assertEqual(phone_lookup_key('+573009998877'), '57:3009998877')
        self.assertIsNone(find_user_by_phone('+573009998877'))
        # ...and the bare local digits don't reach the US user either.
        self.assertIsNone(find_user_by_phone('3009998877'))
        # Only the full US number does.
        self.assertEqual(find_user_by_phone('+13009998877'), us_user)

    def test_argentina_mobile_nine_collapses_to_stored_key(self):
        # canonicalize_phone_digits drops the optional mobile 9, so every
        # spelling of the same AR number must reach the one stored key.
        ar_user = User.objects.create_user(
            username='aruser',
            email='ar@example.com',
            password='testpass123',
            firebase_uid='ar-firebase-uid',
            phone_country='AR',
            phone_number='2231234567',
        )
        self.assertEqual(ar_user.phone_key, '54:2231234567')
        for shape in ('+54 9 223 1234567', '+542231234567', '54:92231234567', '54:2231234567'):
            self.assertEqual(find_user_by_phone(shape), ar_user, shape)

    def test_ambiguous_number_is_refused_not_guessed(self):
        # phone_key has no unique constraint in any migration, and production
        # has none either — as of 2026-08-01 it holds 10 active accounts on
        # 1:2025550123. Paying an arbitrary one of several matching users is
        # worse than refusing. (The local dev DB happens to have an
        # out-of-band index, hence the skip below.)
        from django.db import IntegrityError, transaction
        try:
            with transaction.atomic():
                User.objects.create_user(
                    username='dupe',
                    email='dupe@example.com',
                    password='testpass123',
                    firebase_uid='dupe-firebase-uid',
                    phone_country='CO',
                    phone_number='3132587634',
                )
        except IntegrityError:
            self.skipTest('this database enforces phone_key uniqueness; nothing to refuse')
        self.assertIsNone(find_user_by_phone('57:3132587634'))

    def test_reviewer_numbers_resolve_despite_sharing(self):
        # The app-store reviewer number is shared BY DESIGN — the duplicate
        # check at phone verification is waived for it (sms_verification/
        # schema.py), so every reviewer signup adds a row on the same key.
        # Prod holds 6 on 54:2025550123 and 10 on the legacy default
        # 1:2025550123. Refusing them would break the reviewer's send, and
        # they are 555-01XX reserved-for-fiction numbers holding no real
        # money, so they resolve to the lowest id — deterministic, not random.
        from django.db import IntegrityError
        from django.test import override_settings
        from users.review_numbers import _review_phone_keys, _shared_reviewer_phone_keys

        for country, local, dial in (('AR', '2025550123', '+54'), ('US', '2025550123', '+1')):
            with self.subTest(country=country), override_settings(
                REVIEW_TEST_ENABLED=True,
                REVIEW_TEST_PHONE_E164='+542025550123',
                REVIEW_TEST_CODE='000000',
            ):
                _review_phone_keys.cache_clear()
                _shared_reviewer_phone_keys.cache_clear()
                first = User.objects.create_user(
                    username=f'rv1{country}', email=f'rv1{country}@example.com',
                    password='testpass123', firebase_uid=f'rv1-{country}',
                    phone_country=country, phone_number=local,
                )
                try:
                    User.objects.create_user(
                        username=f'rv2{country}', email=f'rv2{country}@example.com',
                        password='testpass123', firebase_uid=f'rv2-{country}',
                        phone_country=country, phone_number=local,
                    )
                except IntegrityError:
                    self.skipTest('this database enforces phone_key uniqueness')
                self.assertEqual(find_user_by_phone(f'{dial}{local}'), first)
        _review_phone_keys.cache_clear()
        _shared_reviewer_phone_keys.cache_clear()

    def test_legacy_reviewer_number_still_cannot_bypass_verification(self):
        # Widening the DUPLICATE tolerance to the legacy number must not
        # widen the SMS-code bypass — that is what would grant a way in.
        from users.review_numbers import (
            get_review_test_code_for_phone, is_shared_reviewer_phone_key)
        self.assertTrue(is_shared_reviewer_phone_key('1:2025550123'))
        self.assertIsNone(get_review_test_code_for_phone('+12025550123'))

    def test_deactivated_user_does_not_receive(self):
        self.user.is_active = False
        self.user.save()
        self.assertIsNone(find_user_by_phone('57:3132587634'))

    def test_full_digits_of_one_number_are_not_another_users_local_number(self):
        # A US user whose stored local digits spell out the Colombian user's
        # full international number must not be reachable as that number.
        collider = User.objects.create_user(
            username='collider',
            email='collider@example.com',
            password='testpass123',
            firebase_uid='collider-firebase-uid',
            phone_country='US',
            phone_number='573132587634',
        )
        self.assertEqual(collider.phone_number, '573132587634')
        self.assertEqual(find_user_by_phone('57:3132587634'), self.user)
        self.assertEqual(find_user_by_phone('+573132587634'), self.user)
