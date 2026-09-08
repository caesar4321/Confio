from decimal import Decimal
import secrets

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.fields import DateTimeField
from rest_framework.exceptions import ValidationError

from billing.models import (
    BillingEvent, BillingObligation, BillingPayment, InstitutionApplication,
    ObligationSubject, SettlementLeg, WebhookDelivery, WebhookEndpoint,
)
from billing.webhooks import UnsafeWebhookUrl, create_replay, validate_delivery_url
from billing.institutions import public_institution_status

from .authentication import BusinessApiKeyAuthentication
from .errors import BillingApiError, request_id
from .idempotency import execute_idempotent
from .pagination import BillingCursorPagination
from .permissions import HasBillingScope
from .serializers import (
    ObligationCreateSerializer,
    SubjectPatchSerializer,
    SubjectWriteSerializer,
    WebhookEndpointCreateSerializer,
    WebhookEndpointPatchSerializer,
)


def _timestamp_filter(request, parameter):
    try:
        return DateTimeField().run_validation(request.query_params[parameter])
    except ValidationError:
        raise BillingApiError(code='validation_error',
                              message='Expected an ISO 8601 timestamp.', param=parameter)


def _subject_dto(subject):
    return {
        'id': subject.public_id,
        'object': 'subject',
        'external_id': subject.external_id,
        'type': subject.subject_type,
        'masked_reference': subject.masked_reference,
        'status': subject.status,
        'locale': subject.locale,
        'timezone': subject.timezone,
        'version': subject.version,
        'created_at': subject.created_at.isoformat(),
        'updated_at': subject.updated_at.isoformat(),
    }


def _obligation_dto(obligation):
    return {
        'id': obligation.public_id,
        'object': 'obligation',
        'external_id': obligation.external_reference,
        'subject': obligation.subject.public_id,
        'commercial_amount': {
            'value': f'{Decimal(obligation.original_amount_minor) / 100:.2f}',
            'currency': obligation.currency,
        },
        'amount_paid': {
            'value': f'{Decimal(obligation.amount_paid_minor) / 100:.2f}',
            'currency': obligation.currency,
        },
        'amount_remaining': {
            'value': f'{Decimal(obligation.amount_remaining_minor) / 100:.2f}',
            'currency': obligation.currency,
        },
        'period': {
            'start': obligation.period_start.isoformat(),
            'end': obligation.period_end.isoformat(),
        },
        'issued_at': obligation.issued_at.isoformat(),
        'due_at': obligation.due_at.isoformat(),
        'status': obligation.status,
        'created_at': obligation.created_at.isoformat(),
        'updated_at': obligation.updated_at.isoformat(),
    }


def _payment_dto(payment):
    return {
        'id': payment.public_id, 'object': 'payment', 'status': payment.status,
        'billing_invoice': payment.billing_invoice.public_id,
        'payment_intent': payment.payment_intent.public_id,
        'commercial_amount': {
            'minor_units': payment.commercial_amount_minor,
            'currency': payment.commercial_currency,
        },
        'settlement': {
            'asset': payment.settlement_asset, 'decimals': payment.settlement_decimals,
            'gross_units': str(payment.gross_units), 'fee_units': str(payment.fee_units),
            'receiver_net_units': str(payment.receiver_net_units), 'chain': payment.chain,
            'transaction_hash': payment.transaction_hash,
        },
        'confirmed_at': payment.confirmed_at.isoformat() if payment.confirmed_at else None,
        'created_at': payment.created_at.isoformat(),
    }


def _settlement_dto(leg):
    return {
        'id': leg.public_id, 'object': 'settlement',
        'payment': leg.billing_payment.public_id, 'chain_id': leg.chain_id,
        'contract_version': leg.contract_version, 'receiver_address': leg.receiver_address,
        'input_asset': leg.input_token_symbol, 'input_decimals': leg.input_token_decimals,
        'gross_units': str(leg.gross_units), 'fee_units': str(leg.fee_units),
        'input_net_units': str(leg.receiver_net_units), 'routed': leg.routed,
        'output_asset': leg.output_token_symbol, 'output_decimals': leg.output_token_decimals,
        'output_units': str(leg.output_units), 'transaction_hash': leg.transaction_hash,
        'block_number': leg.block_number, 'log_index': leg.log_index,
        'created_at': leg.created_at.isoformat(),
    }


def _application_dto(application):
    return {
        'id': application.public_id, 'object': 'institution_application',
        'payment': application.billing_payment.public_id,
        'status': application.status, 'attempts': application.attempts,
        'acknowledgement_reference': application.acknowledgement_reference,
        'returned_status': public_institution_status(application.returned_status),
        'returned_version': application.returned_version,
        'created_at': application.created_at.isoformat(),
        'payment_confirmed_at': application.payment_confirmed_at.isoformat(),
        'institution_applied_at': (
            application.institution_applied_at.isoformat()
            if application.institution_applied_at else None),
    }


def _event_dto(event):
    return {
        'id': event.public_id, 'object': 'event', 'type': event.event_type,
        'api_version': event.api_version, 'data': event.payload.get('data', {}),
        'created_at': event.created_at.isoformat(),
    }


def _endpoint_dto(endpoint):
    return {
        'id': endpoint.public_id, 'object': 'webhook_endpoint', 'mode': endpoint.mode,
        'url': endpoint.url, 'event_types': endpoint.event_types,
        'status': endpoint.status, 'description': endpoint.description,
        'created_at': endpoint.created_at.isoformat(),
        'updated_at': endpoint.updated_at.isoformat(),
    }


def _delivery_dto(delivery):
    return {
        'id': delivery.public_id, 'object': 'webhook_delivery',
        'event': delivery.event.public_id, 'endpoint': delivery.endpoint.public_id,
        'replay_number': delivery.replay_number, 'status': delivery.status,
        'attempts': delivery.attempts, 'response_status': delivery.response_status,
        'last_error': delivery.last_error,
        'delivered_at': delivery.delivered_at.isoformat() if delivery.delivered_at else None,
        'created_at': delivery.created_at.isoformat(),
    }


class BillingAPIView(APIView):
    authentication_classes = (BusinessApiKeyAuthentication,)
    permission_classes = (HasBillingScope,)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Confio-Request-Id'] = request_id(request)
        if hasattr(request, 'billing_rate_limit'):
            response['RateLimit-Limit'] = request.billing_rate_limit
            response['RateLimit-Remaining'] = request.billing_rate_remaining
            response['RateLimit-Reset'] = request.billing_rate_reset
        return response

    def invalid(self, serializer):
        first_field = next(iter(serializer.errors), None)
        raise BillingApiError(
            code='validation_error', message=str(serializer.errors),
            status_code=400, param=first_field)


class SubjectListCreateView(BillingAPIView):
    def get_permissions(self):
        self.required_scope = (
            'subjects:read' if self.request.method == 'GET' else 'subjects:write')
        return super().get_permissions()

    def get(self, request):
        queryset = ObligationSubject.objects.filter(
            business_id=request.user.business_id, mode=request.user.mode)
        if request.query_params.get('external_id'):
            queryset = queryset.filter(
                external_id=request.query_params['external_id'])
        if request.query_params.get('updated_after'):
            queryset = queryset.filter(updated_at__gt=_timestamp_filter(request, 'updated_after'))
        paginator = BillingCursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([_subject_dto(item) for item in page])

    def post(self, request):
        serializer = SubjectWriteSerializer(data=request.data)
        if not serializer.is_valid():
            self.invalid(serializer)

        def operation():
            data = serializer.validated_data
            if ObligationSubject.objects.filter(
                    business_id=request.user.business_id,
                    mode=request.user.mode, external_id=data['external_id']).exists():
                raise BillingApiError(
                    code='subject_external_id_conflict',
                    message='A subject with this external_id already exists.',
                    status_code=409, param='external_id')
            try:
                with transaction.atomic():
                    subject = ObligationSubject.objects.create(
                        business_id=request.user.business_id, mode=request.user.mode, **data)
            except IntegrityError:
                raise BillingApiError(
                    code='subject_external_id_conflict',
                    message='A subject with this external_id already exists.',
                    status_code=409, param='external_id')
            return Response(_subject_dto(subject), status=201)

        return execute_idempotent(request, operation)


class SubjectDetailView(BillingAPIView):
    def get_permissions(self):
        self.required_scope = (
            'subjects:read' if self.request.method == 'GET' else 'subjects:write')
        return super().get_permissions()

    def _get(self, request, public_id):
        return get_object_or_404(
            ObligationSubject,
            business_id=request.user.business_id, mode=request.user.mode, public_id=public_id)

    def get(self, request, public_id):
        return Response(_subject_dto(self._get(request, public_id)))

    def patch(self, request, public_id):
        serializer = SubjectPatchSerializer(data=request.data)
        if not serializer.is_valid():
            self.invalid(serializer)
        try:
            expected_version = int(request.headers.get('If-Match', ''))
        except ValueError:
            expected_version = 0
        if expected_version <= 0:
            raise BillingApiError(
                code='if_match_required',
                message='If-Match must contain the current numeric version.',
                status_code=409, param='If-Match')

        def operation():
            subject = ObligationSubject.objects.select_for_update().filter(
                business_id=request.user.business_id,
                mode=request.user.mode, public_id=public_id).first()
            if subject is None:
                raise BillingApiError(
                    code='resource_not_found', message='Subject not found.',
                    status_code=404)
            if subject.version != expected_version:
                raise BillingApiError(
                    code='version_conflict',
                    message='The subject has changed; fetch it and retry.',
                    status_code=409, param='If-Match')
            for field, value in serializer.validated_data.items():
                setattr(subject, field, value)
            subject.version += 1
            subject.save(update_fields=(
                *serializer.validated_data.keys(), 'version', 'updated_at'))
            return Response(_subject_dto(subject))

        return execute_idempotent(request, operation)


class ObligationListCreateView(BillingAPIView):
    def get_permissions(self):
        self.required_scope = (
            'obligations:read' if self.request.method == 'GET'
            else 'obligations:write')
        return super().get_permissions()

    def get(self, request):
        queryset = BillingObligation.objects.select_related('subject').filter(
            business_id=request.user.business_id, mode=request.user.mode)
        for parameter, field in (
                ('external_id', 'external_reference'), ('status', 'status')):
            if request.query_params.get(parameter):
                queryset = queryset.filter(
                    **{field: request.query_params[parameter]})
        if request.query_params.get('subject'):
            queryset = queryset.filter(
                subject__public_id=request.query_params['subject'])
        if request.query_params.get('updated_after'):
            queryset = queryset.filter(updated_at__gt=_timestamp_filter(request, 'updated_after'))
        paginator = BillingCursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([_obligation_dto(item) for item in page])

    def post(self, request):
        serializer = ObligationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            self.invalid(serializer)

        def operation():
            data = serializer.validated_data
            subject = ObligationSubject.objects.filter(
                business_id=request.user.business_id,
                mode=request.user.mode, public_id=data['subject'], status='active').first()
            if subject is None:
                raise BillingApiError(
                    code='subject_not_found',
                    message='Active subject not found.', status_code=404,
                    param='subject')
            external_id = data['external_id']
            if BillingObligation.objects.filter(
                    business_id=request.user.business_id,
                    mode=request.user.mode, external_reference=external_id).exists():
                raise BillingApiError(
                    code='obligation_external_id_conflict',
                    message='An obligation with this external_id already exists.',
                    status_code=409, param='external_id')
            amount = data['commercial_amount']
            amount_minor = int(amount['value'] * 100)
            period = data['period']
            description = data.get('description', '')
            try:
                with transaction.atomic():
                    obligation = BillingObligation.objects.create(
                        business_id=request.user.business_id,
                        mode=request.user.mode,
                        subject=subject, external_reference=external_id,
                        currency=amount['currency'],
                        original_amount_minor=amount_minor,
                        amount_remaining_minor=amount_minor,
                        line_items_snapshot=[{
                            'description': description,
                            'amount_minor': amount_minor,
                        }],
                        period_start=period['start'], period_end=period['end'],
                        issued_at=data.get('issued_at', timezone.now()),
                        due_at=data['due_at'], status='open', source_version='api-v1')
            except IntegrityError:
                raise BillingApiError(
                    code='obligation_external_id_conflict',
                    message='An obligation with this external_id already exists.',
                    status_code=409, param='external_id')
            return Response(_obligation_dto(obligation), status=201)

        return execute_idempotent(request, operation)


class ObligationDetailView(BillingAPIView):
    required_scope = 'obligations:read'

    def get(self, request, public_id):
        obligation = get_object_or_404(
            BillingObligation.objects.select_related('subject'),
            business_id=request.user.business_id, mode=request.user.mode, public_id=public_id)
        return Response(_obligation_dto(obligation))


class TenantReadListView(BillingAPIView):
    dto = None

    def get_queryset(self, request):
        raise NotImplementedError

    def get(self, request):
        paginator = BillingCursorPagination()
        page = paginator.paginate_queryset(self.get_queryset(request), request, view=self)
        return paginator.get_paginated_response([self.dto(item) for item in page])


class PaymentListView(TenantReadListView):
    required_scope = 'payments:read'
    dto = staticmethod(_payment_dto)

    def get_queryset(self, request):
        queryset = BillingPayment.objects.select_related(
            'billing_invoice', 'payment_intent').filter(
                billing_invoice__business_id=request.user.business_id,
                billing_invoice__subject__mode=request.user.mode)
        if request.query_params.get('status'):
            queryset = queryset.filter(status=request.query_params['status'])
        if request.query_params.get('subject'):
            queryset = queryset.filter(billing_invoice__subject__public_id=request.query_params['subject'])
        if request.query_params.get('obligation'):
            queryset = queryset.filter(
                effects__allocations__obligation__public_id=request.query_params['obligation'])
        if request.query_params.get('updated_after'):
            queryset = queryset.filter(updated_at__gt=_timestamp_filter(request, 'updated_after'))
        return queryset.distinct()


class PaymentDetailView(BillingAPIView):
    required_scope = 'payments:read'

    def get(self, request, public_id):
        item = get_object_or_404(BillingPayment.objects.select_related(
            'billing_invoice', 'payment_intent'), public_id=public_id,
            billing_invoice__business_id=request.user.business_id,
            billing_invoice__subject__mode=request.user.mode)
        return Response(_payment_dto(item))


class SettlementListView(TenantReadListView):
    required_scope = 'settlements:read'
    dto = staticmethod(_settlement_dto)

    def get_queryset(self, request):
        queryset = SettlementLeg.objects.select_related('billing_payment').filter(
            billing_payment__billing_invoice__business_id=request.user.business_id,
            billing_payment__billing_invoice__subject__mode=request.user.mode)
        if request.query_params.get('payment'):
            queryset = queryset.filter(
                billing_payment__public_id=request.query_params['payment'])
        return queryset


class ApplicationListView(TenantReadListView):
    required_scope = 'applications:read'
    dto = staticmethod(_application_dto)

    def get_queryset(self, request):
        queryset = InstitutionApplication.objects.select_related('billing_payment').filter(
            billing_payment__billing_invoice__business_id=request.user.business_id,
            billing_payment__billing_invoice__subject__mode=request.user.mode,
            connection__mode=request.user.mode)
        if request.query_params.get('payment'):
            queryset = queryset.filter(billing_payment__public_id=request.query_params['payment'])
        if request.query_params.get('obligation'):
            queryset = queryset.filter(
                allocation__obligation__public_id=request.query_params['obligation'])
        if request.query_params.get('status'):
            queryset = queryset.filter(status=request.query_params['status'])
        if request.query_params.get('updated_after'):
            queryset = queryset.filter(updated_at__gt=_timestamp_filter(request, 'updated_after'))
        return queryset


class ApplicationDetailView(BillingAPIView):
    required_scope = 'applications:read'

    def get(self, request, public_id):
        item = get_object_or_404(InstitutionApplication.objects.select_related(
            'billing_payment'), public_id=public_id,
            billing_payment__billing_invoice__business_id=request.user.business_id,
            billing_payment__billing_invoice__subject__mode=request.user.mode,
            connection__mode=request.user.mode)
        return Response(_application_dto(item))


class EventListView(TenantReadListView):
    required_scope = 'events:read'
    dto = staticmethod(_event_dto)

    def get_queryset(self, request):
        queryset = BillingEvent.objects.filter(business_id=request.user.business_id, mode=request.user.mode)
        if request.query_params.get('type'):
            queryset = queryset.filter(event_type=request.query_params['type'])
        if request.query_params.get('created_after'):
            queryset = queryset.filter(created_at__gte=_timestamp_filter(request, 'created_after'))
        return queryset


class EventDetailView(BillingAPIView):
    required_scope = 'events:read'

    def get(self, request, public_id):
        event = get_object_or_404(
            BillingEvent, public_id=public_id, business_id=request.user.business_id,
            mode=request.user.mode)
        return Response(_event_dto(event))


class WebhookEndpointListCreateView(BillingAPIView):
    def get_permissions(self):
        self.required_scope = ('webhook_endpoints:read' if self.request.method == 'GET'
                               else 'webhook_endpoints:write')
        return super().get_permissions()

    def get(self, request):
        endpoints = WebhookEndpoint.objects.filter(
            business_id=request.user.business_id, mode=request.user.mode).order_by('-created_at')
        return Response({'data': [_endpoint_dto(item) for item in endpoints]})

    def post(self, request):
        serializer = WebhookEndpointCreateSerializer(data=request.data)
        if not serializer.is_valid():
            self.invalid(serializer)

        def operation():
            try:
                validate_delivery_url(serializer.validated_data['url'])
            except UnsafeWebhookUrl as exc:
                raise BillingApiError(code='unsafe_webhook_url', message=str(exc),
                                      status_code=400, param='url')
            secret = 'whsec_' + secrets.token_urlsafe(32)
            endpoint = WebhookEndpoint.objects.create(
                business_id=request.user.business_id, mode=request.user.mode,
                secret=secret, **serializer.validated_data)
            body = _endpoint_dto(endpoint)
            body['signing_secret'] = secret
            return Response(body, status=201)

        return execute_idempotent(request, operation)


class WebhookEndpointDetailView(BillingAPIView):
    def get_permissions(self):
        self.required_scope = ('webhook_endpoints:read' if self.request.method == 'GET'
                               else 'webhook_endpoints:write')
        return super().get_permissions()

    def _get(self, request, public_id):
        return get_object_or_404(WebhookEndpoint, business_id=request.user.business_id,
                                 mode=request.user.mode, public_id=public_id)

    def get(self, request, public_id):
        return Response(_endpoint_dto(self._get(request, public_id)))

    def patch(self, request, public_id):
        serializer = WebhookEndpointPatchSerializer(data=request.data)
        if not serializer.is_valid():
            self.invalid(serializer)

        def operation():
            endpoint = get_object_or_404(
                WebhookEndpoint.objects.select_for_update(), business_id=request.user.business_id,
                mode=request.user.mode, public_id=public_id)
            for field, value in serializer.validated_data.items():
                setattr(endpoint, field, value)
            endpoint.save(update_fields=(*serializer.validated_data.keys(), 'updated_at'))
            return Response(_endpoint_dto(endpoint))
        return execute_idempotent(request, operation)

    def delete(self, request, public_id):
        def operation():
            endpoint = get_object_or_404(
                WebhookEndpoint.objects.select_for_update(), business_id=request.user.business_id,
                mode=request.user.mode, public_id=public_id)
            endpoint.status = 'disabled'
            endpoint.save(update_fields=('status', 'updated_at'))
            return Response(status=204)
        return execute_idempotent(request, operation)


class WebhookEndpointRotateSecretView(BillingAPIView):
    required_scope = 'webhook_endpoints:write'

    def post(self, request, public_id):
        def operation():
            endpoint = get_object_or_404(
                WebhookEndpoint.objects.select_for_update(), business_id=request.user.business_id,
                mode=request.user.mode, public_id=public_id)
            endpoint.secret = 'whsec_' + secrets.token_urlsafe(32)
            endpoint.save(update_fields=('secret', 'updated_at'))
            body = _endpoint_dto(endpoint)
            body['signing_secret'] = endpoint.secret
            return Response(body)
        return execute_idempotent(request, operation)


class WebhookEndpointTestView(BillingAPIView):
    required_scope = 'webhook_endpoints:write'

    def post(self, request, public_id):
        def operation():
            endpoint = get_object_or_404(
                WebhookEndpoint.objects.select_for_update(), business_id=request.user.business_id,
                mode=request.user.mode, public_id=public_id)
            previous_version = BillingEvent.objects.filter(
                business_id=request.user.business_id, mode=request.user.mode,
                aggregate_type='webhook_endpoint', aggregate_id=endpoint.public_id
            ).aggregate(version=Max('aggregate_version'))['version'] or 0
            event = BillingEvent.objects.create(
                business_id=request.user.business_id, event_type='endpoint.test',
                mode=request.user.mode,
                aggregate_type='webhook_endpoint', aggregate_id=endpoint.public_id,
                aggregate_version=previous_version + 1,
                transition_key=f'endpoint:{endpoint.id}:test:{secrets.token_hex(12)}',
                payload={'object': 'event', 'type': 'endpoint.test',
                         'data': {'object': _endpoint_dto(endpoint)}})
            delivery = WebhookDelivery.objects.create(
                event=event, endpoint=endpoint, endpoint_url=endpoint.url,
                signing_secret=endpoint.secret,
                event_body={**event.payload, 'id': event.public_id,
                            'api_version': event.api_version,
                            'created_at': event.created_at.isoformat()},
                available_at=timezone.now())
            return Response(_delivery_dto(delivery), status=201)
        return execute_idempotent(request, operation)


class WebhookDeliveryListView(TenantReadListView):
    required_scope = 'webhook_endpoints:read'
    dto = staticmethod(_delivery_dto)

    def get_queryset(self, request):
        queryset = WebhookDelivery.objects.select_related('event', 'endpoint').filter(
            event__business_id=request.user.business_id, endpoint__mode=request.user.mode)
        if request.query_params.get('event'):
            queryset = queryset.filter(event__public_id=request.query_params['event'])
        if request.query_params.get('status'):
            queryset = queryset.filter(status=request.query_params['status'])
        return queryset


class WebhookDeliveryDetailView(BillingAPIView):
    required_scope = 'webhook_endpoints:read'

    def get(self, request, public_id):
        delivery = get_object_or_404(WebhookDelivery.objects.select_related(
            'event', 'endpoint'), public_id=public_id,
            event__business_id=request.user.business_id, endpoint__mode=request.user.mode)
        return Response(_delivery_dto(delivery))


class WebhookDeliveryReplayView(BillingAPIView):
    required_scope = 'webhook_endpoints:write'

    def post(self, request, public_id):
        def operation():
            delivery = get_object_or_404(WebhookDelivery.objects.select_related(
                'event', 'endpoint'), public_id=public_id,
                event__business_id=request.user.business_id,
                endpoint__mode=request.user.mode)
            replay = create_replay(delivery)
            return Response(_delivery_dto(replay), status=201)
        return execute_idempotent(request, operation)
