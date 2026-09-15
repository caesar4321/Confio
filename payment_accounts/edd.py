"""Enhanced due diligence (EDD) through Didit: proof of address + source of funds.

The person answers the structured questions in the app (occupation is
prefilled from the economic activity they already declared for Recarga/
Retiro). Didit then collects and screens the documents in ONE session:
proof of address (name/address/age/tampering checks against the verified
name and the declared address) and a questionnaire with the source-of-funds
uploads. Completed submissions are automatically attached to the Infinia owner,
including sessions awaiting review: Infinia makes the EDD decision. No Confio
review or local limit increase is required. Incomplete or declined sessions
are never forwarded; failed handoffs are retried by the background reconciler.
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import LimitIncreaseRequest, ProviderProfile
from .services import PaymentAccountError

OPEN_STATUSES = ('started', 'submitted', 'in_review')
INCOME_TYPES = ('employed', 'self_employed', 'not_employed')
SOURCES = ('salary', 'business_income', 'savings', 'investments', 'family_support', 'other')
# Didit questionnaire 585211e7-b673-4cbb-a7a3-4857343dce95 element ids.
QUESTIONNAIRE_FILES = ('income_proof', 'bank_statements')
_DIDIT_TO_STATUS = {
    'approved': 'submitted',     # ready for automatic provider handoff
    'in review': 'in_review',
    'declined': 'rejected',
    'abandoned': 'started',
    'expired': 'started',
    'not started': 'started',
    'in progress': 'started',
}


def _primary_identity(owner):
    """The identity the provider owner was opened with (it can be an additional
    passport), else the primary verification, else any verified personal document."""
    from django.db.models import Q
    from security.models import IdentityVerification
    profile = ProviderProfile.objects.filter(confio_account=owner, provider='infinia').select_related(
        'identity_verification').first()
    if profile and profile.identity_verification and profile.identity_verification.status == 'verified':
        return profile.identity_verification
    # Not .exclude(account_type='business'): on a JSON key that also drops
    # every row where the key is missing, i.e. every personal identity.
    return (
        IdentityVerification.all_documents.filter(user=owner.user, status='verified')
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .order_by('is_additional_document', '-verified_at', '-updated_at').first()
    )


def _expected_details(owner, identity):
    """Cross-checks for proof of address: the verified name, the declared address."""
    from ramps.schema import _build_effective_ramp_address_snapshot, _is_ramp_address_complete
    declared = _build_effective_ramp_address_snapshot(owner.user)
    if not _is_ramp_address_complete(declared):
        raise PaymentAccountError('Completa tu dirección antes de pedir un límite mayor.')
    address = ', '.join(part for part in (
        declared.address_street, declared.address_neighborhood, declared.address_city,
        declared.address_state, declared.address_zip_code) if part)
    return {
        'first_name': identity.verified_first_name,
        'last_name': identity.verified_last_name,
        'address': address,
        'poa_country': declared.address_country,
    }


def start(owner, *, income_type, occupation, expected_monthly_usd, source_of_funds, callback_url=None):
    """Record the answers and open (or resume) the Didit EDD session."""
    if owner.account_type == 'business':
        raise PaymentAccountError('Para empresas, el aumento de límite lo revisamos contigo. Escríbenos a soporte.')
    if income_type not in INCOME_TYPES:
        raise PaymentAccountError('Elige cómo generas tus ingresos.')
    if source_of_funds not in SOURCES:
        raise PaymentAccountError('Elige el origen de tus fondos.')
    try:
        expected = Decimal(str(expected_monthly_usd)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentAccountError('Ingresa un monto válido.') from exc
    # The field holds 20 digits with 2 decimals: larger is an input error, not a database one.
    if not expected.is_finite() or expected <= 0 or expected >= Decimal('1000000000000000000'):
        raise PaymentAccountError('Ingresa un monto válido.')
    occupation = str(occupation or '').strip()[:120]
    if len(occupation) < 2:
        raise PaymentAccountError('Cuéntanos a qué te dedicas.')
    identity = _primary_identity(owner)
    if identity is None:
        raise PaymentAccountError('Verifica tu identidad antes de pedir un límite mayor.')
    workflow_id = getattr(settings, 'DIDIT_EDD_WORKFLOW_ID', '') or ''
    if not workflow_id:
        raise PaymentAccountError('La revisión de límites no está disponible por ahora.')
    expected_details = _expected_details(owner, identity)

    with transaction.atomic():
        row = LimitIncreaseRequest.objects.select_for_update().filter(
            confio_account=owner, status__in=OPEN_STATUSES).first()
        if row and row.status != 'started':
            raise PaymentAccountError('Ya tienes una solicitud en revisión.')
        answers = dict(income_type=income_type, occupation=occupation, expected_monthly_usd=expected,
                       source_of_funds=source_of_funds)
        try:
            if row:
                for field, value in answers.items():
                    setattr(row, field, value)
                row.save(update_fields=[*answers, 'updated_at'])
            else:
                row = LimitIncreaseRequest.objects.create(confio_account=owner, provider='infinia', **answers)
        except IntegrityError as exc:
            raise PaymentAccountError('Ya tienes una solicitud en revisión.') from exc

    from security.didit import DiditAPIError, DiditConfigurationError, create_didit_workflow_session
    # A stable per-request reference resumes this request, while a later
    # evidence update gets a fresh session even if the old one awaits review.
    try:
        session = create_didit_workflow_session(
            user=owner.user, workflow_id=workflow_id, expected_details=expected_details,
            session_reference=str(row.internal_id),
            metadata={'purpose': 'edd', 'request': str(row.internal_id)}, callback_url=callback_url, language='es',
        )
    except (DiditAPIError, DiditConfigurationError) as exc:
        # The request stays 'started', so trying again resumes it.
        raise PaymentAccountError('No pudimos abrir la verificación. Intenta de nuevo en unos minutos.') from exc
    with transaction.atomic():
        # Re-read under the lock: ops may have closed this request (and a newer
        # one may have taken the session) while Didit was answering.
        row = LimitIncreaseRequest.objects.select_for_update().get(pk=row.pk)
        if row.status != 'started':
            raise PaymentAccountError('Tu solicitud cambió mientras la abríamos. Vuelve a intentarlo.')
        # Didit resumes this person's unfinished session, which an earlier
        # request that is no longer open (asked for more information, or closed)
        # may still hold: this request continues it. Never take it from an open one.
        LimitIncreaseRequest.objects.select_for_update().filter(
            confio_account=owner, didit_session_id=session['session_id'],
        ).exclude(pk=row.pk).exclude(status__in=(*OPEN_STATUSES, 'forwarded')).update(didit_session_id=None)
        row.didit_session_id = session['session_id']
        try:
            row.save(update_fields=['didit_session_id', 'updated_at'])
        except IntegrityError as exc:
            raise PaymentAccountError('No pudimos iniciar la verificación. Escríbenos a soporte.') from exc
    return row, session


def is_edd_session(session_id):
    return LimitIncreaseRequest.objects.filter(didit_session_id=str(session_id)).exists()


_EDD_MEDIA_KEYS = {'document_file', 'url'}


def _is_link(value):
    return isinstance(value, str) and value.lower().startswith(('http://', 'https://'))


def _edd_evidence(decision):
    """Didit facts without any document link. Presigned URLs (the proof of
    address `document_file`, questionnaire file `url`s) are credentials;
    forwarding reads a fresh decision, never this stored copy."""
    from security.didit import _without_transient_didit_media

    def strip(value):
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key not in _EDD_MEDIA_KEYS}
        if isinstance(value, list):
            return [strip(item) for item in value if not _is_link(item)]
        return '' if _is_link(value) else value
    return strip(_without_transient_didit_media(decision))


def sync_edd_session(session_id, *, expected_user=None, enqueue=True):
    from django.db import transaction
    from security.didit import retrieve_didit_decision
    # One sync per request at a time, from asking Didit to saving: the row is
    # locked first, so a later sync always records Didit's later answer (a
    # delayed Declined can never land after an Approved) and a reviewer's
    # decision made meanwhile is never overwritten.
    with transaction.atomic():
        row = LimitIncreaseRequest.objects.select_for_update(of=('self',)).select_related(
            'confio_account__user').get(didit_session_id=str(session_id))
        decision = retrieve_didit_decision(session_id=str(session_id),
                                           expected_user=expected_user or row.confio_account.user)
        didit_status = str(decision.get('status') or '').strip()
        mapped = _DIDIT_TO_STATUS.get(didit_status.lower())
        # A late answer from before submission (overlapping syncs) is stale: it
        # must neither move the request back to 'started' nor replace the
        # evidence of the later answer.
        if mapped == 'started' and row.status != 'started':
            return row
        row.didit_status = didit_status[:30]
        # Presigned media URLs are short-lived credentials; keep only the facts.
        row.evidence = _edd_evidence(decision)
        # Never walk a request back after it has been forwarded or closed.
        if mapped and row.status in ('started', 'submitted', 'in_review'):
            row.status = mapped
            if mapped in ('submitted', 'in_review') and row.submitted_at is None:
                row.submitted_at = timezone.now()
            if mapped == 'rejected' and not row.user_message:
                row.user_message = 'No pudimos validar tus documentos. Revisa que se lean bien y vuelve a intentarlo.'
        row.save(update_fields=['didit_status', 'evidence', 'status', 'submitted_at', 'user_message', 'updated_at'])
    if enqueue and row.status in ('submitted', 'in_review'):
        transaction.on_commit(lambda: _enqueue_handoff(row.pk), robust=True)
    return row


def _enqueue_handoff(request_id):
    from .tasks import forward_edd
    forward_edd.delay(request_id)


def _questionnaire_files(decision, element_id):
    urls = []
    for response in decision.get('questionnaire_responses') or []:
        for section in (response or {}).get('sections') or []:
            for item in (section or {}).get('items') or []:
                if not isinstance(item, dict) or item.get('value') != element_id:
                    continue
                answer = item.get('answer') if isinstance(item.get('answer'), dict) else {}
                for value in answer.get('files') or []:
                    url = value.get('url') if isinstance(value, dict) else value
                    if isinstance(url, str) and url:
                        urls.append(url)
    return urls


def _proof_of_address_file(decision):
    for check in decision.get('poa_verifications') or []:
        if isinstance(check, dict) and check.get('document_file'):
            return str(check['document_file'])
    return ''


def forward_to_provider(row, *, client=None):
    """Automatically attach completed EDD evidence to the provider owner.

    Reads a FRESH decision (media URLs expire), uploads the proof of address and
    every source-of-funds file (one PDF: the owner keeps one document per type) to the Infinia account owner, and marks the
    request forwarded. The limit itself is raised by the provider.
    """
    from .clients import InfiniaClient
    from .compliance import ComplianceHandoffError, _upload_bundle, _upload_document
    from security.didit import retrieve_didit_decision

    row.refresh_from_db()
    if row.status == 'forwarded':
        return row
    if row.status not in ('submitted', 'in_review'):
        raise PaymentAccountError('Only submitted requests can be forwarded')
    profile = ProviderProfile.objects.filter(
        confio_account=row.confio_account, provider=row.provider, status='active').first()
    if not profile or not profile.provider_owner_id:
        raise PaymentAccountError('The user has no active provider account owner yet')
    decision = retrieve_didit_decision(session_id=row.didit_session_id, expected_user=row.confio_account.user)
    if str(decision.get('status') or '').strip().lower() == 'declined':
        raise PaymentAccountError('Didit rechazó esta sesión: no se puede reenviar al proveedor.')
    if str(decision.get('status') or '').strip().lower() not in ('approved', 'in review'):
        raise PaymentAccountError('The EDD session is not submitted yet')
    proof_of_address = _proof_of_address_file(decision)
    file_groups = [_questionnaire_files(decision, element) for element in QUESTIONNAIRE_FILES]
    funds = [url for group in file_groups for url in group]
    if not proof_of_address or not all(file_groups):
        raise ComplianceHandoffError('The Didit EDD session is missing proof of address or source-of-funds files')
    client = client or InfiniaClient()
    # Uploading alone attaches nothing; linking them to the owner is the act.
    address_id, address_audit = _upload_document(client, document_type='PROOF_OF_ADDRESS', front_url=proof_of_address)
    funds_id, funds_audit = _upload_bundle(client, document_type='SOURCE_OF_FUNDS', urls=funds)
    with transaction.atomic():
        # A reviewer may have rejected the request during the calls above: the
        # link to the owner happens only for a request that is still eligible.
        row = LimitIncreaseRequest.objects.select_for_update().get(pk=row.pk)
        if row.status == 'forwarded':
            return row
        if row.status not in ('submitted', 'in_review'):
            raise PaymentAccountError('La solicitud cambió mientras se enviaba; revísala de nuevo.')
        individual = {
            'proof_of_address_document_id': address_id,
            'source_of_funds_document_id': funds_id,
        }
        if profile.kyc_mode == 'SELF_DECLARED':
            individual['expected_monthly_volume_usd'] = float(row.expected_monthly_usd)
        client.update_owner(profile.provider_owner_id, {'individual': individual})
        row.provider_documents = {
            'proof_of_address_document_id': address_id,
            'source_of_funds_document_id': funds_id,
            'audits': [address_audit, funds_audit],
            'source_of_funds_files': len(funds),
        }
        row.status = 'forwarded'
        row.forwarded_at = timezone.now()
        row.save(update_fields=['provider_documents', 'status', 'forwarded_at', 'updated_at'])
    return row
