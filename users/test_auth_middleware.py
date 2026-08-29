import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from users.middleware import AuthTokenVersionMiddleware


class PublicAuthenticationMiddlewareTest(SimpleTestCase):
    def test_web3auth_login_discards_a_stale_confio_jwt(self):
        observed = {}

        def downstream(request):
            observed['authorization'] = request.headers.get('Authorization')
            observed['is_authenticated'] = request.user.is_authenticated
            return JsonResponse({'ok': True})

        request = RequestFactory().post(
            '/graphql/',
            data=json.dumps({
                'operationName': 'Web3AuthLogin',
                'query': 'mutation Web3AuthLogin { web3AuthLogin { success } }',
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION='JWT stale-deleted-user-token',
        )

        with patch('users.middleware.verify_auth_token_version') as verify:
            response = AuthTokenVersionMiddleware(downstream)(request)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(observed['authorization'])
        self.assertFalse(observed['is_authenticated'])
        verify.assert_not_called()

    def test_private_operation_keeps_normal_jwt_verification(self):
        request = RequestFactory().post(
            '/graphql/',
            data=json.dumps({
                'operationName': 'GetUserProfile',
                'query': 'query GetUserProfile { userProfile { id } }',
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION='JWT existing-user-token',
        )

        with patch(
            'users.middleware.verify_auth_token_version',
            side_effect=Exception('test verification stop'),
        ) as verify:
            response = AuthTokenVersionMiddleware(lambda _request: JsonResponse({'ok': True}))(request)

        self.assertEqual(response.status_code, 200)
        verify.assert_called_once_with('existing-user-token')
        self.assertEqual(request.headers.get('Authorization'), 'JWT existing-user-token')
        self.assertIsInstance(request.user, AnonymousUser)
