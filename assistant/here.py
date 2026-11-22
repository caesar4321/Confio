"""What a person finishes right in the chat, with no other screen.

On builds whose Inicio is the conversation, an answer can leave a card whose
button does the thing on the person's own phone: it opens WhatsApp with
their invitation, shares their @usuario, changes that @usuario, or turns a
kind of notification on or off. The assistant only proposes: nothing changes
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
}
# Forms the person fills in right in the conversation: key -> (the card's
# title, what the model is told it is for, Venezuela only).
FORMS = {
    'profile_name': ('Cambiar mi nombre', 'cambiar su nombre o su apellido (solo antes de verificar su identidad: '
                                          'después el nombre es el del documento y no se cambia)', False),
    'agenda_pagomovil': ('Guardar un contacto de Pago Móvil',
                         'guardar en su Agenda a alguien a quien le envía por Pago Móvil (teléfono, cédula, banco)',
                         True),
    'pagomovil_payment': ('Enviar por Pago Móvil',
                          'enviar por Pago Móvil a alguien que todavía no tiene guardado: escribe a quién y cuánto, '
                          'queda guardado en su Agenda y aparece el pago para revisar y aprobar', True),
}
TOOLS = {'act_here', 'propose_username', 'notification_settings', 'ask_details'}
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
    }]
    if _personal_owner(viewer):
        out += [{
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
             'promotions': 'promociones', 'announcements': 'anuncios'}[setting]
    _add(belt, {'type': 'do', 'target': f'set_notifications:{setting}={"on" if enabled else "off"}',
                'label': f'{"Activar" if enabled else "Apagar"} {short}'})
    return {**out, 'ok': True, 'boton': label, 'nota': _NOT_YET}


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
               'notification_settings': notification_settings, 'ask_details': ask_details}[name]
    return handler(belt, **args)
