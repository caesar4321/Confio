"""What Perfil → Verificación shows the person, for the assistant.

The identity line only says verified / pending / rejected, and the note that
explains it is about topping up, so it is left out where top-ups are paused
(Colombia). Asked "my documents are in review" or "it says a step is
missing", the assistant answered that it could not see the verification
(2026-11-24): a person who had been declined twice for an unaccepted
document was told to look for themselves.

Reasons come only from what the app already shows: `rejected_reason`
(security/didit.py: a reviewer's note to the person, or the retry hint from
user_facing_decline_reason, which stays empty when a fraud signal may be
behind the decline) and Didit's resubmission request. Raw Didit warnings
never reach the model.
"""
from datetime import timedelta
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

# How far back an earlier decline still explains a new, unfinished attempt.
EARLIER_DECLINE_DAYS = 30
GUIDANCE = ('Si pregunta por su verificación o por qué no avanza, explícale esto con tus palabras; nunca digas '
            'que no puedes ver su verificación. Si no hay un motivo concreto, sugiérele repetirla (deja la tarjeta '
            'de Verificación con `navigate`, `verification`) con su documento de identidad nacional o pasaporte, original y vigente, con buena luz y '
            'sin reflejos, y no adivines otro motivo.\n')


def _raw(doc):
    return str(((doc.risk_factors or {}).get('didit') or {}).get('raw_status') or '').strip().lower()


def _declined(doc):
    reason = (doc.rejected_reason or '').strip()
    if reason:
        return f'fue rechazado. Motivo que le muestra la app: «{reason}».'
    return 'fue rechazado, sin un motivo concreto en la app.'


def verification_note(viewer) -> str:
    user = getattr(viewer, 'user', None)
    if user is None or getattr(viewer, 'is_employee', False) or getattr(viewer, 'account_type', 'personal') != 'personal':
        return ''
    try:
        from security.identity_status import is_identity_verified, personal_documents

        from .suggestions import DIDIT_UNFINISHED, waits_on_review
        if is_identity_verified(user):
            return ''
        docs = list(personal_documents(user).order_by('-created_at')[:5])
        if not docs:
            return ''
        latest = docs[0]
        if latest.status == 'rejected':
            fact = 'Su último intento de verificación ' + _declined(latest)
        elif latest.status == 'pending' and latest.needs_person_action:
            fact = f'Didit le pide repetir un paso de su verificación: «{latest.action_detail}».'
        elif latest.status == 'pending' and waits_on_review(user):
            return ''  # the in-review note says it, and asks nothing of the person
        elif latest.status == 'expired' or (latest.status == 'pending' and _raw(latest) in DIDIT_UNFINISHED):
            fact = ('Empezó una verificación y no la terminó.' if latest.status == 'pending'
                    else f'Su última verificación no se completó: «{latest.status_detail}».')
            since = timezone.now() - timedelta(days=EARLIER_DECLINE_DAYS)
            earlier = next((d for d in docs[1:] if d.status == 'rejected' and d.created_at >= since), None)
            if earlier is not None:
                fact += ' Su intento anterior ' + _declined(earlier)
        else:
            return ''
        return f'Su verificación de identidad: {fact}\n' + GUIDANCE
    except Exception:  # noqa: BLE001 - unknown is no note, never a broken reply
        logger.warning('Confio Assistant: verification note unavailable', exc_info=True)
        return ''
