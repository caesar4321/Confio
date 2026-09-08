import hashlib
import hmac
import ipaddress
import json
from json import dumps as json_dumps
import secrets
import socket
import time
from datetime import timedelta
from urllib.parse import urlparse

import requests
import urllib3
from django.db import transaction
from django.utils import timezone

from .models import BillingEvent, WebhookDelivery, WebhookEndpoint


class UnsafeWebhookUrl(ValueError):
    pass


def _delivery_addresses(url, *, resolver=socket.getaddrinfo):
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeWebhookUrl('invalid webhook URL') from exc
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeWebhookUrl('webhook URL must be HTTPS without credentials')
    if port not in (None, 443):
        raise UnsafeWebhookUrl('webhook URL must use port 443')
    try:
        addresses = {item[4][0] for item in resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    except (OSError, socket.gaierror) as exc:
        raise UnsafeWebhookUrl('webhook hostname could not be resolved') from exc
    if not addresses:
        raise UnsafeWebhookUrl('webhook hostname has no address')
    for address in addresses:
        ip = ipaddress.ip_address(address.split('%', 1)[0])
        if not ip.is_global:
            raise UnsafeWebhookUrl('webhook hostname resolves to a non-public address')
    return parsed, sorted(addresses)


def validate_delivery_url(url, *, resolver=socket.getaddrinfo):
    _delivery_addresses(url, resolver=resolver)
    return url


def public_https_post(url, *, data=None, json=None, headers=None, timeout=10,
                      allow_redirects=False):
    """Connect to the validated IP while verifying TLS against the original host.

    Using requests.post after a separate DNS check permits a second resolution
    to rebind to an internal address. This pool connects to the checked IP only.
    Environment proxy settings are intentionally not used.
    """
    parsed, addresses = _delivery_addresses(url)
    body = data
    request_headers = dict(headers or {})
    request_headers['Host'] = parsed.hostname
    if json is not None:
        body = json_dumps(json).encode('utf-8')
        request_headers['Content-Type'] = 'application/json'
    pool = urllib3.HTTPSConnectionPool(
        addresses[0], port=443, assert_hostname=parsed.hostname,
        server_hostname=parsed.hostname, cert_reqs='CERT_REQUIRED',
        ca_certs=requests.certs.where(), maxsize=1)
    try:
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        response = pool.request(
            'POST', path,
            body=body, headers=request_headers, timeout=timeout,
            redirect=False, retries=False, preload_content=False)
        try:
            content = response.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise requests.RequestException('response exceeds size limit')
            result = requests.Response()
            result.status_code = response.status
            result._content = content
            result.headers.update(response.headers)
            return result
        finally:
            response.close()
    except urllib3.exceptions.HTTPError as exc:
        raise requests.RequestException('HTTPS delivery failed') from exc
    finally:
        pool.close()


def event_body(event):
    body = dict(event.payload)
    body.update({
        'id': event.public_id,
        'api_version': event.api_version,
        'created_at': event.created_at.isoformat(),
    })
    return body


def enqueue_event_deliveries(event):
    endpoints = WebhookEndpoint.objects.filter(
        business_id=event.business_id, mode=event.mode, status='active')
    created = []
    for endpoint in endpoints:
        if endpoint.event_types and event.event_type not in endpoint.event_types:
            continue
        delivery, was_created = WebhookDelivery.objects.get_or_create(
            event=event, endpoint=endpoint, replay_number=0,
            defaults={
                'endpoint_url': endpoint.url,
                'signing_secret': endpoint.secret,
                'event_body': event_body(event),
                'available_at': timezone.now(),
            })
        if was_created:
            created.append(delivery)
    return created


@transaction.atomic
def create_replay(delivery):
    # Serialize numbering on a stable parent, including simultaneous replays.
    endpoint = WebhookEndpoint.objects.select_for_update().get(pk=delivery.endpoint_id)
    last = WebhookDelivery.objects.filter(
        event=delivery.event, endpoint=delivery.endpoint).order_by('-replay_number').first()
    return WebhookDelivery.objects.create(
        event=delivery.event, endpoint=delivery.endpoint,
        replay_number=(last.replay_number + 1),
        endpoint_url=endpoint.url,
        signing_secret=endpoint.secret,
        event_body=event_body(delivery.event), available_at=timezone.now())


def signature_header(secret, timestamp, raw_body):
    digest = hmac.new(
        secret.encode('utf-8'), f'{timestamp}.'.encode('ascii') + raw_body,
        hashlib.sha256).hexdigest()
    return f't={timestamp},v1={digest}'


def _claim(delivery_id):
    now = timezone.now()
    with transaction.atomic():
        delivery = WebhookDelivery.objects.select_for_update().filter(id=delivery_id).first()
        if delivery is None or delivery.status in ('delivered', 'failed'):
            return None
        if delivery.endpoint.status != 'active':
            delivery.status = 'failed'
            delivery.last_error = 'endpoint_disabled'
            delivery.save(update_fields=('status', 'last_error', 'updated_at'))
            return None
        if delivery.available_at > now:
            return None
        if (delivery.status == 'leased' and delivery.leased_at
                and delivery.leased_at > now - timedelta(minutes=2)):
            return None
        event = delivery.event
        if WebhookDelivery.objects.filter(
                endpoint_id=delivery.endpoint_id,
                event__aggregate_type=event.aggregate_type,
                event__aggregate_id=event.aggregate_id,
                event__aggregate_version__lt=event.aggregate_version,
        ).exclude(status__in=('delivered', 'failed')).exists():
            return None
        token = secrets.token_hex(16)
        delivery.status = 'leased'
        delivery.lease_token = token
        delivery.leased_at = now
        delivery.attempts += 1
        delivery.save(update_fields=(
            'status', 'lease_token', 'leased_at', 'attempts', 'updated_at'))
        return delivery, token


def deliver(delivery_id, *, sender=None):
    sender = sender or public_https_post
    claimed = _claim(delivery_id)
    if claimed is None:
        return False
    delivery, token = claimed
    raw_body = json.dumps(
        delivery.event_body, sort_keys=True, separators=(',', ':')).encode('utf-8')
    timestamp = int(time.time())
    error = ''
    response_status = None
    success = False
    try:
        # Resolve again immediately before every request to mitigate DNS rebinding.
        validate_delivery_url(delivery.endpoint_url)
        response = sender(
            delivery.endpoint_url, data=raw_body,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Confio-Webhooks/1.0',
                'Confio-Event-Id': delivery.event.public_id,
                'Confio-Delivery-Id': delivery.public_id,
                'Confio-Signature': signature_header(
                    delivery.signing_secret, timestamp, raw_body),
            }, timeout=10, allow_redirects=False)
        response_status = response.status_code
        success = 200 <= response.status_code < 300
        if not success:
            error = f'http_{response.status_code}'
    except (requests.RequestException, UnsafeWebhookUrl) as exc:
        error = type(exc).__name__

    with transaction.atomic():
        current = WebhookDelivery.objects.select_for_update().get(id=delivery.id)
        if current.lease_token != token:
            return False
        current.response_status = response_status
        current.last_error = error
        current.lease_token = ''
        current.leased_at = None
        if success:
            current.status = 'delivered'
            current.delivered_at = timezone.now()
        elif current.attempts >= 12:
            current.status = 'failed'
        else:
            current.status = 'retrying'
            delay = min(6 * 60 * 60, 30 * (2 ** (current.attempts - 1)))
            current.available_at = timezone.now() + timedelta(seconds=delay)
        current.save(update_fields=(
            'status', 'response_status', 'last_error', 'lease_token', 'leased_at',
            'available_at', 'delivered_at', 'updated_at'))
    return success
