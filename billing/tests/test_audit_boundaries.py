import json
import graphene
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings


class MembershipLogPrivacyTests(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_claim_token_never_enters_graphql_debug_logs(self):
        from config.urls import LoggingGraphQLView
        secret = 'private-one-use-membership-token'
        for query, variables in (
            ('mutation Claim($token:String!){claimInstitutionMembership(provider:"cip",token:$token){success}}',
             {'token': secret}),
            ('mutation{claimInstitutionMembership(provider:"cip",token:"' + secret + '"){success}}', {}),
        ):
            request = RequestFactory().post(
                '/graphql/', data=json.dumps({'query': query, 'variables': variables}),
                content_type='application/json')
            request.user = SimpleNamespace(is_authenticated=True)
            with patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=None), \
                    patch('graphene_django.views.GraphQLView.dispatch', return_value=HttpResponse('{}')), \
                    self.assertLogs('config.urls', level='INFO') as logs:
                LoggingGraphQLView(schema=graphene.Schema(), middleware=[]).dispatch(request)
            self.assertNotIn(secret, '\n'.join(logs.output))
            self.assertIn('[membership claim redacted]', '\n'.join(logs.output))


class PaymentSubmitAccountTests(SimpleTestCase):
    @override_settings(CUSD_PLUS_7702_ENABLED=True)
    def test_submit_rejects_signature_from_previous_active_account(self):
        from payments.schema import SubmitBscInvoicePayment
        payment = SimpleNamespace(payer_account=SimpleNamespace(
            account_type='business', account_index=0, business_id=20, deleted_at=None))
        info = SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(id=1, is_authenticated=True)))
        with patch('cusd_plus.schema._bsc_rate_limited', return_value=False), \
                patch('users.jwt_context.get_jwt_business_context_with_validation',
                      return_value={'account_type': 'business', 'business_id': 21, 'account_index': 0}), \
                patch('payments.schema.PaymentTransaction.objects.filter') as lookup, \
                patch('payments.bsc_flow.submit_bsc_payment') as submit:
            lookup.return_value.first.return_value = payment
            result = SubmitBscInvoicePayment.mutate.__wrapped__(
                None, info, 'payment', '1', '9999999999', 'signature')
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'permission_denied')
        submit.assert_not_called()
