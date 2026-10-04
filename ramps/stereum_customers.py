"""Reuse verified Confío identity data for Stereum's sandbox onboarding."""
import hashlib
import json
import unicodedata
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone

from .models import StereumCustomer
from .stereum_client import StereumClient, StereumError, resource_id, validate_response

DEPARTMENTS = {'BO_B', 'BO_C', 'BO_H', 'BO_L', 'BO_O', 'BO_N', 'BO_P', 'BO_S', 'BO_T'}
INCOMES = {'Menos de $500', '500 - 1000', '1000 - 2000', '2000 - 5000', 'Más de $5,000'}
FIELDS = {'state_of_residence', 'economic_activity', 'source_of_funds', 'destination_of_funds',
          'income_level', 'surname1', 'surname2', 'complement_number'}


def access(user):
    if not getattr(settings, 'STEREUM_TEST_ENABLED', False) or not getattr(settings, 'STEREUM_CUSTOMER_TEST_ENABLED', False):
        raise StereumError('Stereum customer sandbox is disabled.')
    if not user or not user.is_authenticated or not user.is_active:
        raise StereumError('An active authenticated user is required.')


def required(data, key, limit):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise StereumError(f'{key} is required (maximum {limit} characters).')
    return value.strip()


def current_identity(user):
    from security.models import IdentityVerification
    identity = IdentityVerification.objects.filter(user=user).filter(
        Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'),
    ).order_by('-updated_at', '-pk').first()
    if not identity or identity.status != 'verified':
        raise StereumError('A current verified personal identity is required.')
    today = timezone.localdate(timezone=ZoneInfo('America/La_Paz'))
    if identity.document_expiry_date and identity.document_expiry_date < today:
        raise StereumError('Your verified identity document has expired.')
    return identity


def identity_data(identity):
    document_type = {'national_id': 'CI', 'foreign_id': 'CE', 'passport': 'PASSPORT'}.get(identity.document_type)
    if not document_type:
        raise StereumError('Stereum supports national IDs, foreign resident IDs and passports.')
    if document_type != 'PASSPORT' and identity.document_issuing_country.upper() not in {'BO', 'BOL'}:
        raise StereumError('SEGIP requires a Bolivian-issued CI or CE.')
    if identity.verified_country.upper() not in {'BO', 'BOL'}:
        raise StereumError('This Stereum integration currently supports residents of Bolivia.')
    dob = identity.verified_date_of_birth
    if not dob or dob >= timezone.localdate(timezone=ZoneInfo('America/La_Paz')):
        raise StereumError('A valid verified date of birth is required.')
    return {
        'name': required({'name': identity.verified_first_name}, 'name', 100),
        'lastname': required({'lastname': identity.verified_last_name}, 'lastname', 100),
        'document_type': document_type,
        'document_number': required({'document_number': identity.document_number}, 'document_number', 20),
        'country': 'BO', 'birthdate': dob.strftime('%d/%m/%Y'),
    }


def fingerprint(identity):
    return hashlib.sha256(json.dumps(identity_data(identity), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(identity, extra):
    if not isinstance(extra, dict) or set(extra) - FIELDS:
        raise StereumError('Unexpected customer onboarding fields.')
    customer = identity_data(identity)
    birthdate = customer.pop('birthdate')
    customer.update({key: required(extra, key, limit) for key, limit in {
        'state_of_residence': 4, 'economic_activity': 200, 'source_of_funds': 60,
        'destination_of_funds': 60, 'income_level': 30,
    }.items()})
    if customer['state_of_residence'] not in DEPARTMENTS or customer['income_level'] not in INCOMES:
        raise StereumError('Select a supported Bolivian department and income bracket.')
    validation = None
    if customer['document_type'] != 'PASSPORT':
        surname1 = required(extra, 'surname1', 100)
        surname2 = extra.get('surname2', '')
        complement = extra.get('complement_number', '')
        if not isinstance(surname2, str) or len(surname2) > 100 or not isinstance(complement, str) or len(complement) > 20:
            raise StereumError('Invalid surname or document complement.')
        normalize = lambda value: ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
        if normalize(' '.join([surname1, surname2])) != normalize(customer['lastname']):
            raise StereumError('The surname fields must match the verified full surname.')
        validation = {'givenNames': customer['name'], 'surname1': surname1, 'surname2': surname2.strip(),
                      'birthdate': birthdate, 'dniType': customer['document_type'],
                      'documentNumber': customer['document_number'], 'complementNumber': complement.strip()}
    return {'customer': customer, 'validation': validation}


def onboarding_status(user, *, client=None):
    access(user)
    client = client or StereumClient()
    return StereumCustomer.objects.filter(user=user, credential_scope=client.scope).first()


def quote_customer(user, *, client=None):
    access(user)
    client = client or StereumClient()
    customer = onboarding_status(user, client=client)
    if not customer or customer.status != 'registered':
        raise StereumError('Complete Stereum customer registration before requesting an end-user quote.')
    identity = current_identity(user)
    if customer.identity_fingerprint != fingerprint(identity):
        raise StereumError('Your verified identity changed; Stereum registration requires reconciliation.')
    # Stereum documents externalUserId as our registration idempotency_key,
    # not the provider-generated customer ID. Never fall back to SELF.
    return str(customer.external_user_id)


def onboard(user, extra, *, consent=False, client=None):
    access(user)
    if consent is not True:
        raise StereumError('Consent to share identity data with Stereum is required.')
    if not getattr(settings, 'STEREUM_TEST_WRITES_ENABLED', False):
        raise StereumError('Stereum test mutations are disabled.')
    client = client or StereumClient()
    # Reserve the user before either signed POST. A repeat or competing request
    # returns the saved attempt; unknown/in-flight outcomes are never replayed.
    with transaction.atomic(durable=True):
        locked_user = type(user).objects.select_for_update().get(pk=user.pk)
        access(locked_user)
        identity = current_identity(user)
        payload = snapshot(identity, extra)
        record = StereumCustomer.objects.filter(user=user, credential_scope=client.scope).first()
        if record:
            if record.request_snapshot != payload or record.identity_fingerprint != fingerprint(identity):
                raise StereumError('Customer data differs from the reserved registration; reconcile it before changing identity.')
            if record.status != 'validated':
                return record
        else:
            record = StereumCustomer.objects.create(user=user, credential_scope=client.scope,
                source_verification=identity, identity_fingerprint=fingerprint(identity), request_snapshot=payload,
                status='validating' if payload['validation'] else 'validated', consent_at=timezone.now())
    if record.status == 'validating':
        try:
            result = validate_response(client.validate_identity(payload['validation']), writes=True)
            if not isinstance(result, dict):
                raise StereumError('Invalid identity validation response.', ambiguous=True)
            if result.get('status') != 'VERIFIED':
                raise StereumError('Stereum did not verify the supplied identity.')
            validation_id = result.get('validationId')
            if not isinstance(validation_id, str) or not validation_id or len(validation_id) > 160:
                raise StereumError('Stereum verified identity without a usable validation reference.', ambiguous=True)
            record.validation_id = validation_id
            record.status = 'validated'
            record.save(update_fields=['validation_id', 'status', 'updated_at'])
        except StereumError as exc:
            record.status = 'unknown' if exc.ambiguous else 'rejected'
            record.error = str(exc)[:300]
            record.save(update_fields=['status', 'error', 'updated_at'])
            return record
    return _register(record.pk, user, client)


def _register(pk, user, client):
    with transaction.atomic(durable=True):
        record = StereumCustomer.objects.select_for_update().get(pk=pk, user=user, credential_scope=client.scope)
        if record.status != 'validated':
            return record
        payload = dict(record.request_snapshot['customer'])
        if payload['document_type'] != 'PASSPORT':
            if not record.validation_id:
                raise StereumError('SEGIP validation reference is missing.')
            payload['doc_provider_id'] = record.validation_id
        payload['idempotency_key'] = str(record.external_user_id)
        record.status = 'registering'
        record.save(update_fields=['status', 'updated_at'])
    try:
        result = validate_response(client.create_customer(payload), writes=True)
        if not isinstance(result, dict):
            raise StereumError('Invalid customer registration response.', ambiguous=True)
        try:
            provider_id = resource_id(result.get('id'))
        except StereumError:
            raise StereumError('Customer registration returned no usable ID; reconcile before retrying.', ambiguous=True) from None
        # Registration can return an existing customer by document number. Ensure
        # that identity matches before binding it to this Confío user.
        if any(result.get(key) != payload[key] for key in ('document_number', 'document_type', 'country')):
            raise StereumError('Returned customer identity does not match; reconcile with Stereum.', ambiguous=True)
        record.provider_customer_id = provider_id
        record.status = 'registered'
    except StereumError as exc:
        record.status = 'unknown' if exc.ambiguous else 'rejected'
        record.error = str(exc)[:300]
    try:
        with transaction.atomic():
            record.save(update_fields=['provider_customer_id', 'status', 'error', 'updated_at'])
    except IntegrityError:
        record.provider_customer_id = ''
        record.status = 'unknown'
        record.error = 'Provider customer is already linked; reconcile with Stereum.'
        record.save(update_fields=['provider_customer_id', 'status', 'error', 'updated_at'])
    return record
