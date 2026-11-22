"""What a person finishes right in the chat, with no other screen.

On builds whose Inicio is the conversation, an answer can leave a card whose
button does the thing on the person's own phone: it opens WhatsApp with
their invitation, shares their @usuario, changes that @usuario, turns a kind
of notification on or off, names the pet or opens its picker, switches who
may write to them or whether their investor profile is public, or registers
who invited them. The assistant only proposes: nothing changes
until the person taps, and the change itself is made by the app with the
same mutations its screens use (so every rule those enforce still applies).

An action is `{'type': 'do', 'target': '<key>[:<argument>]', 'label': ...}`.
Builds that predate it ignore the type; the tools are not offered to them.

Details that have to be typed (a contact's phone, cédula and bank; a name)
are typed by the person into a short form under the answer (`ask_details`,
an action `{'type': 'form', 'target': '<key>', 'label': ...}`): they go from
the phone straight to the app's own mutation. The assistant never receives
them and never fills them in, so a number it misread can never be saved or
paid.
"""
from .prompts import conversation_home

# Opened on the phone, nothing stored: (label, what the model is told it does).
SHARE_ACTIONS = {
    'invite_whatsapp': ('Invitar por WhatsApp',
                        'abre WhatsApp con la invitación de la persona (su enlace y su código); ella elige a quién '
                        'enviarla'),
    'share_username': ('Compartir mi usuario',
                       'abre el menú de compartir del teléfono con su @usuario, para que otra persona con Confío le '
                       'envíe dinero'),
}
# Push notifications a person may switch from the chat: key -> (model field, how it is said).
# Security alerts are not here: they are changed on their own screen only.
NOTIFICATIONS = {
    'all': ('push_enabled', 'todas las notificaciones'),
    'transactions': ('push_transactions', 'los avisos de movimientos de tu dinero'),
    'p2p': ('push_p2p', 'los avisos de intercambios P2P'),
    'promotions': ('push_promotions', 'los avisos de promociones'),
    'announcements': ('push_announcements', 'los anuncios de Confío'),
    # The list of notices inside the app (the bell), not the phone's alerts.
    'in_app': ('in_app_enabled', 'las notificaciones dentro de la app (la campana)'),
}
# The person's own switches in Comunidad: key -> how it is said.
PRIVACY = {
    'messages': 'recibir mensajes de personas nuevas (sus conversaciones siguen)',
    'investor_profile': 'que su perfil de inversor (lo que tiene invertido) sea público en Comunidad',
}
PET_NAME_MAX = 24
# Forms the person fills in right in the conversation: key -> (the card's
# title, what the model is told it is for, Venezuela only).
FORMS = {
    'profile_name': ('Cambiar mi nombre', 'cambiar su nombre o su apellido (solo antes de verificar su identidad: '
                                          'después el nombre es el del documento y no se cambia)', False),
    'agenda_pagomovil': ('Guardar un contacto de Pago Móvil',
                         'guardar en su Agenda a alguien a quien le envía por Pago Móvil (teléfono, cédula, banco)',
                         True),
    # A top-up created here (assistant/topup_limits.py says where it is offered).
    'topup': ('Recargar',
              'crear una recarga con su banco local aquí mismo: escribe cuánto paga en su moneda, elige cómo paga, ve '
              'cuánto recibe y la crea; las instrucciones para pagar quedan en la conversación', False),
    'investor_bio': ('Escribir mi descripción',
                     'escribir o cambiar la descripción de su perfil de inversor en Comunidad (una línea, hasta 140 '
                     'caracteres, sin enlaces; se revisa antes de guardarse)', False),
    'pagomovil_payment': ('Enviar por Pago Móvil',
                          'enviar por Pago Móvil a alguien que todavía no tiene guardado: escribe a quién y cuánto, '
                          'queda guardado en su Agenda y aparece el pago para revisar y aprobar', True),
}
TOOLS = {'act_here', 'propose_username', 'notification_settings', 'ask_details', 'customize_pet',
         'privacy_settings', 'propose_referrer'}
_NOT_YET = ('Todavía no cambió nada: quedó un botón bajo tu respuesta y el cambio se hace cuando la persona lo toca. '
            'Dile que lo toque; no digas que ya está hecho.')


def _personal_owner(viewer) -> bool:
    return viewer.account_type in ('personal', 'smart') and not viewer.is_employee


def forms_for(viewer, belt=None):
    """The forms this person can be handed."""
    if not _personal_owner(viewer):
        return []
    # A verified person's name is the verified one: it can no longer be
    # changed (users.schema.UpdateUserProfile refuses it), so no form for it.
    keys = [] if getattr(viewer.user, 'is_identity_verified', False) else ['profile_name']
    keys.append('investor_bio')
    if belt is not None:
        from . import topup_limits
        if topup_limits.offered(belt):
            keys.append('topup')
    try:
        from security.geo import country_of
        if (country_of(viewer.user) or '').upper() == 'VE':
            keys.append('agenda_pagomovil')
            from ramps import ve_pagomovil
            ready = getattr(belt, 'payments_ready', None)
            if (ready is not None and ready() and ve_pagomovil.enabled(ve_pagomovil.SEND)
                    and ve_pagomovil.client_supports(ve_pagomovil.SEND, viewer.request_meta or {})):
                keys.append('pagomovil_payment')
    except Exception:  # noqa: BLE001 - a form not offered, never a failed turn
        import logging
        logging.getLogger(__name__).warning('here: forms unavailable', exc_info=True)
    return keys


def specs(viewer, belt=None):
    """The tools this viewer gets; none outside the conversation home."""
    if not conversation_home(viewer.request_meta) or getattr(viewer, 'user', None) is None:
        return []
    out = [{
        'type': 'function',
        'name': 'notification_settings',
        'description': ('Lee qué notificaciones tiene activas la persona y, si pide prender o apagar alguna, deja un '
                        'botón en la conversación que lo hace al tocarlo. Sin `setting` solo lee. Opciones: '
                        + '; '.join(f'{key}: {said}' for key, (_field, said) in NOTIFICATIONS.items())
                        + '. Las alertas de seguridad no se cambian desde el chat.'),
        'parameters': {
            'type': 'object',
            'properties': {'setting': {'type': ['string', 'null'], 'enum': [*NOTIFICATIONS, None]},
                           'enabled': {'type': ['boolean', 'null']}},
            'required': ['setting', 'enabled'],
            'additionalProperties': False,
        },
        'strict': True,
    }, {
        'type': 'function',
        'name': 'customize_pet',
        'description': ('Tu propio aspecto y nombre en esta app (la mascota de la persona). Con `name`: deja un '
                        'botón que te pone ese nombre al tocarlo (úsalo solo con el nombre que la persona '
                        f'escribió, hasta {PET_NAME_MAX} caracteres). Sin `name`: deja un botón que abre aquí '
                        'mismo el selector, donde elige el personaje (Confi, llama, capibara, gato, perro), el '
                        'color, o crea uno propio desde una foto o una idea.'),
        'parameters': {
            'type': 'object',
            'properties': {'name': {'type': ['string', 'null']}},
            'required': ['name'],
            'additionalProperties': False,
        },
        'strict': True,
    }]
    if _personal_owner(viewer):
        out += [{
            'type': 'function',
            'name': 'privacy_settings',
            'description': ('Lee los interruptores de la persona en Comunidad y, si pide cambiar uno, deja un botón '
                            'que lo hace al tocarlo. Sin `setting` solo lee. Opciones: '
                            + '; '.join(f'{key}: {said}' for key, said in PRIVACY.items()) + '.'),
            'parameters': {
                'type': 'object',
                'properties': {'setting': {'type': ['string', 'null'], 'enum': [*PRIVACY, None]},
                               'enabled': {'type': ['boolean', 'null']}},
                'required': ['setting', 'enabled'],
                'additionalProperties': False,
            },
            'strict': True,
        }, {
            'type': 'function',
            'name': 'propose_referrer',
            'description': ('Cuando la persona dice quién la invitó a Confío: revisa ese @usuario y, si se puede, '
                            'deja un botón que lo registra al tocarlo. Se registra una sola vez y después no se '
                            'cambia. Solo con el @usuario que la persona escribió.'),
            'parameters': {
                'type': 'object',
                'properties': {'username': {'type': 'string'}},
                'required': ['username'],
                'additionalProperties': False,
            },
            'strict': True,
        }, {
            'type': 'function',
            'name': 'act_here',
            'description': ('Deja en la conversación un botón que hace eso aquí mismo, en el teléfono de la persona, '
                            'sin abrir otra pantalla. Úsalo cuando quiera hacerlo ahora. Opciones: '
                            + '; '.join(f'{key}: {does}' for key, (_label, does) in SHARE_ACTIONS.items()) + '.'),
            'parameters': {
                'type': 'object',
                'properties': {'action': {'type': 'string', 'enum': list(SHARE_ACTIONS)}},
                'required': ['action'],
                'additionalProperties': False,
            },
            'strict': True,
        }, {
            'type': 'function',
            'name': 'propose_username',
            'description': ('Revisa si un @usuario nuevo es válido y está libre y, si lo está, deja un botón que lo '
                            'cambia al tocarlo. El @usuario es también su código de invitación. Úsalo solo con el '
                            'nombre que la persona escribió; no inventes uno salvo que te pida ideas.'),
            'parameters': {
                'type': 'object',
                'properties': {'username': {'type': 'string'}},
                'required': ['username'],
                'additionalProperties': False,
            },
            'strict': True,
        }]
    forms = forms_for(viewer, belt)
    if forms:
        out.append({
            'type': 'function',
            'name': 'ask_details',
            'description': ('Deja bajo tu respuesta un formulario corto para que la persona escriba ella misma los '
                            'datos, aquí en el chat. Úsalo cuando haga falta escribir datos para: '
                            + '; '.join(f'{key}: {FORMS[key][1]}' for key in forms)
                            + '. No le pidas que te dicte esos datos a ti ni los repitas: los escribe en el '
                              'formulario y de ahí van directo a su cuenta.'),
            'parameters': {
                'type': 'object',
                'properties': {'form': {'type': 'string', 'enum': forms}},
                'required': ['form'],
                'additionalProperties': False,
            },
            'strict': True,
        })
    return out


def _add(belt, action):
    if action not in belt.result.actions:
        belt.result.actions.append(action)


def act_here(belt, action):
    if action not in SHARE_ACTIONS:
        return {'ok': False, 'error': 'acción desconocida'}
    label, does = SHARE_ACTIONS[action]
    _add(belt, {'type': 'do', 'target': action, 'label': label})
    return {'ok': True, 'boton': label,
            'nota': f'Quedó un botón bajo tu respuesta que {does}. Dile que lo toque. No digas que ya se envió.'}


def propose_username(belt, username):
    from users.models import User
    from users.validators import validate_username

    name = (username or '').strip().lstrip('@')
    valid, why = validate_username(name)
    if not valid:
        return {'ok': False, 'motivo': why}
    # The same checks as the app's own screen (users.schema.UpdateUsername),
    # which runs them again when the button is tapped.
    user = belt.viewer.user
    current = (getattr(user, 'username', '') or '')
    if name.lower() == current.lower():
        return {'ok': False, 'motivo': f'Su usuario ya es @{current}.'}
    if name.lower().startswith('inversor_'):
        return {'ok': False, 'motivo': 'Ese nombre de usuario está reservado.'}
    if User.objects.filter(username__iexact=name).exclude(pk=user.pk).exists():
        return {'ok': False, 'motivo': 'Ese nombre de usuario ya está en uso: propón otro.'}
    _add(belt, {'type': 'do', 'target': f'set_username:{name}', 'label': f'Usar @{name}'})
    return {'ok': True, 'libre': True, 'boton': f'Usar @{name}', 'nota': _NOT_YET
            + ' Recuérdale en una línea que su código de invitación cambia con el usuario.'}


def notification_settings(belt, setting=None, enabled=None):
    from notifications.models import NotificationPreference

    preferences, _created = NotificationPreference.objects.get_or_create(user=belt.viewer.user)
    current = {key: bool(getattr(preferences, field)) for key, (field, _said) in NOTIFICATIONS.items()}
    out = {'activas': {said: current[key] for key, (_field, said) in NOTIFICATIONS.items()},
           'seguridad': 'Las alertas de seguridad se cambian solo en la pantalla de avisos.'}
    if setting is None or enabled is None:
        return out
    if setting not in NOTIFICATIONS:
        return {**out, 'ok': False, 'error': 'opción desconocida'}
    said = NOTIFICATIONS[setting][1]
    if current[setting] == bool(enabled):
        return {**out, 'ok': False, 'motivo': f'Ya tiene {"activos" if enabled else "apagados"} {said}.'}
    label = f'{"Activar" if enabled else "Apagar"} {said}'
    # The card's own label is short; the full sentence is the model's to say.
    short = {'all': 'notificaciones', 'transactions': 'avisos de movimientos', 'p2p': 'avisos de P2P',
             'promotions': 'promociones', 'announcements': 'anuncios', 'in_app': 'avisos en la app'}[setting]
    _add(belt, {'type': 'do', 'target': f'set_notifications:{setting}={"on" if enabled else "off"}',
                'label': f'{"Activar" if enabled else "Apagar"} {short}'})
    return {**out, 'ok': True, 'boton': label, 'nota': _NOT_YET}


def customize_pet(belt, name=None):
    from . import service

    profile = service.profile_for(belt.viewer.user)
    current = profile.mascot_name or ''
    if name is None or not str(name).strip():
        _add(belt, {'type': 'do', 'target': 'customize_pet', 'label': 'Elegir mi mascota'})
        return {'ok': True, 'nombre_actual': current or None, 'boton': 'Elegir mi mascota',
                'nota': 'Quedó un botón bajo tu respuesta que abre el selector aquí mismo. Dile que lo toque.'}
    # As the app's own mutation cleans it (assistant.schema.UpdateAssistantProfile).
    clean = ' '.join(str(name).split())
    if len(clean) > PET_NAME_MAX:
        return {'ok': False, 'motivo': f'El nombre puede tener hasta {PET_NAME_MAX} caracteres: pide uno más corto.'}
    if clean == current:
        return {'ok': False, 'motivo': f'Ya te llamas {current}.'}
    _add(belt, {'type': 'do', 'target': f'set_pet_name:{clean}', 'label': f'Llamarte {clean}'})
    return {'ok': True, 'boton': f'Llamarte {clean}', 'nota': _NOT_YET}


def privacy_settings(belt, setting=None, enabled=None):
    from inbox import community, direct_messages
    from inbox.models import CommunityProfileSettings

    user = belt.viewer.user
    public = not community.portfolio_hidden(user)
    current = {'messages': direct_messages.dms_enabled(user), 'investor_profile': public}
    out = {'ahora': {'recibe mensajes de personas nuevas': current['messages'],
                     'perfil de inversor público': current['investor_profile']}}
    if setting is None or enabled is None:
        return out
    if setting not in PRIVACY:
        return {**out, 'ok': False, 'error': 'opción desconocida'}
    enabled = bool(enabled)
    if current[setting] == enabled:
        return {**out, 'ok': False, 'motivo': 'Ya está así: no hay nada que cambiar.'}
    if setting == 'messages':
        label = 'Recibir mensajes nuevos' if enabled else 'No recibir mensajes nuevos'
        _add(belt, {'type': 'do', 'target': f'set_messages:{"on" if enabled else "off"}', 'label': label})
        return {**out, 'ok': True, 'boton': label, 'nota': _NOT_YET}
    if not enabled:
        # The same lock the app's switch has (inbox.community.set_portfolio_hidden),
        # which is checked again when the button is tapped.
        from django.utils import timezone
        shown = (CommunityProfileSettings.objects.filter(user=user)
                 .values_list('portfolio_published_at', flat=True).first())
        if shown and timezone.now() - shown < community.REPUBLISH_LOCK:
            return {**out, 'ok': False, 'motivo': community.REPUBLISH_LOCK_MESSAGE}
    label = 'Hacer público mi perfil' if enabled else 'Ocultar mi perfil de inversor'
    _add(belt, {'type': 'do', 'target': f'set_investor_profile:{"public" if enabled else "hidden"}', 'label': label})
    note = _NOT_YET
    if enabled:
        note += (' Antes de que lo toque dile en una línea que, una vez público, no podrá ocultarlo de nuevo '
                 'durante 24 horas, y que solo se ve el perfil de quien verificó su identidad.')
    else:
        # What the app's own confirmation says before hiding.
        note += (' Antes de que lo toque dile en una o dos líneas qué pasa al ocultarlo: nadie verá su rentabilidad '
                 'ni sus posiciones, ella tampoco podrá ver las de otros inversores (los portafolios son '
                 'recíprocos) y, si está en un equipo, saldrá de él y dejará de aparecer en la Liga. Puede volver '
                 'a hacerlo público cuando quiera.')
    return {**out, 'ok': True, 'boton': label, 'nota': note}


def propose_referrer(belt, username):
    import re

    from achievements.models import UserReferral
    from users.models import User

    user = belt.viewer.user
    # The same checks as the app's own mutation (users.referral_mutations.SetReferrer),
    # which runs them again when the button is tapped.
    existing = UserReferral.objects.filter(referred_user=user, deleted_at__isnull=True).first()
    if existing:
        return {'ok': False, 'motivo': f'Ya registró a @{existing.referrer_identifier}: se registra una sola vez.'}
    name = (username or '').strip().strip('*~ ').lstrip('@').strip('*~ ')
    if not re.fullmatch(r'[A-Za-z0-9_]{3,20}', name):
        return {'ok': False, 'motivo': 'Eso no es un @usuario (letras, números o guion bajo, de 3 a 20). Pídele el '
                                       '@usuario de quien la invitó: está en el perfil de esa persona en Confío.'}
    referrer = User.objects.filter(username__iexact=name).first()
    if referrer is None:
        return {'ok': False, 'motivo': f'No hay nadie con el usuario @{name}. Que lo revise con quien la invitó.'}
    if referrer.pk == user.pk:
        return {'ok': False, 'motivo': 'No puede registrarse a sí misma.'}
    label = f'Registrar a @{referrer.username}'
    _add(belt, {'type': 'do', 'target': f'set_referrer:{referrer.username}', 'label': label})
    return {'ok': True, 'boton': label,
            'nota': _NOT_YET + ' Recuérdale en una línea que se registra una sola vez y no se cambia después.'}


def ask_details(belt, form):
    if form not in forms_for(belt.viewer, belt):
        return {'ok': False, 'error': 'formulario no disponible'}
    title = FORMS[form][0]
    if any(a.get('type') == 'form' for a in belt.result.actions):
        return {'ok': False, 'error': 'Ya hay un formulario en esta respuesta: uno a la vez.'}
    _add(belt, {'type': 'form', 'target': form, 'label': title})
    return {'ok': True, 'formulario': title,
            'nota': ('Quedó un formulario bajo tu respuesta. Dile en una frase que escriba ahí los datos y toque el '
                     'botón. No le pidas los datos a ti ni digas que ya se guardó o se envió nada.')}


def call(belt, name, args):
    handler = {'act_here': act_here, 'propose_username': propose_username,
               'notification_settings': notification_settings, 'ask_details': ask_details,
               'customize_pet': customize_pet, 'privacy_settings': privacy_settings,
               'propose_referrer': propose_referrer}[name]
    return handler(belt, **args)
