"""What the person wants Confío for, said in their own words.

Where the chat is Inicio, the first conversation asks it as an open question
(assistant/guide.py, step `opening_words`) instead of a row of chips. When
the person answers in a message, the model files what they wrote under the
same few keys the chips had (`note_first_use`), so the guide's next steps
and the numbers keep working; their words themselves stay where they wrote
them, in the conversation. Nothing is said about the note: the reply just
helps with what they asked.
"""
import logging

from .prompts import conversation_home
from .suggestions import GUIDE_ANSWERS, PROBE_ANSWERS, PROBE_ID

logger = logging.getLogger(__name__)

TOOL = 'note_first_use'
REASONS = {**dict(PROBE_ANSWERS), **dict(GUIDE_ANSWERS)}


def due(viewer) -> bool:
    """A person, in their own personal account, on a build whose Inicio is
    the chat, who has not said it yet."""
    if (getattr(viewer, 'user', None) is None or viewer.account_type != 'personal' or viewer.is_employee
            or not conversation_home(viewer.request_meta)):
        return False
    try:
        from .models import ProbeAnswer
        return not ProbeAnswer.objects.filter(user=viewer.user, probe_id=PROBE_ID).exists()
    except Exception:  # noqa: BLE001 - no tool is always safe
        logger.warning('Confio Assistant: first-use state unavailable', exc_info=True)
        return False


def spec():
    return {
        'type': 'function',
        'name': TOOL,
        'description': ('Esta persona todavía no ha contado para qué quiere usar Confío. Cuando en su mensaje lo '
                        'cuente (con sus palabras: "quiero ahorrar", "mandarle plata a mi mamá", "comprar '
                        'acciones"…), anota la opción que mejor lo resume, una sola vez, y sigue ayudándola con '
                        'eso. No le digas que lo anotaste. Si solo saluda, pregunta cómo empezar o qué puede hacer, '
                        'o pregunta otra cosa sin decir para qué la quiere, no la llames: "other" es solo para un '
                        'para qué que dijo y no cabe en las demás opciones. '
                        'Opciones: ' + '; '.join(f'{key}: {label}' for key, label in REASONS.items()) + '.'),
        'parameters': {
            'type': 'object',
            'properties': {'reason': {'type': 'string', 'enum': list(REASONS)}},
            'required': ['reason'],
            'additionalProperties': False,
        },
        'strict': True,
    }


def note(belt, reason):
    from . import guide
    from .suggestions import _state

    viewer = belt.viewer
    if reason not in REASONS:
        return {'ok': False, 'error': 'opción desconocida'}
    if not due(viewer):
        return {'ok': False, 'motivo': 'Ya estaba anotado.'}
    try:
        funded = bool(_state(viewer, viewer.request_meta).funded)
    except Exception:  # noqa: BLE001 - the note matters more than this column
        funded = False
    # As a tap on a chip of the opening step: the answer is stored once and
    # that step is done, so the guide moves on to what follows from it.
    from .suggestions import record_probe_answer
    record_probe_answer(viewer.user, PROBE_ID, reason, funded=funded)
    guide.record_event(viewer, 'opening_words', 'accepted', answer=reason, funded=funded, detail='words')
    return {'ok': True, 'nota': 'Anotado. No se lo menciones: ayúdala ahora con eso que quiere, con lo que la app tiene.'}
