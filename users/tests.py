from django.test import TestCase
from django.contrib.auth import get_user_model
from graphene_django.utils.testing import GraphQLTestCase
from graphql_jwt.testcases import JSONWebTokenTestCase
from graphql_jwt.exceptions import PermissionDenied
from graphql_jwt.utils import jwt_encode
import json
from users.jwt import jwt_payload_handler, verify_auth_token_version
from users.migration_safety import (
    MATERIAL_SPENDABLE_ALGO_MICROS,
    get_address_reassignment_blocker,
    inspect_address_migration_risk,
)

User = get_user_model()


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
        """Test that account balance query returns correct values"""
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
        
        # Test cUSD balance
        result = query.resolve_account_balance(info, 'cUSD')
        self.assertEqual(result, '2850.35')
        
        # Test CONFIO balance
        result = query.resolve_account_balance(info, 'CONFIO')
        self.assertEqual(result, '234.18')
        
        # Test USDC balance
        result = query.resolve_account_balance(info, 'USDC')
        self.assertEqual(result, '458.22')
        
        # Test unknown token type
        result = query.resolve_account_balance(info, 'UNKNOWN')
        self.assertEqual(result, '0')

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


class MigrationSafetyTestCase(TestCase):
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
                    {'asset-id': 31566704, 'amount': 123456},
                ],
            }
        })

        risk = inspect_address_migration_risk(algod, 'legacy')
        self.assertTrue(risk['has_material_risk'])
        self.assertEqual(risk['relevant_assets'][31566704], 123456)

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
