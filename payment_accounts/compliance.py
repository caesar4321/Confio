import hashlib
import ipaddress
import mimetypes
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
import pycountry
from django.conf import settings

from payment_accounts.clients import ComplianceHandoffError


MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = {'image/jpeg', 'image/png', 'application/pdf'}


def iso_alpha2(value):
    normalized = str(value or '').strip().upper()
    country = (
        pycountry.countries.get(alpha_2=normalized)
        if len(normalized) == 2
        else pycountry.countries.get(alpha_3=normalized)
    )
    if not country:
        raise ComplianceHandoffError(f'Unsupported country code in compliance data: {value!r}')
    return country.alpha_2


@dataclass(frozen=True)
class EvidenceFile:
    url: str
    content: bytes
    content_type: str
    sha256: str


def _first(items):
    return next((item for item in (items or []) if isinstance(item, dict)), {})


def _approved_first(items):
    approved = next(
        (
            item for item in (items or [])
            if isinstance(item, dict)
            and str(item.get('status') or '').strip().lower() == 'approved'
        ),
        None,
    )
    return approved or _first(items)


def _required(value, label):
    if value in (None, '', [], {}):
        raise ComplianceHandoffError(f'Didit did not provide required {label}')
    return value


def _address(*, line_1, city, state, postal_code, country):
    values = {
        'line_1': line_1,
        'city': city,
        'state': state,
        'postal_code': postal_code,
        'country': iso_alpha2(country),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ComplianceHandoffError(
            f'Didit verification is missing Infinia address fields: {", ".join(missing)}'
        )
    return values


def _contact(decision, user):
    contact = decision.get('contact_details') or {}
    email = contact.get('email') or user.email
    phone = contact.get('phone')
    if not phone and user.phone_number and user.phone_country_code:
        phone = f'{user.phone_country_code}{user.phone_number}'
    return (
        _required(email, 'email address'),
        _required(phone, 'phone number with country code'),
    )


def _validate_media_url(url):
    parsed = urlparse(str(url or ''))
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ComplianceHandoffError('Didit evidence URL must be an authenticated HTTPS URL')
    allowed = {
        host.strip().lower()
        for host in getattr(settings, 'DIDIT_MEDIA_ALLOWED_HOSTS', [])
        if host.strip()
    }
    if not allowed:
        raise ComplianceHandoffError('Didit evidence host allowlist is not configured')
    hostname = parsed.hostname.lower()
    if allowed and not any(hostname == host or hostname.endswith(f'.{host}') for host in allowed):
        raise ComplianceHandoffError('Didit evidence URL host is not allowlisted')
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443)}
    except socket.gaierror as exc:
        raise ComplianceHandoffError('Didit evidence URL could not be resolved') from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ComplianceHandoffError('Didit evidence URL resolved to a private address')
    return str(url)


def fetch_didit_evidence(url, *, session=None):
    url = _validate_media_url(url)
    session = session or requests.Session()
    try:
        response = session.get(url, stream=True, timeout=20, allow_redirects=False)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ComplianceHandoffError('Unable to download Didit compliance evidence') from exc
    try:
        content_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].lower()
        if not content_type:
            content_type = mimetypes.guess_type(urlparse(url).path)[0] or ''
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ComplianceHandoffError('Didit evidence format is not accepted by Infinia')
        declared_length = response.headers.get('Content-Length')
        if declared_length:
            try:
                declared_length = int(declared_length)
            except (TypeError, ValueError) as exc:
                raise ComplianceHandoffError('Didit evidence has an invalid content length') from exc
            if declared_length > MAX_EVIDENCE_BYTES:
                raise ComplianceHandoffError('Didit evidence exceeds Infinia 10 MB limit')
        chunks = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_EVIDENCE_BYTES:
                raise ComplianceHandoffError('Didit evidence exceeds Infinia 10 MB limit')
            chunks.append(chunk)
        content = b''.join(chunks)
        if not content:
            raise ComplianceHandoffError('Didit evidence file is empty')
        return EvidenceFile(
            url=url,
            content=content,
            content_type=content_type,
            sha256=hashlib.sha256(content).hexdigest(),
        )
    finally:
        response.close()


def _normalized_roles(party):
    raw_roles = party.get('roles') or []
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    roles = set()
    for item in raw_roles:
        role = item.get('role') if isinstance(item, dict) else item
        normalized = str(role or '').strip().lower()
        if normalized:
            roles.add(normalized)
    role = str(party.get('role') or '').strip().lower()
    if role:
        roles.add(role)
    return roles


def _upload_document(client, *, document_type, front_url, back_url=None):
    front = fetch_didit_evidence(front_url, session=client.session)
    back = fetch_didit_evidence(back_url, session=client.session) if back_url else None
    initiated = client.initiate_owner_document(
        document_type=document_type,
        double_sided=bool(back),
    )
    document_id = str(_required(initiated.get('id'), 'Infinia document ID'))
    client.upload_owner_document(
        _required(initiated.get('upload_front_url'), 'Infinia front upload URL'),
        front.content,
        content_type=front.content_type,
    )
    if back:
        client.upload_owner_document(
            _required(initiated.get('upload_back_url'), 'Infinia back upload URL'),
            back.content,
            content_type=back.content_type,
        )
    return document_id, {
        'document_type': document_type,
        'document_id': document_id,
        'front_sha256': front.sha256,
        'back_sha256': back.sha256 if back else '',
    }


def _document_type(value):
    normalized = str(value or '').strip().lower().replace(' ', '_')
    if 'passport' in normalized:
        return 'PASSPORT'
    if 'driver' in normalized or 'driving' in normalized:
        return 'DRIVERS_LICENSE'
    return 'NATIONAL_ID'


def _individual_payload(*, decision, identity, user, client):
    if decision.get('session_kind') not in (None, '', 'user'):
        raise ComplianceHandoffError('A personal Infinia owner requires a Didit KYC session')
    id_check = _approved_first(decision.get('id_verifications'))
    liveness = _approved_first(decision.get('liveness_checks'))
    front_url = id_check.get('full_front_image') or id_check.get('front_image')
    back_url = id_check.get('full_back_image') or id_check.get('back_image')
    selfie_url = liveness.get('reference_image')
    identity_document_id, identity_audit = _upload_document(
        client,
        document_type=_document_type(id_check.get('document_type') or identity.document_type),
        front_url=_required(front_url, 'identity document image'),
        back_url=back_url,
    )
    selfie_document_id, selfie_audit = _upload_document(
        client,
        document_type='SELFIE',
        front_url=_required(selfie_url, 'liveness reference image'),
    )
    email, phone = _contact(decision, user)
    payload = {
        'first_name': identity.verified_first_name,
        'last_name': identity.verified_last_name,
        'date_of_birth': identity.verified_date_of_birth.isoformat(),
        'tax_id': identity.document_number,
        'tax_id_country': iso_alpha2(identity.document_issuing_country),
        'email': email,
        'phone_number': phone,
        'address': _address(
            line_1=identity.verified_address,
            city=identity.verified_city,
            state=identity.verified_state,
            postal_code=identity.verified_postal_code,
            country=identity.verified_country,
        ),
        'identity_document_id': identity_document_id,
        'selfie_document_id': selfie_document_id,
    }
    return payload, [identity_audit, selfie_audit]


BUSINESS_DOCUMENT_MAP = {
    'certificate_of_incorporation': ('CERTIFICATE_OF_INCORPORATION', 'incorporation_document_id'),
    'legal_presence': ('CERTIFICATE_OF_INCORPORATION', 'incorporation_document_id'),
    'source_of_funds': ('SOURCE_OF_FUNDS', 'source_of_funds_document_id'),
    'financial_statements': ('SOURCE_OF_FUNDS', 'source_of_funds_document_id'),
    'proof_of_address': ('PROOF_OF_ADDRESS', 'proof_of_address_document_id'),
    'ownership_structure': ('OWNERSHIP_STRUCTURE', 'ownership_structure_document_id'),
    'tax_registration': ('TAX_REGISTRATION', 'tax_registration_document_id'),
    'corporate_org_chart': ('CORPORATE_ORG_CHART', 'corporate_org_chart_document_id'),
}


def _business_documents(decision, client):
    fields = {}
    audits = []
    for check in decision.get('document_verifications') or []:
        for item in check.get('items') or []:
            if str(item.get('status') or '').strip().lower() != 'approved':
                continue
            raw_type = str(
                item.get('document_subtype')
                or item.get('document_type')
                or item.get('document_group')
                or ''
            ).strip().lower()
            mapping = next(
                (value for key, value in BUSINESS_DOCUMENT_MAP.items() if key in raw_type),
                None,
            )
            if not mapping or mapping[1] in fields or not item.get('file_url'):
                continue
            document_id, audit = _upload_document(
                client,
                document_type=mapping[0],
                front_url=item['file_url'],
            )
            fields[mapping[1]] = document_id
            audits.append(audit)
    required = {
        'incorporation_document_id',
        'source_of_funds_document_id',
        'proof_of_address_document_id',
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise ComplianceHandoffError(
            f'Didit KYB workflow is missing Infinia-required documents: {", ".join(missing)}'
        )
    return fields, audits


def _company(decision):
    registry = _approved_first(decision.get('registry_checks'))
    return _required(registry.get('company'), 'approved business registry result')


def _organization_payload(*, decision, identity, user, client, child_decisions):
    if decision.get('session_kind') != 'business':
        raise ComplianceHandoffError('A business Infinia owner requires a Didit KYB session')
    company = _company(decision)
    email, phone = _contact(decision, user)
    address_data = _first(company.get('addresses'))
    address = _address(
        line_1=address_data.get('address') or address_data.get('line_1') or company.get('registered_address'),
        city=address_data.get('city'),
        state=address_data.get('state') or address_data.get('region'),
        postal_code=address_data.get('postal_code'),
        country=address_data.get('country_code') or company.get('country_code'),
    )
    document_fields, audits = _business_documents(decision, client)
    parties = []
    for check in decision.get('key_people_checks') or []:
        parties.extend(((check.get('submitted') or {}).get('parties') or []))
    ubos = []
    seen = set()
    for party in parties:
        roles = _normalized_roles(party)
        if 'ubo' not in roles:
            continue
        if party.get('entity_type') not in (None, '', 'person'):
            raise ComplianceHandoffError('Infinia requires every UBO to be a natural person')
        child_id = str(_required(party.get('kyc_session_id'), 'UBO Didit KYC session ID'))
        if child_id in seen:
            continue
        seen.add(child_id)
        child = _required(child_decisions.get(child_id), 'UBO Didit KYC decision')
        child_identity = child.get('_identity')
        if not child_identity:
            raise ComplianceHandoffError('UBO Didit KYC identity was not normalized')
        ubo, ubo_audits = _individual_payload(
            decision=child,
            identity=child_identity,
            user=user,
            client=client,
        )
        ubos.append(ubo)
        audits.extend(ubo_audits)
    summary = _first(decision.get('key_people_checks')).get('ubo_kyc_summary') or {}
    if int(summary.get('total') or 0) and len(ubos) != int(summary.get('total')):
        raise ComplianceHandoffError('All Didit UBO KYC sessions must be approved and transferable')
    payload = {
        'name': _required(company.get('company_name'), 'company name'),
        'date_of_incorporation': _required(company.get('incorporation_date'), 'incorporation date'),
        'tax_id': _required(company.get('tax_number') or company.get('registration_number'), 'company tax ID'),
        'tax_id_country': iso_alpha2(_required(company.get('country_code'), 'company country')),
        'email': email,
        'phone_number': phone,
        'address': address,
        'ultimate_beneficial_owners': ubos,
        **document_fields,
    }
    return payload, audits


def build_infinia_self_declared_payload(*, profile, client, decision, child_decisions=None):
    if str(decision.get('status') or '').strip().lower() != 'approved':
        raise ComplianceHandoffError('Didit verification must be approved before Infinia onboarding')
    identity = profile.identity_verification
    if not identity or identity.status != 'verified':
        raise ComplianceHandoffError('Verified Didit identity is required')
    if (identity.risk_factors or {}).get('provider') != 'didit':
        raise ComplianceHandoffError('Infinia SELF_DECLARED onboarding requires Didit evidence')
    if profile.owner_type == 'business':
        details, audits = _organization_payload(
            decision=decision,
            identity=identity,
            user=profile.confio_account.user,
            client=client,
            child_decisions=child_decisions or {},
        )
        typed = {'organization': details}
    else:
        details, audits = _individual_payload(
            decision=decision,
            identity=identity,
            user=profile.confio_account.user,
            client=client,
        )
        typed = {'individual': details}
    return {
        'type': 'ORGANIZATION' if profile.owner_type == 'business' else 'INDIVIDUAL',
        'kyc_mode': 'SELF_DECLARED',
        'idempotency_key': str(profile.internal_id),
        **typed,
    }, audits
