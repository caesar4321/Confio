from django.test import TestCase
from django.contrib.auth import get_user_model
from graphene_django.utils.testing import GraphQLTestCase
from graphql_jwt.testcases import JSONWebTokenTestCase
import json

User = get_user_model()

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
