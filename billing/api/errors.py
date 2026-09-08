import uuid
import logging

from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger(__name__)


class BillingApiError(APIException):
    status_code = 400
    default_code = 'invalid_request'

    def __init__(self, *, code, message, status_code=400, param=None,
                 retryable=False):
        self.status_code = status_code
        self.billing_code = code
        self.param = param
        self.retryable = retryable
        super().__init__(detail=message, code=code)


def request_id(request):
    current = getattr(request, 'billing_request_id', None)
    if current:
        return current
    current = 'req_' + uuid.uuid4().hex
    request.billing_request_id = current
    return current


def exception_handler(exc, context):
    request = context.get('request')
    rid = request_id(request) if request is not None else 'req_' + uuid.uuid4().hex
    if isinstance(exc, BillingApiError):
        response = Response({
            'error': {
                'type': 'invalid_request',
                'code': exc.billing_code,
                'message': str(exc.detail),
                'param': exc.param,
                'request_id': rid,
                'retryable': exc.retryable,
                'doc_url': f'https://docs.confio.lat/errors/{exc.billing_code}',
            },
        }, status=exc.status_code)
        if exc.billing_code == 'idempotency_in_progress':
            response['Retry-After'] = '2'
    else:
        response = drf_exception_handler(exc, context)
        if response is None:
            logger.error('Unhandled billing API error request_id=%s', rid, exc_info=exc)
            response = Response({'error': {
                'type': 'api_error', 'code': 'internal_error',
                'message': 'The request could not be completed. Retry with the same idempotency key.',
                'param': None, 'request_id': rid, 'retryable': True,
                'doc_url': 'https://docs.confio.lat/errors/internal_error',
            }}, status=500)
            response['Confio-Request-Id'] = rid
            return response
        code = {
            401: 'invalid_api_key',
            403: 'missing_scope',
            404: 'resource_not_found',
            405: 'method_not_allowed',
            415: 'unsupported_media_type',
            429: 'rate_limit_exceeded',
        }.get(response.status_code, 'request_failed')
        detail = response.data.get('detail', 'Request failed.') \
            if isinstance(response.data, dict) else 'Request failed.'
        response.data = {'error': {
            'type': 'invalid_request', 'code': code,
            'message': str(detail), 'param': None, 'request_id': rid,
            'retryable': False,
            'doc_url': f'https://docs.confio.lat/errors/{code}',
        }}
    response['Confio-Request-Id'] = rid
    return response
