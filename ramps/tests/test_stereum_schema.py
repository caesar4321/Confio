from types import SimpleNamespace
from unittest.mock import patch
import graphene
from django.test import SimpleTestCase, override_settings

from ramps.stereum_schema import Query, Mutation


@override_settings(STEREUM_TEST_ENABLED=True, STEREUM_CUSTOMER_TEST_ENABLED=True)
class StereumSchemaTests(SimpleTestCase):
    def setUp(self):
        self.schema = graphene.Schema(query=Query, mutation=Mutation)
        self.user = SimpleNamespace(pk=1, is_authenticated=True, is_active=True)
        self.context = SimpleNamespace(user=self.user)

    @patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={'account_type': 'personal'})
    @patch('ramps.stereum_schema.onboarding_status')
    def test_status_uses_authenticated_user(self, status, context):
        status.return_value = SimpleNamespace(status='registered', error='')
        result = self.schema.execute('{ stereumCustomerStatus { status error } }', context_value=self.context)
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['stereumCustomerStatus']['status'], 'registered')
        status.assert_called_once_with(self.user)

    @patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={'account_type': 'business'})
    @patch('ramps.stereum_schema.onboarding_status')
    def test_business_context_cannot_use_personal_customer(self, status, context):
        result = self.schema.execute('{ stereumCustomerStatus { status } }', context_value=self.context)
        self.assertTrue(result.errors)
        status.assert_not_called()

    @patch('ramps.stereum_schema.onboarding_status')
    def test_anonymous_user_is_denied(self, status):
        self.user.is_authenticated = False
        result = self.schema.execute('{ stereumCustomerStatus { status } }', context_value=self.context)
        self.assertTrue(result.errors)
        status.assert_not_called()

    @patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={'account_type': 'personal'})
    @patch('ramps.stereum_schema.onboard')
    def test_onboarding_binds_to_authenticated_user_without_identity_overrides(self, onboard, context):
        onboard.return_value = SimpleNamespace(status='registered', error='')
        query = '''mutation($details: StereumCustomerInput!) {
          onboardStereumCustomer(details: $details, consent: true) { status }
        }'''
        details = {'stateOfResidence':'BO_L', 'economicActivity':'Software', 'sourceOfFunds':'Trabajo',
                   'destinationOfFunds':'Servicios', 'incomeLevel':'500 - 1000', 'surname1':'PEREZ'}
        result = self.schema.execute(query, variable_values={'details': details}, context_value=self.context)
        self.assertIsNone(result.errors)
        self.assertIs(onboard.call_args.args[0], self.user)
        self.assertEqual(onboard.call_args.args[1]['source_of_funds'], 'Trabajo')
        self.assertTrue(onboard.call_args.kwargs['consent'])
        result = self.schema.execute(query, variable_values={'details': {**details, 'userId':'another-user'}}, context_value=self.context)
        self.assertTrue(result.errors)
        self.assertEqual(onboard.call_count, 1)
