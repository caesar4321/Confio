"""Rollout compatibility only. Client headers never prove a face check passed.

FACE_STEP_UP_ENABLED forces legacy clients to update. Supported clients always
enforce Face, even during the store rollout. Recovery/read/support routes
are deliberately not included in the transaction gate.
"""
import logging
import re

from .face_step_up import _setting, step_up_enabled

logger = logging.getLogger(__name__)

UPDATE_CODE = 'APP_UPDATE_REQUIRED'
UPDATE_MESSAGE = 'Actualiza Confío desde App Store o Google Play para continuar. La nueva versión incluye la verificación Confío Face.'

# Schema field names, NOT client-controlled operation names or aliases.
TRANSACTION_FIELDS = frozenset('''
prepareBscSend submitBscSend prepareBscInvite submitBscInvite
prepareBscInvoicePayment submitBscInvoicePayment payInvoice
createRampOrder createMockRampOrder sponsorBscBatch submitBscTransaction
createPaymentPayout createPaymentTransfer preparePaymentBridge submitPaymentBridge
createInfiniaJourney createCobreJourney
algorandSponsoredSend submitSponsoredGroup createSponsoredPayment submitSponsoredPayment
prepareInviteForPhone submitInviteForPhone buildBurnAndSend
buildGuardarianOfframpTransactions submitAutoSwapTransactions
createUsdcWithdrawal
preparePayrollItemPayout submitPayrollItemPayout
preparePayrollVaultFunding submitPayrollVaultFunding
prepareBscPayrollPayout submitBscPayrollPayout
prepareBscPresalePurchase submitBscPresalePurchase purchasePresaleTokens
startFaceCheck completeFaceCheck
'''.split())


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', value):
        return None
    return tuple(int(part) for part in value.split('.'))


def supports_face(headers):
    headers = {str(k).lower(): str(v) for k, v in headers.items()}
    platform = headers.get('x-confio-platform', '').lower()
    if platform not in ('ios', 'android'):
        return False
    floor = _version(str(_setting('FACE_MIN_APP_VERSION', '5.1.5')))
    version = _version(headers.get('x-confio-version', ''))
    build = headers.get('x-confio-build', '')
    minimum_build = int(_setting('FACE_MIN_' + platform.upper() + '_BUILD', 1 if platform == 'ios' else 157, int))
    return not (floor is None or version is None or version < floor
            or not re.fullmatch(r'[0-9]{1,12}', build)
            or int(build) < 1
            or (version == floor and int(build) < minimum_build)
            or headers.get('x-confio-face-capable') != '1')


def update_required(headers):
    return step_up_enabled() and not supports_face(headers)


def log_update_refusal(headers, user, where: str) -> None:
    """What the client reported when it was told to update: no other trace
    exists of why a client failed supports_face."""
    headers = {str(k).lower(): str(v) for k, v in headers.items()}
    logger.warning(
        'App update required: where=%s user=%s platform=%r version=%r build=%r face_capable=%r ua=%r',
        where, getattr(user, 'id', None), headers.get('x-confio-platform', ''),
        headers.get('x-confio-version', ''), headers.get('x-confio-build', ''),
        headers.get('x-confio-face-capable', ''), headers.get('user-agent', '')[:80])


def request_headers(request):
    headers = getattr(request, 'headers', None)
    if headers is None:
        headers = {key[5:].replace('_', '-'): value
                   for key, value in getattr(request, 'META', {}).items() if key.startswith('HTTP_')}
    return headers


class FaceClientRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .face_context import face_client_supported
        token = face_client_supported.set(supports_face(request_headers(request)))
        try:
            return self.get_response(request)
        finally:
            face_client_supported.reset(token)


def request_update_required(request):
    headers = getattr(request, 'headers', None)
    if headers is None:
        headers = {key[5:].replace('_', '-'): value
                   for key, value in getattr(request, 'META', {}).items() if key.startswith('HTTP_')}
    return update_required(headers)


class FaceClientCompatibilityMiddleware:
    def resolve(self, next, root, info, **args):
        user = getattr(info.context, 'user', None)
        is_funding = (info.field_name in ('prepareBscPayrollAdmin', 'submitBscPayrollAdmin')
                      and args.get('action') == 'fund')
        if (info.parent_type == info.schema.mutation_type
                and (info.field_name in TRANSACTION_FIELDS or is_funding)
                and getattr(user, 'is_authenticated', False)
                and request_update_required(info.context)):
            log_update_refusal(request_headers(info.context), user, info.field_name)
            from graphql import GraphQLError
            raise GraphQLError(UPDATE_MESSAGE, extensions={
                'code': UPDATE_CODE, 'nextStep': 'update_app',
                'minimumVersion': str(_setting('FACE_MIN_APP_VERSION', '5.1.5')),
            })
        return next(root, info, **args)


WS_TRANSACTION_MESSAGES = {
    '/ws/send_session': {'prepare_request', 'submit_request'},
    '/ws/pay_session': {'prepare_request', 'submit_request'},
    '/ws/withdraw_session': {'prepare', 'submit'},
    '/ws/p2p_session': {'prepare', 'submit'},
    '/ws/presale_session': {'prepare_request', 'submit_request'},
    '/ws/humanitarian_session': {'donation_prepare', 'donation_submit'},
}


class FaceClientWebSocketMiddleware:
    """Check each money-moving frame, including already-open connections.

    Chat, keepalives, status and claim/recovery messages still get through.
    A connection opened while ENABLE was off does not bypass a later flip.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        import json
        guarded = WS_TRANSACTION_MESSAGES.get(scope.get('path', '').rstrip('/'), set())
        headers = {k.decode('latin1'): v.decode('latin1') for k, v in scope.get('headers', [])}

        async def checked_receive():
            while True:
                message = await receive()
                if guarded and message.get('type') == 'websocket.receive':
                    try:
                        payload = json.loads(message.get('text') or message.get('bytes') or '{}')
                    except (ValueError, TypeError, UnicodeDecodeError):
                        payload = None
                    recovery = (isinstance(payload, dict)
                                and scope.get('path', '').rstrip('/') == '/ws/p2p_session'
                                and payload.get('action') in ('cancel', 'open_dispute'))
                    if (isinstance(payload, dict) and payload.get('type') in guarded and not recovery
                            and update_required(headers)):
                        log_update_refusal(headers, scope.get('user'), scope.get('path', ''))
                        await send({'type': 'websocket.send', 'text': json.dumps({
                            'type': 'error', 'code': UPDATE_CODE, 'message': UPDATE_MESSAGE,
                            'next_step': 'update_app',
                        })})
                        continue
                return message

        from .face_context import face_client_supported
        token = face_client_supported.set(supports_face(headers))
        try:
            return await self.app(scope, checked_receive, send)
        finally:
            face_client_supported.reset(token)
