import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import InstitutionConnection
from .sandbox_cip import (
    CipSandboxDisabled,
    apply_cip_sandbox_payload,
    authorize_sandbox_request,
    sandbox_connection,
    verify_member_and_issue_link,
)


def _token(request):
    value = request.headers.get('Authorization', '')
    return value[7:] if value.startswith('Bearer ') else ''


def _body(request):
    try:
        value = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _allowed(request):
    try:
        return authorize_sandbox_request(_token(request))
    except CipSandboxDisabled:
        return False


@csrf_exempt
@require_POST
def cip_sandbox_verify(request):
    if not _allowed(request):
        return JsonResponse({'error': 'not_found'}, status=404)
    payload = _body(request)
    member_number = payload.get('member_number') if payload else None
    if (not isinstance(member_number, str) or not member_number.strip()
            or len(member_number) > 80):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    try:
        return JsonResponse(verify_member_and_issue_link(
            member_number=member_number.strip(), connection=sandbox_connection(
                public_id=request.headers.get('X-CIP-Sandbox-Connection'))))
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@csrf_exempt
@require_POST
def cip_sandbox_apply(request):
    if not _allowed(request):
        return JsonResponse({'error': 'not_found'}, status=404)
    payload = _body(request)
    idempotency_key = request.headers.get('Idempotency-Key', '')
    if payload is None or not idempotency_key or len(idempotency_key) > 255:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    try:
        connection = sandbox_connection(
            public_id=request.headers.get('X-CIP-Sandbox-Connection'))
        outcome, response = apply_cip_sandbox_payload(
            connection=connection, payload=payload,
            idempotency_key=idempotency_key)
    except (InstitutionConnection.DoesNotExist,
            InstitutionConnection.MultipleObjectsReturned, ValueError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse(response, status=409 if outcome == 'mismatch' else 200)
