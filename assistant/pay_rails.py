"""How a person pays in local money from this chat, from each rail's live switch.

Asked "¿cómo pago con Pix / SPEI / Bre-B / Pago Móvil / un QR?", the assistant
used to answer from prompt text that froze each rail's state (Bolivia's QR
"llegará muy pronto", Bre-B paused, Pix "sí se puede"). Here every rail's state
is read from the same switches the app and the payment code obey, per person and
per build, so the answer flips the moment ops switches a rail on or off:

  - Pix, SPEI, Bre-B, Argentina (CVU/CBU, QR): payment_accounts.local_money.rail_status
    (flags, LOCAL_MONEY_METHODS, eligibility rules such as the Bre-B partner pause,
    verified documents), plus payment_intents.word_rails() for a key typed in words.
  - Venezuela Pago Móvil: ramps.ve_pagomovil SEND switch and app floor.
  - Bolivia QR: ramps.bolivia_qr SEND switch, testers and app floor.
  - Peru (Yape, Plin, QR): not built, only its "Próximamente" waitlist.

What is ON is prepared here (prepare_payment, the Pago Móvil form, the QR button
beside the composer). What is OFF is said plainly, with what works instead and
the rail's waitlist (`notify_rail`), never a date.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60


@dataclass(frozen=True)
class PayRail:
    key: str
    country: str        # ISO-2
    name: str           # how it is said
    methods: tuple = ()  # payment_accounts.local_money.METHODS ids
    way: str = ''       # 'code' (paste or scan), 'words' (a key or account typed), 'form', 'scan'
    word_rail: str = ''  # payment_intents.WORD_RAILS id, for 'words'
    probe: str = ''     # users.models_rail_waitlist.KNOWN_RAIL_IDS ("Avísame")
    off_note: str = ''  # said when off, besides "no disponible por ahora"


RAILS = (
    PayRail('pix_code', 'BR', 'Pix con QR o código «Pix copia e cola»', ('br_qr',), 'code', probe='send_br_pix'),
    PayRail('pix_key', 'BR', 'Pix a una chave Pix', ('br_pix',), 'words', 'br_pix', 'send_br_pix'),
    PayRail('spei', 'MX', 'SPEI a una CLABE', ('mx_clabe',), 'words', 'mx_clabe', 'send_mx_clabe'),
    PayRail('breb_key', 'CO', 'Bre-B a una llave Bre-B', ('co_breb',), 'words', 'co_breb', 'send_co_breb'),
    PayRail('breb_qr', 'CO', 'un QR Bre-B', ('co_qr',), 'code', probe='send_co_breb'),
    PayRail('ar_cvu', 'AR', 'una transferencia a un CVU o CBU (22 dígitos; un alias de texto todavía no)',
            ('ar_cvu',), 'words', 'ar_cvu', 'send_ar_alias'),
    PayRail('ar_qr', 'AR', 'un QR interoperable de Argentina', ('ar_qr',), 'code', probe='send_ar_alias'),
    PayRail('pagomovil', 'VE', 'Pago Móvil (bolívares)', way='form', probe='send_ve_pagomovil'),
    PayRail('bo_qr', 'BO', 'un QR de bancos o billeteras de Bolivia', way='scan', probe='send_bo_qr',
            off_note='Pagar QR de bancos de Bolivia llegará muy pronto (sin fecha); hoy Pagar sirve para QR de cobro de '
                     'Confío.'),
    PayRail('pe_qr', 'PE', 'Yape, Plin o un QR de Perú', probe='send_pe_qr'),
)
BY_KEY = {rail.key: rail for rail in RAILS}

# What each state lets the assistant do, said to the model.
HOW = {
    'code': ('se hace aquí: que pegue en este chat el código o el texto del QR, o lo escanee con el botón de QR junto '
             'a donde escribe, y lo preparas con `prepare_payment` (rail null)'),
    'words': ('se hace aquí: que escriba en este chat {what} de quien recibe y lo preparas con `prepare_payment` '
              '(`{rail}`); el monto lo pregunta el servidor'),
    'form': 'se hace aquí: deja el formulario `ask_details` (`pagomovil_payment`); a alguien guardado, `prepare_payment` '
            '(`ve_pagomovil_send`)',
    'scan': 'se hace con el botón de QR junto a donde escribe (escanea el QR); no hay código que pegar',
}
WHAT = {'pix_key': 'la chave Pix', 'spei': 'la CLABE', 'breb_key': 'la llave Bre-B', 'ar_cvu': 'el CVU o CBU'}
STATES = {
    'verify': 'necesita verificar su identidad primero: deja la tarjeta de Verificación con `navigate`',
    'document': 'necesita otro documento de identidad para este medio (Verificación)',
    'update': 'está disponible, pero su versión de la app no lo tiene: que actualice Confío desde la tienda',
    'screen': 'está disponible en la app, pero no desde este chat: deja la tarjeta de Enviar con `navigate`',
    'not_for_you': 'no está disponible para su cuenta (país o nacionalidad): dilo sin dar más motivos',
    'paused': 'está en pausa por ahora, sin fecha',
    'off': 'no está disponible por ahora, sin fecha',
}
# Reasons of local_money.rail_status that mean "switched off" rather than "paused".
OFF_REASONS = frozenset({'not_enabled', 'policy_not_configured'})


def _infinia_state(rail, viewer, belt):
    from payment_accounts import local_money, payment_intents
    method = local_money.METHODS[rail.methods[0]]
    account = getattr(viewer, 'account', None)
    if account is None:
        return 'off'
    status, reason, _requirement = local_money.rail_status(account, payment_intents._identity(account), method)
    if status == 'needs_verification':
        return 'verify'
    if status == 'needs_document':
        return 'document'
    if status != 'live':
        if reason in local_money.IDENTITY_BLOCKED_REASONS or reason == local_money.REGION_UNSUPPORTED_REASON:
            return 'not_for_you'
        return 'off' if reason in OFF_REASONS else 'paused'
    if not (belt is not None and belt.payments_ready()):
        return 'screen'
    if rail.way == 'words' and rail.word_rail not in payment_intents.word_rails():
        return 'screen'
    return 'on'


def _pagomovil_state(viewer, belt):
    from ramps import ve_pagomovil
    if not ve_pagomovil.enabled(ve_pagomovil.SEND):
        return 'off'
    if not ve_pagomovil.client_supports(ve_pagomovil.SEND, viewer.request_meta or {}):
        return 'update'
    if viewer.account_type != 'personal':
        return 'not_for_you'
    return 'on' if belt is not None and belt.payments_ready() else 'screen'


def _bo_qr_state(viewer):
    from ramps import bolivia_qr
    user = viewer.user
    if not (bolivia_qr.enabled(bolivia_qr.SEND) or bolivia_qr.is_tester(user)):
        return 'off'
    if not bolivia_qr.client_supports(bolivia_qr.SEND, viewer.request_meta or {}):
        return 'update'
    return 'on' if viewer.account_type == 'personal' else 'not_for_you'


def state(rail, viewer, belt=None):
    """'on', 'verify', 'document', 'update', 'screen', 'not_for_you', 'paused' or 'off'. Unknown: 'off'
    is never claimed for a rail that might be on, so a failed read says nothing ('')."""
    try:
        if rail.methods:
            return _infinia_state(rail, viewer, belt)
        if rail.key == 'pagomovil':
            return _pagomovil_state(viewer, belt)
        if rail.key == 'bo_qr':
            return _bo_qr_state(viewer)
        return 'off'                       # not built: only its waitlist
    except Exception:  # noqa: BLE001 - unknown is no line, never a guess
        logger.warning('Confio Assistant: rail state unavailable for %s', rail.key, exc_info=True)
        return ''


def _line(rail, current, identity_needed=False):
    if current == 'on':
        how = HOW[rail.way].format(what=WHAT.get(rail.key, ''), rail=rail.word_rail)
        return f'- {rail.name} ({rail.country}): disponible; {how}.'
    text = STATES[current]
    extra = f' {rail.off_note}' if current in ('off', 'paused') and rail.off_note else ''
    probe = (' Ofrécele avisarle cuando esté («¿Te aviso cuando esté?») y, si dice que sí, llama `notify_rail` '
             f'(`{rail.key}`).') if current in ('off', 'paused') and rail.probe else ''
    return f'- {rail.name} ({rail.country}): {text}.{extra}{probe}'


def section(viewer, belt=None):
    """The prompt section: every rail's state for this person now. '' for business employees."""
    if viewer.user is None or getattr(viewer, 'is_employee', False):
        return ''
    from django.core.cache import cache
    meta = viewer.request_meta or {}
    key = (f'assistant:pay_rails:{viewer.user.pk}:{viewer.account_type}:'
           f'{meta.get("HTTP_X_CONFIO_VERSION", "")}:{meta.get("HTTP_X_CONFIO_HOME", "")}:'
           f'{int(bool(belt is not None and belt.payments_ready()))}')
    cached = cache.get(key)
    if cached is not None:
        return cached
    lines = []
    for rail in RAILS:
        current = state(rail, viewer, belt)
        if current:
            lines.append(_line(rail, current))
    text = ('\n# Pagar en moneda local: el estado de hoy de cada medio (lo dice el sistema, manda sobre las respuestas '
            'aprobadas)\nSi pregunta cómo pagar o enviar con uno de estos medios, o pega un código o quiere pagar un '
            'QR, sigue su línea. Lo que está disponible se hace en este chat: no abras ni dejes la pantalla de Enviar '
            'o Pagar para eso. Lo que no, dilo en una frase, con lo que sí puede hacer. Si quiere pagar un QR y el '
            'QR de su país no está disponible, díselo antes de nada (y que los QR de cobro de Confío sí se pagan con el '
            'botón de QR); no abras el escáner como si su QR se pudiera pagar.\n'
            + '\n'.join(lines) + '\n') if lines else ''
    cache.set(key, text, CACHE_SECONDS)
    return text


NOTIFY = 'notify_rail'


def notify_spec():
    return {
        'type': 'function',
        'name': NOTIFY,
        'description': ('Anota a la persona para avisarle cuando un medio de pago que hoy no está disponible se '
                        'abra («Sí, avísame»). Solo cuando ella lo pidió o dijo que sí a tu oferta de avisarle.'),
        'parameters': {'type': 'object',
                       'properties': {'rail': {'type': 'string', 'enum': [r.key for r in RAILS if r.probe]}},
                       'required': ['rail'], 'additionalProperties': False},
        'strict': True,
    }


def notify(belt, rail):
    """Join that rail's "Próximamente" waitlist, as its "Sí, avísame" does (users.rail_waitlist_schema)."""
    found = BY_KEY.get(rail)
    viewer = belt.viewer
    if found is None or not found.probe or viewer.user is None or getattr(viewer, 'is_employee', False):
        return {'ok': False, 'error': 'Ese medio no tiene lista de aviso.'}
    if state(found, viewer, belt) not in ('off', 'paused'):
        return {'ok': False, 'motivo': 'Ese medio ya está disponible o depende de otro paso: dile cómo usarlo.'}
    from users.models_rail_waitlist import KIND_COMING_SOON, LocalRailWaitlistEntry, parse_rail_id
    direction, country = parse_rail_id(found.probe)
    LocalRailWaitlistEntry.objects.get_or_create(
        user=viewer.user, rail_id=found.probe,
        defaults={'direction': direction, 'country': country, 'kind': KIND_COMING_SOON})
    return {'ok': True, 'nota': 'Quedó anotada: dile que le avisaremos cuando esté, sin fecha.'}


# The QR each country's people scan at a shop, for what Pagar's scanner can pay there.
COUNTRY_QR = {'BO': 'bo_qr', 'AR': 'ar_qr', 'CO': 'breb_qr', 'BR': 'pix_code'}


def scanner_note(viewer, belt=None):
    """When the scanner is opened for someone whose country's QR can't be paid now: the fact, for the reply.
    '' when it can, or when unknown."""
    try:
        from security.geo import country_of
        key = COUNTRY_QR.get((country_of(viewer.user) or '').upper()) if viewer.user is not None else None
        if not key:
            return ''
        rail = BY_KEY[key]
        current = state(rail, viewer, belt)
        if current in ('', 'on'):
            return ''
        return (f'Pagar {rail.name} hoy no se puede ({STATES[current]}). Dilo antes que nada: el escáner solo '
                'sirve para QR de cobro de Confío. No digas que confirme el pago de su QR.')
    except Exception:  # noqa: BLE001 - no note
        logger.warning('Confio Assistant: scanner note unavailable', exc_info=True)
        return ''
