import hashlib
import ipaddress
import mimetypes
import socket
import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
import pycountry
from django.conf import settings

from payment_accounts.clients import ComplianceHandoffError


MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = {'image/jpeg', 'image/png', 'application/pdf'}

# These IDs identify the reviewed questionnaire *versions*, not their titles.
# Updating a workflow preserves its ID, but publishing a questionnaire version
# requires explicitly reviewing and updating this mapping.
BUSINESS_WORKFLOW_ID = '8513abf3-95b2-4740-8dda-2d629d0c5d77'
PERSON_WORKFLOW_ID = 'f3c80006-d551-4fab-9317-46ce9a5236dc'
BUSINESS_QUESTIONNAIRE_ID = '4290ba59-8631-45c6-9afb-54e1bc586858'
PERSON_QUESTIONNAIRE_ID = 'd3ad7c27-3561-4db0-9fba-cfd3a3361c01'


def _reviewed_answers(decision, questionnaire_id, workflow_id):
    responses = decision.get('questionnaire_responses') or []
    matches = [r for r in responses if isinstance(r, dict)
               and r.get('questionnaire_id') == questionnaire_id]
    if not matches:
        if decision.get('workflow_id') == workflow_id or responses:
            raise ComplianceHandoffError('The required reviewed KYB questionnaire is missing')
        return {}
    if (len(matches) != 1 or str(decision.get('status') or '').lower() != 'approved'
            or str(matches[0].get('status') or '').lower() != 'approved'):
        raise ComplianceHandoffError('The KYB questionnaire must be individually approved')
    answers = {}
    for section in matches[0].get('sections') or []:
        for item in section.get('items') or []:
            key = item.get('value')
            if not key:
                continue
            if key in answers:
                raise ComplianceHandoffError('Ambiguous duplicate KYB questionnaire answer')
            answers[key] = item.get('answer') if isinstance(item.get('answer'), dict) else {}
    if not answers:
        raise ComplianceHandoffError('The reviewed KYB questionnaire contains no answers')
    return answers


def _answer_files(answers, key):
    files = answers.get(key, {}).get('files') or []
    if not isinstance(files, list):
        raise ComplianceHandoffError('Invalid KYB evidence file list')
    urls = [item.get('url') if isinstance(item, dict) else item for item in files]
    if any(not isinstance(url, str) or not url.strip() for url in urls):
        raise ComplianceHandoffError('Invalid KYB evidence file URL')
    return urls


def _questionnaire_address(answers, prefix):
    return _address(**{field: answers.get(f'{prefix}_{field}', {}).get('value')
                      for field in ('line_1', 'city', 'state', 'postal_code', 'country')})


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
    if value in (None, '', [], {}) or (isinstance(value, str) and not value.strip()):
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
    missing = [name for name, value in values.items() if not isinstance(value, str) or not value.strip()
               or value in {'Verified by Didit', 'Unknown City', 'Unknown State'}]
    if missing:
        raise ComplianceHandoffError(
            f'Didit verification is missing Infinia address fields: {", ".join(missing)}'
        )
    return values


def _verified_contact(decision):
    email = _approved_first(decision.get('email_verifications'))
    phone = _approved_first(decision.get('phone_verifications'))
    if any(str(item.get('status') or '').lower() != 'approved' for item in (email, phone)):
        raise ComplianceHandoffError('Approved email and phone verifications are required for KYB')
    return (_required(email.get('email'), 'verified email address'),
            _required(phone.get('full_number'), 'verified phone number'))


def _contact(decision, user):
    contact = decision.get('contact_details') or {}
    email = contact.get('email') or (user.email if user else None)
    phone = contact.get('phone')
    if not phone and user and user.phone_number and user.phone_country_code:
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


def didit_ubo_parties(decision):
    """UBOs from both authoritative Key People buckets, with deletion safeguards.

    Registry-derived people do not appear in submitted.parties (source=USER).
    Use their detailed Key People linkage, not the company's simplified URLs.
    """
    result = []
    for check in decision.get('key_people_checks') or []:
        registry = check.get('registry') or {}
        candidates = [*(registry.get('officers') or []),
                      *((check.get('submitted') or {}).get('parties') or [])]
        for party in registry.get('beneficial_owners') or []:
            candidates.append({**party, 'roles': [*_normalized_roles(party), 'ubo']})
        for party in candidates:
            if 'ubo' not in _normalized_roles(party):
                continue
            if party.get('is_skipped') or party.get('kyc_session_deleted'):
                raise ComplianceHandoffError('Skipped or deleted UBO KYC cannot be transferred to Infinia')
            if party.get('entity_type') not in (None, '', 'person'):
                raise ComplianceHandoffError('Infinia requires every UBO to be a natural person')
            _required(party.get('kyc_session_id'), 'UBO Didit KYC session ID')
            result.append(party)
    return result


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


def _combined_pdf(files):
    """One PDF with every page of every file (an image becomes one page)."""
    from io import BytesIO

    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    try:
        for item in files:
            source = BytesIO(item.content)
            if item.content_type != 'application/pdf':
                source = BytesIO()
                Image.open(BytesIO(item.content)).convert('RGB').save(source, 'PDF')
                source.seek(0)
            for page in PdfReader(source).pages:
                writer.add_page(page)
        output = BytesIO()
        writer.write(output)
    except Exception as exc:
        raise ComplianceHandoffError('Unable to combine the Didit evidence into one document') from exc
    return output.getvalue()


def _upload_bundle(client, *, document_type, urls):
    """Every file as ONE provider document: Infinia keeps a single document per type."""
    if len(urls) == 1:
        return _upload_document(client, document_type=document_type, front_url=urls[0])
    files = [fetch_didit_evidence(url, session=client.session) for url in urls]
    content = _combined_pdf(files)
    if len(content) > MAX_EVIDENCE_BYTES:
        raise ComplianceHandoffError('Didit evidence exceeds Infinia 10 MB limit')
    initiated = client.initiate_owner_document(document_type=document_type, double_sided=False)
    document_id = str(_required(initiated.get('id'), 'Infinia document ID'))
    client.upload_owner_document(
        _required(initiated.get('upload_front_url'), 'Infinia front upload URL'),
        content,
        content_type='application/pdf',
    )
    return document_id, {
        'document_type': document_type,
        'document_id': document_id,
        'front_sha256': hashlib.sha256(content).hexdigest(),
        'source_sha256': [item.sha256 for item in files],
    }


def _document_type(value):
    normalized = str(value or '').strip().lower().replace(' ', '_')
    types = {
        'passport': 'PASSPORT',
        'drivers_license': 'DRIVERS_LICENSE',
        'driver_license': 'DRIVERS_LICENSE',
        "driver's_license": 'DRIVERS_LICENSE',
        'driving_license': 'DRIVERS_LICENSE',
        'national_id': 'NATIONAL_ID',
        'id': 'NATIONAL_ID',
        'identity_card': 'NATIONAL_ID',
        'national_identity_card': 'NATIONAL_ID',
        'id_card': 'NATIONAL_ID',
    }
    if normalized not in types:
        raise ComplianceHandoffError('Unsupported Infinia identity document type')
    return types[normalized]


def _individual_identifiers(identity, id_check):
    # Koywe consumes this same verified IdentityVerification value. Didit's
    # shared normalizer selects CPF (BR), CURP (MX), RUN (CL) and personal
    # number (CO), not the OCR card serial. Never replace it with raw OCR.
    from security.models import normalize_brazilian_cpf
    country = iso_alpha2(identity.document_issuing_country)
    number = _required(identity.document_number, 'verified identity/tax identifier')
    number = str(number).strip().upper()
    _required(number, 'verified identity/tax identifier')
    result = {'tax_id_country': country}
    if country == 'BR' and identity.document_type != 'passport':
        # A Brazilian passport carries a passport number, not a CPF.
        if (getattr(identity, 'brazilian_cpf_database_validation_present', False)
                and not getattr(identity, 'brazilian_cpf_database_validation_valid', False)):
            raise ComplianceHandoffError('Brazilian CPF database verification did not match')
        number = normalize_brazilian_cpf(number)
        _required(number, 'valid Brazilian CPF')
    elif country == 'MX' and identity.document_type != 'passport':
        if not re.fullmatch(r'[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d', number):
            raise ComplianceHandoffError('A verified Mexican CURP is required, not the card serial')
    elif country == 'CL' and identity.document_type != 'passport':
        compact = re.sub(r'[.\s-]', '', number)
        if not re.fullmatch(r'\d{7,8}[0-9K]', compact):
            raise ComplianceHandoffError('A verified Chilean RUN/RUT is required')
        number = f'{compact[:-1]}-{compact[-1]}'
    elif country == 'AR' and identity.document_type != 'passport':
        # Like MX/CL: a passport carries no DNI, so the DNI/CUIL pair is only
        # required for the national ID.
        # CUIL must be supplied separately; it cannot be inferred from DNI.
        extra = id_check.get('extra_fields') or {}
        if not isinstance(extra, dict):
            raise ComplianceHandoffError('Invalid Argentine identifier evidence')
        candidates = {re.sub(r'[\s-]', '', str(v)) for v in (
            id_check.get('additional_tax_id'), extra.get('additional_tax_id'), extra.get('cuil'),
        ) if v not in (None, '')}
        if len(candidates) != 1:
            raise ComplianceHandoffError('A unique verified Argentine CUIL is required')
        cuil = candidates.pop()
        if not re.fullmatch(r'\d{7,8}', number) or not re.fullmatch(r'\d{11}', cuil):
            raise ComplianceHandoffError('Verified Argentine DNI and CUIL are required')
        check = (11 - sum(int(n) * w for n, w in zip(cuil[:10], [5,4,3,2,7,6,5,4,3,2])) % 11) % 11
        if check > 9 or check != int(cuil[-1]) or cuil[2:10] != number.zfill(8):
            raise ComplianceHandoffError('Argentine CUIL does not validate against DNI')
        result['additional_tax_id'] = cuil
    result['tax_id'] = number
    return result


def _volume_fields(decision):
    answers = (_reviewed_answers(decision, BUSINESS_QUESTIONNAIRE_ID, BUSINESS_WORKFLOW_ID)
               if decision.get('session_kind') == 'business' else {})
    value = (answers.get('expected_monthly_volume_usd', {}).get('value')
             if answers else decision.get('expected_monthly_volume_usd'))
    if answers:
        _required(value, 'expected monthly USD volume')
    if value is None:
        return {}
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ComplianceHandoffError('Invalid expected monthly USD volume') from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal('1e15'):
        raise ComplianceHandoffError('Invalid expected monthly USD volume')
    return {'expected_monthly_volume_usd': float(amount)}


def _declared_address(user):
    """The account owner's self-declared ramp address — the one Koywe uses."""
    from ramps.schema import _build_effective_ramp_address_snapshot
    return _build_effective_ramp_address_snapshot(user)


def _individual_payload(*, decision, identity, user, client, declared_address=None):
    if str(decision.get('status') or '').strip().lower() != 'approved':
        raise ComplianceHandoffError('Approved Didit KYC is required for each individual, including UBOs')
    if decision.get('session_kind') not in (None, '', 'user'):
        raise ComplianceHandoffError('A personal Infinia owner requires a Didit KYC session')
    # security.didit normalizes the FIRST ID check. Never combine that identity
    # with another check's images or supplementary identifiers.
    checks = decision.get('id_verifications') or []
    id_check = checks[0] if isinstance(checks, list) and checks and isinstance(checks[0], dict) else {}
    liveness = _approved_first(decision.get('liveness_checks'))
    if any(str(check.get('status') or '').strip().lower() != 'approved' for check in (id_check, liveness)):
        raise ComplianceHandoffError('Approved Didit identity and liveness checks are required')
    document_type = _document_type(id_check.get('document_type') or identity.document_type)
    answers = (_reviewed_answers(decision, PERSON_QUESTIONNAIRE_ID, PERSON_WORKFLOW_ID)
               if user is None else {})
    if answers and iso_alpha2(identity.document_issuing_country) == 'AR' and identity.document_type != 'passport':
        # The reviewed answer is only supplementary evidence when an official
        # tax document was attached. Bare self-declared CUIL is never enough.
        cuil = answers.get('additional_tax_id', {}).get('value')
        if cuil and _answer_files(answers, 'tax_id_evidence'):
            previous = id_check.get('additional_tax_id')
            if previous and re.sub(r'[\s-]', '', str(previous)) != re.sub(r'[\s-]', '', str(cuil)):
                raise ComplianceHandoffError('Conflicting Argentine CUIL evidence')
            id_check = {**id_check, 'additional_tax_id': cuil}
    identifiers = _individual_identifiers(identity, id_check)
    volume = _volume_fields(decision)
    email, phone = _verified_contact(decision) if answers else _contact(decision, user)
    if declared_address is not None:
        # The account owner: many LATAM cédulas/DNIs carry no address, so use
        # the same self-declared ramp address Koywe uses (country from the
        # phone). Proof of address is an EDD document, not an opening one.
        declared = declared_address
        line_1 = ', '.join(part for part in (
            (declared.address_street or '').strip(), (declared.address_neighborhood or '').strip()) if part)
        try:
            address = _address(
                line_1=line_1,
                city=declared.address_city,
                state=declared.address_state,
                postal_code=declared.address_zip_code,
                country=declared.address_country,
            )
        except (ComplianceHandoffError, ValueError) as exc:
            raise ComplianceHandoffError('Completa tu dirección para abrir tu cuenta local.') from exc
    elif answers:
        poa = _approved_first(decision.get('poa_verifications'))
        if str(poa.get('status') or '').lower() != 'approved':
            raise ComplianceHandoffError('An approved proof of address is required for the UBO')
        _required(poa.get('document_file'), 'UBO proof of address document')
        address = _questionnaire_address(answers, 'residential_address')
    else:
        # A UBO is a different person: only their own verified data, never
        # the account owner's declared address.
        address = _address(
            line_1=identity.verified_address,
            city=identity.verified_city,
            state=identity.verified_state,
            postal_code=identity.verified_postal_code,
            country=identity.verified_country,
        )
    _required(identity.verified_first_name, 'first name')
    _required(identity.verified_last_name, 'last name')
    dob = _required(identity.verified_date_of_birth, 'date of birth').isoformat()
    front_url = id_check.get('full_front_image') or id_check.get('front_image')
    back_url = id_check.get('full_back_image') or id_check.get('back_image')
    selfie_url = liveness.get('reference_image')
    _required(selfie_url, 'liveness reference image')
    identity_document_id, identity_audit = _upload_document(
        client,
        document_type=document_type,
        front_url=_required(front_url, 'identity document image'),
        back_url=back_url,
    )
    selfie_document_id, selfie_audit = _upload_document(
        client,
        document_type='SELFIE',
        front_url=_required(selfie_url, 'liveness reference image'),
    )
    payload = {
        'first_name': identity.verified_first_name,
        'last_name': identity.verified_last_name,
        'date_of_birth': dob,
        **identifiers,
        **volume,
        'email': email,
        'phone_number': phone,
        'address': address,
        'identity_document_id': identity_document_id,
        'selfie_document_id': selfie_document_id,
    }
    documents, audits = _supporting_documents(decision, client, {
        'source_of_funds': ('SOURCE_OF_FUNDS', 'source_of_funds_document_id'),
        'financial_statements': ('SOURCE_OF_FUNDS', 'source_of_funds_document_id'),
        'proof_of_address': ('PROOF_OF_ADDRESS', 'proof_of_address_document_id'),
    })
    if answers:
        poa_id, poa_audit = _upload_document(client, document_type='PROOF_OF_ADDRESS',
                                            front_url=poa['document_file'])
        documents['proof_of_address_document_id'] = poa_id
        audits.append(poa_audit)
        tax_urls = _answer_files(answers, 'tax_id_evidence')
        if tax_urls:
            tax_id, tax_audit = _upload_bundle(client, document_type='TAX_REGISTRATION', urls=tax_urls)
            documents['other_documents'] = [tax_id]
            audits.append(tax_audit)
    payload.update(documents)
    return payload, [identity_audit, selfie_audit, *audits]


BUSINESS_DOCUMENT_MAP = {
    'certificate_of_incorporation': ('CERTIFICATE_OF_INCORPORATION', 'incorporation_document_id'),
    'source_of_funds': ('SOURCE_OF_FUNDS', 'source_of_funds_document_id'),
    'financial_statements': ('SOURCE_OF_FUNDS', 'source_of_funds_document_id'),
    'proof_of_address': ('PROOF_OF_ADDRESS', 'proof_of_address_document_id'),
    'ownership_structure': ('OWNERSHIP_STRUCTURE', 'ownership_structure_document_id'),
    'tax_registration': ('TAX_REGISTRATION', 'tax_registration_document_id'),
    'corporate_org_chart': ('CORPORATE_ORG_CHART', 'corporate_org_chart_document_id'),
}


def _supporting_documents(decision, client, mapping):
    # Every approved file, grouped by the owner field it fills: Infinia keeps
    # one document per field, so several files for one field go as one PDF.
    groups = {}
    for check in decision.get('document_verifications') or []:
        for item in check.get('items') or []:
            if str(item.get('status') or '').strip().lower() != 'approved':
                continue
            matched = next(
                (mapping[value] for field in ('document_subtype', 'document_type', 'document_group')
                 if (value := str(item.get(field) or '').strip().lower()) in mapping),
                None,
            )
            if not matched:
                continue
            document_type, owner_field = matched
            groups.setdefault(owner_field, (document_type, []))[1].append(
                _required(item.get('file_url'), 'supporting document file URL'))
    fields = {}
    audits = []
    for owner_field, (document_type, urls) in groups.items():
        document_id, audit = _upload_bundle(client, document_type=document_type, urls=urls)
        fields[owner_field] = document_id
        audits.append(audit)
    return fields, audits


def _business_documents(decision, client):
    answers = _reviewed_answers(decision, BUSINESS_QUESTIONNAIRE_ID, BUSINESS_WORKFLOW_ID)
    extra_items = []
    for element, kind in (
        ('source_of_funds_document', 'source_of_funds'),
        ('proof_of_address_document', 'proof_of_address'),
        ('tax_registration_document', 'tax_registration'),
    ):
        urls = _answer_files(answers, element)
        if answers:
            _required(urls, element)
        extra_items.extend({'status': 'Approved', 'document_type': kind, 'file_url': url} for url in urls)
    combined = {**decision, 'document_verifications': [
        *(decision.get('document_verifications') or []), {'items': extra_items}]}
    fields, audits = _supporting_documents(combined, client, BUSINESS_DOCUMENT_MAP)
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
    # Match the first registry result used by security.didit's identity normalizer.
    registry = _first(decision.get('registry_checks'))
    if str(registry.get('status') or '').strip().lower() != 'approved':
        raise ComplianceHandoffError('An approved business registry check is required')
    return _required(registry.get('company'), 'approved business registry result')


def _organization_payload(*, decision, identity, user, client, child_decisions):
    if decision.get('session_kind') != 'business':
        raise ComplianceHandoffError('A business Infinia owner requires a Didit KYB session')
    company = _company(decision)
    answers = _reviewed_answers(decision, BUSINESS_QUESTIONNAIRE_ID, BUSINESS_WORKFLOW_ID)
    email, phone = _verified_contact(decision) if answers else _contact(decision, None)
    address_data = _first(company.get('addresses'))
    address = _questionnaire_address(answers, 'company_address') if answers else _address(
        line_1=address_data.get('address') or address_data.get('line_1') or company.get('registered_address'),
        city=address_data.get('city'),
        state=address_data.get('state') or address_data.get('region'),
        postal_code=address_data.get('postal_code'),
        country=address_data.get('country_code') or company.get('country_code'),
    )
    name = _required(company.get('company_name'), 'company name')
    incorporated = _required(company.get('incorporation_date'), 'incorporation date')
    tax_id = _required(company.get('tax_number'), 'company tax ID (registration number is not a substitute)')
    tax_country = iso_alpha2(_required(company.get('country_code'), 'company country'))
    volume = _volume_fields(decision)
    for check in decision.get('key_people_checks') or []:
        if answers and str(check.get('status') or '').lower() != 'approved':
            raise ComplianceHandoffError('An approved key people check is required')
    parties = didit_ubo_parties(decision)
    if not parties:
        raise ComplianceHandoffError('Natural-person UBO disclosure is required before Infinia onboarding')
    document_fields, audits = _business_documents(decision, client)
    ubos = []
    seen = set()
    for party in parties:
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
            user=None,  # A UBO's contact cannot fall back to the account owner.
            client=client,
        )
        ubos.append(ubo)
        audits.extend(ubo_audits)
    summary = _first(decision.get('key_people_checks')).get('ubo_kyc_summary') or {}
    if int(summary.get('total') or 0) and len(ubos) != int(summary.get('total')):
        raise ComplianceHandoffError('All Didit UBO KYC sessions must be approved and transferable')
    payload = {
        'name': name,
        'date_of_incorporation': incorporated,
        'tax_id': tax_id,
        'tax_id_country': tax_country,
        'email': email,
        'phone_number': phone,
        'address': address,
        'ultimate_beneficial_owners': ubos,
        **volume,
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
            declared_address=_declared_address(profile.confio_account.user),
        )
        typed = {'individual': details}
    return {
        'type': 'ORGANIZATION' if profile.owner_type == 'business' else 'INDIVIDUAL',
        'kyc_mode': 'SELF_DECLARED',
        'idempotency_key': str(profile.internal_id),
        **typed,
    }, audits
