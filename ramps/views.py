import json
import logging

from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ramps.koywe_client import KoyweClient, KoyweError
from ramps.koywe_sync import (
    extract_koywe_event_id,
    extract_koywe_event_type,
    extract_koywe_order_id,
    sync_koywe_ramp_transaction_from_order,
    verify_koywe_webhook_signature,
)
from ramps.models import RampTransaction, RampWebhookEvent

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def koywe_webhook(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        logger.warning('Koywe webhook rejected due to invalid JSON')
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    logger.info(
        'Koywe webhook received: payload_signature_present=%s content_length=%s',
        bool(payload.get('signature')),
        request.META.get('CONTENT_LENGTH'),
    )

    if not verify_koywe_webhook_signature(payload):
        logger.warning('Koywe webhook rejected due to invalid payload signature')
        return JsonResponse({'ok': False, 'error': 'Invalid signature'}, status=403)

    event_type = extract_koywe_event_type(payload)
    event_id = extract_koywe_event_id(payload)
    if not event_id:
        logger.warning('Koywe webhook rejected due to missing event id: type=%s', event_type)
        return JsonResponse({'ok': False, 'error': 'Missing event id'}, status=400)

    event, created = RampWebhookEvent.objects.get_or_create(
        event_id=event_id,
        defaults={
            'provider': 'koywe',
            'event_type': event_type,
            'payload': payload,
        },
    )
    if not created:
        return JsonResponse({'ok': True, 'duplicate': True})

    order_id = extract_koywe_order_id(payload)
    if not order_id:
        logger.info('Koywe webhook stored without order id: event_id=%s type=%s', event_id, event_type)
        return JsonResponse({'ok': True, 'stored': True})

    ramp_tx = RampTransaction.objects.filter(
        provider='koywe',
        provider_order_id=order_id,
    ).first()

    # The create-order POST can succeed at Koywe after Confío times out waiting
    # for its response. In that case the pre-created reservation has no
    # provider_order_id, but Koywe echoes our externalId in every webhook. Join
    # on that key only for blank-ID reservations, then persist the provider ID
    # before making another network request so pollers and later webhooks can
    # finish reconciliation even if the status lookup below fails.
    external_id = str(payload.get('externalId') or '').strip()
    if not ramp_tx and external_id:
        reservation = (
            RampTransaction.objects.filter(
                provider='koywe',
                provider_order_id='',
                external_id=external_id,
                status='PENDING',
                metadata__wallet_address_reservation_state__in=(
                    'creating_order',
                    'ambiguous_order_creation',
                ),
            )
            .order_by('created_at')
            .first()
        )
        if reservation:
            recovered_at = timezone.now()
            metadata = dict(reservation.metadata or {})
            metadata.update({
                'wallet_address_reservation_state': 'provider_order_recorded',
                'provider_order_recovery': {
                    'source': 'koywe_webhook',
                    'event_id': event_id,
                    'recovered_at': recovered_at.isoformat(),
                },
            })
            updated = RampTransaction.objects.filter(
                pk=reservation.pk,
                provider_order_id='',
                status='PENDING',
                metadata__wallet_address_reservation_state__in=(
                    'creating_order',
                    'ambiguous_order_creation',
                ),
            ).update(
                provider_order_id=order_id,
                metadata=metadata,
                updated_at=recovered_at,
            )
            if updated:
                reservation.provider_order_id = order_id
                reservation.metadata = metadata
                reservation.updated_at = recovered_at
                ramp_tx = reservation
                logger.info(
                    'Koywe webhook recovered ambiguous order: '
                    'ramp_id=%s order_id=%s external_id=%s',
                    reservation.pk,
                    order_id,
                    external_id,
                )
            else:
                # A concurrent webhook may have recorded the same order first.
                ramp_tx = RampTransaction.objects.filter(
                    pk=reservation.pk,
                    provider_order_id=order_id,
                ).first()

    if not ramp_tx:
        logger.info('Koywe webhook stored for unknown order: event_id=%s order_id=%s', event_id, order_id)
        return JsonResponse({'ok': True, 'stored': True, 'order_id': order_id})

    client = KoyweClient()
    if not client.is_configured:
        logger.warning('Koywe webhook could not reconcile order %s: client not configured', order_id)
        return JsonResponse({'ok': True, 'stored': True, 'order_id': order_id})

    try:
        auth_email = str((ramp_tx.metadata or {}).get('auth_email') or '').strip() or None
        if not auth_email and ramp_tx.actor_user_id:
            try:
                auth_email = str(
                    getattr(ramp_tx.actor_user.ramp_user_address, 'auth_email', '') or ''
                ).strip() or None
            except ObjectDoesNotExist:
                auth_email = None
        result = client.get_ramp_order_status(order_id=order_id, email=auth_email)
        sync_koywe_ramp_transaction_from_order(
            ramp_tx=ramp_tx,
            order_payload=result.raw_response,
            next_action_url=result.next_action_url,
        )
    except KoyweError as exc:
        logger.warning('Koywe webhook reconcile failed for %s: %s', order_id, exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Unexpected Koywe webhook failure for %s', order_id)
        return JsonResponse({'ok': False, 'error': 'Unexpected error'}, status=500)

    return JsonResponse({'ok': True, 'order_id': order_id, 'status': ramp_tx.status})


@csrf_exempt
@require_POST
def vexpay_webhook(request):
    """Signed VEXPay event → re-read the payment at VEXPay asynchronously.

    The body is only a hint: the poller and this re-read use the API as the
    source of truth. Deliveries are single-attempt with a 10 s budget, so
    answer 2xx once the event is stored, even if enqueueing fails.
    """
    from django.conf import settings

    from ramps.vexpay_client import verify_webhook_signature

    raw = request.body
    if not verify_webhook_signature(
        raw, request.headers.get('VexPay-Signature', ''),
        getattr(settings, 'VEXPAY_WEBHOOK_SECRET', ''),
    ):
        logger.warning('VEXPay webhook rejected: invalid signature')
        return JsonResponse({'ok': False, 'error': 'Invalid signature'}, status=403)
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    event_id = str(request.headers.get('VexPay-Event-Id') or '').strip()
    if not event_id or not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'Missing event id'}, status=400)
    event_type = str(payload.get('event') or '')[:120]
    _, created = RampWebhookEvent.objects.get_or_create(
        event_id=f'vexpay:{event_id}'[:120],
        defaults={'provider': 'vexpay', 'event_type': event_type, 'payload': payload},
    )
    if not created:
        return JsonResponse({'ok': True, 'duplicate': True})

    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    payment_id = str(data.get('paymentId') or '').strip()
    external_ref = str(data.get('externalRef') or '').strip()
    ramp_tx = None
    if payment_id:
        ramp_tx = RampTransaction.objects.filter(provider='vexpay', provider_order_id=payment_id).first()
    if ramp_tx is None and external_ref:
        ramp_tx = RampTransaction.objects.filter(provider='vexpay', external_id=external_ref).first()
    if ramp_tx is None:
        return JsonResponse({'ok': True, 'stored': True})
    _enqueue_ve_sync(ramp_tx.pk)
    return JsonResponse({'ok': True})


def _enqueue_ve_sync(ramp_pk: int) -> None:
    try:
        from ramps.tasks import sync_ve_pagomovil_order
        sync_ve_pagomovil_order.delay(ramp_pk)
    except Exception:  # noqa: BLE001 — the poller reconciles within a minute
        logger.exception('VE Pago Móvil webhook enqueue failed for ramp %s', ramp_pk)


@csrf_exempt
@require_POST
def pagoasap_webhook(request):
    """Signed Pago ASAP event (payment intent or blockchain deposit) → re-check.

    `X-Webhook-Signature` is base64 Ed25519 over the exact raw body. The body
    is only a hint: payouts are re-read from the API and funding is proven on
    chain. Store, enqueue, answer 2xx.
    """
    import hashlib

    from django.conf import settings

    from ramps.pagoasap_client import verify_webhook_signature

    raw = request.body
    signature = request.headers.get('X-Webhook-Signature', '')
    keys = (getattr(settings, 'PAGOASAP_PAYMENT_WEBHOOK_PUBLIC_KEY', ''),
            getattr(settings, 'PAGOASAP_DEPOSIT_WEBHOOK_PUBLIC_KEY', ''))
    if not any(verify_webhook_signature(raw, signature, key) for key in keys if key):
        logger.warning('Pago ASAP webhook rejected: invalid signature')
        return JsonResponse({'ok': False, 'error': 'Invalid signature'}, status=403)
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    event_type = str(payload.get('event') or '')[:120]
    _, created = RampWebhookEvent.objects.get_or_create(
        event_id=f'pagoasap:{hashlib.sha256(raw).hexdigest()}'[:120],
        defaults={'provider': 'pagoasap', 'event_type': event_type, 'payload': payload},
    )
    if not created:
        return JsonResponse({'ok': True, 'duplicate': True})
    body = payload.get('payload') if isinstance(payload.get('payload'), dict) else {}
    targets = []
    intent = body.get('intent') if isinstance(body.get('intent'), dict) else {}
    if event_type == 'payment_intent_state_termination' and intent.get('id'):
        targets = list(RampTransaction.objects.filter(
            provider='pagoasap', direction='off_ramp',
            metadata__ve_send__operation_id=str(intent['id'])).values_list('pk', flat=True)[:1])
    movement = body.get('movement') if isinstance(body.get('movement'), dict) else {}
    sender = str(movement.get('counterpartyAddress') or '').strip().lower()
    if event_type == 'blockchain_deposit_state_termination' and sender:
        targets = list(RampTransaction.objects.filter(
            provider='pagoasap', direction='off_ramp', actor_address__iexact=sender,
            status__in=('PENDING', 'PROCESSING')).values_list('pk', flat=True)[:5])
    for pk in targets:
        _enqueue_ve_sync(pk)
    return JsonResponse({'ok': True})
